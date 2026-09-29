"""App-local converter engines and a user-confirmed GitHub update channel.

Engines remain separate programs under their own licenses. The FLUKE installer
ships a pinned baseline under ``engines/``; optional updates are installed into
the user's writable FLUKE data directory and activated through an atomic
pointer file. Existing versions are kept so failed installs never replace the
working copy and running converter processes can finish safely.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
import zipfile

from PySide6.QtCore import Property, QObject, QRunnable, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices


ENGINE_UPDATE_MANIFEST_URL = (
    "https://github.com/linjiuyao2025/FLUKE/releases/latest/download/fluke-engines.json"
)
ENGINE_RELEASE_DOWNLOAD_PREFIX = (
    "https://github.com/linjiuyao2025/FLUKE/releases/download/"
)
GITHUB_DOWNLOAD_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}
ENGINE_IDS = ("ffmpeg", "tesseract", "calibre")
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 50_000

ENGINE_SPECS: dict[str, dict[str, str]] = {
    "ffmpeg": {
        "label": "FFmpeg 音视频引擎",
        "description": "音频、视频格式转换与音轨提取。",
        "executable": "bin/ffmpeg.exe",
        "probe_argument": "-version",
        "source_required": "true",
    },
    "tesseract": {
        "label": "Tesseract OCR 引擎",
        "description": "图片文字识别、扫描 PDF 文字层和表格识别。",
        "executable": "tesseract.exe",
        "probe_argument": "--version",
        "source_required": "true",
    },
    "calibre": {
        "label": "Calibre 电子书引擎",
        "description": "无 DRM MOBI 等电子书格式转换。",
        "executable": "Calibre/ebook-convert.exe",
        "probe_argument": "--version",
        "source_required": "true",
    },
}


def bundled_engines_root() -> Path:
    """Return the engine data folder in a frozen app or source checkout."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "engines"
    return Path(__file__).resolve().parents[1] / "third-party" / "converter-engines"


def user_engine_root() -> Path:
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    )
    return local_app_data / "FLUKE" / "EngineUpdates"


