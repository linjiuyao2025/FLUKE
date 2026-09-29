from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from main import _caldav_sync_is_due


class CalDAVSchedulerTests(unittest.TestCase):
    def test_missing_or_invalid_attempt_time_is_due(self) -> None:
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        self.assertTrue(_caldav_sync_is_due("", now))
        self.assertTrue(_caldav_sync_is_due("not-a-timestamp", now))

    def test_account_is_not_retried_before_one_hour(self) -> None:
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        recent = (now - timedelta(minutes=59)).isoformat()
        self.assertFalse(_caldav_sync_is_due(recent, now))
        due = (now - timedelta(hours=1)).isoformat()
        self.assertTrue(_caldav_sync_is_due(due, now))

    def test_startup_can_force_a_refresh_for_a_recently_synced_account(self) -> None:
        now = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        recent = (now - timedelta(minutes=5)).isoformat()
        self.assertFalse(_caldav_sync_is_due(recent, now))
        self.assertTrue(_caldav_sync_is_due(recent, now, force=True))


if __name__ == "__main__":
    unittest.main()
