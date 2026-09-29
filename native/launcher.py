"""Small side-by-side launcher for the FLUKE Native Windows installer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from typing import Any
import uuid


POINTER_NAME = "active.json"
READY_NAME = ".install-complete.json"
VERSIONS_NAME = "versions"
HEALTH_TIMEOUT_SECONDS = 60
STARTUP_GRACE_SECONDS = 8


def _version_key(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError("invalid FLUKE version")
    return tuple(int(part) for part in parts)  # type: ignore[return-value]


def _root(executable: Path | None = None) -> Path:
    return (executable or Path(sys.executable)).resolve().parent


def _versions_root(root: Path) -> Path:
    return root / VERSIONS_NAME


def _version_dir(root: Path, version: str) -> Path:
    _version_key(version)
    candidate = (_versions_root(root) / version).resolve()
    versions = _versions_root(root).resolve()
    if candidate.parent != versions:
        raise ValueError("invalid FLUKE version directory")
    return candidate


def _ready_versions(root: Path) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    versions = _versions_root(root)
    if not versions.is_dir():
        return result
    for directory in versions.iterdir():
        if not directory.is_dir():
            continue
        try:
            version = directory.name
            _version_key(version)
            executable = _version_dir(root, version) / "FLUKE.exe"
        except ValueError:
            continue
        if (directory / READY_NAME).is_file() and executable.is_file():
            result.append((version, executable))
    return sorted(result, key=lambda item: _version_key(item[0]), reverse=True)


def _read_pointer(root: Path) -> dict[str, Any]:
    try:
        payload = json.loads((root / POINTER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_pointer(root: Path, version: str, previous: str | None) -> None:
    payload = {"version": version, "previousVersion": previous, "updatedAt": int(time.time())}
    temporary = root / f"{POINTER_NAME}.{uuid.uuid4().hex}.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    os.replace(temporary, root / POINTER_NAME)


def _health_check(executable: Path, root: Path) -> bool:
    health_root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "FLUKE" / "HealthChecks"
    health_root.mkdir(parents=True, exist_ok=True)
    temporary = health_root / uuid.uuid4().hex
    temporary.mkdir()
    database = temporary / "health.sqlite3"
    environment = os.environ.copy()
    environment.update({"QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"})
    try:
        completed = subprocess.run(
            [str(executable), "--health-check", "--database", str(database)],
            cwd=str(executable.parent),
            env=environment,
            capture_output=True,
            text=True,
            timeout=HEALTH_TIMEOUT_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _activate(root: Path, version: str) -> bool:
    executable = _version_dir(root, version) / "FLUKE.exe"
    marker = executable.parent / READY_NAME
    if not executable.is_file() or not marker.is_file() or not _health_check(executable, root):
        return False
    pointer = _read_pointer(root)
    previous = pointer.get("version")
    if not isinstance(previous, str) or previous == version:
        previous = pointer.get("previousVersion") if isinstance(pointer.get("previousVersion"), str) else None
    _write_pointer(root, version, previous)
    return True


def _rollback(root: Path) -> bool:
    pointer = _read_pointer(root)
    previous = pointer.get("previousVersion")
    if not isinstance(previous, str):
        return False
    return _activate(root, previous)


def _active_version(root: Path) -> tuple[str, Path] | None:
    pointer = _read_pointer(root)
    for version in (pointer.get("version"), pointer.get("previousVersion")):
        if isinstance(version, str):
            candidate = next((item for item in _ready_versions(root) if item[0] == version), None)
            if candidate is not None:
                return candidate
    ready = _ready_versions(root)
    return ready[0] if ready else None


def _start(root: Path, version: str, executable: Path) -> int:
    try:
        process = subprocess.Popen([str(executable)], cwd=str(executable.parent))
        try:
            return_code = process.wait(timeout=STARTUP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            return 0
    except OSError:
        return_code = 1
    if return_code == 0:
        return 1
    if _rollback(root):
        fallback = _active_version(root)
        if fallback is not None and fallback[0] != version:
            try:
                subprocess.Popen([str(fallback[1])], cwd=str(fallback[1].parent))
                return 0
            except OSError:
                pass
    return return_code or 1


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = _root()
    if arguments[:1] == ["--activate"]:
        if len(arguments) != 2:
            return 1
        if not _activate(root, arguments[1]):
            pointer = _read_pointer(root)
            current = pointer.get("version")
            if not isinstance(current, str) or current == arguments[1]:
                if not _rollback(root):
                    return 1
    elif arguments[:1] == ["--rollback"]:
        if not _rollback(root):
            return 1
    elif arguments:
        return 2
    active = _active_version(root)
    if active is None:
        return 1
    if not _activate(root, active[0]):
        if not _rollback(root):
            return 1
        active = _active_version(root)
        if active is None or not _activate(root, active[0]):
            return 1
    return _start(root, active[0], active[1])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        log_root = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        ) / "FLUKE" / "HealthChecks"
        try:
            log_root.mkdir(parents=True, exist_ok=True)
            (log_root / "last-launcher-exception.txt").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
        except OSError:
            pass
        raise
