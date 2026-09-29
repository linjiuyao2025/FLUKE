from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wanxiang.database import import_package, load_imported_data
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)
from wanxiang.preferences import (
    LEGACY_PREFERENCES_KEY,
    LEGACY_TOPICS_KEY,
    IssuePreferencesRepository,
    PreferencesRepositoryError,
)


def _migration_package(
    topics: list[str] | None = None,
    preferences: dict[str, object] | None = None,
):
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    if topics is not None:
        raw_values[LEGACY_TOPICS_KEY] = json.dumps(
            topics, ensure_ascii=False, separators=(",", ":")
        )
    if preferences is not None:
        raw_values[LEGACY_PREFERENCES_KEY] = json.dumps(
            preferences, ensure_ascii=False, separators=(",", ":")
        )
    return validate_package(
        {
            "format": PACKAGE_FORMAT,
            "schemaVersion": PACKAGE_SCHEMA_VERSION,
            "sourceVersion": "synthetic-preferences-test",
            "exportedAt": "2026-09-27T10:00:00Z",
            "keys": raw_values,
            "checksum": calculate_checksum(raw_values),
        }
    )


class IssuePreferencesRepositoryTests(unittest.TestCase):
    def test_empty_database_has_old_empty_defaults_and_reopens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.sqlite3"
            repository = IssuePreferencesRepository(path)

            self.assertEqual(
                repository.get(),
                {
                    "topics": [],
                    "preferences": {
                        "subtopics": "",
                        "sources": "",
                        "presetSources": [],
                    },
                },
            )
            reopened = IssuePreferencesRepository(path)
            self.assertEqual(reopened.get(), repository.get())

    def test_imported_legacy_values_normalize_to_the_old_rendered_form(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            imported = {
                "raw_values": {
                    LEGACY_TOPICS_KEY: json.dumps(
                        ["ai", "finance", "ai", "future-topic", " "]
                    ),
                    LEGACY_PREFERENCES_KEY: json.dumps(
                        {
                            "subtopics": "  AI Agent、独立游戏  ",
                            "sources": "Reuters, Nature；Reuters; ProPublica",
                            "presetSources": ["财新网", "旧版站点", "Nature"],
                        }
                    ),
                }
            }
            repository = IssuePreferencesRepository(path, imported)

            self.assertEqual(
                repository.get(),
                {
                    "topics": ["ai", "finance", "future-topic"],
                    "preferences": {
                        "subtopics": "AI Agent、独立游戏",
                        "sources": "Reuters、Nature、ProPublica、旧版站点",
                        "presetSources": ["财新网", "Nature"],
                    },
                },
            )

    def test_unknown_preset_source_is_capped_when_moved_to_custom_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            long_source = "媒体" * 80
            repository = IssuePreferencesRepository(
                Path(directory) / "legacy.sqlite3",
                {"topics": [], "preferences": {"presetSources": [long_source]}},
            )
            self.assertEqual(repository.get()["preferences"]["sources"], long_source[:60])
            self.assertEqual(repository.get()["preferences"]["presetSources"], [])

    def test_real_migration_import_keeps_original_storage_rows_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "migration.sqlite3"
            package = _migration_package(
                ["technology", "ai"],
                {
                    "subtopics": "AI Agent",
                    "sources": "Reuters、Nature",
                    "presetSources": ["ProPublica"],
                },
            )
            import_package(package, path)
            before = load_imported_data(path)
            original_checksum = before["import_info"]["checksum_sha256"]
            original_values = dict(before["raw_values"])

            repository = IssuePreferencesRepository(path)
            repository.save(["games"], {"subtopics": "独立游戏", "sources": "Game Dev"})
            after = load_imported_data(path)

            self.assertEqual(after["raw_values"], original_values)
            self.assertEqual(after["import_info"]["checksum_sha256"], original_checksum)
            self.assertEqual(
                repository.get(),
                {
                    "topics": ["games"],
                    "preferences": {
                        "subtopics": "独立游戏",
                        "sources": "Game Dev",
                        "presetSources": [],
                    },
                },
            )
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM issue_preferences_state"
                    ).fetchone()[0],
                    1,
                )

    def test_save_canonicalizes_and_survives_process_style_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.sqlite3"
            repository = IssuePreferencesRepository(path)
            saved = repository.save(
                ["ai", "ai", "technology"],
                {
                    "subtopics": "  AI Agent  ",
                    "sources": "Nature, Reuters；Nature",
                    "presetSources": ["Nature", "Reuters", "Nature"],
                },
            )

            self.assertEqual(saved["topics"], ["ai", "technology"])
            self.assertEqual(
                saved["preferences"],
                {
                    "subtopics": "AI Agent",
                    "sources": "Nature、Reuters",
                    "presetSources": ["Nature", "Reuters"],
                },
            )
            self.assertEqual(IssuePreferencesRepository(path).get(), saved)

    def test_late_import_is_adopted_until_a_native_save_occurs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.sqlite3"
            repository = IssuePreferencesRepository(path)
            incoming = {"topics": ["finance"], "preferences": {"subtopics": "rates"}}
            self.assertEqual(repository.adopt_imported_data(incoming)["topics"], ["finance"])

            repository.save(["games"], {"subtopics": "indie"})
            later = {"topics": ["domestic"], "preferences": {"subtopics": "policy"}}
            self.assertEqual(repository.adopt_imported_data(later)["topics"], ["games"])
            self.assertEqual(IssuePreferencesRepository(path).get()["topics"], ["games"])

    def test_invalid_save_does_not_change_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.sqlite3"
            repository = IssuePreferencesRepository(path)
            repository.save(["ai"], {"subtopics": "agents"})
            before = repository.get()

            with self.assertRaises(PreferencesRepositoryError):
                repository.save(["news", 5], {"sources": "Reuters"})
            self.assertEqual(repository.get(), before)
            self.assertEqual(IssuePreferencesRepository(path).get(), before)

    def test_sqlite_failure_rolls_back_without_changing_cached_or_saved_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.sqlite3"
            repository = IssuePreferencesRepository(path)
            repository.save(["ai"], {"subtopics": "agents"})
            before = repository.get()
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    """CREATE TRIGGER reject_preferences_update
                    BEFORE UPDATE ON issue_preferences_state
                    BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"""
                )
                connection.commit()

            with self.assertRaises(PreferencesRepositoryError):
                repository.save(["games"], {"subtopics": "indie"})
            self.assertEqual(repository.get(), before)
            self.assertEqual(IssuePreferencesRepository(path).get(), before)


if __name__ == "__main__":
    unittest.main()
