"""Verified GitHub Setup downloads; installation stays manual until rollback is safe."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PySide6.QtCore import QObject, Property, QRunnable, QProcess, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices


APP_VERSION = "0.1.2"  # Keep in sync with pyproject.toml and installer/FLUKE.iss.
MINIMUM_UPDATE_VERSION = (0, 1, 2)
GITHUB_REPOSITORY = "linjiuyao2025/FLUKE"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases?per_page=100"
GITHUB_API_HOST = "api.github.com"
GITHUB_DOWNLOAD_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}
MAX_RELEASES_BYTES = 2 * 1024 * 1024
MAX_RELEASE_PAGES = 5
MAX_SETUP_BYTES = 2 * 1024 * 1024 * 1024
MAX_CHECKSUM_BYTES = 4096
MIN_INSTALL_FREE_BYTES = 128 * 1024 * 1024
TAG_PATTERN = re.compile(
    r"^(?:native-)?v(?P<version>\d+\.\d+\.\d+)(?:-preview\.(?P<preview>\d+))?$"
)
CHECKSUM_PATTERN = re.compile(r"^([0-9a-fA-F]{64})(?:[ \t]+\*?([^\r\n]+))?$")


class UpdateCancelled(Exception):
    pass


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise ValueError("FLUKE 版本号格式无效。")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _release_key(tag: str) -> tuple[int, int, int, int, int]:
    match = TAG_PATTERN.fullmatch(tag)
    if not match:
        raise ValueError("GitHub Release 标签不是受支持的 FLUKE 版本。")
    version = _version_tuple(match.group("version"))
    preview = match.group("preview")
    return (*version, 0 if preview else 1, int(preview or 0))


def _asset_url(release_tag: str, asset: dict[str, Any], expected_name: str) -> str:
    if asset.get("name") != expected_name or not isinstance(asset.get("browser_download_url"), str):
        raise ValueError(f"GitHub Release 缺少 {expected_name}。")
    url = asset["browser_download_url"]
    parsed = urlsplit(url)
    expected_path = f"/{GITHUB_REPOSITORY}/releases/download/{quote(release_tag, safe='')}/{expected_name}"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.path != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{expected_name} 不是 FLUKE 官方 GitHub Release 资产。")
    return url


def _release_details(release: dict[str, Any], tag: str) -> dict[str, Any]:
    version = _release_key(tag)[:3]
    version_text = ".".join(str(part) for part in version)
    release_url = release.get("html_url")
    expected_release_url = (
        f"https://github.com/{GITHUB_REPOSITORY}/releases/tag/{quote(tag, safe='')}"
    )
    if release_url != expected_release_url:
        raise ValueError("FLUKE Release 页面不是官方 GitHub Release。")

    setup_name = f"FLUKE-{version_text}-Setup.exe"
    checksum_name = f"{setup_name}.sha256"
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError("FLUKE Release 缺少安装资产清单。")
    asset_by_name: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str):
            if asset["name"] in asset_by_name:
                raise ValueError("FLUKE Release 含重复安装资产。")
            asset_by_name[asset["name"]] = asset
    setup_asset = asset_by_name.get(setup_name)
    checksum_asset = asset_by_name.get(checksum_name)
    if setup_asset is None or checksum_asset is None:
        raise ValueError(f"FLUKE {version_text} Release 缺少安装包或 SHA-256 sidecar。")
    setup_size = setup_asset.get("size")
    checksum_size = checksum_asset.get("size")
    if type(setup_size) is not int or not 1 <= setup_size <= MAX_SETUP_BYTES:
        raise ValueError("FLUKE 安装包的大小超出允许范围。")
    if type(checksum_size) is not int or not 1 <= checksum_size <= MAX_CHECKSUM_BYTES:
        raise ValueError("FLUKE SHA-256 sidecar 的大小无效。")
    return {
        "version": version_text,
        "tag": tag,
        "releaseUrl": expected_release_url,
        "setupName": setup_name,
        "setupSize": setup_size,
        "setupUrl": _asset_url(tag, setup_asset, setup_name),
        "checksumName": checksum_name,
        "checksumSize": checksum_size,
        "checksumUrl": _asset_url(tag, checksum_asset, checksum_name),
    }


def _release_for_update(releases: object, current_version: str = APP_VERSION) -> dict[str, Any] | None:
    current = _version_tuple(current_version)
    if not isinstance(releases, list):
        raise ValueError("GitHub Release 响应格式无效。")
    eligible: list[tuple[tuple[int, int, int, int, int], dict[str, Any], str]] = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") is not False:
            continue
        tag = release.get("tag_name")
        if not isinstance(tag, str):
            continue
        try:
            key = _release_key(tag)
        except ValueError:
            continue
        tag_match = TAG_PATTERN.fullmatch(tag)
        if bool(release.get("prerelease")) != bool(tag_match and tag_match.group("preview")):
            continue
        if key[:3] >= MINIMUM_UPDATE_VERSION and key[:3] > current:
            eligible.append((key, release, tag))
    if not eligible:
        return None
    first_error = ""
    for _key, release, tag in sorted(eligible, key=lambda item: item[0], reverse=True):
        try:
            return _release_details(release, tag)
        except ValueError as exc:
            if not first_error:
                first_error = str(exc)
    raise ValueError(first_error or "没有找到包含完整 FLUKE 安装资产的 Release。")


def _is_trusted_https_url(url: str, allowed_hosts: set[str]) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in allowed_hosts
            and parsed.username is None
            and parsed.password is None
            and parsed.port is None
            and not parsed.fragment
        )
    except ValueError:
        return False


def _checksum_from_sidecar(body: bytes, asset_name: str) -> str:
    if not body or len(body) > MAX_CHECKSUM_BYTES:
        raise ValueError("SHA-256 sidecar 为空或超出大小上限。")
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("SHA-256 sidecar 不是 ASCII 文本。") from exc
    text = text.removesuffix("\r\n").removesuffix("\n")
    if "\r" in text or "\n" in text:
        raise ValueError("SHA-256 sidecar 必须只含一条校验记录。")
    match = CHECKSUM_PATTERN.fullmatch(text)
    if not match or (match.group(2) and match.group(2).strip() != asset_name):
        raise ValueError("SHA-256 sidecar 格式无效或文件名不匹配。")
    return match.group(1).lower()


def _get_bytes(url: str, limit: int, user_agent: str) -> bytes:
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "application/octet-stream"})
    with _open_github_url(request, GITHUB_DOWNLOAD_HOSTS, timeout=35) as response:
        if not _is_trusted_https_url(response.geturl(), GITHUB_DOWNLOAD_HOSTS):
            raise ValueError("下载没有来自 GitHub 的 HTTPS 资产地址。")
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("GitHub 响应超过大小上限。")
    return body


class _AllowedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        if not _is_trusted_https_url(new_url, self.allowed_hosts):
            raise ValueError("GitHub 请求重定向到了不受信任的 HTTPS 主机。")
        return super().redirect_request(request, file_pointer, code, message, headers, new_url)


def _open_github_url(request: Request, allowed_hosts: set[str], timeout: int) -> Any:
    if not _is_trusted_https_url(request.full_url, allowed_hosts):
        raise ValueError("FLUKE 更新请求不是受信任的 GitHub HTTPS 地址。")
    opener = build_opener(_AllowedRedirectHandler(allowed_hosts))
    return opener.open(request, timeout=timeout)


def _read_releases() -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    for page in range(1, MAX_RELEASE_PAGES + 1):
        url = f"{GITHUB_RELEASES_API}&page={page}"
        request = Request(
            url,
            headers={"User-Agent": "FLUKE-Desktop-Updater", "Accept": "application/vnd.github+json"},
        )
        with _open_github_url(request, {GITHUB_API_HOST}, timeout=25) as response:
            if not _is_trusted_https_url(response.geturl(), {GITHUB_API_HOST}):
                raise ValueError("FLUKE 更新清单没有来自 GitHub API。")
            body = response.read(MAX_RELEASES_BYTES + 1)
        if len(body) > MAX_RELEASES_BYTES:
            raise ValueError("FLUKE GitHub Release 列表超过大小上限。")
        try:
            payload = json.loads(body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("FLUKE GitHub Release 列表无法解析。") from exc
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise ValueError("FLUKE GitHub Release 响应格式无效。")
        releases.extend(payload)
        if len(payload) < 100:
            return releases
    raise ValueError("FLUKE GitHub Release 数量超出检查上限。")


def _is_windows_pe(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            header = stream.read(64)
            if len(header) < 64 or header[:2] != b"MZ":
                return False
            offset = int.from_bytes(header[0x3C:0x40], "little")
            file_size = path.stat().st_size
            if offset < 64 or offset > 1024 * 1024 or offset + 24 > file_size:
                return False
            stream.seek(offset)
            pe_header = stream.read(24)
            if len(pe_header) != 24 or pe_header[:4] != b"PE\0\0":
                return False
            machine = int.from_bytes(pe_header[4:6], "little")
            sections = int.from_bytes(pe_header[6:8], "little")
            optional_size = int.from_bytes(pe_header[20:22], "little")
            characteristics = int.from_bytes(pe_header[22:24], "little")
            if machine not in {0x014C, 0x8664, 0xAA64} or not 1 <= sections <= 96:
                return False
            if not characteristics & 0x0002 or characteristics & 0x2000:
                return False
            minimum_optional_size = 96 if machine == 0x014C else 112
            section_table = offset + 24 + optional_size
            if (
                optional_size < minimum_optional_size
                or optional_size > 4096
                or section_table + sections * 40 > file_size
            ):
                return False
            optional_header = stream.read(optional_size)
            magic = int.from_bytes(optional_header[:2], "little")
            expected_magic = 0x10B if machine == 0x014C else 0x20B
            subsystem = int.from_bytes(optional_header[68:70], "little")
            image_size = int.from_bytes(optional_header[56:60], "little")
            return magic == expected_magic and subsystem == 2 and image_size > 0
    except OSError:
        return False


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_install_space(root: Path, installer: Path) -> bool:
    try:
        required = max(MIN_INSTALL_FREE_BYTES, installer.stat().st_size * 2)
        return shutil.disk_usage(root).free >= required
    except OSError:
        return False


def _remove_temporary_files(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _download_verified_setup(
    release: dict[str, Any],
    download_root: Path,
    report_progress: Callable[[str, int], None],
    should_cancel: Callable[[], bool] | None = None,
) -> Path:
    version_dir = download_root / release["tag"]
    version_dir.mkdir(parents=True, exist_ok=True)
    target = version_dir / release["setupName"]
    sidecar_path = version_dir / release["checksumName"]
    temporary = target.with_name(target.name + ".part")
    temporary_sidecar = sidecar_path.with_name(sidecar_path.name + ".part")

    try:
        if should_cancel and should_cancel():
            raise UpdateCancelled("用户已取消 FLUKE 更新下载。")
        _remove_temporary_files(temporary, temporary_sidecar)
        report_progress("正在下载并检查 SHA-256 sidecar…", 5)
        sidecar = _get_bytes(release["checksumUrl"], MAX_CHECKSUM_BYTES, "FLUKE-Desktop-Updater")
        if len(sidecar) != release["checksumSize"]:
            raise ValueError("SHA-256 sidecar 下载不完整。")
        expected_hash = _checksum_from_sidecar(sidecar, release["setupName"])

        if target.is_file() and sidecar_path.is_file():
            try:
                if sidecar_path.stat().st_size <= MAX_CHECKSUM_BYTES:
                    cached_sidecar = sidecar_path.read_bytes()
                    if (
                        _checksum_from_sidecar(cached_sidecar, release["setupName"]) == expected_hash
                        and _file_sha256(target) == expected_hash
                        and _is_windows_pe(target)
                    ):
                        report_progress("已找到并重新校验现存的 FLUKE 安装包。", 100)
                        return target
            except (OSError, ValueError):
                pass

        digest = hashlib.sha256()
        received = 0
        request = Request(
            release["setupUrl"],
            headers={"User-Agent": "FLUKE-Desktop-Updater", "Accept": "application/octet-stream"},
        )
        with (
            _open_github_url(request, GITHUB_DOWNLOAD_HOSTS, timeout=60) as response,
            temporary.open("wb") as stream,
        ):
            if not _is_trusted_https_url(response.geturl(), GITHUB_DOWNLOAD_HOSTS):
                raise ValueError("FLUKE 安装包下载没有来自 GitHub 的 HTTPS 地址。")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                if should_cancel and should_cancel():
                    raise UpdateCancelled("用户已取消 FLUKE 更新下载。")
                received += len(chunk)
                if received > release["setupSize"] or received > MAX_SETUP_BYTES:
                    raise ValueError("FLUKE 安装包体积超过 GitHub Release 声明。")
                digest.update(chunk)
                stream.write(chunk)
                report_progress(
                    f"正在下载 FLUKE {release['version']}：{received // (1024 * 1024)} MiB",
                    min(95, int(received * 95 / release["setupSize"])),
                )
        if received != release["setupSize"]:
            raise ValueError("FLUKE 安装包下载不完整。")
        if digest.hexdigest() != expected_hash:
            raise ValueError("FLUKE 安装包 SHA-256 校验失败，文件未保留。")
        if not _is_windows_pe(temporary):
            raise ValueError("下载文件不是有效的 Windows 安装程序。")
        temporary_sidecar.write_bytes(sidecar)
        os.replace(temporary, target)
        os.replace(temporary_sidecar, sidecar_path)
        report_progress("FLUKE 安装包已下载并通过 SHA-256 校验；尚未运行安装器。", 100)
        return target
    finally:
        _remove_temporary_files(temporary, temporary_sidecar)


class _UpdateSignals(QObject):
    progress = Signal(str, int)
    finished = Signal(object)


class _UpdateTask(QRunnable):
    def __init__(self, operation: Callable[[Callable[[str, int], None]], dict[str, Any]]) -> None:
        super().__init__()
        self.signals = _UpdateSignals()
        self._operation = operation

    def run(self) -> None:
        try:
            result = self._operation(self.signals.progress.emit)
        except UpdateCancelled as exc:
            result = {"ok": False, "cancelled": True, "error": str(exc)}
        except HTTPError as exc:
            result = {"ok": False, "error": f"GitHub 更新请求失败（HTTP {exc.code}）。"}
        except (URLError, TimeoutError, OSError) as exc:
            result = {"ok": False, "error": f"无法连接 FLUKE GitHub Release：{exc}"}
        except (ValueError, json.JSONDecodeError) as exc:
            result = {"ok": False, "error": str(exc) or "FLUKE 更新校验失败。"}
        except Exception as exc:  # Keep unexpected download failures out of the Qt event loop.
            result = {"ok": False, "error": f"FLUKE 更新失败：{exc}"}
        self.signals.finished.emit(result)


class AppUpdateBridge(QObject):
    """Checks and verifies releases; installs only in the side-by-side layout."""

    stateChanged = Signal()
    restartRequested = Signal()

    def __init__(
        self,
        download_root: Path | None = None,
        current_version: str = APP_VERSION,
        application_executable: Path | None = None,
    ) -> None:
        super().__init__()
        self._current_version = current_version
        self._application_executable = (application_executable or Path(sys.executable)).resolve()
        self._download_root = (download_root or Path.home() / "AppData" / "Local" / "FLUKE" / "Updates").resolve()
        self._release: dict[str, Any] | None = None
        self._verified_path: Path | None = None
        self._busy = False
        self._progress = 0
        self._status = "可检查 FLUKE GitHub Releases 中 v0.1.2 及以上的安装包。"
        self._pool = QThreadPool(self)
        self._task: _UpdateTask | None = None
        self._action = ""
        self._cancel_requested = False

    def _snapshot(self) -> dict[str, Any]:
        has_release = self._release is not None
        release = self._release or {}
        verified = self._verified_path if self._verified_path and self._verified_path.is_file() else None
        return {
            "currentVersion": self._current_version,
            "availableVersion": str(release.get("version", "")),
            "releaseTag": str(release.get("tag", "")),
            "releaseUrl": str(release.get("releaseUrl", "")),
            "updateAvailable": has_release,
            "downloadSize": int(release.get("setupSize", 0)) if release else 0,
            "verifiedInstallerPath": str(verified) if verified else "",
            "busy": self._busy,
            "progress": self._progress,
            "statusMessage": self._status,
            "automaticInstallAvailable": self._automatic_install_available(),
            "cancellable": self._busy and self._action == "download",
        }

    def _installation_root(self) -> Path | None:
        parent = self._application_executable.parent
        if parent.parent.name.casefold() != "versions":
            return None
        root = parent.parent.parent
        if not (root / "FLUKE.exe").is_file() or not (root / "versions").is_dir():
            return None
        return root

    def _automatic_install_available(self) -> bool:
        return self._installation_root() is not None

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return self._snapshot()

    def _begin(
        self,
        action: str,
        operation: Callable[[Callable[[str, int], None]], dict[str, Any]],
        status: str,
    ) -> None:
        if self._busy:
            return
        self._busy = True
        self._action = action
        self._cancel_requested = False
        self._progress = 0
        self._status = status
        task = _UpdateTask(operation)
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_finished)
        self._task = task
        self.stateChanged.emit()
        self._pool.start(task)

    @Slot(str, int)
    def _on_progress(self, message: str, percentage: int) -> None:
        self._status = message
        self._progress = max(0, min(100, int(percentage)))
        self.stateChanged.emit()

    @Slot(object)
    def _on_finished(self, result: object) -> None:
        info = result if isinstance(result, dict) else {"ok": False, "error": "更新操作没有返回结果。"}
        if info.get("ok"):
            if self._action == "check":
                self._release = info.get("release")
                self._verified_path = None
            elif self._action == "download":
                self._verified_path = Path(info["path"])
            self._status = str(info.get("message") or "完成。")
        else:
            self._status = str(info.get("error") or "FLUKE 更新失败。")
        self._busy = False
        self._task = None
        self._cancel_requested = False
        self.stateChanged.emit()

    @Slot()
    def checkForUpdates(self) -> None:
        def operation(report: Callable[[str, int], None]) -> dict[str, Any]:
            report("正在检查 FLUKE 官方 GitHub Releases…", 10)
            release = _release_for_update(_read_releases(), self._current_version)
            if release is None:
                return {"ok": True, "message": f"当前版本 {self._current_version}；未找到更新版本。", "release": None}
            return {
                "ok": True,
                "message": f"发现 FLUKE {release['version']}（{release['tag']}）。",
                "release": release,
            }
        self._begin("check", operation, "正在检查 FLUKE 更新…")

    @Slot()
    def downloadAndVerify(self) -> None:
        release = self._release
        if self._busy:
            return
        if release is None:
            self._status = "请先检查更新；没有可下载的 FLUKE 安装包。"
            self.stateChanged.emit()
            return

        def operation(report: Callable[[str, int], None]) -> dict[str, Any]:
            path = _download_verified_setup(
                release,
                self._download_root,
                report,
                should_cancel=lambda: self._cancel_requested,
            )
            return {
                "ok": True,
                "message": f"安装包已通过 SHA-256 校验并保存在：{path}。应用尚未安装或重启。",
                "path": str(path),
            }
        self._begin("download", operation, f"正在准备 FLUKE {release['version']} 安装包…")

    @Slot()
    def cancelCurrentOperation(self) -> None:
        if self._busy and self._action == "download":
            self._cancel_requested = True
            self._status = "正在取消 FLUKE 下载…"
            self.stateChanged.emit()

    @Slot()
    def openVerifiedDownloadFolder(self) -> None:
        if self._verified_path is None or not self._verified_path.is_file():
            self._status = "请先下载并校验 FLUKE 安装包。"
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._verified_path.parent))):
            self._status = "无法打开已校验安装包所在文件夹。"
        else:
            self._status = "已打开安装包所在文件夹；应用没有运行安装器。"
        self.stateChanged.emit()

    @Slot()
    def installVerifiedUpdate(self) -> None:
        if self._busy:
            return
        installer = self._verified_path
        root = self._installation_root()
        if installer is None or not installer.is_file():
            self._status = "请先下载并校验 FLUKE 安装包。"
        elif root is None:
            self._status = "自动安装已关闭：当前安装不是可回滚的 side-by-side 版本布局。"
        elif not _has_install_space(root, installer):
            self._status = "可用磁盘空间不足；当前版本未切换。"
        else:
            started, _pid = QProcess.startDetached(
                str(installer),
                [
                    "/VERYSILENT",
                    "/NORESTART",
                    "/SUPPRESSMSGBOXES",
                    "/CLOSEAPPLICATIONS",
                    f"/DIR={root}",
                    "/LANG=chinesesimp",
                ],
                str(root),
            )
            if not started:
                self._status = "无法启动 FLUKE 安装程序；当前版本未切换。"
            else:
                self._status = "安装程序已启动；新版会先健康检查，失败时保留旧版本。"
                self.restartRequested.emit()
        self.stateChanged.emit()


if __name__ == "__main__":
    sample = [{
        "draft": False,
        "prerelease": True,
        "tag_name": "native-v0.1.2-preview.1",
        "html_url": "https://github.com/linjiuyao2025/FLUKE/releases/tag/native-v0.1.2-preview.1",
        "assets": [
            {"name": "FLUKE-0.1.2-Setup.exe", "size": 1234,
             "browser_download_url": "https://github.com/linjiuyao2025/FLUKE/releases/download/native-v0.1.2-preview.1/FLUKE-0.1.2-Setup.exe"},
            {"name": "FLUKE-0.1.2-Setup.exe.sha256", "size": 90,
             "browser_download_url": "https://github.com/linjiuyao2025/FLUKE/releases/download/native-v0.1.2-preview.1/FLUKE-0.1.2-Setup.exe.sha256"},
        ],
    }]
    assert _release_for_update(sample, "0.1.1")["version"] == "0.1.2"
    assert _release_for_update(sample, "0.1.2") is None
    assert _checksum_from_sidecar(("a" * 64 + "  FLUKE-0.1.2-Setup.exe\n").encode(), "FLUKE-0.1.2-Setup.exe") == "a" * 64
    try:
        _checksum_from_sidecar(("a" * 64 + "  other.exe\n").encode(), "FLUKE-0.1.2-Setup.exe")
    except ValueError:
        pass
    else:
        raise AssertionError("sidecar filename mismatch was accepted")
    print("app update selection and checksum self-check passed")
