from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError
from urllib.request import Request
from unittest.mock import patch

from wanxiang.app_updates import (
    GITHUB_API_HOST,
    GITHUB_DOWNLOAD_HOSTS,
    _AllowedRedirectHandler,
    _checksum_from_sidecar,
    _download_verified_setup,
    _has_install_space,
    _is_windows_pe,
    _read_releases,
    _release_for_update,
    UpdateCancelled,
)


def release(
    tag: str,
    version: str,
    *,
    with_checksum: bool = True,
    release_url: str | None = None,
) -> dict[str, object]:
    base = f"FLUKE-{version}-Setup.exe"
    prefix = f"https://github.com/linjiuyao2025/FLUKE/releases/download/{tag}"
    assets: list[dict[str, object]] = [
        {"name": base, "size": 4096, "browser_download_url": f"{prefix}/{base}"}
    ]
    if with_checksum:
        assets.append(
            {
                "name": f"{base}.sha256",
                "size": 90,
                "browser_download_url": f"{prefix}/{base}.sha256",
            }
        )
    return {
        "draft": False,
        "prerelease": "-preview." in tag,
        "tag_name": tag,
        "html_url": release_url
        or f"https://github.com/linjiuyao2025/FLUKE/releases/tag/{tag}",
        "assets": assets,
    }


def make_pe(
    *,
    machine: int = 0x8664,
    subsystem: int = 2,
    dll: bool = False,
    offset: int = 64,
    optional_size: int | None = None,
) -> bytes:
    magic = 0x10B if machine == 0x014C else 0x20B
    optional_size = optional_size or (224 if machine == 0x014C else 240)
    section_table = offset + 24 + optional_size
    data = bytearray(section_table + 40)
    data[:2] = b"MZ"
    data[0x3C:0x40] = offset.to_bytes(4, "little")
    data[offset : offset + 4] = b"PE\0\0"
    data[offset + 4 : offset + 6] = machine.to_bytes(2, "little")
    data[offset + 6 : offset + 8] = (1).to_bytes(2, "little")
    data[offset + 20 : offset + 22] = optional_size.to_bytes(2, "little")
    characteristics = 0x0002 | (0x2000 if dll else 0)
    data[offset + 22 : offset + 24] = characteristics.to_bytes(2, "little")
    optional = offset + 24
    data[optional : optional + 2] = magic.to_bytes(2, "little")
    data[optional + 56 : optional + 60] = (0x2000).to_bytes(4, "little")
    data[optional + 68 : optional + 70] = subsystem.to_bytes(2, "little")
    return bytes(data)


class Response(io.BytesIO):
    def __init__(
        self,
        body: bytes,
        url: str = "https://release-assets.githubusercontent.com/fluke-test",
    ) -> None:
        super().__init__(body)
        self.url = url

    def geturl(self) -> str:
        return self.url

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class InterruptedResponse(Response):
    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self._first_read = True

    def read(self, size: int = -1) -> bytes:
        if self._first_read:
            self._first_read = False
            return super().read(min(size, 64))
        raise OSError("synthetic interrupted transfer")


def download_release(installer: bytes) -> dict[str, object]:
    name = "FLUKE-0.1.2-Setup.exe"
    tag = "native-v0.1.2-preview.1"
    prefix = f"https://github.com/linjiuyao2025/FLUKE/releases/download/{tag}"
    sidecar = f"{hashlib.sha256(installer).hexdigest()}  {name}\n".encode("ascii")
    return {
        "tag": tag,
        "version": "0.1.2",
        "setupName": name,
        "setupSize": len(installer),
        "setupUrl": f"{prefix}/{name}",
        "checksumName": f"{name}.sha256",
        "checksumSize": len(sidecar),
        "checksumUrl": f"{prefix}/{name}.sha256",
        "_sidecar": sidecar,
    }


