from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class FocusTimerProcessRestartTests(unittest.TestCase):
    """Persisted focus checkpoints survive a real interpreter boundary."""

    def test_running_custom_timer_restores_checkpoint_mode_and_task_in_new_process(self) -> None:
        native_dir = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="wanxiang-focus-restart-") as directory:
            database = Path(directory) / "focus.sqlite3"
            base_time = "2026-09-27T12:00:00+08:00"
            script = r'''
import json, sys
from datetime import datetime, timedelta
from pathlib import Path
from PySide6.QtGui import QGuiApplication
from main import DailyBridge

app = QGuiApplication([])
database = Path(sys.argv[1])
mode = sys.argv[2]
base = datetime.fromisoformat(sys.argv[3])
if mode == "write":
    now = [base]
    daily = DailyBridge(database, clock=lambda: now[0])
    assert daily.setFocusMode("countdown", 45)["ok"]
    assert daily.toggleFocus("synthetic-task", "进程边界合成任务")["ok"]
    now[0] += timedelta(seconds=17)
    daily.tickFocus()
    print(json.dumps(daily.state["focusTimer"], ensure_ascii=False))
else:
    now = base + timedelta(seconds=77)
    daily = DailyBridge(database, clock=lambda: now)
    print(json.dumps(daily.state["focusTimer"], ensure_ascii=False))
    daily.close()
'''

            def invoke(action: str) -> dict[str, object]:
                environment = os.environ.copy()
                environment["QT_QPA_PLATFORM"] = "offscreen"
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import sys; sys.path.insert(0, "
                        + repr(str(native_dir))
                        + ");\n"
                        + script,
                        str(database),
                        action,
                        base_time,
                    ],
                    cwd=str(native_dir.parent),
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"subprocess {action} failed:\n{completed.stdout}\n{completed.stderr}",
                )
                lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
                self.assertTrue(lines, completed.stdout)
                return json.loads(lines[-1])

            written = invoke("write")
            self.assertEqual(written["mode"], "countdown")
            self.assertEqual(written["durationSeconds"], 2700)
            self.assertEqual(written["remainingSeconds"], 2683)
            self.assertEqual(written["elapsedSeconds"], 17)
            self.assertTrue(written["running"])
            self.assertEqual(written["taskId"], "synthetic-task")
            self.assertEqual(written["taskTitle"], "进程边界合成任务")

            restored = invoke("restore")
            self.assertEqual(restored["mode"], "countdown")
            self.assertEqual(restored["remainingSeconds"], 2623)
            self.assertEqual(restored["elapsedSeconds"], 77)
            self.assertTrue(restored["running"])
            self.assertEqual(restored["taskId"], "synthetic-task")
            self.assertEqual(restored["taskTitle"], "进程边界合成任务")


if __name__ == "__main__":
    unittest.main()
