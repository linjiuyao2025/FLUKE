from __future__ import annotations

import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QUrl

from main import MigrationBridge
from migrate_legacy import default_database_path
from wanxiang.database import (
    PREVIOUS_SCHEMA_VERSION,
    SCHEMA_VERSION,
    import_package,
    initialize_database,
    load_imported_data,
    preview_import,
)
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    SOURCE_IDENTITY,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _raw(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _payload(marker: str = "first") -> dict[str, object]:
    state = {
        "records": [
            {
                "id": "record-stable",
                "type": "money",
                "date": "2026-09-27",
                "data": {"amount": 10, "note": "synthetic"},
            }
        ],
        "habits": [{"id": "habit-stable", "key": "walk", "entries": {}}],
        "mediaItems": [{"id": "media-stable", "name": "synthetic media", "type": "book"}],
        "settings": {"marker": marker},
    }
    keys: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    keys.update(
        {
            "richangji-state-v1": _raw(state),
            "richangji-samples-cleared": "1",
            "wanxiang-paper-layout-v2": _raw({"order": [marker]}),
            "wanxiang-daily-issues-v1": _raw({"active": None, "archive": []}),
            "wanxiang-issue-questions-v1": _raw([]),
            "wanxiang-issue-topics-v1": _raw([marker]),
            "wanxiang-issue-preferences-v1": _raw({"source": marker}),
            "wanxiang-issue-clippings-v1": _raw([]),
        }
    )
    payload: dict[str, object] = {
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-snapshot-test",
        "exportedAt": f"2026-09-27T00:00:0{1 if marker == 'first' else 2}Z",
        "keys": keys,
    }
    payload["checksum"] = calculate_checksum(keys)
    return payload


def _updated_payload() -> dict[str, object]:
    payload = _payload("second")
    keys = payload["keys"]
    assert isinstance(keys, dict)
    state = json.loads(keys["richangji-state-v1"])
    state["records"][0]["data"]["amount"] = 25
    state["records"].append(
        {
            "id": "record-added",
            "type": "money",
            "date": "2026-09-28",
            "data": {"amount": 5, "note": "synthetic added"},
        }
    )
    state["mediaItems"] = []
    keys["richangji-state-v1"] = _raw(state)
    keys["richangji-samples-cleared"] = None
    payload["checksum"] = calculate_checksum(keys)
    return payload


def _create_v1_database(
    path: Path,
    package_payload: dict[str, object],
    *,
    reject_upgrade: bool = False,
    source_identity_index: str = "full",
) -> None:
    package = validate_package(package_payload)
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE schema_info (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                schema_version INTEGER NOT NULL
            );
            INSERT INTO schema_info VALUES (1, 1);
            CREATE TABLE migration_batches (
                batch_id TEXT PRIMARY KEY,
                source_identity TEXT NOT NULL,
                source_version TEXT NOT NULL,
                source_schema_version INTEGER NOT NULL,
                exported_at TEXT NOT NULL,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                checksum_sha256 TEXT NOT NULL
            );
            CREATE TABLE legacy_storage (
                batch_id TEXT NOT NULL REFERENCES migration_batches(batch_id) ON DELETE CASCADE,
                storage_key TEXT NOT NULL,
                raw_value TEXT,
                PRIMARY KEY(batch_id, storage_key)
            );
            CREATE TABLE json_documents (
                batch_id TEXT NOT NULL REFERENCES migration_batches(batch_id) ON DELETE CASCADE,
                document_key TEXT NOT NULL,
                document_json TEXT NOT NULL,
                PRIMARY KEY(batch_id, document_key)
            );
            CREATE TABLE records (
                record_row_id INTEGER PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES migration_batches(batch_id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                legacy_id TEXT,
                record_type TEXT,
                record_date TEXT,
                payload_json TEXT NOT NULL,
                UNIQUE(batch_id, position)
            );
            CREATE TABLE habits (
                habit_row_id INTEGER PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES migration_batches(batch_id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                legacy_id TEXT,
                habit_key TEXT,
                payload_json TEXT NOT NULL,
                UNIQUE(batch_id, position)
            );
            CREATE TABLE media_items (
                media_row_id INTEGER PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES migration_batches(batch_id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                legacy_id TEXT,
                name TEXT,
                media_type TEXT,
                status TEXT,
                item_date TEXT,
                payload_json TEXT NOT NULL,
                UNIQUE(batch_id, position)
            );
            CREATE TABLE app_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
            CREATE TABLE finance_module_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), state_json TEXT NOT NULL
            );
            """
        )
        if source_identity_index == "full":
            connection.execute(
                "CREATE UNIQUE INDEX migration_batches_source_identity_uq "
                "ON migration_batches(source_identity)"
            )
        elif source_identity_index == "partial":
            connection.execute(
                "CREATE UNIQUE INDEX migration_batches_source_identity_partial "
                "ON migration_batches(source_identity) "
                "WHERE source_identity <> 'wanxiang-localstorage-v1'"
            )
        elif source_identity_index == "none":
            connection.execute(
                "CREATE INDEX migration_batches_source_identity_idx "
                "ON migration_batches(source_identity)"
            )
        else:
            raise ValueError("unsupported synthetic source identity index fixture")
        connection.execute(
            "INSERT INTO migration_batches(batch_id,source_identity,source_version,"
            "source_schema_version,exported_at,checksum_sha256) VALUES(?,?,?,?,?,?)",
            (
                package.checksum,
                SOURCE_IDENTITY,
                package.source_version,
                PACKAGE_SCHEMA_VERSION,
                package.exported_at,
                package.checksum,
            ),
        )
        connection.executemany(
            "INSERT INTO legacy_storage(batch_id,storage_key,raw_value) VALUES(?,?,?)",
            [(package.checksum, key, package.raw_values[key]) for key in STORAGE_KEYS],
        )
        connection.executemany(
            "INSERT INTO json_documents(batch_id,document_key,document_json) VALUES(?,?,?)",
            [
                (
                    package.checksum,
                    key,
                    json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True),
                )
                for key, value in package.parsed_values.items()
            ],
        )
        state = package.parsed_values["richangji-state-v1"]
        for table, items in (
            ("records", state.get("records", [])),
            ("habits", state.get("habits", [])),
            ("media_items", state.get("mediaItems", [])),
        ):
            for position, item in enumerate(items):
                payload_json = json.dumps(
                    item, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
                )
                if table == "records":
                    connection.execute(
                        "INSERT INTO records(batch_id,position,legacy_id,record_type,record_date,payload_json) "
                        "VALUES(?,?,?,?,?,?)",
                        (package.checksum, position, item.get("id"), item.get("type"), item.get("date"), payload_json),
                    )
                elif table == "habits":
                    connection.execute(
                        "INSERT INTO habits(batch_id,position,legacy_id,habit_key,payload_json) "
                        "VALUES(?,?,?,?,?)",
                        (package.checksum, position, item.get("id"), item.get("key"), payload_json),
                    )
                else:
                    connection.execute(
                        "INSERT INTO media_items(batch_id,position,legacy_id,name,media_type,status,item_date,payload_json) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (
                            package.checksum,
                            position,
                            item.get("id"),
                            item.get("name"),
                            item.get("type"),
                            item.get("status"),
                            item.get("date"),
                            payload_json,
                        ),
                    )
        connection.execute(
            "INSERT INTO app_settings(key,value_json) VALUES('synthetic-preserve','{\"value\":1}')"
        )
        connection.execute(
            "INSERT INTO finance_module_state(singleton,state_json) VALUES(1,'{\"overlay\":true}')"
        )
        if reject_upgrade:
            connection.execute(
                "CREATE TRIGGER reject_schema_upgrade BEFORE UPDATE OF schema_version ON schema_info "
                "WHEN OLD.schema_version=1 AND NEW.schema_version=2 "
                "BEGIN SELECT RAISE(ABORT,'synthetic schema upgrade rejection'); END"
            )


class SnapshotMigrationTests(unittest.TestCase):
    def test_v1_upgrade_preserves_children_foreign_keys_settings_and_overlays(self) -> None:
        package = validate_package(_payload())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v1.sqlite3"
            _create_v1_database(path, _payload())

            initialize_database(path)

            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT schema_version FROM schema_info").fetchone()[0],
                    SCHEMA_VERSION,
                )
                self.assertEqual(
                    connection.execute("SELECT active_batch_id FROM migration_sources").fetchone()[0],
                    package.checksum,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM legacy_storage").fetchone()[0],
                    len(STORAGE_KEYS),
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM records").fetchone()[0], 1
                )
                self.assertEqual(
                    connection.execute("SELECT value_json FROM app_settings WHERE key='synthetic-preserve'").fetchone()[0],
                    '{"value":1}',
                )
                self.assertEqual(
                    connection.execute("SELECT state_json FROM finance_module_state").fetchone()[0],
                    '{"overlay":true}',
                )
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(
                    connection.execute("PRAGMA foreign_key_list(records)").fetchone()[2],
                    "migration_batches",
                )

            updated = validate_package(_updated_payload())
            result = import_package(updated, path)
            self.assertEqual(result.status, "imported")
            self.assertEqual(load_imported_data(path)["import_info"]["checksum_sha256"], updated.checksum)

    def test_bootstrap_upgrades_a_copy_and_keeps_the_previous_native_file_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            appdata = Path(directory)
            previous = appdata / "Wanxiang Life Workspace Native" / "wanxiang.sqlite3"
            previous.parent.mkdir(parents=True)
            _create_v1_database(previous, _payload())
            original_digest = hashlib.sha256(previous.read_bytes()).hexdigest()

            with patch.dict("os.environ", {"APPDATA": str(appdata)}):
                current = default_database_path()
                self.assertEqual(current, appdata / "FLUKE" / "fluke.sqlite3")
                self.assertEqual(hashlib.sha256(previous.read_bytes()).hexdigest(), original_digest)
                initialize_database(current)

            with closing(sqlite3.connect(current)) as connection:
                self.assertEqual(
                    connection.execute("SELECT schema_version FROM schema_info").fetchone()[0],
                    SCHEMA_VERSION,
                )
            self.assertEqual(hashlib.sha256(previous.read_bytes()).hexdigest(), original_digest)

    def test_preview_diffs_are_summary_only_and_do_not_write(self) -> None:
        first = validate_package(_payload())
        updated = validate_package(_updated_payload())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preview.sqlite3"
            import_package(first, path)
            before = hashlib.sha256(path.read_bytes()).hexdigest()

            preview = preview_import(updated, path)

            self.assertEqual(preview["status"], "new_snapshot")
            self.assertEqual(preview["currentChecksum"], first.checksum)
            self.assertTrue(preview["willActivate"])
            self.assertGreaterEqual(preview["keyChangeCounts"]["changed"], 1)
            self.assertGreaterEqual(preview["keyChangeCounts"]["removed"], 1)
            self.assertEqual(preview["entityChanges"]["records"]["changed"], 1)
            self.assertEqual(preview["entityChanges"]["records"]["added"], 1)
            self.assertEqual(preview["entityChanges"]["media_items"]["removed"], 1)
            self.assertNotIn("record-stable", json.dumps(preview, ensure_ascii=False))
            self.assertNotIn("synthetic added", json.dumps(preview, ensure_ascii=False))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_new_snapshot_is_atomic_retains_raw_history_and_preserves_overlays(self) -> None:
        first_payload = _payload()
        first = validate_package(first_payload)
        second = validate_package(_updated_payload())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replace.sqlite3"
            import_package(first, path)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "CREATE TABLE finance_module_state(singleton INTEGER PRIMARY KEY,state_json TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO finance_module_state VALUES(1,'{\"edited\":true}')"
                )
                connection.commit()

            changed = import_package(
                second,
                path,
                expected_active_checksum=first.checksum,
            )
            active = load_imported_data(path)
            self.assertEqual(changed.status, "imported")
            self.assertTrue(changed.is_active)
            self.assertEqual(active["import_info"]["checksum_sha256"], second.checksum)
            self.assertEqual(len(active["entities"]["records"]), 2)
            self.assertEqual(active["entities"]["media_items"], [])

            with closing(sqlite3.connect(path)) as connection:
                batches = dict(
                    connection.execute(
                        "SELECT checksum_sha256,batch_id FROM migration_batches"
                    ).fetchall()
                )
                self.assertEqual(set(batches), {first.checksum, second.checksum})
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM legacy_storage").fetchone()[0],
                    2 * len(STORAGE_KEYS),
                )
                for package in (first, second):
                    raw = dict(
                        connection.execute(
                            "SELECT storage_key,raw_value FROM legacy_storage WHERE batch_id=?",
                            (batches[package.checksum],),
                        ).fetchall()
                    )
                    self.assertEqual(raw, package.raw_values)
                self.assertEqual(
                    connection.execute("SELECT active_batch_id FROM migration_sources").fetchone()[0],
                    batches[second.checksum],
                )
                self.assertEqual(
                    connection.execute("SELECT state_json FROM finance_module_state").fetchone()[0],
                    '{"edited":true}',
                )

            # Replaying an old historical checksum is idempotent and never rolls
            # the active pointer back to that old batch.
            archived_repeat = import_package(
                first,
                path,
                expected_active_checksum=second.checksum,
            )
            self.assertEqual(archived_repeat.status, "already_imported")
            self.assertFalse(archived_repeat.is_active)
            self.assertEqual(
                load_imported_data(path)["import_info"]["checksum_sha256"],
                second.checksum,
            )

    def test_failed_snapshot_transaction_keeps_active_snapshot_and_history_intact(self) -> None:
        first = validate_package(_payload())
        second = validate_package(_updated_payload())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollback.sqlite3"
            import_package(first, path)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    "CREATE TRIGGER reject_next_document BEFORE INSERT ON json_documents "
                    "BEGIN SELECT RAISE(ABORT,'synthetic snapshot rejection'); END"
                )
                connection.commit()

            before = load_imported_data(path)
            with self.assertRaises(sqlite3.IntegrityError):
                import_package(
                    second,
                    path,
                    expected_active_checksum=first.checksum,
                )

            after = load_imported_data(path)
            self.assertEqual(after["import_info"]["checksum_sha256"], first.checksum)
            self.assertEqual(after["raw_values"], before["raw_values"])
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM migration_batches").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM legacy_storage").fetchone()[0],
                    len(STORAGE_KEYS),
                )
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_stale_preview_cannot_overwrite_a_newer_active_snapshot(self) -> None:
        first = validate_package(_payload())
        second = validate_package(_updated_payload())
        third_payload = _payload("third")
        third = validate_package(third_payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stale.sqlite3"
            import_package(first, path)
            with self.assertRaisesRegex(RuntimeError, "快照已变化"):
                import_package(
                    second,
                    path,
                    expected_active_checksum=third.checksum,
                )
            self.assertEqual(
                load_imported_data(path)["import_info"]["checksum_sha256"],
                first.checksum,
            )

    def test_v2_initialization_does_not_guess_an_active_archived_snapshot(self) -> None:
        first = validate_package(_payload())
        second = validate_package(_updated_payload())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing-active-pointer.sqlite3"
            import_package(first, path)
            import_package(second, path)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DELETE FROM migration_sources")
                connection.commit()

            with self.assertRaisesRegex(RuntimeError, "no active source pointer"):
                initialize_database(path)

            self.assertEqual(load_imported_data(path)["status"], "unavailable")
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM migration_batches").fetchone()[0],
                    2,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM migration_sources").fetchone()[0],
                    0,
                )

    def test_failed_v1_schema_upgrade_rolls_back_without_mutating_original(self) -> None:
        payload = _payload()
        package = validate_package(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "upgrade-rollback.sqlite3"
            _create_v1_database(path, payload, reject_upgrade=True)
            before = hashlib.sha256(path.read_bytes()).hexdigest()

            with self.assertRaises(sqlite3.IntegrityError):
                initialize_database(path)

            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(
                    connection.execute("SELECT schema_version FROM schema_info").fetchone()[0],
                    PREVIOUS_SCHEMA_VERSION,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM legacy_storage").fetchone()[0],
                    len(STORAGE_KEYS),
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM migration_sources").fetchone()[0]
                    if "migration_sources" in {
                        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }
                    else 0,
                    0,
                )
                self.assertEqual(
                    connection.execute("SELECT checksum_sha256 FROM migration_batches").fetchone()[0],
                    package.checksum,
                )

    def test_v1_upgrade_rejects_partial_index_or_duplicate_source_batches(self) -> None:
        package_payload = _payload()
        package = validate_package(package_payload)
        cases = (
            ("partial", "完整唯一索引"),
            ("duplicate", "重复来源批次"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for case, expected_error in cases:
                with self.subTest(case=case):
                    path = Path(directory) / f"unsafe-v1-{case}.sqlite3"
                    index_mode = "partial" if case == "partial" else "none"
                    _create_v1_database(
                        path,
                        package_payload,
                        source_identity_index=index_mode,
                    )
                    if case == "duplicate":
                        with closing(sqlite3.connect(path)) as connection:
                            connection.execute(
                                "INSERT INTO migration_batches(batch_id,source_identity,"
                                "source_version,source_schema_version,exported_at,checksum_sha256) "
                                "VALUES(?,?,?,?,?,?)",
                                (
                                    package.checksum + "-duplicate",
                                    SOURCE_IDENTITY,
                                    package.source_version,
                                    PACKAGE_SCHEMA_VERSION,
                                    package.exported_at,
                                    "synthetic-second-checksum",
                                ),
                            )
                            connection.commit()
                    before = hashlib.sha256(path.read_bytes()).hexdigest()

                    with self.assertRaisesRegex(RuntimeError, expected_error):
                        initialize_database(path)

                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
                    with closing(sqlite3.connect(path)) as connection:
                        self.assertEqual(
                            connection.execute(
                                "SELECT schema_version FROM schema_info WHERE singleton=1"
                            ).fetchone()[0],
                            PREVIOUS_SCHEMA_VERSION,
                        )
                        expected_batches = 2 if case == "duplicate" else 1
                        self.assertEqual(
                            connection.execute("SELECT COUNT(*) FROM migration_batches").fetchone()[0],
                            expected_batches,
                        )
                        self.assertNotIn(
                            "migration_sources",
                            {
                                row[0]
                                for row in connection.execute(
                                    "SELECT name FROM sqlite_master WHERE type='table'"
                                )
                            },
                        )

    def test_bridge_reports_snapshot_diff_and_does_not_reactivate_history(self) -> None:
        first_payload = _payload()
        first = validate_package(first_payload)
        second_payload = _updated_payload()
        second = validate_package(second_payload)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "bridge.sqlite3"
            first_file = root / "first.json"
            second_file = root / "second.json"
            first_file.write_text(json.dumps(first_payload, ensure_ascii=False), encoding="utf-8")
            second_file.write_text(json.dumps(second_payload, ensure_ascii=False), encoding="utf-8")
            bridge = MigrationBridge(database_path)

            new_preview = bridge.previewPackage(QUrl.fromLocalFile(str(first_file)))
            self.assertEqual(new_preview["status"], "new")
            self.assertFalse(database_path.exists())
            self.assertTrue(bridge.applyPreview()["ok"])

            update_preview = bridge.previewPackage(QUrl.fromLocalFile(str(second_file)))
            self.assertEqual(update_preview["status"], "new_snapshot")
            self.assertEqual(update_preview["preview"]["entityChanges"]["records"]["changed"], 1)
            self.assertTrue(bridge.applyPreview()["ok"])
            self.assertEqual(
                load_imported_data(database_path)["import_info"]["checksum_sha256"],
                second.checksum,
            )

    def test_bridge_rejects_a_snapshot_if_active_data_changed_after_preview(self) -> None:
        first_payload = _payload()
        first = validate_package(first_payload)
        second_payload = _updated_payload()
        second = validate_package(second_payload)
        third = validate_package(_payload("third"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "stale-bridge.sqlite3"
            first_file = root / "first.json"
            second_file = root / "second.json"
            first_file.write_text(json.dumps(first_payload, ensure_ascii=False), encoding="utf-8")
            second_file.write_text(json.dumps(second_payload, ensure_ascii=False), encoding="utf-8")
            import_package(first, database_path)
            bridge = MigrationBridge(database_path)
            preview = bridge.previewPackage(QUrl.fromLocalFile(str(second_file)))
            self.assertEqual(preview["status"], "new_snapshot")

            import_package(third, database_path)
            applied = bridge.applyPreview()

            self.assertFalse(applied["ok"])
            self.assertIn("快照已变化", applied["error"])
            self.assertEqual(
                load_imported_data(database_path)["import_info"]["checksum_sha256"],
                third.checksum,
            )

            archived_preview = bridge.previewPackage(QUrl.fromLocalFile(str(first_file)))
            self.assertEqual(archived_preview["status"], "new_snapshot")
            self.assertTrue(archived_preview["preview"]["historicalInactive"])
            self.assertFalse(bridge.applyPreview()["ok"])
            self.assertEqual(
                load_imported_data(database_path)["import_info"]["checksum_sha256"],
                third.checksum,
            )


if __name__ == "__main__":
    unittest.main()
