from __future__ import annotations

from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wanxiang.archive import (
    ARCHIVE_FILTERS,
    ArchiveRepository,
    ArchiveRepositoryError,
)


def _record(
    record_id: str,
    kind: str,
    day: str,
    data: dict[str, object] | None = None,
    *,
    created_at: int = 10,
    **extra: object,
) -> dict[str, object]:
    return {
        "id": record_id,
        "type": kind,
        "date": day,
        "createdAt": created_at,
        "sample": False,
        "data": data or {},
        **extra,
    }


def _source(records: list[dict[str, object]] | None = None,
            settings: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "version": 2,
        "records": records or [],
        "mediaItems": [{"id": "separate-media", "name": "书影音不属于 records"}],
        "settings": settings or {},
    }


class ArchiveRepositoryTests(unittest.TestCase):
    def test_saved_filter_survives_reopen_and_records_are_never_persisted(self) -> None:
        rows = [_record("private", "money", "2026-09-27", {"note": "private archive text"})]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "archive.sqlite3"
            repository = ArchiveRepository(database, _source(rows, {"archiveFilter": "money"}))
            self.assertEqual(repository.current_filter(), "money")
            self.assertEqual(repository.set_filter("fitness"), "fitness")

            reopened = ArchiveRepository(database, _source())
            self.assertEqual(reopened.current_filter(), "fitness")
            with closing(sqlite3.connect(database)) as connection:
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                stored = connection.execute(
                    "SELECT state_json FROM archive_module_state WHERE singleton=1"
                ).fetchone()[0]
            self.assertEqual(tables, {"archive_module_state"})
            self.assertNotIn("private archive text", stored)
            self.assertNotIn("private", stored)

    def test_filter_grouping_order_and_media_are_excluded(self) -> None:
        rows = [
            _record("money-old", "money", "2026-09-26", {"flow": "expense"}, created_at=10),
            _record("fitness", "fitness", "2026-09-27", {"weight": 62}, created_at=20),
            _record("money-new", "money", "2026-09-27", {"flow": "income"}, created_at=30),
            _record("planner", "planner", "2026-09-27", {"title": "安排"}, created_at=25),
            _record("home", "home", "2026-09-25", {"name": "清单项"}),
            _record("media-record", "media", "2026-09-27", {"name": "不显示"}),
        ]
        original = json.loads(json.dumps(rows, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as directory:
            repository = ArchiveRepository(Path(directory) / "archive.sqlite3", _source())
            state = repository.state(rows, today="2026-09-27")

        self.assertEqual(rows, original)
        self.assertEqual([group["date"] for group in state["groups"]],
                         ["2026-09-27", "2026-09-26", "2026-09-25"])
        self.assertEqual([item["id"] for item in state["groups"][0]["records"]],
                         ["money-new", "planner", "fitness"])
        self.assertNotIn("media-record", json.dumps(state, ensure_ascii=False))
        money = ArchiveRepository.filter_records(rows, "money")
        self.assertEqual([item["id"] for item in money], ["money-new", "money-old"])

    def test_month_summary_counts_types_dates_and_rolling_seven_days(self) -> None:
        rows = [
            _record("aug-boundary", "money", "2026-08-31"),
            _record("today-a", "planner", "2026-09-27", created_at=20),
            _record("today-b", "money", "2026-09-27", created_at=10),
            _record("last-week", "home", "2026-09-22"),
            _record("outside-seven", "fitness", "2026-09-18"),
            _record("media", "media", "2026-09-27"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = ArchiveRepository(Path(directory) / "archive.sqlite3", _source())
            summary = repository.monthly_summary(rows, today=date(2026, 9, 27))

        self.assertEqual(summary["month"], "2026-09")
        self.assertEqual(summary["recordCount"], 4)
        self.assertEqual(summary["dateCount"], 3)
        # Tied types use the first appearance in newest-first archive ordering.
        self.assertEqual(summary["favoriteType"], "planner")
        self.assertEqual(summary["favoriteCount"], 1)
        self.assertEqual(summary["recentSevenDayCount"], 3)
        self.assertEqual(summary["maxRecentDayCount"], 2)
        self.assertEqual(summary["recentDays"][-1], {"date": "2026-09-27", "count": 2})
        self.assertEqual(summary["typeCounts"], {"planner": 1, "money": 1, "home": 1, "fitness": 1})

    def test_state_summary_uses_the_same_filter_scope_as_visible_groups(self) -> None:
        rows = [
            _record("money", "money", "2026-09-27"),
            _record("planner", "planner", "2026-09-27"),
            _record("fitness", "fitness", "2026-09-26"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            repository = ArchiveRepository(Path(directory) / "archive.sqlite3", _source())
            repository.set_filter("money")
            state = repository.state(rows, today="2026-09-27")

        self.assertEqual(state["recordCount"], 1)
        self.assertEqual(sum(group["count"] for group in state["groups"]), 1)
        self.assertEqual(state["summary"]["recordCount"], 1)
        self.assertEqual(state["summary"]["typeCounts"], {"money": 1})
        self.assertEqual(state["summary"]["recentSevenDayCount"], 1)

    def test_filters_are_validated_and_filter_is_saved_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ArchiveRepository(Path(directory) / "archive.sqlite3", _source())
            for selected in ARCHIVE_FILTERS:
                self.assertEqual(repository.set_filter(selected), selected)
            with self.assertRaises(ArchiveRepositoryError):
                repository.set_filter("media")
            with self.assertRaises(ArchiveRepositoryError):
                repository.state({"records": []})

    def test_later_import_adopts_only_archive_filter_and_local_choice_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ArchiveRepository(Path(directory) / "archive.sqlite3", _source())
            imported = _source(
                [_record("must-not-be-copied", "money", "2026-09-27", {"note": "record"})],
                {"archiveFilter": "home", "secretFutureSetting": "leave elsewhere"},
            )
            self.assertTrue(repository.adopt_imported_data(imported))
            self.assertEqual(repository.current_filter(), "home")
            self.assertEqual(repository.state([], today="2026-09-27")["recordCount"], 0)
            repository.set_filter("planner")
            self.assertTrue(repository.adopt_imported_data(_source(settings={"archiveFilter": "money"})))
            self.assertEqual(repository.current_filter(), "planner")

            with closing(sqlite3.connect(Path(directory) / "archive.sqlite3")) as connection:
                stored = connection.execute(
                    "SELECT state_json FROM archive_module_state WHERE singleton=1"
                ).fetchone()[0]
            self.assertNotIn("must-not-be-copied", stored)
            self.assertNotIn("secretFutureSetting", stored)

    def test_invalid_archive_record_shape_fails_clearly_and_bad_date_is_grouped_last(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ArchiveRepository(Path(directory) / "archive.sqlite3", _source())
            with self.assertRaisesRegex(ArchiveRepositoryError, "对象数组"):
                repository.state("not a records array")
            state = repository.state([
                _record("undated", "home", "not-a-date"),
                _record("dated", "home", "2026-09-27"),
            ], today="2026-09-27")
        self.assertEqual([group["date"] for group in state["groups"]], ["2026-09-27", "未标日期"])
        self.assertEqual(state["summary"]["recordCount"], 1)


if __name__ == "__main__":
    unittest.main()
