from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from wanxiang.caldav import (
    CalDAVError,
    basic_authorization_header,
    caldav_calendar_multiget_body,
    caldav_sync_collection_body,
    caldav_sync_token_was_rejected,
    caldav_vtodo_query_body,
    normalize_caldav_url,
    parse_caldav_calendar_multiget_report,
    parse_caldav_sync_collection_report,
    parse_caldav_vtodo_report,
    parse_caldav_collection_probe,
    protect_caldav_credentials,
    update_vtodo_completion,
    unprotect_caldav_credentials,
    validate_caldav_credentials,
    validate_caldav_transport,
)
from wanxiang.calendar_exchange import parse_ics, parse_ical_vtodos
from wanxiang.planner import PlannerRepository, PlannerRepositoryError


def _source() -> dict[str, object]:
    return {
        "richangji-state-v1": {
            "records": [], "settings": {}, "drafts": {"plannerForm": {}},
        }
    }


_PROPFIND = b'''<?xml version="1.0" encoding="utf-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:response><d:href>/remote.php/dav/calendars/alice/tasks/</d:href>
    <d:propstat><d:prop>
      <d:displayname>Tasks and calendar</d:displayname>
      <d:resourcetype><d:collection/><c:calendar/></d:resourcetype>
      <c:supported-calendar-component-set>
        <c:comp name="VEVENT"/><c:comp name="VTODO"/><c:comp name="VJOURNAL"/>
      </c:supported-calendar-component-set>
    </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
  </d:response>
</d:multistatus>'''


