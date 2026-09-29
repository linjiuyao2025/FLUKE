from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from wanxiang.database import (
    SCHEMA_STATEMENTS,
    SCHEMA_VERSION,
    get_app_setting,
    import_package,
    load_imported_data,
    preview_import,
    set_app_setting,
    set_app_settings,
)
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _synthetic_package():
    documents: dict[str, object] = {
        "richangji-state-v1": {
            "records": [
                {
                    "id": "synthetic-record",
                    "type": "money",
                    "date": "2026-09-27",
                    "data": {"amount": 3},
                }
            ],
            "habits": [{"id": "synthetic-habit", "key": "walk"}],
            "mediaItems": [{"id": "synthetic-media", "name": "synthetic"}],
        },
        "wanxiang-paper-layout-v2": {"order": ["synthetic"]},
        "wanxiang-daily-issues-v1": {"active": None, "archive": []},
        "wanxiang-issue-questions-v1": [{"text": "synthetic"}],
        "wanxiang-issue-topics-v1": ["synthetic"],
        "wanxiang-issue-preferences-v1": {
            "subtopics": "synthetic",
            "sources": "Synthetic source",
            "presetSources": [],
        },
        "wanxiang-issue-clippings-v1": [
            {
                "key": "2026-09-27::synthetic-article",
                "date": "2026-09-27",
                "item": {"id": "synthetic-article", "title": "Synthetic article"},
            }
        ],
    }
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    for key, value in documents.items():
        raw_values[key] = json.dumps(
            value, ensure_ascii=False, separators=(",", ":")
        )
    raw_values["richangji-samples-cleared"] = "1"
    raw_values["wanxiang-saved-knowledge"] = "0"
    return validate_package(
        {
            "format": PACKAGE_FORMAT,
            "schemaVersion": PACKAGE_SCHEMA_VERSION,
            "sourceVersion": "synthetic-test",
            "exportedAt": "2026-09-27T00:00:00.000Z",
            "keys": raw_values,
            "checksum": calculate_checksum(raw_values),
        }
    )


