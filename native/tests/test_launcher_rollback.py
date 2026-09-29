from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

try:
    from native import launcher
except ImportError:
    import launcher


def ready_version(root: Path, version: str) -> Path:
    directory = root / "versions" / version
    directory.mkdir(parents=True)
    executable = directory / "FLUKE.exe"
    executable.write_bytes(b"fixture")
    (directory / launcher.READY_NAME).write_text(
        json.dumps({"version": version}), encoding="utf-8"
    )
    return executable


class LauncherRollback(unittest.TestCase):
    def test_incomplete_version_is_never_selected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ready_version(root, "0.1.1")
            incomplete = root / "versions" / "0.1.2"
            incomplete.mkdir(parents=True)
            (incomplete / "FLUKE.exe").write_bytes(b"partial")
            self.assertEqual([item[0] for item in launcher._ready_versions(root)], ["0.1.1"])

    def test_activation_records_previous_and_rollback_keeps_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            launcher, "_health_check", return_value=True
        ):
            root = Path(temporary)
            ready_version(root, "0.1.1")
            ready_version(root, "0.1.2")
            self.assertTrue(launcher._activate(root, "0.1.1"))
            self.assertTrue(launcher._activate(root, "0.1.2"))
            self.assertEqual(json.loads((root / launcher.POINTER_NAME).read_text())["version"], "0.1.2")
            self.assertEqual(json.loads((root / launcher.POINTER_NAME).read_text())["previousVersion"], "0.1.1")
            self.assertTrue(launcher._rollback(root))
            pointer = json.loads((root / launcher.POINTER_NAME).read_text())
            self.assertEqual(pointer["version"], "0.1.1")
            self.assertTrue((root / "versions" / "0.1.2" / "FLUKE.exe").is_file())

    def test_failed_first_start_returns_to_previous_ready_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            launcher, "_health_check", return_value=True
        ), patch.object(
            launcher.subprocess, "Popen",
            side_effect=[
                _CompletedProcess(return_code=1),
                _RunningProcess(),
            ],
        ):
            root = Path(temporary)
            ready_version(root, "0.1.1")
            ready_version(root, "0.1.2")
            launcher._activate(root, "0.1.1")
            launcher._activate(root, "0.1.2")
            self.assertEqual(
                launcher._start(
                    root,
                    "0.1.2",
                    root / "versions" / "0.1.2" / "FLUKE.exe",
                ),
                0,
            )
            pointer = json.loads((root / launcher.POINTER_NAME).read_text())
            self.assertEqual(pointer["version"], "0.1.1")

    def test_failed_activation_rolls_back_before_normal_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous = ready_version(root, "0.1.1").resolve()
            ready_version(root, "0.1.2")
            (root / launcher.POINTER_NAME).write_text(
                json.dumps({"version": "0.1.1", "previousVersion": None}),
                encoding="utf-8",
            )
            with patch.object(launcher, "_root", return_value=root), patch.object(
                launcher, "_health_check", side_effect=lambda executable, _root: executable == previous
            ), patch.object(launcher, "_start", return_value=0) as start:
                self.assertEqual(launcher.main(["--activate", "0.1.2"]), 0)
            start.assert_called_once()
            self.assertEqual(start.call_args.args[1], "0.1.1")

    def test_external_sqlite_data_survives_activation_and_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            launcher, "_health_check", return_value=True
        ):
            root = Path(temporary)
            database_path = root / "user-data" / "wanxiang.sqlite3"
            database_path.parent.mkdir()
            connection = sqlite3.connect(database_path)
            connection.execute("CREATE TABLE records (value TEXT NOT NULL)")
            connection.execute("INSERT INTO records(value) VALUES (?)", ("kept",))
            connection.commit()
            connection.close()
            ready_version(root, "0.1.1")
            ready_version(root, "0.1.2")
            self.assertTrue(launcher._activate(root, "0.1.1"))
            self.assertTrue(launcher._activate(root, "0.1.2"))
            self.assertTrue(launcher._rollback(root))
            connection = sqlite3.connect(database_path)
            self.assertEqual(
                connection.execute("SELECT value FROM records").fetchone(),
                ("kept",),
            )
            connection.close()
            self.assertTrue(database_path.is_file())


class _CompletedProcess:
    def __init__(self, return_code: int) -> None:
        self.return_code = return_code

    def wait(self, timeout: int) -> int:
        return self.return_code


class _RunningProcess:
    def wait(self, timeout: int) -> int:
        raise subprocess.TimeoutExpired("FLUKE", timeout)


if __name__ == "__main__":
    unittest.main()
