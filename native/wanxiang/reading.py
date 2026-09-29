"""SQLite-backed local saved-knowledge flag and news clippings."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
import time
from typing import Any

from .database import load_imported_data
from .json_utils import strict_copy_json
from .migration import MigrationPackage


LEGACY_CLIPPINGS_KEY = "wanxiang-issue-clippings-v1"
LEGACY_SAVED_KNOWLEDGE_KEY = "wanxiang-saved-knowledge"
MAX_CLIPPINGS = 80
_TABLE = "reading_module_state"
_DATE_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MISSING = object()


class ReadingRepositoryError(ValueError):
    """Readable validation or persistence error for the reading module."""


def _reject_constant(value: str) -> None:
    raise ReadingRepositoryError(f"数据包含无效 JSON 数值：{value}。")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReadingRepositoryError(f"数据包含重复字段：{key}。")
        result[key] = value
    return result


def _loads(raw: str, label: str) -> Any:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except ReadingRepositoryError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise ReadingRepositoryError(f"{label}不是有效 JSON。") from exc


def _json_copy(value: Any, label: str) -> Any:
    return strict_copy_json(
        value,
        label,
        ReadingRepositoryError,
        invalid_number_suffix=" 包含无效数值。",
        invalid_type_suffix=" 包含不能保存的数据类型。",
        invalid_json_suffix=" 不是有效 JSON 数据。",
    )


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ReadingRepositoryError("阅读与剪报状态无法编码为有效 JSON。") from exc


def _raw_values(source: Any) -> dict[str, Any]:
    if isinstance(source, MigrationPackage):
        return source.raw_values
    if not isinstance(source, dict):
        return {}
    for name in ("raw_values", "keys"):
        value = source.get(name)
        if isinstance(value, dict):
            return value
    return {}


def _parsed_values(source: Any) -> dict[str, Any]:
    if isinstance(source, MigrationPackage):
        return source.parsed_values
    if not isinstance(source, dict):
        return {}
    for name in ("parsed_values", "documents"):
        value = source.get(name)
        if isinstance(value, dict):
            return value
    return {}


def _legacy_value(source: Any, key: str) -> Any:
    """Read one migration value without mutating the source snapshot."""
    raw = _raw_values(source)
    parsed = _parsed_values(source)

    if key == LEGACY_SAVED_KNOWLEDGE_KEY:
        # v1 stores the exact localStorage string "1" or "0", not a per-story
        # collection and not a JSON boolean. Match the old strict comparison.
        if key in raw:
            return raw[key] == "1"
        if isinstance(source, dict) and key in source:
            return source[key] == "1"
        return False

    if key in parsed:
        return parsed[key]
    if key in raw:
        value = raw[key]
        if value is None:
            return None
        if not isinstance(value, str):
            raise ReadingRepositoryError(f"旧版存储键 {key} 必须是 JSON 字符串。")
        return _loads(value, "旧版剪报")
    if isinstance(source, dict) and key in source:
        value = source[key]
        if isinstance(value, str):
            return _loads(value, "旧版剪报")
        return value
    return _MISSING


def _normalize_clippings(value: Any) -> list[dict[str, Any]]:
    if value is _MISSING or value is None:
        return []
    if not isinstance(value, list):
        raise ReadingRepositoryError("旧版新闻剪报必须是数组。")

    result: list[dict[str, Any]] = []
    # The old reader exposed only its first 80 valid rows. Keep their source
    # order (newest first) and leave the immutable imported JSON untouched.
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            continue
        item = raw.get("item")
        if not (
            isinstance(raw.get("key"), str)
            and raw["key"]
            and isinstance(raw.get("date"), str)
            and raw["date"]
            and isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"]
            and isinstance(item.get("title"), str)
            and item["title"]
        ):
            continue
        # Preserve all recognized and future fields verbatim; only JSON safety
        # is enforced. There is intentionally no cloud-record interpretation.
        result.append(_json_copy(raw, f"旧版剪报第 {index} 项"))
        if len(result) == MAX_CLIPPINGS:
            break
    return result


def _read_runtime(database_path: Path) -> dict[str, Any] | None:
    if not database_path.is_file():
        return None
    connection: sqlite3.Connection | None = None
    try:
        uri = f"{database_path.expanduser().resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.execute("PRAGMA query_only = ON")
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_TABLE,)
        ).fetchone()
        if exists is None:
            return None
        columns = {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({_TABLE})").fetchall()
        }
        selected_columns = "saved_knowledge, clippings_json"
        if "local_fields_json" in columns:
            selected_columns += ", local_fields_json"
        row = connection.execute(
            f"SELECT {selected_columns} FROM {_TABLE} WHERE singleton=1"
        ).fetchone()
        if row is None:
            return None
        saved_knowledge = row[0]
        if saved_knowledge not in (0, 1):
            raise ReadingRepositoryError("本机稍后读状态损坏。")
        clippings = _normalize_clippings(_loads(row[1], "本机新闻剪报"))
        local_fields: list[str] = []
        if len(row) > 2:
            parsed_fields = _loads(row[2], "本机阅读修改标记")
            if not isinstance(parsed_fields, list) or any(
                field not in {"savedKnowledge", "clippings"} for field in parsed_fields
            ):
                raise ReadingRepositoryError("本机阅读修改标记结构无效。")
            local_fields = list(dict.fromkeys(parsed_fields))
        return {
            "savedKnowledge": bool(saved_knowledge),
            "clippings": clippings,
            "localFields": local_fields,
        }
    except ReadingRepositoryError:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise ReadingRepositoryError(f"无法读取本机阅读与剪报数据：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def _create_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            saved_knowledge INTEGER NOT NULL CHECK (saved_knowledge IN (0, 1)),
            clippings_json TEXT NOT NULL,
            local_fields_json TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    columns = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({_TABLE})").fetchall()
    }
    if "local_fields_json" not in columns:
        connection.execute(
            f"ALTER TABLE {_TABLE} ADD COLUMN local_fields_json TEXT NOT NULL DEFAULT '[]'"
        )


def _validate_state(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ReadingRepositoryError("阅读与剪报状态必须是对象。")
    saved = state.get("savedKnowledge")
    if not isinstance(saved, bool):
        raise ReadingRepositoryError("稍后读状态必须是全局布尔值。")
    clippings = _normalize_clippings(state.get("clippings"))
    local_fields = state.get("localFields", [])
    if not isinstance(local_fields, (list, set, tuple)) or any(
        field not in {"savedKnowledge", "clippings"} for field in local_fields
    ):
        raise ReadingRepositoryError("本机阅读修改标记结构无效。")
    return {
        "savedKnowledge": saved,
        "clippings": clippings,
        "localFields": sorted(set(local_fields)),
    }


def _insert_state(connection: sqlite3.Connection, state: dict[str, Any]) -> None:
    connection.execute(
        f"INSERT INTO {_TABLE}(singleton, saved_knowledge, clippings_json, local_fields_json) "
        "VALUES (1, ?, ?, ?)",
        (
            int(state["savedKnowledge"]),
            _json_dumps(state["clippings"]),
            _json_dumps(state["localFields"]),
        ),
    )


class ReadingRepository:
    """Transactional local reading state seeded from a read-only migration view.

    ``legacy_snapshot`` accepts a ``MigrationPackage`` or the snapshot returned
    by ``load_imported_data``. The repository copies those values into its own
    table and never edits the imported source rows, raw JSON, or checksum.

    The legacy saved-knowledge flag is global. Clippings are separate local
    snapshots of article objects; source URLs identify publishers, not cloud
    records or account-sync state.
    """

    def __init__(
        self,
        database_path: str | Path,
        legacy_snapshot: Any = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser()
        self._lock = RLock()

        existing = _read_runtime(self.database_path)
        if existing is None:
            source = legacy_snapshot
            if source is None:
                imported = load_imported_data(self.database_path)
                if imported.get("status") == "unavailable":
                    raise ReadingRepositoryError(
                        imported.get("error") or "无法读取迁移包中的阅读数据。"
                    )
                source = imported
            saved_value = _legacy_value(source, LEGACY_SAVED_KNOWLEDGE_KEY)
            clipping_value = _legacy_value(source, LEGACY_CLIPPINGS_KEY)
            seed = {
                "savedKnowledge": saved_value is True,
                "clippings": _normalize_clippings(clipping_value),
            }
            self._materialize_if_missing(seed)
            existing = _read_runtime(self.database_path)
            if existing is None:
                raise ReadingRepositoryError("无法初始化本机阅读与剪报状态。")

        self._state = _validate_state(existing)

    def _materialize_if_missing(self, seed: dict[str, Any]) -> None:
        validated = _validate_state(seed)
        path = self.database_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("BEGIN IMMEDIATE")
            _create_table(connection)
            present = connection.execute(
                f"SELECT 1 FROM {_TABLE} WHERE singleton=1"
            ).fetchone()
            if present is None:
                _insert_state(connection, validated)
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise ReadingRepositoryError(f"初始化本机阅读与剪报数据失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _commit(self, state: dict[str, Any]) -> None:
        validated = _validate_state(state)
        path = self.database_path.resolve()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("BEGIN IMMEDIATE")
            _create_table(connection)
            connection.execute(
                f"UPDATE {_TABLE} SET saved_knowledge=?, clippings_json=?, local_fields_json=? "
                "WHERE singleton=1",
                (
                    int(validated["savedKnowledge"]),
                    _json_dumps(validated["clippings"]),
                    _json_dumps(validated["localFields"]),
                ),
            )
            if connection.total_changes == 0:
                _insert_state(connection, validated)
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise ReadingRepositoryError(f"保存阅读与剪报数据失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        self._state = validated

    def snapshot(self) -> dict[str, Any]:
        """Return a detached view: one global flag and an ordered clip list."""
        with self._lock:
            return {
                "savedKnowledge": self._state["savedKnowledge"],
                "clippings": deepcopy(self._state["clippings"]),
            }

    def saved_knowledge(self) -> bool:
        with self._lock:
            return self._state["savedKnowledge"]

    def set_saved_knowledge(self, saved: bool) -> bool:
        if not isinstance(saved, bool):
            raise ReadingRepositoryError("稍后读状态必须是布尔值。")
        with self._lock:
            if saved == self._state["savedKnowledge"]:
                return saved
            next_state = deepcopy(self._state)
            next_state["savedKnowledge"] = saved
            self._mark_local(next_state, "savedKnowledge")
            self._commit(next_state)
            return saved

    def toggle_saved_knowledge(self) -> bool:
        with self._lock:
            return self.set_saved_knowledge(not self._state["savedKnowledge"])

    def clippings(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._state["clippings"])

    def is_clipped(self, item_id: str, date: str) -> bool:
        if not isinstance(item_id, str) or not item_id:
            raise ReadingRepositoryError("报道 id 必须是非空字符串。")
        if not isinstance(date, str) or not date:
            raise ReadingRepositoryError("剪报日期不能为空。")
        key = f"{date}::{item_id}"
        with self._lock:
            return any(entry.get("key") == key for entry in self._state["clippings"])

    def save_clipping(
        self,
        item: Any,
        date: str,
        topic: Any = "",
        saved_at: int | None = None,
    ) -> bool:
        """Save a full article snapshot once; newest clips appear first."""
        clipping = self._make_clipping(item, date, topic, saved_at)
        with self._lock:
            if any(
                entry.get("key") == clipping["key"]
                for entry in self._state["clippings"]
            ):
                return False
            next_state = deepcopy(self._state)
            next_state["clippings"] = (
                [clipping, *next_state["clippings"]][:MAX_CLIPPINGS]
            )
            self._mark_local(next_state, "clippings")
            self._commit(next_state)
            return True

    def toggle_clipping(
        self,
        item: Any,
        date: str,
        topic: Any = "",
        saved_at: int | None = None,
    ) -> bool:
        """Mirror the old article button: add when absent, remove one when present."""
        key = self._clipping_key(item, date)
        with self._lock:
            for index, entry in enumerate(self._state["clippings"]):
                if entry.get("key") == key:
                    next_state = deepcopy(self._state)
                    next_state["clippings"].pop(index)
                    self._mark_local(next_state, "clippings")
                    self._commit(next_state)
                    return False
            # RLock keeps the contains-and-insert operation atomic if two UI
            # events attempt to save the same story at nearly the same time.
            return self.save_clipping(item, date, topic, saved_at)

    def remove_clipping(self, key: str) -> int:
        """Remove all rows with a key, matching the clipping-list remove action."""
        if not isinstance(key, str) or not key:
            raise ReadingRepositoryError("剪报 key 必须是非空字符串。")
        with self._lock:
            next_state = deepcopy(self._state)
            remaining = [entry for entry in next_state["clippings"] if entry["key"] != key]
            removed = len(next_state["clippings"]) - len(remaining)
            if removed:
                next_state["clippings"] = remaining
                self._mark_local(next_state, "clippings")
                self._commit(next_state)
            return removed

    @staticmethod
    def _mark_local(state: dict[str, Any], field: str) -> None:
        fields = state.setdefault("localFields", [])
        if field not in fields:
            fields.append(field)

    def adopt_imported_data(self, legacy_snapshot: Any) -> dict[str, Any]:
        """Adopt newly imported source values without overwriting local edits.

        The saved flag and clipping collection are independent legacy keys,
        so each has its own modification marker. Newly imported clippings lead
        the merged list; matching date/id keys are included once, within the
        same 80-row limit as the original reader.
        """
        saved_value = _legacy_value(legacy_snapshot, LEGACY_SAVED_KNOWLEDGE_KEY)
        clipping_value = _legacy_value(legacy_snapshot, LEGACY_CLIPPINGS_KEY)
        incoming_saved = saved_value is True
        incoming_clippings = _normalize_clippings(clipping_value)
        with self._lock:
            next_state = deepcopy(self._state)
            local_fields = set(next_state.get("localFields", []))
            if "savedKnowledge" not in local_fields:
                next_state["savedKnowledge"] = incoming_saved
            if "clippings" not in local_fields:
                combined: list[dict[str, Any]] = []
                seen: set[str] = set()
                for clipping in [*incoming_clippings, *next_state["clippings"]]:
                    key = clipping.get("key")
                    if isinstance(key, str) and key not in seen:
                        seen.add(key)
                        combined.append(clipping)
                    if len(combined) >= MAX_CLIPPINGS:
                        break
                next_state["clippings"] = combined
            self._commit(next_state)
            return self.snapshot()

    def clipping(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            for entry in self._state["clippings"]:
                if entry.get("key") == key:
                    return deepcopy(entry)
            return None

    @staticmethod
    def _clipping_key(item: Any, date: str) -> str:
        if not isinstance(item, dict):
            raise ReadingRepositoryError("报道必须是对象。")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ReadingRepositoryError("报道 id 必须是非空字符串。")
        if not isinstance(date, str) or not _DATE_SHAPE.fullmatch(date):
            raise ReadingRepositoryError("剪报日期必须使用 YYYY-MM-DD 格式。")
        return f"{date}::{item_id}"

    @classmethod
    def _make_clipping(
        cls,
        item: Any,
        date: str,
        topic: Any,
        saved_at: int | None,
    ) -> dict[str, Any]:
        key = cls._clipping_key(item, date)
        article = _json_copy(item, "报道")
        if not isinstance(article.get("title"), str) or not article["title"]:
            raise ReadingRepositoryError("报道标题不能为空。")
        image = article.get("image")
        if isinstance(image, dict):
            source = image.get("src")
            if isinstance(source, str) and source.startswith("data:"):
                # The old code strips embedded image payloads from saved clips.
                article["image"] = None
        if topic is None or topic is False or topic == "":
            topic = ""
        _json_copy(topic, "剪报主题")
        timestamp = time.time_ns() // 1_000_000 if saved_at is None else saved_at
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise ReadingRepositoryError("savedAt 必须是毫秒时间戳整数。")
        return {
            "key": key,
            "date": date,
            "topic": topic,
            "item": article,
            "savedAt": timestamp,
        }


__all__ = [
    "LEGACY_CLIPPINGS_KEY",
    "LEGACY_SAVED_KNOWLEDGE_KEY",
    "MAX_CLIPPINGS",
    "ReadingRepository",
    "ReadingRepositoryError",
]