class CalDAVAddressTests(unittest.TestCase):
    def test_normalizes_endpoint_and_rejects_embedded_credentials(self) -> None:
        url, host = normalize_caldav_url("HTTPS://Calendar.Example.test:8443/dav/calendar/#view")
        self.assertEqual(url, "https://Calendar.Example.test:8443/dav/calendar/")
        self.assertEqual(host, "calendar.example.test:8443")
        for value in (
            "ftp://calendar.example.test/dav/",
            "https://alice:secret@calendar.example.test/dav/",
            "https:///missing-host/",
            "https://calendar.example.test:70000/dav/",
            "https://calendar.example.test/bad path/",
        ):
            with self.subTest(value=value), self.assertRaises(CalDAVError):
                normalize_caldav_url(value)

    def test_credentials_are_validated_and_protected_payload_round_trips(self) -> None:
        protected_values: list[str] = []

        def protect(value: str) -> str:
            protected_values.append(value)
            return "encrypted:" + value[::-1]

        def unprotect(value: str) -> str:
            self.assertTrue(value.startswith("encrypted:"))
            return value.removeprefix("encrypted:")[::-1]

        protected = protect_caldav_credentials("alice", "app-password", protect)
        self.assertNotIn("alice", protected)
        self.assertNotIn("app-password", protected)
        self.assertEqual(
            unprotect_caldav_credentials(protected, unprotect),
            ("alice", "app-password"),
        )
        self.assertEqual(len(protected_values), 1)
        with self.assertRaises(CalDAVError):
            validate_caldav_credentials("alice", "")
        with self.assertRaises(CalDAVError):
            validate_caldav_credentials("alice:other", "password")
        with self.assertRaises(CalDAVError):
            validate_caldav_credentials("alice", "bad\npassword")

    def test_basic_auth_header_is_generated_only_for_complete_credentials(self) -> None:
        self.assertIsNone(basic_authorization_header("", ""))
        self.assertEqual(
            basic_authorization_header("alice", "app-password"),
            b"Basic YWxpY2U6YXBwLXBhc3N3b3Jk",
        )

    def test_remote_caldav_requires_tls_even_without_credentials(self) -> None:
        with self.assertRaisesRegex(CalDAVError, "必须使用 HTTPS"):
            validate_caldav_transport("http://calendar.example.test/dav/tasks/", True)
        with self.assertRaisesRegex(CalDAVError, "必须使用 HTTPS"):
            validate_caldav_transport("http://calendar.example.test/public/", False)
        self.assertTrue(validate_caldav_transport("https://calendar.example.test/public/", False)[0])
        self.assertTrue(validate_caldav_transport("http://127.0.0.1:8000/dav/", True)[0])
        self.assertTrue(validate_caldav_transport("http://localhost:8000/dav/", True)[0])

    def test_vtodo_report_resolves_only_resources_inside_same_collection(self) -> None:
        calendar = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VTODO\r\nUID:task-a@example.test\r\nSUMMARY:远程任务\r\n"
            "STATUS:NEEDS-ACTION\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
        )
        from xml.sax.saxutils import escape
        escaped = escape(calendar)
        response = f'''<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
          <d:response><d:href>/dav/tasks/a.ics</d:href><d:propstat><d:prop>
            <d:getetag>"tag-1"</d:getetag><c:calendar-data>{escaped}</c:calendar-data>
          </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
        </d:multistatus>'''.encode()
        resources = parse_caldav_vtodo_report(response, "https://calendar.example.test/dav/tasks/")
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["href"], "https://calendar.example.test/dav/tasks/a.ics")
        self.assertEqual(resources[0]["etag"], '"tag-1"')
        self.assertEqual(resources[0]["todo"]["uid"], "task-a@example.test")
        cross_origin = response.replace(b"/dav/tasks/a.ics", b"https://attacker.example/steal.ics")
        with self.assertRaisesRegex(CalDAVError, "另一个服务器"):
            parse_caldav_vtodo_report(cross_origin, "https://calendar.example.test/dav/tasks/")
        sibling = response.replace(b"/dav/tasks/a.ics", b"/dav/tasks-evil/a.ics")
        with self.assertRaisesRegex(CalDAVError, "不属于当前日历集"):
            parse_caldav_vtodo_report(sibling, "https://calendar.example.test/dav/tasks/")

    def test_sync_collection_request_treats_token_as_opaque_and_xml_escapes_it(self) -> None:
        payload = caldav_sync_collection_body("urn:vendor:sync?a=1&b=2")
        self.assertIn(b"<d:sync-token>urn:vendor:sync?a=1&amp;b=2</d:sync-token>", payload)
        self.assertIn(b"<d:sync-level>1</d:sync-level>", payload)
        self.assertIn(b"<d:getetag/>", payload)
        with self.assertRaisesRegex(CalDAVError, "有效 URI"):
            caldav_sync_collection_body("opaque-token-without-scheme")

    def test_sync_collection_parser_reads_changes_deletions_truncation_and_new_token(self) -> None:
        response = b'''<d:multistatus xmlns:d="DAV:">
          <d:response><d:href>/dav/tasks/changed.ics</d:href><d:propstat><d:prop>
            <d:getetag>"next"</d:getetag>
          </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
          <d:response><d:href>/dav/tasks/deleted.ics</d:href>
            <d:status>HTTP/1.1 404 Not Found</d:status></d:response>
          <d:response><d:href>/dav/tasks/</d:href>
            <d:status>HTTP/1.1 507 Insufficient Storage</d:status></d:response>
          <d:sync-token>urn:server:sync:42</d:sync-token>
        </d:multistatus>'''
        result = parse_caldav_sync_collection_report(
            response, "https://calendar.example.test/dav/tasks/",
        )
        self.assertEqual(result["syncToken"], "urn:server:sync:42")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["changes"], [
            {
                "href": "https://calendar.example.test/dav/tasks/changed.ics",
                "etag": '"next"', "removed": "false",
            },
            {
                "href": "https://calendar.example.test/dav/tasks/deleted.ics",
                "etag": "", "removed": "true",
            },
        ])
        self.assertFalse(caldav_sync_token_was_rejected(response))
        rejected = b'<d:error xmlns:d="DAV:"><d:valid-sync-token/></d:error>'
        self.assertTrue(caldav_sync_token_was_rejected(rejected))
        with self.assertRaisesRegex(CalDAVError, "同步令牌"):
            parse_caldav_sync_collection_report(
                response.replace(b"urn:server:sync:42", b"invalid-token"),
                "https://calendar.example.test/dav/tasks/",
            )
        internal_entity = (
            b'<!DOCTYPE d:multistatus [<!ENTITY token "urn:server:sync:42">]>'
            b'<d:multistatus xmlns:d="DAV:"><d:sync-token>&token;</d:sync-token></d:multistatus>'
        )
        with self.assertRaisesRegex(CalDAVError, "不安全"):
            parse_caldav_sync_collection_report(
                internal_entity.decode("ascii").encode("utf-16"),
                "https://calendar.example.test/dav/tasks/",
            )

    def test_calendar_multiget_parses_tasks_events_and_deleted_resources_safely(self) -> None:
        from xml.sax.saxutils import escape
        todo = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\n"
            "UID:task-a@example.test\r\nSUMMARY:Remote task\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
        )
        event = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\n"
            "UID:event-a@example.test\r\nDTSTART:20260928T120000Z\r\n"
            "DTEND:20260928T130000Z\r\nSUMMARY:Remote event\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        requested = [
            "https://calendar.example.test/dav/tasks/todo.ics",
            "https://calendar.example.test/dav/tasks/event.ics",
            "https://calendar.example.test/dav/tasks/gone.ics",
        ]
        body = (
            '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:response><d:href>/dav/tasks/todo.ics</d:href><d:propstat><d:prop>'
            '<d:getetag>"todo-v1"</d:getetag><c:calendar-data>' + escape(todo)
            + '</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
            '<d:response><d:href>/dav/tasks/event.ics</d:href><d:propstat><d:prop>'
            '<d:getetag>"event-v1"</d:getetag><c:calendar-data>' + escape(event)
            + '</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
            '<d:response><d:href>/dav/tasks/gone.ics</d:href><d:status>HTTP/1.1 404 Not Found</d:status></d:response>'
            '</d:multistatus>'
        ).encode()
        result = parse_caldav_calendar_multiget_report(
            body, "https://calendar.example.test/dav/tasks/", requested,
        )
        self.assertEqual([item["todo"]["uid"] if item["todo"] else None for item in result["resources"]], [
            "task-a@example.test", None,
        ])
        self.assertEqual(result["removedHrefs"], [requested[2]])
        request = caldav_calendar_multiget_body(requested)
        self.assertIn(b"calendar-multiget", request)
        self.assertIn(b"/dav/tasks/event.ics", request)
        with self.assertRaisesRegex(CalDAVError, "地址与请求不匹配"):
            parse_caldav_calendar_multiget_report(
                body.replace(b"/dav/tasks/gone.ics", b"/dav/tasks/other.ics"),
                "https://calendar.example.test/dav/tasks/", requested,
            )

    def test_recurring_vtodo_does_not_block_other_multiget_resources(self) -> None:
        from xml.sax.saxutils import escape

        supported = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\n"
            "UID:supported@example.test\r\nSUMMARY:Supported\r\n"
            "STATUS:NEEDS-ACTION\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
        )
        recurring = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\n"
            "UID:recurring@example.test\r\nSUMMARY:Recurring\r\n"
            "STATUS:NEEDS-ACTION\r\nRRULE:FREQ=DAILY\r\n"
            "END:VTODO\r\nEND:VCALENDAR\r\n"
        )
        hrefs = [
            "https://calendar.example.test/dav/tasks/supported.ics",
            "https://calendar.example.test/dav/tasks/recurring.ics",
        ]
        body = (
            '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:response><d:href>/dav/tasks/supported.ics</d:href><d:propstat><d:prop>'
            '<d:getetag>"s1"</d:getetag><c:calendar-data>' + escape(supported)
            + '</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
            '<d:response><d:href>/dav/tasks/recurring.ics</d:href><d:propstat><d:prop>'
            '<d:getetag>"r1"</d:getetag><c:calendar-data>' + escape(recurring)
            + '</c:calendar-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>'
            '</d:multistatus>'
        ).encode("utf-8")
        result = parse_caldav_calendar_multiget_report(
            body, "https://calendar.example.test/dav/tasks/", hrefs,
        )
        self.assertEqual(result["resources"][0]["todo"]["uid"], "supported@example.test")
        self.assertIsNone(result["resources"][1]["todo"])
        self.assertIn("重复规则", result["resources"][1]["unsupportedError"])

        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "planner.sqlite3", _source())
            account_id = repo.add_caldav_account(
                "Work", "calendar.example.test", "opaque-url", "opaque-credentials",
            )["id"]
            synced = repo.sync_caldav_vtodos(account_id, result["resources"])
            self.assertEqual(synced["resourceCount"], 1)
            self.assertEqual(synced["unsupportedResourceCount"], 1)
            self.assertEqual(
                [row["data"]["externalTodo"]["uid"] for row in repo.records()],
                ["supported@example.test"],
            )

    def test_full_calendar_query_includes_vevent_only_resources(self) -> None:
        from xml.sax.saxutils import escape
        event = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:meeting@example.test\r\nSUMMARY:Remote meeting\r\n"
            "DTSTART:20260928T100000Z\r\nDTEND:20260928T110000Z\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        payload = (
            '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:response><d:href>/dav/tasks/meeting.ics</d:href>'
            '<d:propstat><d:prop><d:getetag>"e1"</d:getetag>'
            '<c:calendar-data>' + escape(event) + '</c:calendar-data></d:prop>'
            '<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>'
        ).encode("utf-8")
        self.assertNotIn(b'name="VTODO"', caldav_vtodo_query_body())
        resources = parse_caldav_vtodo_report(
            payload, "https://calendar.example.test/dav/tasks/",
        )
        self.assertEqual(len(resources), 1)
        self.assertIsNone(resources[0]["todo"])

    def test_caldav_vevent_sync_accepts_utc_recurrence_values_with_zoned_start(self) -> None:
        calendar = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:utc-rdate@example.test\r\n"
            "DTSTART;TZID=America/New_York:20260928T090000\r\n"
            "DTEND;TZID=America/New_York:20260928T100000\r\n"
            "RRULE:FREQ=DAILY;COUNT=3\r\n"
            "EXDATE:20260929T130000Z\r\nRDATE:20261002T130000Z\r\n"
            "SUMMARY:UTC 例外日程\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "utc-rdate.sqlite3", _source())
            account = repo.add_caldav_account(
                "Work", "calendar.example.test", "opaque-url", "opaque-credentials",
            )
            result = repo.sync_caldav_vtodos(account["id"], [{
                "href": "https://calendar.example.test/dav/work/utc-rdate.ics",
                "etag": '"event-v1"',
                "calendarData": calendar,
                "todo": None,
            }], sync_token="urn:test:sync:utc-rdate")

            self.assertEqual(result["eventCount"], 1)
            stored = repo._state["calendarEvents"]
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0]["excludedDates"], ["2026-09-29T09:00:00"])
            self.assertEqual(stored[0]["recurrenceDates"], ["2026-10-02T09:00:00"])
            self.assertEqual(
                repo.caldav_account_details(account["id"])["syncToken"],
                "urn:test:sync:utc-rdate",
            )

    def test_completion_writeback_preserves_unknown_fields_and_valarm(self) -> None:
        calendar = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Remote//EN\r\n"
            "BEGIN:VTODO\r\nUID:task-a@example.test\r\nSUMMARY:Keep this task\r\n"
            "X-VENDOR-PRIVATE:preserve-me\r\nSTATUS:NEEDS-ACTION\r\nPERCENT-COMPLETE:0\r\n"
            "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Reminder\r\nTRIGGER:-PT5M\r\nEND:VALARM\r\n"
            "END:VTODO\r\nEND:VCALENDAR\r\n"
        )
        instant = datetime(2026, 9, 28, 4, 0, tzinfo=timezone.utc)
        completed = update_vtodo_completion(calendar, "task-a@example.test", True, instant)
        self.assertIn("X-VENDOR-PRIVATE:preserve-me", completed)
        self.assertIn("BEGIN:VALARM", completed)
        self.assertIn("STATUS:COMPLETED", completed)
        self.assertIn("PERCENT-COMPLETE:100", completed)
        self.assertIn("COMPLETED:20260928T040000Z", completed)
        reopened = update_vtodo_completion(completed, "task-a@example.test", False, instant)
        self.assertIn("STATUS:NEEDS-ACTION", reopened)
        self.assertIn("PERCENT-COMPLETE:0", reopened)
        self.assertNotIn("COMPLETED:", reopened)
        self.assertIn("X-VENDOR-PRIVATE:preserve-me", reopened)
        with self.assertRaises(CalDAVError):
            update_vtodo_completion(calendar, "wrong-uid", True, instant)

    def test_probe_reads_calendar_name_and_supported_components(self) -> None:
        result = parse_caldav_collection_probe(_PROPFIND)
        self.assertEqual(result["calendars"], [{
            "href": "/remote.php/dav/calendars/alice/tasks/",
            "name": "Tasks and calendar",
            "components": ["VEVENT", "VTODO"],
        }])
        with self.assertRaisesRegex(CalDAVError, "不安全"):
            parse_caldav_collection_probe(b"<!DOCTYPE x [<!ENTITY test SYSTEM 'file:///secret'>]><x/>")
        with self.assertRaisesRegex(CalDAVError, "日历集"):
            parse_caldav_collection_probe(
                b'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"/>'
            )