def _active_update_record(engine_id: str, root: Path | None = None) -> dict[str, str] | None:
    if engine_id not in ENGINE_SPECS:
        return None
    update_root = (root or user_engine_root()).resolve()
    try:
        payload = json.loads((update_root / "active.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    record = payload.get(engine_id) if isinstance(payload, dict) else None
    if not isinstance(record, dict):
        return None
    directory = record.get("directory")
    version = record.get("version")
    if not isinstance(directory, str) or not re.fullmatch(r"[A-Za-z0-9._+-]{1,160}", directory):
        return None
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._+-]{1,120}", version):
        return None
    component = (update_root / engine_id / directory).resolve()
    if component.parent != (update_root / engine_id).resolve() or not component.is_dir():
        return None
    try:
        metadata = json.loads((component / "engine.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict) or metadata.get("id") != engine_id or metadata.get("version") != version:
        return None
    if not (component / "THIRD-PARTY-NOTICES.md").is_file():
        return None
    executable = component.joinpath(*ENGINE_SPECS[engine_id]["executable"].split("/"))
    if not executable.is_file():
        return None
    return {"directory": directory, "version": version, "path": str(component)}


def component_root(engine_id: str) -> Path | None:
    """Return the active updated engine, or its installer-bundled baseline."""
    record = _active_update_record(engine_id)
    if record:
        return Path(record["path"])
    candidate = bundled_engines_root() / engine_id
    metadata = _load_engine_metadata(candidate)
    spec = ENGINE_SPECS.get(engine_id)
    if (
        spec
        and candidate.is_dir()
        and metadata.get("id") == engine_id
        and isinstance(metadata.get("version"), str)
        and (candidate / "THIRD-PARTY-NOTICES.md").is_file()
        and candidate.joinpath(*spec["executable"].split("/")).is_file()
    ):
        return candidate
    return None


def engine_executable(engine_id: str) -> str | None:
    root = component_root(engine_id)
    spec = ENGINE_SPECS.get(engine_id)
    if root is None or spec is None:
        return None
    candidate = root.joinpath(*spec["executable"].split("/"))
    return str(candidate.resolve()) if candidate.is_file() else None


def engine_data_directory(engine_id: str, relative_path: str) -> str | None:
    root = component_root(engine_id)
    if root is None:
        return None
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return str(candidate) if candidate.is_dir() else None


def _load_engine_metadata(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        payload = json.loads((path / "engine.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _version_key(value: str) -> tuple[int, ...]:
    digits = re.findall(r"\d+", value)
    return tuple(int(part) for part in digits[:12]) if digits else ()


def _read_update_manifest() -> dict[str, Any]:
    request = Request(
        ENGINE_UPDATE_MANIFEST_URL,
        headers={"User-Agent": "FLUKE-Desktop-Engine-Updater", "Accept": "application/json"},
    )
    with urlopen(request, timeout=25) as response:
        final_url = urlsplit(response.geturl())
        if final_url.scheme != "https" or final_url.hostname not in GITHUB_DOWNLOAD_HOSTS:
            raise ValueError("更新清单没有来自 FLUKE 的 GitHub Release。")
        body = response.read(MAX_MANIFEST_BYTES + 1)
    if len(body) > MAX_MANIFEST_BYTES:
        raise ValueError("引擎更新清单超过大小上限。")
    try:
        manifest = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("引擎更新清单无法解析。") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ValueError("引擎更新清单版本不受支持。")
    tag = manifest.get("releaseTag")
    if not isinstance(tag, str) or not re.fullmatch(r"[A-Za-z0-9._+-]{1,120}", tag):
        raise ValueError("引擎更新清单缺少有效的发行版本。")
    raw_components = manifest.get("components")
    if not isinstance(raw_components, list):
        raise ValueError("引擎更新清单缺少组件列表。")
    components: dict[str, dict[str, Any]] = {}
    for item in raw_components:
        if not isinstance(item, dict):
            raise ValueError("引擎更新清单含无效组件。")
        engine_id = item.get("id")
        if engine_id not in ENGINE_SPECS or engine_id in components:
            raise ValueError("引擎更新清单包含重复或不支持的组件。")
        version = item.get("version")
        asset = item.get("asset")
        digest = item.get("sha256")
        size = item.get("sizeBytes")
        if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._+-]{1,120}", version):
            raise ValueError(f"{engine_id} 的版本号无效。")
        if not isinstance(asset, str) or not re.fullmatch(r"[A-Za-z0-9._+-]{1,180}\.zip", asset):
            raise ValueError(f"{engine_id} 的下载文件名无效。")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            raise ValueError(f"{engine_id} 缺少有效 SHA-256。")
        if not isinstance(size, int) or size < 1 or size > MAX_ARCHIVE_BYTES:
            raise ValueError(f"{engine_id} 的更新包大小无效。")
        components[engine_id] = {
            "id": engine_id,
            "version": version,
            "asset": asset,
            "sha256": digest.lower(),
            "sizeBytes": size,
            "releaseTag": tag,
            "downloadUrl": f"{ENGINE_RELEASE_DOWNLOAD_PREFIX}{tag}/{asset}",
        }
    return {"releaseTag": tag, "components": components}


@dataclass(frozen=True)
class _DownloadResult:
    path: Path
    sha256: str


def _download_verified(
    component: dict[str, Any],
    cache_dir: Path,
    report_progress: Callable[[str, int], None],
) -> _DownloadResult:
    download_url = component["downloadUrl"]
    if not download_url.startswith(ENGINE_RELEASE_DOWNLOAD_PREFIX):
        raise ValueError("组件下载地址不在 FLUKE GitHub Release 中。")
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{component['id']}-{component['version']}.zip.part"
    request = Request(
        download_url,
        headers={"User-Agent": "FLUKE-Desktop-Engine-Updater", "Accept": "application/octet-stream"},
    )
    digest = hashlib.sha256()
    received = 0
    try:
        with urlopen(request, timeout=35) as response, target.open("wb") as stream:
            final_url = urlsplit(response.geturl())
            if final_url.scheme != "https" or final_url.hostname not in GITHUB_DOWNLOAD_HOSTS:
                raise ValueError("组件下载没有来自 GitHub Releases 或其下载服务。")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > component["sizeBytes"] or received > MAX_ARCHIVE_BYTES:
                    raise ValueError("组件下载体积超过清单声明。")
                digest.update(chunk)
                stream.write(chunk)
                percentage = min(95, int(received * 95 / component["sizeBytes"]))
                report_progress(f"正在下载 {component['id']}：{received // (1024 * 1024)} MiB", percentage)
        if received != component["sizeBytes"]:
            raise ValueError("组件下载未完成，文件大小与清单不一致。")
        actual_hash = digest.hexdigest()
        if actual_hash != component["sha256"]:
            raise ValueError("组件 SHA-256 校验失败，已放弃安装。")
        complete_path = target.with_suffix("")
        os.replace(target, complete_path)
        return _DownloadResult(complete_path, actual_hash)
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _extract_component(
    archive_path: Path,
    component: dict[str, Any],
    staging: Path,
    report_progress: Callable[[str, int], None],
) -> Path:
    spec = ENGINE_SPECS[component["id"]]
    staging.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    total = 0
    with zipfile.ZipFile(archive_path, "r") as package:
        infos = package.infolist()
        if not infos or len(infos) > MAX_ARCHIVE_FILES:
            raise ValueError("组件压缩包文件数量无效。")
        for index, info in enumerate(infos, start=1):
            name = info.filename.replace("\\", "/")
            relative = PurePosixPath(name)
            if (
                not name
                or name.startswith("/")
                or ":" in name
                or any(part in ("", ".", "..") for part in relative.parts)
            ):
                raise ValueError("组件压缩包含越界路径。")
            key = name.casefold().rstrip("/")
            if key in seen:
                raise ValueError("组件压缩包含重复路径。")
            seen.add(key)
            mode = info.external_attr >> 16
            if mode & 0o170000 == 0o120000:
                raise ValueError("组件压缩包不允许包含符号链接。")
            total += info.file_size
            if total > MAX_EXTRACTED_BYTES:
                raise ValueError("组件解压体积超过安全上限。")
            destination = staging.joinpath(*relative.parts)
            try:
                destination.resolve().relative_to(staging.resolve())
            except ValueError as exc:
                raise ValueError("组件解压路径越界。") from exc
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info, "r") as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
            report_progress(f"正在展开 {component['id']}", 95 + int(index * 3 / len(infos)))

    executable = staging.joinpath(*spec["executable"].split("/"))
    if not executable.is_file():
        raise ValueError(f"更新包内缺少 {spec['executable']}。")
    if not (staging / "THIRD-PARTY-NOTICES.md").is_file():
        raise ValueError("更新包缺少第三方许可说明。")
    if spec["source_required"] == "true":
        source_root = staging / "source"
        if not source_root.is_dir() or not any(path.is_file() for path in source_root.rglob("*")):
            raise ValueError("此组件更新包缺少对应源码归档，未启用更新。")
    metadata = {
        "id": component["id"],
        "version": component["version"],
        "sha256": component["sha256"],
        "releaseTag": component["releaseTag"],
    }
    (staging / "engine.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_progress(f"正在验证 {component['id']}", 98)
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [str(executable), spec["probe_argument"]],
            cwd=str(staging),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"{component['id']} 无法启动，更新没有生效。") from exc
    if result.returncode != 0 or not result.stdout:
        raise ValueError(f"{component['id']} 自检失败，更新没有生效。")
    return staging


class _EngineTaskSignals(QObject):
    progress = Signal(str, int)
    finished = Signal(object)


class _EngineTask(QRunnable):
    def __init__(self, operation: Callable[[Callable[[str, int], None]], dict[str, Any]]) -> None:
        super().__init__()
        self.signals = _EngineTaskSignals()
        self._operation = operation

    def run(self) -> None:
        try:
            result = self._operation(self.signals.progress.emit)
        except HTTPError as exc:
            if exc.code == 404:
                result = {"ok": False, "error": "FLUKE GitHub Release 尚未发布引擎更新清单。"}
            else:
                result = {"ok": False, "error": f"检查引擎更新失败（HTTP {exc.code}）。"}
        except (URLError, TimeoutError, OSError) as exc:
            result = {"ok": False, "error": f"无法连接引擎更新服务：{exc}"}
        except (ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            result = {"ok": False, "error": str(exc) or "引擎更新包校验失败。"}
        except Exception as exc:  # Keep unexpected package failures out of the GUI event loop.
            result = {"ok": False, "error": f"引擎操作失败：{exc}"}
        self.signals.finished.emit(result)


class ConverterEngineUpdateBridge(QObject):
    """QML-facing async checker and updater for app-local converter engines."""

    stateChanged = Signal()
    engineUpdated = Signal(str)

    def __init__(self, data_root: Path | None = None) -> None:
        super().__init__()
        self._update_root = (data_root or user_engine_root()).resolve()
        self._cache_root = self._update_root / "downloads"
        self._remote: dict[str, Any] = {}
        self._busy = False
        self._status_message = "可在这里查看和更新随应用携带的转换引擎。"
        self._progress = 0
        self._pool = QThreadPool(self)
        self._task: _EngineTask | None = None

    def _installed(self, engine_id: str) -> tuple[str, str]:
        active = _active_update_record(engine_id, self._update_root)
        root = Path(active["path"]) if active else bundled_engines_root() / engine_id
        metadata = _load_engine_metadata(root if root.is_dir() else None)
        executable = root.joinpath(*ENGINE_SPECS[engine_id]["executable"].split("/"))
        if (
            root.is_dir()
            and executable.is_file()
            and (root / "THIRD-PARTY-NOTICES.md").is_file()
            and metadata.get("id") == engine_id
            and isinstance(metadata.get("version"), str)
        ):
            return str(metadata["version"]), "随包" if not active else "已更新"
        return "", "未内置"

    def _previous_version(self, engine_id: str) -> dict[str, str] | None:
        active = _active_update_record(engine_id, self._update_root)
        if active is None:
            return None
        current_key = _version_key(active["version"])
        candidates: list[dict[str, str]] = []
        component_parent = self._update_root / engine_id
        if component_parent.is_dir():
            for folder in component_parent.iterdir():
                if not folder.is_dir() or folder.name == active["directory"] or folder.name.startswith("."):
                    continue
                if not re.fullmatch(r"[A-Za-z0-9._+-]{1,160}", folder.name):
                    continue
                metadata = _load_engine_metadata(folder)
                version = metadata.get("version")
                executable = folder.joinpath(*ENGINE_SPECS[engine_id]["executable"].split("/"))
                if (
                    metadata.get("id") == engine_id
                    and isinstance(version, str)
                    and _version_key(version) < current_key
                    and executable.is_file()
                    and (folder / "THIRD-PARTY-NOTICES.md").is_file()
                ):
                    candidates.append({"directory": folder.name, "version": version})
        bundled_root = bundled_engines_root() / engine_id
        bundled_metadata = _load_engine_metadata(bundled_root)
        bundled_version = bundled_metadata.get("version")
        bundled_executable = bundled_root.joinpath(*ENGINE_SPECS[engine_id]["executable"].split("/"))
        if (
            bundled_metadata.get("id") == engine_id
            and isinstance(bundled_version, str)
            and _version_key(bundled_version) < current_key
            and bundled_executable.is_file()
            and (bundled_root / "THIRD-PARTY-NOTICES.md").is_file()
        ):
            candidates.append({"directory": "", "version": bundled_version})
        return max(candidates, key=lambda item: _version_key(item["version"])) if candidates else None

    def _snapshot(self) -> dict[str, Any]:
        rows = []
        for engine_id in ENGINE_IDS:
            spec = ENGINE_SPECS[engine_id]
            local_version, local_source = self._installed(engine_id)
            remote = self._remote.get("components", {}).get(engine_id, {})
            remote_version = str(remote.get("version") or "")
            available = bool(remote_version) and (
                not local_version or _version_key(remote_version) > _version_key(local_version)
            )
            previous = self._previous_version(engine_id)
            rows.append({
                "id": engine_id,
                "label": spec["label"],
                "description": spec["description"],
                "installedVersion": local_version,
                "installedSource": local_source,
                "availableVersion": remote_version,
                "updateAvailable": available,
                "downloadSize": int(remote.get("sizeBytes") or 0),
                "canRollback": previous is not None,
                "previousVersion": previous["version"] if previous else "",
                "licenseNoticeAvailable": bool(
                    (component_root(engine_id) / "THIRD-PARTY-NOTICES.md").is_file()
                    if component_root(engine_id) else False
                ),
            })
        return {
            "engines": rows,
            "busy": self._busy,
            "progress": self._progress,
            "statusMessage": self._status_message,
            "releaseTag": str(self._remote.get("releaseTag") or ""),
        }

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return self._snapshot()

    def _begin(
        self,
        operation: Callable[[Callable[[str, int], None]], dict[str, Any]],
        fallback_status: str,
    ) -> None:
        if self._busy:
            return
        self._busy = True
        self._progress = 0
        self._status_message = fallback_status
        task = _EngineTask(operation)
        task.signals.progress.connect(self._on_progress)
        task.signals.finished.connect(self._on_finished)
        self._task = task
        self.stateChanged.emit()
        self._pool.start(task)

    @Slot(str, int)
    def _on_progress(self, message: str, percentage: int) -> None:
        self._status_message = message
        self._progress = max(0, min(100, int(percentage)))
        self.stateChanged.emit()

    @Slot(object)
    def _on_finished(self, result: object) -> None:
        info = result if isinstance(result, dict) else {"ok": False, "error": "引擎操作没有返回结果。"}
        self._busy = False
        self._task = None
        self._progress = 100 if info.get("ok") else 0
        self._status_message = str(info.get("message") or info.get("error") or "操作完成。")
        if info.get("engines"):
            self._remote = info["engines"]
        engine_id = info.get("engineId")
        if info.get("ok") and engine_id in ENGINE_SPECS:
            self.engineUpdated.emit(str(engine_id))
        self.stateChanged.emit()

    @Slot()
    def checkForUpdates(self) -> None:
        def operation(report: Callable[[str, int], None]) -> dict[str, Any]:
            report("正在检查 FLUKE 转换引擎更新……", 10)
            manifest = _read_update_manifest()
            return {
                "ok": True,
                "message": "已检查引擎更新。",
                "engines": manifest,
            }
        self._begin(operation, "正在检查引擎更新……")

    @Slot(str)
    def installOrUpdate(self, engine_id: str) -> None:
        if engine_id not in ENGINE_SPECS:
            self._status_message = "不支持这个转换引擎。"
            self.stateChanged.emit()
            return
        component = self._remote.get("components", {}).get(engine_id)
        if not isinstance(component, dict):
            self._status_message = "请先检查更新，当前没有该引擎的发布包。"
            self.stateChanged.emit()
            return
        local_version, _ = self._installed(engine_id)
        if local_version and _version_key(component["version"]) <= _version_key(local_version):
            self._status_message = f"{ENGINE_SPECS[engine_id]['label']} 已是最新版本。"
            self.stateChanged.emit()
            return

        def operation(report: Callable[[str, int], None]) -> dict[str, Any]:
            self._update_root.mkdir(parents=True, exist_ok=True)
            download = _download_verified(component, self._cache_root, report)
            staging = self._update_root / engine_id / f".staging-{threading.get_ident()}"
            try:
                extracted = _extract_component(download.path, component, staging, report)
                folder = f"{component['version']}-{component['sha256'][:12]}"
                target = self._update_root / engine_id / folder
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    existing = _load_engine_metadata(target)
                    if existing.get("sha256") != component["sha256"]:
                        raise ValueError("目标版本目录已存在但校验值不同，旧组件保持不变。")
                    shutil.rmtree(extracted, ignore_errors=True)
                else:
                    os.replace(extracted, target)
                self._activate(engine_id, folder, component["version"])
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            finally:
                download.path.unlink(missing_ok=True)
            report(f"{ENGINE_SPECS[engine_id]['label']} 已安装。", 100)
            return {
                "ok": True,
                "message": f"{ENGINE_SPECS[engine_id]['label']} 已更新到 {component['version']}。",
                "engineId": engine_id,
            }
        self._begin(operation, f"正在准备 {ENGINE_SPECS[engine_id]['label']}……")

    def _activate(self, engine_id: str, directory: str, version: str) -> None:
        current_path = self._update_root / "active.json"
        try:
            current = json.loads(current_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        current[engine_id] = {"directory": directory, "version": version}
        self._update_root.mkdir(parents=True, exist_ok=True)
        temporary = self._update_root / f".active-{threading.get_ident()}.tmp"
        temporary.write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, current_path)

    def _deactivate(self, engine_id: str) -> None:
        current_path = self._update_root / "active.json"
        try:
            current = json.loads(current_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        current.pop(engine_id, None)
        self._update_root.mkdir(parents=True, exist_ok=True)
        temporary = self._update_root / f".active-{threading.get_ident()}.tmp"
        temporary.write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, current_path)

    @Slot(str)
    def rollbackEngine(self, engine_id: str) -> None:
        if engine_id not in ENGINE_SPECS or self._busy:
            return
        previous = self._previous_version(engine_id)
        if previous is None:
            self._status_message = "没有可恢复的旧版引擎。"
            self.stateChanged.emit()
            return
        if previous["directory"]:
            self._activate(engine_id, previous["directory"], previous["version"])
        else:
            self._deactivate(engine_id)
        self._status_message = f"{ENGINE_SPECS[engine_id]['label']} 已恢复到 {previous['version']}。"
        self.engineUpdated.emit(engine_id)
        self.stateChanged.emit()

    @Slot(str)
    def openLicenseNotice(self, engine_id: str) -> None:
        root = component_root(engine_id)
        notice = root / "THIRD-PARTY-NOTICES.md" if root else None
        if notice is None or not notice.is_file():
            self._status_message = "此引擎尚无随包许可说明。"
            self.stateChanged.emit()
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(notice.resolve()))):
            self._status_message = "无法打开许可说明文件。"
            self.stateChanged.emit()
