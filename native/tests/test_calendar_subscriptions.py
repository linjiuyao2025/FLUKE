from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from wanxiang.calendar_subscriptions import (
    CalendarSubscriptionError,
    normalize_subscription_url,
    protect_subscription_url,
    unprotect_subscription_url,
)
from wanxiang.planner import PlannerRepository, PlannerRepositoryError
from main import PlannerBridge

from PySide6.QtWidgets import QApplication


def _source() -> dict[str, object]:
    return {"richangji-state-v1": {"records": [], "settings": {}, "drafts": {"plannerForm": {}}}}


def _feed(summary: str = "Team review", *, include_holiday: bool = True) -> str:
    holiday = (
        "BEGIN:VEVENT\r\nUID:holiday@example.test\r\n"
        "DTSTART;VALUE=DATE:20260929\r\nDTEND;VALUE=DATE:20260930\r\n"
        "SUMMARY:Holiday\r\nEND:VEVENT\r\n"
        if include_holiday else ""
    )
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:Provider calendar\r\n"
        "BEGIN:VEVENT\r\nUID:review@example.test\r\n"
        "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
        "DTEND;TZID=Asia/Shanghai:20260928T100000\r\n"
        f"SUMMARY:{summary}\r\nEND:VEVENT\r\n"
        f"{holiday}END:VCALENDAR\r\n"
    )


def _empty_feed() -> str:
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"


class CalendarSubscriptionUrlTests(unittest.TestCase):
    def test_webcal_is_upgraded_and_token_query_is_preserved(self) -> None:
        url, host = normalize_subscription_url("webcal://Calendar.Example.test/feed?id=private-token#view")
        self.assertEqual(url, "https://Calendar.Example.test/feed?id=private-token")
        self.assertEqual(host, "calendar.example.test")

    def test_rejects_credentials_bad_scheme_and_malformed_address(self) -> None:
        for value in (
            "ftp://calendar.example.test/feed.ics",
            "https://user:pass@calendar.example.test/private.ics",
            "https://calendar.example.test/with space.ics",
            "https:///missing-host.ics",
            "https://calendar.example.test:70000/feed.ics",
        ):
            with self.subTest(value=value), self.assertRaises(CalendarSubscriptionError):
                normalize_subscription_url(value)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is available only on Windows")
    def test_dpapi_ciphertext_round_trips_without_exposing_feed_token(self) -> None:
        url = "https://calendar.example.test/private.ics?token=secret-calendar-key"
        ciphertext = protect_subscription_url(url)
        self.assertNotIn("secret-calendar-key", ciphertext)
        self.assertEqual(unprotect_subscription_url(ciphertext), url)


class CalendarSubscriptionRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fluke-calendar-subscriptions-")
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "planner.sqlite3"
        self.now = datetime(2026, 9, 28, 8, 0, tzinfo=timezone(timedelta(hours=8)))
        self.repo = PlannerRepository(self.path, _source(), clock=lambda: self.now)
        self.subscription = self.repo.add_calendar_subscription(
            "Team meetings", "calendar.example.test", "opaque-protected-value"
        )

    def test_subscription_url_is_private_and_state_survives_restart(self) -> None:
        self.assertNotIn("urlProtected", self.repo.state()["calendarSubscriptions"][0])
        details = self.repo.calendar_subscription_details(self.subscription["id"])
        self.assertEqual(details["urlProtected"], "opaque-protected-value")

        reopened = PlannerRepository(self.path, clock=lambda: self.now)
        self.assertEqual(reopened.state()["calendarSubscriptions"][0]["name"], "Team meetings")
        self.assertEqual(
            reopened.calendar_subscription_details(self.subscription["id"])["urlProtected"],
            "opaque-protected-value",
        )

    def test_refresh_replaces_only_its_feed_and_uses_scoped_event_ids(self) -> None:
        manual = self.repo.import_calendar(_feed(), "manual.ics")
        self.assertEqual(manual["added"], 2)
        first = self.repo.replace_calendar_subscription_events(
            self.subscription["id"], _feed(), '"v1"', "Mon, 28 Sep 2026 00:00:00 GMT"
        )
        self.assertEqual((first["added"], first["removed"], first["total"]), (2, 0, 2))
        subscribed_events = [
            item for item in self.repo._state["calendarEvents"]
            if item.get("subscriptionId") == self.subscription["id"]
        ]
        self.assertEqual(len(subscribed_events), 2)
        self.assertNotEqual(
            {item["uid"] for item in subscribed_events},
            {"review@example.test", "holiday@example.test"},
        )

        updated = self.repo.replace_calendar_subscription_events(
            self.subscription["id"], _feed("Updated review", include_holiday=False), '"v2"', "Tue, 29 Sep 2026 00:00:00 GMT"
        )
        self.assertEqual(
            (updated["added"], updated["updated"], updated["removed"], updated["total"]),
            (0, 1, 1, 1),
        )
        self.repo.set_selected_day("2026-09-28")
        events = self.repo.state()["calendarEvents"]
        self.assertEqual(len(events), 2)
        self.assertEqual({item["title"] for item in events}, {"Team review", "Updated review"})
        self.assertEqual(
            sum(item.get("subscriptionId") == self.subscription["id"] for item in events), 1
        )

    def test_not_modified_and_failure_keep_cached_events(self) -> None:
        self.repo.replace_calendar_subscription_events(self.subscription["id"], _feed(), '"v1"')
        self.assertTrue(self.repo.record_calendar_subscription_not_modified(
            self.subscription["id"], '"v1"', "Mon, 28 Sep 2026 00:00:00 GMT"
        ))
        before = [
            item for item in self.repo._state["calendarEvents"]
            if item.get("subscriptionId") == self.subscription["id"]
        ]
        self.assertTrue(self.repo.mark_calendar_subscription_error(
            self.subscription["id"], "Network unavailable; cached events remain."
        ))
        after = [
            item for item in self.repo._state["calendarEvents"]
            if item.get("subscriptionId") == self.subscription["id"]
        ]
        self.assertEqual(before, after)
        visible = self.repo.state()["calendarSubscriptions"][0]
        self.assertIn("Network unavailable", visible["lastError"])
        self.assertEqual(visible["eventCount"], 2)

    def test_invalid_refresh_is_atomic_and_empty_feed_removes_only_subscription_events(self) -> None:
        self.repo.import_calendar(_feed(), "manual.ics")
        self.repo.replace_calendar_subscription_events(self.subscription["id"], _feed(), '"v1"')
        before = list(self.repo._state["calendarEvents"])
        with self.assertRaises(PlannerRepositoryError):
            self.repo.replace_calendar_subscription_events(self.subscription["id"], "not ICS", '"v2"')
        self.assertEqual(self.repo._state["calendarEvents"], before)

        result = self.repo.replace_calendar_subscription_events(
            self.subscription["id"], _empty_feed(), '"v3"'
        )
        self.assertEqual((result["total"], result["removed"]), (0, 2))
        remaining = self.repo._state["calendarEvents"]
        self.assertEqual(len(remaining), 2)
        self.assertTrue(all(not item.get("subscriptionId") for item in remaining))

    def test_remove_subscription_removes_cache_but_keeps_manual_import(self) -> None:
        self.repo.import_calendar(_feed(), "manual.ics")
        self.repo.replace_calendar_subscription_events(self.subscription["id"], _feed(), '"v1"')
        self.assertTrue(self.repo.remove_calendar_subscription(self.subscription["id"]))
        self.assertEqual(len(self.repo._state["calendarEvents"]), 2)
        self.assertEqual(self.repo.state()["calendarSubscriptions"], [])


class CalendarSubscriptionNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fluke-calendar-network-")
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "planner.sqlite3"
        state = {"status": 200, "etag": '"v1"', "body": _feed(), "requests": []}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
                state["requests"].append(dict(self.headers.items()))
                if self.headers.get("If-None-Match") == state["etag"] and state["status"] == 200:
                    self.send_response(304)
                    self.send_header("ETag", state["etag"])
                    self.end_headers()
                    return
                body = str(state["body"]).encode("utf-8")
                self.send_response(int(state["status"]))
                self.send_header("ETag", str(state["etag"]))
                self.send_header("Last-Modified", "Mon, 28 Sep 2026 00:00:00 GMT")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if int(state["status"]) == 200:
                    self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.server_state = state
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self._stop_server)
        self.bridge = PlannerBridge(self.path)
        self.addCleanup(self.bridge.deleteLater)

    def _stop_server(self) -> None:
        if hasattr(self, "server"):
            self.server.shutdown()
            self.server.server_close()
            self.server_thread.join(timeout=2)

    def _wait_until_idle(self, subscription_id: str, timeout: float = 5.0) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            subscription = next(
                item for item in self.bridge.state["calendarSubscriptions"]
                if item["id"] == subscription_id
            )
            if not subscription.get("refreshing"):
                return subscription
            time.sleep(0.01)
        self.fail("calendar subscription network request did not finish")

    def test_http_feed_refresh_304_failure_and_update_preserve_cache_rules(self) -> None:
        url = f"http://127.0.0.1:{self.server.server_port}/team.ics?token=local-test"
        result = self.bridge.addCalendarSubscription("Team", url)
        self.assertTrue(result["ok"], result)
        subscription_id = result["state"]["calendarSubscriptions"][0]["id"]
        first = self._wait_until_idle(subscription_id)
        self.assertEqual(first["eventCount"], 2)
        self.assertEqual(first["lastError"], "")
        self.assertNotIn("local-test", repr(self.bridge.state["calendarSubscriptions"]))

        self.bridge.refreshCalendarSubscription(subscription_id)
        unchanged = self._wait_until_idle(subscription_id)
        self.assertEqual(unchanged["eventCount"], 2)
        self.assertEqual(len(self.server_state["requests"]), 2)
        self.assertEqual(self.server_state["requests"][1].get("If-None-Match"), '"v1"')

        self.server_state["status"] = 503
        self.bridge.refreshCalendarSubscription(subscription_id)
        failed = self._wait_until_idle(subscription_id)
        self.assertIn("HTTP 503", failed["lastError"])
        self.assertEqual(failed["eventCount"], 2)

        self.server_state.update({
            "status": 200,
            "etag": '"v2"',
            "body": _feed("Updated review", include_holiday=False),
        })
        self.bridge.refreshCalendarSubscription(subscription_id)
        updated = self._wait_until_idle(subscription_id)
        self.assertEqual(updated["eventCount"], 1)
        self.assertEqual(updated["lastError"], "")
        events = [
            item for item in self.bridge._repository.state("2026-09-28")["calendarEvents"]
            if item.get("subscriptionId") == subscription_id
        ]
        self.assertEqual([event["title"] for event in events], ["Updated review"])

        self.server_state.update({
            "status": 200,
            "etag": '"oversized"',
            "body": _feed("Too large") + ("X" * (2_000_001)),
        })
        self.bridge.refreshCalendarSubscription(subscription_id)
        oversized = self._wait_until_idle(subscription_id)
        self.assertIn("2 MB", oversized["lastError"])
        self.assertEqual(oversized["eventCount"], 1)
