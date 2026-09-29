from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
FFMPEG_SOURCE = ROOT / "source" / "ffmpeg" / "ffmpeg-g51c4a23d74.tar.gz"
EXPECTED_FFMPEG_SHA256 = "10323f69c6a2b69e035c5cfdd3a1ab366af784e3bbe25d1cb64534027791b384"
MSYS_ROOT = ROOT / "source" / "unpacked" / "msys2"
UPSTREAM_ROOT = ROOT / "source" / "upstream"
FFMPEG_ROOT = ROOT / "source" / "unpacked" / "ffmpeg" / "FFmpeg-51c4a23d74"

PACKAGES = {
    "lame": ("mingw-w64-lame", "3.100-3", "LGPL", "https://lame.sourceforge.io/"),
    "libvpx": ("mingw-w64-libvpx", "1.17.0-1", "BSD-3-Clause", "https://github.com/webmproject/libvpx"),
    "opus": ("mingw-w64-opus", "1.6.1-1", "BSD-3-Clause", "https://github.com/xiph/opus"),
    "libvorbis": ("mingw-w64-libvorbis", "1.3.7-3", "custom (Xiph license text included)", "https://gitlab.xiph.org/xiph/vorbis"),
    "libogg": ("mingw-w64-libogg", "1.3.6-1", "BSD-3-Clause", "https://gitlab.xiph.org/xiph/ogg"),
}

LICENSE_FILES = {
    "ffmpeg": [(FFMPEG_ROOT / "COPYING.LGPLv3", "ffmpeg-COPYING.LGPLv3")],
    "lame": [(UPSTREAM_ROOT / "lame-3.100" / "COPYING", "lame-COPYING"), (UPSTREAM_ROOT / "lame-3.100" / "LICENSE", "lame-LICENSE")],
    "libvpx": [(UPSTREAM_ROOT / "libvpx-1.17.0" / "LICENSE", "libvpx-LICENSE"), (UPSTREAM_ROOT / "libvpx-1.17.0" / "PATENTS", "libvpx-PATENTS")],
    "opus": [(UPSTREAM_ROOT / "opus-1.6.1" / "COPYING", "opus-COPYING")],
    "libvorbis": [(UPSTREAM_ROOT / "libvorbis-1.3.7" / "COPYING", "libvorbis-COPYING")],
    "libogg": [(UPSTREAM_ROOT / "libogg-1.3.6" / "COPYING", "libogg-COPYING")],
    "gcc-runtime": [
        (ROOT / "source" / "runtime-licenses" / "libgcc-COPYING.RUNTIME", "gcc-COPYING.RUNTIME"),
        (ROOT / "source" / "runtime-licenses" / "libgcc-COPYING3", "gcc-COPYING3"),
        (ROOT / "source" / "runtime-licenses" / "libstdc++-COPYING.RUNTIME", "libstdc++-COPYING.RUNTIME"),
        (ROOT / "source" / "runtime-licenses" / "libstdc++-COPYING3", "libstdc++-COPYING3"),
    ],
    "winpthreads-runtime": [
        (ROOT / "source" / "runtime-licenses" / "libwinpthread-COPYING", "libwinpthread-COPYING"),
    ],
}

