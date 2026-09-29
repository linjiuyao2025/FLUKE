from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wanxiang.database import import_package
from wanxiang.habits import (
    BUILTIN_HABITS,
    HabitRepository,
    HabitRepositoryError,
)
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _habit(
    habit_id: str,
    key: str,
    *,
    name: str | None = None,
    habit_type: str = "check",
    target: int | float = 1,
    entries: dict[str, int | float] | None = None,
    **extra: object,
) -> dict[str, object]:
    return {
        "id": habit_id,
        "key": key,
        "name": name or f"合成习惯 {habit_id}",
        "type": habit_type,
        "target": target,
        "unit": "次",
        "tone": "sage",
        "entries": entries or {},
        "sample": False,
        **extra,
    }


def _package_for_habits(habits: list[dict[str, object]], hidden: list[str] | None = None):
    state = {
        "version": 2,
        "records": [],
        "habits": habits,
        "mediaItems": [],
        "settings": {"hiddenHabitKeys": hidden or []},
    }
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


def _database_source_rows(database_path: Path) -> tuple[list[tuple], list[tuple]]:
    with closing(sqlite3.connect(database_path)) as connection:
        legacy = connection.execute(
            "SELECT storage_key, raw_value FROM legacy_storage ORDER BY storage_key"
        ).fetchall()
        documents = connection.execute(
            "SELECT document_key, document_json FROM json_documents ORDER BY document_key"
        ).fetchall()
    return legacy, documents


