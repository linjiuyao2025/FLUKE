from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wanxiang.database import import_package
from wanxiang.finance import (
    FinanceRepository,
    FinanceRepositoryError,
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


class FinanceRepositoryTests(unittest.TestCase):
    def test_full_records_settings_and_unknown_fields_survive_seed_and_reads(self) -> None:
        old_rows = [
            _record(
                "money-old", "money", "2026-09-26",
                {"flow": "expense", "amount": 12.5, "category": "吃饭", "note": "午饭",
                 "futureData": {"keep": True}},
                futureRecordField="untouched",
            ),
            _record("planner-old", "planner", "2026-09-27", {"title": "稍后处理"}),
        ]
        legacy = _source(
            old_rows,
            {"budget": 3456, "moneyFilter": "未来分类", "futureSetting": {"keep": 9}},
            futureStateField="preserved",
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "finance.sqlite3"
            repository = FinanceRepository(database, legacy)

            self.assertEqual(repository.records(), old_rows)
            self.assertEqual(repository.money_records(), old_rows[:1])
            self.assertEqual(repository.settings()["budget"], 3456)
            self.assertEqual(repository.settings()["moneyFilter"], "未来分类")
            self.assertEqual(repository.settings()["futureSetting"], {"keep": 9})
            self.assertEqual(repository.money_records()[0]["futureRecordField"], "untouched")
            self.assertEqual(
                repository.money_records()[0]["data"]["futureData"], {"keep": True}
            )
            result = repository.money_records()
            result[0]["data"]["note"] = "caller mutation"
            self.assertEqual(repository.money_records()[0]["data"]["note"], "午饭")

    def test_new_income_and_expense_validation_and_counter_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = FinanceRepository(
                Path(directory) / "add.sqlite3",
                _source(settings={"moneySinceExport": 19, "recordsSinceExport": 31}),
            )
            income = repository.add_record(
                "income", "125.50", "工资", "2026-09-27", "  月薪  ",
                record_id="new-income", created_at=500,
            )
            self.assertEqual(income["data"], {
                "flow": "income", "amount": 125.5, "category": "工资", "note": "月薪"
            })
            self.assertFalse(income["sample"])
            self.assertEqual(repository.summary("2026-09-27")["moneySinceExport"], 20)
            self.assertTrue(repository.summary("2026-09-27")["backupReminderDue"])
            self.assertEqual(repository.summary("2026-09-27")["recordsSinceExport"], 32)

            expense = repository.add_record(
                "expense", 1, "交通", "2026-09-26", "地铁", record_id="new-expense"
            )
            self.assertEqual(expense["data"]["amount"], 1)
            self.assertEqual(repository.money_records()[0]["id"], "new-income")
            self.assertEqual(repository.category_options(), [
                "吃饭", "交通", "购物", "娱乐", "房租", "看病", "学习", "其他",
                "工资", "奖金", "兼职", "理财",
            ])

            invalid = [
                ("transfer", 1, "其他", "2026-09-27", ""),
                ("income", 0, "工资", "2026-09-27", ""),
                ("expense", True, "吃饭", "2026-09-27", ""),
                ("expense", 1.001, "吃饭", "2026-09-27", ""),
                ("expense", 1, "工资", "2026-09-27", ""),
                ("expense", 1, "吃饭", "2026-02-30", ""),
                ("expense", 1, "吃饭", "2026-09-27", "x" * 61),
            ]
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(FinanceRepositoryError):
                    repository.add_record(*args)

    def test_filter_budget_and_sorting_match_old_module_contract(self) -> None:
        source = _source([
            _record("m-old", "money", "2026-09-26", {"flow": "expense", "amount": 5, "category": "吃饭", "note": ""}),
            _record("m-new", "money", "2026-09-27", {"flow": "expense", "amount": 8, "category": "交通", "note": ""}, createdAt=30),
            _record("f-old", "fitness", "2026-09-27", {"weight": 65}),
        ])
        with tempfile.TemporaryDirectory() as directory:
            repository = FinanceRepository(Path(directory) / "filter.sqlite3", source)
            self.assertEqual(repository.settings()["budget"], 5000)
            self.assertTrue(repository.settings()["budgetIsDefault"])
            self.assertEqual(repository.settings()["moneyFilter"], "all")
            self.assertEqual([row["id"] for row in repository.filtered_records()], ["m-new", "m-old"])
            self.assertEqual([row["id"] for row in repository.filtered_records("吃饭")], ["m-old"])
            repository.set_filter("交通")
            self.assertEqual([row["id"] for row in repository.filtered_records()], ["m-new"])
            self.assertEqual(repository.set_budget("4200"), 4200)
            self.assertEqual(repository.settings()["budget"], 4200)
            self.assertFalse(repository.settings()["budgetIsDefault"])
            with self.assertRaises(FinanceRepositoryError):
                repository.set_budget(-1)

    def test_add_budget_filter_and_unknown_legacy_state_survive_repository_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "restart.sqlite3"
            repository = FinanceRepository(
                database,
                _source(
                    [_record("other-module", "home", "2026-09-20", {"name": "保留"})],
                    {"futureSetting": {"nested": "kept"}},
                    futureStateField=[1, 2],
                ),
            )
            created = repository.add_record("expense", "25.40", "购物", "2026-09-27", "书")
            repository.set_budget(3000)
            repository.set_filter("购物")

            reopened = FinanceRepository(database)
            self.assertEqual(reopened.money_records()[0]["id"], created["id"])
            self.assertEqual(reopened.settings()["budget"], 3000)
            self.assertEqual(reopened.settings()["moneyFilter"], "购物")
            self.assertEqual(reopened.settings()["futureSetting"], {"nested": "kept"})
            self.assertEqual(
                [record["id"] for record in reopened.records()],
                ["other-module", created["id"]],
            )

    def test_month_previous_month_category_and_consumption_summaries(self) -> None:
        rows = [
            _record("breakfast", "money", "2026-09-02", {"flow": "expense", "amount": 100, "category": "吃饭", "note": "早餐"}),
            _record("travel", "money", "2026-09-25", {"flow": "expense", "amount": 20, "category": "交通", "note": "车票"}),
            _record("salary", "money", "2026-09-27", {"flow": "income", "amount": 500, "category": "工资", "note": ""}),
            _record("older", "money", "2026-08-05", {"flow": "expense", "amount": 90, "category": "吃饭", "note": ""}),
            _record("future", "money", "2026-10-01", {"flow": "expense", "amount": 500, "category": "购物", "note": ""}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = FinanceRepository(Path(directory) / "summary.sqlite3", _source(rows))
            stats = repository.summary("2026-09-27")
            self.assertEqual(stats["month"], "2026-09")
            self.assertEqual(stats["previousMonth"], "2026-08")
            self.assertEqual((stats["income"], stats["expense"], stats["balance"]), (500, 120, 380))
            self.assertEqual(stats["previousExpense"], 90)
            self.assertEqual(stats["expenseDifference"], 30)
            self.assertEqual(stats["expenseDifferencePercent"], 33)
            self.assertEqual(stats["budget"], 5000)
            self.assertEqual(stats["budgetUsedPercent"], 2)
            self.assertEqual(stats["budgetBarPercent"], 2)
            categories = repository.expense_categories("2026-09-27")
            self.assertEqual(categories[0]["category"], "吃饭")
            self.assertEqual(categories[0]["amount"], 100)
            self.assertAlmostEqual(sum(item["share"] for item in categories), 1.0)
            insight = repository.consumption_summary("2026-09-27")
            self.assertEqual(insight["elapsedDays"], 27)
            self.assertAlmostEqual(insight["dailyAverage"], 120 / 27)
            self.assertEqual(insight["topCategory"], {"category": "吃饭", "amount": 100})
            self.assertEqual(insight["largestExpense"]["id"], "breakfast")

    def test_alert_priority_is_over_budget_then_no_today_entry_then_backup(self) -> None:
        cases = [
            ([
                _record("over", "money", "2026-09-01", {"flow": "expense", "amount": 5001, "category": "房租", "note": ""}),
            ], 20, "over_budget"),
            ([
                _record("under", "money", "2026-09-01", {"flow": "expense", "amount": 1, "category": "吃饭", "note": ""}),
            ], 20, "no_today_record"),
            ([
                _record("today", "money", "2026-09-27", {"flow": "expense", "amount": 1, "category": "吃饭", "note": ""}),
            ], 20, "backup_reminder"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, (records, count, expected) in enumerate(cases):
                repo = FinanceRepository(
                    Path(directory) / f"alert-{index}.sqlite3",
                    _source(records, {"moneySinceExport": count}),
                )
                stats = repo.summary("2026-09-27")
                self.assertEqual(stats["alertReason"], expected)

    def test_imported_delete_is_a_tombstone_and_preserves_other_types_and_raw_source(self) -> None:
        old_rows = [
            _record("money-delete", "money", "2026-09-20", {"flow": "expense", "amount": 40, "category": "购物", "note": ""}, extraLegacy=True),
            _record("planner-stays", "planner", "2026-09-21", {"title": "保留待办"}),
            _record("fitness-stays", "fitness", "2026-09-22", {"weight": 70}),
        ]
        source_text = json.dumps(_source(old_rows, {"budget": 7000}), ensure_ascii=False, separators=(",", ":"))
        package = _package(_source(old_rows, {"budget": 7000}))
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "tombstone.sqlite3"
            import_package(package, database)
            repository = FinanceRepository(database)

            self.assertTrue(repository.delete_record("money-delete"))
            self.assertFalse(repository.delete_record("money-delete"))
            self.assertEqual(repository.money_records(), [])
            self.assertEqual(
                [row["id"] for row in repository.records()], ["planner-stays", "fitness-stays"]
            )
            self.assertEqual(repository.deleted_record_keys(), [{"type": "money", "id": "money-delete"}])
            reopened = FinanceRepository(database)
            self.assertEqual([row["id"] for row in reopened.records()], ["planner-stays", "fitness-stays"])
            with closing(sqlite3.connect(database)) as connection:
                raw = connection.execute(
                    "SELECT raw_value FROM legacy_storage WHERE storage_key='richangji-state-v1'"
                ).fetchone()[0]
                stored_base = connection.execute(
                    "SELECT COUNT(*) FROM records WHERE record_type='money'"
                ).fetchone()[0]
            self.assertEqual(raw, source_text)
            self.assertEqual(stored_base, 1)

    def test_late_import_adoption_keeps_local_records_and_tombstones(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = FinanceRepository(Path(directory) / "adopt.sqlite3")
            local = repository.add_record("expense", 2, "吃饭", "2026-09-27", "local", record_id="local-id")
            self.assertEqual(local["id"], "local-id")
            self.assertTrue(repository.adopt_imported_data(_source([
                _record("imported", "money", "2026-09-26", {"flow": "expense", "amount": 1, "category": "交通", "note": ""}),
                _record("another-module", "home", "2026-09-26", {"name": "书"}),
            ], {"budget": 9000, "futureSetting": True})))
            self.assertEqual({row["id"] for row in repository.money_records()}, {"local-id", "imported"})
            self.assertEqual(repository.settings()["budget"], 9000)
            self.assertTrue(repository.settings()["futureSetting"])
            self.assertFalse(repository.adopt_imported_data({"status": "empty"}))

    def test_excel_rows_and_backup_counter_reset(self) -> None:
        rows = [
            _record("old", "money", "2026-09-20", {"flow": "income", "amount": 8, "category": "奖金", "note": "奖金"}, sample=True),
            _record("fitness", "fitness", "2026-09-20", {"weight": 60}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = FinanceRepository(
                Path(directory) / "export.sqlite3",
                _source(rows, {"recordsSinceExport": 8, "moneySinceExport": 4}),
            )
            repository.add_record("expense", 3, "交通", "2026-09-27", "地铁")
            exported = repository.excel_export_data()
            self.assertEqual(exported["headers"], ["日期", "类型", "分类", "金额", "备注"])
            self.assertEqual(exported["rows"][0], ["2026-09-27", "支出", "交通", 3, "地铁"])
            self.assertEqual(exported["rows"][1], ["2026-09-20", "收入", "奖金", 8, "奖金"])
            english = repository.excel_export_data("en")
            self.assertEqual(english["rows"][1][1], "Income")
            repository.note_record_created("planner", 2)
            self.assertEqual(repository.summary("2026-09-27")["recordsSinceExport"], 11)
            self.assertEqual(repository.summary("2026-09-27")["moneySinceExport"], 5)
            state = repository.mark_backup_exported()
            self.assertEqual(state["recordsSinceExport"], 0)
            self.assertEqual(state["moneySinceExport"], 0)
            self.assertIsNotNone(state["lastExportAt"])
            repository.note_record_created("fitness")
            self.assertEqual(repository.summary("2026-09-27")["recordsSinceExport"], 1)
            self.assertEqual(repository.summary("2026-09-27")["moneySinceExport"], 0)

    def test_write_failure_rolls_back_database_and_in_memory_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "rollback.sqlite3"
            repository = FinanceRepository(database, _source(settings={"budget": 5000}))
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    """CREATE TRIGGER reject_finance_update BEFORE UPDATE ON finance_module_state
                    BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END"""
                )
            with self.assertRaises(FinanceRepositoryError):
                repository.set_budget(1234)
            self.assertEqual(repository.settings()["budget"], 5000)
            reopened = FinanceRepository(database)
            self.assertEqual(reopened.settings()["budget"], 5000)


if __name__ == "__main__":
    unittest.main()
