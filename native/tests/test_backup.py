from __future__ import annotations

import base64
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from wanxiang.backup import (
    BackupError,
    DATABASE_MEMBER,
    MANIFEST_MEMBER,
    _database_summary,
    export_backup,
    export_encrypted_backup,
    preview_backup,
    preview_encrypted_backup,
    restore_backup,
    restore_encrypted_backup,
)
from wanxiang.database import (
    get_app_setting,
    import_package,
    initialize_schema,
    load_imported_data,
    set_app_setting,
)
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    SOURCE_IDENTITY,
    calculate_checksum,
    validate_package,
)
from wanxiang.webdav_planner import encrypt_snapshot


class FullBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database_path = self.root / "wanxiang.sqlite3"
        self.package_path = self.root / "private.wxbak"
        self._make_database(self.database_path, "before")

    @staticmethod
    def _make_database(path: Path, value: str) -> None:
        with closing(sqlite3.connect(path)) as connection:
            initialize_schema(connection)
            connection.execute(
                "INSERT INTO app_settings(key,value_json) VALUES('synthetic',?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (json.dumps({"value": value}, separators=(",", ":")),),
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS finance_module_state ("
                "singleton INTEGER PRIMARY KEY, state_json TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO finance_module_state(singleton,state_json) VALUES(1,?) "
                "ON CONFLICT(singleton) DO UPDATE SET state_json=excluded.state_json",
                (json.dumps({"privateSynthetic": value}, separators=(",", ":")),),
            )
            connection.commit()

    @staticmethod
    def _setting(path: Path) -> str:
        with closing(sqlite3.connect(path)) as connection:
            raw = connection.execute(
                "SELECT value_json FROM app_settings WHERE key='synthetic'"
            ).fetchone()[0]
        return json.loads(raw)["value"]

    @staticmethod
    def _make_v1_database(path: Path) -> None:
        state = {
            "records": [
                {
                    "id": "v1-record",
                    "type": "money",
                    "date": "2026-09-28",
                    "data": {"amount": 17},
                }
            ],
            "habits": [],
            "mediaItems": [],
        }
        raw_values = {key: None for key in STORAGE_KEYS}
        raw_values["richangji-state-v1"] = json.dumps(
            state, ensure_ascii=False, separators=(",", ":")
        )
        raw_values["wanxiang-issue-topics-v1"] = '["v1-topic"]'
        payload = {
            "format": PACKAGE_FORMAT,
            "schemaVersion": PACKAGE_SCHEMA_VERSION,
            "sourceVersion": "synthetic-v1-backup",
            "exportedAt": "2026-09-28T00:00:00Z",
            "keys": raw_values,
            "checksum": calculate_checksum(raw_values),
        }
        package = validate_package(payload)

        with closing(sqlite3.connect(path, isolation_level=None)) as connection:
            connection.executescript(
                """
                CREATE TABLE schema_info (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    schema_version INTEGER NOT NULL
                );
                INSERT INTO schema_info VALUES (1, 1);
                CREATE TABLE migration_batches (
                    batch_id TEXT PRIMARY KEY,
                    source_identity TEXT NOT NULL UNIQUE,
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
                [
                    (package.checksum, key, package.raw_values[key])
                    for key in STORAGE_KEYS
                ],
            )
            connection.executemany(
                "INSERT INTO json_documents(batch_id,document_key,document_json) VALUES(?,?,?)",
                [
                    (
                        package.checksum,
                        key,
                        json.dumps(
                            value,
                            ensure_ascii=False,
                            allow_nan=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    )
                    for key, value in package.parsed_values.items()
                ],
            )
            for position, item in enumerate(state["records"]):
                connection.execute(
                    "INSERT INTO records(batch_id,position,legacy_id,record_type,record_date,payload_json) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        package.checksum,
                        position,
                        item.get("id"),
                        item.get("type"),
                        item.get("date"),
                        json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
            connection.execute(
                "INSERT INTO app_settings(key,value_json) VALUES('synthetic',?)",
                (json.dumps({"value": "v1-setting"}, separators=(",", ":")),),
            )
            connection.execute(
                "INSERT INTO finance_module_state(singleton,state_json) VALUES(1,?)",
                ('{"overlay":"v1-preserved"}',),
            )
            connection.commit()

    def test_export_preview_and_restore_replace_every_table_from_snapshot(self) -> None:
        exported = export_backup(self.database_path, self.package_path)
        self.assertTrue(self.package_path.is_file())
        self.assertEqual(exported["summary"]["tables"], preview_backup(self.package_path)["summary"]["tables"])

        # Preview is read-only and cannot change the active database.
        self.assertEqual(self._setting(self.database_path), "before")
        self._make_database(self.database_path, "after")
        restored = restore_backup(self.package_path, self.database_path)
        self.assertEqual(restored["summary"], exported["summary"])
        self.assertEqual(self._setting(self.database_path), "before")
        with closing(sqlite3.connect(self.database_path)) as connection:
            raw = connection.execute(
                "SELECT state_json FROM finance_module_state WHERE singleton=1"
            ).fetchone()[0]
        self.assertEqual(json.loads(raw), {"privateSynthetic": "before"})

    def test_full_backup_preserves_snapshot_history_and_active_pointer(self) -> None:
        def package(marker: str) -> object:
            raw = {key: None for key in STORAGE_KEYS}
            state = {
                "records": [
                    {
                        "id": f"record-{marker}",
                        "type": "money",
                        "date": "2026-09-28",
                        "data": {"amount": len(marker)},
                    }
                ],
                "habits": [],
                "mediaItems": [],
            }
            raw["richangji-state-v1"] = json.dumps(
                state, ensure_ascii=False, separators=(",", ":")
            )
            raw["wanxiang-issue-topics-v1"] = json.dumps([marker], ensure_ascii=False)
            payload = {
                "format": PACKAGE_FORMAT,
                "schemaVersion": PACKAGE_SCHEMA_VERSION,
                "sourceVersion": "synthetic-backup-snapshot",
                "exportedAt": f"2026-09-28T00:00:0{len(marker)}Z",
                "keys": raw,
                "checksum": calculate_checksum(raw),
            }
            return validate_package(payload)

        first = package("first")
        active = package("second")
        import_package(first, self.database_path)
        import_package(active, self.database_path)
        set_app_setting(self.database_path, "keep-local", {"value": "synthetic"})
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS finance_module_state "
                "(singleton INTEGER PRIMARY KEY,state_json TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO finance_module_state VALUES(1,'{\"overlay\":true}') "
                "ON CONFLICT(singleton) DO UPDATE SET state_json=excluded.state_json"
            )
            connection.commit()
        export_backup(self.database_path, self.package_path)

        # Replace the live state after export, then restore the whole snapshot.
        import_package(package("third"), self.database_path)
        set_app_setting(self.database_path, "keep-local", {"value": "later"})
        restore_backup(self.package_path, self.database_path)

        loaded = load_imported_data(self.database_path)
        self.assertEqual(loaded["import_info"]["checksum_sha256"], active.checksum)
        self.assertEqual(loaded["entities"]["records"][0]["id"], "record-second")
        self.assertEqual(get_app_setting(self.database_path, "keep-local"), {"value": "synthetic"})
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM migration_batches").fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT b.checksum_sha256 FROM migration_sources AS s "
                    "JOIN migration_batches AS b ON b.batch_id=s.active_batch_id "
                    "WHERE s.source_identity=?",
                    ("wanxiang-localstorage-v1",),
                ).fetchone()[0],
                active.checksum,
            )
            self.assertEqual(
                connection.execute("SELECT state_json FROM finance_module_state").fetchone()[0],
                '{"overlay":true}',
            )
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_v1_native_backup_remains_readable_and_source_is_never_upgraded(self) -> None:
        v1_path = self.root / "synthetic-v1.sqlite3"
        v1_backup = self.root / "synthetic-v1.wxbak"
        upgraded_clone = self.root / "synthetic-v1-clone.sqlite3"
        self._make_v1_database(v1_path)
        source_digest = hashlib.sha256(v1_path.read_bytes()).hexdigest()

        source_summary = _database_summary(v1_path)
        self.assertEqual(source_summary["schemaVersion"], 1)
        self.assertEqual(source_summary["legacy"]["records"], 1)
        self.assertEqual(
            load_imported_data(v1_path)["entities"]["records"][0]["id"],
            "v1-record",
        )
        self.assertEqual(hashlib.sha256(v1_path.read_bytes()).hexdigest(), source_digest)

        export_backup(v1_path, v1_backup)
        preview = preview_backup(v1_backup)
        self.assertEqual(preview["summary"], source_summary)
        self.assertEqual(preview["summary"]["schemaVersion"], 1)
        self.assertEqual(hashlib.sha256(v1_path.read_bytes()).hexdigest(), source_digest)

        restored = restore_backup(v1_backup, self.database_path)
        self.assertEqual(restored["summary"]["schemaVersion"], 1)
        self.assertEqual(load_imported_data(self.database_path)["status"], "loaded")
        self.assertEqual(
            load_imported_data(self.database_path)["entities"]["records"][0]["id"],
            "v1-record",
        )
        self.assertEqual(get_app_setting(self.database_path, "synthetic"), {"value": "v1-setting"})
        with closing(sqlite3.connect(self.database_path)) as connection:
            version = connection.execute(
                "SELECT schema_version FROM schema_info WHERE singleton=1"
            ).fetchone()[0]
            overlay = connection.execute(
                "SELECT state_json FROM finance_module_state WHERE singleton=1"
            ).fetchone()[0]
        self.assertEqual(version, 1)
        self.assertEqual(json.loads(overlay), {"overlay": "v1-preserved"})

        upgraded_clone.write_bytes(v1_path.read_bytes())
        with closing(sqlite3.connect(upgraded_clone)) as connection:
            initialize_schema(connection)
            active = connection.execute(
                "SELECT b.checksum_sha256 FROM migration_sources AS s "
                "JOIN migration_batches AS b ON b.batch_id=s.active_batch_id "
                "WHERE s.source_identity=?",
                (SOURCE_IDENTITY,),
            ).fetchone()[0]
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(active, load_imported_data(upgraded_clone)["import_info"]["checksum_sha256"])
        self.assertEqual(hashlib.sha256(v1_path.read_bytes()).hexdigest(), source_digest)

    def test_checksum_failure_does_not_modify_existing_database(self) -> None:
        export_backup(self.database_path, self.package_path)
        self._make_database(self.database_path, "keep")
        before = hashlib.sha256(self.database_path.read_bytes()).hexdigest()

        corrupt = self.root / "corrupt.wxbak"
        with zipfile.ZipFile(self.package_path, "r") as source:
            manifest = json.loads(source.read(MANIFEST_MEMBER))
            manifest["sha256"] = "0" * 64
            database = source.read(DATABASE_MEMBER)
        with zipfile.ZipFile(corrupt, "w", compression=zipfile.ZIP_DEFLATED) as target:
            target.writestr(MANIFEST_MEMBER, json.dumps(manifest).encode("utf-8"))
            target.writestr(DATABASE_MEMBER, database)

        with self.assertRaisesRegex(BackupError, "SHA-256"):
            restore_backup(corrupt, self.database_path)
        self.assertEqual(hashlib.sha256(self.database_path.read_bytes()).hexdigest(), before)
        self.assertEqual(self._setting(self.database_path), "keep")

    def test_non_native_or_legacy_json_backup_is_rejected(self) -> None:
        old_json = self.root / "unsupported.json"
        old_json.write_text(
            json.dumps({"format": "unknown-backup", "version": 1}),
            encoding="utf-8",
        )
        with self.assertRaises(BackupError):
            preview_backup(old_json)

    @staticmethod
    def _write_old_full_backup(path: Path, *, invalid_date: bool = False) -> None:
        state = {
            "records": [
                {
                    "id": "legacy-record",
                    "type": "money",
                    "date": "2026-2-3" if invalid_date else "2026-02-03",
                    "data": {"amount": 13, "note": "synthetic backup record"},
                }
            ],
            "habits": [],
            "mediaItems": [{"id": "movie-1", "name": "synthetic film"}],
            "settings": {
                "samplesCleared": True,
                "brand": {"name": "旧版测试页", "theme": "forest", "futureField": "kept"},
            },
        }
        issue = {
            "version": "1",
            "date": "2026-02-03",
            "topic": "synthetic issue",
            "focus": [{
                "id": "focus-1", "label": "焦点", "title": "焦点标题",
                "summary": "合成摘要", "publisher": "测试社", "publishedAt": "2026-02-03",
                "sourceUrl": "https://example.test/focus", "body": ["合成正文"],
            }],
            "highlights": [{
                "id": "highlight-1", "label": "要闻", "title": "要闻标题",
                "summary": "合成摘要", "publisher": "测试社", "publishedAt": "2026-02-03",
                "sourceUrl": "https://example.test/highlight", "body": ["合成正文"],
            }],
            "articles": [],
        }
        path.write_text(
            json.dumps({
                "format": "daily-atlas-backup",
                "version": 1,
                "exportedAt": "2026-02-03T10:30:00.000Z",
                "state": state,
                "issueContent": {"active": issue, "archive": []},
            }, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_legacy_daily_atlas_backup_preview_reports_counts(self) -> None:
        old_json = self.root / "old-full-backup.json"
        self._write_old_full_backup(old_json)
        result = preview_backup(old_json)
        self.assertEqual(result["sourceFormat"], "daily-atlas-backup-v1")
        self.assertEqual(result["exportedAt"], "2026-02-03T10:30:00.000Z")
        self.assertEqual(result["summary"]["legacy"]["records"], 1)
        self.assertEqual(result["summary"]["legacy"]["media_items"], 1)
        self.assertEqual(result["summary"]["legacy"]["active_issue"], 1)

    def test_legacy_restore_replaces_state_keeps_independent_data_and_resets_overlays(self) -> None:
        current_state = {
            "records": [{"id": "old", "type": "home", "date": "2025-01-01", "data": {}}],
            "habits": [], "mediaItems": [], "settings": {"brand": {"name": "旧品牌"}},
        }
        raw = {key: None for key in STORAGE_KEYS}
        raw["richangji-state-v1"] = json.dumps(current_state, ensure_ascii=False)
        raw["wanxiang-issue-questions-v1"] = json.dumps(["保留的今日问题"], ensure_ascii=False)
        migration_payload = {
            "format": PACKAGE_FORMAT,
            "schemaVersion": PACKAGE_SCHEMA_VERSION,
            "sourceVersion": "synthetic",
            "exportedAt": "2026-01-01T00:00:00Z",
            "keys": raw,
            "checksum": calculate_checksum(raw),
        }
        import_package(validate_package(migration_payload), self.database_path)
        set_app_setting(self.database_path, "independent-local-setting", {"keep": True})
        set_app_setting(self.database_path, "brandAppearance", {
            "version": 1,
            "legacyBrand": {"name": "旧品牌"},
            "settingsOverrides": {"name": "当前本机品牌"},
        })
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "CREATE TABLE daily_flow_state (singleton INTEGER PRIMARY KEY, state_json TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO daily_flow_state(singleton,state_json) VALUES(1,?)",
                (json.dumps({"questions": ["保留的今日问题"]}, ensure_ascii=False),),
            )
            connection.execute(
                "INSERT INTO finance_module_state(singleton,state_json) VALUES(1,?) "
                "ON CONFLICT(singleton) DO UPDATE SET state_json=excluded.state_json",
                (json.dumps({"syntheticOverlay": True}),),
            )
            connection.commit()
        old_json = self.root / "old-full-backup.json"
        self._write_old_full_backup(old_json)

        restored = restore_backup(old_json, self.database_path)
        loaded = load_imported_data(self.database_path)
        self.assertEqual(restored["sourceFormat"], "daily-atlas-backup-v1")
        self.assertEqual(loaded["entities"]["records"][0]["id"], "legacy-record")
        self.assertEqual(loaded["summary"]["media_items"], 1)
        self.assertEqual(loaded["raw_values"]["wanxiang-issue-questions-v1"], '["保留的今日问题"]')
        self.assertTrue(get_app_setting(self.database_path, "independent-local-setting")["keep"])
        brand = get_app_setting(self.database_path, "brandAppearance")
        self.assertEqual(brand["legacyBrand"]["name"], "旧版测试页")
        self.assertEqual(brand["legacyBrand"]["futureField"], "kept")
        self.assertEqual(brand["settingsOverrides"], {})
        with closing(sqlite3.connect(self.database_path)) as connection:
            overlay = connection.execute(
                "SELECT 1 FROM finance_module_state WHERE singleton=1"
            ).fetchone()
            daily_flow = connection.execute(
                "SELECT 1 FROM daily_flow_state WHERE singleton=1"
            ).fetchone()
        self.assertIsNone(overlay)
        self.assertIsNone(daily_flow)

    def test_malformed_legacy_backup_is_rejected_without_changing_database(self) -> None:
        old_json = self.root / "invalid.json"
        self._write_old_full_backup(old_json, invalid_date=True)
        before = hashlib.sha256(self.database_path.read_bytes()).hexdigest()
        with self.assertRaises(BackupError):
            restore_backup(old_json, self.database_path)
        self.assertEqual(hashlib.sha256(self.database_path.read_bytes()).hexdigest(), before)

    def test_legacy_backup_enforces_fifty_megabyte_limit(self) -> None:
        old_json = self.root / "oversized.json"
        old_json.write_bytes(b" " * (50 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(BackupError, "50 MB"):
            preview_backup(old_json)

    def test_export_does_not_replace_existing_file_on_validation_failure(self) -> None:
        self.package_path.write_bytes(b"previous synthetic backup")
        bad_database = self.root / "foreign.sqlite3"
        with closing(sqlite3.connect(bad_database)) as connection:
            connection.execute("CREATE TABLE unrelated(value TEXT)")
            connection.commit()
        with self.assertRaises(BackupError):
            export_backup(bad_database, self.package_path)
        self.assertEqual(self.package_path.read_bytes(), b"previous synthetic backup")

    def test_restore_rejects_database_with_active_sidecar(self) -> None:
        export_backup(self.database_path, self.package_path)
        sidecar = Path(f"{self.database_path}-wal")
        sidecar.write_bytes(b"open synthetic database marker")
        with self.assertRaisesRegex(BackupError, "仍被使用"):
            restore_backup(self.package_path, self.database_path)
        self.assertEqual(self._setting(self.database_path), "before")

    def test_snapshot_can_be_exported_from_a_first_run_without_database_file(self) -> None:
        empty_database = self.root / "not-created-yet.sqlite3"
        target = self.root / "empty.wxbak"
        result = export_backup(empty_database, target)
        self.assertTrue(target.is_file())
        self.assertEqual(result["summary"]["legacy"]["keys_present"], 0)
        self.assertFalse(empty_database.exists())

    def test_encrypted_v1_legacy_backup_accepts_password_and_restores(self) -> None:
        plain = self.root / "legacy.json"
        encrypted = self.root / "legacy.wxbackup"
        password = "synthetic-v1-password"
        self._write_old_full_backup(plain)
        encrypted.write_text(
            encrypt_snapshot(json.loads(plain.read_text(encoding="utf-8")), password),
            encoding="utf-8",
        )

        preview = preview_encrypted_backup(encrypted, password)
        self.assertEqual(preview["sourceFormat"], "daily-atlas-backup-v1-encrypted")
        self.assertEqual(preview["summary"]["legacy"]["records"], 1)
        restored = restore_encrypted_backup(encrypted, self.database_path, password)
        self.assertEqual(restored["sourceFormat"], "daily-atlas-backup-v1-encrypted")
        self.assertEqual(
            load_imported_data(self.database_path)["entities"]["records"][0]["id"],
            "legacy-record",
        )

    def test_encrypted_v1_wrong_password_and_tampering_leave_database_unchanged(self) -> None:
        plain = self.root / "legacy.json"
        encrypted = self.root / "legacy.wxbackup"
        self._write_old_full_backup(plain)
        envelope = json.loads(
            encrypt_snapshot(
                json.loads(plain.read_text(encoding="utf-8")), "synthetic-v1-password"
            )
        )
        encrypted.write_text(json.dumps(envelope), encoding="utf-8")
        before = hashlib.sha256(self.database_path.read_bytes()).hexdigest()

        with self.assertRaises(BackupError):
            restore_encrypted_backup(encrypted, self.database_path, "wrong-password")
        self.assertEqual(hashlib.sha256(self.database_path.read_bytes()).hexdigest(), before)
        self.assertEqual(self._setting(self.database_path), "before")

        ciphertext = bytearray(base64.b64decode(envelope["ciphertext"], validate=True))
        ciphertext[0] ^= 1
        envelope["ciphertext"] = base64.b64encode(ciphertext).decode("ascii")
        encrypted.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaises(BackupError):
            restore_encrypted_backup(encrypted, self.database_path, "synthetic-v1-password")
        self.assertEqual(hashlib.sha256(self.database_path.read_bytes()).hexdigest(), before)
        self.assertEqual(self._setting(self.database_path), "before")

    def test_native_v2_encrypted_export_preview_and_restore_round_trip(self) -> None:
        encrypted = self.root / "native-private.wxbak2"
        password = "synthetic-native-password"
        exported = export_encrypted_backup(self.database_path, encrypted, password)
        self.assertTrue(encrypted.is_file())
        envelope = json.loads(encrypted.read_text(encoding="utf-8"))
        self.assertEqual(envelope["format"], "wanxiang-encrypted-backup")
        self.assertEqual(envelope["version"], 2)
        self.assertEqual(envelope["payloadFormat"], "wanxiang-native-backup")
        self.assertEqual(envelope["payloadVersion"], 1)

        preview = preview_encrypted_backup(encrypted, password)
        self.assertEqual(preview["sourceFormat"], "wanxiang-native-backup-encrypted-v2")
        self.assertEqual(preview["summary"], exported["summary"])
        self._make_database(self.database_path, "after-export")
        restored = restore_encrypted_backup(encrypted, self.database_path, password)
        self.assertEqual(restored["summary"], exported["summary"])
        self.assertEqual(self._setting(self.database_path), "before")

    def test_malformed_native_envelope_does_not_change_database(self) -> None:
        encrypted = self.root / "broken.wxbak2"
        encrypted.write_text(
            json.dumps({
                "format": "wanxiang-encrypted-backup",
                "version": 2,
                "payloadFormat": "another-app-format",
                "payloadVersion": 1,
                "kdf": "PBKDF2-HMAC-SHA256",
                "iterations": 600000,
                "cipher": "AES-256-GCM",
                "salt": "AA==",
                "iv": "AA==",
                "ciphertext": "AA==",
            }),
            encoding="utf-8",
        )
        before = hashlib.sha256(self.database_path.read_bytes()).hexdigest()
        with self.assertRaises(BackupError):
            restore_encrypted_backup(encrypted, self.database_path, "synthetic-password")
        self.assertEqual(hashlib.sha256(self.database_path.read_bytes()).hexdigest(), before)

    def test_native_encrypted_backup_keeps_legacy_password_length_bounds(self) -> None:
        target = self.root / "password-bounds.wxbak2"
        with self.assertRaisesRegex(BackupError, "至少需要 12 个字符"):
            export_encrypted_backup(self.database_path, target, "too-short")
        with self.assertRaisesRegex(BackupError, "256 字节"):
            export_encrypted_backup(self.database_path, target, "😀" * 65)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
