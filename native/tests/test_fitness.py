from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from openpyxl import load_workbook

from wanxiang.database import import_package
from wanxiang.fitness import (
    DEFAULT_PROFILE,
    DEFAULT_WEEKLY_PLAN,
    FitnessRepository,
    FitnessRepositoryError,
)
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _record(
    record_id: str,
    kind: str,
    day: str,
    data: dict[str, object],
    **extra: object,
) -> dict[str, object]:
    return {
        "id": record_id,
        "type": kind,
        "date": day,
        "createdAt": 10,
        "sample": False,
        "data": data,
        **extra,
    }


def _source(
    records: list[dict[str, object]] | None = None,
    settings: dict[str, object] | None = None,
    **state_extra: object,
) -> dict[str, object]:
    return {
        "version": 2,
        "records": records or [],
        "habits": [],
        "mediaItems": [],
        "settings": settings or {},
        **state_extra,
    }


def _package(state: dict[str, object]):
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    raw_values["richangji-state-v1"] = json.dumps(
        state, ensure_ascii=False, separators=(",", ":")
    )
    return validate_package(
        {
            "format": PACKAGE_FORMAT,
            "schemaVersion": PACKAGE_SCHEMA_VERSION,
            "sourceVersion": "synthetic-test",
            "exportedAt": "2026-09-27T10:00:00Z",
            "keys": raw_values,
            "checksum": calculate_checksum(raw_values),
        }
    )


