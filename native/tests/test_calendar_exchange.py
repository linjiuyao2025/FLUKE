from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from wanxiang.calendar_exchange import (
    CalendarExchangeError,
    calendar_occurrences_for_day,
    parse_ical_vtodos,
    parse_ics,
    task_events_to_ics,
)
from wanxiang.planner import PlannerRepository, PlannerRepositoryError


def _source() -> dict[str, object]:
    return {
        "richangji-state-v1": {
            "records": [], "settings": {}, "drafts": {"plannerForm": {}},
        }
    }


def _calendar(summary: str = "设计复盘", *, recurring: bool = False) -> str:
    recurrence = "RRULE:FREQ=DAILY\r\n" if recurring else ""
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:团队日历\r\n"
        "BEGIN:VEVENT\r\nUID:review-1@example.test\r\n"
        "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
        "DTEND;TZID=Asia/Shanghai:20260928T100000\r\n"
        f"SUMMARY:{summary}\r\nDESCRIPTION:要点一\\n要点二\\,补充\r\n"
        "LOCATION:线上会议室\r\n"
        f"{recurrence}END:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:holiday-1@example.test\r\n"
        "DTSTART;VALUE=DATE:20260929\r\nDTEND;VALUE=DATE:20260930\r\n"
        "SUMMARY:全天活动\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )


def _todo_calendar(
    title: str = "准备评审",
    *,
    percent: int = 25,
    second_status: str = "COMPLETED",
) -> str:
    escaped_title = title.replace(",", "\\,")
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:团队待办\r\n"
        "BEGIN:VTODO\r\nUID:review-task@example.test\r\n"
        "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
        "DUE;VALUE=DATE:20260929\r\n"
        f"SUMMARY:{escaped_title}\r\n"
        "DESCRIPTION:检查资料\\n整理结论\r\n"
        f"STATUS:IN-PROCESS\r\nPERCENT-COMPLETE:{percent}\r\nPRIORITY:2\r\n"
        "URL:https://example.test/task/review\r\nEND:VTODO\r\n"
        "BEGIN:VTODO\r\nUID:followup-task@example.test\r\n"
        "SUMMARY:发送会议纪要\r\n"
        f"STATUS:{second_status}\r\nPERCENT-COMPLETE:100\r\n"
        "COMPLETED:20260927T113000Z\r\nEND:VTODO\r\n"
        "END:VCALENDAR\r\n"
    )


def _todo_calendar_with_uids(name: str, uids: tuple[str, ...]) -> str:
    todos = "".join(
        "BEGIN:VTODO\r\n"
        f"UID:{uid}\r\n"
        f"SUMMARY:{uid}\r\n"
        "STATUS:NEEDS-ACTION\r\n"
        "END:VTODO\r\n"
        for uid in uids
    )
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        f"X-WR-CALNAME:{name}\r\n"
        f"{todos}END:VCALENDAR\r\n"
    )