class DatabaseReadTests(unittest.TestCase):
    def _tamper_and_assert_fail_closed(
        self, statement: str, parameters: tuple[object, ...]
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "tampered.sqlite3"
            package = _synthetic_package()
            import_package(package, database_path)

            with closing(sqlite3.connect(database_path)) as connection:
                cursor = connection.execute(statement, parameters)
                self.assertEqual(cursor.rowcount, 1, "the synthetic tamper must affect one row")
                connection.commit()

            before = hashlib.sha256(database_path.read_bytes()).hexdigest()
            loaded = load_imported_data(database_path)
            self.assertEqual(loaded["status"], "unavailable")
            with self.assertRaises(RuntimeError):
                preview_import(package, database_path)
            after = hashlib.sha256(database_path.read_bytes()).hexdigest()
            self.assertEqual(before, after, "integrity checks must remain read-only")

    def test_tampered_raw_storage_value_fails_closed(self) -> None:
        package = _synthetic_package()
        self._tamper_and_assert_fail_closed(
            "UPDATE legacy_storage SET raw_value=? WHERE batch_id=? AND storage_key=?",
            ('["tampered"]', package.checksum, "wanxiang-issue-topics-v1"),
        )

    def test_tampered_parsed_document_fails_closed(self) -> None:
        package = _synthetic_package()
        self._tamper_and_assert_fail_closed(
            "UPDATE json_documents SET document_json=? WHERE batch_id=? AND document_key=?",
            ('{"order":["tampered"]}', package.checksum, "wanxiang-paper-layout-v2"),
        )

    def test_tampered_entity_payload_fails_closed(self) -> None:
        package = _synthetic_package()
        self._tamper_and_assert_fail_closed(
            "UPDATE records SET payload_json=? WHERE batch_id=? AND position=?",
            (
                '{"data":{"amount":4},"date":"2026-09-27",'
                '"id":"synthetic-record","type":"money"}',
                package.checksum,
                0,
            ),
        )

    def test_missing_storage_key_row_fails_closed(self) -> None:
        package = _synthetic_package()
        self._tamper_and_assert_fail_closed(
            "DELETE FROM legacy_storage WHERE batch_id=? AND storage_key=?",
            (package.checksum, "wanxiang-saved-knowledge"),
        )

    def test_loaded_data_survives_reopen_and_reads_do_not_change_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "synthetic.sqlite3"
            package = _synthetic_package()
            import_package(package, database_path)

            # Read-only snapshot loading must not depend on app_settings existing.
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute("DROP TABLE app_settings")
                connection.commit()

            before = hashlib.sha256(database_path.read_bytes()).hexdigest()
            first = load_imported_data(database_path)
            second = load_imported_data(database_path)
            after = hashlib.sha256(database_path.read_bytes()).hexdigest()

            self.assertEqual(first["status"], "loaded")
            self.assertTrue(first["hasData"])
            self.assertEqual(first["summary"]["keys_total"], len(package.raw_values))
            self.assertEqual(
                first["summary"]["keys_present"],
                sum(value is not None for value in package.raw_values.values()),
            )
            self.assertEqual(first["summary"]["records"], 1)
            self.assertEqual(first["summary"]["habits"], 1)
            self.assertEqual(first["summary"]["media_items"], 1)
            self.assertEqual(len(first["raw_values"]), len(package.raw_values))
            self.assertEqual(len(first["documents"]), 7)
            self.assertEqual(len(first["entities"]["records"]), 1)
            self.assertEqual(len(first["entities"]["habits"]), 1)
            self.assertEqual(len(first["entities"]["media_items"]), 1)
            self.assertTrue(
                first["raw_values"] == package.raw_values
                and second["raw_values"] == package.raw_values
            )
            self.assertEqual(first["summary"], second["summary"])
            self.assertEqual(before, after)

    def test_missing_database_returns_stable_empty_shape_without_creating_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "not-created.sqlite3"
            result = load_imported_data(database_path)

            self.assertFalse(database_path.exists())
            self.assertEqual(result["status"], "empty")
            self.assertFalse(result["hasData"])
            self.assertEqual(set(result["raw_values"]), set(STORAGE_KEYS))
            self.assertTrue(all(value is None for value in result["raw_values"].values()))
            self.assertEqual(result["documents"], {})
            self.assertTrue(all(not items for items in result["entities"].values()))
            self.assertEqual(result["summary"]["keys_total"], len(STORAGE_KEYS))

    def test_app_settings_round_trip_default_and_schema_addition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "settings.sqlite3"

            self.assertEqual(get_app_setting(database_path, "city", "default"), "default")
            set_app_setting(database_path, "city", {"name": "synthetic", "units": [1, 2]})
            self.assertEqual(
                get_app_setting(database_path, "city", "default"),
                {"name": "synthetic", "units": [1, 2]},
            )
            set_app_setting(database_path, "city", "updated")
            self.assertEqual(get_app_setting(database_path, "city"), "updated")
            self.assertEqual(SCHEMA_VERSION, 2)
            self.assertIn("app_settings", SCHEMA_STATEMENTS[-1])

    def test_app_settings_reject_non_json_values_before_database_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "invalid-setting.sqlite3"
            with self.assertRaises((TypeError, ValueError)):
                set_app_setting(database_path, "bad", float("nan"))
            self.assertFalse(database_path.exists())

    def test_app_settings_group_commits_together_and_invalid_value_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "settings-group.sqlite3"
            set_app_settings(database_path, {"city": "合成市", "location": {"latitude": 1.2}})
            self.assertEqual(get_app_setting(database_path, "city"), "合成市")
            self.assertEqual(get_app_setting(database_path, "location"), {"latitude": 1.2})

            with self.assertRaises(ValueError):
                set_app_settings(database_path, {"city": "另一个合成市", "invalid": float("nan")})
            self.assertEqual(get_app_setting(database_path, "city"), "合成市")
            self.assertIsNone(get_app_setting(database_path, "invalid"))


if __name__ == "__main__":
    unittest.main()
