from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from wanxiang.backup import export_backup
from wanxiang.database import import_package, load_imported_data
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _package_with_record(record_id: str) -> object:
    state = {
        "records": [{
            "id": record_id,
            "type": "money",
            "date": date.today().isoformat(),
            "createdAt": 1,
            "sample": False,
            "data": {"amount": 23, "flow": "expense", "note": "synthetic process restart"},
        }],
        "habits": [],
        "mediaItems": [],
        "settings": {},
    }
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    raw_values["richangji-state-v1"] = json.dumps(state, ensure_ascii=False)
    return validate_package({
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-process-restart",
        "exportedAt": "2026-09-28T10:00:00Z",
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    })


class BackupProcessRestartTests(unittest.TestCase):
    """Exercise the production detached restart with two isolated app processes."""

    def test_native_backup_restore_starts_new_process_that_reads_restored_finance_page(self) -> None:
        self._assert_process_restore(legacy_json=False)

    def test_legacy_json_restore_starts_new_process_that_reads_restored_finance_page(self) -> None:
        self._assert_process_restore(legacy_json=True)

    def _assert_process_restore(self, *, legacy_json: bool) -> None:
        native_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="fluke-backup-process-restart-") as directory:
            root = Path(directory)
            control = root / "control"
            control.mkdir()
            database = root / "target.sqlite3"
            backup_database = root / "backup-source.sqlite3"
            backup_path = root / ("restore.json" if legacy_json else "restore.wxbak")
            capture_path = root / "restarted-window.png"

            import_package(_package_with_record("target-before-restore"), database)
            import_package(_package_with_record("process-restored-row"), backup_database)
            if legacy_json:
                backup_path.write_text(json.dumps({
                    "format": "daily-atlas-backup",
                    "version": 1,
                    "exportedAt": "2026-09-28T10:00:00.000Z",
                    "state": {
                        "records": [{
                            "id": "process-restored-row",
                            "type": "money",
                            "date": date.today().isoformat(),
                            "createdAt": 1,
                            "sample": False,
                            "data": {
                                "amount": 23,
                                "flow": "expense",
                                "note": "synthetic process restart",
                            },
                        }],
                        "habits": [],
                        "mediaItems": [],
                        "settings": {},
                    },
                    "issueContent": {"active": None, "archive": []},
                }, ensure_ascii=False), encoding="utf-8")
            else:
                export_backup(backup_database, backup_path)

            helper_dir = native_dir / "tests" / "process_support"
            env = os.environ.copy()
            env.update({
                "QT_QPA_PLATFORM": "offscreen",
                "FLUKE_RESTART_TEST_CONTROL": str(control),
                "FLUKE_RESTART_TEST_BACKUP": str(backup_path),
                "FLUKE_RESTART_TEST_DATABASE": str(database),
                "FLUKE_RESTART_TEST_RECORD_ID": "process-restored-row",
                "QML_DISK_CACHE_PATH": str(root / "qml-cache"),
                "LOCALAPPDATA": str(root / "appdata" / "Local"),
                "APPDATA": str(root / "appdata" / "Roaming"),
            })
            existing_pythonpath = env.get("PYTHONPATH", "")
            pythonpath_items = [str(helper_dir), str(native_dir)]
            if existing_pythonpath:
                pythonpath_items.append(existing_pythonpath)
            env["PYTHONPATH"] = os.pathsep.join(pythonpath_items)

            command = [
                sys.executable,
                str(native_dir / "main.py"),
                "--database",
                str(database),
                "--capture",
                str(capture_path),
                "--size",
                "760x620",
            ]
            completed = subprocess.run(
                command,
                cwd=native_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"parent app exited {completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )

            marker_path = control / "restore-confirmed.json"
            self.assertTrue(marker_path.is_file(), "production QML restore was not confirmed")
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertTrue(marker["confirmed"])
            self.assertNotEqual(marker["pid"], os.getpid())

            readback_path = control / "child-readback.json"
            child_exited_path = control / "child-exited.txt"
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not child_exited_path.exists():
                if (control / "parent-failure.json").exists():
                    break
                if (control / "child-failure.json").exists():
                    break
                time.sleep(0.05)

            if (control / "parent-failure.json").exists():
                self.fail((control / "parent-failure.json").read_text(encoding="utf-8"))
            if (control / "child-failure.json").exists():
                self.fail((control / "child-failure.json").read_text(encoding="utf-8"))
            self.assertTrue(readback_path.is_file(), "QProcess did not launch a child that read back the DB")
            self.assertTrue(child_exited_path.is_file(), "restarted app did not exit through --capture")

            child = json.loads(readback_path.read_text(encoding="utf-8"))
            self.assertNotEqual(child["pid"], marker["pid"], "restart must use a distinct process")
            self.assertEqual(child["databasePath"], str(database.resolve()))
            self.assertIn("process-restored-row", child["recordIds"])
            self.assertNotIn("target-before-restore", child["recordIds"])
            self.assertTrue(capture_path.is_file(), "restarted production window did not capture")
            self.assertGreater(capture_path.stat().st_size, 0)

            restored = load_imported_data(database)
            self.assertEqual(restored["entities"]["records"][0]["id"], "process-restored-row")


if __name__ == "__main__":
    unittest.main()
