"""Transactional, local-only cleanup for the legacy sample and clear-all actions.

Imported migration tables are immutable source material. Cleanup edits only the
native runtime overlays and adds tombstones so a later import adoption cannot
make cleared rows visible again.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

from .fitness import DEFAULT_WEEKLY_PLAN


RECORD_STATE_TABLES = (
    "finance_module_state",
    "fitness_module_state",
    "planner_module_state",
    "shopping_module_state",
)
RECORD_OWNER_TYPES = {
    "fitness_module_state": "fitness",
    "planner_module_state": "planner",
    "shopping_module_state": "home",
}
MEDIA_STATE_TABLE = "media_module_state"
HABIT_STATE_TABLE = "habit_module_state"
REQUIRED_STATE_TABLES = (*RECORD_STATE_TABLES, MEDIA_STATE_TABLE, HABIT_STATE_TABLE)
STATE_TABLE_LABELS = {
    "finance_module_state": "记账",
    "fitness_module_state": "健身",
    "planner_module_state": "日程",
    "shopping_module_state": "待买",
    MEDIA_STATE_TABLE: "书影音",
    HABIT_STATE_TABLE: "习惯",
}
SAMPLES_CLEARED_SETTING = "richangji-samples-cleared"
SAMPLES_CLEARED_VALUE = "1"
ISSUE_STORE_SETTING = "dailyIssueStore"
ISSUE_DRAFT_SETTING = "dailyIssueDraft"


class DataCleanupError(RuntimeError):
    """Readable error raised when a local cleanup transaction cannot commit."""


def _decode_object(raw: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DataCleanupError(f"{label} 内容无法读取，未清理任何数据。") from exc
    if not isinstance(value, dict):
        raise DataCleanupError(f"{label} 结构无效，未清理任何数据。")
    return value


def _encode(value: Any, label: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise DataCleanupError(f"{label} 无法保存，未清理任何数据。") from exc


def _record_key(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    record_type, record_id = value.get("type"), value.get("id")
    if isinstance(record_type, str) and record_type and isinstance(record_id, str) and record_id:
        return record_type, record_id
    return None


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _validate_required_module_rows(
    connection: sqlite3.Connection,
    tables: set[str],
) -> None:
    missing_tables = [table for table in REQUIRED_STATE_TABLES if table not in tables]
    if missing_tables:
        labels = "、".join(STATE_TABLE_LABELS[table] for table in missing_tables)
        raise DataCleanupError(f"本机数据结构不完整，缺少{labels}模块状态表；未修改任何数据。")
    for table in REQUIRED_STATE_TABLES:
        state_column = "habits_json" if table == HABIT_STATE_TABLE else "state_json"
        row = connection.execute(
            f"SELECT {state_column} FROM {table} WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise DataCleanupError(
                f"本机{STATE_TABLE_LABELS[table]}数据尚未初始化；未修改任何数据。"
            )


class LocalDataCleanupRepository:
    """Atomically clear sample rows or all local records while preserving sources."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path).expanduser()

    def preview_samples(self) -> dict[str, int]:
        return self._preview(samples_only=True)

    def preview_all(self) -> dict[str, int]:
        return self._preview(samples_only=False)

    def clear_samples(
        self,
        *,
        failure_injector: Callable[[str], None] | None = None,
    ) -> dict[str, int]:
        return self._apply(
            samples_only=True, failure_injector=failure_injector
        )

    def clear_all(
        self,
        *,
        failure_injector: Callable[[str], None] | None = None,
    ) -> dict[str, int]:
        return self._apply(samples_only=False, failure_injector=failure_injector)

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            uri = f"{self.database_path.resolve().as_uri()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=5)
            connection.execute("PRAGMA query_only = ON")
            return connection
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(self.database_path.resolve()), timeout=30, isolation_level=None
        )
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _read_states(
        self,
        connection: sqlite3.Connection,
        tables: set[str],
    ) -> dict[str, dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        for table in RECORD_STATE_TABLES:
            if table not in tables:
                continue
            row = connection.execute(
                f"SELECT state_json FROM {table} WHERE singleton=1"
            ).fetchone()
            if row is not None:
                states[table] = _decode_object(row[0], f"{table} 运行状态")
        if MEDIA_STATE_TABLE in tables:
            row = connection.execute(
                f"SELECT state_json FROM {MEDIA_STATE_TABLE} WHERE singleton=1"
            ).fetchone()
            if row is not None:
                states[MEDIA_STATE_TABLE] = _decode_object(
                    row[0], "书影音运行状态"
                )
        return states

    @staticmethod
    def _record_rows(states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for table in RECORD_STATE_TABLES:
            state = states.get(table)
            if state is None:
                continue
            for field in ("legacyRecords", "localRecords"):
                value = state.get(field, [])
                if not isinstance(value, list):
                    raise DataCleanupError(f"{table} 的 {field} 结构无效，未清理任何数据。")
                rows.extend(item for item in value if isinstance(item, dict))
        return rows

    @staticmethod
    def _record_tombstones(states: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
        result: set[tuple[str, str]] = set()
        for table in RECORD_STATE_TABLES:
            state = states.get(table)
            if state is None:
                continue
            deleted = state.get("deletedRecords", [])
            if not isinstance(deleted, list):
                raise DataCleanupError(f"{table} 的 deletedRecords 结构无效，未清理任何数据。")
            result.update(key for item in deleted if (key := _record_key(item)))
        return result

    @staticmethod
    def _media_parts(
        states: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], set[str]]:
        state = states.get(MEDIA_STATE_TABLE)
        if state is None:
            return [], set()
        rows: list[dict[str, Any]] = []
        for field in ("legacyItems", "localItems"):
            value = state.get(field, [])
            if not isinstance(value, list):
                raise DataCleanupError(f"书影音的 {field} 结构无效，未清理任何数据。")
            rows.extend(item for item in value if isinstance(item, dict))
        deleted = state.get("deletedItems", [])
        if not isinstance(deleted, list):
            raise DataCleanupError("书影音的 deletedItems 结构无效，未清理任何数据。")
        deleted_ids = {
            item["id"]
            for item in deleted
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        return rows, deleted_ids

    def _preview(self, *, samples_only: bool) -> dict[str, int]:
        if not self.database_path.is_file():
            return {"records": 0, "media": 0, "habits": 0, "dailyIssues": 0, "draft": 0}
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect(readonly=True)
            tables = _table_names(connection)
            _validate_required_module_rows(connection, tables)
            states = self._read_states(connection, tables)
            hidden_records = self._record_tombstones(states)
            candidate_records = {
                key
                for row in self._record_rows(states)
                if (key := _record_key(row)) is not None
                and (not samples_only or row.get("sample") is True)
            }
            candidate_records.difference_update(hidden_records)
            media_rows, hidden_media = self._media_parts(states)
            media_ids = {
                str(row["id"])
                for row in media_rows
                if isinstance(row.get("id"), str)
                and row["id"]
                and (not samples_only or row.get("sample") is True)
            }
            media_ids.difference_update(hidden_media)
            habit_count = 0
            if HABIT_STATE_TABLE in tables:
                row = connection.execute(
                    f"SELECT habits_json FROM {HABIT_STATE_TABLE} WHERE singleton=1"
                ).fetchone()
                if row is not None:
                    habits = json.loads(row[0])
                    if not isinstance(habits, list) or any(not isinstance(item, dict) for item in habits):
                        raise DataCleanupError("习惯运行状态结构无效，未清理任何数据。")
                    habit_count = sum(
                        1 for habit in habits
                        if not samples_only or habit.get("sample") is True
                    )
            settings: dict[str, Any] = {}
            if "app_settings" in tables:
                settings = {
                    str(key): json.loads(value)
                    for key, value in connection.execute(
                        "SELECT key,value_json FROM app_settings"
                    )
                }
            issue_store = settings.get(ISSUE_STORE_SETTING, {})
            daily_issues = 0
            if not samples_only and isinstance(issue_store, dict):
                daily_issues = (1 if issue_store.get("active") is not None else 0) + len(
                    issue_store.get("archive", [])
                    if isinstance(issue_store.get("archive", []), list)
                    else []
                )
            return {
                "records": len(candidate_records),
                "media": len(media_ids),
                "habits": habit_count,
                "dailyIssues": daily_issues,
                "draft": int(not samples_only and settings.get(ISSUE_DRAFT_SETTING) is not None),
            }
        except (OSError, sqlite3.Error, TypeError, ValueError, DataCleanupError) as exc:
            if isinstance(exc, DataCleanupError):
                raise
            raise DataCleanupError(f"无法预览本机数据：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _apply(
        self,
        *,
        samples_only: bool,
        failure_injector: Callable[[str], None] | None,
    ) -> dict[str, int]:
        if not self.database_path.is_file():
            return {"records": 0, "media": 0, "habits": 0, "dailyIssues": 0, "draft": 0}
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            tables = _table_names(connection)
            if "app_settings" not in tables:
                raise DataCleanupError("本机设置表不可用，未清理任何数据。")
            _validate_required_module_rows(connection, tables)
            daily_issue_count = 0
            draft_count = 0
            if not samples_only:
                current_settings = {
                    str(key): json.loads(value_json)
                    for key, value_json in connection.execute(
                        "SELECT key,value_json FROM app_settings WHERE key IN (?,?)",
                        (ISSUE_STORE_SETTING, ISSUE_DRAFT_SETTING),
                    )
                }
                issue_store = current_settings.get(ISSUE_STORE_SETTING, {})
                if isinstance(issue_store, dict):
                    archive = issue_store.get("archive", [])
                    daily_issue_count = int(issue_store.get("active") is not None) + (
                        len(archive) if isinstance(archive, list) else 0
                    )
                draft_count = int(current_settings.get(ISSUE_DRAFT_SETTING) is not None)
            states = self._read_states(connection, tables)
            rows = self._record_rows(states)
            hidden_records = self._record_tombstones(states)
            record_keys = {
                key
                for row in rows
                if (key := _record_key(row)) is not None
                and (not samples_only or row.get("sample") is True)
            }
            if samples_only:
                record_keys.difference_update(hidden_records)
            media_rows, hidden_media = self._media_parts(states)
            media_ids = {
                str(row["id"])
                for row in media_rows
                if isinstance(row.get("id"), str)
                and row["id"]
                and (not samples_only or row.get("sample") is True)
            }
            if samples_only:
                media_ids.difference_update(hidden_media)

            record_updates: list[tuple[str, str]] = []
            for table, state in states.items():
                if table in RECORD_STATE_TABLES:
                    deleted = state.get("deletedRecords", [])
                    if not isinstance(deleted, list):
                        raise DataCleanupError(f"{table} 的 deletedRecords 结构无效，未清理任何数据。")
                    seen = {key for item in deleted if (key := _record_key(item))}
                    state_record_keys = (
                        record_keys
                        if table == "finance_module_state"
                        else {key for key in record_keys if key[0] == RECORD_OWNER_TYPES[table]}
                    )
                    for key in state_record_keys:
                        if key not in seen:
                            deleted.append({"type": key[0], "id": key[1]})
                            seen.add(key)
                    state["deletedRecords"] = deleted
                    for field in ("legacyRecords", "localRecords"):
                        values = state.get(field, [])
                        if not isinstance(values, list):
                            raise DataCleanupError(f"{table} 的 {field} 结构无效，未清理任何数据。")
                        if samples_only:
                            state[field] = [
                                item for item in values
                                if not (
                                    isinstance(item, dict)
                                    and item.get("sample") is True
                                    and (key := _record_key(item)) in record_keys
                                )
                            ]
                        else:
                            state[field] = []
                    if table == "finance_module_state":
                        overrides = state.get("settingsOverrides", {})
                        if not isinstance(overrides, dict):
                            raise DataCleanupError("主状态设置结构无效，未清理任何数据。")
                        overrides = dict(overrides)
                        overrides["samplesCleared"] = True
                        if not samples_only:
                            overrides["userTouched"] = True
                        state["settingsOverrides"] = overrides
                    if table == "fitness_module_state" and not samples_only:
                        overrides = state.get("settingsOverrides", {})
                        if not isinstance(overrides, dict):
                            raise DataCleanupError("周计划设置结构无效，未清理任何数据。")
                        overrides = dict(overrides)
                        overrides["weeklyPlan"] = [deepcopy(item) for item in DEFAULT_WEEKLY_PLAN]
                        state["settingsOverrides"] = overrides
                    if table == "planner_module_state":
                        overrides = state.get("recordOverrides", {})
                        if not isinstance(overrides, dict):
                            raise DataCleanupError("日程记录覆盖结构无效，未清理任何数据。")
                        if samples_only:
                            overrides = {
                                record_id: value
                                for record_id, value in overrides.items()
                                if ("planner", record_id) not in record_keys
                            }
                        else:
                            overrides = {}
                            state["activeTracking"] = None
                        state["recordOverrides"] = overrides
                    if table == "shopping_module_state":
                        overrides = state.get("recordOverrides", [])
                        if not isinstance(overrides, list):
                            raise DataCleanupError("待买记录覆盖结构无效，未清理任何数据。")
                        state["recordOverrides"] = (
                            [item for item in overrides
                             if not (isinstance(item, dict)
                                     and (item.get("type"), str(item.get("id", ""))) in record_keys)]
                            if samples_only else []
                        )
                    encoded = _encode(state, f"{table} 运行状态")
                    record_updates.append((table, encoded))

            media_update: str | None = None
            if MEDIA_STATE_TABLE in states:
                media_state = states[MEDIA_STATE_TABLE]
                deleted = media_state.get("deletedItems", [])
                if not isinstance(deleted, list):
                    raise DataCleanupError("书影音的 deletedItems 结构无效，未清理任何数据。")
                seen_media = {
                    item["id"]
                    for item in deleted
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
                for item_id in media_ids:
                    if item_id not in seen_media:
                        deleted.append({"id": item_id})
                        seen_media.add(item_id)
                media_state["deletedItems"] = deleted
                for field in ("legacyItems", "localItems"):
                    values = media_state.get(field, [])
                    if not isinstance(values, list):
                        raise DataCleanupError(f"书影音的 {field} 结构无效，未清理任何数据。")
                    if samples_only:
                        media_state[field] = [
                            item for item in values
                            if not (
                                isinstance(item, dict)
                                and item.get("sample") is True
                                and str(item.get("id", "")) in media_ids
                            )
                        ]
                    else:
                        media_state[field] = []
                media_update = _encode(media_state, "书影音运行状态")

            habit_count = 0
            habit_update: tuple[str, str, str] | None = None
            if HABIT_STATE_TABLE in tables:
                row = connection.execute(
                    f"SELECT habits_json,hidden_keys_json,local_ids_json FROM {HABIT_STATE_TABLE} WHERE singleton=1"
                ).fetchone()
                if row is not None:
                    habits = json.loads(row[0])
                    if not isinstance(habits, list) or any(not isinstance(item, dict) for item in habits):
                        raise DataCleanupError("习惯运行状态结构无效，未清理任何数据。")
                    local_ids = json.loads(row[2])
                    if not isinstance(local_ids, list) or any(not isinstance(item, str) for item in local_ids):
                        raise DataCleanupError("习惯本机来源标记结构无效，未清理任何数据。")
                    next_habits = deepcopy(habits)
                    for habit in next_habits:
                        if not samples_only:
                            habit["entries"] = {}
                            habit["remoteEntries"] = {}
                            habit["sample"] = False
                            habit_count += 1
                        elif habit.get("sample") is True:
                            habit["entries"] = {}
                            habit["sample"] = False
                            habit_count += 1
                    if not samples_only:
                        # HabitRepository merges remoteEntries from later imports
                        # unconditionally. Mark current definitions as local so
                        # clearing them cannot be undone by an explicit re-adopt.
                        local_ids = list(dict.fromkeys([
                            *local_ids,
                            *(
                                habit["id"]
                                for habit in next_habits
                                if isinstance(habit.get("id"), str) and habit["id"]
                            ),
                        ]))
                    habit_update = (
                        _encode(next_habits, "习惯运行状态"),
                        row[1],
                        _encode(local_ids, "习惯本机来源标记"),
                    )

            settings_updates = {
                SAMPLES_CLEARED_SETTING: SAMPLES_CLEARED_VALUE,
            }
            if not samples_only:
                settings_updates[ISSUE_STORE_SETTING] = {"active": None, "archive": []}
                settings_updates[ISSUE_DRAFT_SETTING] = None

            # Match the legacy UI: when no sample rows/items/habits exist,
            # clearing samples is a true no-op. In particular, do not persist
            # the samples-cleared marker merely because the action was opened.
            if samples_only and not record_keys and not media_ids and not habit_count:
                connection.rollback()
                return {
                    "records": 0,
                    "media": 0,
                    "habits": 0,
                    "dailyIssues": 0,
                    "draft": 0,
                }

            for table, encoded in record_updates:
                cursor = connection.execute(
                    f"UPDATE {table} SET state_json=? WHERE singleton=1", (encoded,)
                )
                if cursor.rowcount != 1:
                    raise DataCleanupError(f"{table} 状态未能保存，清理已回滚。")
                if failure_injector is not None:
                    failure_injector("after-record-state")
            if media_update is not None:
                cursor = connection.execute(
                    f"UPDATE {MEDIA_STATE_TABLE} SET state_json=? WHERE singleton=1",
                    (media_update,),
                )
                if cursor.rowcount != 1:
                    raise DataCleanupError("书影音状态未能保存，清理已回滚。")
                if failure_injector is not None:
                    failure_injector("after-media-state")
            if habit_update is not None:
                cursor = connection.execute(
                    f"UPDATE {HABIT_STATE_TABLE} SET habits_json=?,hidden_keys_json=?,local_ids_json=? "
                    "WHERE singleton=1",
                    habit_update,
                )
                if cursor.rowcount != 1:
                    raise DataCleanupError("习惯状态未能保存，清理已回滚。")
                if failure_injector is not None:
                    failure_injector("after-habit-state")
            for key, value in settings_updates.items():
                connection.execute(
                    "INSERT INTO app_settings(key,value_json) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (key, _encode(value, key)),
                )
                if failure_injector is not None:
                    failure_injector("after-app-setting")
            if failure_injector is not None:
                failure_injector("before-commit")
            connection.commit()
            return {
                "records": len(record_keys),
                "media": len(media_ids),
                "habits": habit_count,
                "dailyIssues": daily_issue_count,
                "draft": draft_count,
            }
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            if isinstance(exc, DataCleanupError):
                raise
            raise DataCleanupError(f"本机清理失败，所有改动已回滚：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()


__all__ = ["DataCleanupError", "LocalDataCleanupRepository"]
