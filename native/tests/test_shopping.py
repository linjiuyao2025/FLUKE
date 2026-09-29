from __future__ import annotations

from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wanxiang.shopping import ShoppingRepository, ShoppingRepositoryError


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


class ShoppingRepositoryTests(unittest.TestCase):
    def test_source_envelope_and_unknown_fields_are_read_only(self) -> None:
        old = _record(
            "old-home", "home", "2026-09-20",
            {"name": "燕麦奶", "quantity": "2 盒", "category": "食品", "price": 18.5,
             "priority": "high", "note": "原装字段", "bought": False,
             "futureData": {"keep": True}},
            futureRecordField={"untouched": True},
        )
        source = _source(
            [old, _record("money", "money", "2026-09-20", {"future": "other module"})],
            {"shoppingFilter": "all", "futureSetting": {"keep": 9}},
            futureStateField="preserved",
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = ShoppingRepository(Path(directory) / "shopping.sqlite3", source)
            self.assertEqual(repository.legacy_records(), [old, source["records"][1]])
            self.assertEqual(repository.shopping_records("all")[0]["futureRecordField"], {"untouched": True})
            self.assertEqual(repository.shopping_records("all")[0]["data"]["futureData"], {"keep": True})
            self.assertEqual(repository.settings()["futureSetting"], {"keep": 9})

            repository.toggle_bought("old-home", True, bought_date="2026-09-27")
            effective = repository.shopping_records("all")[0]
            self.assertTrue(effective["data"]["bought"])
            self.assertEqual(effective["data"]["boughtDate"], "2026-09-27")
            self.assertEqual(repository.legacy_records()[0], old)

            repository = ShoppingRepository(Path(directory) / "shopping.sqlite3")
            reopened_bought = repository.shopping_records("all")[0]
            self.assertTrue(reopened_bought["data"]["bought"])
            self.assertEqual(reopened_bought["data"]["boughtDate"], "2026-09-27")

            repository.toggle_bought("old-home", False)
            effective = repository.shopping_records("all")[0]
            self.assertFalse(effective["data"]["bought"])
            self.assertNotIn("boughtDate", effective["data"])
            self.assertEqual(repository.legacy_records()[0], old)
            repository = ShoppingRepository(Path(directory) / "shopping.sqlite3")
            reopened_pending = repository.shopping_records("all")[0]
            self.assertFalse(reopened_pending["data"]["bought"])
            self.assertNotIn("boughtDate", reopened_pending["data"])

    def test_add_validation_filter_and_filter_persist_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "add.sqlite3"
            repository = ShoppingRepository(
                database, _source(settings={"shoppingFilter": "pending", "future": "kept"}),
                today_provider=lambda: date(2026, 9, 27),
            )
            local = repository.add_item(
                " 燕麦奶 ", "2 盒", "食品", "12.50", "high", "无糖", record_id="local-item",
                created_at=100,
            )
            self.assertEqual(local["data"], {
                "name": "燕麦奶", "quantity": "2 盒", "category": "食品", "price": 12.5,
                "priority": "high", "note": "无糖", "bought": False,
            })
            self.assertEqual(repository.current_filter(), "pending")
            self.assertEqual([row["id"] for row in repository.shopping_records()], ["local-item"])
            self.assertEqual(repository.set_filter("bought"), "bought")
            self.assertEqual(repository.shopping_records(), [])

            reopened = ShoppingRepository(database)
            self.assertEqual(reopened.current_filter(), "bought")
            self.assertEqual(reopened.settings()["future"], "kept")
            self.assertEqual(reopened.shopping_records("all")[0]["id"], "local-item")

            invalid = [
                ("", "1", "食品", 2, "normal", ""),
                ("n" * 41, "", "食品", 0, "normal", ""),
                ("x", "q" * 17, "食品", 0, "normal", ""),
                ("x", "", "unknown", 0, "normal", ""),
                ("x", "", "食品", -1, "normal", ""),
                ("x", "", "食品", 1.001, "normal", ""),
                ("x", "", "食品", 0, "urgent", ""),
                ("x", "", "食品", 0, "normal", "n" * 61),
            ]
            for args in invalid:
                with self.subTest(args=args), self.assertRaises(ShoppingRepositoryError):
                    repository.add_item(*args)
            with self.assertRaises(ShoppingRepositoryError):
                repository.set_filter("invalid")

    def test_summary_matches_local_date_month_fallback_and_seven_day_boundary(self) -> None:
        source = _source([
            _record("aged-eight", "home", "2026-09-19", {"name": "较早", "price": 10.25, "bought": False}),
            _record("aged-seven", "home", "2026-09-20", {"name": "第七天", "price": 2, "bought": False}),
            _record("aged-six", "home", "2026-09-21", {"name": "第六天", "price": 3, "bought": False}),
            _record("today", "home", "2026-09-27", {"name": "今天", "price": 4, "bought": False}),
            _record("future", "home", "2026-10-01", {"name": "未来日期", "price": 5, "bought": False}),
            _record("bought-date", "home", "2026-08-31", {"name": "本月购买", "bought": True, "boughtDate": "2026-09-02"}),
            _record("bought-fallback", "home", "2026-09-02", {"name": "日期回退", "bought": True}),
            _record("bought-last-month", "home", "2026-09-01", {"name": "上月购买", "bought": True, "boughtDate": "2026-08-31"}),
            _record("other", "money", "2026-09-26", {"amount": 9}),
        ])
        with tempfile.TemporaryDirectory() as directory:
            repository = ShoppingRepository(Path(directory) / "summary.sqlite3", source)
            summary = repository.summary("2026-09-27")
            self.assertEqual(summary["pendingCount"], 5)
            self.assertEqual(summary["pendingAmount"], 24.25)
            self.assertEqual(summary["purchasedThisMonthCount"], 2)
            self.assertEqual(summary["addedAtLeastSevenDaysCount"], 2)
            self.assertEqual(summary["earliestPending"], {
                "id": "aged-eight", "name": "较早", "date": "2026-09-19", "days": 8,
            })
            self.assertTrue({row["id"] for row in repository.shopping_records("pending")} >= {
                "aged-eight", "aged-seven", "aged-six", "today", "future",
            })
            self.assertEqual(len(repository.shopping_records("bought")), 3)

    def test_future_dated_items_do_not_appear_as_already_added(self) -> None:
        today = date(2026, 9, 27)
        future_only = _source([
            _record("future-one", "home", "2026-10-01", {"name": "未来物品", "bought": False}),
        ])
        mixed = _source([
            _record("old-item", "home", "2026-09-20", {"name": "已加入物品", "bought": False}),
            _record("future-item", "home", "2026-10-01", {"name": "未来计划", "bought": False}),
        ])
        with tempfile.TemporaryDirectory() as directory:
            future_repository = ShoppingRepository(
                Path(directory) / "future-only.sqlite3",
                future_only,
                today_provider=lambda: today,
            )
            self.assertIsNone(future_repository.summary()["earliestPending"])

            mixed_repository = ShoppingRepository(
                Path(directory) / "mixed.sqlite3",
                mixed,
                today_provider=lambda: today,
            )
            self.assertEqual(mixed_repository.summary()["earliestPending"], {
                "id": "old-item", "name": "已加入物品", "date": "2026-09-20", "days": 7,
            })

    def test_added_today_crosses_seven_days_at_local_midnight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ShoppingRepository(Path(directory) / "boundary.sqlite3", _source())
            repository.add_item("边界物品", day="2026-09-20", record_id="boundary")
            self.assertEqual(repository.summary("2026-09-26")["addedAtLeastSevenDaysCount"], 0)
            self.assertEqual(repository.summary("2026-09-27")["addedAtLeastSevenDaysCount"], 1)

    def test_legacy_delete_tombstone_local_delete_and_restart(self) -> None:
        source = _source([
            _record("old-home", "home", "2026-09-20", {"name": "旧版商品", "bought": False}),
        ])
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "delete.sqlite3"
            repository = ShoppingRepository(database, source)
            repository.toggle_bought("old-home", True, bought_date="2026-09-27")
            self.assertTrue(repository.delete_item("old-home"))
            self.assertEqual(repository.shopping_records("all"), [])
            self.assertEqual(repository.deleted_record_keys(), [{"type": "home", "id": "old-home"}])
            self.assertEqual(repository.legacy_records()[0], source["records"][0])

            repository.add_item("本地商品", record_id="local")
            self.assertTrue(repository.delete_item("local"))
            self.assertEqual(repository.deleted_record_keys(), [{"type": "home", "id": "old-home"}])
            self.assertEqual(repository.shopping_records("all"), [])

            reopened = ShoppingRepository(database)
            self.assertEqual(reopened.shopping_records("all"), [])
            self.assertEqual(reopened.deleted_record_keys(), [{"type": "home", "id": "old-home"}])

    def test_failed_sqlite_write_rolls_back_database_and_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "rollback.sqlite3"
            repository = ShoppingRepository(database, _source(settings={"shoppingFilter": "pending"}))
            with closing(sqlite3.connect(database)) as connection:
                connection.execute(
                    """CREATE TRIGGER reject_shopping_update BEFORE UPDATE ON shopping_module_state
                    BEGIN SELECT RAISE(ABORT, 'synthetic write failure'); END"""
                )
            with self.assertRaises(ShoppingRepositoryError):
                repository.set_filter("all")
            self.assertEqual(repository.current_filter(), "pending")
            self.assertEqual(ShoppingRepository(database).current_filter(), "pending")

    def test_late_import_after_empty_startup_keeps_local_records_and_filter_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "late-import.sqlite3"
            empty_snapshot = {
                "status": "empty", "hasData": False,
                "entities": {"records": [], "habits": [], "media_items": []},
                "documents": {},
            }
            repository = ShoppingRepository(database, empty_snapshot)
            repository.set_filter("bought")
            local = repository.add_item("本机先记", record_id="local-before-import")

            imported = _source(
                [
                    _record("legacy-home", "home", "2026-09-20", {
                        "name": "导入旧物品", "quantity": "1 件", "category": "家居",
                        "price": 25, "priority": "normal", "note": "旧备注", "bought": False,
                    }),
                    _record("legacy-money", "money", "2026-09-20", {"amount": 3}),
                ],
                {"shoppingFilter": "all", "newUnknownSetting": {"kept": True}},
            )
            self.assertTrue(repository.adopt_imported_data(imported))
            self.assertEqual(
                {item["id"] for item in repository.shopping_records("all")},
                {"legacy-home", local["id"]},
            )
            self.assertEqual(repository.current_filter(), "bought")
            self.assertEqual(repository.settings()["shoppingFilter"], "bought")
            self.assertEqual(repository.settings()["newUnknownSetting"], {"kept": True})
            self.assertFalse(repository.adopt_imported_data(empty_snapshot))

            reopened = ShoppingRepository(database)
            self.assertEqual(
                {item["id"] for item in reopened.shopping_records("all")},
                {"legacy-home", local["id"]},
            )
            self.assertEqual(reopened.current_filter(), "bought")

    def test_late_import_preserves_tombstones_unknown_settings_and_unoverridden_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ShoppingRepository(
                Path(directory) / "overlay-import.sqlite3",
                _source(
                    [_record("deleted-later", "home", "2026-09-10", {"name": "已删除"})],
                    {"shoppingFilter": "pending", "legacyUnknown": {"old": 1}},
                ),
            )
            repository.delete_item("deleted-later")
            repository.add_item("本机保留", record_id="local-kept")
            self.assertTrue(repository.adopt_imported_data(_source(
                [
                    _record("deleted-later", "home", "2026-09-10", {"name": "新版源中的旧项"}),
                    _record("new-home", "home", "2026-09-25", {"name": "新导入"}),
                ],
                {"shoppingFilter": "all", "newUnknown": "preserved"},
            )))
            self.assertEqual(
                {item["id"] for item in repository.shopping_records("all")},
                {"new-home", "local-kept"},
            )
            self.assertEqual(repository.deleted_record_keys(), [
                {"type": "home", "id": "deleted-later"},
            ])
            self.assertEqual(repository.current_filter(), "all")
            self.assertEqual(repository.settings()["legacyUnknown"], {"old": 1})
            self.assertEqual(repository.settings()["newUnknown"], "preserved")


if __name__ == "__main__":
    unittest.main()
