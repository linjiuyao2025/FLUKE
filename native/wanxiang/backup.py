"""Private, whole-database backup and restore for the native application."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Callable
import zipfile

from .database import SCHEMA_VERSION, initialize_schema, load_imported_data
from .migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    MigrationPackageError,
    calculate_checksum,
    validate_package,
)


BACKUP_FORMAT = "wanxiang-native-backup"
BACKUP_VERSION = 1
DATABASE_MEMBER = "wanxiang.sqlite3"
MANIFEST_MEMBER = "manifest.json"
MAX_DATABASE_BYTES = 50 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
MAX_PACKAGE_BYTES = MAX_DATABASE_BYTES + 128 * 1024

_MIGRATION_TABLES = {
    "schema_info",
    "migration_batches",
    "migration_sources",
    "legacy_storage",
    "json_documents",
    "records",
    "habits",
    "media_items",
}
_KNOWN_NATIVE_TABLES = {
    *_MIGRATION_TABLES,
    "app_settings",
    "habit_module_state",
    "issue_preferences_state",
    "reading_module_state",
    "daily_flow_state",
    "finance_module_state",
    "fitness_module_state",
    "planner_module_state",
    "shopping_module_state",
    "media_module_state",
    "archive_module_state",
    "recommendation_schema",
    "article_feedback",
}


class BackupError(ValueError):
    """Readable error for invalid backup packages or failed backup I/O."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BackupError("备份清单包含重复字段。")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise BackupError("备份清单含有无效数值。")


