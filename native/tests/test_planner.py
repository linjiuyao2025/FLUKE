from __future__ import annotations

import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wanxiang.planner import PlannerRepository, PlannerRepositoryError


def _record(
    record_id: str,
    day: str,
    data: dict[str, object],
    *,
    created_at: int = 1,
    sample: bool = False,
    **extra: object,
) -> dict[str, object]:
    return {
        "id": record_id,
        "type": "planner",
        "date": day,
        "createdAt": created_at,
        "sample": sample,
        "data": data,
        **extra,
    }


def _source(records: list[dict[str, object]], **state_extra: object) -> dict[str, object]:
    return {
        "richangji-state-v1": {
            "records": records,
            "settings": {"plannerFilter": "all", "unownedSetting": {"keep": True}},
            "drafts": {"plannerForm": {"title": "恢复草稿", "remind": True}},
            **state_extra,
        }
    }


def _edit_task(repo: PlannerRepository, record_id: str, **overrides: object) -> dict[str, object] | None:
    fields: dict[str, object] = {
        "title": "更新后的待办",
        "date": "2026-09-27",
        "time": "10:00",
        "priority": "normal",
        "list_name": "生活",
        "note": "",
        "remind": True,
        "estimate_minutes": 30,
        "repeat": "none",
        "project": "",
        "tags": [],
    }
    fields.update(overrides)
    return repo.update_task(record_id, **fields)


