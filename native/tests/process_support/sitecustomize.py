"""Test-only QML driver for the real detached backup-restart subprocess test."""

from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import traceback

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine


_control_value = os.environ.get("FLUKE_RESTART_TEST_CONTROL")
_control_dir = Path(_control_value) if _control_value else None
_scheduled = False
_restored_marker = _control_dir / "restore-confirmed.json" if _control_dir else None
_child_result = _control_dir / "child-readback.json" if _control_dir else None


if _control_dir is not None:
    expected_database = Path(os.environ["FLUKE_RESTART_TEST_DATABASE"]).resolve()
    from wanxiang import database as _database_module
    import migrate_legacy as _legacy_module

    _original_initialize_database = _database_module.initialize_database

    def _guarded_initialize_database(path: str | Path, *args: object, **kwargs: object) -> object:
        if Path(path).expanduser().resolve() != expected_database:
            raise RuntimeError("restart test refused a database outside its synthetic temp directory")
        return _original_initialize_database(path, *args, **kwargs)

    def _forbid_default_database_path() -> Path:
        raise RuntimeError("restart test requires the explicit isolated --database argument")

    _database_module.initialize_database = _guarded_initialize_database
    _legacy_module.default_database_path = _forbid_default_database_path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _record_failure(path: Path, exc: BaseException) -> None:
    _write_json(path, {"error": str(exc), "traceback": traceback.format_exc()})
    app = QApplication.instance()
    if app is not None:
        app.exit(7)


if _control_dir is not None and _restored_marker is not None and _restored_marker.is_file():
    atexit.register(lambda: (_control_dir / "child-exited.txt").write_text("exited", encoding="utf-8"))


_original_load = QQmlApplicationEngine.load


def _load_and_schedule(self: QQmlApplicationEngine, *args: object) -> object:
    global _scheduled
    result = _original_load(self, *args)
    if _scheduled or _control_dir is None or _restored_marker is None or not _control_dir.is_dir():
        return result
    _scheduled = True
    if _restored_marker.is_file():
        QTimer.singleShot(450, lambda: _verify_child(self))
    else:
        QTimer.singleShot(450, lambda: _confirm_restore(self))
    return result


def _confirm_restore(engine: QQmlApplicationEngine) -> None:
    if _control_dir is None or _restored_marker is None:
        return
    try:
        root = engine.rootObjects()[0]
        backup_path = Path(os.environ["FLUKE_RESTART_TEST_BACKUP"])
        invoked = QMetaObject.invokeMethod(
            root,
            "showFullBackupPreview",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", QUrl.fromLocalFile(str(backup_path))),
        )
        if not invoked:
            raise RuntimeError("production QML backup preview handler was not invokable")
        button = root.findChild(QObject, "backupPreviewConfirmButton")
        if button is None:
            raise RuntimeError("production QML restore confirmation button was not found")
        clicked = QMetaObject.invokeMethod(
            button, "click", Qt.ConnectionType.DirectConnection
        )
        if not clicked:
            raise RuntimeError("production QML restore confirmation could not be clicked")
        # The click can synchronously request app.quit(), so create the phase
        # marker before doing any further assertions. This keeps a failed
        # parent verification from re-triggering restore in every child.
        _write_json(_restored_marker, {"pid": os.getpid(), "confirmed": True})
        from wanxiang.database import load_imported_data

        restored = load_imported_data(Path(os.environ["FLUKE_RESTART_TEST_DATABASE"]))
        record_ids = [
            str(row.get("id", ""))
            for row in restored.get("entities", {}).get("records", [])
        ]
        expected_id = os.environ["FLUKE_RESTART_TEST_RECORD_ID"]
        if expected_id not in record_ids:
            raise RuntimeError("confirmed production restore did not write the expected record")
    except BaseException as exc:
        _record_failure(_control_dir / "parent-failure.json", exc)


def _verify_child(engine: QQmlApplicationEngine) -> None:
    if _control_dir is None or _child_result is None:
        return
    try:
        root = engine.rootObjects()[0]
        root.setProperty("currentSectionIndex", 1)

        def readback() -> None:
            try:
                finance_page = root.findChild(QObject, "financePage")
                if finance_page is None:
                    raise RuntimeError("fresh process did not create FinancePage")
                snapshot = finance_page.property("snapshot")
                records = snapshot["records"]
                record_ids = [str(row.get("id", "")) for row in records]
                _write_json(_child_result, {
                    "pid": os.getpid(),
                    "databasePath": str(Path(os.environ["FLUKE_RESTART_TEST_DATABASE"]).resolve()),
                    "recordIds": record_ids,
                    "snapshotRecordCount": len(records),
                })
            except BaseException as exc:
                _record_failure(_control_dir / "child-failure.json", exc)

        QTimer.singleShot(350, readback)
    except BaseException as exc:
        _record_failure(_control_dir / "child-failure.json", exc)


QQmlApplicationEngine.load = _load_and_schedule
