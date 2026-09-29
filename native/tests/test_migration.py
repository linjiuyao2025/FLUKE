from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from PySide6.QtCore import QUrl

from main import MigrationBridge
from wanxiang.database import (
    import_package,
    initialize_schema,
    load_imported_data,
    preview_import,
)
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    STORAGE_KEYS_V1,
    MigrationPackageError,
    calculate_checksum,
    validate_package,
)


def _raw(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _synthetic_article(article_id: str, title: str) -> dict[str, object]:
    return {
        "id": article_id,
        "label": "合成栏目",
        "title": title,
        "summary": "用于迁移验证的合成摘要。",
        "body": ["用于迁移验证的合成正文。"],
        "publisher": "合成来源",
        "publishedAt": "2026-09-20T08:00:00Z",
        "sourceUrl": f"https://example.test/{article_id}",
    }


def _synthetic_issue(date: str, topic: str, suffix: str) -> dict[str, object]:
    return {
        "version": 1,
        "date": date,
        "topic": topic,
        "focus": [_synthetic_article(f"{suffix}-focus", "合成焦点")],
        "highlights": [_synthetic_article(f"{suffix}-highlight", "合成快讯")],
        "articles": [],
    }


def synthetic_payload() -> dict[str, object]:
    keys = {
        "richangji-state-v1": _raw(
            {
                "version": 2,
                "records": [
                    {
                        "id": "record-1",
                        "type": "money",
                        "date": "2026-09-20",
                        "createdAt": 42,
                        "sample": False,
                        "data": {"flow": "expense", "amount": 32, "note": "合成记录"},
                    }
                ],
                "habits": [
                    {
                        "id": "habit-reading",
                        "key": "reading",
                        "entries": {"2026-09-20": 1},
                    }
                ],
                "mediaItems": [
                    {
                        "id": "media-1",
                        "name": "合成书目",
                        "type": "书",
                        "status": "想看",
                        "date": "2026-09-20",
                    }
                ],
                "drafts": {},
                "settings": {"budget": 5000},
            }
        ),
        "richangji-samples-cleared": "1",
        "wanxiang-paper-layout-v2": _raw(
            {"order": ["weather", "news"], "slots": {}, "hidden": []}
        ),
        "wanxiang-daily-issues-v1": _raw(
            {
                "active": _synthetic_issue("2026-09-20", "合成主题", "active"),
                "archive": [
                    {
                        "issue": _synthetic_issue("2026-09-19", "合成历史刊", "archive"),
                        "publishedAt": "2026-09-19T12:00:00.000Z",
                    }
                ],
            }
        ),
        "wanxiang-issue-questions-v1": _raw([{"text": "合成问题"}]),
        "wanxiang-issue-topics-v1": _raw(["technology"]),
        "wanxiang-issue-preferences-v1": _raw({"媒体甲": True}),
        "wanxiang-issue-clippings-v1": _raw(
            [
                {
                    "key": "2026-09-20::story-1",
                    "date": "2026-09-20",
                    "topic": "合成主题",
                    "item": _synthetic_article("story-1", "合成报道"),
                    "savedAt": 42,
                }
            ]
        ),
        "wanxiang-saved-knowledge": "1",
        "wanxiang-planner-sync-device-v1": "synthetic-device-v2",
    }
    payload = {
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic",
        "exportedAt": "2026-09-27T00:00:00.000Z",
        "keys": keys,
    }
    payload["checksum"] = calculate_checksum(keys)
    return payload


class MigrationPackageTests(unittest.TestCase):
    def test_checksum_matches_javascript_json_stringify_and_webcrypto_input(self) -> None:
        values = {
            key: (f"汉字😀{index}" if index % 2 == 0 else None)
            for index, key in enumerate(STORAGE_KEYS_V1)
        }
        self.assertEqual(
            calculate_checksum(values, schema_version=1),
            "f97e4d4d7e25223cc3890f14a21da5aab42ed11ef6453798a42492d5b1173981",
        )

    def test_validates_all_ten_keys_and_counts_without_exposing_values(self) -> None:
        package = validate_package(synthetic_payload())
        self.assertEqual(len(package.raw_values), len(STORAGE_KEYS))
        self.assertEqual(package.schema_version, 2)
        self.assertEqual(package.summary["keys_total"], 10)
        self.assertEqual(package.summary["records"], 1)
        self.assertEqual(package.summary["habits"], 1)
        self.assertEqual(package.summary["media_items"], 1)
        self.assertEqual(package.summary["active_issue"], 1)
        self.assertEqual(package.summary["questions"], 1)

    def test_schema_v1_nine_key_package_stays_readable(self) -> None:
        payload = synthetic_payload()
        payload["schemaVersion"] = 1
        del payload["keys"]["wanxiang-planner-sync-device-v1"]
        payload["checksum"] = calculate_checksum(payload["keys"], schema_version=1)

        package = validate_package(payload)
        self.assertEqual(package.schema_version, 1)
        self.assertEqual(len(package.raw_values), 9)
        self.assertEqual(package.summary["keys_total"], 9)
        self.assertEqual(package.checksum, payload["checksum"])

    def test_checksum_tampering_is_rejected(self) -> None:
        payload = synthetic_payload()
        payload["keys"]["richangji-samples-cleared"] = "0"
        with self.assertRaisesRegex(MigrationPackageError, "SHA-256"):
            validate_package(payload)

    def test_tenth_key_is_covered_by_schema_v2_checksum(self) -> None:
        payload = synthetic_payload()
        payload["keys"]["wanxiang-planner-sync-device-v1"] = "changed-device"
        with self.assertRaisesRegex(MigrationPackageError, "SHA-256"):
            validate_package(payload)

    def test_missing_key_is_rejected(self) -> None:
        payload = synthetic_payload()
        del payload["keys"]["wanxiang-paper-layout-v2"]
        with self.assertRaisesRegex(MigrationPackageError, "键清单"):
            validate_package(payload)

    def test_import_preserves_each_raw_value_and_repeat_is_idempotent(self) -> None:
        package = validate_package(synthetic_payload())
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "native.sqlite3"
            first = import_package(package, database_path)
            second = import_package(package, database_path)

            self.assertEqual(first.status, "imported")
            self.assertEqual(second.status, "already_imported")
            self.assertEqual(first.batch_id, second.batch_id)
            self.assertEqual(second.summary, first.summary)
            self.assertEqual(second.summary["active_issue"], 1)
            self.assertEqual(second.summary["archived_issues"], 1)
            self.assertEqual(second.summary["questions"], 1)
            self.assertEqual(second.summary["topics"], 1)
            self.assertEqual(second.summary["clippings"], 1)

            with closing(sqlite3.connect(database_path)) as connection:
                stored = dict(
                    connection.execute(
                        "SELECT storage_key, raw_value FROM legacy_storage"
                    ).fetchall()
                )
                self.assertEqual(stored, package.raw_values)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM records").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM habits").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM media_items").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM migration_batches").fetchone()[0], 1)
                self.assertEqual(
                    connection.execute(
                        "SELECT source_schema_version FROM migration_batches"
                    ).fetchone()[0],
                    2,
                )

    def test_import_upgrades_from_schema_v1_to_v2_and_preserves_both_batches(self) -> None:
        legacy_payload = synthetic_payload()
        legacy_payload["schemaVersion"] = 1
        legacy_payload["keys"].pop("wanxiang-planner-sync-device-v1")
        legacy_payload["checksum"] = calculate_checksum(
            legacy_payload["keys"], schema_version=1
        )
        legacy = validate_package(legacy_payload)
        current = validate_package(synthetic_payload())

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "nine-to-ten.sqlite3"
            first = import_package(legacy, database_path)
            self.assertEqual(first.status, "imported")
            before = load_imported_data(database_path)
            self.assertEqual(before["summary"]["keys_total"], 9)
            self.assertNotIn("wanxiang-planner-sync-device-v1", before["raw_values"])

            preview = preview_import(current, database_path)
            self.assertEqual(preview["status"], "new_snapshot")
            self.assertEqual(preview["keyChangeCounts"]["added"], 1)
            self.assertEqual(
                [item for item in preview["keyChanges"] if item["change"] == "added"],
                [{"key": "wanxiang-planner-sync-device-v1", "change": "added"}],
            )
            second = import_package(current, database_path)
            self.assertEqual(second.status, "imported")
            self.assertEqual(import_package(current, database_path).status, "already_imported")

            loaded = load_imported_data(database_path)
            self.assertEqual(loaded["summary"]["keys_total"], 10)
            self.assertEqual(
                loaded["raw_values"]["wanxiang-planner-sync-device-v1"],
                "synthetic-device-v2",
            )
            self.assertEqual(loaded["import_info"]["source_schema_version"], 2)
            with closing(sqlite3.connect(database_path)) as connection:
                counts = dict(
                    connection.execute(
                        "SELECT batch_id, COUNT(*) FROM legacy_storage GROUP BY batch_id"
                    ).fetchall()
                )
                self.assertEqual(counts, {legacy.checksum: 9, current.checksum: 10})

    def test_invalid_content_is_rejected_before_database_creation(self) -> None:
        payload = synthetic_payload()
        payload["keys"]["richangji-state-v1"] = _raw({"records": "wrong"})
        payload["checksum"] = calculate_checksum(payload["keys"])
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "must-not-exist.sqlite3"
            with self.assertRaisesRegex(MigrationPackageError, "records"):
                import_package(validate_package(payload), database_path)
            self.assertFalse(database_path.exists())

    def test_invalid_record_shape_is_rejected_before_database_creation(self) -> None:
        payload = synthetic_payload()
        state = json.loads(payload["keys"]["richangji-state-v1"])
        state["records"][0]["type"] = "unknown"
        payload["keys"]["richangji-state-v1"] = _raw(state)
        payload["checksum"] = calculate_checksum(payload["keys"])
        with self.assertRaisesRegex(MigrationPackageError, "type"):
            validate_package(payload)

    def test_incomplete_clipping_is_rejected_before_database_creation(self) -> None:
        payload = synthetic_payload()
        payload["keys"]["wanxiang-issue-clippings-v1"] = _raw(
            [{"key": "2026-09-20::story-1", "date": "2026-09-20", "item": {"id": "story-1"}}]
        )
        payload["checksum"] = calculate_checksum(payload["keys"])
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "must-not-exist.sqlite3"
            with self.assertRaisesRegex(MigrationPackageError, "id 和 title"):
                import_package(validate_package(payload), database_path)
            self.assertFalse(database_path.exists())

    def test_failed_transaction_leaves_no_partial_import_rows(self) -> None:
        package = validate_package(synthetic_payload())
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "rollback.sqlite3"
            with closing(sqlite3.connect(database_path)) as connection:
                initialize_schema(connection)
                connection.execute(
                    """
                    CREATE TRIGGER reject_json_document
                    BEFORE INSERT ON json_documents
                    BEGIN SELECT RAISE(ABORT, 'synthetic rollback'); END
                    """
                )
                connection.commit()

            with self.assertRaises(sqlite3.IntegrityError):
                import_package(package, database_path)

            with closing(sqlite3.connect(database_path)) as connection:
                for table in (
                    "migration_batches",
                    "legacy_storage",
                    "json_documents",
                    "records",
                    "habits",
                    "media_items",
                ):
                    self.assertEqual(
                        connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                        0,
                        table,
                    )

    def test_different_package_becomes_active_snapshot_and_keeps_history(self) -> None:
        first_package = validate_package(synthetic_payload())
        payload = synthetic_payload()
        payload["keys"]["richangji-samples-cleared"] = "0"
        payload["checksum"] = calculate_checksum(payload["keys"])
        second_package = validate_package(payload)

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "snapshots.sqlite3"
            first = import_package(first_package, database_path)
            second = import_package(second_package, database_path)
            self.assertEqual(first.status, "imported")
            self.assertEqual(second.status, "imported")
            self.assertNotEqual(first.checksum, second.checksum)
            self.assertEqual(
                load_imported_data(database_path)["import_info"]["checksum_sha256"],
                second_package.checksum,
            )
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM migration_batches").fetchone()[0],
                    2,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM legacy_storage").fetchone()[0],
                    2 * len(STORAGE_KEYS),
                )


