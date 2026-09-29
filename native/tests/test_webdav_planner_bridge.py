from __future__ import annotations

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtNetwork import QNetworkAccessManager
from PySide6.QtTest import QTest

from wanxiang.planner import PlannerRepository
from wanxiang.planner_sync import FORMAT, VERSION
from wanxiang.webdav_planner import (
    decrypt_snapshot,
    encrypt_snapshot,
    load_account,
)
from wanxiang.webdav_planner_bridge import WebDavPlannerSyncBridge


DEVICE_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DEVICE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PASSPHRASE = "synthetic planner passphrase"


class MockRemote:
    def __init__(self) -> None:
        self.body: bytes | None = None
        self.etag = '"seed"'
        self.put_count = 0
        self.get_failures = 0
        self.events: list[tuple[str, str, str, str]] = []


def make_handler(remote: MockRemote) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *args: object) -> None:
            return

        def _respond(self, status: int, body: bytes = b"", etag: str = "") -> None:
            self.send_response(status)
            if etag:
                self.send_header("ETag", etag)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self) -> None:
            remote.events.append(("GET", self.path, self.headers.get("If-Match", ""), self.headers.get("If-None-Match", "")))
            if remote.get_failures:
                remote.get_failures -= 1
                self._respond(503)
            elif remote.body is None:
                self._respond(404)
            else:
                self._respond(200, remote.body, remote.etag)

        def do_PUT(self) -> None:
            length = min(int(self.headers.get("Content-Length", "0")), 70 * 1024 * 1024)
            body = self.rfile.read(length)
            if_match = self.headers.get("If-Match", "")
            if_none_match = self.headers.get("If-None-Match", "")
            remote.events.append(("PUT", self.path, if_match, if_none_match))
            if remote.body is None:
                if if_none_match != "*":
                    self._respond(412)
                    return
            elif if_match != remote.etag:
                self._respond(412)
                return
            remote.body = body
            remote.put_count += 1
            remote.etag = f'"mock-{remote.put_count}"'
            self._respond(201, etag=remote.etag)

    return Handler


class WebDavPlannerBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="synthetic-webdav-planner-")
        self.addCleanup(self.temp_dir.cleanup)
        self.database = Path(self.temp_dir.name) / "synthetic.sqlite3"
        self.repository = PlannerRepository(self.database, {"richangji-state-v1": {
            "records": [], "settings": {}, "drafts": {},
        }})
        self.remote = MockRemote()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.remote))
        self.server_thread = Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self._stop_server)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/backup.wxbackup"
        self.secret = {
            "url": self.base_url,
            "host": "127.0.0.1",
            "username": "synthetic-user",
            "password": "synthetic-password",
            "passphrase": PASSPHRASE,
        }
        self.account = {
            "format": 1,
            "id": "synthetic-account-id",
            "host": "127.0.0.1",
            "fileName": "backup.wxbackup",
            "encryptedSecret": "synthetic-protected-value",
            "plannerRemoteExists": False,
            "plannerEtag": "",
            "lastPlannerSyncAt": "",
            "lastPlannerError": "",
        }
        self.patchers = [
            patch("wanxiang.webdav_planner_bridge.create_protected_account", return_value=deepcopy(self.account)),
            patch("wanxiang.webdav_planner_bridge.reveal_account_secret", return_value=self.secret),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.network = QNetworkAccessManager(self.app)
        self.bridge = WebDavPlannerSyncBridge(
            self.database, self.repository, self.network, self.app,
            allow_loopback_http=True, start_automatically=False,
        )
        self.addCleanup(self.bridge.close)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)

    def _wait_for(self, predicate, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(10)
        self.fail("Timed out waiting for the isolated localhost WebDAV exchange.")

    def _add_versioned_task(self, title: str) -> str:
        created = self.repository.add_task(title, "2026-09-29")
        state = self.repository.webdav_sync_state()
        task = next(item for item in state["records"] if item["id"] == created["id"])
        task["webdavSyncVersion"] = {DEVICE_A: 1}
        state["settings"]["webdavPlannerVector"] = {DEVICE_A: 1}
        self.repository.save_webdav_sync_state(state, DEVICE_A)
        return created["id"]

    def _configure(self) -> None:
        result = self.bridge.configure(self.base_url, "synthetic-user", "synthetic-password", PASSPHRASE)
        self.assertTrue(result["ok"], result)

    def test_first_sync_uses_localhost_conditional_create_and_can_clear_account(self) -> None:
        task_id = self.repository.add_task("合成日程 A", "2026-09-29")["id"]
        self._configure()
        self._wait_for(lambda: self.bridge.state["status"] == "ok" and not self.bridge.state["busy"])

        self.assertTrue(self.remote.body)
        snapshot = decrypt_snapshot(self.remote.body, PASSPHRASE)
        self.assertEqual([item["id"] for item in snapshot["tasks"]], [task_id])
        self.assertEqual(self.remote.events[0][0:2], ("GET", "/backup.planner-sync.wxbackup"))
        first_put = next(item for item in self.remote.events if item[0] == "PUT")
        self.assertEqual(first_put[3], "*")
        self.assertEqual(self.bridge.state["host"], "127.0.0.1")
        self.assertTrue(self.bridge.state["lastSyncAt"])

        self.assertTrue(self.bridge.clearAccount()["ok"])
        self.assertIsNone(load_account(self.database))
        self.assertEqual(self.repository.records()[0]["id"], task_id)

    def test_conflict_variants_can_be_resolved_and_resynced(self) -> None:
        task_id = self._add_versioned_task("本机标题")
        remote_task = {
            "id": task_id,
            "type": "planner",
            "date": "2026-09-29",
            "createdAt": 10,
            "webdavSyncVersion": {DEVICE_B: 1},
            "data": {"title": "远端标题", "done": False, "list": "生活", "note": ""},
        }
        self.remote.body = encrypt_snapshot({
            "format": FORMAT, "version": VERSION, "deviceId": DEVICE_B,
            "vector": {DEVICE_B: 1}, "tasks": [remote_task], "tombstones": [], "conflicts": [],
        }, PASSPHRASE).encode("utf-8")
        self._configure()
        self._wait_for(lambda: self.bridge.state["status"] == "conflict" and not self.bridge.state["busy"])

        conflicts = self.bridge.conflicts
        self.assertEqual(len(conflicts), 1)
        variants = conflicts[0]["variants"]
        choose_remote = next(i for i, item in enumerate(variants) if item.get("record", {}).get("data", {}).get("title") == "远端标题")
        self.assertTrue(self.bridge.resolve(task_id, choose_remote, True)["ok"])
        self._wait_for(lambda: self.bridge.state["status"] == "ok" and not self.bridge.state["busy"])

        self.assertEqual(self.bridge.conflicts, [])
        self.assertEqual(len(self.repository.records()), 2)
        merged = decrypt_snapshot(self.remote.body or b"", PASSPHRASE)
        self.assertEqual(len(merged["tasks"]), 2)
        self.assertTrue(any(item["data"].get("webdavConflictOf") == task_id for item in merged["tasks"]))

    def test_manual_retry_succeeds_after_localhost_http_failure(self) -> None:
        self.remote.get_failures = 1
        self._configure()
        self._wait_for(lambda: self.bridge.state["status"] == "error" and not self.bridge.state["busy"])
        self.assertIn("503", self.bridge.state["message"])

        result = self.bridge.syncNow()
        self.assertTrue(result["ok"], result)
        self._wait_for(lambda: self.bridge.state["status"] == "ok" and not self.bridge.state["busy"])
        self.assertGreaterEqual(sum(item[0] == "GET" for item in self.remote.events), 2)


if __name__ == "__main__":
    unittest.main()