class AppUpdateCheck(unittest.TestCase):
    def test_selects_highest_complete_official_release(self) -> None:
        incomplete = release("native-v0.1.4-preview.1", "0.1.4", with_checksum=False)
        tampered_page = release(
            "v0.1.5", "0.1.5", release_url="https://example.com/releases/tag/v0.1.5"
        )
        found = _release_for_update(
            [
                release("native-v0.1.2-preview.4", "0.1.2"),
                release("v0.1.3", "0.1.3"),
                incomplete,
                tampered_page,
                release("native-v0.1.0-preview.1", "0.1.0"),
            ],
            "0.1.1",
        )
        self.assertEqual(found["tag"], "v0.1.3")
        self.assertEqual(
            found["releaseUrl"],
            "https://github.com/linjiuyao2025/FLUKE/releases/tag/v0.1.3",
        )

    def test_release_selection_uses_semver_and_preview_channel_flags(self) -> None:
        items = [
            release("native-v0.1.3-preview.2", "0.1.3"),
            release("native-v0.1.3-preview.1", "0.1.3"),
            release("v0.1.3", "0.1.3"),
            {**release("v0.1.4", "0.1.4"), "prerelease": True},
        ]
        self.assertEqual(_release_for_update(items, "0.1.1")["tag"], "v0.1.3")
        self.assertIsNone(_release_for_update([release("v0.1.1", "0.1.1")], "0.1.1"))

    def test_release_api_reads_beyond_the_first_page(self) -> None:
        first_page = [release("v0.1.2", "0.1.2")] + [
            {"draft": True, "tag_name": f"unrelated-{index}"} for index in range(99)
        ]
        second_page = [release("v0.2.0", "0.2.0")]
        responses = [
            Response(
                json.dumps(first_page).encode(),
                f"https://{GITHUB_API_HOST}/repos/releases?page=1",
            ),
            Response(
                json.dumps(second_page).encode(),
                f"https://{GITHUB_API_HOST}/repos/releases?page=2",
            ),
        ]
        requested_urls: list[str] = []

        def open_page(request: Request, _hosts: set[str], timeout: int) -> Response:
            self.assertEqual(timeout, 25)
            requested_urls.append(request.full_url)
            return responses.pop(0)

        with patch("wanxiang.app_updates._open_github_url", side_effect=open_page):
            results = _read_releases()
        self.assertEqual(len(results), 101)
        self.assertEqual([url.rsplit("page=", 1)[1] for url in requested_urls], ["1", "2"])
        self.assertEqual(_release_for_update(results, "0.1.1")["tag"], "v0.2.0")

    def test_asset_and_release_urls_must_be_official_exact_paths(self) -> None:
        item = release("v0.1.2", "0.1.2")
        item["assets"][0]["browser_download_url"] = (
            "https://github.com@evil.example/linjiuyao2025/FLUKE/releases/download/v0.1.2/"
            "FLUKE-0.1.2-Setup.exe"
        )
        with self.assertRaisesRegex(ValueError, "官方 GitHub Release"):
            _release_for_update([item], "0.1.1")

    def test_redirects_allow_github_cdn_hosts_but_reject_untrusted_hops(self) -> None:
        handler = _AllowedRedirectHandler(GITHUB_DOWNLOAD_HOSTS)
        request = Request("https://github.com/linjiuyao2025/FLUKE/releases/download/v0.1.2/x")
        allowed = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://release-assets.githubusercontent.com/assets/abc",
        )
        self.assertIn("release-assets.githubusercontent.com", allowed.full_url)
        for url in (
            "https://evil.example/x",
            "http://release-assets.githubusercontent.com/x",
            "https://user@release-assets.githubusercontent.com/x",
            "https://release-assets.githubusercontent.com:443/x",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "Found", {}, url)

    def test_checksum_sidecar_is_single_line_and_names_the_expected_installer(self) -> None:
        name = "FLUKE-0.1.2-Setup.exe"
        digest = "ab" * 32
        self.assertEqual(_checksum_from_sidecar(f"{digest}  {name}\r\n".encode(), name), digest)
        self.assertEqual(_checksum_from_sidecar(digest.encode(), name), digest)
        for body in (
            f"{digest}  other.exe\n".encode(),
            f"{digest}  {name}\n{digest}  {name}\n".encode(),
            (" " + digest + "  " + name).encode(),
            (digest + "  " + name).encode("utf-8") + b"\xff",
            b"a" * 4097,
        ):
            with self.subTest(body=body[:24]), self.assertRaises(ValueError):
                _checksum_from_sidecar(body, name)

    def test_pe_check_rejects_signature_only_and_non_installer_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            valid = root / "valid.exe"
            valid.write_bytes(make_pe())
            self.assertTrue(_is_windows_pe(valid))

            spoof = root / "spoof.exe"
            spoof.write_bytes(b"MZ" + b"\0" * 58 + (64).to_bytes(4, "little") + b"PE\0\0")
            self.assertFalse(_is_windows_pe(spoof))

            dll = root / "dll.exe"
            dll.write_bytes(make_pe(dll=True))
            self.assertFalse(_is_windows_pe(dll))

            console = root / "console.exe"
            console.write_bytes(make_pe(subsystem=3))
            self.assertFalse(_is_windows_pe(console))

            bad_machine = root / "bad-machine.exe"
            bad_machine.write_bytes(make_pe(machine=0x1234))
            self.assertFalse(_is_windows_pe(bad_machine))

            oversized_header = root / "oversized-header.exe"
            oversized_header.write_bytes(make_pe(optional_size=5000))
            self.assertFalse(_is_windows_pe(oversized_header))

    def test_download_persists_only_matching_checksum_and_valid_pe(self) -> None:
        installer = make_pe()
        release_info = download_release(installer)
        sidecar = release_info.pop("_sidecar")
        with tempfile.TemporaryDirectory() as temporary:
            with patch(
                "wanxiang.app_updates._open_github_url",
                side_effect=[Response(sidecar), Response(installer)],
            ):
                path = _download_verified_setup(release_info, Path(temporary), lambda *_: None)
            self.assertEqual(path.read_bytes(), installer)
            self.assertTrue(_is_windows_pe(path))
            self.assertEqual(path.with_name(path.name + ".sha256").read_bytes(), sidecar)
            self.assertFalse(path.with_name(path.name + ".part").exists())
            self.assertFalse(path.with_name(path.name + ".sha256.part").exists())

    def test_bad_checksum_or_bad_pe_never_becomes_a_verified_download(self) -> None:
        installer = make_pe()
        release_info = download_release(installer)
        release_info.pop("_sidecar")
        name = release_info["setupName"]
        tag = release_info["tag"]
        bad_sidecar = f"{'0' * 64}  {name}\n".encode("ascii")
        with tempfile.TemporaryDirectory() as temporary:
            with patch(
                "wanxiang.app_updates._open_github_url",
                side_effect=[Response(bad_sidecar), Response(installer)],
            ):
                with self.assertRaisesRegex(ValueError, "SHA-256 校验失败"):
                    _download_verified_setup(release_info, Path(temporary), lambda *_: None)
            self.assertFalse((Path(temporary) / tag / name).exists())

        invalid_pe = b"MZ" + b"not an executable"
        invalid_release = download_release(invalid_pe)
        invalid_sidecar = invalid_release.pop("_sidecar")
        with tempfile.TemporaryDirectory() as temporary:
            with patch(
                "wanxiang.app_updates._open_github_url",
                side_effect=[Response(invalid_sidecar), Response(invalid_pe)],
            ):
                with self.assertRaisesRegex(ValueError, "Windows 安装程序"):
                    _download_verified_setup(invalid_release, Path(temporary), lambda *_: None)
            self.assertFalse((Path(temporary) / tag / name).exists())

    def test_cache_is_rechecked_for_pe_before_reuse(self) -> None:
        invalid_pe = b"MZ" + b"not a valid PE image"
        release_info = download_release(invalid_pe)
        sidecar = release_info.pop("_sidecar")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version_dir = root / release_info["tag"]
            version_dir.mkdir()
            cached = version_dir / release_info["setupName"]
            cached.write_bytes(invalid_pe)
            cached.with_name(cached.name + ".sha256").write_bytes(sidecar)
            with patch(
                "wanxiang.app_updates._open_github_url",
                side_effect=[Response(sidecar), Response(invalid_pe)],
            ) as open_asset:
                with self.assertRaisesRegex(ValueError, "Windows 安装程序"):
                    _download_verified_setup(release_info, root, lambda *_: None)
            self.assertEqual(
                open_asset.call_count,
                2,
                "invalid cached PE was downloaded again, not reused",
            )

    def test_interrupted_download_cleans_stale_and_partial_files(self) -> None:
        installer = make_pe()
        release_info = download_release(installer)
        sidecar = release_info.pop("_sidecar")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version_dir = root / release_info["tag"]
            version_dir.mkdir()
            target = version_dir / release_info["setupName"]
            target.with_name(target.name + ".part").write_bytes(b"stale installer part")
            target.with_name(target.name + ".sha256.part").write_bytes(b"stale sidecar part")
            with patch(
                "wanxiang.app_updates._open_github_url",
                side_effect=[Response(sidecar), InterruptedResponse(installer)],
            ):
                with self.assertRaisesRegex(OSError, "interrupted transfer"):
                    _download_verified_setup(release_info, root, lambda *_: None)
            self.assertFalse(target.with_name(target.name + ".part").exists())
            self.assertFalse(target.with_name(target.name + ".sha256.part").exists())
            self.assertFalse(target.exists())

    def test_user_cancel_cleans_partial_download(self) -> None:
        installer = make_pe()
        release_info = download_release(installer)
        sidecar = release_info.pop("_sidecar")
        with tempfile.TemporaryDirectory() as temporary:
            with patch(
                "wanxiang.app_updates._open_github_url",
                side_effect=[Response(sidecar), Response(installer)],
            ):
                with self.assertRaises(UpdateCancelled):
                    _download_verified_setup(
                        release_info,
                        Path(temporary),
                        lambda *_: None,
                        should_cancel=lambda: True,
                    )
            self.assertFalse((Path(temporary) / release_info["tag"] / release_info["setupName"]).exists())

    def test_install_space_preflight_blocks_when_disk_is_full(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installer = root / "FLUKE-0.1.2-Setup.exe"
            installer.write_bytes(b"installer")
            usage = type("Usage", (), {"free": 1})()
            with patch("wanxiang.app_updates.shutil.disk_usage", return_value=usage):
                self.assertFalse(_has_install_space(root, installer))

    def test_sidecar_request_failure_cleans_old_parts_before_retry(self) -> None:
        installer = make_pe()
        release_info = download_release(installer)
        release_info.pop("_sidecar")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version_dir = root / release_info["tag"]
            version_dir.mkdir()
            target = version_dir / release_info["setupName"]
            stale_parts = (
                target.with_name(target.name + ".part"),
                target.with_name(target.name + ".sha256.part"),
            )
            for stale_part in stale_parts:
                stale_part.write_bytes(b"stale")
            with patch(
                "wanxiang.app_updates._open_github_url",
                side_effect=URLError("offline"),
            ):
                with self.assertRaises(URLError):
                    _download_verified_setup(release_info, root, lambda *_: None)
            self.assertTrue(all(not path.exists() for path in stale_parts))


if __name__ == "__main__":
    unittest.main()
