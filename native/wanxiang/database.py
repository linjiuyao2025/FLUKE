from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from pathlib import Path
import json
import sqlite3
from typing import Any

from .migration import (
    PACKAGE_FORMAT,
    MigrationPackage,
    SOURCE_IDENTITY,
    STORAGE_KEYS,
    STORAGE_KEYS_BY_SCHEMA,
    _make_summary,
    calculate_checksum,
    compact_json,
    validate_package,
)


SCHEMA_VERSION = 2
PREVIOUS_SCHEMA_VERSION = 1

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS schema_info (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        schema_version INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS migration_batches (
        batch_id TEXT PRIMARY KEY,
        source_identity TEXT NOT NULL,
        source_version TEXT NOT NULL,
        source_schema_version INTEGER NOT NULL,
        exported_at TEXT NOT NULL,
        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        checksum_sha256 TEXT NOT NULL,
        UNIQUE (source_identity, checksum_sha256),
        UNIQUE (batch_id, source_identity)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS migration_sources (
        source_identity TEXT PRIMARY KEY,
        active_batch_id TEXT NOT NULL UNIQUE,
        activated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (active_batch_id, source_identity)
            REFERENCES migration_batches(batch_id, source_identity) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS legacy_storage (
        batch_id TEXT NOT NULL REFERENCES migration_batches(batch_id) ON DELETE CASCADE,
        storage_key TEXT NOT NULL,
        raw_value TEXT,
        PRIMARY KEY (batch_id, storage_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS json_documents (
        batch_id TEXT NOT NULL REFERENCES migration_batches(batch_id) ON DELETE CASCADE,
        document_key TEXT NOT NULL,
        document_json TEXT NOT NULL,
        PRIMARY KEY (batch_id, document_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS records (
        record_row_id INTEGER PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES migration_batches(batch_id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        legacy_id TEXT,
        record_type TEXT,
        record_date TEXT,
        payload_json TEXT NOT NULL,
        UNIQUE (batch_id, position)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS habits (
        habit_row_id INTEGER PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES migration_batches(batch_id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        legacy_id TEXT,
        habit_key TEXT,
        payload_json TEXT NOT NULL,
        UNIQUE (batch_id, position)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS media_items (
        media_row_id INTEGER PRIMARY KEY,
        batch_id TEXT NOT NULL REFERENCES migration_batches(batch_id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        legacy_id TEXT,
        name TEXT,
        media_type TEXT,
        status TEXT,
        item_date TEXT,
        payload_json TEXT NOT NULL,
        UNIQUE (batch_id, position)
    )
    """,
    "CREATE INDEX IF NOT EXISTS records_by_type_date ON records(record_type, record_date)",
    "CREATE INDEX IF NOT EXISTS habits_by_key ON habits(habit_key)",
    "CREATE INDEX IF NOT EXISTS media_by_date ON media_items(item_date)",
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL
    )
    """,
)

ENTITY_TABLES = ("records", "habits", "media_items")
EMPTY_SUMMARY = {
    "keys_total": len(STORAGE_KEYS),
    "keys_present": 0,
    "records": 0,
    "habits": 0,
    "media_items": 0,
    "active_issue": 0,
    "archived_issues": 0,
    "questions": 0,
    "topics": 0,
    "clippings": 0,
}
_EXPECTED_ACTIVE_UNSET = object()


def _empty_import_data(status: str, error: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "hasData": False,
        "summary": dict(EMPTY_SUMMARY),
        "raw_values": {key: None for key in STORAGE_KEYS},
        "documents": {},
        "entities": {table: [] for table in ENTITY_TABLES},
        "import_info": None,
        "error": error,
    }


def _readonly_connection(database_path: Path) -> sqlite3.Connection:
    uri = f"{database_path.expanduser().resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
    try:
        connection.execute("PRAGMA query_only = ON")
        return connection
    except Exception:
        connection.close()
        raise


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _migration_batch_v1_sql() -> str:
    return """
        CREATE TABLE migration_batches_v2 (
            batch_id TEXT PRIMARY KEY,
            source_identity TEXT NOT NULL,
            source_version TEXT NOT NULL,
            source_schema_version INTEGER NOT NULL,
            exported_at TEXT NOT NULL,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            checksum_sha256 TEXT NOT NULL,
            UNIQUE (source_identity, checksum_sha256),
            UNIQUE (batch_id, source_identity)
        )
    """


def _validate_v1_schema_for_upgrade(connection: sqlite3.Connection) -> None:
    required_tables = {
        "schema_info",
        "migration_batches",
        "legacy_storage",
        "json_documents",
        *ENTITY_TABLES,
    }
    if not required_tables.issubset(_table_names(connection)):
        raise RuntimeError("旧版 SQLite 迁移表结构不完整，未执行升级")

    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(migration_batches)")
    }
    expected_columns = {
        "batch_id",
        "source_identity",
        "source_version",
        "source_schema_version",
        "exported_at",
        "imported_at",
        "checksum_sha256",
    }
    if columns != expected_columns:
        raise RuntimeError("旧版 SQLite 迁移批次结构无法安全升级")

    duplicate_source = connection.execute(
        "SELECT source_identity FROM migration_batches "
        "GROUP BY source_identity HAVING COUNT(*) > 1 LIMIT 1"
    ).fetchone()
    if duplicate_source is not None:
        raise RuntimeError("SQLite 旧版迁移存在重复来源批次，未执行升级")

    unique_indexes = connection.execute(
        "PRAGMA index_list(migration_batches)"
    ).fetchall()
    has_source_identity_unique = False
    for index in unique_indexes:
        # index_list columns are seq, name, unique, origin, partial. Older
        # SQLite versions without the partial field can only expose complete
        # indexes, so treating an absent field as false remains safe.
        if not bool(index[2]) or (len(index) > 4 and bool(index[4])):
            continue
        index_name = str(index[1]).replace('"', '""')
        indexed_columns = tuple(
            row[2]
            for row in connection.execute(f'PRAGMA index_info("{index_name}")')
        )
        if indexed_columns == ("source_identity",):
            has_source_identity_unique = True
            break
    if not has_source_identity_unique:
        raise RuntimeError("SQLite 来源索引不是完整唯一索引，未执行升级")

    for table in ("legacy_storage", "json_documents", *ENTITY_TABLES):
        foreign_keys = connection.execute(
            f'PRAGMA foreign_key_list("{table}")'
        ).fetchall()
        if not any(
            row[2] == "migration_batches"
            and row[3] == "batch_id"
            and row[4] == "batch_id"
            and row[6].upper() == "CASCADE"
            for row in foreign_keys
        ):
            raise RuntimeError(
                f"旧版 SQLite 表 {table} 缺少预期的 batch 外键，未执行升级"
            )


def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
    _validate_v1_schema_for_upgrade(connection)
    connection.execute(_migration_batch_v1_sql())
    connection.execute(
        """
        INSERT INTO migration_batches_v2(
            batch_id, source_identity, source_version, source_schema_version,
            exported_at, imported_at, checksum_sha256
        )
        SELECT batch_id, source_identity, source_version, source_schema_version,
               exported_at, imported_at, checksum_sha256
        FROM migration_batches
        """
    )
    # Child tables keep their REFERENCES migration_batches(batch_id) clauses.
    # With foreign keys disabled for this DDL transaction, replacing the parent
    # under the same name preserves those references and every child row.
    connection.execute("DROP TABLE migration_batches")
    connection.execute(
        "ALTER TABLE migration_batches_v2 RENAME TO migration_batches"
    )


def _populate_missing_active_sources(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT b.source_identity, b.batch_id, b.imported_at
        FROM migration_batches AS b
        WHERE NOT EXISTS (
            SELECT 1 FROM migration_sources AS s
            WHERE s.source_identity = b.source_identity
        )
        ORDER BY b.source_identity, b.imported_at DESC, b.batch_id DESC
        """
    ).fetchall()
    for source_identity, batch_id, imported_at in rows:
        connection.execute(
            "INSERT INTO migration_sources(source_identity, active_batch_id, activated_at) "
            "VALUES (?, ?, ?) ON CONFLICT(source_identity) DO NOTHING",
            (source_identity, batch_id, imported_at),
        )


def _validate_active_sources(connection: sqlite3.Connection) -> None:
    missing = connection.execute(
        """
        SELECT b.source_identity
        FROM migration_batches AS b
        LEFT JOIN migration_sources AS s
          ON s.source_identity = b.source_identity
        WHERE s.source_identity IS NULL
        LIMIT 1
        """
    ).fetchone()
    if missing is not None:
        raise RuntimeError(
            "SQLite migration history has no active source pointer; refusing to guess"
        )


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create the current schema or atomically upgrade the supported v1 schema."""
    if connection.in_transaction:
        raise RuntimeError("initialize_schema must run outside a transaction")

    foreign_keys_were_enabled = bool(
        connection.execute("PRAGMA foreign_keys").fetchone()[0]
    )
    tables = _table_names(connection)
    has_schema = "schema_info" in tables
    if has_schema:
        version_row = connection.execute(
            "SELECT schema_version FROM schema_info WHERE singleton = 1"
        ).fetchone()
        version = version_row[0] if version_row is not None else None
        if version not in (SCHEMA_VERSION, PREVIOUS_SCHEMA_VERSION):
            raise RuntimeError(
                f"SQLite schema version {version!r} is not supported by this importer"
            )
    else:
        version = None
        if tables.intersection(
            {"migration_batches", "legacy_storage", "json_documents", *ENTITY_TABLES}
        ):
            raise RuntimeError("SQLite migration schema is incomplete; refusing to initialize")

    upgrading_v1 = version == PREVIOUS_SCHEMA_VERSION
    if upgrading_v1:
        connection.execute("PRAGMA foreign_keys = OFF")

    try:
        connection.execute("BEGIN IMMEDIATE")
        if upgrading_v1:
            _migrate_v1_to_v2(connection)

        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)

        if version is None:
            connection.execute(
                "INSERT INTO schema_info(singleton, schema_version) VALUES (1, ?)",
                (SCHEMA_VERSION,),
            )
        elif version == PREVIOUS_SCHEMA_VERSION:
            connection.execute(
                "UPDATE schema_info SET schema_version = ? WHERE singleton = 1",
                (SCHEMA_VERSION,),
            )

        if upgrading_v1:
            # v1 allowed only one batch per source, so its active snapshot is
            # unambiguous. v2 history may contain archived revisions; never
            # infer its active pointer during ordinary initialization.
            _populate_missing_active_sources(connection)
        elif version == SCHEMA_VERSION:
            _validate_active_sources(connection)

        foreign_key_error = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchone()
        if foreign_key_error is not None:
            raise sqlite3.IntegrityError(
                "SQLite schema upgrade would leave a broken foreign-key relationship"
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        if foreign_keys_were_enabled:
            connection.execute("PRAGMA foreign_keys = ON")


def initialize_database(database_path: str | Path) -> None:
    """Ensure a database file is at the current schema before app services start."""
    path = Path(database_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        initialize_schema(connection)
    finally:
        connection.close()


def _strict_json_loads(value: str) -> Any:
    def reject_constant(constant: str) -> None:
        raise ValueError(f"non-standard JSON constant: {constant}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = item
        return result

    return json.loads(
        value,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicate_keys,
    )


def _stored_entity_rows(
    connection: sqlite3.Connection, batch_id: str, table: str
) -> list[tuple[Any, ...]]:
    if table == "records":
        columns = "position, legacy_id, record_type, record_date, payload_json"
    elif table == "habits":
        columns = "position, legacy_id, habit_key, payload_json"
    elif table == "media_items":
        columns = (
            "position, legacy_id, name, media_type, status, item_date, payload_json"
        )
    else:
        raise AssertionError(f"Unknown entity table: {table}")
    return connection.execute(
        f"SELECT {columns} FROM {table} WHERE batch_id = ? ORDER BY position",
        (batch_id,),
    ).fetchall()


def _validate_entity_projection(
    connection: sqlite3.Connection,
    batch_id: str,
    table: str,
    expected_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fail closed if an entity table differs from its source document array."""
    rows = _stored_entity_rows(connection, batch_id, table)
    if len(rows) != len(expected_items):
        raise ValueError(f"{table} entity count does not match the source document")

    decoded: list[dict[str, Any]] = []
    for position, (row, item) in enumerate(zip(rows, expected_items)):
        stored_row = list(row)
        stored_payload = _strict_json_loads(stored_row[-1])
        if not isinstance(stored_payload, dict):
            raise ValueError(f"{table} entity payload is not an object")
        # Older schema v1 databases serialized entity object keys in insertion
        # order. Compare canonical JSON so those valid snapshots remain readable.
        stored_row[-1] = compact_json(stored_payload)
        if table == "records":
            expected_row = (
                position,
                _optional_text(item.get("id")),
                _optional_text(item.get("type")),
                _optional_text(item.get("date")),
                compact_json(item),
            )
        elif table == "habits":
            expected_row = (
                position,
                _optional_text(item.get("id")),
                _optional_text(item.get("key")),
                compact_json(item),
            )
        else:
            expected_row = (
                position,
                _optional_text(item.get("id")),
                _optional_text(item.get("name")),
                _optional_text(item.get("type")),
                _optional_text(item.get("status")),
                _optional_text(item.get("date")),
                compact_json(item),
            )
        if tuple(stored_row) != expected_row:
            raise ValueError(f"{table} entity projection does not match the source document")
        decoded.append(item)
    return decoded


def load_imported_data(database_path: str | Path) -> dict[str, Any]:
    """Read the latest imported legacy snapshot without creating or changing the DB."""
    path = Path(database_path).expanduser()
    if not path.is_file():
        return _empty_import_data("empty")

    connection: sqlite3.Connection | None = None
    try:
        connection = _readonly_connection(path)
        connection.execute("BEGIN")
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        migration_tables = {
            "schema_info",
            "migration_batches",
            "migration_sources",
            "legacy_storage",
            "json_documents",
            *ENTITY_TABLES,
        }
        if not table_names.intersection(migration_tables):
            connection.rollback()
            return _empty_import_data("empty")
        if "schema_info" not in table_names or "migration_batches" not in table_names:
            raise ValueError("incomplete migration schema")
        version_row = connection.execute(
            "SELECT schema_version FROM schema_info WHERE singleton = 1"
        ).fetchone()
        if version_row is None or version_row[0] not in (
            PREVIOUS_SCHEMA_VERSION,
            SCHEMA_VERSION,
        ):
            raise ValueError("unsupported migration schema")
        schema_version = version_row[0]
        required_tables = migration_tables - {"schema_info", "migration_sources"}
        if schema_version == SCHEMA_VERSION:
            required_tables.add("migration_sources")
        if not required_tables.issubset(table_names):
            raise ValueError("incomplete migration schema")

        if schema_version == SCHEMA_VERSION:
            batch = connection.execute(
                """
                SELECT b.batch_id, b.source_identity, b.source_version,
                       b.source_schema_version, b.exported_at, b.imported_at,
                       b.checksum_sha256
                FROM migration_sources AS s
                JOIN migration_batches AS b
                  ON b.batch_id = s.active_batch_id
                 AND b.source_identity = s.source_identity
                WHERE s.source_identity = ?
                """,
                (SOURCE_IDENTITY,),
            ).fetchone()
        else:
            # Read v1 databases without mutating them. The application entry
            # point upgrades them before repositories begin writing.
            batch = connection.execute(
                """
                SELECT batch_id, source_identity, source_version, source_schema_version,
                       exported_at, imported_at, checksum_sha256
                FROM migration_batches
                WHERE source_identity = ?
                ORDER BY imported_at DESC, batch_id DESC
                LIMIT 1
                """,
                (SOURCE_IDENTITY,),
            ).fetchone()
        if batch is None:
            if schema_version == SCHEMA_VERSION and connection.execute(
                "SELECT 1 FROM migration_batches WHERE source_identity = ? LIMIT 1",
                (SOURCE_IDENTITY,),
            ).fetchone():
                raise ValueError("migration history has no active source pointer")
            connection.rollback()
            return _empty_import_data("empty")

        batch_id = batch[0]
        raw_rows = connection.execute(
            "SELECT storage_key, raw_value FROM legacy_storage WHERE batch_id = ?",
            (batch_id,),
        ).fetchall()
        package_keys = STORAGE_KEYS_BY_SCHEMA.get(batch[3])
        if package_keys is None:
            raise ValueError("active migration batch uses an unsupported package version")
        if len(raw_rows) != len(package_keys) or {
            key for key, _ in raw_rows
        } != set(package_keys):
            raise ValueError("active migration batch does not match its package key list")
        stored_raw_values = {key: value for key, value in raw_rows}

        actual_checksum = calculate_checksum(stored_raw_values, batch[3])
        if actual_checksum != batch[6]:
            raise ValueError("active migration storage checksum does not match its metadata")

        # Reuse the package validator as the single schema authority. The two
        # legacy marker keys (samples-cleared and saved-knowledge) intentionally
        # retain their original non-JSON string values and have no JSON document.
        validated_package = validate_package(
            {
                "format": PACKAGE_FORMAT,
                "schemaVersion": batch[3],
                "sourceVersion": batch[2],
                "exportedAt": batch[4],
                "keys": stored_raw_values,
                "checksum": actual_checksum,
            }
        )

        document_rows = connection.execute(
            "SELECT document_key, document_json FROM json_documents "
            "WHERE batch_id = ?",
            (batch_id,),
        ).fetchall()
        documents = {
            key: _strict_json_loads(value) for key, value in document_rows
        }
        expected_documents = validated_package.parsed_values
        if len(document_rows) != len(expected_documents) or {
            key: compact_json(value) for key, value in documents.items()
        } != {
            key: compact_json(value) for key, value in expected_documents.items()
        }:
            raise ValueError("parsed JSON documents do not match the validated source keys")

        state = expected_documents.get("richangji-state-v1") or {}
        entities = {
            "records": _validate_entity_projection(
                connection, batch_id, "records", state.get("records") or []
            ),
            "habits": _validate_entity_projection(
                connection, batch_id, "habits", state.get("habits") or []
            ),
            "media_items": _validate_entity_projection(
                connection, batch_id, "media_items", state.get("mediaItems") or []
            ),
        }
        connection.commit()

        summary = _make_summary(stored_raw_values, documents, package_keys)
        raw_values = stored_raw_values
        for table in ENTITY_TABLES:
            summary[table] = len(entities[table])
        return {
            "status": "loaded",
            "hasData": True,
            "summary": summary,
            "raw_values": raw_values,
            "documents": documents,
            "entities": entities,
            "import_info": {
                "batch_id": batch[0],
                "source_identity": batch[1],
                "source_version": batch[2],
                "source_schema_version": batch[3],
                "exported_at": batch[4],
                "imported_at": batch[5],
                "checksum_sha256": batch[6],
            },
            "error": None,
        }
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
    ):
        return _empty_import_data("unavailable", "数据库结构或内容无法读取")
    finally:
        if connection is not None:
            connection.close()


def get_app_setting(
    database_path: str | Path, key: str, default: Any = None
) -> Any:
    """Read one JSON setting; missing, invalid, or unavailable values use default."""
    if not isinstance(key, str) or not key:
        return default
    path = Path(database_path).expanduser()
    if not path.is_file():
        return default
    connection: sqlite3.Connection | None = None
    try:
        connection = _readonly_connection(path)
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_settings'"
        ).fetchone()
        if table is None:
            return default
        row = connection.execute(
            "SELECT value_json FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return _strict_json_loads(row[0])
        except (ValueError, TypeError, json.JSONDecodeError):
            return default
    except (OSError, sqlite3.Error, ValueError):
        return default
    finally:
        if connection is not None:
            connection.close()


def set_app_setting(database_path: str | Path, key: str, value: Any) -> None:
    """Atomically store a JSON-compatible setting in the local SQLite database."""
    set_app_settings(database_path, {key: value})


def set_app_settings(database_path: str | Path, values: dict[str, Any]) -> None:
    """Atomically store a group of JSON-compatible settings."""
    if not isinstance(values, dict) or not values:
        raise ValueError("settings must be a non-empty object")
    encoded_values: list[tuple[str, str]] = []
    for key, value in values.items():
        if not isinstance(key, str) or not key:
            raise ValueError("setting key must be a non-empty string")
        value_json = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        encoded_values.append((key, value_json))
    path = Path(database_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        initialize_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(SCHEMA_STATEMENTS[-1])
        connection.executemany(
            """
            INSERT INTO app_settings(key, value_json) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            encoded_values,
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return compact_json(value)


def _insert_entities(
    connection: sqlite3.Connection,
    batch_id: str,
    table: str,
    items: list[dict[str, Any]],
) -> None:
    if table == "records":
        for position, item in enumerate(items):
            connection.execute(
                """
                INSERT INTO records(
                    batch_id, position, legacy_id, record_type, record_date, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    position,
                    _optional_text(item.get("id")),
                    _optional_text(item.get("type")),
                    _optional_text(item.get("date")),
                    compact_json(item),
                ),
            )
    elif table == "habits":
        for position, item in enumerate(items):
            connection.execute(
                """
                INSERT INTO habits(
                    batch_id, position, legacy_id, habit_key, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    position,
                    _optional_text(item.get("id")),
                    _optional_text(item.get("key")),
                    compact_json(item),
                ),
            )
    elif table == "media_items":
        for position, item in enumerate(items):
            connection.execute(
                """
                INSERT INTO media_items(
                    batch_id, position, legacy_id, name, media_type, status, item_date,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    position,
                    _optional_text(item.get("id")),
                    _optional_text(item.get("name")),
                    _optional_text(item.get("type")),
                    _optional_text(item.get("status")),
                    _optional_text(item.get("date")),
                    compact_json(item),
                ),
            )
    else:
        raise AssertionError(f"Unknown entity table: {table}")


def _existing_summary(connection: sqlite3.Connection, batch_id: str) -> dict[str, int]:
    raw_values = dict(
        connection.execute(
            "SELECT storage_key, raw_value FROM legacy_storage WHERE batch_id = ?",
            (batch_id,),
        ).fetchall()
    )
    parsed_values = {
        key: json.loads(document_json)
        for key, document_json in connection.execute(
            "SELECT document_key, document_json FROM json_documents WHERE batch_id = ?",
            (batch_id,),
        ).fetchall()
    }
    summary = _make_summary(raw_values, parsed_values)
    for table in ENTITY_TABLES:
        summary[table] = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE batch_id = ?", (batch_id,)
        ).fetchone()[0]
    return summary


def _entity_diff(
    previous: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> dict[str, int]:
    def grouped(items: list[dict[str, Any]]) -> dict[str, Counter[str]]:
        result: dict[str, Counter[str]] = {}
        for position, item in enumerate(items):
            identity = _optional_text(item.get("id"))
            stable_key = f"id:{identity}" if identity is not None else f"position:{position}"
            result.setdefault(stable_key, Counter())[compact_json(item)] += 1
        return result

    old_by_id = grouped(previous)
    new_by_id = grouped(incoming)
    unchanged = 0
    changed = 0
    added = 0
    removed = 0
    for stable_key in old_by_id.keys() | new_by_id.keys():
        old_payloads = old_by_id.get(stable_key, Counter())
        new_payloads = new_by_id.get(stable_key, Counter())
        exact = old_payloads & new_payloads
        exact_count = sum(exact.values())
        unchanged += exact_count
        old_remaining = sum(old_payloads.values()) - exact_count
        new_remaining = sum(new_payloads.values()) - exact_count
        changed_count = min(old_remaining, new_remaining)
        changed += changed_count
        removed += old_remaining - changed_count
        added += new_remaining - changed_count
    return {
        "before": len(previous),
        "after": len(incoming),
        "unchanged": unchanged,
        "changed": changed,
        "added": added,
        "removed": removed,
    }


def _history_batch(
    connection: sqlite3.Connection, checksum: str
) -> tuple[str, bool] | None:
    batch = connection.execute(
        "SELECT batch_id FROM migration_batches "
        "WHERE source_identity = ? AND checksum_sha256 = ?",
        (SOURCE_IDENTITY, checksum),
    ).fetchone()
    if batch is None:
        return None
    tables = _table_names(connection)
    if "migration_sources" not in tables:
        return batch[0], True
    active = connection.execute(
        "SELECT active_batch_id FROM migration_sources WHERE source_identity = ?",
        (SOURCE_IDENTITY,),
    ).fetchone()
    return batch[0], bool(active and active[0] == batch[0])


def preview_import(
    package: MigrationPackage, database_path: str | Path
) -> dict[str, Any]:
    """Compare a validated package with the active snapshot without writing."""
    path = Path(database_path).expanduser()
    current = load_imported_data(path)
    if current.get("status") == "unavailable":
        raise RuntimeError(current.get("error") or "无法安全读取当前迁移快照。")
    has_active = bool(current.get("hasData"))
    current_raw = current.get("raw_values", {})
    key_changes: list[dict[str, str]] = []
    change_counts = {name: 0 for name in ("added", "removed", "changed", "unchanged", "empty")}
    for key in package.raw_values:
        previous = current_raw.get(key)
        incoming = package.raw_values.get(key)
        if not has_active:
            change = "added" if incoming is not None else "empty"
        elif previous == incoming:
            change = "unchanged"
        elif previous is None:
            change = "added"
        elif incoming is None:
            change = "removed"
        else:
            change = "changed"
        change_counts[change] += 1
        key_changes.append({"key": key, "change": change})

    previous_entities = current.get("entities", {})
    incoming_state = package.parsed_values.get("richangji-state-v1") or {}
    incoming_entities = {
        "records": incoming_state.get("records") or [],
        "habits": incoming_state.get("habits") or [],
        "media_items": incoming_state.get("mediaItems") or [],
    }
    entity_changes = {
        table: _entity_diff(
            list(previous_entities.get(table, [])) if has_active else [],
            list(incoming_entities[table]),
        )
        for table in ENTITY_TABLES
    }

    history: tuple[str, bool] | None = None
    if path.is_file():
        connection: sqlite3.Connection | None = None
        try:
            connection = _readonly_connection(path)
            tables = _table_names(connection)
            if "migration_batches" in tables:
                history = _history_batch(connection, package.checksum)
        except sqlite3.Error as exc:
            raise RuntimeError("无法安全检查已保存的迁移批次。") from exc
        finally:
            if connection is not None:
                connection.close()

    active_checksum = None
    if current.get("import_info"):
        active_checksum = current["import_info"].get("checksum_sha256")
    if not has_active:
        status = "new"
    elif active_checksum == package.checksum:
        status = "same_snapshot"
    else:
        status = "new_snapshot"
    historical_inactive = bool(history and not history[1])
    return {
        "status": status,
        "checksum": package.checksum,
        "currentChecksum": active_checksum,
        "historyContainsChecksum": history is not None,
        "historicalInactive": historical_inactive,
        "canApply": not historical_inactive,
        "willActivate": status in ("new", "new_snapshot") and not historical_inactive,
        "summary": dict(package.summary),
        "currentSummary": dict(current.get("summary", EMPTY_SUMMARY)),
        "keyChanges": key_changes,
        "keyChangeCounts": change_counts,
        "entityChanges": entity_changes,
    }


@dataclass(frozen=True)
class ImportResult:
    status: str
    batch_id: str
    checksum: str
    summary: dict[str, int]
    database_path: str
    is_active: bool


def import_package(
    package: MigrationPackage,
    database_path: str | Path,
    *,
    expected_active_checksum: str | None | object = _EXPECTED_ACTIVE_UNSET,
) -> ImportResult:
    """Store one immutable snapshot and atomically select it as active."""
    database_path = database_path.expanduser().resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path), timeout=30, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        initialize_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        try:
            active = connection.execute(
                """
                SELECT b.batch_id, b.checksum_sha256
                FROM migration_sources AS s
                JOIN migration_batches AS b
                  ON b.batch_id = s.active_batch_id
                 AND b.source_identity = s.source_identity
                WHERE s.source_identity = ?
                """,
                (SOURCE_IDENTITY,),
            ).fetchone()
            active_checksum = active[1] if active else None
            if (
                expected_active_checksum is not _EXPECTED_ACTIVE_UNSET
                and active_checksum != expected_active_checksum
            ):
                raise RuntimeError("当前迁移快照已变化，请重新预览后再确认。")

            existing = connection.execute(
                "SELECT batch_id FROM migration_batches "
                "WHERE source_identity = ? AND checksum_sha256 = ?",
                (SOURCE_IDENTITY, package.checksum),
            ).fetchone()
            if existing:
                connection.rollback()
                return ImportResult(
                    status="already_imported",
                    batch_id=existing[0],
                    checksum=package.checksum,
                    summary=_existing_summary(connection, existing[0]),
                    database_path=str(database_path),
                    is_active=bool(active and active[0] == existing[0]),
                )

            batch_id = package.checksum
            connection.execute(
                """
                INSERT INTO migration_batches(
                    batch_id, source_identity, source_version, source_schema_version,
                    exported_at, checksum_sha256
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    SOURCE_IDENTITY,
                    package.source_version,
                    package.schema_version,
                    package.exported_at,
                    package.checksum,
                ),
            )

            for key, raw_value in package.raw_values.items():
                connection.execute(
                    "INSERT INTO legacy_storage(batch_id, storage_key, raw_value) "
                    "VALUES (?, ?, ?)",
                    (batch_id, key, raw_value),
                )

            for key, value in package.parsed_values.items():
                connection.execute(
                    "INSERT INTO json_documents(batch_id, document_key, document_json) "
                    "VALUES (?, ?, ?)",
                    (batch_id, key, compact_json(value)),
                )

            state = package.parsed_values.get("richangji-state-v1") or {}
            _insert_entities(connection, batch_id, "records", state.get("records") or [])
            _insert_entities(connection, batch_id, "habits", state.get("habits") or [])
            _insert_entities(
                connection, batch_id, "media_items", state.get("mediaItems") or []
            )
            connection.execute(
                """
                INSERT INTO migration_sources(
                    source_identity, active_batch_id, activated_at
                ) VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source_identity) DO UPDATE SET
                    active_batch_id = excluded.active_batch_id,
                    activated_at = excluded.activated_at
                """,
                (SOURCE_IDENTITY, batch_id),
            )
            connection.commit()
            return ImportResult(
                status="imported",
                batch_id=batch_id,
                checksum=package.checksum,
                summary=dict(package.summary),
                database_path=str(database_path),
                is_active=True,
            )
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()