class HabitRepositoryTests(unittest.TestCase):
    def test_empty_database_seeds_old_builtin_definitions_without_fake_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "habits.sqlite3"
            repository = HabitRepository(database_path)

            habits = repository.habits()
            self.assertEqual([item["key"] for item in habits], [item["key"] for item in BUILTIN_HABITS])
            self.assertEqual([item["target"] for item in habits], [8, 7, 1, 1, 1])
            self.assertTrue(all(item["entries"] == {} for item in habits))
            self.assertTrue(all(item["sample"] is False for item in habits))

            first = repository.habits()
            first[0]["entries"]["2026-09-27"] = 100
            reopened = HabitRepository(database_path)
            self.assertEqual(reopened.habits()[0]["entries"], {})

    def test_legacy_entries_precede_completed_dates_and_unknown_fields_survive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            legacy = {
                "version": 2,
                "habits": [
                    _habit(
                        "habit-water",
                        "water",
                        name="喝水",
                        habit_type="counter",
                        target=8,
                        entries={"2026-09-26": 4},
                        completedDates=["2026-09-26", "2026-09-27", "2026-09-27"],
                        remoteEntries={"2026-09-26": "remote-row"},
                        futureField={"kept": True},
                    )
                ],
                "settings": {"hiddenHabitKeys": ["meditation"]},
            }
            repository = HabitRepository(Path(directory) / "legacy.sqlite3", legacy)
            habits = repository.habits()
            water = next(item for item in habits if item["key"] == "water")

            self.assertEqual(water["entries"], {"2026-09-26": 4, "2026-09-27": 1})
            self.assertEqual(water["remoteEntries"], {"2026-09-26": "remote-row"})
            self.assertEqual(water["futureField"], {"kept": True})
            self.assertNotIn("meditation", [item["key"] for item in habits])
            self.assertEqual(repository.hidden_habit_keys(), ["meditation"])

    def test_invalid_legacy_dates_values_and_targets_are_rejected_without_materializing(self) -> None:
        invalid_rows = [
            [_habit("bad-date", "custom-date", entries={"2026-02-30": 1})],
            [_habit("bad-value", "custom-value", entries={"2026-09-27": -1})],
            [_habit("bad-bool", "custom-bool", entries={"2026-09-27": True})],
            [_habit("bad-target", "custom-target", target=1000)],
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, rows in enumerate(invalid_rows):
                database_path = Path(directory) / f"invalid-{index}.sqlite3"
                with self.subTest(index=index), self.assertRaises(HabitRepositoryError):
                    HabitRepository(database_path, {"habits": rows})
                self.assertFalse(database_path.exists())

    def test_check_counter_and_number_actions_obey_legacy_bounds_and_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "actions.sqlite3"
            repository = HabitRepository(database_path)
            today = "2026-09-27"

            water = repository.adjust_counter("habit-water", today, -3)
            self.assertEqual(water["entries"][today], 0)
            water = repository.adjust_counter("habit-water", today, 2)
            self.assertEqual(water["entries"][today], 2)
            water = repository.quick_check("habit-water", today)
            self.assertEqual(water["entries"][today], 8)
            water = repository.quick_check("habit-water", today)
            self.assertEqual(water["entries"][today], 0)

            sleep = repository.set_value("habit-sleep", today, 12000)
            self.assertEqual(sleep["entries"][today], 9999)
            sleep = repository.set_value("habit-sleep", today, -3)
            self.assertEqual(sleep["entries"][today], 0)
            sleep = repository.quick_check("habit-sleep", today)
            self.assertEqual(sleep["entries"][today], 7)
            sleep = repository.quick_check("habit-sleep", today)
            self.assertEqual(sleep["entries"][today], 0)

            exercise = repository.quick_check("habit-exercise", today)
            self.assertEqual(exercise["entries"][today], 1)
            exercise = repository.set_value("habit-exercise", today, 0)
            self.assertEqual(exercise["entries"][today], 0)
            with self.assertRaises(HabitRepositoryError):
                repository.set_value("habit-exercise", today, 2)
            with self.assertRaises(HabitRepositoryError):
                repository.adjust_counter("habit-sleep", today, 1)
            with self.assertRaises(HabitRepositoryError):
                repository.quick_check("missing-habit", today)

    def test_add_habit_target_name_and_date_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = HabitRepository(Path(directory) / "add.sqlite3")
            check = repository.add_habit(
                {
                    "id": "custom-check",
                    "key": "custom-check",
                    "name": "  合成打卡  ",
                    "type": "check",
                    "target": 50,
                    "unit": "分钟",
                    "tone": "plum",
                }
            )
            self.assertEqual(check["name"], "合成打卡")
            self.assertEqual(check["target"], 1)
            self.assertEqual(check["unit"], "次")

            maximum = repository.add_habit(
                {
                    "id": "custom-max",
                    "key": "custom-max",
                    "name": "上限目标",
                    "type": "number",
                    "target": 999,
                }
            )
            self.assertEqual(maximum["target"], 999)
            for definition in (
                {"id": "bad-min", "key": "bad-min", "name": "低目标", "type": "counter", "target": 0},
                {"id": "bad-max", "key": "bad-max", "name": "高目标", "type": "number", "target": 1000},
                {"id": "bad-date", "key": "bad-date", "name": "错日期", "type": "counter", "entries": {"2026-02-30": 1}},
                {"id": "bad-tone", "key": "bad-tone", "name": "错颜色", "type": "check", "tone": "unknown"},
            ):
                with self.subTest(definition=definition["id"]), self.assertRaises(HabitRepositoryError):
                    repository.add_habit(definition)

            self.assertEqual({item["id"] for item in repository.habits()}, {"habit-water", "habit-sleep", "habit-exercise", "habit-reading", "habit-meditation", "custom-check", "custom-max"})

    def test_metrics_include_today_week_month_heatmap_and_streaks(self) -> None:
        end = "2026-09-27"
        rows = [
            _habit(
                "habit-water",
                "water",
                name="喝水",
                habit_type="counter",
                target=8,
                entries={
                    "2026-09-20": 8,
                    "2026-09-21": 8,
                    "2026-09-25": 4,
                    "2026-09-26": 8,
                    "2026-09-27": 8,
                },
            ),
            _habit(
                "habit-sleep",
                "sleep",
                name="睡觉",
                habit_type="number",
                target=7,
                entries={"2026-09-26": 7, "2026-09-27": 7},
            ),
            _habit(
                "habit-exercise",
                "exercise",
                name="运动",
                entries={"2026-09-27": 1},
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = HabitRepository(Path(directory) / "metrics.sqlite3", {"habits": rows})
            metrics = repository.metrics(end)

            self.assertEqual((metrics["date"], metrics["done"], metrics["total"]), (end, 3, 5))
            self.assertEqual(metrics["bestStreak"], 2)
            self.assertEqual(metrics["completionRate30Days"], 5)
            water = next(item for item in metrics["habits"] if item["key"] == "water")
            self.assertEqual((water["streak"], water["bestStreak"], water["done7"]), (2, 2, 3))
            partial = next(cell for cell in water["history"] if cell["date"] == "2026-09-25")
            self.assertEqual((partial["value"], partial["done"], partial["partial"]), (4, False, True))
            self.assertEqual(len(water["history"]), 30)
            self.assertEqual(metrics["week"]["total"], 6)
            self.assertEqual(metrics["week"]["completionRate"], 17)
            self.assertEqual(metrics["week"]["topHabits"][0], {"id": "habit-water", "name": "喝水", "count": 3})

    def test_completion_rates_exclude_days_before_habit_creation(self) -> None:
        habit = _habit(
            "new-habit",
            "custom-new-habit",
            createdDate="2026-09-24",
            entries={"2026-09-24": 1, "2026-09-26": 1, "2026-09-27": 1},
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = HabitRepository(
                Path(directory) / "new-habit.sqlite3",
                {
                    "habits": [habit],
                    "settings": {"hiddenHabitKeys": [item["key"] for item in BUILTIN_HABITS]},
                },
            )
            metrics = repository.metrics("2026-09-27")

        self.assertEqual((metrics["total"], metrics["done"]), (1, 1))
        self.assertEqual(metrics["completionRate30Days"], 75)
        self.assertEqual(metrics["week"]["completionRate"], 75)
        history = metrics["habits"][0]["history"]
        before_creation = next(item for item in history if item["date"] == "2026-09-23")
        creation_day = next(item for item in history if item["date"] == "2026-09-24")
        self.assertFalse(before_creation["active"])
        self.assertTrue(creation_day["active"])

    def test_weekday_schedule_ignores_rest_days_and_streak_counts_due_days(self) -> None:
        habit = _habit(
            "weekday-habit",
            "custom-weekday-habit",
            createdDate="2026-09-21",
            schedule={"type": "weekdays", "days": [1, 3, 5]},
            entries={"2026-09-21": 1, "2026-09-23": 1, "2026-09-25": 1},
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = HabitRepository(
                Path(directory) / "weekday-habit.sqlite3",
                {
                    "habits": [habit],
                    "settings": {"hiddenHabitKeys": [item["key"] for item in BUILTIN_HABITS]},
                },
            )
            metrics = repository.metrics("2026-09-27")

            self.assertEqual((metrics["total"], metrics["done"]), (0, 0))
            self.assertEqual(metrics["completionRate30Days"], 100)
            self.assertEqual(metrics["week"]["completionRate"], 100)
            self.assertEqual(metrics["habits"][0]["streak"], 3)
            self.assertEqual(metrics["habits"][0]["bestStreak"], 3)
            saturday = next(
                item for item in metrics["habits"][0]["history"]
                if item["date"] == "2026-09-26"
            )
            self.assertTrue(saturday["active"])
            self.assertFalse(saturday["due"])
            self.assertFalse(saturday["eligible"])

            repository.set_value("weekday-habit", "2026-09-23", 0)
            missed = repository.metrics("2026-09-27")
            self.assertEqual(missed["week"]["completionRate"], 67)
            self.assertEqual(missed["habits"][0]["streak"], 1)
            self.assertEqual(missed["habits"][0]["bestStreak"], 1)

    def test_weekday_schedule_validation_rejects_empty_invalid_and_duplicate_days(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = HabitRepository(Path(directory) / "schedule-validation.sqlite3")
            for days in ([], [0, 1], [1, 1], [True]):
                with self.subTest(days=days), self.assertRaises(HabitRepositoryError):
                    repository.add_habit(
                        {
                            "name": "无效频率",
                            "type": "check",
                            "schedule": {"type": "weekdays", "days": days},
                        }
                    )

    def test_schedule_edits_preserve_history_and_only_change_due_days_from_effective_date(self) -> None:
        habit = _habit(
            "editable-habit",
            "custom-editable-habit",
            name="可编辑记录",
            createdDate="2026-09-21",
            entries={
                "2026-09-21": 1,
                "2026-09-22": 1,
                "2026-09-23": 1,
                "2026-09-24": 1,
                "2026-09-25": 1,
            },
        )
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "schedule-edit.sqlite3"
            repository = HabitRepository(
                database_path,
                {"habits": [habit], "settings": {"hiddenHabitKeys": [item["key"] for item in BUILTIN_HABITS]}},
            )
            original_entries = repository.habits()[0]["entries"]
            updated = repository.update_habit(
                "editable-habit",
                {"schedule": {"type": "weekdays", "days": [1, 3, 5]}},
                effective_date="2026-09-24",
            )
            metrics = repository.metrics("2026-09-27")
            persisted = HabitRepository(database_path).habits()[0]

        self.assertEqual(updated["entries"], original_entries)
        self.assertEqual(persisted["entries"], original_entries)
        self.assertEqual(persisted["scheduleHistory"], updated["scheduleHistory"])
        self.assertEqual(
            updated["scheduleHistory"],
            [
                {"effectiveDate": "2026-09-21", "schedule": {"type": "daily"}},
                {"effectiveDate": "2026-09-24", "schedule": {"type": "weekdays", "days": [1, 3, 5]}},
            ],
        )
        history = metrics["habits"][0]["history"]
        self.assertTrue(next(item for item in history if item["date"] == "2026-09-23")["due"])
        self.assertFalse(next(item for item in history if item["date"] == "2026-09-24")["due"])
        self.assertEqual(metrics["completionRate30Days"], 100)

    def test_schedule_edit_rejects_backdated_change_without_modifying_habit(self) -> None:
        habit = _habit(
            "editable-habit",
            "custom-editable-habit",
            createdDate="2026-09-21",
            scheduleHistory=[
                {"effectiveDate": "2026-09-21", "schedule": {"type": "daily"}},
                {"effectiveDate": "2026-09-25", "schedule": {"type": "weekdays", "days": [1, 3, 5]}},
            ],
            schedule={"type": "weekdays", "days": [1, 3, 5]},
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = HabitRepository(
                Path(directory) / "schedule-edit.sqlite3",
                {"habits": [habit], "settings": {"hiddenHabitKeys": [item["key"] for item in BUILTIN_HABITS]}},
            )
            before = repository.habits()
            with self.assertRaises(HabitRepositoryError):
                repository.update_habit(
                    "editable-habit",
                    {"schedule": {"type": "daily"}},
                    effective_date="2026-09-24",
                )

        self.assertEqual(repository.habits(), before)

    def test_delete_builtin_hides_key_and_restart_keeps_local_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "delete.sqlite3"
            repository = HabitRepository(database_path)
            repository.set_value("habit-water", "2026-09-27", 4)

            self.assertTrue(repository.delete_habit("habit-water"))
            self.assertFalse(repository.delete_habit("habit-water"))
            self.assertEqual(repository.hidden_habit_keys(), ["water"])
            reopened = HabitRepository(database_path, {"habits": [_habit("habit-water", "water", entries={"2026-09-27": 8})]})
            self.assertNotIn("water", [item["key"] for item in reopened.habits()])
            self.assertEqual(reopened.hidden_habit_keys(), ["water"])

    def test_clear_samples_preserves_user_rows_unknown_fields_and_remote_entries(self) -> None:
        sample = _habit(
            "habit-water",
            "water",
            name="喝水",
            habit_type="counter",
            target=8,
            entries={"2026-09-27": 6},
            completedDates=["2026-09-26"],
            sample=True,
            remoteEntries={"2026-09-27": "remote-sample"},
            futureField="kept",
        )
        user = _habit(
            "user-1",
            "custom-user-1",
            habit_type="number",
            target=7,
            entries={"2026-09-27": 5},
            sample=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = HabitRepository(Path(directory) / "samples.sqlite3", {"habits": [sample, user]})
            self.assertEqual(repository.clear_samples(), 1)
            rows = repository.habits()
            water = next(item for item in rows if item["key"] == "water")
            user_row = next(item for item in rows if item["id"] == "user-1")
            self.assertFalse(water["sample"])
            self.assertEqual(water["entries"], {})
            self.assertEqual(water["completedDates"], [])
            self.assertEqual(water["remoteEntries"], {"2026-09-27": "remote-sample"})
            self.assertEqual(water["futureField"], "kept")
            self.assertEqual(user_row["entries"], {"2026-09-27": 5})
            self.assertEqual(repository.clear_samples(), 0)
            reopened = HabitRepository(Path(directory) / "samples.sqlite3")
            re_adopted = reopened.adopt_imported_data([sample], [])
            retained_water = next(item for item in re_adopted if item["key"] == "water")
            self.assertEqual(retained_water["entries"], {})
            self.assertFalse(retained_water["sample"])

    def test_adopt_after_startup_preserves_local_collision_merges_new_ids_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "adopt.sqlite3"
            repository = HabitRepository(database_path)
            local = repository.add_habit(
                {
                    "id": "collision-id",
                    "key": "custom-local",
                    "name": "本机习惯",
                    "type": "counter",
                    "target": 4,
                }
            )
            repository.set_value(local["id"], "2026-09-27", 3)

            imported = [
                _habit(
                    "collision-id",
                    "custom-from-import",
                    name="导入冲突项",
                    habit_type="counter",
                    target=9,
                    entries={"2026-09-27": 9},
                    importedExtra="must-not-overwrite-local",
                ),
                _habit(
                    "source-only-id",
                    "custom-source-only",
                    name="新导入项",
                    habit_type="number",
                    target=2,
                    entries={"2026-09-27": 1},
                    importedExtra="retained",
                ),
                _habit(
                    "source-only-id",
                    "custom-source-only-duplicate",
                    name="重复 id",
                ),
            ]
            first = repository.adopt_imported_data(imported, ["sleep", "sleep"])
            local_after = next(item for item in first if item["id"] == "collision-id")
            added_after = next(item for item in first if item["id"] == "source-only-id")
            self.assertEqual(local_after["name"], "本机习惯")
            self.assertEqual(local_after["entries"], {"2026-09-27": 3})
            self.assertEqual(added_after["entries"], {"2026-09-27": 1})
            self.assertEqual(added_after["importedExtra"], "retained")
            self.assertNotIn("sleep", [item["key"] for item in first])
            self.assertEqual(repository.hidden_habit_keys(), ["sleep"])

            second = repository.adopt_imported_data(imported, ["sleep"])
            self.assertEqual(second, first)
            self.assertEqual(len([item for item in second if item["id"] == "source-only-id"]), 1)
            reopened = HabitRepository(database_path)
            self.assertEqual(reopened.habits(), first)

    def test_adopt_builtin_with_different_legacy_id_merges_by_key_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "builtin-id-merge.sqlite3"
            repository = HabitRepository(database_path)
            today = "2026-09-27"
            repository.set_value("habit-water", today, 2)

            # Seed a current runtime remote reference: the public repository
            # intentionally has no cloud-write API, so this remains synthetic
            # SQLite fixture data and never touches legacy migration tables.
            with closing(sqlite3.connect(database_path)) as connection:
                raw = connection.execute(
                    "SELECT habits_json FROM habit_module_state WHERE singleton=1"
                ).fetchone()[0]
                runtime_habits = json.loads(raw)
                runtime_water = next(item for item in runtime_habits if item["key"] == "water")
                runtime_water["remoteEntries"] = {today: "current-remote-row"}
                connection.execute(
                    "UPDATE habit_module_state SET habits_json=? WHERE singleton=1",
                    (json.dumps(runtime_habits, ensure_ascii=False, separators=(",", ":")),),
                )
                connection.commit()

            repository = HabitRepository(database_path)
            incoming = _habit(
                "legacy-water-id",
                "water",
                name="喝水",
                habit_type="counter",
                target=8,
                entries={today: 8, "2026-09-26": 8},
                remoteEntries={"2026-09-26": "imported-remote-row"},
                sourceOnlyField={"kept": True},
            )
            merged_habits = repository.adopt_imported_data([incoming], [])
            water_rows = [item for item in merged_habits if item["key"] == "water"]

            self.assertEqual(len(water_rows), 1)
            self.assertEqual(water_rows[0]["id"], "legacy-water-id")
            self.assertEqual(water_rows[0]["sourceOnlyField"], {"kept": True})
            self.assertEqual(water_rows[0]["entries"], {today: 2, "2026-09-26": 8})
            self.assertEqual(
                water_rows[0]["remoteEntries"],
                {today: "current-remote-row", "2026-09-26": "imported-remote-row"},
            )

            repeated = repository.adopt_imported_data([incoming], [])
            self.assertEqual(repeated, merged_habits)
            self.assertEqual(len([item for item in repeated if item["key"] == "water"]), 1)

    def test_later_adoption_merges_source_fields_and_keeps_runtime_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = HabitRepository(
                Path(directory) / "merge.sqlite3",
                {"habits": [_habit("legacy-1", "custom-legacy", name="旧名称", habit_type="counter", target=2)]},
            )
            repository.set_value("legacy-1", "2026-09-27", 1)
            updated = _habit(
                "legacy-1",
                "custom-legacy",
                name="新名称",
                habit_type="counter",
                target=3,
                entries={"2026-09-26": 2, "2026-09-27": 9},
                remoteEntries={"2026-09-26": "remote-row"},
                newUnknown="preserved",
            )

            row = next(item for item in repository.adopt_imported_data([updated], ["water"]) if item["id"] == "legacy-1")
            self.assertEqual(row["name"], "新名称")
            self.assertEqual(row["target"], 3)
            self.assertEqual(row["entries"], {"2026-09-26": 2, "2026-09-27": 1})
            self.assertEqual(row["remoteEntries"], {"2026-09-26": "remote-row"})
            self.assertEqual(row["newUnknown"], "preserved")

    def test_failed_write_rolls_back_database_and_in_memory_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "rollback.sqlite3"
            repository = HabitRepository(database_path)
            before = repository.habits()
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    f"""
                    CREATE TRIGGER reject_habit_update
                    BEFORE UPDATE ON {"habit_module_state"}
                    BEGIN
                        SELECT RAISE(ABORT, 'synthetic write failure');
                    END
                    """
                )
                connection.commit()

            with self.assertRaises(HabitRepositoryError):
                repository.adjust_counter("habit-water", "2026-09-27", 1)

            self.assertEqual(repository.habits(), before)
            self.assertEqual(HabitRepository(database_path).habits(), before)

    def test_materialization_and_mutations_never_change_legacy_source_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy-readonly.sqlite3"
            package = _package_for_habits(
                [
                    _habit(
                        "legacy-water",
                        "water",
                        name="喝水",
                        habit_type="counter",
                        target=8,
                        entries={"2026-09-26": 5},
                        futureField={"source": "untouched"},
                    )
                ],
                ["meditation"],
            )
            import_package(package, database_path)
            original = _database_source_rows(database_path)

            repository = HabitRepository(database_path)
            repository.adjust_counter("legacy-water", "2026-09-27", 1)
            repository.add_habit(
                {"id": "native-only", "key": "custom-native", "name": "本机新增", "type": "check"}
            )
            self.assertEqual(_database_source_rows(database_path), original)

            reopened = HabitRepository(database_path)
            self.assertEqual(
                next(item for item in reopened.habits() if item["id"] == "legacy-water")["entries"]["2026-09-27"],
                1,
            )


if __name__ == "__main__":
    unittest.main()