def _strict_json(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_MANIFEST_BYTES:
        raise BackupError("备份清单过大。")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except BackupError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise BackupError("备份清单不是有效的 UTF-8 JSON。") from exc
    if not isinstance(value, dict):
        raise BackupError("备份清单必须是对象。")
    return value


def _readonly_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _snapshot_database(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    destination: sqlite3.Connection | None = None
    source: sqlite3.Connection | None = None
    try:
        destination = sqlite3.connect(str(target_path), timeout=30)
        if source_path.is_file():
            source = sqlite3.connect(_readonly_uri(source_path), uri=True, timeout=30)
            source.execute("PRAGMA query_only = ON")
            source.backup(destination, pages=256, sleep=0.01)
        else:
            initialize_schema(destination)
        destination.commit()
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        raise BackupError("无法生成一致的本机数据快照。") from exc
    finally:
        if source is not None:
            source.close()
        if destination is not None:
            destination.close()


def _database_summary(database_path: Path) -> dict[str, Any]:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(_readonly_uri(database_path), uri=True, timeout=10)
        connection.execute("PRAGMA query_only = ON")
        check = connection.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise BackupError("备份数据库完整性检查未通过。")
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_errors is not None:
            raise BackupError("备份数据库的关联记录检查未通过。")

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not tables.intersection(_KNOWN_NATIVE_TABLES):
            raise BackupError("所选数据库不是 FLUKE 原生版数据文件。")
        has_migration_schema = bool(tables.intersection(_MIGRATION_TABLES))
        if has_migration_schema:
            version = connection.execute(
                "SELECT schema_version FROM schema_info WHERE singleton=1"
            ).fetchone()
            if version is None or version[0] not in (1, SCHEMA_VERSION):
                raise BackupError("此备份使用了不支持的数据库版本。")
            required = _MIGRATION_TABLES - {"migration_sources"}
            required.add("app_settings")
            if version[0] == SCHEMA_VERSION:
                required.add("migration_sources")
            if not required.issubset(tables):
                raise BackupError("迁移数据表结构不完整，无法安全备份或恢复。")
        else:
            version = None

        # The preview loader opens its own read-only connection. Close this
        # validation connection first so Windows can later atomically replace
        # the staged database file.
        connection.close()
        connection = None
        if has_migration_schema:
            imported = load_imported_data(database_path)
            if imported.get("status") == "unavailable":
                raise BackupError(imported.get("error") or "迁移数据无法读取。")
            summary = imported.get("summary", {})
        else:
            summary = {}

        return {
            "schemaVersion": version[0] if version is not None else None,
            "tables": len(tables),
            "legacy": {
                key: int(summary.get(key, 0) or 0)
                for key in (
                    "keys_present",
                    "records",
                    "habits",
                    "media_items",
                    "active_issue",
                    "archived_issues",
                    "questions",
                    "topics",
                    "clippings",
                )
            },
        }
    except BackupError:
        raise
    except (OSError, sqlite3.Error, RuntimeError, TypeError, ValueError) as exc:
        raise BackupError("备份数据库结构或内容无法读取。") from exc
    finally:
        if connection is not None:
            connection.close()


def _manifest_for(snapshot_path: Path) -> dict[str, Any]:
    size = snapshot_path.stat().st_size
    if size > MAX_DATABASE_BYTES:
        raise BackupError("完整备份超过 50 MB，未生成文件。")
    digest = hashlib.sha256()
    with snapshot_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    summary = _database_summary(snapshot_path)
    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "exportedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "databaseBytes": size,
        "sha256": digest.hexdigest(),
        "schemaVersion": summary["schemaVersion"],
        "summary": summary,
    }


def export_backup(
    database_path: str | Path,
    target_path: str | Path,
    *,
    prepare_snapshot: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Write an atomic, checksummed snapshot containing every native SQLite table."""
    source = Path(database_path).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()
    if source == target:
        raise BackupError("备份文件不能覆盖正在使用的数据库。")
    if target.suffix.lower() != ".wxbak":
        raise BackupError("完整备份文件请使用 .wxbak 扩展名。")
    target.parent.mkdir(parents=True, exist_ok=True)

    package_temp: str | None = None
    with tempfile.TemporaryDirectory(prefix="fluke-backup-") as temp_dir:
        snapshot = Path(temp_dir) / "snapshot.sqlite3"
        _snapshot_database(source, snapshot)
        if prepare_snapshot is not None:
            try:
                prepare_snapshot(snapshot)
            except Exception as exc:
                raise BackupError("完整备份准备失败；当前数据库没有被修改。") from exc
        manifest = _manifest_for(snapshot)
        fd, package_temp = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        os.close(fd)
        try:
            with zipfile.ZipFile(
                package_temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                archive.writestr(
                    MANIFEST_MEMBER,
                    json.dumps(
                        manifest,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
                archive.write(snapshot, DATABASE_MEMBER)
            if Path(package_temp).stat().st_size > MAX_PACKAGE_BYTES:
                raise BackupError("完整备份文件超过允许大小。")
            os.replace(package_temp, target)
            package_temp = None
        except BackupError:
            raise
        except (OSError, RuntimeError, zipfile.BadZipFile, ValueError) as exc:
            raise BackupError("完整备份写入失败；已有文件未被替换。") from exc
        finally:
            if package_temp and os.path.exists(package_temp):
                os.unlink(package_temp)
        return {
            "path": str(target),
            "exportedAt": manifest["exportedAt"],
            "databaseBytes": manifest["databaseBytes"],
            "sha256": manifest["sha256"],
            "summary": manifest["summary"],
        }


def _check_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("format") != BACKUP_FORMAT or manifest.get("version") != BACKUP_VERSION:
        raise BackupError("这不是受支持的 FLUKE 原生完整备份。")
    exported_at = manifest.get("exportedAt")
    if not isinstance(exported_at, str) or not exported_at.strip():
        raise BackupError("备份时间字段无效。")
    try:
        datetime.fromisoformat(exported_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackupError("备份时间字段无效。") from exc
    size = manifest.get("databaseBytes")
    digest = manifest.get("sha256")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_DATABASE_BYTES:
        raise BackupError("备份数据大小字段无效。")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise BackupError("备份校验字段无效。")
    return manifest


def _read_legacy_backup(
    package_path: Path,
    current_database_path: Path | None = None,
) -> tuple[dict[str, Any], Any]:
    try:
        size = package_path.stat().st_size
        if size <= 0 or size > MAX_DATABASE_BYTES:
            raise BackupError("完整备份为空或超过 50 MB。")
        with package_path.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(
                stream,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_constant,
            )
    except BackupError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise BackupError("完整备份不是可读取的 UTF-8 JSON。") from exc

    if not isinstance(payload, dict) or payload.get("format") != "daily-atlas-backup":
        if isinstance(payload, dict) and payload.get("format") == PACKAGE_FORMAT:
            raise BackupError("这是旧版迁移包，请使用“导入旧版迁移包”。")
        raise BackupError("文件不是受支持的本机完整备份。")
    if type(payload.get("version")) is not int or payload["version"] != 1:
        raise BackupError("旧版完整备份格式版本不受支持。")
    state = payload.get("state")
    issue_content = payload.get("issueContent")
    if not isinstance(state, dict):
        raise BackupError("完整备份缺少主状态。")
    if not all(isinstance(state.get(key), list) for key in ("records", "habits", "mediaItems")):
        raise BackupError("完整备份的 records、habits、mediaItems 必须是数组。")
    if issue_content is not None and not isinstance(issue_content, dict):
        raise BackupError("完整备份的刊期内容结构无效。")
    exported_at = payload.get("exportedAt")
    if not isinstance(exported_at, str) or not exported_at:
        raise BackupError("完整备份缺少导出时间。")
    try:
        datetime.fromisoformat(exported_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BackupError("完整备份的导出时间无效。") from exc

    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    if current_database_path is not None:
        current = load_imported_data(current_database_path)
        if current.get("status") == "unavailable":
            raise BackupError(current.get("error") or "当前迁移数据无法安全读取。")
        raw = current.get("raw_values", {})
        raw_values.update({key: raw.get(key) for key in STORAGE_KEYS})
        questions = _read_daily_questions(current_database_path)
        if questions is not None:
            raw_values["wanxiang-issue-questions-v1"] = json.dumps(
                questions, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            )

    raw_values["richangji-state-v1"] = json.dumps(
        state, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )
    settings = state.get("settings", {})
    samples_cleared = settings.get("samplesCleared") if isinstance(settings, dict) else False
    raw_values["richangji-samples-cleared"] = "1" if samples_cleared else None
    if issue_content is not None:
        raw_values["wanxiang-daily-issues-v1"] = json.dumps(
            issue_content, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )

    migration_payload = {
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "daily-atlas-backup-v1",
        "exportedAt": exported_at,
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    }
    try:
        validated = validate_package(migration_payload)
    except MigrationPackageError as exc:
        raise BackupError(f"完整备份内容无法导入：{exc}") from exc
    except (TypeError, ValueError) as exc:
        raise BackupError("完整备份含有无法保存的数据。") from exc
    return payload, validated


def _read_daily_questions(database_path: Path) -> list[Any] | None:
    if not database_path.is_file():
        return None
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(_readonly_uri(database_path), uri=True, timeout=5)
        row = connection.execute(
            "SELECT state_json FROM daily_flow_state WHERE singleton=1"
        ).fetchone()
        if row is None:
            return None
        state = _strict_json(row[0].encode("utf-8"))
        questions = state.get("questions") if isinstance(state, dict) else None
        return questions if isinstance(questions, list) else None
    except sqlite3.Error:
        return None
    finally:
        if connection is not None:
            connection.close()


def _restore_legacy_backup(
    package_path: Path,
    database_path: Path,
) -> dict[str, Any]:
    payload, migration_package = _read_legacy_backup(package_path, database_path)
    with tempfile.TemporaryDirectory(prefix="fluke-legacy-restore-") as temp_dir:
        staging = Path(temp_dir) / "restored.sqlite3"
        _snapshot_database(database_path, staging)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(staging), timeout=30, isolation_level=None)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "migration_batches" in tables:
                connection.execute("DELETE FROM migration_batches")
            # These runtime overlays represent the main legacy state replaced
            # by the old complete backup. Independent local settings, reading
            # lists, article feedback, and weather remain in the copied DB.
            for table in (
                "habit_module_state",
                "finance_module_state",
                "fitness_module_state",
                "planner_module_state",
                "shopping_module_state",
                "media_module_state",
                "archive_module_state",
                "daily_flow_state",
            ):
                if table in tables:
                    connection.execute(f'DELETE FROM "{table}"')
            issue_content = payload.get("issueContent")
            if issue_content is not None and "app_settings" in tables:
                encoded = json.dumps(
                    issue_content, ensure_ascii=False, allow_nan=False, separators=(",", ":")
                )
                connection.execute(
                    "INSERT INTO app_settings(key,value_json) VALUES('dailyIssueStore',?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (encoded,),
                )
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise BackupError("备份恢复准备失败；原数据库未修改。") from exc
        finally:
            if connection is not None:
                connection.close()

        try:
            from .database import import_package

            import_package(migration_package, staging)
            # The old exporter serialized settings.brand inside ``state``.
            # Native edits live in app_settings, so clear only those explicit
            # overrides and rebase on the brand contained in the restored
            # state; unrelated native settings remain untouched.
            state = payload["state"]
            settings = state.get("settings", {})
            brand = settings.get("brand", {}) if isinstance(settings, dict) else {}
            if not isinstance(brand, dict):
                brand = {}
            brand_runtime = {
                "version": 1,
                "legacyBrand": brand,
                "settingsOverrides": {},
            }
            connection = sqlite3.connect(str(staging), timeout=30)
            try:
                connection.execute(
                    "INSERT INTO app_settings(key,value_json) VALUES('brandAppearance',?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (json.dumps(brand_runtime, ensure_ascii=False, allow_nan=False, separators=(",", ":")),),
                )
                connection.commit()
            finally:
                connection.close()
            summary = _database_summary(staging)
        except (OSError, RuntimeError, sqlite3.Error, ValueError, TypeError) as exc:
            raise BackupError("旧版完整备份无法写入临时数据库；原数据库未修改。") from exc

        sidecars = [Path(f"{database_path}{suffix}") for suffix in ("-wal", "-shm", "-journal")]
        if any(path.exists() and path.stat().st_size for path in sidecars):
            raise BackupError("当前数据库仍被使用；关闭其他窗口后再恢复。")
        try:
            os.replace(staging, database_path)
        except OSError as exc:
            raise BackupError("恢复文件替换失败；原数据库未修改。") from exc
    return {
        "path": str(database_path),
        "exportedAt": payload["exportedAt"],
        "summary": summary,
        "sourceFormat": "daily-atlas-backup-v1",
    }


def _unpack_and_validate(package_path: Path, staging_path: Path) -> dict[str, Any]:
    if not package_path.is_file():
        raise BackupError("所选备份文件不存在。")
    try:
        package_size = package_path.stat().st_size
        if package_size <= 0 or package_size > MAX_PACKAGE_BYTES:
            raise BackupError("备份文件为空或超过 50 MB。")
        with zipfile.ZipFile(package_path, "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(infos) != 2 or len(set(names)) != 2 or set(names) != {
                MANIFEST_MEMBER,
                DATABASE_MEMBER,
            }:
                raise BackupError("备份文件结构不正确。")
            by_name = {info.filename: info for info in infos}
            manifest_info = by_name[MANIFEST_MEMBER]
            database_info = by_name[DATABASE_MEMBER]
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise BackupError("备份清单过大。")
            if database_info.file_size > MAX_DATABASE_BYTES:
                raise BackupError("备份数据超过 50 MB。")
            if any(
                info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                for info in infos
            ):
                raise BackupError("备份文件使用了不受支持的压缩方式。")
            manifest = _check_manifest(_strict_json(archive.read(manifest_info)))
            if database_info.file_size != manifest["databaseBytes"]:
                raise BackupError("备份大小与清单不一致。")
            hasher = hashlib.sha256()
            written = 0
            with archive.open(database_info, "r") as source, staging_path.open("wb") as target:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_DATABASE_BYTES:
                        raise BackupError("备份数据超过 50 MB。")
                    hasher.update(chunk)
                    target.write(chunk)
            if written != manifest["databaseBytes"] or hasher.hexdigest() != manifest["sha256"]:
                raise BackupError("SHA-256 校验失败，数据库没有被修改。")
        with staging_path.open("rb") as database_file:
            header = database_file.read(16)
        if header != b"SQLite format 3\x00":
            raise BackupError("备份内容不是 SQLite 数据库。")
        summary = _database_summary(staging_path)
        if manifest.get("schemaVersion") != summary["schemaVersion"]:
            raise BackupError("备份版本与数据库结构不一致。")
        if manifest.get("summary") != summary:
            raise BackupError("备份摘要与数据库内容不一致。")
        manifest["_verifiedSummary"] = summary
        return manifest
    except BackupError:
        raise
    except (OSError, EOFError, RuntimeError, ValueError, zipfile.BadZipFile, sqlite3.Error) as exc:
        raise BackupError("备份文件损坏或无法读取；现有数据库未修改。") from exc


def preview_backup(package_path: str | Path) -> dict[str, Any]:
    """Validate the package without creating or changing the target database."""
    source = Path(package_path).expanduser().resolve()
    if not source.is_file():
        raise BackupError("所选备份文件不存在。")
    try:
        with source.open("rb") as stream:
            signature = stream.read(4)
    except OSError as exc:
        raise BackupError("备份文件无法读取。") from exc
    if source.suffix.lower() == ".json" or signature != b"PK\x03\x04":
        payload, package = _read_legacy_backup(source)
        summary = {
            "tables": 0,
            "legacy": {
                **package.summary,
                "active_issue": int(bool((payload.get("issueContent") or {}).get("active"))),
                "archived_issues": len((payload.get("issueContent") or {}).get("archive") or []),
            },
        }
        return {
            "path": str(source),
            "sourceFormat": "daily-atlas-backup-v1",
            "exportedAt": payload["exportedAt"],
            "databaseBytes": source.stat().st_size,
            "sha256": "",
            "summary": summary,
        }
    with tempfile.TemporaryDirectory(prefix="fluke-backup-preview-") as temp_dir:
        manifest = _unpack_and_validate(source, Path(temp_dir) / "preview.sqlite3")
    return {
        "path": str(source),
        "sourceFormat": BACKUP_FORMAT,
        "exportedAt": manifest["exportedAt"],
        "databaseBytes": manifest["databaseBytes"],
        "sha256": manifest["sha256"],
        "summary": manifest["_verifiedSummary"],
    }


def restore_backup(package_path: str | Path, database_path: str | Path) -> dict[str, Any]:
    """Validate fully, then atomically replace the native SQLite database file."""
    source = Path(package_path).expanduser().resolve()
    target = Path(database_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if source == target:
        raise BackupError("备份文件不能与数据库文件相同。")
    if not source.is_file():
        raise BackupError("所选备份文件不存在。")
    try:
        with source.open("rb") as stream:
            signature = stream.read(4)
    except OSError as exc:
        raise BackupError("备份文件无法读取。") from exc
    if source.suffix.lower() == ".json" or signature != b"PK\x03\x04":
        return _restore_legacy_backup(source, target)
    sidecars = [Path(f"{target}{suffix}") for suffix in ("-wal", "-shm", "-journal")]
    if any(path.exists() and path.stat().st_size for path in sidecars):
        raise BackupError("数据库仍被使用或有未完成写入；关闭其他窗口后再恢复。")

    fd, staging_name = tempfile.mkstemp(
        prefix=f".{target.name}.restore-", suffix=".sqlite3", dir=target.parent
    )
    os.close(fd)
    staging = Path(staging_name)
    try:
        manifest = _unpack_and_validate(source, staging)
        os.replace(staging, target)
    except BackupError:
        raise
    except OSError as exc:
        raise BackupError("恢复文件替换失败；现有数据库保持不变。") from exc
    finally:
        if staging.exists():
            staging.unlink()
    return {
        "path": str(target),
        "exportedAt": manifest["exportedAt"],
        "summary": manifest["_verifiedSummary"],
    }