class MigrationBridgeTests(unittest.TestCase):
    def test_preview_and_confirmed_import_use_the_selected_package(self) -> None:
        payload = synthetic_payload()
        with tempfile.TemporaryDirectory() as directory:
            package_path = Path(directory) / "synthetic-migration.json"
            database_path = Path(directory) / "native.sqlite3"
            package_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            bridge = MigrationBridge(database_path)

            preview = bridge.previewPackage(QUrl.fromLocalFile(str(package_path)))
            self.assertTrue(preview["ok"])
            self.assertEqual(preview["summary"]["records"], 1)
            self.assertFalse(database_path.exists())

            imported = bridge.applyPreview()
            self.assertTrue(imported["ok"])
            self.assertEqual(imported["status"], "imported")

            preview_again = bridge.previewPackage(QUrl.fromLocalFile(str(package_path)))
            self.assertTrue(preview_again["ok"])
            repeated = bridge.applyPreview()
            self.assertTrue(repeated["ok"])
            self.assertEqual(repeated["status"], "already_imported")

    def test_invalid_preview_does_not_create_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package_path = Path(directory) / "invalid.json"
            database_path = Path(directory) / "must-not-exist.sqlite3"
            package_path.write_text('{"format":"wrong"}', encoding="utf-8")
            bridge = MigrationBridge(database_path)

            preview = bridge.previewPackage(QUrl.fromLocalFile(str(package_path)))
            self.assertFalse(preview["ok"])
            self.assertFalse(database_path.exists())
            self.assertFalse(bridge.applyPreview()["ok"])


if __name__ == "__main__":
    unittest.main()
