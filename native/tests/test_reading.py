from __future__ import annotations

from copy import deepcopy
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from wanxiang.reading import (
    LEGACY_CLIPPINGS_KEY,
    LEGACY_SAVED_KNOWLEDGE_KEY,
    MAX_CLIPPINGS,
    ReadingRepository,
    ReadingRepositoryError,
)


def _article(article_id: str, *, image: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "id": article_id,
        "group": "articles",
        "label": "合成主题",
        "title": f"合成报道 {article_id}",
        "summary": "仅供本地仓储测试。",
        "publisher": "合成来源",
        "publishedAt": "2026-09-27",
        "sourceUrl": f"https://news.example.org/{article_id}",
        "futureArticleField": {"retained": True},
        "image": image,
    }


def _clip(article_id: str, *, key: str | None = None) -> dict[str, object]:
    return {
        "key": key or f"2026-09-27::{article_id}",
        "date": "2026-09-27",
        "topic": "合成主题",
        "item": _article(article_id),
        "savedAt": 1790467200000,
        "futureClipField": "retained",
    }


class ReadingRepositoryTests(unittest.TestCase):
    def test_adapts_read_only_migration_snapshot_and_keeps_global_saved_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "reading.sqlite3"
            clippings = [_clip("imported")]
            source = {
                "status": "loaded",
                "raw_values": {
                    LEGACY_SAVED_KNOWLEDGE_KEY: "1",
                    LEGACY_CLIPPINGS_KEY: json.dumps(clippings, ensure_ascii=False),
                },
                "documents": {LEGACY_CLIPPINGS_KEY: clippings},
                "summary": {"clippings": 1},
            }
            original = deepcopy(source)

            repository = ReadingRepository(database_path, source)

            self.assertTrue(repository.saved_knowledge())
            self.assertEqual(repository.snapshot()["clippings"], clippings)
            self.assertEqual(source, original)
            self.assertEqual(ReadingRepository(database_path).snapshot(), repository.snapshot())

    def test_saved_knowledge_matches_legacy_exact_string_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for index, raw_value in enumerate(("1", "0", "true", True, None)):
                with self.subTest(raw_value=raw_value):
                    repository = ReadingRepository(
                        Path(directory) / f"saved-{index}.sqlite3",
                        {"raw_values": {LEGACY_SAVED_KNOWLEDGE_KEY: raw_value}},
                    )
                    self.assertEqual(repository.saved_knowledge(), raw_value == "1")

    def test_global_saved_knowledge_toggle_persists_without_story_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "global-flag.sqlite3"
            repository = ReadingRepository(
                database_path,
                {"raw_values": {LEGACY_SAVED_KNOWLEDGE_KEY: "1"}},
            )

            self.assertFalse(repository.toggle_saved_knowledge())
            self.assertEqual(repository.snapshot(), {"savedKnowledge": False, "clippings": []})
            self.assertTrue(ReadingRepository(database_path).toggle_saved_knowledge())
            self.assertTrue(ReadingRepository(database_path).saved_knowledge())

    def test_latest_clippings_are_first_and_capped_at_eighty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "capacity.sqlite3"
            legacy_clippings = [_clip(f"old-{index}") for index in range(82)]
            legacy_clippings[0]["futureEnvelopeField"] = {"preserve": 1}
            legacy_clippings[0]["item"]["sourceTitle"] = "旧版未知来源字段"
            original = deepcopy(legacy_clippings)
            repository = ReadingRepository(
                database_path,
                {"documents": {LEGACY_CLIPPINGS_KEY: legacy_clippings}},
            )

            self.assertEqual(len(repository.clippings()), MAX_CLIPPINGS)
            self.assertEqual(repository.clippings()[0]["key"], "2026-09-27::old-0")
            self.assertEqual(
                repository.clippings()[0]["futureEnvelopeField"], {"preserve": 1}
            )
            self.assertEqual(
                repository.clippings()[0]["item"]["sourceTitle"], "旧版未知来源字段"
            )

            incoming = _article(
                "newest",
                image={"src": "data:image/png;base64,synthetic", "caption": "本地图"},
            )
            self.assertTrue(repository.save_clipping(incoming, "2026-09-28", "新主题", 7))
            rows = repository.clippings()
            self.assertEqual(len(rows), MAX_CLIPPINGS)
            self.assertEqual(rows[0]["key"], "2026-09-28::newest")
            self.assertIsNone(rows[0]["item"]["image"])
            self.assertNotIn("2026-09-27::old-79", [row["key"] for row in rows])
            self.assertEqual(incoming["image"]["src"], "data:image/png;base64,synthetic")
            self.assertEqual(legacy_clippings, original)

    def test_save_deduplicates_and_article_button_toggles_only_first_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "toggle.sqlite3"
            repository = ReadingRepository(database_path)
            article = _article("toggle")

            self.assertTrue(repository.save_clipping(article, "2026-09-27", saved_at=1))
            self.assertFalse(repository.save_clipping(article, "2026-09-27", saved_at=2))
            self.assertEqual(len(repository.clippings()), 1)
            self.assertTrue(repository.is_clipped("toggle", "2026-09-27"))

            # The old article button is a toggle. The old clipping list remove
            # path below is separate and removes every row matching its key.
            self.assertFalse(repository.toggle_clipping(article, "2026-09-27"))
            self.assertFalse(repository.clippings())
            self.assertTrue(repository.toggle_clipping(article, "2026-09-27", saved_at=3))
            self.assertEqual(
                ReadingRepository(database_path).clippings()[0]["savedAt"], 3
            )

    def test_list_remove_clears_duplicate_legacy_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            duplicate_rows = [_clip("duplicate"), _clip("duplicate")]
            repository = ReadingRepository(
                Path(directory) / "duplicates.sqlite3",
                {"documents": {LEGACY_CLIPPINGS_KEY: duplicate_rows}},
            )

            removed = repository.remove_clipping("2026-09-27::duplicate")

            self.assertEqual(removed, 2)
            self.assertEqual(repository.clippings(), [])

    def test_late_import_adopts_untouched_fields_and_preserves_locally_toggled_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "late-import.sqlite3"
            repository = ReadingRepository(
                database_path,
                {"raw_values": {LEGACY_SAVED_KNOWLEDGE_KEY: "1"}},
            )
            repository.toggle_saved_knowledge()
            source = {
                "raw_values": {
                    LEGACY_SAVED_KNOWLEDGE_KEY: "1",
                    LEGACY_CLIPPINGS_KEY: json.dumps([_clip("late-a"), _clip("late-b")]),
                },
                "documents": {
                    LEGACY_CLIPPINGS_KEY: [_clip("late-a"), _clip("late-b")]
                },
            }
            original = deepcopy(source)

            adopted = repository.adopt_imported_data(source)

            self.assertFalse(adopted["savedKnowledge"])
            self.assertEqual([item["item"]["id"] for item in adopted["clippings"]], ["late-a", "late-b"])
            self.assertEqual(source, original)
            self.assertEqual(ReadingRepository(database_path).snapshot(), adopted)

    def test_late_import_does_not_replace_a_locally_edited_clipping_collection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "local-clippings.sqlite3"
            repository = ReadingRepository(database_path)
            repository.save_clipping(_article("local"), "2026-09-27", saved_at=1)
            incoming = {
                "documents": {
                    LEGACY_CLIPPINGS_KEY: [_clip("imported")]
                }
            }

            adopted = repository.adopt_imported_data(incoming)

            self.assertEqual([item["item"]["id"] for item in adopted["clippings"]], ["local"])

    def test_existing_v1_reading_table_is_upgraded_without_dropping_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "old-schema.sqlite3"
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    "CREATE TABLE reading_module_state ("
                    "singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                    "saved_knowledge INTEGER NOT NULL CHECK(saved_knowledge IN (0,1)), "
                    "clippings_json TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO reading_module_state VALUES (1, 1, ?)",
                    (json.dumps([_clip("existing")], ensure_ascii=False),),
                )
                connection.commit()

            repository = ReadingRepository(database_path)

            self.assertTrue(repository.saved_knowledge())
            self.assertEqual(repository.clippings()[0]["item"]["id"], "existing")
            self.assertFalse(repository.toggle_saved_knowledge())
            self.assertFalse(ReadingRepository(database_path).saved_knowledge())

    def test_transaction_failure_keeps_database_and_memory_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "rollback.sqlite3"
            repository = ReadingRepository(database_path)
            before = repository.snapshot()
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    """
                    CREATE TRIGGER reject_reading_update
                    BEFORE UPDATE ON reading_module_state
                    BEGIN
                        SELECT RAISE(ABORT, 'synthetic write failure');
                    END
                    """
                )
                connection.commit()

            with self.assertRaises(ReadingRepositoryError):
                repository.save_clipping(_article("rollback"), "2026-09-27", saved_at=4)

            self.assertEqual(repository.snapshot(), before)
            self.assertEqual(ReadingRepository(database_path).snapshot(), before)

    def test_rejects_invalid_mutations_without_partial_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ReadingRepository(Path(directory) / "validation.sqlite3")
            before = repository.snapshot()

            with self.assertRaises(ReadingRepositoryError):
                repository.set_saved_knowledge(1)  # type: ignore[arg-type]
            with self.assertRaises(ReadingRepositoryError):
                repository.save_clipping(_article("invalid"), "bad-date")
            with self.assertRaises(ReadingRepositoryError):
                repository.save_clipping({"id": "missing-title"}, "2026-09-27")

            self.assertEqual(repository.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