class CalDAVRepositoryTests(unittest.TestCase):
    def test_removing_caldav_account_removes_its_external_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "planner.sqlite3", _source())
            account = repo.add_caldav_account(
                "Work", "calendar.example.test", "opaque-url", "opaque-credentials",
            )
            account_id = account["id"]
            calendar = (
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                "BEGIN:VEVENT\r\nUID:meeting@example.test\r\nSUMMARY:Remote meeting\r\n"
                "DTSTART:20260928T100000Z\r\nDTEND:20260928T110000Z\r\n"
                "END:VEVENT\r\nEND:VCALENDAR\r\n"
            )
            event = {**parse_ics(calendar)[1][0], "resourceHref": "https://calendar.example.test/dav/meeting.ics"}
            repo.import_calendar(
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n",
                "Work",
                f"caldav:{account_id}",
                todo_provider="caldav",
                parsed_todos=[],
                parsed_events=[event],
                caldav_account_id=account_id,
                caldav_sync_token="urn:test:sync:1",
                caldav_sync_collection_unsupported=False,
            )
            self.assertEqual(len(repo.state("2026-09-28")["calendarEvents"]), 1)
            self.assertTrue(repo.remove_caldav_account(account_id))
            self.assertEqual(repo.state("2026-09-28")["calendarEvents"], [])

    def test_delta_import_preserves_unchanged_tasks_and_commits_token_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planner.sqlite3"
            repo = PlannerRepository(path, _source())
            account = repo.add_caldav_account(
                "Work", "calendar.example.test", "opaque-url", "opaque-credentials",
            )
            account_id = account["id"]

            def resource(uid: str, title: str, href: str) -> dict[str, object]:
                calendar = (
                    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                    "BEGIN:VTODO\r\nUID:" + uid + "\r\nSUMMARY:" + title + "\r\n"
                    "STATUS:NEEDS-ACTION\r\nPERCENT-COMPLETE:0\r\n"
                    "END:VTODO\r\nEND:VCALENDAR\r\n"
                )
                return {
                    "href": href,
                    "etag": '"v1"',
                    "calendarData": calendar,
                    "todo": parse_ical_vtodos(calendar)[1][0],
                }

            first_href = "https://calendar.example.test/dav/tasks/first.ics"
            second_href = "https://calendar.example.test/dav/tasks/second.ics"
            first = resource("first@example.test", "First", first_href)
            second = resource("second@example.test", "Second", second_href)
            initial = repo.sync_caldav_vtodos(
                account_id, [first, second], sync_token="urn:test:sync:1",
                sync_collection_unsupported=False,
            )
            self.assertEqual(initial["import"]["tasks"]["added"], 2)
            visible_account = next(
                row for row in repo.state()["caldavAccounts"] if row["id"] == account_id
            )
            self.assertNotIn("syncToken", visible_account)
            self.assertEqual(
                repo.caldav_account_details(account_id)["syncToken"], "urn:test:sync:1",
            )

            changed_first = resource("first@example.test", "First changed", first_href)
            delta = repo.sync_caldav_vtodos(
                account_id, [changed_first], complete_snapshot=False,
                sync_token="urn:test:sync:2",
            )
            self.assertEqual(delta["import"]["tasks"]["updated"], 1)
            self.assertEqual(len(repo.records()), 2)
            self.assertEqual(
                {row["data"]["title"] for row in repo.records()}, {"First changed", "Second"},
            )

            removed = repo.sync_caldav_vtodos(
                account_id, [], complete_snapshot=False,
                removed_resource_hrefs=[second_href], sync_token="urn:test:sync:3",
            )
            self.assertEqual(removed["import"]["tasks"]["sourceMissing"], 1)
            self.assertTrue(next(
                row for row in repo.records()
                if row["data"]["externalTodo"]["uid"] == "second@example.test"
            )["data"]["externalTodo"]["sourceMissing"])
            with self.assertRaises(PlannerRepositoryError):
                repo.sync_caldav_vtodos(
                    account_id, [{"malformed": True}], complete_snapshot=False,
                    sync_token="urn:test:sync:4",
                )
            self.assertEqual(
                repo.caldav_account_details(account_id)["syncToken"], "urn:test:sync:3",
            )

    def test_vtodo_sync_imports_idempotently_and_detects_local_completion_for_safe_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planner.sqlite3"
            repo = PlannerRepository(path, _source())
            account = repo.add_caldav_account(
                "Work", "calendar.example.test", "opaque-url", "opaque-credentials",
            )
            account_id = account["id"]
            calendar = (
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:Work tasks\r\n"
                "BEGIN:VTODO\r\nUID:remote-task@example.test\r\nSUMMARY:Remote task\r\n"
                "STATUS:NEEDS-ACTION\r\nPERCENT-COMPLETE:0\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
            )
            todo = parse_ical_vtodos(calendar)[1][0]
            resource = {
                "href": "https://calendar.example.test/dav/tasks/task.ics",
                "etag": '"v1"', "calendarData": calendar, "todo": todo,
            }
            first = repo.sync_caldav_vtodos(account_id, [resource])
            self.assertEqual(first["import"]["tasks"]["added"], 1)
            self.assertEqual(first["writebacks"], [])
            repeated = repo.sync_caldav_vtodos(account_id, [resource])
            self.assertEqual(repeated["import"]["tasks"]["unchanged"], 1)
            self.assertEqual(len(repo.records()), 1)

            task = repo.records()[0]
            repo.schedule_task(task["id"], "2026-10-01", "09:00", 45)
            repeated_with_local_plan = repo.sync_caldav_vtodos(account_id, [resource])
            self.assertEqual(repeated_with_local_plan["import"]["tasks"]["unchanged"], 1)
            preserved = repo._target(task["id"])["data"]
            self.assertEqual((preserved["plannedDate"], preserved["plannedStart"], preserved["estimateMinutes"]),
                             ("2026-10-01", "09:00", 45))

            repo.toggle_task(task["id"])
            pending = repo.sync_caldav_vtodos(account_id, [resource])
            self.assertEqual(len(pending["writebacks"]), 1)
            self.assertTrue(pending["writebacks"][0]["done"])
            self.assertTrue(repo.records()[0]["data"]["done"])
            self.assertTrue(repo.record_caldav_task_writeback(
                account_id, "remote-task@example.test", True, '"v2"',
            ))
            reopened = PlannerRepository(path)
            ext = reopened.records()[0]["data"]["externalTodo"]
            self.assertTrue(ext["syncedDone"])
            self.assertEqual(ext["etag"], '"v2"')

            completed_calendar = calendar.replace(
                "STATUS:NEEDS-ACTION\r\nPERCENT-COMPLETE:0",
                "STATUS:COMPLETED\r\nPERCENT-COMPLETE:100\r\nCOMPLETED:20260928T040000Z",
            )
            completed_todo = parse_ical_vtodos(completed_calendar)[1][0]
            completed_resource = {**resource, "etag": '"v2"', "calendarData": completed_calendar, "todo": completed_todo}
            remote_result = reopened.sync_caldav_vtodos(account_id, [completed_resource])
            self.assertEqual(remote_result["writebacks"], [])
            self.assertTrue(reopened.records()[0]["data"]["done"])
            self.assertFalse(reopened.records()[0]["data"]["externalTodo"]["sourceMissing"])

            removed = reopened.sync_caldav_vtodos(account_id, [])
            self.assertEqual(removed["import"]["tasks"]["sourceMissing"], 1)
            self.assertTrue(reopened.records()[0]["data"]["externalTodo"]["sourceMissing"])

    def test_uid_replacement_at_same_resource_href_retires_old_task_and_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "planner.sqlite3", _source())
            account_id = repo.add_caldav_account(
                "Work", "calendar.example.test", "opaque-url", "opaque-credentials",
            )["id"]
            href = "https://calendar.example.test/dav/tasks/item.ics"

            def resource(event_uid: str, todo_uid: str) -> dict[str, object]:
                calendar = (
                    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                    f"BEGIN:VEVENT\r\nUID:{event_uid}\r\n"
                    "DTSTART:20260928T090000Z\r\nDTEND:20260928T100000Z\r\n"
                    "SUMMARY:Calendar item\r\nEND:VEVENT\r\n"
                    f"BEGIN:VTODO\r\nUID:{todo_uid}\r\n"
                    "SUMMARY:Task item\r\nSTATUS:NEEDS-ACTION\r\nEND:VTODO\r\n"
                    "END:VCALENDAR\r\n"
                )
                return {
                    "href": href,
                    "etag": '"v1"',
                    "calendarData": calendar,
                    "todo": parse_ical_vtodos(calendar)[1][0],
                }

            repo.sync_caldav_vtodos(account_id, [resource("event-old", "todo-old")])
            repo.sync_caldav_vtodos(
                account_id,
                [resource("event-new", "todo-new")],
                complete_snapshot=False,
            )

            old_task = next(row for row in repo.records() if row["data"]["externalTodo"]["uid"] == "todo-old")
            new_task = next(row for row in repo.records() if row["data"]["externalTodo"]["uid"] == "todo-new")
            self.assertTrue(old_task["data"]["externalTodo"]["sourceMissing"])
            self.assertFalse(new_task["data"]["externalTodo"]["sourceMissing"])
            event_rows = repo.state("2026-09-28")["calendarEvents"]
            self.assertEqual([row["sourceEventUid"] for row in event_rows], ["event-new"])

    def test_removing_and_readding_same_caldav_collection_reuses_local_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "planner.sqlite3", _source())
            identity = "https://calendar.example.test/dav/tasks/"
            account_id = repo.add_caldav_account(
                "Work", "calendar.example.test", "opaque-url", "opaque-credentials",
                source_identity=identity,
            )["id"]
            calendar = (
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                "BEGIN:VTODO\r\nUID:remote-task@example.test\r\n"
                "SUMMARY:Remote task\r\nSTATUS:NEEDS-ACTION\r\nEND:VTODO\r\n"
                "END:VCALENDAR\r\n"
            )
            resource = {
                "href": identity + "task.ics",
                "etag": '"v1"',
                "calendarData": calendar,
                "todo": parse_ical_vtodos(calendar)[1][0],
            }
            repo.sync_caldav_vtodos(account_id, [resource])
            original_id = repo.records()[0]["id"]
            self.assertTrue(repo.remove_caldav_account(account_id))
            self.assertTrue(repo.records()[0]["data"]["externalTodo"]["sourceMissing"])

            replacement_account = repo.add_caldav_account(
                "Work reconnected", "calendar.example.test", "new-opaque-url", "new-opaque-credentials",
                source_identity=identity,
            )["id"]
            result = repo.sync_caldav_vtodos(replacement_account, [resource])

            self.assertEqual(result["import"]["tasks"]["added"], 0)
            self.assertEqual(len(repo.records()), 1)
            task = repo.records()[0]
            self.assertEqual(task["id"], original_id)
            self.assertFalse(task["data"]["externalTodo"]["sourceMissing"])
            self.assertEqual(task["data"]["externalTodo"]["accountId"], replacement_account)

    def test_readding_legacy_account_migrates_existing_collection_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "planner.sqlite3", _source())
            identity = "https://calendar.example.test/dav/tasks/"
            account_id = repo.add_caldav_account(
                "Legacy Work", "calendar.example.test", "opaque-url", "opaque-credentials",
            )["id"]
            calendar = (
                "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
                "BEGIN:VTODO\r\nUID:legacy-task@example.test\r\n"
                "SUMMARY:Legacy task\r\nSTATUS:NEEDS-ACTION\r\nEND:VTODO\r\n"
                "END:VCALENDAR\r\n"
            )
            resource = {
                "href": identity + "task.ics",
                "etag": '"v1"',
                "calendarData": calendar,
                "todo": parse_ical_vtodos(calendar)[1][0],
            }
            repo.sync_caldav_vtodos(account_id, [resource])
            original = repo.records()[0]
            old_source_key = original["data"]["externalTodo"]["sourceKey"]
            self.assertTrue(repo.remove_caldav_account(account_id))

            readded = repo.add_caldav_account(
                "Legacy Work", "calendar.example.test", "new-url", "new-credentials",
                source_identity=identity,
            )
            self.assertNotEqual(readded["id"], account_id)
            result = repo.sync_caldav_vtodos(readded["id"], [resource])

            self.assertEqual(result["import"]["tasks"]["added"], 0)
            self.assertEqual(len(repo.records()), 1)
            current = repo.records()[0]
            self.assertEqual(current["id"], original["id"])
            self.assertEqual(current["data"]["externalTodo"]["sourceKey"], old_source_key)
            self.assertFalse(current["data"]["externalTodo"]["sourceMissing"])

    def test_account_credentials_are_hidden_and_probe_status_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planner.sqlite3"
            now = datetime(2026, 9, 28, 9, 0, tzinfo=timezone(timedelta(hours=8)))
            repo = PlannerRepository(path, _source(), clock=lambda: now)
            account = repo.add_caldav_account(
                "Work", "calendar.example.test", "opaque-url", "opaque-credentials",
            )
            account_id = account["id"]
            self.assertNotIn("urlProtected", repr(repo.state()))
            self.assertNotIn("credentialsProtected", repr(repo.state()))
            details = repo.caldav_account_details(account_id)
            self.assertEqual(details["credentialsProtected"], "opaque-credentials")

            calendars = [{"name": "Tasks", "components": ["VTODO"]}]
            self.assertTrue(repo.record_caldav_probe_result(account_id, calendars))
            visible = repo.state()["caldavAccounts"][0]
            self.assertEqual(visible["calendars"], calendars)
            self.assertNotIn("urlProtected", visible)
            self.assertNotIn("credentialsProtected", visible)

            reopened = PlannerRepository(path, clock=lambda: now)
            self.assertEqual(reopened.state()["caldavAccounts"][0]["calendars"], calendars)
            self.assertTrue(reopened.remove_caldav_account(account_id))
            self.assertEqual(reopened.state()["caldavAccounts"], [])

    def test_failed_probe_keeps_last_successful_calendar_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "planner.sqlite3", _source())
            account = repo.add_caldav_account(
                "Work", "calendar.example.test", "opaque-url", "opaque-credentials",
            )
            account_id = account["id"]
            calendars = [{"name": "Tasks", "components": ["VTODO"]}]
            repo.record_caldav_probe_result(account_id, calendars)
            repo.record_caldav_probe_result(account_id, error="服务器暂不可用。")
            visible = repo.state()["caldavAccounts"][0]
            self.assertEqual(visible["calendars"], calendars)
            self.assertEqual(visible["lastError"], "服务器暂不可用。")