RUNTIME_PACKAGES = {
    "gcc-runtime": {
        "name": "mingw-w64-gcc",
        "version": "16.2.0-4",
        "license": "GPL-3.0-or-later WITH GCC-exception-3.1 AND GFDL-1.3-or-later",
        "homepage": "https://gcc.gnu.org",
        "archiveSha256": "a1792a44764405bc365746e0e60f0daa122076cec0dddd35a781d141f94273cf",
        "srcInfoSha256": "c175f88951ae11e5d3410277d85c1776ce60d56d542c3559e2422b2bcbb2f285",
        "sourceOnlyUrl": "https://mirror.msys2.org/mingw/sources/mingw-w64-gcc-16.2.0-4.src.tar.zst",
        "runtimeFiles": ["libgcc_s_seh-1.dll", "libstdc++-6.dll"],
    },
    "winpthreads-runtime": {
        "name": "mingw-w64-winpthreads",
        "version": "14.0.0.r426.g4564ee4b5-1",
        "license": "MIT AND BSD-3-Clause-Clear",
        "homepage": "https://www.mingw-w64.org/",
        "archiveSha256": "5493832de1b7e24f09edb556ed409091b0844f9677212c4865618d6f93c508be",
        "srcInfoSha256": "c99535913544afa7a57e5c7da19d92c42d8401e5978fabade279619799de91ff",
        "sourceOnlyUrl": "https://mirror.msys2.org/mingw/sources/mingw-w64-winpthreads-14.0.0.r426.g4564ee4b5-1.src.tar.zst",
        "runtimeFiles": ["libwinpthread-1.dll"],
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def required_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"Missing or empty required file: {path}")


required_file(FFMPEG_SOURCE)
ffmpeg_sha = sha256(FFMPEG_SOURCE)
if ffmpeg_sha != EXPECTED_FFMPEG_SHA256:
    raise SystemExit(f"FFmpeg source SHA-256 mismatch: {ffmpeg_sha}")

manifest = {
    "ffmpeg": {
        "version": "9.0.2-10-g51c4a23d74",
        "sourceUrl": "https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/51c4a23d74",
        "sourceArchive": FFMPEG_SOURCE.name,
        "sourceSha256": ffmpeg_sha,
        "license": "LGPL-3.0-or-later",
    },
    "externalPackages": [],
}

for key, (base, version, license_name, homepage) in PACKAGES.items():
    package_root = MSYS_ROOT / base
    source_info = package_root / ".SRCINFO"
    required_file(source_info)
    info = source_info.read_text(encoding="utf-8")
    source_items = [line.split("=", 1)[1].strip() for line in info.splitlines() if line.lstrip().startswith("source =")]
    checksums = [line.split("=", 1)[1].strip().lower() for line in info.splitlines() if line.lstrip().startswith("sha256sums =")]
    if len(source_items) != len(checksums) or not source_items:
        raise SystemExit(f"Malformed source/hash list in {source_info}")
    verified_sources = []
    for source, expected_sha in zip(source_items, checksums, strict=True):
        source_ref = source.split("::")[-1]
        filename = unquote(Path(urlsplit(source_ref).path).name or source_ref)
        source_path = package_root / filename
        required_file(source_path)
        actual_sha = sha256(source_path)
        if actual_sha != expected_sha:
            raise SystemExit(f"Source SHA-256 mismatch for {base}/{filename}: {actual_sha} != {expected_sha}")
        verified_sources.append({"filename": filename, "sha256": actual_sha, "source": source})

    archive = ROOT / "source" / "msys2" / f"{base}-{version}.src.tar.zst"
    required_file(archive)
    manifest["externalPackages"].append({
        "name": base,
        "version": version,
        "license": license_name,
        "homepage": homepage,
        "sourceOnlyArchive": archive.name,
        "sourceOnlyUrl": f"https://mirror.msys2.org/mingw/sources/{archive.name}",
        "sourceOnlyArchiveSha256": sha256(archive),
        "sourcesAndPatches": verified_sources,
    })

for key, package in RUNTIME_PACKAGES.items():
    base = package["name"]
    version = package["version"]
    archive = ROOT / "source" / "msys2" / f"{base}-{version}.src.tar.zst"
    source_info = ROOT / "source" / "msys2" / f"{base}-{version}.SRCINFO"
    required_file(archive)
    required_file(source_info)
    archive_sha = sha256(archive)
    source_info_sha = sha256(source_info)
    if archive_sha != package["archiveSha256"]:
        raise SystemExit(f"Runtime source archive SHA-256 mismatch for {base}: {archive_sha}")
    if source_info_sha != package["srcInfoSha256"]:
        raise SystemExit(f"Runtime package .SRCINFO SHA-256 mismatch for {base}: {source_info_sha}")
    info = source_info.read_text(encoding="utf-8")
    if f"pkgver = {version.rsplit('-', 1)[0]}" not in info or f"pkgrel = {version.rsplit('-', 1)[1]}" not in info:
        raise SystemExit(f"Runtime package version mismatch in {source_info}")
    if f"license = spdx:{package['license']}" not in info:
        raise SystemExit(f"Runtime package license mismatch in {source_info}")
    sources = [line.split("=", 1)[1].strip() for line in info.splitlines() if line.lstrip().startswith("source =")]
    checksums = [line.split("=", 1)[1].strip().lower() for line in info.splitlines() if line.lstrip().startswith("sha256sums =")]
    if len(sources) != len(checksums) or not sources:
        raise SystemExit(f"Malformed source/hash list in {source_info}")
    manifest["externalPackages"].append({
        "name": base,
        "version": version,
        "license": package["license"],
        "homepage": package["homepage"],
        "sourceOnlyArchive": archive.name,
        "sourceOnlyUrl": package["sourceOnlyUrl"],
        "sourceOnlyArchiveSha256": archive_sha,
        "srcInfoFile": source_info.name,
        "srcInfoSha256": source_info_sha,
        "runtimeFiles": package["runtimeFiles"],
        "sourcesAndPatches": [
            {"source": source, "sha256": None if checksum == "skip" else checksum}
            for source, checksum in zip(sources, checksums, strict=True)
        ],
    })

license_manifest = []
for files in LICENSE_FILES.values():
    for source_path, destination_name in files:
        required_file(source_path)
        license_manifest.append({"path": f"notices/{destination_name}", "sha256": sha256(source_path)})

notice_dir = ROOT / "notices"
notice_dir.mkdir(parents=True, exist_ok=True)
for component, files in LICENSE_FILES.items():
    for source_path, destination_name in files:
        required_file(source_path)
        (notice_dir / destination_name).write_bytes(source_path.read_bytes())

notice_lines = [
    "# FFmpeg candidate third-party notices",
    "",
    "Candidate only. This notice inventory is generated from the pinned source archives; it does not establish installed-app or published-release acceptance.",
    "",
    "- FFmpeg 9.0.2-10-g51c4a23d74: LGPL-3.0-or-later. The corresponding source archive and SHA-256 are listed in `source-manifest.json`.",
    "- LAME 3.100: LGPL; upstream `COPYING` and `LICENSE`, source tarball, MSYS2 recipe, and patches are included.",
    "- libvpx 1.17.0: BSD-3-Clause; upstream `LICENSE` and `PATENTS`, source tarball, MSYS2 recipe, and patch are included.",
    "- Opus 1.6.1: BSD-3-Clause; upstream `COPYING`, source tarball, MSYS2 recipe, and patch are included.",
    "- libvorbis 1.3.7: the upstream Xiph `COPYING` text is included with its source tarball and MSYS2 recipe.",
    "- libogg 1.3.6: BSD-3-Clause; upstream `COPYING`, source tarball, MSYS2 recipe, and patch are included.",
    "- MinGW GCC runtime DLLs `libgcc_s_seh-1.dll` and `libstdc++-6.dll`: GPL-3.0-or-later with GCC Runtime Library Exception 3.1; `COPYING3` and `COPYING.RUNTIME` texts, exact GCC source-only archive, recipe, and patches are included.",
    "- MinGW winpthreads runtime DLL `libwinpthread-1.dll`: MIT and BSD-3-Clause-Clear; upstream license text and exact source-only archive, recipe, and patch are included.",
    "",
    "The MSYS2 source-only archives contain the exact package recipe, patches, and upstream source archives associated with the package versions selected for this isolated candidate. SHA-256 values for every archive are recorded in `source-manifest.json`.",
    "",
    "The build configuration is LGPL shared, disables GPL, nonfree, autodetected components, and libzvbi. The runtime PE dependency closure is recorded separately; Windows system imports remain supplied by Windows.",
    "",
]
(notice_dir / "THIRD-PARTY-NOTICES.md").write_text("\n".join(notice_lines), encoding="utf-8")
manifest["licenseTexts"] = license_manifest
(ROOT / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

print(f"Verified FFmpeg source: {ffmpeg_sha}")
print(f"Verified {len(PACKAGES) + len(RUNTIME_PACKAGES)} MSYS2 source-only archives and their declared source/patch metadata.")
print(f"Copied {len(license_manifest)} source license/patent texts into {notice_dir}.")