class CalendarExchangeTests(unittest.TestCase):
    def test_vtodo_parser_reads_schedule_deadline_status_priority_and_notes(self) -> None:
        calendar_name, tasks = parse_ical_vtodos(_todo_calendar("准备,评审"))
        self.assertEqual(calendar_name, "团队待办")
        self.assertEqual(len(tasks), 2)
        first, second = tasks
        self.assertEqual(first["title"], "准备,评审")
        self.assertEqual(first["description"], "检查资料\n整理结论")
        self.assertEqual((first["startDate"], first["startTime"]), ("2026-09-28", "09:00"))
        self.assertEqual((first["dueDate"], first["dueTime"]), ("2026-09-29", ""))
        self.assertEqual((first["priority"], first["partial"], first["percentComplete"]), ("high", True, 25))
        self.assertFalse(first["done"])
        self.assertTrue(second["done"])
        self.assertEqual(second["completedAt"], "2026-09-27T19:30:00")
        self.assertEqual(first["url"], "https://example.test/task/review")

    def test_vtodo_parser_rejects_duplicate_uids_and_invalid_progress(self) -> None:
        duplicate = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VTODO\r\nUID:same\r\nSUMMARY:one\r\nEND:VTODO\r\n"
            "BEGIN:VTODO\r\nUID:same\r\nSUMMARY:two\r\nEND:VTODO\r\n"
            "END:VCALENDAR\r\n"
        )
        with self.assertRaises(CalendarExchangeError):
            parse_ical_vtodos(duplicate)
        with self.assertRaises(CalendarExchangeError):
            parse_ical_vtodos(_todo_calendar(percent=101))

    def test_cancelled_vtodo_is_not_mistaken_for_a_completed_task(self) -> None:
        _calendar_name, todos = parse_ical_vtodos(_todo_calendar(second_status="CANCELLED"))
        cancelled = todos[1]
        self.assertTrue(cancelled["cancelled"])
        self.assertFalse(cancelled["done"])

    def test_cancelled_external_todo_cannot_be_completed_or_tracked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "planner.sqlite3", _source())
            source_id = str(Path(directory) / "team-tasks.ics")
            repo.import_calendar(
                _todo_calendar(),
                "team-tasks.ics",
                source_id,
            )
            completed = next(
                row for row in repo.records()
                if row["data"].get("externalTodo", {}).get("uid") == "followup-task@example.test"
            )
            repo.toggle_task(completed["id"])
            repo.import_calendar(_todo_calendar(second_status="CANCELLED"), "team-tasks.ics", source_id)
            cancelled = next(
                row for row in repo.records()
                if row["data"].get("externalTodo", {}).get("uid") == "followup-task@example.test"
            )
            self.assertFalse(cancelled["data"]["done"])
            with self.assertRaisesRegex(PlannerRepositoryError, "来源已取消"):
                repo.toggle_task(cancelled["id"])
            with self.assertRaisesRegex(PlannerRepositoryError, "来源已取消"):
                repo.start_tracking(cancelled["id"])

    def test_vtodo_parser_rejects_recurrence_until_supported(self) -> None:
        recurring = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VTODO\r\nUID:weekly@example.test\r\nSUMMARY:周任务\r\n"
            "RRULE:FREQ=WEEKLY\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
        )
        with self.assertRaisesRegex(CalendarExchangeError, "重复待办暂不导入"):
            parse_ical_vtodos(recurring)

    def test_imports_vtodos_idempotently_and_preserves_local_tracking_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = [datetime(2026, 9, 28, 8, 0, tzinfo=timezone(timedelta(hours=8)))]
            path = Path(directory) / "calendar.sqlite3"
            repo = PlannerRepository(path, _source(), clock=lambda: now[0])
            source_id = str(Path(directory) / "team-tasks.ics")
            first = repo.import_calendar(_todo_calendar(), "team-tasks.ics", source_id)
            self.assertEqual((first["added"], first["total"]), (0, 0))
            self.assertEqual(first["tasks"], {
                "added": 2, "updated": 0, "unchanged": 0, "cancelled": 0,
                "sourceMissing": 0, "total": 2,
            })
            rows = repo.records()
            self.assertEqual(len(rows), 2)
            review = next(row for row in rows if row["data"]["externalTodo"]["uid"] == "review-task@example.test")
            self.assertEqual(review["date"], "2026-09-29")
            self.assertEqual(review["data"]["plannedDate"], "2026-09-28")
            self.assertEqual(review["data"]["plannedStart"], "09:00")
            self.assertEqual(review["data"]["externalTodo"]["sourceKey"], rows[0]["data"]["externalTodo"]["sourceKey"])
            repo.set_estimate(review["id"], 60)

            repeated = repo.import_calendar(_todo_calendar(), "team-tasks.ics", source_id)
            self.assertEqual(repeated["tasks"]["unchanged"], 2)
            updated = repo.import_calendar(
                _todo_calendar("准备新版评审", percent=100, second_status="CANCELLED"),
                "team-tasks.ics",
                source_id,
            )
            self.assertEqual((updated["tasks"]["updated"], updated["tasks"]["cancelled"]), (2, 1))
            current = {row["data"]["externalTodo"]["uid"]: row for row in repo.records()}
            self.assertEqual(current["review-task@example.test"]["data"]["estimateMinutes"], 60)
            self.assertTrue(current["review-task@example.test"]["data"]["done"])
            self.assertEqual(current["review-task@example.test"]["data"]["title"], "准备新版评审")
            self.assertTrue(current["followup-task@example.test"]["data"]["externalTodo"]["cancelled"])
            reopened = PlannerRepository(path, clock=lambda: now[0])
            self.assertEqual(len(reopened.records()), 2)

    def test_vtodo_source_removal_marks_local_copy_and_move_keeps_same_import_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.sqlite3"
            repo = PlannerRepository(path, _source())
            original_path = str(Path(directory) / "team-tasks.ics")
            first = repo.import_calendar(_todo_calendar(), "team-tasks.ics", original_path)
            self.assertEqual(first["tasks"]["added"], 2)
            review = next(row for row in repo.records() if row["data"]["externalTodo"]["uid"] == "review-task@example.test")
            repo.set_estimate(review["id"], 75)

            moved_path = str(Path(directory) / "archive" / "team-tasks.ics")
            moved = repo.import_calendar(_todo_calendar("准备评审新版"), "team-tasks.ics", moved_path)
            self.assertEqual((moved["tasks"]["updated"], moved["tasks"]["unchanged"]), (1, 1))
            self.assertEqual(len(repo.records()), 2)
            review = next(row for row in repo.records() if row["data"]["externalTodo"]["uid"] == "review-task@example.test")
            self.assertEqual(review["data"]["estimateMinutes"], 75)

            one_todo = _todo_calendar().replace(
                "BEGIN:VTODO\r\nUID:followup-task@example.test\r\n"
                "SUMMARY:发送会议纪要\r\nSTATUS:COMPLETED\r\nPERCENT-COMPLETE:100\r\n"
                "COMPLETED:20260927T113000Z\r\nEND:VTODO\r\n",
                "",
            )
            removed = repo.import_calendar(one_todo, "team-tasks.ics", moved_path)
            self.assertEqual(removed["tasks"]["sourceMissing"], 1)
            followup = next(row for row in repo.records() if row["data"]["externalTodo"]["uid"] == "followup-task@example.test")
            self.assertTrue(followup["data"]["externalTodo"]["sourceMissing"])
            reopened = PlannerRepository(path)
            followup = next(row for row in reopened.records() if row["data"]["externalTodo"]["uid"] == "followup-task@example.test")
            self.assertTrue(followup["data"]["externalTodo"]["sourceMissing"])
            restored = reopened.import_calendar(_todo_calendar(), "team-tasks.ics", moved_path)
            self.assertEqual(
                (restored["tasks"]["updated"], restored["tasks"]["unchanged"]),
                (1, 1),
            )
            followup = next(row for row in reopened.records() if row["data"]["externalTodo"]["uid"] == "followup-task@example.test")
            self.assertFalse(followup["data"]["externalTodo"]["sourceMissing"])

    def test_same_name_sources_with_overlapping_uids_keep_separate_identities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "calendar.sqlite3", _source())
            source_a = str(Path(directory) / "a.ics")
            source_b = str(Path(directory) / "b.ics")
            repo.import_calendar(
                _todo_calendar_with_uids("Shared calendar", ("shared", "a-only")),
                "Shared calendar", source_a,
            )

            repo.import_calendar(
                _todo_calendar_with_uids("Shared calendar", ("shared", "b-only")),
                "Shared calendar", source_b,
            )

            rows_by_uid: dict[str, list[dict[str, object]]] = {}
            for row in repo.records():
                external = row["data"]["externalTodo"]
                rows_by_uid.setdefault(external["uid"], []).append(row)
            self.assertEqual(set(rows_by_uid), {"shared", "a-only", "b-only"})
            self.assertEqual(len(rows_by_uid["shared"]), 2)
            self.assertFalse(rows_by_uid["a-only"][0]["data"]["externalTodo"]["sourceMissing"])
            self.assertFalse(rows_by_uid["b-only"][0]["data"]["externalTodo"]["sourceMissing"])
            source_keys = {
                row["data"]["externalTodo"]["sourceKey"]
                for row in rows_by_uid["shared"]
            }
            self.assertEqual(len(source_keys), 2)

            repo.import_calendar(
                _todo_calendar_with_uids("Shared calendar", ("shared", "b-only")),
                "Shared calendar", source_b,
            )
            a_only = next(row for row in repo.records() if row["data"]["externalTodo"]["uid"] == "a-only")
            self.assertFalse(a_only["data"]["externalTodo"]["sourceMissing"])

    def test_cancelled_vtodo_cannot_be_scheduled_or_remain_on_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixed = datetime(2026, 9, 28, 8, 0)
            repo = PlannerRepository(
                Path(directory) / "calendar.sqlite3", _source(), clock=lambda: fixed,
            )
            active_calendar = _todo_calendar().replace(
                "STATUS:IN-PROCESS", "STATUS:NEEDS-ACTION",
            )
            repo.import_calendar(active_calendar, "团队待办", str(Path(directory) / "team.ics"))
            task = next(
                row for row in repo.records()
                if row["data"]["externalTodo"]["uid"] == "review-task@example.test"
            )
            repo.schedule_task(task["id"], "2026-09-28", "09:00", 30)

            cancelled_calendar = active_calendar.replace(
                "STATUS:NEEDS-ACTION", "STATUS:CANCELLED",
            )
            repo.import_calendar(cancelled_calendar, "团队待办", str(Path(directory) / "team.ics"))

            cancelled_task = next(row for row in repo.records() if row["id"] == task["id"])
            self.assertTrue(cancelled_task["data"]["externalTodo"]["cancelled"])
            with self.assertRaisesRegex(PlannerRepositoryError, "取消"):
                repo.schedule_task(task["id"], "2026-09-28", "10:00", 30)
            with self.assertRaisesRegex(PlannerRepositoryError, "取消"):
                repo.set_task_status(task["id"], "done")
            timeline = repo.state("2026-09-28")["timeline"]
            self.assertNotIn(task["id"], [row["id"] for row in timeline["blocks"]])
            self.assertNotIn(task["id"], [row["id"] for row in timeline["unscheduled"]])

    def test_deleting_imported_vtodo_survives_restart_and_same_source_reimport(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calendar.sqlite3"
            source_id = str(Path(directory) / "team-tasks.ics")
            repo = PlannerRepository(path, _source())
            repo.import_calendar(_todo_calendar(), "team-tasks.ics", source_id)
            review = next(row for row in repo.records() if row["data"]["externalTodo"]["uid"] == "review-task@example.test")
            self.assertTrue(repo.delete_task(review["id"]))
            reopened = PlannerRepository(path)
            self.assertEqual(len(reopened.records()), 1)
            result = reopened.import_calendar(_todo_calendar(), "team-tasks.ics", source_id)
            self.assertEqual(result["tasks"]["unchanged"], 2)
            self.assertEqual(
                [row["data"]["externalTodo"]["uid"] for row in reopened.records()],
                ["followup-task@example.test"],
            )

    def test_manual_ics_reimport_removes_missing_events_from_only_that_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "calendar.sqlite3", _source())
            source_id = str(Path(directory) / "team.ics")
            first = repo.import_calendar(_calendar(), "team.ics", source_id)
            self.assertEqual(first["added"], 2)
            one_event = _calendar().replace(
                "BEGIN:VEVENT\r\nUID:holiday-1@example.test\r\n"
                "DTSTART;VALUE=DATE:20260929\r\nDTEND;VALUE=DATE:20260930\r\n"
                "SUMMARY:全天活动\r\nEND:VEVENT\r\n",
                "",
            )
            result = repo.import_calendar(one_event, "team.ics", source_id)
            self.assertEqual((result["added"], result["removed"], result["total"]), (0, 1, 1))
            self.assertEqual(len(repo._state["calendarEvents"]), 1)
            self.assertEqual(repo._state["calendarEvents"][0]["sourceEventUid"], "review-1@example.test")

    def test_import_reads_timed_and_all_day_events_and_deduplicates_by_uid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = [datetime(2026, 9, 28, 8, 0, tzinfo=timezone(timedelta(hours=8)))]
            repo = PlannerRepository(
                Path(directory) / "calendar.sqlite3", _source(), clock=lambda: now[0]
            )
            local_task = repo.add_task("本机任务", "2026-09-28")
            first = repo.import_calendar(_calendar(), "team.ics")
            self.assertEqual((first["added"], first["updated"], first["unchanged"]), (2, 0, 0))
            again = repo.import_calendar(_calendar(), "team.ics")
            self.assertEqual((again["added"], again["updated"], again["unchanged"]), (0, 0, 2))
            self.assertEqual(len(repo.records()), 1)
            self.assertEqual(repo.records()[0]["id"], local_task["id"])

            repo.set_selected_day("2026-09-28")
            events = repo.state("2026-09-28")["calendarEvents"]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["title"], "设计复盘")
            self.assertEqual(events[0]["displayTime"], "09:00–10:00")
            self.assertEqual(events[0]["description"], "要点一\n要点二,补充")
            self.assertEqual(events[0]["location"], "线上会议室")

            repo.set_selected_day("2026-09-29")
            holiday = repo.state("2026-09-29")["calendarEvents"]
            self.assertEqual(len(holiday), 1)
            self.assertTrue(holiday[0]["allDay"])
            self.assertEqual(holiday[0]["displayTime"], "全天")
            repo.set_selected_day("2026-09-30")
            self.assertEqual(repo.state("2026-09-30")["calendarEvents"], [])
            changed = repo.import_calendar(_calendar("设计复盘更新"), "team.ics")
            self.assertEqual((changed["added"], changed["updated"], changed["unchanged"]), (0, 1, 1))
            repo.set_selected_day("2026-09-28")
            self.assertEqual(repo.state("2026-09-28")["calendarEvents"][0]["title"], "设计复盘更新")

    def test_busy_calendar_events_block_suggestions_and_transparent_events_do_not(self) -> None:
        calendar = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:busy@example.test\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
            "DTEND;TZID=Asia/Shanghai:20260928T100000\r\n"
            "SUMMARY:占用会议\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:free@example.test\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260928T100000\r\n"
            "DTEND;TZID=Asia/Shanghai:20260928T110000\r\n"
            "SUMMARY:自由事件\r\nTRANSP:TRANSPARENT\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "calendar-busy.sqlite3", _source())
            repo.import_calendar(calendar, "availability.ics")
            task = repo.add_task("会议后排程", "2026-09-28")

            snapshot = repo.state("2026-09-28")
            timeline = snapshot["timeline"]
            self.assertEqual(len(timeline["eventBlocks"]), 1)
            self.assertEqual(timeline["eventBlocks"][0]["title"], "占用会议")
            self.assertEqual(timeline["freeMinutes"], 900)

            repo.schedule_task(task["id"], "2026-09-28", "09:30", 30)
            scheduled = repo.state("2026-09-28")["timeline"]["blocks"]
            self.assertEqual(len(scheduled), 1)
            self.assertTrue(scheduled[0]["conflict"])
            self.assertEqual(repo.state("2026-09-28")["timeline"]["conflictCount"], 1)

    def test_recurrence_override_can_change_calendar_busy_status(self) -> None:
        recurring = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:recurring-availability@example.test\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
            "DTEND;TZID=Asia/Shanghai:20260928T100000\r\n"
            "RRULE:FREQ=DAILY;COUNT=3\r\nTRANSP:TRANSPARENT\r\n"
            "SUMMARY:默认空闲\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:recurring-availability@example.test\r\n"
            "RECURRENCE-ID;TZID=Asia/Shanghai:20260929T090000\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260929T100000\r\n"
            "DTEND;TZID=Asia/Shanghai:20260929T110000\r\n"
            "TRANSP:OPAQUE\r\nSUMMARY:例外占用\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        local_zone = ZoneInfo("Asia/Shanghai")
        with patch("wanxiang.calendar_exchange.get_localzone", return_value=local_zone):
            _name, events = parse_ics(recurring)
            self.assertEqual(events[0]["transparency"], "TRANSPARENT")
            normal_day = calendar_occurrences_for_day(events, "2026-09-28")
            exception_day = calendar_occurrences_for_day(events, "2026-09-29")

        self.assertEqual(normal_day[0]["transparency"], "TRANSPARENT")
        self.assertEqual(exception_day[0]["transparency"], "OPAQUE")
        self.assertEqual(exception_day[0]["title"], "例外占用")

    def test_import_expands_daily_rrule_rdate_and_exdate_on_selected_day(self) -> None:
        recurring = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:daily@example.test\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
            "DTEND;TZID=Asia/Shanghai:20260928T100000\r\n"
            "RRULE:FREQ=DAILY;COUNT=4\r\n"
            "EXDATE;TZID=Asia/Shanghai:20260929T090000\r\n"
            "RDATE;TZID=Asia/Shanghai:20261002T130000\r\n"
            "SUMMARY:每日例会\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "calendar-repeat.sqlite3", _source())
            imported = repo.import_calendar(recurring, "repeat.ics")
            self.assertEqual(imported["added"], 1)
            self.assertEqual(len(repo._state["calendarEvents"]), 1)
            repo.set_selected_day("2026-09-29")
            self.assertEqual(repo.state("2026-09-29")["calendarEvents"], [])
            repo.set_selected_day("2026-09-30")
            occurrence = repo.state("2026-09-30")["calendarEvents"]
            self.assertEqual(len(occurrence), 1)
            self.assertTrue(occurrence[0]["recurringInstance"])
            self.assertEqual(occurrence[0]["displayTime"], "09:00–10:00")
            repo.set_selected_day("2026-10-02")
            extra_date = repo.state("2026-10-02")["calendarEvents"]
            self.assertEqual(len(extra_date), 1)
            self.assertEqual(extra_date[0]["displayTime"], "13:00–14:00")

    def test_utc_and_other_zone_recurrence_dates_are_converted_to_master_timezone(self) -> None:
        recurring = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:mixed-zone@example.test\r\n"
            "DTSTART;TZID=America/New_York:20260928T090000\r\n"
            "DTEND;TZID=America/New_York:20260928T100000\r\n"
            "RRULE:FREQ=DAILY;COUNT=3\r\n"
            "EXDATE:20260929T130000Z\r\n"
            "RDATE:20261002T130000Z\r\n"
            "RDATE;TZID=Asia/Shanghai:20261003T130000\r\n"
            "SUMMARY:跨时区重复会议\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        local_zone = ZoneInfo("Asia/Shanghai")
        with patch("wanxiang.calendar_exchange.get_localzone", return_value=local_zone):
            calendar_name, events = parse_ics(recurring)
            self.assertEqual(calendar_name, "外部日历")
            self.assertEqual(events[0]["excludedDates"], ["2026-09-29T09:00:00"])
            self.assertEqual(events[0]["recurrenceDates"], [
                "2026-10-02T09:00:00",
                "2026-10-03T01:00:00",
            ])
            self.assertEqual(calendar_occurrences_for_day(events, "2026-09-29"), [])
            utc_addition = calendar_occurrences_for_day(events, "2026-10-02")
            self.assertEqual(len(utc_addition), 1)
            self.assertEqual(
                datetime.fromisoformat(utc_addition[0]["startAt"]).astimezone(local_zone).strftime("%H:%M"),
                "21:00",
            )
            zoned_addition = calendar_occurrences_for_day(events, "2026-10-03")
            self.assertEqual(len(zoned_addition), 1)
            self.assertEqual(
                datetime.fromisoformat(zoned_addition[0]["startAt"]).astimezone(local_zone).strftime("%H:%M"),
                "13:00",
            )

    def test_utc_recurrence_date_rejects_an_explicit_tzid(self) -> None:
        invalid = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:invalid-utc-rdate@example.test\r\n"
            "DTSTART;TZID=America/New_York:20260928T090000\r\n"
            "DTEND;TZID=America/New_York:20260928T100000\r\n"
            "RDATE;TZID=America/New_York:20261002T130000Z\r\n"
            "SUMMARY:无效 UTC 时区组合\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with self.assertRaisesRegex(CalendarExchangeError, "UTC 时间不能同时声明 TZID"):
            parse_ics(invalid)

    def test_date_recurrence_value_rejects_tzid(self) -> None:
        invalid = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:invalid-date-rdate@example.test\r\n"
            "DTSTART;VALUE=DATE:20260928\r\n"
            "RRULE:FREQ=DAILY;COUNT=2\r\n"
            "RDATE;VALUE=DATE;TZID=America/New_York:20260930\r\n"
            "SUMMARY:无效日期时区组合\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with self.assertRaisesRegex(CalendarExchangeError, "DATE 值不能同时声明 TZID"):
            parse_ics(invalid)

    def test_recurrence_keeps_named_timezone_across_dst(self) -> None:
        recurring = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:berlin@example.test\r\n"
            "DTSTART;TZID=Europe/Berlin:20261024T090000\r\n"
            "DTEND;TZID=Europe/Berlin:20261024T100000\r\n"
            "RRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:柏林例会\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "calendar-dst.sqlite3", _source())
            repo.import_calendar(recurring, "dst.ics")
            repo.set_selected_day("2026-10-25")
            occurrence = repo.state("2026-10-25")["calendarEvents"]
            self.assertEqual(len(occurrence), 1)
            self.assertEqual(occurrence[0]["displayTime"], "16:00–17:00")

    def test_custom_vtimezone_and_moved_cancelled_recurrence_exceptions_survive_restart(self) -> None:
        recurring = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VTIMEZONE\r\nTZID:Custom/India\r\n"
            "BEGIN:STANDARD\r\nDTSTART:19700101T000000\r\n"
            "TZOFFSETFROM:+0530\r\nTZOFFSETTO:+0530\r\nEND:STANDARD\r\nEND:VTIMEZONE\r\n"
            "BEGIN:VEVENT\r\nUID:custom-series@example.test\r\n"
            "DTSTART;TZID=Custom/India:20260928T090000\r\n"
            "DTEND;TZID=Custom/India:20260928T100000\r\n"
            "RRULE:FREQ=DAILY;COUNT=4\r\nSUMMARY:每日碰头\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:custom-series@example.test\r\n"
            "RECURRENCE-ID;TZID=Custom/India:20260929T090000\r\n"
            "DTSTART;TZID=Custom/India:20260930T110000\r\n"
            "DTEND;TZID=Custom/India:20260930T120000\r\nSUMMARY:改期碰头\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:custom-series@example.test\r\n"
            "RECURRENCE-ID;TZID=Custom/India:20261001T090000\r\n"
            "DTSTART;TZID=Custom/India:20261001T090000\r\n"
            "DTEND;TZID=Custom/India:20261001T100000\r\n"
            "STATUS:CANCELLED\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "custom-calendar.sqlite3"
            repo = PlannerRepository(database, _source())
            imported = repo.import_calendar(recurring, "custom.ics")
            self.assertEqual((imported["added"], imported["updated"], imported["unchanged"]), (1, 0, 0))
            self.assertEqual(repo.import_calendar(recurring, "custom.ics")["unchanged"], 1)

            repo.set_selected_day("2026-09-29")
            self.assertEqual(repo.state("2026-09-29")["calendarEvents"], [])
            repo.set_selected_day("2026-09-30")
            moved = repo.state("2026-09-30")["calendarEvents"]
            self.assertEqual([event["title"] for event in moved], ["每日碰头", "改期碰头"])
            self.assertEqual([event["displayTime"] for event in moved], ["11:30–12:30", "13:30–14:30"])

            reopened = PlannerRepository(database, _source())
            reopened.set_selected_day("2026-10-01")
            self.assertEqual(reopened.state("2026-10-01")["calendarEvents"], [])
            reopened.set_selected_day("2026-09-30")
            self.assertEqual([event["title"] for event in reopened.state("2026-09-30")["calendarEvents"]], ["每日碰头", "改期碰头"])

    def test_embedded_vtimezone_applies_its_daylight_saving_rules(self) -> None:
        recurring = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VTIMEZONE\r\nTZID:Custom/NewYork\r\n"
            "BEGIN:STANDARD\r\nDTSTART:20261101T020000\r\n"
            "RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU\r\n"
            "TZOFFSETFROM:-0400\r\nTZOFFSETTO:-0500\r\nEND:STANDARD\r\n"
            "BEGIN:DAYLIGHT\r\nDTSTART:20260308T020000\r\n"
            "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU\r\n"
            "TZOFFSETFROM:-0500\r\nTZOFFSETTO:-0400\r\nEND:DAYLIGHT\r\nEND:VTIMEZONE\r\n"
            "BEGIN:VEVENT\r\nUID:custom-dst@example.test\r\n"
            "DTSTART;TZID=Custom/NewYork:20260307T090000\r\n"
            "DTEND;TZID=Custom/NewYork:20260307T100000\r\n"
            "RRULE:FREQ=DAILY;COUNT=3\r\nSUMMARY:纽约例会\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "custom-dst.sqlite3", _source())
            repo.import_calendar(recurring, "custom-dst.ics")
            before = repo.state("2026-03-07")["calendarEvents"]
            after = repo.state("2026-03-08")["calendarEvents"]
            self.assertEqual(before[0]["startAt"], "2026-03-07T09:00:00-05:00")
            self.assertEqual(after[0]["startAt"], "2026-03-08T09:00:00-04:00")

    def test_this_and_future_changes_later_instances_and_single_override_wins(self) -> None:
        series = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:range-series@example.test\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
            "DTEND;TZID=Asia/Shanghai:20260928T100000\r\n"
            "RRULE:FREQ=DAILY;COUNT=5\r\nSUMMARY:例会\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:range-series@example.test\r\n"
            "RECURRENCE-ID;TZID=Asia/Shanghai;RANGE=THISANDFUTURE:20260930T090000\r\n"
            "DTSTART;TZID=Asia/Shanghai:20261001T110000\r\n"
            "DTEND;TZID=Asia/Shanghai:20261001T120000\r\n"
            "SUMMARY:调整后的例会\r\nLOCATION:新会议室\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:range-series@example.test\r\n"
            "RECURRENCE-ID;TZID=Asia/Shanghai:20261001T090000\r\n"
            "DTSTART;TZID=Asia/Shanghai:20261001T130000\r\n"
            "DTEND;TZID=Asia/Shanghai:20261001T140000\r\n"
            "SUMMARY:仅此一次\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "range-calendar.sqlite3", _source())
            result = repo.import_calendar(series, "range.ics")
            self.assertEqual((result["added"], result["updated"]), (1, 0))
            repo.set_selected_day("2026-09-29")
            self.assertEqual(repo.state("2026-09-29")["calendarEvents"][0]["displayTime"], "09:00–10:00")
            repo.set_selected_day("2026-10-01")
            moved_and_single = repo.state("2026-10-01")["calendarEvents"]
            self.assertEqual([event["title"] for event in moved_and_single], ["调整后的例会", "仅此一次"])
            self.assertEqual([event["displayTime"] for event in moved_and_single], ["11:00–12:00", "13:00–14:00"])
            self.assertEqual(moved_and_single[0]["location"], "新会议室")
            repo.set_selected_day("2026-10-02")
            self.assertEqual(repo.state("2026-10-02")["calendarEvents"], [])
            repo.set_selected_day("2026-10-03")
            future = repo.state("2026-10-03")["calendarEvents"]
            self.assertEqual([event["title"] for event in future], ["调整后的例会"])
            self.assertEqual(future[0]["displayTime"], "11:00–12:00")

    def test_this_and_future_duration_extension_is_found_on_intervening_days(self) -> None:
        series = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:extended-range@example.test\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
            "DTEND;TZID=Asia/Shanghai:20260928T100000\r\n"
            "RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=MO\r\nSUMMARY:Weekly review\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:extended-range@example.test\r\n"
            "RECURRENCE-ID;TZID=Asia/Shanghai;RANGE=THISANDFUTURE:20260928T090000\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
            "DTEND;TZID=Asia/Shanghai:20261008T090000\r\n"
            "SUMMARY:Extended review\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        events = parse_ics(series)[1]
        occurrence = calendar_occurrences_for_day(events, "2026-10-01")
        self.assertEqual([event["title"] for event in occurrence], ["Extended review"])
        self.assertEqual(occurrence[0]["startAt"], "2026-09-28T09:00:00+08:00")
        self.assertEqual(occurrence[0]["endAt"], "2026-10-08T09:00:00+08:00")
    def test_all_day_this_and_future_reschedules_from_original_recurrence_date(self) -> None:
        series = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:all-day-range@example.test\r\n"
            "DTSTART;VALUE=DATE:20260928\r\nDTEND;VALUE=DATE:20260929\r\n"
            "RRULE:FREQ=DAILY;COUNT=4\r\nSUMMARY:全天例会\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:all-day-range@example.test\r\n"
            "RECURRENCE-ID;RANGE=THISANDFUTURE;VALUE=DATE:20260929\r\n"
            "DTSTART;VALUE=DATE:20260930\r\nDTEND;VALUE=DATE:20261001\r\n"
            "SUMMARY:调整后的全天例会\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "all-day-range.sqlite3", _source())
            repo.import_calendar(series, "all-day-range.ics")
            repo.set_selected_day("2026-09-29")
            self.assertEqual(repo.state("2026-09-29")["calendarEvents"], [])
            repo.set_selected_day("2026-09-30")
            moved = repo.state("2026-09-30")["calendarEvents"]
            self.assertEqual([event["title"] for event in moved], ["调整后的全天例会"])
            self.assertTrue(moved[0]["allDay"])
            self.assertEqual(moved[0]["startDate"], "2026-09-30")
            repo.set_selected_day("2026-10-01")
            self.assertEqual([event["title"] for event in repo.state("2026-10-01")["calendarEvents"]], ["调整后的全天例会"])

    def test_this_and_future_cancellation_removes_anchor_and_later_occurrences(self) -> None:
        series = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:cancel-range@example.test\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
            "DTEND;TZID=Asia/Shanghai:20260928T100000\r\n"
            "RRULE:FREQ=DAILY;COUNT=4\r\nSUMMARY:每日例会\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:cancel-range@example.test\r\n"
            "RECURRENCE-ID;TZID=Asia/Shanghai;RANGE=THISANDFUTURE:20260930T090000\r\n"
            "STATUS:CANCELLED\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "cancel-range.sqlite3", _source())
            repo.import_calendar(series, "cancel-range.ics")
            repo.set_selected_day("2026-09-29")
            self.assertEqual(len(repo.state("2026-09-29")["calendarEvents"]), 1)
            for day_key in ("2026-09-30", "2026-10-01", "2026-10-02"):
                repo.set_selected_day(day_key)
                self.assertEqual(repo.state(day_key)["calendarEvents"], [])

    def test_monthly_all_day_rule_skips_invalid_month_dates(self) -> None:
        recurring = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:first-monday@example.test\r\n"
            "DTSTART;VALUE=DATE:20260907\r\nDTEND;VALUE=DATE:20260908\r\n"
            "RRULE:FREQ=MONTHLY;COUNT=3;BYDAY=1MO\r\nSUMMARY:每月计划\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "calendar-monthly.sqlite3", _source())
            repo.import_calendar(recurring, "monthly.ics")
            repo.set_selected_day("2026-10-05")
            occurrence = repo.state("2026-10-05")["calendarEvents"]
            self.assertEqual(len(occurrence), 1)
            self.assertTrue(occurrence[0]["allDay"])
            self.assertEqual(occurrence[0]["displayTime"], "全天")

    def test_import_rejects_unsupported_recurrence_and_unknown_timezone_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "calendar-reject.sqlite3", _source())
            hourly = _calendar().replace("DTSTART;TZID=Asia/Shanghai:20260928T090000", "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\nRRULE:FREQ=HOURLY")
            with self.assertRaisesRegex(PlannerRepositoryError, "频率"):
                repo.import_calendar(hourly, "team.ics")
            self.assertEqual(repo._state["calendarEvents"], [])
            unknown_zone = _calendar().replace("Asia/Shanghai", "Mars/Olympus")
            with self.assertRaisesRegex(PlannerRepositoryError, "无法识别的时区"):
                repo.import_calendar(unknown_zone, "team.ics")
            self.assertEqual(repo._state["calendarEvents"], [])

    def test_export_round_trips_scheduled_and_all_day_tasks_with_folded_utf8_lines(self) -> None:
        timezone_local = datetime.now().astimezone().tzinfo
        now = datetime(2026, 9, 28, 8, 0, tzinfo=timezone_local)
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "calendar-export.sqlite3", _source(), clock=lambda: now)
            repo.add_task(
                "会议信息" * 14, "2026-09-28", "09:30", estimate_minutes=45,
                project="FLUKE", tags=["日历"], note="需要讨论导入与时区处理",
            )
            repo.add_task("全天准备", "2026-09-29", estimate_minutes=30)
            repo.add_task("区间外任务", "2026-10-10")
            payload = task_events_to_ics(repo.records(), "2026-09-28", "2026-09-29", now)
            physical_lines = payload.split("\r\n")
            self.assertTrue(all(len(line.encode("utf-8")) <= 75 for line in physical_lines))
            name, events = parse_ics(payload)
            self.assertEqual(name, "FLUKE 日程")
            self.assertEqual(len(events), 2)
            self.assertFalse(events[0]["allDay"])
            self.assertIn("会议信息", events[0]["title"])
            self.assertIn("讨论导入与时区处理", events[0]["description"])
            self.assertTrue(events[1]["allDay"])
            self.assertEqual(events[1]["startDate"], "2026-09-29")

            path = repo.export_calendar_ics(Path(directory) / "tasks.ics", "2026-09-28", "2026-09-29")
            self.assertTrue(path.is_file())
            self.assertEqual(len(parse_ics(path.read_text(encoding="utf-8"))[1]), 2)
            with self.assertRaises(PlannerRepositoryError):
                repo.export_calendar_ics(Path(directory) / "tasks.txt", "2026-09-28", "2026-09-29")

    def test_vevent_alarm_description_is_not_imported_as_event_description(self) -> None:
        calendar = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:alarm-only@example.test\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260928T090000\r\n"
            "DTEND;TZID=Asia/Shanghai:20260928T100000\r\nSUMMARY:Alarm only\r\n"
            "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Reminder text\r\n"
            "TRIGGER:-PT5M\r\nEND:VALARM\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:event-description@example.test\r\n"
            "DTSTART;TZID=Asia/Shanghai:20260929T090000\r\n"
            "DTEND;TZID=Asia/Shanghai:20260929T100000\r\nSUMMARY:Event description\r\n"
            "DESCRIPTION:Meeting notes\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\n"
            "DESCRIPTION:Reminder text\r\nTRIGGER:-PT5M\r\nEND:VALARM\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        events = parse_ics(calendar)[1]
        self.assertEqual(events[0]["description"], "")
        self.assertEqual(events[1]["description"], "Meeting notes")
    def test_parser_rejects_incomplete_calendar_and_duplicate_uids(self) -> None:
        with self.assertRaises(CalendarExchangeError):
            parse_ics("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n")
        duplicate = _calendar().replace(
            "UID:holiday-1@example.test", "UID:review-1@example.test",
        )
        with self.assertRaisesRegex(CalendarExchangeError, "重复 UID"):
            parse_ics(duplicate)


if __name__ == "__main__":
    unittest.main()