class FitnessRepositoryTests(unittest.TestCase):
    def test_old_records_settings_and_unknown_fields_are_preserved(self) -> None:
        old_fitness = _record(
            "weight-old",
            "fitness",
            "2026-09-26",
            {"weight": 64.5, "duration": 35, "note": "散步", "futureData": {"keep": True}},
            futureRecordField="untouched",
        )
        other_module = _record("planner-old", "planner", "2026-09-27", {"title": "留存"})
        legacy = _source(
            [old_fitness, other_module],
            {
                "fitnessProfile": {"height": 170, "target": 60, "age": 29, "custom": {"keep": 1}},
                "weeklyPlan": [{"id": "legacy-plan", "group": "恢复", "title": "旧计划",
                                "note": "留存", "done": False, "futurePlanField": 7}],
                "futureSetting": {"keep": "yes"},
            },
            futureStateField="state-kept",
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fitness.sqlite3"
            repository = FitnessRepository(database, legacy)

            self.assertEqual(repository.records(), [old_fitness, other_module])
            self.assertEqual(repository.fitness_records()[0]["futureRecordField"], "untouched")
            self.assertEqual(repository.fitness_records()[0]["data"]["futureData"], {"keep": True})
            self.assertEqual(repository.profile()["age"], 29)
            self.assertEqual(repository.profile()["custom"], {"keep": 1})
            self.assertEqual(repository.settings()["futureSetting"], {"keep": "yes"})
            self.assertEqual(repository.weekly_plan()[0]["futurePlanField"], 7)

            with closing(sqlite3.connect(database)) as connection:
                stored = json.loads(connection.execute(
                    "SELECT state_json FROM fitness_module_state WHERE singleton=1"
                ).fetchone()[0])
                stored["deletedRecords"] = [{"type": "planner", "id": "planner-old"}]
                connection.execute(
                    "UPDATE fitness_module_state SET state_json=? WHERE singleton=1",
                    (json.dumps(stored, ensure_ascii=False),),
                )
                connection.commit()
            reopened = FitnessRepository(database)
            self.assertEqual(reopened.records(), [old_fitness, other_module])
            self.assertEqual(reopened.settings()["futureSetting"], {"keep": "yes"})

    def test_record_validation_boundaries_and_local_add_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = FitnessRepository(Path(directory) / "validation.sqlite3", _source())
            low = repository.add_record(20, 0, "2026-09-27", "  起点  ", record_id="low", created_at=1)
            high = repository.add_record(300, 1440, "2026-09-28", "", record_id="high", created_at=2)
            self.assertEqual(low["data"], {"weight": 20, "duration": 0, "note": "起点"})
            self.assertEqual(high["data"]["duration"], 1440)
            self.assertEqual([item["id"] for item in repository.fitness_records()], ["high", "low"])

            invalid = [
                (19.9, 0, "2026-09-27", ""),
                (300.1, 0, "2026-09-27", ""),
                (True, 0, "2026-09-27", ""),
                (65.25, 1, "2026-09-27", ""),
                (65, -1, "2026-09-27", ""),
                (65, 1441, "2026-09-27", ""),
                (65, 1.5, "2026-09-27", ""),
                (65, 1, "2026-02-30", ""),
                (65, 1, "2026-09-27", "x" * 61),
            ]
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(FitnessRepositoryError):
                    repository.add_record(*args)

            self.assertTrue(repository.delete_record("low"))
            self.assertFalse(repository.delete_record("low"))
            self.assertEqual([item["id"] for item in repository.records()], ["high"])

    def test_imported_delete_uses_fitness_tombstone_without_changing_migration_original(self) -> None:
        old_records = [
            _record("fitness-delete", "fitness", "2026-09-20", {"weight": 70}, extraLegacy=True),
            _record("planner-stays", "planner", "2026-09-21", {"title": "保留待办"}),
            _record("money-stays", "money", "2026-09-22", {"amount": 3}),
        ]
        old_state = _source(old_records, {"fitnessProfile": {"height": 172}})
        source_text = json.dumps(old_state, ensure_ascii=False, separators=(",", ":"))
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "imported.sqlite3"
            import_package(_package(old_state), database)
            repository = FitnessRepository(database)

            self.assertTrue(repository.delete_record("fitness-delete"))
            self.assertEqual(repository.deleted_record_keys(), [{"type": "fitness", "id": "fitness-delete"}])
            self.assertEqual([row["id"] for row in repository.records()], ["planner-stays", "money-stays"])

            reopened = FitnessRepository(database)
            self.assertEqual([row["id"] for row in reopened.records()], ["planner-stays", "money-stays"])
            with closing(sqlite3.connect(database)) as connection:
                raw = connection.execute(
                    "SELECT raw_value FROM legacy_storage WHERE storage_key='richangji-state-v1'"
                ).fetchone()[0]
                source_rows = connection.execute(
                    "SELECT COUNT(*) FROM records WHERE record_type='fitness'"
                ).fetchone()[0]
            self.assertEqual(raw, source_text)
            self.assertEqual(source_rows, 1)

    def test_profile_updates_height_target_and_start_weight_and_preserves_other_fields(self) -> None:
        legacy_plan = {
            "id": "keep-plan",
            "group": "运动",
            "title": "保留字段",
            "note": "旧说明",
            "done": False,
            "futurePlanField": {"keep": True},
        }
        settings = {
            "fitnessProfile": {
                "height": 170,
                "target": 68,
                "startWeight": 82,
                "age": 34,
                "sex": "male",
                "activity": 1.55,
                "profileFuture": "keep",
            },
            "weeklyPlan": [legacy_plan],
            "otherSetting": [1, 2],
        }
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "profile-plan.sqlite3"
            repository = FitnessRepository(database, _source(settings=settings))
            updated = repository.set_profile(
                height=171, target="67.5", start_weight="79.5"
            )
            self.assertEqual((updated["height"], updated["target"]), (171, 67.5))
            self.assertEqual(updated["startWeight"], 79.5)
            self.assertEqual(updated["age"], 34)
            self.assertEqual(updated["sex"], "male")
            self.assertEqual(updated["activity"], 1.55)
            self.assertEqual(updated["profileFuture"], "keep")

            with self.assertRaises(FitnessRepositoryError):
                repository.set_profile(height=99)
            with self.assertRaises(FitnessRepositoryError):
                repository.set_profile(target=200.1)
            with self.assertRaises(FitnessRepositoryError):
                repository.set_profile(start_weight=19.9)
            with self.assertRaises(FitnessRepositoryError):
                repository.set_profile(start_weight=75.55)

            added = repository.add_plan("恢复", "午休拉伸", "每天下午")
            self.assertEqual(added["note"], "每天下午")
            self.assertFalse(added["done"])
            self.assertEqual(repository.weekly_plan()[0]["futurePlanField"], {"keep": True})
            toggled = repository.toggle_plan("keep-plan")
            self.assertTrue(toggled["done"])
            self.assertEqual(toggled["futurePlanField"], {"keep": True})
            self.assertFalse(repository.toggle_plan("missing"))
            self.assertTrue(repository.delete_plan(added["id"]))
            self.assertFalse(repository.delete_plan(added["id"]))

            reopened = FitnessRepository(database)
            self.assertEqual(reopened.profile()["startWeight"], 79.5)
            self.assertEqual(reopened.profile()["height"], 171)
            self.assertEqual(reopened.weekly_plan(), [{**legacy_plan, "done": True}])
            self.assertEqual(reopened.settings()["otherSetting"], [1, 2])

    def test_default_profile_and_weekly_plan_match_legacy_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = FitnessRepository(Path(directory) / "defaults.sqlite3", _source())
            self.assertEqual(repository.profile(), DEFAULT_PROFILE)
            summary = repository.summary("2026-09-28")
            self.assertEqual(repository.state("2026-09-28")["profileFields"], [])
            self.assertFalse(summary["hasWeightRecord"])
            self.assertIsNone(summary["current"])
            self.assertIsNone(summary["height"])
            self.assertIsNone(summary["target"])
            self.assertIsNone(summary["bmi"])
            self.assertIsNone(summary["remaining"])
            self.assertIsNone(summary["progress"])
            self.assertEqual(repository.weekly_plan(), list(DEFAULT_WEEKLY_PLAN))
            self.assertEqual(len(repository.weekly_plan()), 6)

    def test_plan_validation_defaults_and_profile_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = FitnessRepository(Path(directory) / "plan-validation.sqlite3", _source())
            created = repository.add_plan("其他", "  一点拉伸  ", "  ")
            self.assertEqual(created["title"], "一点拉伸")
            self.assertEqual(created["note"], "按自己的节奏完成")
            invalid = [
                ("未知", "名字", ""),
                ("运动", " " * 2, ""),
                ("运动", "计划" * 15, ""),
                ("饮食", "计划", "说明" * 31),
            ]
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(FitnessRepositoryError):
                    repository.add_plan(*args)
            self.assertEqual(repository.set_profile(height=100, target=30)["height"], 100)
            self.assertEqual(repository.set_profile(height=230, target=200)["target"], 200)

    def test_bmi_goal_estimate_and_seven_point_trend_match_legacy_math(self) -> None:
        rows = [
            _record("w1", "fitness", "2026-01-01", {"weight": 70, "duration": 20, "note": "起点"}),
            _record("exercise-only", "fitness", "2026-01-04", {"duration": 30, "note": "训练"}),
            _record("w2", "fitness", "2026-01-08", {"weight": 68, "duration": 40, "note": ""}),
        ]
        settings = {"fitnessProfile": {"height": 170, "target": 65, "startWeight": 72}}
        with tempfile.TemporaryDirectory() as directory:
            repository = FitnessRepository(Path(directory) / "stats.sqlite3", _source(rows, settings))
            summary = repository.summary("2026-01-08")
            self.assertEqual((summary["current"], summary["start"], summary["target"]), (68, 72, 65))
            self.assertAlmostEqual(summary["bmi"], 68 / (1.7**2), places=9)
            self.assertEqual(summary["remaining"], 3)
            self.assertEqual(summary["elapsedDays"], 7)
            self.assertEqual(summary["days"], 11)
            self.assertAlmostEqual(summary["progress"], (4 / 7) * 100)
            self.assertEqual([point["weight"] for point in repository.trend_points()], [70, 68])
            self.assertEqual([point["average"] for point in repository.trend_points()], [70, 69])
            self.assertEqual(len(summary["records"]), 2)

            state = repository.state("2026-01-08")
            self.assertEqual(state["profile"]["height"], 170)
            self.assertEqual(len(state["records"]), 3)
            self.assertEqual(state["summary"]["days"], 11)

    def test_trend_is_limited_to_latest_30_points_and_seven_record_moving_average(self) -> None:
        start = date(2026, 1, 1)
        rows = [
            _record(
                f"w-{index}",
                "fitness",
                (start + timedelta(days=index)).isoformat(),
                {"weight": 80 + index},
                createdAt=index,
            )
            for index in range(35)
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = FitnessRepository(Path(directory) / "trend.sqlite3", _source(rows))
            points = repository.trend_points()
            self.assertEqual(len(points), 30)
            self.assertEqual(points[0]["date"], "2026-01-06")
            self.assertEqual(points[0]["weight"], 85)
            self.assertEqual(points[6]["average"], 88)
            self.assertEqual(points[-1]["average"], 111)

    def test_trend_calendar_ranges_filter_by_real_record_dates(self) -> None:
        today = date(2026, 9, 29)
        rows = [
            _record("old", "fitness", (today - timedelta(days=100)).isoformat(), {"weight": 80}),
            _record("middle", "fitness", (today - timedelta(days=45)).isoformat(), {"weight": 75}),
            _record("recent", "fitness", (today - timedelta(days=2)).isoformat(), {"weight": 70}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = FitnessRepository(Path(directory) / "trend-ranges.sqlite3", _source(rows))
            self.assertEqual(
                [point["date"] for point in repository.trend_points(days=30, today=today)],
                [(today - timedelta(days=2)).isoformat()],
            )
            self.assertEqual(
                [point["date"] for point in repository.trend_points(days=90, today=today)],
                [(today - timedelta(days=45)).isoformat(), (today - timedelta(days=2)).isoformat()],
            )
            self.assertEqual(
                len(repository.trend_points(all_records=True, today=today)),
                3,
            )

    def test_excel_rows_and_shared_helper_export_workbook(self) -> None:
        rows = [
            _record("older", "fitness", "2026-09-20", {"weight": 61.5, "duration": 20, "note": "晨跑"}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = FitnessRepository(root / "export.sqlite3", _source(rows))
            repository.add_record(62, 0, "2026-09-27", "  恢复日  ", record_id="newer", created_at=30)
            export_data = repository.excel_export_data()
            self.assertEqual(export_data["headers"], ["日期", "体重(kg)", "运动分钟", "备注"])
            self.assertEqual(export_data["rows"], [
                ["2026-09-27", 62, "", "恢复日"],
                ["2026-09-20", 61.5, 20, "晨跑"],
            ])
            english = repository.excel_export_data("en")
            self.assertEqual(english["headers"], ["Date", "Weight (kg)", "Exercise (min)", "Note"])
            with self.assertRaises(FitnessRepositoryError):
                repository.excel_export_data("fr")

            target = repository.export_excel(root / "fitness.xlsx")
            self.assertTrue(target.is_file())
            workbook = load_workbook(target, read_only=True, data_only=False)
            try:
                actual_rows = list(workbook.active.values)
            finally:
                workbook.close()
            expected_rows = [
                tuple(export_data["headers"]),
                *[tuple(None if value == "" else value for value in row) for row in export_data["rows"]],
            ]
            self.assertEqual(actual_rows, expected_rows)

    def test_write_failure_rolls_back_database_and_in_memory_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "rollback.sqlite3"
            repository = FitnessRepository(database, _source())
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    """CREATE TRIGGER reject_fitness_update BEFORE UPDATE ON fitness_module_state
                    BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END"""
                )
            with self.assertRaises(FitnessRepositoryError):
                repository.add_record(60, 30, "2026-09-27", "不会保存")
            self.assertEqual(repository.fitness_records(), [])
            reopened = FitnessRepository(database)
            self.assertEqual(reopened.fitness_records(), [])

    def test_late_import_adoption_keeps_local_record_and_tombstone_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "adopt.sqlite3"
            repository = FitnessRepository(database, _source())
            local = repository.add_record(64, 15, "2026-09-27", "本机记录", record_id="local-id")
            self.assertEqual(local["id"], "local-id")
            self.assertTrue(repository.adopt_imported_data(_source([
                _record("imported-fitness", "fitness", "2026-09-20", {"weight": 65}),
                _record("other-module", "home", "2026-09-21", {"name": "书"}),
            ], {"fitnessProfile": {"height": 170, "target": 60}})))
            self.assertEqual(
                {row["id"] for row in repository.fitness_records()}, {"local-id", "imported-fitness"}
            )
            self.assertTrue(repository.delete_record("imported-fitness"))
            self.assertEqual([row["id"] for row in repository.records()], ["other-module", "local-id"])
            self.assertFalse(repository.adopt_imported_data({"status": "empty"}))


if __name__ == "__main__":
    unittest.main()
