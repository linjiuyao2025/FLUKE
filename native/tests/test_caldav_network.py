from __future__ import annotations

import base64
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from main import PlannerBridge


_PROPFIND = b'''<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response><d:href>/caldav/work/</d:href><d:propstat><d:prop>
    <d:displayname>Work calendar</d:displayname>
    <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
    <c:supported-calendar-component-set>
      <c:comp name="VEVENT"/><c:comp name="VTODO"/>
    </c:supported-calendar-component-set>
  </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
</d:multistatus>'''

_VTODO = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:Work tasks\r\n"
    "BEGIN:VTODO\r\nUID:remote-task@example.test\r\nSUMMARY:Remote task\r\n"
    "STATUS:NEEDS-ACTION\r\nPERCENT-COMPLETE:0\r\nX-CUSTOM:preserve-me\r\n"
    "END:VTODO\r\nEND:VCALENDAR\r\n"
)
_VEVENT_COMPONENT = (
    "BEGIN:VEVENT\r\nUID:remote-meeting@example.test\r\n"
    "SUMMARY:Remote meeting\r\nDTSTART:20260928T100000Z\r\n"
    "DTEND:20260928T110000Z\r\nEND:VEVENT\r\n"
)


def _with_event(calendar_data: str, title: str = "Remote meeting") -> str:
    component = _VEVENT_COMPONENT.replace("SUMMARY:Remote meeting", f"SUMMARY:{title}")
    return calendar_data.replace("END:VCALENDAR\r\n", component + "END:VCALENDAR\r\n")


def _source() -> dict[str, object]:
    return {"richangji-state-v1": {"records": [], "settings": {}, "drafts": {"plannerForm": {}}}}


class CalDAVProbeNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("CalDAV account credentials use Windows DPAPI")
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fluke-caldav-probe-")
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "planner.sqlite3"
        self.state = {
            "requests": [], "authorized": True, "redirect": False, "oversize": False,
            "calendar_data": _VTODO, "etag": '"v1"', "writes": [], "put_status": 204,
            "race_after_report": False, "sync_token": "urn:test:sync:1",
            "delta_changes": [], "deleted_paths": set(), "sync_truncated": False,
            "sync_unsupported": False, "reject_sync_token": False,
            "multiget_incomplete": False,
        }
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def do_PROPFIND(self) -> None:  # noqa: N802 - stdlib HTTP handler API
                state["requests"].append({
                    "path": self.path,
                    "depth": self.headers.get("Depth"),
                    "authorization": self.headers.get("Authorization"),
                    "content_type": self.headers.get("Content-Type"),
                })
                if state["redirect"]:
                    self.send_response(302)
                    self.send_header("Location", "/should-not-follow")
                    self.end_headers()
                    return
                if not state["authorized"]:
                    self.send_response(401)
                    self.end_headers()
                    return
                body = b" " * 512_001 if state["oversize"] else _PROPFIND
                self.send_response(207)
                self.send_header("Content-Type", "application/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self) -> None:  # noqa: N802 - should never follow credentials on redirect
                state["requests"].append({"path": self.path, "authorization": self.headers.get("Authorization")})
                self.send_response(404)
                self.end_headers()

            def do_REPORT(self) -> None:  # noqa: N802 - stdlib HTTP handler API
                request_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                entry = {
                    "method": "REPORT", "path": self.path,
                    "depth": self.headers.get("Depth"),
                    "authorization": self.headers.get("Authorization"),
                    "body": request_body,
                }
                state["requests"].append(entry)
                if not state["authorized"]:
                    self.send_response(401)
                    self.end_headers()
                    return
                if b"sync-collection" in request_body:
                    entry["kind"] = "sync-collection"
                    if state["sync_unsupported"]:
                        self.send_response(501)
                        self.end_headers()
                        return
                    request_root = ElementTree.fromstring(request_body)
                    token_node = request_root.find("{DAV:}sync-token")
                    requested_token = token_node.text or "" if token_node is not None else ""
                    entry["sync_token"] = requested_token
                    if state["reject_sync_token"] and requested_token:
                        body = b'<d:error xmlns:d="DAV:"><d:valid-sync-token/></d:error>'
                        self.send_response(403)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return
                    page_token = "urn:test:sync:page-1"
                    if state["sync_truncated"] and requested_token == "":
                        state["sync_truncated"] = False
                        sync_token = page_token
                        body = (
                            '<d:multistatus xmlns:d="DAV:"><d:response>'
                            '<d:href>/caldav/work/</d:href>'
                            '<d:status>HTTP/1.1 507 Insufficient Storage</d:status>'
                            '</d:response><d:sync-token>' + sync_token + '</d:sync-token></d:multistatus>'
                        ).encode("utf-8")
                    else:
                        if requested_token == "":
                            changes = [
                                {"href": path, "etag": state["etag"], "removed": False}
                                for path in ["/caldav/work/task.ics"]
                            ]
                            next_token = state["sync_token"]
                        elif requested_token == page_token:
                            changes = [
                                {"href": "/caldav/work/task.ics", "etag": state["etag"], "removed": False},
                            ]
                            next_token = state["sync_token"]
                        elif requested_token != state["sync_token"]:
                            changes = list(state["delta_changes"])
                            next_token = state["sync_token"]
                        else:
                            changes = []
                            next_token = state["sync_token"]
                        pieces = [
                            '<d:multistatus xmlns:d="DAV:"><d:sync-token>' + escape(next_token) + '</d:sync-token>'
                        ]
                        for item in changes:
                            href = escape(str(item["href"]))
                            if item.get("removed"):
                                pieces.append(
                                    '<d:response><d:href>' + href + '</d:href>'
                                    '<d:status>HTTP/1.1 404 Not Found</d:status></d:response>'
                                )
                            else:
                                pieces.append(
                                    '<d:response><d:href>' + href + '</d:href>'
                                    '<d:propstat><d:prop><d:getetag>' + escape(str(item["etag"])) + '</d:getetag>'
                                    '</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
                                )
                        pieces.append('</d:multistatus>')
                        body = ''.join(pieces).encode("utf-8")
                    self._send_xml(207, body)
                    return

                if b"calendar-multiget" in request_body:
                    entry["kind"] = "calendar-multiget"
                    request_root = ElementTree.fromstring(request_body)
                    hrefs = [
                        node.text or "" for node in request_root.findall("{DAV:}href")
                    ]
                    entry["hrefs"] = hrefs
                    if state["multiget_incomplete"]:
                        state["multiget_incomplete"] = False
                        self._send_xml(
                            207,
                            b'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"/>',
                        )
                        return
                    pieces = [
                        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    ]
                    response_data = []
                    for href in hrefs:
                        path = href.replace(f"http://127.0.0.1:{self.server.server_port}", "")
                        if path in state["deleted_paths"]:
                            pieces.append(
                                '<d:response><d:href>' + escape(path) + '</d:href>'
                                '<d:status>HTTP/1.1 404 Not Found</d:status></d:response>'
                            )
                            continue
                        if path != "/caldav/work/task.ics":
                            self.send_error(404)
                            return
                        calendar_data = state["calendar_data"]
                        etag = state["etag"]
                        response_data.append((path, calendar_data, etag))
                        pieces.append(
                            '<d:response><d:href>' + escape(path) + '</d:href>'
                            '<d:propstat><d:prop><d:getetag>' + escape(etag) + '</d:getetag>'
                            '<c:calendar-data>' + escape(calendar_data) + '</c:calendar-data></d:prop>'
                            '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
                        )
                    pieces.append('</d:multistatus>')
                    body = ''.join(pieces).encode("utf-8")
                    if state["race_after_report"]:
                        state["calendar_data"] = state["calendar_data"].replace(
                            "X-CUSTOM:preserve-me", "X-CUSTOM:remote-change",
                        )
                        state["etag"] = '"raced"'
                        state["race_after_report"] = False
                    self._send_xml(207, body)
                    return

                # Compatibility path used only when the server rejects RFC 6578.
                entry["kind"] = "calendar-query"
                escaped_calendar = escape(state["calendar_data"])
                body = (
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                    '<d:response><d:href>/caldav/work/task.ics</d:href>'
                    '<d:propstat><d:prop><d:getetag>' + str(state["etag"]) + '</d:getetag>'
                    '<c:calendar-data>' + escaped_calendar + '</c:calendar-data></d:prop>'
                    '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
                    '</d:multistatus>'
                ).encode("utf-8")
                self._send_xml(207, body)

            def _send_xml(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_PUT(self) -> None:  # noqa: N802 - stdlib HTTP handler API
                content = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                state["writes"].append({
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "if_match": self.headers.get("If-Match"),
                    "content_type": self.headers.get("Content-Type"),
                    "body": content.decode("utf-8"),
                })
                status = int(state["put_status"])
                if self.headers.get("If-Match") != state["etag"]:
                    status = 412
                self.send_response(status)
                if status in {200, 201, 204}:
                    state["calendar_data"] = content.decode("utf-8")
                    state["etag"] = '"v2"'
                    state["sync_token"] = "urn:test:sync:2"
                    state["delta_changes"] = [{
                        "href": "/caldav/work/task.ics", "etag": state["etag"], "removed": False,
                    }]
                    self.send_header("ETag", state["etag"])
                self.end_headers()

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.bridge = PlannerBridge(self.path, _source())
        self.addCleanup(self.bridge.deleteLater)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def _wait_idle(self, account_id: str, timeout: float = 5.0) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            account = next(
                row for row in self.bridge.state["caldavAccounts"]
                if row["id"] == account_id
            )
            if not account.get("checking"):
                return account
            time.sleep(0.01)
        self.fail("CalDAV connection check did not finish")

    def _add_account(self) -> tuple[str, dict[str, object]]:
        url = f"http://127.0.0.1:{self.server.server_port}/caldav/work/"
        result = self.bridge.addCalDAVAccount("Work", url, "alice", "app-password")
        self.assertTrue(result["ok"], result)
        account = result["state"]["caldavAccounts"][0]
        return account["id"], account

    def _wait_sync_idle(self, account_id: str, timeout: float = 5.0) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            account = next(
                row for row in self.bridge.state["caldavAccounts"]
                if row["id"] == account_id
            )
            if not account.get("syncing"):
                return account
            time.sleep(0.01)
        self.fail("CalDAV task sync did not finish")

    def test_authenticated_probe_reports_components_without_exposing_credentials(self) -> None:
        account_id, returned = self._add_account()
        account = self._wait_idle(account_id)
        self.assertEqual(account["lastError"], "")
        self.assertEqual(account["calendars"], [{
            "name": "Work calendar", "components": ["VEVENT", "VTODO"],
        }])
        self.assertNotIn("app-password", repr(returned))
        self.assertNotIn("alice", repr(returned))
        self.assertNotIn("urlProtected", repr(account))
        self.assertNotIn("credentialsProtected", repr(account))
        self.assertEqual(self.state["requests"][0]["depth"], "0")
        self.assertEqual(
            self.state["requests"][0]["authorization"],
            "Basic " + base64.b64encode(b"alice:app-password").decode("ascii"),
        )
        self.assertEqual(self.state["requests"][0]["path"], "/caldav/work/")
        self.assertNotIn(b"app-password", self.path.read_bytes())

    def test_saved_account_is_synced_when_startup_calendar_refresh_runs(self) -> None:
        self.bridge._calendar_startup_refresh_timer.stop()
        account_id, _returned = self._add_account()
        self.assertEqual(self._wait_idle(account_id)["lastError"], "")
        self.state["requests"].clear()

        self.bridge._refresh_calendar_sources_at_startup()
        account = self._wait_sync_idle(account_id)

        self.assertEqual(account["lastSyncError"], "")
        self.assertEqual(len(self.bridge.activity_records()), 1)
        self.assertTrue(any(
            item.get("kind") == "sync-collection" for item in self.state["requests"]
        ))

    def test_deleting_task_aborts_its_in_flight_completion_writeback(self) -> None:
        task = self.bridge._repository.add_task("删除时同步", "2026-09-28")
        account_id = "synthetic-account"
        job = {
            "phase": "put",
            "writebacks": [{
                "recordId": task["id"], "uid": "task@example.test", "done": True,
            }],
            "writebackIndex": 0,
        }
        reply = Mock()
        self.bridge._caldav_sync_jobs[account_id] = job
        self.bridge._caldav_sync_replies[account_id] = reply
        self.bridge._caldav_sync_buffers[account_id] = bytearray()

        result = self.bridge.deleteTask(task["id"])
        self.assertTrue(result["ok"], result)
        reply.abort.assert_called_once_with()
        self.assertEqual(job["writebacks"], [])
        self.assertNotIn(task["id"], [row["id"] for row in self.bridge._repository.records()])
        self.app.processEvents()
        self.assertNotIn(account_id, self.bridge._caldav_sync_jobs)

    def test_reauthentication_and_redirect_failures_keep_cached_discovery(self) -> None:
        account_id, _returned = self._add_account()
        first = self._wait_idle(account_id)
        self.assertEqual(len(first["calendars"]), 1)

        self.state["authorized"] = False
        self.bridge.checkCalDAVAccount(account_id)
        unauthorized = self._wait_idle(account_id)
        self.assertIn("拒绝登录", unauthorized["lastError"])
        self.assertEqual(len(unauthorized["calendars"]), 1)

        self.state.update({"authorized": True, "redirect": True})
        self.bridge.checkCalDAVAccount(account_id)
        redirected = self._wait_idle(account_id)
        self.assertIn("跳转", redirected["lastError"])
        self.assertEqual(len(redirected["calendars"]), 1)
        self.assertFalse(any(item.get("path") == "/should-not-follow" for item in self.state["requests"]))

    def test_oversize_probe_response_is_stopped_and_reported(self) -> None:
        self.state["oversize"] = True
        account_id, _returned = self._add_account()
        account = self._wait_idle(account_id)
        self.assertIn("超过 512 KB", account["lastError"])
        self.assertEqual(account["calendars"], [])

    def test_vtodo_initial_delta_sync_and_if_match_completion_writeback(self) -> None:
        account_id, _returned = self._add_account()
        account = self._wait_idle(account_id)
        self.assertEqual(account["lastError"], "")

        started = self.bridge.syncCalDAVTasks(account_id)
        self.assertTrue(started["ok"], started)
        account = self._wait_sync_idle(account_id)
        self.assertEqual(account["lastSyncError"], "")
        task = next(
            row for row in self.bridge.activity_records()
            if row["data"].get("externalTodo", {}).get("uid") == "remote-task@example.test"
        )
        self.assertFalse(task["data"]["done"])
        report = next(
            item for item in self.state["requests"]
            if item.get("kind") == "sync-collection"
        )
        self.assertEqual(report["depth"], "0")
        self.assertIn(b"sync-collection", report["body"])
        multiget = next(
            item for item in self.state["requests"]
            if item.get("kind") == "calendar-multiget"
        )
        self.assertEqual(multiget["depth"], "1")
        self.assertEqual(multiget["hrefs"], [
            f"http://127.0.0.1:{self.server.server_port}/caldav/work/task.ics",
        ])
        self.assertEqual(
            self.bridge._repository.caldav_account_details(account_id)["syncToken"],
            "urn:test:sync:1",
        )

        toggled = self.bridge.toggleTask(task["id"])
        self.assertTrue(toggled["ok"], toggled)
        started = self.bridge.syncCalDAVTasks(account_id)
        self.assertTrue(started["ok"], started)
        account = self._wait_sync_idle(account_id)
        self.assertEqual(account["lastSyncError"], "")
        self.assertEqual(len(self.state["writes"]), 1)
        write = self.state["writes"][0]
        self.assertEqual(write["if_match"], '"v1"')
        self.assertEqual(write["path"], "/caldav/work/task.ics")
        self.assertIn("STATUS:COMPLETED", write["body"])
        self.assertIn("X-CUSTOM:preserve-me", write["body"])
        current = self.bridge.activity_records()[0]["data"]
        self.assertTrue(current["done"])
        self.assertEqual(current["externalTodo"]["etag"], '"v2"')
        self.assertTrue(current["externalTodo"]["syncedDone"])
        self.assertEqual(self.state["writes"][0]["authorization"], self.state["requests"][0]["authorization"])

    def test_remote_change_between_snapshot_and_put_preserves_both_versions(self) -> None:
        account_id, _returned = self._add_account()
        self._wait_idle(account_id)
        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        self._wait_sync_idle(account_id)
        task = self.bridge.activity_records()[0]
        self.assertTrue(self.bridge.toggleTask(task["id"])["ok"])

        self.state["race_after_report"] = True
        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        account = self._wait_sync_idle(account_id)

        self.assertIn("已变化", account["lastSyncError"])
        current = self.bridge.activity_records()[0]
        self.assertTrue(current["data"]["done"], "local completion must survive a failed conditional write")
        self.assertIn("X-CUSTOM:remote-change", self.state["calendar_data"])
        self.assertIn("STATUS:NEEDS-ACTION", self.state["calendar_data"])
        self.assertEqual(self.state["writes"][0]["if_match"], '"v1"')
        self.assertIn("STATUS:COMPLETED", self.state["writes"][0]["body"])
        self.assertNotEqual(self.state["calendar_data"], self.state["writes"][0]["body"])

        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        recovered = self._wait_sync_idle(account_id)
        self.assertEqual(recovered["lastSyncError"], "")
        self.assertEqual(len(self.state["writes"]), 2)
        self.assertEqual(self.state["writes"][1]["if_match"], '"raced"')
        self.assertIn("X-CUSTOM:remote-change", self.state["calendar_data"])
        self.assertIn("STATUS:COMPLETED", self.state["calendar_data"])

    def test_delta_fetches_only_changed_resource_then_marks_deleted_task_missing(self) -> None:
        account_id, _returned = self._add_account()
        self._wait_idle(account_id)
        self.state["calendar_data"] = _with_event(self.state["calendar_data"])
        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        self.assertEqual(self._wait_sync_idle(account_id)["lastSyncError"], "")
        meetings = self.bridge._repository.state("2026-09-28")["calendarEvents"]
        self.assertEqual([event["title"] for event in meetings], ["Remote meeting"])
        self.state["requests"].clear()

        self.state["calendar_data"] = self.state["calendar_data"].replace(
            "SUMMARY:Remote task", "SUMMARY:Changed remotely",
        ).replace("SUMMARY:Remote meeting", "SUMMARY:Changed meeting")
        self.state["etag"] = '"remote-v2"'
        self.state["sync_token"] = "urn:test:sync:2"
        self.state["delta_changes"] = [{
            "href": "/caldav/work/task.ics", "etag": '"remote-v2"', "removed": False,
        }]
        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        self.assertEqual(self._wait_sync_idle(account_id)["lastSyncError"], "")
        fetched = next(
            item for item in self.state["requests"]
            if item.get("kind") == "calendar-multiget"
        )
        self.assertEqual(fetched["hrefs"], [
            f"http://127.0.0.1:{self.server.server_port}/caldav/work/task.ics",
        ])
        task = self.bridge.activity_records()[0]
        self.assertEqual(task["data"]["title"], "Changed remotely")
        self.assertEqual(
            self.bridge._repository.state("2026-09-28")["calendarEvents"][0]["title"], "Changed meeting",
        )

        self.state["requests"].clear()
        self.state["sync_token"] = "urn:test:sync:3"
        self.state["delta_changes"] = [{
            "href": "/caldav/work/task.ics", "etag": "", "removed": True,
        }]
        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        self.assertEqual(self._wait_sync_idle(account_id)["lastSyncError"], "")
        self.assertFalse(any(
            item.get("kind") == "calendar-multiget" for item in self.state["requests"]
        ))
        task = self.bridge.activity_records()[0]
        self.assertTrue(task["data"]["externalTodo"]["sourceMissing"])
        self.assertEqual(self.bridge._repository.state()["calendarEvents"], [])

    def test_stale_sync_token_retries_as_full_sync_before_advancing(self) -> None:
        account_id, _returned = self._add_account()
        self._wait_idle(account_id)
        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        self.assertEqual(self._wait_sync_idle(account_id)["lastSyncError"], "")
        self.state["requests"].clear()
        self.state["reject_sync_token"] = True

        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        self.assertEqual(self._wait_sync_idle(account_id)["lastSyncError"], "")
        sync_requests = [
            item for item in self.state["requests"]
            if item.get("kind") == "sync-collection"
        ]
        self.assertEqual([item["sync_token"] for item in sync_requests], ["urn:test:sync:1", ""])
        details = self.bridge._repository.caldav_account_details(account_id)
        self.assertEqual(details["syncToken"], "urn:test:sync:1")
        self.assertFalse(details["syncCollectionUnsupported"])

    def test_truncated_sync_collection_follows_returned_page_token(self) -> None:
        self.state["sync_truncated"] = True
        account_id, _returned = self._add_account()
        self._wait_idle(account_id)

        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        self.assertEqual(self._wait_sync_idle(account_id)["lastSyncError"], "")
        requests = [
            item for item in self.state["requests"]
            if item.get("kind") == "sync-collection"
        ]
        self.assertEqual([item["sync_token"] for item in requests], ["", "urn:test:sync:page-1"])
        self.assertEqual(
            self.bridge._repository.caldav_account_details(account_id)["syncToken"],
            "urn:test:sync:1",
        )

    def test_unsupported_sync_collection_uses_and_remembers_full_snapshot_fallback(self) -> None:
        self.state["sync_unsupported"] = True
        self.state["calendar_data"] = _with_event(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n",
        )
        account_id, _returned = self._add_account()
        self._wait_idle(account_id)

        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        self.assertEqual(self._wait_sync_idle(account_id)["lastSyncError"], "")
        details = self.bridge._repository.caldav_account_details(account_id)
        self.assertEqual(details["syncToken"], "")
        self.assertTrue(details["syncCollectionUnsupported"])
        self.assertEqual(
            [event["title"] for event in self.bridge._repository.state("2026-09-28")["calendarEvents"]],
            ["Remote meeting"],
        )
        self.state["requests"].clear()
        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        self.assertEqual(self._wait_sync_idle(account_id)["lastSyncError"], "")
        self.assertEqual(
            [item.get("kind") for item in self.state["requests"] if item.get("method") == "REPORT"],
            ["calendar-query"],
        )

    def test_failed_multiget_does_not_advance_sync_token_or_apply_partial_delta(self) -> None:
        account_id, _returned = self._add_account()
        self._wait_idle(account_id)
        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        self.assertEqual(self._wait_sync_idle(account_id)["lastSyncError"], "")
        original_task = self.bridge.activity_records()[0]
        self.state["calendar_data"] = self.state["calendar_data"].replace(
            "SUMMARY:Remote task", "SUMMARY:Changed remotely",
        )
        self.state["etag"] = '"remote-v2"'
        self.state["sync_token"] = "urn:test:sync:2"
        self.state["delta_changes"] = [{
            "href": "/caldav/work/task.ics", "etag": '"remote-v2"', "removed": False,
        }]
        self.state["multiget_incomplete"] = True

        self.assertTrue(self.bridge.syncCalDAVTasks(account_id)["ok"])
        account = self._wait_sync_idle(account_id)
        self.assertNotEqual(account["lastSyncError"], "")
        details = self.bridge._repository.caldav_account_details(account_id)
        self.assertEqual(details["syncToken"], "urn:test:sync:1")
        self.assertEqual(self.bridge.activity_records()[0]["data"]["title"], original_task["data"]["title"])
