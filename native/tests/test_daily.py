from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wanxiang.daily import (
    DailyRepository,
    DailyRepositoryError,
    FocusTimer,
    SPOTIFY_MIGRATION_DECISION,
)
from wanxiang.database import import_package
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _package(main_state: dict[str, object] | None = None,
             questions: list[object] | None = None):
    raw: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    if main_state is not None:
        raw["richangji-state-v1"] = json.dumps(
            main_state, ensure_ascii=False, separators=(",", ":")
        )
    if questions is not None:
        raw["wanxiang-issue-questions-v1"] = json.dumps(
            questions, ensure_ascii=False, separators=(",", ":")
        )
    payload = {
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-daily-tests",
        "exportedAt": "2026-09-27T10:00:00Z",
        "keys": raw,
        "checksum": calculate_checksum(raw),
    }
    return validate_package(payload), raw


def _main_state(*, records: list[dict[str, object]] | None = None,
                habits: list[dict[str, object]] | None = None,
                media: list[dict[str, object]] | None = None,
                settings: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "version": 2,
        "records": records or [],
        "habits": habits or [],
        "mediaItems": media or [],
        "settings": settings or {},
    }


class DailyRepositoryTests(unittest.TestCase):
    def test_legacy_focus_timer_and_sessions_are_adopted_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "focus-import.sqlite3"
            now = datetime(2026, 9, 27, 10, 0, 0).astimezone()
            legacy = {
                "richangji-state-v1": _main_state(settings={
                    "flowTimer": {
                        "mode": "countdown",
                        "durationSeconds": 75 * 60,
                        "remainingSeconds": 31 * 60,
                        "elapsedSeconds": 44 * 60,
                        "running": True,
                        "checkpointAt": int((now - timedelta(seconds=20)).timestamp() * 1000),
                        "sessionId": "legacy-session",
                        "taskId": "legacy-task",
                        "taskTitle": "旧版任务",
                    },
                    "focusSessions": [
                        {"id": "legacy-row", "date": "2026-09-26", "seconds": 120,
                         "mode": "flowtime", "taskTitle": "独立旧专注"},
                        {"date": "bad-date", "seconds": 10},
                        {"date": "2026-09-26", "seconds": 0},
                    ],
                }),
            }
            package, raw = _package(legacy["richangji-state-v1"])
            import_package(package, db)
            repository = DailyRepository(db, clock=lambda: now)
            timer = repository.focus_timer()
            self.assertEqual(timer["mode"], "countdown")
            self.assertEqual(timer["durationSeconds"], 75 * 60)
            self.assertEqual(timer["remainingSeconds"], 31 * 60)
            self.assertEqual(timer["elapsedSeconds"], 44 * 60)
            self.assertTrue(timer["running"])
            self.assertEqual(timer["taskId"], "legacy-task")
            self.assertEqual([row["id"] for row in repository.state()["focusSessions"]], ["legacy-row"])

            hostile = {
                "richangji-state-v1": _main_state(settings={
                    "flowTimer": {
                        "mode": [], "durationSeconds": 10 ** 1000,
                        "remainingSeconds": float("nan"), "elapsedSeconds": -5,
                        "running": True, "checkpointAt": None,
                        "sessionId": [], "taskId": {}, "taskTitle": 7,
                    },
                    "focusSessions": [
                        {"id": [], "date": "2026-09-26", "seconds": 12,
                         "mode": [], "taskTitle": None},
                    ],
                }),
            }
            repository.adopt_imported_data(hostile)
            sanitized = repository.focus_timer()
            self.assertEqual(sanitized["mode"], "pomodoro")
            self.assertEqual(sanitized["durationSeconds"], 1500)
            self.assertEqual(sanitized["remainingSeconds"], 1500)
            self.assertFalse(sanitized["running"])
            self.assertEqual(sanitized["sessionId"], "")
            self.assertEqual(repository.state()["focusSessions"][0]["mode"], "pomodoro")
            with closing(sqlite3.connect(db)) as connection:
                stored_raw = connection.execute(
                    "SELECT raw_value FROM legacy_storage WHERE storage_key='richangji-state-v1'"
                ).fetchone()[0]
            self.assertEqual(stored_raw, raw["richangji-state-v1"])

    def test_flowtime_checkpoints_split_local_midnight_and_enter_yesterday_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "focus-midnight.sqlite3"
            now = [datetime(2026, 9, 26, 23, 59, 50).astimezone()]
            repository = DailyRepository(db, clock=lambda: now[0])
            repository.configure_focus("flowtime", now=now[0])
            repository.toggle_focus("", "跨日独立专注", now=now[0])
            now[0] += timedelta(seconds=25)
            worked, completed = repository.checkpoint_focus(now=now[0])
            self.assertEqual((worked, completed), (25, False))
            timer = repository.focus_timer()
            self.assertEqual(timer["elapsedSeconds"], 25)
            self.assertEqual(timer["mode"], "flowtime")
            sessions = repository.state()["focusSessions"]
            self.assertEqual([(row["date"], row["seconds"]) for row in sessions], [
                ("2026-09-26", 10), ("2026-09-27", 15),
            ])
            yesterday_item = repository.yesterday_review("2026-09-28")["items"][0]
            self.assertEqual(yesterday_item["kind"], "专注")
            self.assertEqual(yesterday_item["title"], "跨日独立专注")
            self.assertEqual(yesterday_item["detail"], "15秒 · Flowtime")

    def test_planner_linked_focus_sessions_enter_yesterday_review_with_day_split(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = DailyRepository(Path(directory) / "planner-review.sqlite3")
            repository.update_activity_snapshot(records=[{
                "id": "linked-task",
                "type": "planner",
                "date": "2026-09-26",
                "sample": False,
                "data": {
                    "title": "跨日关联待办",
                    "sessions": [{
                        "sessionId": "linked-session",
                        "startedAt": "2026-09-26T23:59:30+08:00",
                        "endedAt": "2026-09-27T00:01:30+08:00",
                        "seconds": 120,
                        "mode": "countdown",
                    }],
                },
            }])
            review = repository.yesterday_review("2026-09-28")
            linked = [item for item in review["items"] if item["kind"] == "专注"]
            self.assertEqual(len(linked), 1)
            self.assertEqual(linked[0]["title"], "跨日关联待办")
            self.assertEqual(linked[0]["detail"], "1分钟30秒 · 倒计时")

    def test_user_focus_runtime_wins_over_later_imports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "focus-late-import.sqlite3"
            now = [datetime(2026, 9, 27, 12, 0, 0).astimezone()]
            first = {"richangji-state-v1": _main_state(settings={
                "flowTimer": {"mode": "pomodoro", "durationSeconds": 1500,
                              "remainingSeconds": 900, "elapsedSeconds": 600},
                "focusSessions": [{"id": "old", "date": "2026-09-26", "seconds": 60}],
            })}
            repository = DailyRepository(db, first, clock=lambda: now[0])
            repository.configure_focus("countdown", 45, now=now[0])
            repository.toggle_focus("", "本地任务", now=now[0])
            now[0] += timedelta(seconds=30)
            repository.checkpoint_focus(now=now[0])
            preserved = repository.state()
            later = {"richangji-state-v1": _main_state(settings={
                "flowTimer": {"mode": "flowtime", "durationSeconds": 0,
                              "remainingSeconds": 0, "elapsedSeconds": 0},
                "focusSessions": [{"id": "new-import", "date": "2026-09-26", "seconds": 999}],
            })}
            repository.adopt_imported_data(later)
            self.assertEqual(repository.focus_timer()["mode"], "countdown")
            self.assertEqual(repository.focus_timer()["elapsedSeconds"], 30)
            self.assertEqual(repository.state()["focusSessions"], preserved["focusSessions"])
            reopened = DailyRepository(db, later, clock=lambda: now[0])
            self.assertEqual(reopened.focus_timer()["mode"], "countdown")
            self.assertEqual(reopened.focus_timer()["taskTitle"], "本地任务")
            self.assertEqual(reopened.state()["focusSessions"], preserved["focusSessions"])

    def test_imported_daily_fields_and_question_rows_persist_without_touching_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "synthetic.sqlite3"
            state = _main_state(settings={
                "dailyFlowNotes": {"2026-09-26": "合成跟进线索"},
                "dailyFlowFocusTask": "整理合成资料",
                "dailyFlowAudioUrl": "https://open.spotify.com/playlist/0123456789?si=synthetic",
            })
            questions = ["旧式问题", {"text": "已带日期的问题", "createdDate": "2026-09-25",
                                        "createdAt": 100, "futureField": {"keep": True}}]
            package, raw = _package(state, questions)
            import_package(package, db)

            repository = DailyRepository(db)
            self.assertEqual(repository.follow_up_for("2026-09-26"), "合成跟进线索")
            self.assertEqual(repository.focus_task(), "整理合成资料")
            self.assertIn("?si=synthetic", repository.spotify_url())
            self.assertEqual(repository.questions(), questions)
            self.assertEqual(repository.state()["spotifyMigrationDecision"],
                             SPOTIFY_MIGRATION_DECISION)

            repository.save_follow_up("2026-09-27", "本地新增合成线索")
            repository.save_focus_task("写合成总结")
            reopened = DailyRepository(db)
            self.assertEqual(reopened.follow_up_for("2026-09-27"), "本地新增合成线索")
            self.assertEqual(reopened.focus_task(), "写合成总结")
            with closing(sqlite3.connect(db)) as connection:
                stored = dict(connection.execute(
                    "SELECT storage_key, raw_value FROM legacy_storage"
                ).fetchall())
            self.assertEqual(stored["richangji-state-v1"], raw["richangji-state-v1"])
            self.assertEqual(stored["wanxiang-issue-questions-v1"],
                             raw["wanxiang-issue-questions-v1"])

    def test_yesterday_review_matches_old_record_habit_and_media_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            yesterday = "2026-09-26"
            records = [
                {"id": "money", "type": "money", "date": yesterday, "createdAt": 20,
                 "sample": False, "data": {"note": "合成午餐", "category": "餐饮",
                                           "flow": "expense", "amount": 12.5}},
                {"id": "planner", "type": "planner", "date": yesterday, "createdAt": 10,
                 "sample": False, "data": {"title": "合成整理", "list": "工作",
                                           "time": "15:00", "done": True}},
                {"id": "sample", "type": "fitness", "date": yesterday, "createdAt": 99,
                 "sample": True, "data": {"weight": 60}},
                {"id": "other-day", "type": "home", "date": "2026-09-25", "createdAt": 99,
                 "sample": False, "data": {"name": "别日物品"}},
            ]
            habits = [
                {"id": "water", "name": "合成饮水", "createdDate": "2026-09-20",
                 "target": 8, "unit": "杯", "entries": {yesterday: 4}},
                {"id": "sleep", "name": "合成睡眠", "createdDate": yesterday,
                 "target": 7, "unit": "小时", "entries": {yesterday: 7}},
                {"id": "future", "name": "明日习惯", "createdDate": "2026-09-27",
                 "entries": {}},
                {"id": "sample-habit", "name": "样本习惯", "sample": True,
                 "createdDate": "2026-09-20", "entries": {}},
            ]
            media = [
                {"name": "合成书目", "date": yesterday, "status": "看完", "sample": False},
                {"name": "样本影片", "date": yesterday, "sample": True},
            ]
            package, _ = _package(_main_state(records=records, habits=habits, media=media))
            repository = DailyRepository(Path(directory) / "daily.sqlite3", package)

            review = repository.yesterday_review("2026-09-27")
            self.assertEqual(review["date"], yesterday)
            self.assertEqual(review["count"], 5)
            self.assertEqual([item["kind"] for item in review["items"]],
                             ["财务", "日程", "习惯", "习惯", "影音"])
            self.assertEqual(review["items"][0]["title"], "合成午餐")
            self.assertIn("-¥12.5", review["items"][0]["detail"])
            self.assertEqual(review["items"][1]["detail"],
                             "工作 · 15:00 · 已完成 · 15:00")
            self.assertEqual(review["items"][2]["detail"], "昨日进度 · 4/8杯")
            self.assertEqual(review["items"][3]["detail"], "昨日完成 · 7小时")

    def test_review_keeps_media_and_uses_today_specific_saved_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package, _ = _package(_main_state(media=[
                {"name": "合成播客", "date": "2026-09-26", "sample": False},
            ], settings={"dailyFlowNotes": {"2026-09-26": "昨天跟进"}}))
            repository = DailyRepository(Path(directory) / "daily.sqlite3", package)
            review = repository.yesterday_review("2026-09-27")
            self.assertEqual(review["items"], [{
                "kind": "影音", "title": "合成播客", "detail": "已记录", "time": 0,
            }])
            self.assertEqual(review["followUp"], "昨天跟进")
            self.assertEqual(repository.yesterday_review("2026-09-28")["followUp"], "")

    def test_today_work_counts_all_tasks_shows_first_four_and_filters_focus_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tasks = [
                {"id": str(index), "type": "planner", "date": "2026-09-27",
                 "createdAt": index, "sample": index == 5,
                 "data": {"title": f"合成任务 {index}", "done": index == 3,
                          "time": "10:00"}}
                for index in range(1, 6)
            ]
            tasks.extend([
                {"id": "old", "type": "planner", "date": "2026-09-26", "createdAt": 99,
                 "data": {"title": "昨日任务"}},
                {"id": "money", "type": "money", "date": "2026-09-27", "createdAt": 99,
                 "data": {"note": "非待办"}},
            ])
            package, _ = _package(_main_state(records=tasks))
            repository = DailyRepository(Path(directory) / "daily.sqlite3", package)
            work = repository.today_work("2026-09-27")
            self.assertEqual(work["taskCount"], 5)
            self.assertEqual(len(work["tasks"]), 4)
            self.assertEqual(work["tasks"][0]["title"], "合成任务 5")
            self.assertEqual([row["id"] for row in work["focusCandidates"]], ["4", "2", "1"])
            self.assertEqual(work["mailIntegration"], "shortcut_only")
            self.assertEqual(work["focusTask"], "")

    def test_questions_add_delete_limit_and_keep_legacy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            old = ["未记录日期的旧问题", {"text": "有日期", "createdDate": "2026-09-25",
                                         "futureField": "保留"}]
            package, _ = _package(questions=old)
            db = Path(directory) / "daily.sqlite3"
            repository = DailyRepository(db, package)
            self.assertEqual(repository.questions(), old)
            when = datetime(2026, 9, 27, 9, 30)
            created = repository.add_question("  合成新问题  ", now=when)
            self.assertEqual(created["text"], "合成新问题")
            self.assertEqual(created["createdDate"], "2026-09-27")
            self.assertEqual(repository.questions()[0], created)
            repository.remove_question(1)
            self.assertEqual(repository.questions()[1], {"text": "有日期",
                                                         "createdDate": "2026-09-25",
                                                         "futureField": "保留"})

            for index in range(14):
                repository.add_question(f"新问题 {index}", now=when)
            self.assertEqual(len(repository.questions()), 12)
            self.assertEqual(repository.questions()[0]["text"], "新问题 13")
            self.assertEqual(len(DailyRepository(db).questions()), 12)

    def test_follow_up_and_focus_limits_clear_and_day_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = DailyRepository(Path(directory) / "daily.sqlite3")
            self.assertEqual(repository.save_follow_up("2026-09-27", "  合成线索  "), "合成线索")
            self.assertEqual(repository.follow_up_for("2026-09-27"), "合成线索")
            self.assertEqual(repository.follow_up_for("2026-09-28"), "")
            repository.save_follow_up("2026-09-27", "")
            self.assertEqual(repository.follow_up_for("2026-09-27"), "")
            self.assertEqual(repository.save_focus_task("  合成焦点  "), "合成焦点")
            self.assertEqual(DailyRepository(repository.database_path).focus_task(), "合成焦点")
            with self.assertRaises(DailyRepositoryError):
                repository.save_follow_up("2026-02-30", "不保存")
            with self.assertRaises(DailyRepositoryError):
                repository.save_follow_up("2026-09-27", "字" * 501)
            with self.assertRaises(DailyRepositoryError):
                repository.save_focus_task("字" * 101)

    def test_spotify_url_is_validated_for_new_values_but_legacy_value_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package, _ = _package(_main_state(settings={
                "dailyFlowAudioUrl": "https://open.spotify.com/episode/0123456789?si=old-value",
            }))
            db = Path(directory) / "daily.sqlite3"
            repository = DailyRepository(db, package)
            self.assertEqual(repository.spotify_url(),
                             "https://open.spotify.com/episode/0123456789?si=old-value")
            self.assertEqual(repository.save_spotify_url(
                "https://open.spotify.com/track/0123456789?si=new-value"),
                "https://open.spotify.com/track/0123456789?si=new-value")
            with self.assertRaises(DailyRepositoryError):
                repository.save_spotify_url("https://example.com/audio")
            repository.save_spotify_url("")
            self.assertEqual(DailyRepository(db).spotify_url(), "")
            self.assertEqual(DailyRepository(db).state()["spotifyMigrationDecision"], "external_link")

    def test_late_import_adopts_only_fields_not_changed_locally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "daily.sqlite3"
            repository = DailyRepository(db)
            repository.save_focus_task("本机自己写的焦点")
            package, _ = _package(_main_state(settings={
                "dailyFlowNotes": {"2026-09-26": "导入跟进"},
                "dailyFlowFocusTask": "旧版焦点",
                "dailyFlowAudioUrl": "https://open.spotify.com/track/0123456789",
            }), ["导入的问题"])
            repository.adopt_imported_data(package)
            reopened = DailyRepository(db)
            self.assertEqual(reopened.focus_task(), "本机自己写的焦点")
            self.assertEqual(reopened.follow_up_for("2026-09-26"), "导入跟进")
            self.assertEqual(reopened.spotify_url(), "https://open.spotify.com/track/0123456789")
            self.assertEqual(reopened.questions(), ["导入的问题"])

    def test_sqlite_failure_rolls_back_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "daily.sqlite3"
            repository = DailyRepository(db)
            repository.save_focus_task("旧焦点")
            with closing(sqlite3.connect(db)) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_daily_update BEFORE UPDATE ON daily_flow_state "
                    "BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END"
                )
                connection.commit()
            with self.assertRaises(DailyRepositoryError):
                repository.save_focus_task("新焦点")
            self.assertEqual(repository.focus_task(), "旧焦点")
            self.assertEqual(DailyRepository(db).focus_task(), "旧焦点")


class FocusTimerTests(unittest.TestCase):
    def test_25_minute_start_pause_resume_complete_restart_and_reset(self) -> None:
        timer = FocusTimer()
        self.assertEqual(timer.display(), "25:00")
        self.assertEqual(timer.button_label(), "开始专注")
        self.assertEqual(timer.toggle(), "暂停")
        self.assertFalse(timer.tick(15))
        self.assertEqual(timer.display(), "24:45")
        self.assertAlmostEqual(timer.progress(), 15 / 1500)
        self.assertEqual(timer.toggle(), "继续专注")
        self.assertFalse(timer.tick(1500))
        self.assertEqual(timer.display(), "24:45")
        self.assertEqual(timer.toggle(), "暂停")
        self.assertTrue(timer.tick(2000))
        self.assertEqual(timer.button_label(), "再来一轮")
        self.assertEqual(timer.toggle(), "暂停")
        self.assertEqual(timer.display(), "25:00")
        timer.reset()
        self.assertEqual(timer.button_label(), "开始专注")
        self.assertEqual(timer.display(), "25:00")
        with self.assertRaises(DailyRepositoryError):
            timer.tick(-1)


if __name__ == "__main__":
    unittest.main()
