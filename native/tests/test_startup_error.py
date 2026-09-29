from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class StartupErrorTests(unittest.TestCase):
    def test_health_check_reports_corrupt_database_without_overwriting(self) -> None:
        native_dir = Path(__file__).resolve().parents[1]
        original = b"this is not sqlite"
        with tempfile.TemporaryDirectory(prefix="fluke-startup-error-") as temporary:
            root = Path(temporary)
            database = root / "corrupt.sqlite3"
            database.write_bytes(original)
            environment = os.environ.copy()
            environment.update({
                "APPDATA": str(root / "appdata"),
                "LOCALAPPDATA": str(root / "localappdata"),
                "QT_QPA_PLATFORM": "offscreen",
                "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu",
            })
            result = subprocess.run(
                [
                    sys.executable,
                    str(native_dir / "main.py"),
                    "--health-check",
                    "--database",
                    str(database),
                ],
                cwd=native_dir,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            preserved = database.read_bytes()

        self.assertEqual(result.returncode, 1)
        self.assertIn("无法读取本机数据库", result.stderr)
        self.assertIn("没有覆盖原文件", result.stderr)
        self.assertEqual(preserved, original)


if __name__ == "__main__":
    unittest.main()