class PlannerRepositoryTests(unittest.TestCase):
    def test_legacy_estimates_are_rounded_for_scheduling_without_rewriting_source(self) -> None:
        imported = _record(
            "legacy-seven-minute",
            "2026-09-28",
            {
                "title": "旧数据估时",
                "time": "",
                "plannedDate": "",
                "plannedStart": "",
                "estimateMinutes": 7,
                "done": False,
            },
        )
        source = _source([imported])
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "legacy-estimate.sqlite3", source)
            visible = repo.records()[0]
            self.assertEqual(visible["data"]["estimateMinutes"], 10)
            self.assertEqual(
                repo._state["legacyRecords"][0]["data"]["estimateMinutes"], 7,
                "rounding must leave the imported legacy snapshot untouched",
            )

            scheduled = repo.schedule_task(
                visible["id"], "2026-09-28", "10:15", visible["data"]["estimateMinutes"],
            )
            self.assertIsNotNone(scheduled)
            self.assertEqual(scheduled["data"]["estimateMinutes"], 10)
            timeline = repo.state("2026-09-28")["timeline"]
            self.assertEqual(len(timeline["blocks"]), 1)
            self.assertEqual(timeline["blocks"][0]["endMinute"] - timeline["blocks"][0]["startMinute"], 10)

    def test_legacy_records_are_copied_and_unknown_fields_survive_overlays(self) -> None:
        legacy = _record(
            "old-1",
            "2026-09-27",
            {"title": "合成待办", "time": "09:00", "done": False, "legacyData": {"x": 1}},
            sample=True,
            customEnvelope={"keep": [1, 2]},
        )
        source_state = _source([legacy, {"id": "money-1", "type": "money", "data": {"amount": 2}}])
        before = json.loads(json.dumps(source_state, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as directory:
            repository = PlannerRepository(Path(directory) / "planner.sqlite3", source_state)
            original = repository.records()[0]
            self.assertEqual(original, legacy)
            self.assertEqual(repository.toggle_task("old-1")["data"]["done"], True)
            after_overlay = repository.records()[0]
            self.assertTrue(after_overlay["sample"])
            self.assertEqual(after_overlay["customEnvelope"], {"keep": [1, 2]})
            self.assertEqual(after_overlay["data"]["legacyData"], {"x": 1})
            self.assertTrue(after_overlay["data"]["done"])
            self.assertEqual(source_state, before)
            self.assertEqual(repository.state("2026-09-27")["draft"], {"title": "恢复草稿", "remind": True})

    def test_add_toggle_filter_draft_and_delete_survive_restart(self) -> None:
        fixed = datetime(2026, 9, 27, 10, 15)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "restart.sqlite3"
            repo = PlannerRepository(path, _source([]), clock=lambda: fixed)
            repo.set_filter("today")
            repo.save_draft({"title": "还没保存", "date": "2026-09-27", "time": "10:30"})
            task = repo.add_task("  新待办 ", "2026-09-27", "11:00", "high", "工作", "  备注  ", True)
            self.assertEqual(task["createdAt"], int(fixed.timestamp() * 1000))
            self.assertEqual(task["data"], {
                "title": "新待办", "time": "11:00", "priority": "high", "list": "工作",
                "note": "备注", "remind": True, "done": False,
                "estimateMinutes": 30, "plannedDate": "2026-09-27", "plannedStart": "11:00",
                "trackedSeconds": 0, "sessions": [], "repeat": "none",
                "repeatDayOfMonth": 0, "repeatSeriesId": "",
            })
            repo.toggle_task(task["id"])
            repo2 = PlannerRepository(path)
            snapshot = repo2.state("2026-09-27")
            self.assertEqual(snapshot["filter"], "today")
            self.assertEqual(snapshot["draft"]["title"], "还没保存")
            self.assertTrue(snapshot["records"][0]["data"]["done"])
            self.assertEqual(snapshot["groups"], [])
            self.assertTrue(repo2.delete_task(task["id"]))
            self.assertEqual(repo2.records(), [])

    def test_stale_repository_refreshes_and_refuses_to_overwrite_newer_database_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "concurrent.sqlite3"
            source = _source([])
            first_instance = PlannerRepository(path, source)
            second_instance = PlannerRepository(path, source)

            first_instance.add_task("第一个窗口新增", "2026-09-28")
            with self.assertRaisesRegex(PlannerRepositoryError, "另一个工作台实例更新"):
                second_instance.add_task("第二个窗口新增", "2026-09-28")

            persisted = PlannerRepository(path).records()
            self.assertEqual(
                [row["data"]["title"] for row in persisted],
                ["第一个窗口新增"],
                "a stale full-state write must not erase the committed task",
            )
            self.assertEqual(
                [row["data"]["title"] for row in second_instance.records()],
                ["第一个窗口新增"],
                "the stale repository refreshes to the committed state",
            )

            second_instance.add_task("第二个窗口重试", "2026-09-28")
            self.assertEqual(
                [row["data"]["title"] for row in PlannerRepository(path).records()],
                ["第一个窗口新增", "第二个窗口重试"],
            )

    def test_monthly_repeat_anchors_to_month_end_and_creates_next_task(self) -> None:
        fixed = datetime(2026, 1, 31, 10, 15)
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "monthly.sqlite3", _source([]), clock=lambda: fixed
            )
            task = repo.add_task("月末复盘", "2026-01-31", repeat="monthly")
            self.assertEqual(task["data"]["repeatDayOfMonth"], 31)

            repo.toggle_task(task["id"])
            records = repo.records()
            next_task = next(row for row in records if row["id"] != task["id"])
            self.assertEqual(next_task["date"], "2026-02-28")
            self.assertEqual(next_task["data"]["repeatDayOfMonth"], 31)

    def test_repeated_task_completed_from_doing_creates_todo_occurrence(self) -> None:
        fixed = datetime(2026, 9, 27, 10, 15)
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "repeat-status.sqlite3", _source([]), clock=lambda: fixed,
            )
            task = repo.add_task("每日复盘", "2026-09-27", repeat="daily")
            repo.set_task_status(task["id"], "doing")
            repo.set_task_status(task["id"], "done")

            next_task = next(row for row in repo.records() if row["id"] != task["id"])
            self.assertEqual(next_task["date"], "2026-09-28")
            self.assertFalse(next_task["data"]["done"])
            self.assertEqual(next_task["data"]["status"], "todo")
            self.assertEqual(next_task["data"]["completedAt"], "")

    def test_project_and_tags_are_normalized_and_survive_restart(self) -> None:
        fixed = datetime(2026, 9, 27, 10, 15)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "organization.sqlite3"
            repo = PlannerRepository(path, _source([]), clock=lambda: fixed)
            task = repo.add_task(
                "整理参考资料", "2026-09-27", project="  FLUKE  ",
                tags=[" 开发 ", "研究", "开发", "  "],
            )
            self.assertEqual(task["data"]["project"], "FLUKE")
            self.assertEqual(task["data"]["tags"], ["开发", "研究"])

            updated = repo.set_task_organization(task["id"], "产品迭代", ["复盘"])
            self.assertEqual(updated["data"]["project"], "产品迭代")
            self.assertEqual(updated["data"]["tags"], ["复盘"])
            snapshot = PlannerRepository(path).state("2026-09-27")
            self.assertEqual(snapshot["projects"], ["产品迭代"])
            self.assertEqual(snapshot["tags"], ["复盘"])
            self.assertEqual(snapshot["records"][0]["data"]["project"], "产品迭代")

    def test_subtasks_inherit_organization_block_parent_completion_and_delete_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "subtasks.sqlite3", _source([]))
            parent = repo.add_task(
                "准备发布", "2026-09-27", project="FLUKE", tags=["发布", "桌面"]
            )
            child = repo.add_subtask(parent["id"], "检查安装包")
            self.assertEqual(child["data"]["parentTaskId"], parent["id"])
            self.assertEqual(child["data"]["project"], "FLUKE")
            self.assertEqual(child["data"]["tags"], ["发布", "桌面"])
            with self.assertRaisesRegex(PlannerRepositoryError, "完成全部子任务"):
                repo.toggle_task(parent["id"])

            repo.toggle_task(child["id"])
            repo.toggle_task(parent["id"])
            with self.assertRaisesRegex(PlannerRepositoryError, "已完成的任务"):
                repo.add_subtask(parent["id"], "已完成后不能加")

            repo.delete_task(parent["id"])
            self.assertEqual(repo.records(), [])

    def test_filter_counts_groups_and_seven_day_strip(self) -> None:
        records = [
            _record("overdue", "2026-09-26", {"title": "逾期", "done": False}),
            _record("today", "2026-09-27", {"title": "今天", "done": False}, created_at=2),
            _record("week", "2026-10-03", {"title": "第七天", "done": False}, created_at=3),
            _record("outside", "2026-10-04", {"title": "第八天", "done": False}, created_at=4),
            _record("complete", "2026-09-27", {"title": "完成", "done": True}, created_at=5),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "filters.sqlite3", _source(records))
            snapshot = repo.state("2026-09-27")
            self.assertEqual(snapshot["metrics"], {"today": 1, "overdue": 1, "week": 2})
            self.assertEqual(len(snapshot["weekDays"]), 7)
            self.assertEqual(snapshot["weekDays"][0]["date"], "2026-09-27")
            self.assertEqual(snapshot["weekDays"][-1]["date"], "2026-10-03")
            self.assertEqual(snapshot["weekDays"][-1]["count"], 1)
            self.assertEqual([group["date"] for group in snapshot["groups"]], [
                "2026-09-26", "2026-09-27", "2026-10-03", "2026-10-04",
            ])
            repo.set_filter("scheduled")
            self.assertEqual([row["id"] for group in repo.state("2026-09-27")["groups"] for row in group["records"]], ["today", "week", "outside"])
            repo.set_filter("today")
            self.assertEqual([row["id"] for group in repo.state("2026-09-27")["groups"] for row in group["records"]], ["today"])
            repo.set_filter("done")
            self.assertEqual([row["id"] for group in repo.state("2026-09-27")["groups"] for row in group["records"]], ["complete"])

    def test_imported_delete_is_a_tombstone_and_does_not_edit_source(self) -> None:
        legacy = _record("imported", "2026-09-27", {"title": "只读原件", "done": False}, marker="untouched")
        source = _source([legacy])
        before = json.loads(json.dumps(source, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tombstone.sqlite3"
            repo = PlannerRepository(path, source)
            self.assertTrue(repo.delete_task("imported"))
            self.assertEqual(repo.records(), [])
            self.assertEqual(repo.deleted_record_keys(), [{"type": "planner", "id": "imported"}])
            repo2 = PlannerRepository(path)
            self.assertEqual(repo2.records(), [])
            self.assertEqual(repo2.deleted_record_keys(), [{"type": "planner", "id": "imported"}])
        self.assertEqual(source, before)

    def test_late_import_adoption_keeps_local_work_draft_overrides_and_tombstones(self) -> None:
        fixed = datetime(2026, 9, 27, 10, 15)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "late-import.sqlite3"
            repo = PlannerRepository(path, clock=lambda: fixed)
            local = repo.add_task("本机待办", "2026-09-27", "11:00")
            repo.toggle_task(local["id"])
            repo.set_filter("today")
            repo.save_draft({"title": "本机草稿", "date": "2026-09-28"})

            imported = _source([
                _record("legacy-1", "2026-09-27", {"title": "导入项", "done": False}),
            ], settings={"plannerFilter": "done", "importedSetting": "kept"},
                drafts={"plannerForm": {"title": "旧版草稿", "date": "2026-09-29"}})
            self.assertTrue(repo.adopt_imported_data(imported))
            adopted = repo.state("2026-09-27")
            by_id = {item["id"]: item for item in adopted["records"]}
            self.assertEqual(set(by_id), {local["id"], "legacy-1"})
            self.assertTrue(by_id[local["id"]]["data"]["done"])
            self.assertEqual(adopted["filter"], "today")
            self.assertEqual(adopted["draft"]["title"], "本机草稿")
            self.assertEqual(repo.settings()["importedSetting"], "kept")

            self.assertTrue(repo.delete_task("legacy-1"))
            self.assertTrue(repo.adopt_imported_data(imported))
            self.assertEqual({item["id"] for item in repo.records()}, {local["id"]})
            reopened = PlannerRepository(path)
            self.assertEqual({item["id"] for item in reopened.records()}, {local["id"]})
            self.assertTrue(reopened.records()[0]["data"]["done"])
            self.assertEqual(reopened.draft()["title"], "本机草稿")

        # If the runtime had no local draft choice, a later import can seed it.
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "import-draft.sqlite3")
            self.assertTrue(repo.adopt_imported_data(imported))
            self.assertEqual(repo.draft()["title"], "旧版草稿")

        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "empty-adoption.sqlite3")
            self.assertFalse(repo.adopt_imported_data({"status": "empty"}))

    def test_reminder_boundaries_and_once_only_marking(self) -> None:
        records = [
            _record("due", "2026-09-27", {"title": "到时", "time": "10:29", "note": "现在处理", "remind": True, "done": False}),
            _record("future", "2026-09-27", {"title": "未来", "time": "10:31", "remind": True, "done": False}),
            _record("blank-time", "2026-09-27", {"title": "无时间", "time": "", "remind": True, "done": False}),
            _record("bad-time", "2026-09-27", {"title": "错时间", "time": "25:00", "remind": True, "done": False}),
            _record("yesterday", "2026-09-26", {"title": "昨日", "time": "23:59", "remind": True, "done": False}),
            _record("sample", "2026-09-27", {"title": "样例", "time": "09:00", "remind": True, "done": False}, sample=True),
            _record("complete", "2026-09-27", {"title": "已完成", "time": "09:00", "remind": True, "done": True}),
            _record("no-remind", "2026-09-27", {"title": "未勾选", "time": "09:00", "remind": False, "done": False}),
            _record("already", "2026-09-27", {"title": "已提醒", "time": "09:00", "remind": True, "done": False, "remindedAt": "2026-09-27T09:01:00Z"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reminders.sqlite3"
            repo = PlannerRepository(path, _source(records), clock=lambda: datetime(2026, 9, 27, 10, 30))
            due = repo.check_due_reminders()
            self.assertEqual(due, [{"id": "due", "title": "到时", "body": "现在处理"}])
            due_record = next(item for item in repo.records() if item["id"] == "due")
            self.assertTrue(due_record["data"].get("remindedAt"))
            self.assertEqual(repo.check_due_reminders(), [])
            reopened = PlannerRepository(path, clock=lambda: datetime(2026, 9, 27, 10, 30))
            self.assertEqual(reopened.check_due_reminders(), [])

    def test_has_pending_reminders_includes_today_and_future_and_ignores_ineligible_rows(self) -> None:
        now = datetime(2026, 9, 27, 10, 30)
        eligible = [
            _record(
                "due-today",
                "2026-09-27",
                {"title": "今天尚未处理", "time": "10:00", "remind": True, "done": False},
            ),
            _record(
                "future",
                "2026-09-28",
                {"title": "未来安排", "time": "09:00", "remind": True, "done": False},
            ),
        ]
        ineligible = [
            _record(
                "expired",
                "2026-09-26",
                {"title": "过期", "time": "23:59", "remind": True, "done": False},
            ),
            _record(
                "sample",
                "2026-09-28",
                {"title": "样例", "time": "09:00", "remind": True, "done": False},
                sample=True,
            ),
            _record(
                "done",
                "2026-09-28",
                {"title": "已完成", "time": "09:00", "remind": True, "done": True},
            ),
            _record(
                "disabled",
                "2026-09-28",
                {"title": "未开启", "time": "09:00", "remind": False, "done": False},
            ),
            _record(
                "already-fired",
                "2026-09-28",
                {
                    "title": "已有回执",
                    "time": "09:00",
                    "remind": True,
                    "done": False,
                    "remindedAt": "2026-09-27T10:00:00Z",
                },
            ),
            _record(
                "invalid-time",
                "2026-09-28",
                {"title": "无效时间", "time": "25:00", "remind": True, "done": False},
            ),
            _record(
                "invalid-planned-date",
                "2026-09-28",
                {
                    "title": "无效排程日期",
                    "time": "09:00",
                    "plannedDate": "2026-02-30",
                    "plannedStart": "09:00",
                    "remind": True,
                    "done": False,
                },
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "pending-reminders.sqlite3",
                _source([*eligible, *ineligible]),
                clock=lambda: now,
            )
            self.assertTrue(repo.has_pending_reminders())
            self.assertTrue(repo.has_pending_reminders(now))

            excluded_repo = PlannerRepository(
                Path(directory) / "ineligible-reminders.sqlite3",
                _source(ineligible),
                clock=lambda: now,
            )
            self.assertFalse(excluded_repo.has_pending_reminders())

    def test_rescheduling_clears_receipt_only_for_a_changed_time_and_fires_once(self) -> None:
        now = datetime(2026, 9, 27, 10, 30)
        old_receipt = "2026-09-27T09:01:00Z"
        record = _record(
            "rescheduled",
            "2026-09-27",
            {
                "title": "调整时间",
                "time": "09:00",
                "plannedDate": "2026-09-27",
                "plannedStart": "09:00",
                "remind": True,
                "done": False,
                "remindedAt": old_receipt,
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rescheduled-reminder.sqlite3"
            repo = PlannerRepository(path, _source([record]), clock=lambda: now)

            unchanged = repo.schedule_task("rescheduled", "2026-09-27", "09:00", 35)
            self.assertIsNotNone(unchanged)
            self.assertEqual(unchanged["data"]["remindedAt"], old_receipt)

            changed = repo.schedule_task("rescheduled", "2026-09-27", "10:31", 35)
            self.assertIsNotNone(changed)
            self.assertEqual(changed["data"]["remindedAt"], "")
            self.assertTrue(repo.has_pending_reminders())
            self.assertEqual(repo.check_due_reminders(now), [])

            due = repo.check_due_reminders(now + timedelta(minutes=2))
            self.assertEqual([item["id"] for item in due], ["rescheduled"])
            self.assertEqual(repo.check_due_reminders(now + timedelta(minutes=2)), [])
            reopened = PlannerRepository(path, clock=lambda: now + timedelta(minutes=2))
            self.assertEqual(reopened.check_due_reminders(), [])

    def test_unscheduling_and_reminder_opt_in_changes_clear_receipts(self) -> None:
        now = datetime(2026, 9, 27, 10, 30)
        records = [
            _record(
                "unscheduled",
                "2026-09-27",
                {
                    "title": "取消排程",
                    "time": "09:00",
                    "plannedDate": "2026-09-27",
                    "plannedStart": "09:00",
                    "remind": True,
                    "done": False,
                    "remindedAt": "2026-09-27T09:01:00Z",
                },
            ),
            _record(
                "opt-in",
                "2026-09-27",
                {
                    "title": "重新开启提醒",
                    "time": "10:29",
                    "remind": False,
                    "done": False,
                    "remindedAt": "2026-09-27T09:01:00Z",
                },
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "changed-reminders.sqlite3",
                _source(records),
                clock=lambda: now,
            )

            unscheduled = repo.unschedule_task("unscheduled")
            self.assertIsNotNone(unscheduled)
            self.assertEqual(unscheduled["data"]["remindedAt"], "")
            self.assertEqual(unscheduled["data"]["time"], "")

            enabled = repo.set_task_reminder("opt-in", True)
            self.assertIsNotNone(enabled)
            self.assertTrue(enabled["data"]["remind"])
            self.assertEqual(enabled["data"]["remindedAt"], "")
            self.assertEqual(
                [item["id"] for item in repo.check_due_reminders(now)],
                ["opt-in"],
            )
            self.assertEqual(repo.check_due_reminders(now), [])

    def test_reopening_completed_tasks_clears_receipts_and_allows_one_new_reminder(self) -> None:
        now = datetime(2026, 9, 27, 10, 30)
        completed = [
            _record(
                "toggle-reopen",
                "2026-09-27",
                {
                    "title": "勾选撤销",
                    "time": "10:00",
                    "remind": True,
                    "done": True,
                    "status": "done",
                    "remindedAt": "2026-09-27T10:01:00Z",
                },
            ),
            _record(
                "status-reopen",
                "2026-09-27",
                {
                    "title": "看板撤销",
                    "time": "10:00",
                    "remind": True,
                    "done": True,
                    "status": "done",
                    "remindedAt": "2026-09-27T10:01:00Z",
                },
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "reopened-reminders.sqlite3",
                _source(completed),
                clock=lambda: now,
            )

            toggled = repo.toggle_task("toggle-reopen")
            statused = repo.set_task_status("status-reopen", "todo")
            self.assertIsNotNone(toggled)
            self.assertIsNotNone(statused)
            self.assertFalse(toggled["data"]["done"])
            self.assertFalse(statused["data"]["done"])
            self.assertEqual(toggled["data"]["remindedAt"], "")
            self.assertEqual(statused["data"]["remindedAt"], "")

            due = repo.check_due_reminders(now)
            self.assertEqual({item["id"] for item in due}, {"toggle-reopen", "status-reopen"})
            self.assertEqual(repo.check_due_reminders(now), [])

    def test_update_task_changes_editable_fields_and_preserves_record_metadata(self) -> None:
        fixed = datetime(2026, 9, 27, 10, 30)
        completed = _record(
            "editable-completed",
            "2026-09-27",
            {
                "title": "旧标题",
                "time": "09:00",
                "priority": "normal",
                "list": "生活",
                "note": "旧备注",
                "remind": True,
                "done": True,
                "status": "done",
                "completedAt": "2026-09-27T09:30:00",
                "remindedAt": "2026-09-27T09:01:00Z",
                "estimateMinutes": 60,
                "trackedSeconds": 900,
                "sessions": [{"sessionId": "session-a", "seconds": 900}],
                "repeat": "monthly",
                "repeatDayOfMonth": 31,
                "repeatSeriesId": "series-a",
                "externalTodo": {"provider": "caldav", "uid": "remote-a", "custom": "keep"},
                "unknownData": {"nested": [1, 2]},
            },
            created_at=17,
            remoteId="legacy-remote-a",
            customEnvelope={"keep": True},
        )
        source = _source([completed])
        source_before = json.loads(json.dumps(source, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "update-task-metadata.sqlite3"
            repo = PlannerRepository(path, source, clock=lambda: fixed)
            updated = _edit_task(
                repo,
                "editable-completed",
                title="  新标题  ",
                date="2026-09-28",
                time="11:10",
                priority="high",
                list_name="家庭",
                note="  新备注  ",
                remind=False,
                estimate_minutes=45,
                repeat="monthly",
                project="  新项目  ",
                tags=["工作", "生活", "工作"],
            )
            self.assertIsNotNone(updated)
            self.assertEqual(updated["date"], "2026-09-28")
            self.assertEqual(updated["createdAt"], 17)
            self.assertEqual(updated["remoteId"], "legacy-remote-a")
            self.assertEqual(updated["customEnvelope"], {"keep": True})
            self.assertEqual(updated["data"]["title"], "新标题")
            self.assertEqual(updated["data"]["time"], "11:10")
            self.assertEqual(updated["data"]["plannedDate"], "2026-09-28")
            self.assertEqual(updated["data"]["plannedStart"], "11:10")
            self.assertEqual(updated["data"]["priority"], "high")
            self.assertEqual(updated["data"]["list"], "家庭")
            self.assertEqual(updated["data"]["note"], "新备注")
            self.assertFalse(updated["data"]["remind"])
            self.assertEqual(updated["data"]["estimateMinutes"], 45)
            self.assertEqual(updated["data"]["project"], "新项目")
            self.assertEqual(updated["data"]["tags"], ["工作", "生活"])
            self.assertEqual(updated["data"]["repeat"], "monthly")
            self.assertEqual(updated["data"]["repeatDayOfMonth"], 28)
            self.assertEqual(updated["data"]["repeatSeriesId"], "series-a")
            self.assertEqual(updated["data"]["remindedAt"], "")
            self.assertTrue(updated["data"]["done"])
            self.assertEqual(updated["data"]["status"], "done")
            self.assertEqual(updated["data"]["completedAt"], "2026-09-27T09:30:00")
            self.assertEqual(updated["data"]["trackedSeconds"], 900)
            self.assertEqual(updated["data"]["sessions"], [{"sessionId": "session-a", "seconds": 900}])
            self.assertEqual(
                updated["data"]["externalTodo"],
                {"provider": "caldav", "uid": "remote-a", "custom": "keep"},
            )
            self.assertEqual(updated["data"]["unknownData"], {"nested": [1, 2]})
            self.assertEqual(source, source_before)
            reopened = PlannerRepository(path, clock=lambda: fixed)
            self.assertEqual(reopened.records()[0]["date"], "2026-09-28")
            self.assertEqual(reopened.records()[0]["data"]["unknownData"], {"nested": [1, 2]})

    def test_update_task_clears_receipt_only_when_date_time_or_remind_changes(self) -> None:
        old_receipt = "2026-09-27T09:01:00Z"
        def reminder_record(record_id: str) -> dict[str, object]:
            return _record(
                record_id,
                "2026-09-27",
                {
                    "title": "原待办",
                    "time": "09:00",
                    "remind": True,
                    "done": False,
                    "remindedAt": old_receipt,
                    "repeat": "monthly",
                    "repeatDayOfMonth": 31,
                    "repeatSeriesId": "series-original",
                },
            )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "update-task-reminder.sqlite3",
                _source([
                    reminder_record("editable-reminder"),
                    reminder_record("date-reminder"),
                    reminder_record("time-reminder"),
                    reminder_record("opt-in-reminder"),
                ]),
                clock=lambda: datetime(2026, 9, 27, 10, 30),
            )

            unchanged_schedule = _edit_task(
                repo,
                "editable-reminder",
                title="只改文字",
                date="2026-09-27",
                time="09:00",
                remind=True,
                priority="high",
                list_name="工作",
                note="改了备注",
                estimate_minutes=35,
                repeat="monthly",
                project="项目",
                tags=["标签"],
            )
            self.assertIsNotNone(unchanged_schedule)
            self.assertEqual(unchanged_schedule["data"]["remindedAt"], old_receipt)
            self.assertEqual(unchanged_schedule["data"]["repeatSeriesId"], "series-original")
            self.assertEqual(unchanged_schedule["data"]["repeatDayOfMonth"], 31)

            date_changed = _edit_task(
                repo,
                "date-reminder",
                date="2026-09-28",
                time="09:00",
                repeat="monthly",
            )
            self.assertIsNotNone(date_changed)
            self.assertEqual(date_changed["data"]["remindedAt"], "")
            self.assertEqual(date_changed["data"]["repeatDayOfMonth"], 28)
            self.assertEqual(date_changed["data"]["repeatSeriesId"], "series-original")

            time_changed = _edit_task(
                repo,
                "time-reminder",
                date="2026-09-27",
                time="11:00",
                repeat="monthly",
            )
            self.assertIsNotNone(time_changed)
            self.assertEqual(time_changed["data"]["remindedAt"], "")

            remind_changed = _edit_task(
                repo,
                "opt-in-reminder",
                date="2026-09-27",
                time="09:00",
                remind=False,
                repeat="monthly",
            )
            self.assertIsNotNone(remind_changed)
            self.assertEqual(remind_changed["data"]["remindedAt"], "")

    def test_update_task_rearms_changed_reminder_once_and_persists_receipt(self) -> None:
        now = datetime(2026, 9, 27, 10, 30)
        record = _record(
            "edited-reminder",
            "2026-09-27",
            {
                "title": "编辑前",
                "time": "09:00",
                "remind": True,
                "done": False,
                "remindedAt": "2026-09-27T09:01:00Z",
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "updated-once.sqlite3"
            repo = PlannerRepository(path, _source([record]), clock=lambda: now)
            updated = _edit_task(
                repo,
                "edited-reminder",
                time="10:31",
            )
            self.assertIsNotNone(updated)
            self.assertEqual(updated["data"]["remindedAt"], "")
            self.assertEqual(repo.check_due_reminders(now), [])
            due = repo.check_due_reminders(now + timedelta(minutes=2))
            self.assertEqual([item["id"] for item in due], ["edited-reminder"])
            self.assertEqual(repo.check_due_reminders(now + timedelta(minutes=2)), [])
            reopened = PlannerRepository(path, clock=lambda: now + timedelta(minutes=2))
            self.assertEqual(reopened.check_due_reminders(), [])

    def test_update_task_repeat_identity_and_completion_state_are_preserved(self) -> None:
        record = _record(
            "repeat-edit",
            "2026-01-31",
            {
                "title": "重复待办",
                "time": "09:00",
                "remind": True,
                "done": True,
                "status": "done",
                "completedAt": "2026-01-31T10:00:00",
                "repeat": "monthly",
                "repeatDayOfMonth": 31,
                "repeatSeriesId": "series-monthly",
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "repeat-edit.sqlite3",
                _source([record]),
                clock=lambda: datetime(2026, 1, 31, 10, 30),
            )

            changed_repeat = _edit_task(
                repo,
                "repeat-edit",
                date="2026-01-31",
                time="09:00",
                remind=True,
                repeat="weekly",
            )
            self.assertIsNotNone(changed_repeat)
            self.assertEqual(changed_repeat["data"]["repeat"], "weekly")
            self.assertEqual(changed_repeat["data"]["repeatDayOfMonth"], 0)
            self.assertNotEqual(changed_repeat["data"]["repeatSeriesId"], "series-monthly")
            new_series_id = changed_repeat["data"]["repeatSeriesId"]
            self.assertTrue(new_series_id)

            no_repeat = _edit_task(
                repo,
                "repeat-edit",
                date="2026-01-31",
                time="09:00",
                remind=True,
                repeat="none",
            )
            self.assertIsNotNone(no_repeat)
            self.assertEqual(no_repeat["data"]["repeat"], "none")
            self.assertEqual(no_repeat["data"]["repeatDayOfMonth"], 0)
            self.assertEqual(no_repeat["data"]["repeatSeriesId"], "")
            self.assertTrue(no_repeat["data"]["done"])
            self.assertEqual(no_repeat["data"]["completedAt"], "2026-01-31T10:00:00")

    def test_update_task_preserves_active_timer_state(self) -> None:
        fixed = datetime(2026, 9, 27, 10, 30)
        record = _record(
            "actively-tracked-edit",
            "2026-09-27",
            {
                "title": "正在计时",
                "time": "09:00",
                "remind": True,
                "done": False,
                "trackedSeconds": 240,
                "sessions": [{"sessionId": "saved-session", "seconds": 240}],
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "active-update.sqlite3",
                _source([record]),
                clock=lambda: fixed,
            )
            self.assertIsNotNone(repo.start_tracking("actively-tracked-edit"))
            active_before = json.loads(json.dumps(repo._state["activeTracking"]))

            updated = _edit_task(
                repo,
                "actively-tracked-edit",
                title="继续计时的任务",
                estimate_minutes=40,
            )
            self.assertIsNotNone(updated)
            self.assertEqual(repo._state["activeTracking"], active_before)
            self.assertEqual(updated["data"]["trackedSeconds"], 240)
            self.assertEqual(updated["data"]["sessions"], [{"sessionId": "saved-session", "seconds": 240}])

    def test_update_task_rejects_samples_cancelled_external_tasks_and_invalid_values(self) -> None:
        records = [
            _record("sample-edit", "2026-09-27", {"title": "样例", "done": False}, sample=True),
            _record(
                "cancelled-edit",
                "2026-09-27",
                {
                    "title": "已取消来源任务",
                    "externalTodo": {"provider": "caldav", "cancelled": True},
                },
            ),
            _record("valid-edit", "2026-09-27", {"title": "有效", "done": False}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "update-task-validation.sqlite3", _source(records))
            before = repo.records()
            with self.assertRaisesRegex(PlannerRepositoryError, "样例"):
                _edit_task(repo, "sample-edit")
            with self.assertRaisesRegex(PlannerRepositoryError, "来源已取消"):
                _edit_task(repo, "cancelled-edit")

            invalid_changes = [
                {"title": "  "},
                {"date": "2026-02-30"},
                {"time": "25:00"},
                {"priority": "urgent"},
                {"list_name": "其它"},
                {"note": "x" * 101},
                {"remind": 1},
                {"estimate_minutes": 0},
                {"repeat": "yearly"},
                {"project": "x" * 61},
                {"tags": "不是数组"},
            ]
            for change in invalid_changes:
                with self.subTest(change=change), self.assertRaises(PlannerRepositoryError):
                    _edit_task(repo, "valid-edit", **change)
            self.assertEqual(repo.records(), before)

    def test_invalid_form_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "invalid.sqlite3", _source([]))
            for args in [
                ("", "2026-09-27"),
                ("标题", "2026-02-30"),
                ("标题", "2026-09-27", "25:00"),
                ("标题", "2026-09-27", "", "urgent"),
                ("标题", "2026-09-27", "", "normal", "其它"),
                (" 标题 ", "2026-09-27", "", "normal", "生活", "x" * 101),
            ]:
                with self.subTest(args=args), self.assertRaises(PlannerRepositoryError):
                    repo.add_task(*args)
            self.assertEqual(repo.records(), [])

    def test_invalid_project_and_tags_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "invalid-organization.sqlite3", _source([]))
            with self.assertRaises(PlannerRepositoryError):
                repo.add_task("待办", "2026-09-27", project="x" * 61)
            with self.assertRaises(PlannerRepositoryError):
                repo.add_task("待办", "2026-09-27", tags="not a list")
            with self.assertRaises(PlannerRepositoryError):
                repo.add_task("待办", "2026-09-27", tags=["x" * 31])
            with self.assertRaises(PlannerRepositoryError):
                repo.add_task("待办", "2026-09-27", tags=[str(index) for index in range(13)])
            self.assertEqual(repo.records(), [])

    def test_view_mode_and_task_status_persist_and_guard_parent_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board.sqlite3"
            repo = PlannerRepository(path, _source([]))
            parent = repo.add_task("发布 FLUKE", "2026-09-27", priority="high")
            child = repo.add_subtask(parent["id"], "检查安装包")
            self.assertEqual(repo.state("2026-09-27")["viewMode"], "list")

            repo.set_view_mode("kanban")
            with self.assertRaisesRegex(PlannerRepositoryError, "完成全部子任务"):
                repo.set_task_status(parent["id"], "done")
            repo.set_task_status(parent["id"], "doing")
            self.assertEqual(repo._target(parent["id"])["data"]["status"], "doing")
            repo.set_task_status(child["id"], "done")
            repo.set_task_status(parent["id"], "done")

            reopened = PlannerRepository(path)
            snapshot = reopened.state("2026-09-27")
            self.assertEqual(snapshot["viewMode"], "kanban")
            rows = {row["id"]: row for row in snapshot["records"]}
            self.assertEqual(rows[parent["id"]]["data"]["status"], "done")
            self.assertTrue(rows[parent["id"]]["data"]["done"])
            with self.assertRaises(PlannerRepositoryError):
                reopened.set_view_mode("calendar")

    def test_legacy_planner_display_maps_until_native_view_override(self) -> None:
        legacy_modes = {
            "timeline": "list",
            "board": "kanban",
            "matrix": "matrix",
        }
        with tempfile.TemporaryDirectory() as directory:
            for old_mode, expected in legacy_modes.items():
                with self.subTest(old_mode=old_mode):
                    source = _source([])
                    source["richangji-state-v1"]["settings"]["plannerDisplay"] = old_mode
                    path = Path(directory) / f"legacy-{old_mode}.sqlite3"
                    repository = PlannerRepository(path, source)

                    self.assertEqual(repository.state("2026-09-27")["viewMode"], expected)
                    self.assertEqual(repository.settings()["plannerDisplay"], old_mode)
                    self.assertEqual(PlannerRepository(path).state("2026-09-27")["viewMode"], expected)

            custom_source = _source([])
            custom_source["richangji-state-v1"]["settings"].update({
                "plannerDisplay": "custom-board:legacy-board",
                "plannerCustomBoards": [{
                    "id": "legacy-board",
                    "name": "旧版自定义板",
                    "columns": [
                        {"id": "todo", "title": "待办", "status": "todo", "tag": ""},
                        {"id": "doing", "title": "进行中", "status": "inprogress", "tag": ""},
                    ],
                }],
            })
            custom_path = Path(directory) / "legacy-custom-board.sqlite3"
            custom_repository = PlannerRepository(custom_path, custom_source)
            self.assertEqual(
                custom_repository.state("2026-09-27")["viewMode"],
                "custom-board:legacy-board",
            )
            self.assertEqual(
                custom_repository.settings()["plannerCustomBoards"][0]["columns"][1]["status"],
                "doing",
            )
            self.assertEqual(
                custom_repository._state["legacySettings"]["plannerCustomBoards"][0]["columns"][1]["status"],
                "inprogress",
            )
            self.assertEqual(
                PlannerRepository(custom_path).state("2026-09-27")["viewMode"],
                "custom-board:legacy-board",
            )

            orphan_source = _source([])
            orphan_source["richangji-state-v1"]["settings"]["plannerDisplay"] = (
                "custom-board:missing-board"
            )
            orphan_path = Path(directory) / "legacy-missing-custom-board.sqlite3"
            orphan_repository = PlannerRepository(orphan_path, orphan_source)
            self.assertEqual(orphan_repository.state("2026-09-27")["viewMode"], "list")
            self.assertEqual(
                orphan_repository._state["legacySettings"]["plannerDisplay"],
                "custom-board:missing-board",
            )

            override_source = _source([])
            override_source["richangji-state-v1"]["settings"]["plannerDisplay"] = "board"
            override_path = Path(directory) / "legacy-view-override.sqlite3"
            override_repository = PlannerRepository(override_path, override_source)
            override_repository.set_view_mode("matrix")
            self.assertEqual(override_repository.state("2026-09-27")["viewMode"], "matrix")
            reopened = PlannerRepository(override_path)
            self.assertEqual(reopened.state("2026-09-27")["viewMode"], "matrix")
            self.assertEqual(reopened._state["legacySettings"]["plannerDisplay"], "board")

    def test_legacy_board_order_maps_statuses_and_appends_unlisted_tasks_stably(self) -> None:
        records = [
            _record("todo-saved-a", "2026-09-27", {"title": "已排 A", "time": "10:00", "status": "todo", "done": False}, created_at=3),
            _record("todo-saved-b", "2026-09-27", {"title": "已排 B", "time": "11:00", "status": "todo", "done": False}, created_at=2),
            _record("todo-unsaved-late", "2026-09-27", {"title": "未排较晚", "time": "12:00", "status": "todo", "done": False}, created_at=1),
            _record("todo-unsaved-early", "2026-09-27", {"title": "未排较早", "time": "09:00", "status": "todo", "done": False}, created_at=99),
            _record("doing-a", "2026-09-27", {"title": "进行中 A", "status": "doing", "done": False}, created_at=4),
            _record("doing-b", "2026-09-27", {"title": "进行中 B", "status": "inprogress", "done": False}, created_at=5),
            _record("done-a", "2026-09-27", {"title": "已完成 A", "status": "done", "done": True}, created_at=6),
            _record("done-b", "2026-09-27", {"title": "已完成 B", "status": "done", "done": True}, created_at=7),
        ]
        source = _source(records)
        legacy_order = {
            "todo": ["todo-saved-b", "todo-saved-a", "todo-saved-b"],
            "inprogress": ["doing-b", "doing-a", "doing-b"],
            "done": ["done-b"],
        }
        source["richangji-state-v1"]["settings"]["plannerBoardOrder"] = legacy_order
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-board-order.sqlite3"
            repository = PlannerRepository(path, source)
            expected = {
                "todo": ["todo-saved-b", "todo-saved-a", "todo-unsaved-early", "todo-unsaved-late"],
                "doing": ["doing-b", "doing-a"],
                "done": ["done-b", "done-a"],
            }
            self.assertEqual(repository.state("2026-09-27")["boardOrders"], expected)
            self.assertEqual(repository.state("2026-09-27")["boardOrders"], expected)
            self.assertEqual(
                repository._state["legacySettings"]["plannerBoardOrder"],
                legacy_order,
                "legacy order arrays must remain byte-for-byte represented in the base settings",
            )

            repository.set_filter("done")
            self.assertEqual(repository.state("2026-09-27")["boardOrders"], expected)
            self.assertEqual(PlannerRepository(path).state("2026-09-27")["boardOrders"], expected)

    def test_set_board_order_deduplicates_validates_and_survives_restart(self) -> None:
        records = [
            _record("todo-a", "2026-09-27", {"title": "待办 A", "status": "todo", "done": False}),
            _record("todo-b", "2026-09-27", {"title": "待办 B", "status": "todo", "done": False}),
            _record("todo-c", "2026-09-27", {"title": "待办 C", "status": "todo", "done": False}),
            _record("doing-a", "2026-09-27", {"title": "进行中", "status": "doing", "done": False}),
            _record("done-a", "2026-09-27", {"title": "完成", "status": "done", "done": True}),
        ]
        source = _source(records)
        source["richangji-state-v1"]["settings"]["plannerBoardOrder"] = {
            "todo": ["todo-a", "todo-b"],
            "inprogress": ["doing-a"],
            "done": ["done-a"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "board-order-override.sqlite3"
            repository = PlannerRepository(path, source)
            returned_order = repository.set_board_order(
                "todo", ["todo-c", "todo-a", "todo-c"]
            )
            expected = ["todo-c", "todo-a", "todo-b"]
            self.assertEqual(returned_order, expected)
            snapshot = repository.state("2026-09-27")
            self.assertEqual(snapshot["boardOrders"]["todo"], expected)
            self.assertEqual(snapshot["boardOrders"]["doing"], ["doing-a"])
            self.assertEqual(snapshot["boardOrders"]["done"], ["done-a"])
            self.assertEqual(
                repository._state["legacySettings"]["plannerBoardOrder"]["todo"],
                ["todo-a", "todo-b"],
            )

            reopened = PlannerRepository(path)
            self.assertEqual(reopened.state("2026-09-27")["boardOrders"], snapshot["boardOrders"])
            self.assertEqual(
                reopened.settings()["plannerBoardOrder"],
                {"todo": expected, "doing": ["doing-a"], "done": ["done-a"]},
            )

            with self.assertRaises(PlannerRepositoryError):
                reopened.set_board_order("inprogress", ["doing-a"])
            with self.assertRaises(PlannerRepositoryError):
                reopened.set_board_order("todo", ["todo-a", None])
            with self.assertRaises(PlannerRepositoryError):
                reopened.set_board_order("todo", ["doing-a"])
            with self.assertRaises(PlannerRepositoryError):
                reopened.set_board_order("todo", "todo-a")

    def test_new_tasks_append_after_saved_lane_order_and_remain_stable_across_filters(self) -> None:
        source = _source([
            _record("saved-b", "2026-09-27", {"title": "已排 B", "status": "todo", "done": False}, created_at=2),
            _record("saved-a", "2026-09-27", {"title": "已排 A", "status": "todo", "done": False}, created_at=1),
        ])
        source["richangji-state-v1"]["settings"]["plannerBoardOrder"] = {
            "todo": ["saved-b", "saved-a"],
            "inprogress": [],
            "done": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new-board-tasks.sqlite3"
            repository = PlannerRepository(path, source)
            first = repository.add_task("新增待办一", "2026-09-27")
            second = repository.add_task("新增待办二", "2026-09-27")
            expected = ["saved-b", "saved-a", first["id"], second["id"]]
            self.assertEqual(repository.state("2026-09-27")["boardOrders"]["todo"], expected)
            repository.set_filter("today")
            self.assertEqual(repository.state("2026-09-27")["boardOrders"]["todo"], expected)
            self.assertEqual(PlannerRepository(path).state("2026-09-27")["boardOrders"]["todo"], expected)

    def test_standard_board_move_reorders_lanes_without_losing_filtered_tasks(self) -> None:
        source = _source([
            _record("hidden-early", "2026-09-26", {
                "title": "隐藏较早", "status": "todo", "done": False, "project": "Hidden",
            }),
            _record("visible-a", "2026-09-27", {
                "title": "可见 A", "status": "todo", "done": False, "project": "Visible",
            }),
            _record("hidden-middle", "2026-09-28", {
                "title": "隐藏中间", "status": "todo", "done": False, "project": "Hidden",
            }),
            _record("visible-b", "2026-09-27", {
                "title": "可见 B", "status": "todo", "done": False, "project": "Visible",
            }),
            _record("moving", "2026-09-27", {
                "title": "拖动项", "status": "todo", "done": False, "project": "Visible",
            }),
            _record("doing-a", "2026-09-27", {
                "title": "进行中", "status": "doing", "done": False, "project": "Visible",
            }),
            _record("done-a", "2026-09-27", {
                "title": "完成", "status": "done", "done": True, "project": "Visible",
            }),
        ])
        source["richangji-state-v1"]["settings"]["plannerBoardOrder"] = {
            "todo": ["hidden-early", "visible-a", "hidden-middle", "visible-b", "moving"],
            "inprogress": ["doing-a"],
            "done": ["done-a"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "standard-board-move.sqlite3"
            repository = PlannerRepository(path, source)
            repository.set_task_filters(project="Visible")
            before = repository.state("2026-09-27")
            visible_ids = {
                row["id"]
                for group in before["groups"]
                for row in group["records"]
            }
            self.assertNotIn("hidden-middle", visible_ids)

            moved = repository.move_task_on_standard_board("moving", "todo", "visible-b")
            expected_todo = [
                "hidden-early", "visible-a", "hidden-middle", "moving", "visible-b",
            ]
            self.assertEqual(moved["task"]["id"], "moving")
            self.assertEqual(moved["boardOrders"]["todo"], expected_todo)
            self.assertEqual(repository.state("2026-09-27")["boardOrders"]["todo"], expected_todo)

            moved = repository.move_task_on_standard_board("visible-a", "doing", "doing-a")
            self.assertEqual(moved["task"]["data"]["status"], "doing")
            self.assertFalse(moved["task"]["data"]["done"])
            self.assertEqual(
                moved["boardOrders"],
                {
                    "todo": ["hidden-early", "hidden-middle", "moving", "visible-b"],
                    "doing": ["visible-a", "doing-a"],
                    "done": ["done-a"],
                },
            )
            reopened = PlannerRepository(path)
            self.assertEqual(reopened.settings()["plannerProjectFilter"], "Visible")
            self.assertEqual(reopened.state("2026-09-27")["boardOrders"], moved["boardOrders"])

            with self.assertRaisesRegex(PlannerRepositoryError, "排序目标已离开此列"):
                reopened.move_task_on_standard_board("moving", "todo", "doing-a")

    def test_standard_board_move_updates_repeat_completion_and_reminder_receipts(self) -> None:
        fixed = datetime(2026, 9, 27, 10, 15)
        source = _source([
            _record("repeat", "2026-09-27", {
                "title": "每日复盘", "status": "doing", "done": False,
                "repeat": "daily", "repeatSeriesId": "daily-series",
            }),
            _record("reopen", "2026-09-27", {
                "title": "重新打开", "status": "done", "done": True,
                "remind": True, "remindedAt": "2026-09-27T09:00:00Z",
                "completedAt": "2026-09-27T09:30:00",
            }),
        ])
        source["richangji-state-v1"]["settings"]["plannerBoardOrder"] = {
            "todo": [], "inprogress": ["repeat"], "done": ["reopen"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "standard-board-side-effects.sqlite3"
            repository = PlannerRepository(path, source, clock=lambda: fixed)

            completed = repository.move_task_on_standard_board("repeat", "done")
            self.assertEqual(completed["task"]["data"]["status"], "done")
            self.assertEqual(completed["task"]["data"]["completedAt"], "2026-09-27T10:15:00")
            next_occurrence = next(row for row in repository.records() if row["id"] != "repeat" and row["id"] != "reopen")
            self.assertEqual(next_occurrence["date"], "2026-09-28")
            self.assertFalse(next_occurrence["data"]["done"])
            self.assertEqual(completed["boardOrders"]["todo"], [next_occurrence["id"]])
            self.assertEqual(completed["boardOrders"]["doing"], [])
            self.assertEqual(completed["boardOrders"]["done"], ["reopen", "repeat"])

            reopened_task = repository.move_task_on_standard_board("reopen", "todo")
            self.assertEqual(reopened_task["task"]["data"]["remindedAt"], "")
            self.assertEqual(reopened_task["task"]["data"]["completedAt"], "")
            expected = {
                "todo": [next_occurrence["id"], "reopen"],
                "doing": [],
                "done": ["repeat"],
            }
            self.assertEqual(reopened_task["boardOrders"], expected)
            self.assertEqual(PlannerRepository(path).state("2026-09-27")["boardOrders"], expected)

    def test_standard_board_move_keeps_status_transition_guards(self) -> None:
        source = _source([
            _record("cancelled", "2026-09-27", {
                "title": "来源已取消", "status": "todo", "done": False,
                "externalTodo": {"cancelled": True},
            }),
            _record("tracked", "2026-09-27", {
                "title": "计时中", "status": "todo", "done": False,
            }),
            _record("parent", "2026-09-27", {
                "title": "有子任务", "status": "todo", "done": False,
            }),
        ])
        with tempfile.TemporaryDirectory() as directory:
            repository = PlannerRepository(
                Path(directory) / "standard-board-guards.sqlite3",
                source,
                clock=lambda: datetime(2026, 9, 27, 10, 15),
            )
            child = repository.add_subtask("parent", "还没完成")
            self.assertIsNotNone(child)
            reordered_cancelled = repository.move_task_on_standard_board("cancelled", "todo")
            self.assertEqual(reordered_cancelled["task"]["data"]["status"], "todo")
            with self.assertRaisesRegex(PlannerRepositoryError, "来源已取消"):
                repository.move_task_on_standard_board("cancelled", "doing")

            repository.start_tracking("tracked")
            with self.assertRaisesRegex(PlannerRepositoryError, "结束这项任务的计时"):
                repository.move_task_on_standard_board("tracked", "todo")
            with self.assertRaisesRegex(PlannerRepositoryError, "完成全部子任务"):
                repository.move_task_on_standard_board("parent", "done")
            self.assertFalse(repository._target("parent")["data"]["done"])
            self.assertEqual(repository._target("tracked")["data"]["status"], "todo")

    def test_custom_boards_filter_tags_move_tasks_and_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom-board.sqlite3"
            repo = PlannerRepository(path, _source([]))
            task = repo.add_task(
                "准备发布检查", "2026-09-27", project="FLUKE", tags=["本机"]
            )
            board = repo.save_custom_board({
                "name": "发布流程",
                "columns": [
                    {"title": "待复核", "status": "doing", "tag": "复核"},
                    {"title": "已发布", "status": "done", "tag": ""},
                ],
            })
            self.assertTrue(board["id"])
            self.assertEqual(len(board["columns"]), 2)
            repo.set_view_mode("custom-board:" + board["id"])
            self.assertEqual(repo.state("2026-09-27")["viewMode"], "custom-board:" + board["id"])

            moved = repo.move_task_to_custom_board_column(task["id"], "doing", "复核")
            self.assertEqual(moved["data"]["status"], "doing")
            self.assertEqual(moved["data"]["tags"], ["本机", "复核"])
            self.assertEqual(moved["data"]["project"], "FLUKE")

            crowded = repo.add_task(
                "标签上限保护", "2026-09-27", tags=[f"tag-{index}" for index in range(12)]
            )
            with self.assertRaises(PlannerRepositoryError):
                repo.move_task_to_custom_board_column(crowded["id"], "doing", "新增标签")
            unchanged = repo._target(crowded["id"])["data"]
            self.assertFalse(unchanged["done"])
            self.assertEqual(len(unchanged["tags"]), 12)

            reopened = PlannerRepository(path)
            self.assertEqual(reopened.state("2026-09-27")["customBoards"], [board])
            self.assertEqual(reopened.state("2026-09-27")["viewMode"], "custom-board:" + board["id"])
            self.assertTrue(reopened.delete_custom_board(board["id"]))
            self.assertEqual(reopened.state("2026-09-27")["viewMode"], "kanban")
            self.assertIsNotNone(reopened._target(task["id"]))

    def test_custom_board_lane_order_moves_to_bottom_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom-board-order.sqlite3"
            repo = PlannerRepository(path, _source([]))
            first = repo.add_task("任务 A", "2026-09-27")
            second = repo.add_task("任务 B", "2026-09-27")
            third = repo.add_task("任务 C", "2026-09-27")
            board = repo.save_custom_board({
                "name": "有序看板",
                "columns": [
                    {"title": "待办", "status": "todo", "tag": ""},
                    {"title": "完成", "status": "done", "tag": ""},
                ],
            })
            column = board["columns"][0]
            repo.set_view_mode("custom-board:" + board["id"])
            repo.move_task_to_custom_board_column(
                first["id"], "todo", "", board["id"], column["id"], first["id"]
            )
            self.assertEqual(
                repo.state("2026-09-27")["customBoardOrders"][board["id"]][column["id"]],
                [first["id"], second["id"], third["id"]],
            )

            repo.move_task_to_custom_board_column(
                first["id"], "todo", "", board["id"], column["id"]
            )
            repo.move_task_to_custom_board_column(
                second["id"], "todo", "", board["id"], column["id"]
            )
            expected_order = [third["id"], first["id"], second["id"]]
            self.assertEqual(
                repo.state("2026-09-27")["customBoardOrders"][board["id"]][column["id"]],
                expected_order,
            )
            repo.move_task_to_custom_board_column(
                first["id"], "todo", "", board["id"], column["id"], first["id"]
            )
            self.assertEqual(
                repo.state("2026-09-27")["customBoardOrders"][board["id"]][column["id"]],
                expected_order,
            )
            finished = repo.add_task("已完成任务", "2026-09-27")
            repo.set_task_status(finished["id"], "done")
            completed_at = repo._target(finished["id"])["data"]["completedAt"]
            completed_column = board["columns"][1]
            repo.move_task_to_custom_board_column(
                finished["id"], "done", "", board["id"], completed_column["id"]
            )
            self.assertEqual(repo._target(finished["id"])["data"]["completedAt"], completed_at)

            reopened = PlannerRepository(path)
            snapshot = reopened.state("2026-09-27")
            self.assertEqual(
                snapshot["customBoardOrders"][board["id"]][column["id"]],
                expected_order,
            )
            self.assertTrue(reopened.delete_custom_board(board["id"]))
            self.assertNotIn(board["id"], reopened.state("2026-09-27")["customBoardOrders"])

    def test_project_and_tag_filters_are_combined_and_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "organization-filters.sqlite3"
            repo = PlannerRepository(path, _source([]))
            first = repo.add_task(
                "项目 A 待办", "2026-09-27", project="项目 A", tags=["发布", "桌面"],
            )
            repo.add_task("项目 A 其他标签", "2026-09-27", project="项目 A", tags=["研究"])
            repo.add_task("项目 B 待办", "2026-09-27", project="项目 B", tags=["发布"])

            repo.set_task_filters(" 项目 A ", "发布")
            snapshot = repo.state("2026-09-27")
            filtered_ids = {
                row["id"]
                for group in snapshot["groups"]
                for row in group["records"]
            }
            self.assertEqual(filtered_ids, {first["id"]})
            self.assertEqual(snapshot["projectFilter"], "项目 A")
            self.assertEqual(snapshot["tagFilter"], "发布")

            reopened = PlannerRepository(path)
            self.assertEqual(reopened.state("2026-09-27")["projectFilter"], "项目 A")
            self.assertEqual(reopened.state("2026-09-27")["tagFilter"], "发布")
            reopened.set_task_filters("", "")
            self.assertEqual(sum(len(group["records"]) for group in reopened.state("2026-09-27")["groups"]), 3)

    def test_focus_modes_track_elapsed_time_and_validate_countdown(self) -> None:
        now = [datetime(2026, 9, 27, 10, 0)]
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "focus-modes.sqlite3", _source([]), clock=lambda: now[0]
            )
            task = repo.add_task("准备报告", "2026-09-27")
            with self.assertRaisesRegex(PlannerRepositoryError, "计时模式无效"):
                repo.start_focus_tracking(task["id"], "unknown")
            with self.assertRaisesRegex(PlannerRepositoryError, "5 至 480 分钟"):
                repo.start_focus_tracking(task["id"], "countdown", 4)

            repo.start_focus_tracking(task["id"], "pomodoro")
            now[0] += timedelta(minutes=7, seconds=30)
            active = repo.state("2026-09-27")["activeTracking"]
            self.assertEqual(active["mode"], "pomodoro")
            self.assertEqual(active["elapsedSeconds"], 450)
            self.assertEqual(active["remainingSeconds"], 1050)

    def test_focus_pause_resume_survives_restart_without_counting_closed_time(self) -> None:
        now = [datetime(2026, 9, 27, 10, 0)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "focus-recovery.sqlite3"
            repo = PlannerRepository(path, _source([]), clock=lambda: now[0])
            task = repo.add_task("撰写提案", "2026-09-27")
            repo.start_focus_tracking(task["id"], "countdown", 20)
            now[0] += timedelta(minutes=3)
            self.assertTrue(repo.pause_tracking())
            now[0] += timedelta(hours=2)
            paused = repo.state("2026-09-27")["activeTracking"]
            self.assertTrue(paused["paused"])
            self.assertEqual(paused["elapsedSeconds"], 180)
            self.assertEqual(paused["remainingSeconds"], 1020)

            self.assertTrue(repo.resume_tracking())
            now[0] += timedelta(minutes=2)
            repo.checkpoint_tracking()
            now[0] += timedelta(hours=1)
            reopened = PlannerRepository(path, clock=lambda: now[0])
            recovered = reopened.state("2026-09-27")["activeTracking"]
            self.assertTrue(recovered["paused"])
            self.assertEqual(recovered["elapsedSeconds"], 300)
            self.assertEqual(recovered["remainingSeconds"], 900)
            self.assertTrue(reopened.resume_tracking())

    def test_focus_timer_completion_saves_one_capped_session(self) -> None:
        now = [datetime(2026, 9, 27, 10, 0)]
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "focus-completion.sqlite3", _source([]), clock=lambda: now[0]
            )
            task = repo.add_task("专注完成", "2026-09-27")
            repo.start_focus_tracking(task["id"], "pomodoro")
            now[0] += timedelta(minutes=27)
            self.assertEqual(repo.complete_tracking_if_due(), "pomodoro")
            saved = repo._target(task["id"])["data"]
            self.assertEqual(saved["trackedSeconds"], 25 * 60)
            self.assertEqual(len(saved["sessions"]), 1)
            self.assertEqual(saved["sessions"][0]["seconds"], 25 * 60)
            self.assertEqual(repo.state("2026-09-27")["activeTracking"], {})

    def test_pause_segments_are_saved_once_and_add_up_to_task_total(self) -> None:
        now = [datetime(2026, 9, 27, 10, 0)]
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "focus-segments.sqlite3", _source([]), clock=lambda: now[0]
            )
            task = repo.add_task("分段专注", "2026-09-27")
            repo.start_focus_tracking(task["id"], "flowtime")
            now[0] += timedelta(minutes=12)
            repo.pause_tracking()
            self.assertEqual(repo._target(task["id"])["data"]["trackedSeconds"], 12 * 60)
            now[0] += timedelta(hours=2)
            repo.resume_tracking()
            now[0] += timedelta(minutes=8)
            repo.stop_tracking()

            data = repo._target(task["id"])["data"]
            self.assertEqual(data["trackedSeconds"], 20 * 60)
            self.assertEqual([row["seconds"] for row in data["sessions"]], [12 * 60, 8 * 60])
            self.assertEqual(sum(row["seconds"] for row in data["sessions"]), data["trackedSeconds"])

    def test_timesheet_splits_midnight_and_csv_matches_daily_totals(self) -> None:
        local_timezone = datetime.now().astimezone().tzinfo
        now = [datetime(2026, 9, 27, 23, 50, tzinfo=local_timezone)]
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(
                Path(directory) / "timesheet.sqlite3", _source([]), clock=lambda: now[0]
            )
            task = repo.add_task(
                "=SUM(1,2)", "2026-09-27", estimate_minutes=60,
                project="FLUKE", tags=["focus", "calendar"],
            )
            repo.start_tracking(task["id"])
            now[0] += timedelta(minutes=20)
            repo.stop_tracking()

            report = repo.timesheet("2026-09-27", "2026-09-28")
            self.assertEqual([row["actualSeconds"] for row in report["days"]], [600, 600])
            self.assertEqual(report["totals"]["actualSeconds"], 1200)
            self.assertEqual(report["totals"]["estimatedSeconds"], 3600)
            self.assertEqual(report["totals"]["varianceSeconds"], -2400)
            self.assertEqual(report["projects"][0]["name"], "FLUKE")
            self.assertEqual({row["name"] for row in report["tags"]}, {"focus", "calendar"})

            target = Path(directory) / "timesheet.csv"
            exported = repo.export_timesheet_csv(target, "2026-09-27", "2026-09-28")
            self.assertEqual(exported, target.resolve())
            with target.open(encoding="utf-8-sig", newline="") as stream:
                csv_rows = list(csv.reader(stream))
            self.assertEqual(len(csv_rows), 3)
            self.assertEqual(sum(int(row[-1]) for row in csv_rows[1:]), 1200)
            self.assertEqual(csv_rows[1][1], "'=SUM(1,2)")

    def test_timesheet_rejects_invalid_and_overlong_periods(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = PlannerRepository(Path(directory) / "timesheet-range.sqlite3", _source([]))
            with self.assertRaisesRegex(PlannerRepositoryError, "晚于结束日期"):
                repo.timesheet("2026-09-28", "2026-09-27")
            with self.assertRaisesRegex(PlannerRepositoryError, "连续 366 天"):
                repo.timesheet("2025-01-01", "2026-01-02")

    def test_failed_sqlite_write_rolls_back_memory_and_persisted_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollback.sqlite3"
            repo = PlannerRepository(path, _source([]))
            connection = sqlite3.connect(path)
            try:
                before_row = connection.execute(
                    "SELECT state_json FROM planner_module_state WHERE singleton=1"
                ).fetchone()[0]
                connection.execute(
                    "CREATE TRIGGER fail_planner_update BEFORE UPDATE ON planner_module_state "
                    "BEGIN SELECT RAISE(ABORT, 'forced planner failure'); END"
                )
            finally:
                connection.close()
            with self.assertRaises(PlannerRepositoryError):
                repo.set_filter("today")
            self.assertEqual(repo.settings()["plannerFilter"], "all")
            self.assertEqual(PlannerRepository(path).settings()["plannerFilter"], "all")
            connection = sqlite3.connect(path)
            try:
                after_row = connection.execute(
                    "SELECT state_json FROM planner_module_state WHERE singleton=1"
                ).fetchone()[0]
                connection.execute("DROP TRIGGER fail_planner_update")
            finally:
                connection.close()
            self.assertEqual(after_row, before_row)
            repo.set_filter("today")
            self.assertEqual(repo.settings()["plannerFilter"], "today")


if __name__ == "__main__":
    unittest.main()
