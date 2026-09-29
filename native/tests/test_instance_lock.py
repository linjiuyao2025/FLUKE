from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from wanxiang.instance_lock import PlannerDatabaseInstanceLock


class PlannerDatabaseInstanceLockTests(unittest.TestCase):
    def test_only_one_live_instance_can_hold_a_database_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "planner.sqlite3"
            first = PlannerDatabaseInstanceLock(database)
            second = PlannerDatabaseInstanceLock(database)

            self.assertTrue(first.acquire())
            self.assertTrue(first.lock_path.exists())
            self.assertFalse(second.acquire())

            first.release()
            self.assertFalse(first.lock_path.exists())
            self.assertTrue(second.acquire())
            second.release()

    def test_instances_using_different_databases_do_not_block_each_other(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = PlannerDatabaseInstanceLock(Path(directory) / "first.sqlite3")
            second = PlannerDatabaseInstanceLock(Path(directory) / "second.sqlite3")
            self.assertTrue(first.acquire())
            self.assertTrue(second.acquire())
            second.release()
            first.release()


if __name__ == "__main__":
    unittest.main()
