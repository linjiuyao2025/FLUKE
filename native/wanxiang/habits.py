"""SQLite-backed habits module with a read-only legacy-data seed."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import json
import math
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any
from uuid import uuid4

from .database import load_imported_data
from .json_utils import strict_copy_json, strict_json_loads
from .migration import MigrationPackage


LEGACY_STATE_KEY = "richangji-state-v1"
_TABLE = "habit_module_state"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TYPES = {"check", "counter", "number"}
_WEEKDAYS = set(range(1, 8))
_TONES = {"sage", "plum", "terracotta", "sand"}

BUILTIN_HABITS: tuple[dict[str, Any], ...] = (
    {
        "key": "water",
        "name": "喝水",
        "nameEn": "Drink water",
        "type": "counter",
        "target": 8,
        "unit": "杯",
        "unitEn": "cups",
        "tone": "sage",
    },
    {
        "key": "sleep",
        "name": "睡觉",
        "nameEn": "Sleep",
        "type": "number",
        "target": 7,
        "unit": "小时",
        "unitEn": "hours",
        "tone": "plum",
    },
    {
        "key": "exercise",
        "name": "运动",
        "nameEn": "Exercise",
        "type": "check",
        "target": 1,
        "unit": "次",
        "unitEn": "times",
        "tone": "terracotta",
    },
    {
        "key": "reading",
        "name": "看书",
        "nameEn": "Read",
        "type": "check",
        "target": 1,
        "unit": "次",
        "unitEn": "times",
        "tone": "sand",
    },
    {
        "key": "meditation",
        "name": "冥想",
        "nameEn": "Meditate",
        "type": "check",
        "target": 1,
        "unit": "次",
        "unitEn": "times",
        "tone": "sage",
    },
)

_BUILTIN_BY_KEY = {habit["key"]: habit for habit in BUILTIN_HABITS}


class HabitRepositoryError(ValueError):
    """Readable validation or persistence error for habit operations."""


def _json_copy(value: Any, label: str) -> Any:
    return strict_copy_json(value, label, HabitRepositoryError)


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise HabitRepositoryError("习惯状态无法编码为有效 JSON。") from exc


def _strict_json_loads(raw: str, label: str) -> Any:
    return strict_json_loads(raw, label, HabitRepositoryError)


def _valid_date(value: Any, label: str = "日期") -> str:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise HabitRepositoryError(f"{label} 必须使用有效的 YYYY-MM-DD 日期。")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise HabitRepositoryError(f"{label} 必须使用有效的 YYYY-MM-DD 日期。") from exc
    if parsed.isoformat() != value:
        raise HabitRepositoryError(f"{label} 必须使用有效的 YYYY-MM-DD 日期。")
    return value


def _number(value: Any, label: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HabitRepositoryError(f"{label} 必须是非负数。")
    if not math.isfinite(float(value)) or value < 0:
        raise HabitRepositoryError(f"{label} 必须是非负有限数值。")
    return value


def _finite_number(value: Any, label: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HabitRepositoryError(f"{label} 必须是数值。")
    if not math.isfinite(float(value)):
        raise HabitRepositoryError(f"{label} 必须是有限数值。")
    return value


def _positive_target(value: Any, label: str = "每日目标") -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise HabitRepositoryError(f"{label} 必须介于 0.1 和 999 之间。")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise HabitRepositoryError(f"{label} 必须介于 0.1 和 999 之间。") from exc
    if not math.isfinite(converted) or not 0.1 <= converted <= 999:
        raise HabitRepositoryError(f"{label} 必须介于 0.1 和 999 之间。")
    return int(converted) if converted.is_integer() else converted


def _normalize_schedule(value: Any, label: str) -> dict[str, Any]:
    """Normalize a daily or selected-weekdays habit schedule."""
    if value is None:
        return {"type": "daily"}
    if not isinstance(value, dict):
        raise HabitRepositoryError(f"{label} schedule 必须是对象。")
    schedule_type = value.get("type", "daily")
    if schedule_type == "daily":
        return {"type": "daily"}
    if schedule_type != "weekdays":
        raise HabitRepositoryError(f"{label} schedule 类型无效。")
    days = value.get("days")
    if not isinstance(days, list) or not days:
        raise HabitRepositoryError(f"{label} 至少选择一个计划日。")
    if any(
        isinstance(day, bool)
        or not isinstance(day, int)
        or day not in _WEEKDAYS
        for day in days
    ):
        raise HabitRepositoryError(f"{label} 计划日必须是 1 到 7 的星期编号。")
    normalized_days = sorted(set(days))
    if len(normalized_days) != len(days):
        raise HabitRepositoryError(f"{label} 计划日不能重复。")
    return {"type": "weekdays", "days": normalized_days}


def _is_due_on(schedule: dict[str, Any], day: date) -> bool:
    if schedule.get("type", "daily") == "daily":
        return True
    return day.isoweekday() in schedule.get("days", [])


def _normalize_schedule_history(value: Any, label: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise HabitRepositoryError(f"{label} scheduleHistory 必须是数组。")
    result: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise HabitRepositoryError(f"{label} scheduleHistory 第 {index + 1} 项无效。")
        effective_date = _valid_date(
            raw.get("effectiveDate"), f"{label} 计划生效日期"
        )
        if effective_date in seen_dates:
            raise HabitRepositoryError(f"{label} 计划生效日期不能重复。")
        seen_dates.add(effective_date)
        result.append(
            {
                "effectiveDate": effective_date,
                "schedule": _normalize_schedule(
                    raw.get("schedule"), f"{label} 历史计划"
                ),
            }
        )
    result.sort(key=lambda entry: entry["effectiveDate"])
    return result


def _schedule_for_date(
    current: dict[str, Any], history: list[dict[str, Any]], day: date
) -> dict[str, Any]:
    if not history:
        return current
    selected = history[0]["schedule"]
    for entry in history:
        if date.fromisoformat(entry["effectiveDate"]) > day:
            break
        selected = entry["schedule"]
    return selected


def _hidden_keys(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(key, str) or not key for key in value
    ):
        raise HabitRepositoryError("hiddenHabitKeys 必须是非空字符串组成的数组。")
    return list(dict.fromkeys(value))


def _extract_legacy_state(source: Any) -> dict[str, Any] | None:
    """Return the parsed legacy main state without modifying its source."""
    if isinstance(source, MigrationPackage):
        value = source.parsed_values.get(LEGACY_STATE_KEY)
        return value if isinstance(value, dict) else None

    if isinstance(source, list):
        return {"habits": source}
    if not isinstance(source, dict):
        return None

    for container_name in ("parsed_values", "documents"):
        container = source.get(container_name)
        if isinstance(container, dict) and LEGACY_STATE_KEY in container:
            value = container[LEGACY_STATE_KEY]
            return value if isinstance(value, dict) else None
    if LEGACY_STATE_KEY in source:
        value = source[LEGACY_STATE_KEY]
        return value if isinstance(value, dict) else None

    for container_name in ("raw_values", "keys"):
        container = source.get(container_name)
        if isinstance(container, dict) and LEGACY_STATE_KEY in container:
            raw = container[LEGACY_STATE_KEY]
            if raw is None:
                return None
            if not isinstance(raw, str):
                raise HabitRepositoryError("旧版主状态原文必须是 JSON 字符串。")
            value = _strict_json_loads(raw, "旧版主状态")
            return value if isinstance(value, dict) else None

    # load_imported_data exposes normalized entity rows when a document is
    # absent. Accept them as a compatibility fallback, while preserving each
    # row's complete payload.
    entities = source.get("entities")
    if isinstance(entities, dict) and isinstance(entities.get("habits"), list):
        return {"habits": entities["habits"]}

    if "habits" in source or "settings" in source:
        return source
    return None


def _legacy_parts(source: Any) -> tuple[list[dict[str, Any]], list[str], bool]:
    state = _extract_legacy_state(source)
    if state is None:
        return [], [], False
    habits = state.get("habits", [])
    settings = state.get("settings", {})
    if not isinstance(habits, list):
        raise HabitRepositoryError("旧版主状态 habits 必须是数组。")
    if not isinstance(settings, dict):
        raise HabitRepositoryError("旧版主状态 settings 必须是对象。")
    hidden = _hidden_keys(settings.get("hiddenHabitKeys", []))
    normalized = _normalize_legacy_habits(habits, hidden)
    return normalized, hidden, True


def _normalize_legacy_habits(
    source_habits: Any, hidden_keys: list[str] | None = None
) -> list[dict[str, Any]]:
    """Apply old built-in matching and check-in compatibility to a habit list."""
    if not isinstance(source_habits, list):
        raise HabitRepositoryError("旧版 habits 必须是数组。")
    hidden = set(hidden_keys or [])
    normalized_existing: list[dict[str, Any]] = []

    for index, raw in enumerate(source_habits):
        label = f"旧版 habits 第 {index + 1} 项"
        if not isinstance(raw, dict):
            raise HabitRepositoryError(f"{label} 必须是对象。")
        item = _json_copy(raw, label)
        raw_key = item.get("key")
        definition = _BUILTIN_BY_KEY.get(raw_key) if isinstance(raw_key, str) else None
        if definition is None and index < len(BUILTIN_HABITS):
            definition = BUILTIN_HABITS[index]
        if definition is None:
            definition = {
                "key": f"custom-{index}",
                "name": item.get("name") or "习惯",
                "type": "check",
                "target": 1,
                "unit": "次",
                "tone": item.get("tone") or "sage",
            }
        merged = {**definition, **item}
        entries = merged.get("entries", {})
        if entries is None:
            entries = {}
        if not isinstance(entries, dict):
            raise HabitRepositoryError(f"{label} entries 必须是对象。")
        normalized_entries: dict[str, float | int] = {}
        for entry_date, value in entries.items():
            valid_date = _valid_date(entry_date, f"{label} entries 日期")
            normalized_entries[valid_date] = _number(value, f"{label} entries 值")

        completed_dates = merged.get("completedDates", [])
        if completed_dates is None:
            completed_dates = []
        if not isinstance(completed_dates, list):
            raise HabitRepositoryError(f"{label} completedDates 必须是数组。")
        for completed_date in completed_dates:
            valid_date = _valid_date(completed_date, f"{label} completedDates 日期")
            # Preserve entries when present; only backfill dates absent there.
            normalized_entries.setdefault(valid_date, 1)

        key = merged.get("key")
        if not isinstance(key, str) or not key:
            key = f"custom-{index}"
        habit_id = merged.get("id")
        if habit_id is None or habit_id == "":
            habit_id = f"habit-{key}"
        if not isinstance(habit_id, str):
            habit_id = str(habit_id)
        name = merged.get("name", "习惯")
        if not isinstance(name, str):
            raise HabitRepositoryError(f"{label} name 必须是字符串。")
        habit_type = merged.get("type", "check")
        if not isinstance(habit_type, str) or habit_type not in _TYPES:
            habit_type = definition.get("type", "check")
        target_value = merged.get("target", 1)
        if target_value is None or target_value == "" or (
            not isinstance(target_value, bool) and target_value == 0
        ):
            target_value = 1
        target = _positive_target(target_value, f"{label} target")
        unit = merged.get("unit", "次")
        if not isinstance(unit, str):
            unit = str(unit)
        if not unit.strip():
            unit = "次"
        tone = merged.get("tone", "sage")
        if not isinstance(tone, str) or tone not in _TONES:
            tone = "sage"

        merged.update(
            {
                "id": habit_id,
                "key": key,
                "name": name,
                "type": habit_type,
                "target": target,
                "unit": unit,
                "tone": tone,
                "entries": normalized_entries,
                "schedule": _normalize_schedule(merged.get("schedule"), label),
            }
        )
        # This alias has now been folded into entries. Keep the field for
        # payload compatibility, but do not let a later re-adoption resurrect
        # dates after sample history is cleared.
        if "completedDates" in merged:
            merged["completedDates"] = []
        merged.setdefault("sample", False)
        if not isinstance(merged["sample"], bool):
            merged["sample"] = bool(merged["sample"])
        normalized_existing.append(merged)

    # Preserve the legacy normalizeState behavior: built-ins are restored in
    # definition order, then custom rows follow in their original order.
    result: list[dict[str, Any]] = []
    matched_ids: set[str] = set()
    builtin_keys = set(_BUILTIN_BY_KEY)
    for definition in BUILTIN_HABITS:
        key = definition["key"]
        if key in hidden:
            continue
        match = next(
            (
                item
                for item in normalized_existing
                if item.get("key") == key
                or item.get("name") == definition["name"]
                or (key == "reading" and "阅读" in item.get("name", ""))
                or (key == "water" and "水" in item.get("name", ""))
            ),
            None,
        )
        if match is None:
            item = {
                **definition,
                "id": f"habit-{key}",
                "entries": {},
                "sample": False,
            }
        else:
            item = {**definition, **match, "entries": match.get("entries", {})}
            matched_ids.add(item["id"])
        result.append(item)

    seen_ids = {item["id"] for item in result}
    seen_custom_keys = {item["key"] for item in result}
    for item in normalized_existing:
        if item["id"] in matched_ids or item["id"] in seen_ids:
            continue
        if item["key"] in builtin_keys:
            continue
        if item["key"] in hidden:
            continue
        # Old custom normalization turns unknown types into a check and uses
        # a generated key only when the source omitted one.
        custom = deepcopy(item)
        if custom["key"] in seen_custom_keys:
            continue
        result.append(custom)
        seen_ids.add(custom["id"])
        seen_custom_keys.add(custom["key"])

    # Duplicate IDs cannot be addressed unambiguously through the repository
    # API. Keep the first source row, as import adoption also does.
    deduplicated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result:
        if item["id"] not in seen:
            seen.add(item["id"])
            deduplicated.append(item)
    for item in deduplicated:
        item["schedule"] = _normalize_schedule(
            item.get("schedule"), f"习惯 {item['name']}"
        )
        item["scheduleHistory"] = _normalize_schedule_history(
            item.get("scheduleHistory"), f"习惯 {item['name']}"
        )
    return deduplicated


def _seed_state(source: Any) -> tuple[list[dict[str, Any]], list[str]]:
    habits, hidden, has_legacy_state = _legacy_parts(source)
    if not has_legacy_state:
        habits = _normalize_legacy_habits([], [])
    return habits, hidden


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
        row = connection.execute(
            f"SELECT habits_json, hidden_keys_json, local_ids_json FROM {_TABLE} "
            "WHERE singleton = 1"
        ).fetchone()
        if row is None:
            return None
        habits = _strict_json_loads(row[0], "本机习惯状态")
        hidden = _strict_json_loads(row[1], "本机隐藏习惯设置")
        local_ids = _strict_json_loads(row[2], "本机习惯来源标记")
        if not isinstance(habits, list) or any(not isinstance(item, dict) for item in habits):
            raise HabitRepositoryError("本机 habits 状态结构无效。")
        normalized = _normalize_persisted_habits(habits)
        if not isinstance(local_ids, list) or any(not isinstance(i, str) for i in local_ids):
            raise HabitRepositoryError("本机习惯来源标记结构无效。")
        return {
            "habits": normalized,
            "hidden": _hidden_keys(hidden),
            "local_ids": set(local_ids),
        }
    except HabitRepositoryError:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise HabitRepositoryError(f"无法读取本机习惯状态：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def _normalize_persisted_habits(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            raise HabitRepositoryError(f"本机 habits 第 {index + 1} 项必须是对象。")
        item = _json_copy(raw, f"本机 habits 第 {index + 1} 项")
        if not isinstance(item.get("id"), str) or not item["id"]:
            raise HabitRepositoryError(f"本机 habits 第 {index + 1} 项 id 无效。")
        if not isinstance(item.get("key"), str) or not item["key"]:
            raise HabitRepositoryError(f"本机 habits 第 {index + 1} 项 key 无效。")
        if not isinstance(item.get("name"), str):
            raise HabitRepositoryError(f"本机 habits 第 {index + 1} 项 name 无效。")
        if item.get("type") not in _TYPES:
            raise HabitRepositoryError(f"本机 habits 第 {index + 1} 项 type 无效。")
        item["target"] = _positive_target(
            item.get("target"), f"本机 habits 第 {index + 1} 项 target"
        )
        if not isinstance(item.get("unit"), str):
            raise HabitRepositoryError(f"本机 habits 第 {index + 1} 项 unit 无效。")
        entries = item.get("entries")
        if not isinstance(entries, dict):
            raise HabitRepositoryError(f"本机 habits 第 {index + 1} 项 entries 无效。")
        checked_entries: dict[str, float | int] = {}
        for entry_date, value in entries.items():
            valid_date = _valid_date(
                entry_date, f"本机 habits 第 {index + 1} 项 entries 日期"
            )
            checked_entries[valid_date] = _number(
                value, f"本机 habits 第 {index + 1} 项 entries 值"
            )
        item["entries"] = checked_entries
        item["schedule"] = _normalize_schedule(
            item.get("schedule"), f"本机 habits 第 {index + 1} 项"
        )
        item["scheduleHistory"] = _normalize_schedule_history(
            item.get("scheduleHistory"), f"本机 habits 第 {index + 1} 项"
        )
        if not isinstance(item.get("tone"), str) or item.get("tone") not in _TONES:
            item["tone"] = "sage"
        if not isinstance(item.get("sample", False), bool):
            item["sample"] = bool(item.get("sample"))
        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            result.append(item)
    return result


def _create_runtime_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            habits_json TEXT NOT NULL,
            hidden_keys_json TEXT NOT NULL,
            local_ids_json TEXT NOT NULL
        )
        """
    )


def _insert_runtime(
    connection: sqlite3.Connection,
    habits: list[dict[str, Any]],
    hidden: list[str],
    local_ids: set[str],
) -> None:
    connection.execute(
        f"INSERT INTO {_TABLE}(singleton, habits_json, hidden_keys_json, local_ids_json) "
        "VALUES (1, ?, ?, ?)",
        (_json_dumps(habits), _json_dumps(hidden), _json_dumps(sorted(local_ids))),
    )


def _ensure_date_value(date_value: Any, value: Any) -> tuple[str, float | int]:
    return _valid_date(date_value), _number(value, "习惯数值")


class HabitRepository:
    """Materialized, transactional habits state backed by a dedicated table.

    ``legacy_store`` may be a :class:`MigrationPackage`, a ``load_imported_data``
    snapshot, the parsed ``richangji-state-v1`` document, or a habits list.
    Once the native state row exists, the legacy source is not consulted again
    unless :meth:`adopt_imported_data` is explicitly called.
    """

    def __init__(
        self,
        database_path: str | Path,
        legacy_store: Any = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser()
        self._lock = RLock()

        existing = _read_runtime(self.database_path)
        if existing is None:
            source = legacy_store
            if source is None:
                imported = load_imported_data(self.database_path)
                if imported.get("status") == "unavailable":
                    raise HabitRepositoryError(
                        imported.get("error") or "无法读取旧版导入数据。"
                    )
                source = imported
            habits, hidden = _seed_state(source)
            local_ids: set[str] = set()
            self._materialize_if_missing(habits, hidden, local_ids)
            existing = _read_runtime(self.database_path)
            if existing is None:
                raise HabitRepositoryError("无法初始化本机习惯状态。")

        self._habits = existing["habits"]
        self._hidden = existing["hidden"]
        self._local_ids = existing["local_ids"]

    def _materialize_if_missing(
        self, habits: list[dict[str, Any]], hidden: list[str], local_ids: set[str]
    ) -> None:
        path = self.database_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("BEGIN IMMEDIATE")
            _create_runtime_table(connection)
            present = connection.execute(
                f"SELECT 1 FROM {_TABLE} WHERE singleton = 1"
            ).fetchone()
            if present is None:
                _insert_runtime(connection, habits, hidden, local_ids)
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise HabitRepositoryError(f"初始化本机习惯状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _commit(
        self,
        habits: list[dict[str, Any]],
        hidden: list[str],
        local_ids: set[str],
    ) -> None:
        # Validate/copy before opening a write transaction. In-memory state is
        # switched only after SQLite commits successfully.
        cloned_habits = _json_copy(habits, "习惯状态")
        cloned_hidden = _hidden_keys(hidden)
        cloned_local_ids = {item for item in local_ids if isinstance(item, str)}
        encoded = (
            _json_dumps(cloned_habits),
            _json_dumps(cloned_hidden),
            _json_dumps(sorted(cloned_local_ids)),
        )
        connection: sqlite3.Connection | None = None
        try:
            path = self.database_path.resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("BEGIN IMMEDIATE")
            _create_runtime_table(connection)
            connection.execute(
                f"UPDATE {_TABLE} SET habits_json=?, hidden_keys_json=?, local_ids_json=? "
                "WHERE singleton=1",
                encoded,
            )
            if connection.total_changes == 0:
                _insert_runtime(connection, cloned_habits, cloned_hidden, cloned_local_ids)
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise HabitRepositoryError(f"保存习惯数据失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        self._habits = cloned_habits
        self._hidden = cloned_hidden
        self._local_ids = cloned_local_ids

    def habits(self) -> list[dict[str, Any]]:
        """Return detached habit payloads in display order."""
        with self._lock:
            return deepcopy(self._habits)

    def hidden_habit_keys(self) -> list[str]:
        """Return the ordered set of hidden built-in keys."""
        with self._lock:
            return list(self._hidden)

    def add_habit(self, definition: Any) -> dict[str, Any]:
        if not isinstance(definition, dict):
            raise HabitRepositoryError("新习惯定义必须是对象。")
        item = _json_copy(definition, "新习惯定义")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise HabitRepositoryError("习惯名称不能为空。")
        name = name.strip()
        if len(name) > 18:
            raise HabitRepositoryError("习惯名称最多 18 个字符。")
        habit_type = item.get("type", "check")
        if not isinstance(habit_type, str) or habit_type not in _TYPES:
            raise HabitRepositoryError("习惯类型必须是 check、counter 或 number。")
        target = 1 if habit_type == "check" else _positive_target(item.get("target", 1))
        unit = "次" if habit_type == "check" else item.get("unit", "次")
        if not isinstance(unit, str):
            raise HabitRepositoryError("习惯单位必须是字符串。")
        if len(unit) > 6:
            raise HabitRepositoryError("习惯单位最多 6 个字符。")
        tone = item.get("tone", "sage")
        if not isinstance(tone, str) or tone not in _TONES:
            raise HabitRepositoryError("习惯主题色无效。")
        schedule = _normalize_schedule(item.get("schedule"), "新习惯")

        habit_id = item.get("id") or f"habit-{uuid4()}"
        key = item.get("key") or f"custom-{uuid4()}"
        if not isinstance(habit_id, str) or not habit_id.strip():
            raise HabitRepositoryError("习惯 id 必须是非空字符串。")
        if not isinstance(key, str) or not key.strip():
            raise HabitRepositoryError("习惯 key 必须是非空字符串。")
        if key in _BUILTIN_BY_KEY:
            raise HabitRepositoryError("自定义习惯不能使用内置习惯 key。")
        created_date = item.get("createdDate", date.today().isoformat())
        _valid_date(created_date, "创建日期")
        raw_entries = item.get("entries", {})
        if not isinstance(raw_entries, dict):
            raise HabitRepositoryError("entries 必须是对象。")
        entries: dict[str, float | int] = {}
        for entry_date, value in raw_entries.items():
            valid_date, number = _ensure_date_value(entry_date, value)
            entries[valid_date] = number

        item.update(
            {
                "id": habit_id,
                "key": key,
                "name": name,
                "type": habit_type,
                "target": target,
                "unit": unit,
                "tone": tone,
                "entries": entries,
                "createdDate": created_date,
                "schedule": schedule,
                "scheduleHistory": _normalize_schedule_history(
                    item.get("scheduleHistory"), f"习惯 {name}"
                ),
                "sample": False,
            }
        )
        with self._lock:
            if any(existing["id"] == habit_id for existing in self._habits):
                raise HabitRepositoryError("习惯 id 已存在。")
            if any(existing["key"] == key for existing in self._habits):
                raise HabitRepositoryError("习惯 key 已存在。")
            next_habits = deepcopy(self._habits)
            next_habits.append(item)
            next_local_ids = set(self._local_ids)
            next_local_ids.add(habit_id)
            self._commit(next_habits, self._hidden, next_local_ids)
            return deepcopy(item)

    def delete_habit(self, habit_id: str) -> bool:
        if not isinstance(habit_id, str) or not habit_id:
            raise HabitRepositoryError("习惯 id 必须是非空字符串。")
        with self._lock:
            target = next((item for item in self._habits if item["id"] == habit_id), None)
            if target is None:
                return False
            next_habits = [item for item in deepcopy(self._habits) if item["id"] != habit_id]
            next_hidden = list(self._hidden)
            key = target.get("key")
            if key in _BUILTIN_BY_KEY and key not in next_hidden:
                next_hidden.append(key)
            next_local_ids = set(self._local_ids)
            next_local_ids.discard(habit_id)
            self._commit(next_habits, next_hidden, next_local_ids)
            return True

    def update_habit(
        self,
        habit_id: str,
        definition: Any,
        effective_date: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(habit_id, str) or not habit_id.strip():
            raise HabitRepositoryError("习惯 id 必须是非空字符串。")
        if not isinstance(definition, dict):
            raise HabitRepositoryError("习惯修改内容必须是对象。")
        patch = _json_copy(definition, "习惯修改内容")
        with self._lock:
            index = self._find_index(habit_id)
            current = deepcopy(self._habits[index])
            name = patch.get("name", current["name"])
            if not isinstance(name, str) or not name.strip():
                raise HabitRepositoryError("习惯名称不能为空。")
            name = name.strip()
            if len(name) > 18:
                raise HabitRepositoryError("习惯名称最多 18 个字符。")
            habit_type = patch.get("type", current["type"])
            if not isinstance(habit_type, str) or habit_type not in _TYPES:
                raise HabitRepositoryError("习惯类型必须是 check、counter 或 number。")
            target = 1 if habit_type == "check" else _positive_target(
                patch.get("target", current["target"])
            )
            unit = "次" if habit_type == "check" else patch.get("unit", current["unit"])
            if not isinstance(unit, str):
                raise HabitRepositoryError("习惯单位必须是字符串。")
            if len(unit) > 6:
                raise HabitRepositoryError("习惯单位最多 6 个字符。")
            tone = patch.get("tone", current["tone"])
            if not isinstance(tone, str) or tone not in _TONES:
                raise HabitRepositoryError("习惯主题色无效。")

            schedule = _normalize_schedule(
                patch.get("schedule", current.get("schedule")), "习惯修改"
            )
            history = _normalize_schedule_history(
                current.get("scheduleHistory"), f"习惯 {current['name']}"
            )
            if schedule != current.get("schedule", {"type": "daily"}):
                effective = _valid_date(
                    effective_date or date.today().isoformat(), "计划生效日期"
                )
                created_value = current.get("createdDate", "0001-01-01")
                try:
                    created = _valid_date(created_value, "创建日期")
                except HabitRepositoryError:
                    created = "0001-01-01"
                if not history:
                    history.append(
                        {
                            "effectiveDate": created,
                            "schedule": _normalize_schedule(
                                current.get("schedule"), f"习惯 {current['name']}"
                            ),
                        }
                    )
                if effective < history[-1]["effectiveDate"]:
                    raise HabitRepositoryError("计划生效日期不能早于已有计划变更。")
                if effective == history[-1]["effectiveDate"]:
                    history[-1] = {"effectiveDate": effective, "schedule": schedule}
                else:
                    history.append({"effectiveDate": effective, "schedule": schedule})

            current.update(
                {
                    "name": name,
                    "type": habit_type,
                    "target": target,
                    "unit": unit,
                    "tone": tone,
                    "schedule": schedule,
                    "scheduleHistory": history,
                }
            )
            next_habits = deepcopy(self._habits)
            next_habits[index] = current
            next_local_ids = set(self._local_ids)
            next_local_ids.add(habit_id)
            self._commit(next_habits, self._hidden, next_local_ids)
            return deepcopy(current)

    def set_value(self, habit_id: str, date_value: str, value: Any) -> dict[str, Any]:
        if not isinstance(habit_id, str) or not habit_id:
            raise HabitRepositoryError("习惯 id 必须是非空字符串。")
        valid_date = _valid_date(date_value)
        numeric = _finite_number(value, "习惯数值")
        with self._lock:
            index = self._find_index(habit_id)
            next_habits = deepcopy(self._habits)
            habit = next_habits[index]
            if habit["type"] == "check":
                if numeric not in (0, 1):
                    raise HabitRepositoryError("完成型习惯的数值只能是 0 或 1。")
            elif habit["type"] == "counter":
                numeric = max(0, numeric)
            elif habit["type"] == "number":
                numeric = min(9999, max(0, numeric))
            habit.setdefault("entries", {})[valid_date] = numeric
            self._commit(next_habits, self._hidden, self._local_ids)
            return deepcopy(habit)

    def adjust_counter(
        self, habit_id: str, date_value: str, delta: int
    ) -> dict[str, Any]:
        if isinstance(delta, bool) or not isinstance(delta, int):
            raise HabitRepositoryError("计数增量必须是整数。")
        valid_date = _valid_date(date_value)
        with self._lock:
            index = self._find_index(habit_id)
            next_habits = deepcopy(self._habits)
            habit = next_habits[index]
            if habit["type"] != "counter":
                raise HabitRepositoryError("只有计数型习惯可以调整计数。")
            current = habit["entries"].get(valid_date, 0)
            next_value = max(0, current + delta)
            habit["entries"][valid_date] = next_value
            self._commit(next_habits, self._hidden, self._local_ids)
            return deepcopy(habit)

    def quick_check(self, habit_id: str, date_value: str) -> dict[str, Any]:
        valid_date = _valid_date(date_value)
        with self._lock:
            index = self._find_index(habit_id)
            next_habits = deepcopy(self._habits)
            habit = next_habits[index]
            current = habit["entries"].get(valid_date, 0)
            target = habit["target"]
            habit["entries"][valid_date] = 0 if current >= target else target
            self._commit(next_habits, self._hidden, self._local_ids)
            return deepcopy(habit)

    def clear_samples(self) -> int:
        with self._lock:
            next_habits = deepcopy(self._habits)
            cleared = 0
            for habit in next_habits:
                if habit.get("sample"):
                    habit["entries"] = {}
                    habit["sample"] = False
                    cleared += 1
            if cleared:
                self._commit(next_habits, self._hidden, self._local_ids)
            return cleared

    def adopt_imported_data(
        self, habits: Any, hidden_keys: Any
    ) -> list[dict[str, Any]]:
        """Merge a later import snapshot without replacing local habits/check-ins.

        Existing native-created habits win ID collisions. For other matching IDs,
        imported fields refresh the legacy definition while current entries,
        remote row references, and sample state remain authoritative.
        """
        next_hidden = list(dict.fromkeys([*self.hidden_habit_keys(), *_hidden_keys(hidden_keys)]))
        incoming = _normalize_legacy_habits(habits, _hidden_keys(hidden_keys))
        with self._lock:
            current = deepcopy(self._habits)
            current_by_id = {item["id"]: item for item in current}
            next_habits = current
            for item in incoming:
                item_id = item["id"]
                item_key = item["key"]
                if item_key in _BUILTIN_BY_KEY and item_key in next_hidden:
                    continue
                existing = current_by_id.get(item_id)
                # A repository opened before migration may have seeded the
                # native default ID (for example ``habit-water``), while the
                # imported legacy row carries another ID for the same built-in
                # key. Adopt that row in place, preserving runtime check-ins
                # and remote references, but never replace a user-created row.
                if existing is None and item_key in _BUILTIN_BY_KEY:
                    existing = next(
                        (
                            row
                            for row in next_habits
                            if row.get("key") == item_key
                            and row.get("id") not in self._local_ids
                        ),
                        None,
                    )
                if existing is None:
                    # Key collisions with local rows are also preserved; old
                    # backups occasionally contain duplicate or regenerated IDs.
                    if any(row["key"] == item_key for row in next_habits):
                        continue
                    next_habits.append(deepcopy(item))
                    current_by_id[item_id] = next_habits[-1]
                    continue
                if item_id in self._local_ids:
                    continue
                merged = {**deepcopy(existing), **deepcopy(item)}
                merged["id"] = item_id
                if existing.get("sample") is False and item.get("sample") is True:
                    # A prior clear_samples() is a durable user choice; a
                    # delayed/repeated legacy import must not restore demo logs.
                    merged["entries"] = deepcopy(existing.get("entries", {}))
                else:
                    merged["entries"] = {
                        **deepcopy(item.get("entries", {})),
                        **deepcopy(existing.get("entries", {})),
                    }
                incoming_remote = item.get("remoteEntries")
                existing_remote = existing.get("remoteEntries")
                if incoming_remote is not None or existing_remote is not None:
                    merged["remoteEntries"] = {
                        **deepcopy(incoming_remote or {}),
                        **deepcopy(existing_remote or {}),
                    }
                else:
                    merged.pop("remoteEntries", None)
                merged["sample"] = existing.get("sample", item.get("sample", False))
                replaced_id = existing["id"]
                next_habits[next_habits.index(existing)] = merged
                current_by_id.pop(replaced_id, None)
                current_by_id[item_id] = merged

            next_habits = [
                item
                for item in next_habits
                if not (
                    item.get("key") in _BUILTIN_BY_KEY
                    and item.get("key") in next_hidden
                )
            ]
            self._commit(next_habits, next_hidden, self._local_ids)
            return deepcopy(self._habits)

    def metrics(self, date_value: str | None = None) -> dict[str, Any]:
        selected_date = _valid_date(date_value or date.today().isoformat())
        end = date.fromisoformat(selected_date)
        dates_30 = [(end - timedelta(days=offset)).isoformat() for offset in range(29, -1, -1)]
        dates_7 = dates_30[-7:]
        with self._lock:
            rows: list[dict[str, Any]] = []
            done_total = 0
            total_done_30 = 0
            total_done_7 = 0
            possible_30 = 0
            possible_7 = 0
            active_today = 0
            for habit in self._habits:
                entries = habit.get("entries", {})
                target = habit["target"]
                schedule = habit.get("schedule", {"type": "daily"})
                schedule_history = habit.get("scheduleHistory", [])
                created_text = habit.get("createdDate")
                try:
                    created_date = (
                        date.fromisoformat(created_text)
                        if isinstance(created_text, str)
                        else None
                    )
                except ValueError:
                    # Older/imported rows may not have trustworthy creation
                    # metadata; preserve their historical daily denominator.
                    created_date = None
                created_days = {
                    day: created_date is None or date.fromisoformat(day) >= created_date
                    for day in dates_30
                }
                due_days = {
                    day: _is_due_on(
                        _schedule_for_date(
                            schedule, schedule_history, date.fromisoformat(day)
                        ),
                        date.fromisoformat(day),
                    )
                    for day in dates_30
                }
                eligible_days = {
                    day: created_days[day] and due_days[day]
                    for day in dates_30
                }
                values = {day: entries.get(day, 0) for day in dates_30}
                done_days = {
                    day: eligible_days[day] and value >= target
                    for day, value in values.items()
                }
                is_done = done_days[selected_date]
                active_today += int(eligible_days[selected_date])
                done_total += int(is_done)
                count_30 = sum(done_days.values())
                count_7 = sum(done_days[day] for day in dates_7)
                total_done_30 += count_30
                total_done_7 += count_7
                possible_30 += sum(eligible_days.values())
                possible_7 += sum(eligible_days[day] for day in dates_7)
                streak = _streak_ending_on(
                    entries, target, end, schedule, created_date, schedule_history
                )
                best_streak = _best_streak(
                    entries, target, schedule, created_date, schedule_history
                )
                rows.append(
                    {
                        "id": habit["id"],
                        "key": habit["key"],
                        "name": habit["name"],
                        "type": habit["type"],
                        "schedule": schedule,
                        "value": values[selected_date],
                        "done": is_done,
                        "streak": streak,
                        "bestStreak": best_streak,
                        "done7": count_7,
                        "history": [
                            {
                                "date": day,
                                "value": values[day],
                                "done": done_days[day],
                                "active": created_days[day],
                                "due": due_days[day],
                                "eligible": eligible_days[day],
                                "partial": bool(values[day]) and not done_days[day],
                            }
                            for day in dates_30
                        ],
                    }
                )

            total = active_today
            rate_30 = round(total_done_30 / possible_30 * 100) if possible_30 else 0
            rate_7 = round(total_done_7 / possible_7 * 100) if possible_7 else 0
            top = sorted(rows, key=lambda row: -row["done7"])[:5]
            return {
                "date": selected_date,
                "done": done_total,
                "total": total,
                "bestStreak": max((row["bestStreak"] for row in rows), default=0),
                "completionRate30Days": rate_30,
                "habits": rows,
                "week": {
                    "days": dates_7,
                    "total": total_done_7,
                    "completionRate": rate_7,
                    "topHabits": [
                        {"id": row["id"], "name": row["name"], "count": row["done7"]}
                        for row in top
                    ],
                },
            }

    def _find_index(self, habit_id: str) -> int:
        if not isinstance(habit_id, str) or not habit_id:
            raise HabitRepositoryError("习惯 id 必须是非空字符串。")
        for index, habit in enumerate(self._habits):
            if habit["id"] == habit_id:
                return index
        raise HabitRepositoryError("找不到指定习惯。")


def _streak_ending_on(
    entries: dict[str, Any],
    target: float | int,
    end: date,
    schedule: dict[str, Any] | None = None,
    created_date: date | None = None,
    schedule_history: list[dict[str, Any]] | None = None,
) -> int:
    streak = 0
    cursor = end
    schedule = schedule or {"type": "daily"}
    if (
        end == date.today()
        and _is_due_on(_schedule_for_date(schedule, schedule_history or [], cursor), cursor)
        and entries.get(cursor.isoformat(), 0) < target
    ):
        cursor -= timedelta(days=1)
    while created_date is None or cursor >= created_date:
        while cursor >= (created_date or date.min) and not _is_due_on(
            _schedule_for_date(schedule, schedule_history or [], cursor), cursor
        ):
            cursor -= timedelta(days=1)
        if cursor < (created_date or date.min):
            break
        if entries.get(cursor.isoformat(), 0) < target:
            break
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _best_streak(
    entries: dict[str, Any],
    target: float | int,
    schedule: dict[str, Any] | None = None,
    created_date: date | None = None,
    schedule_history: list[dict[str, Any]] | None = None,
) -> int:
    if not entries:
        return 0
    best = 0
    current = 0
    schedule = schedule or {"type": "daily"}
    dates = [date.fromisoformat(date_text) for date_text in entries]
    cursor = min(dates)
    last = max(dates)
    if created_date is not None:
        cursor = max(cursor, created_date)
    while cursor <= last:
        if _is_due_on(
            _schedule_for_date(schedule, schedule_history or [], cursor), cursor
        ):
            if entries.get(cursor.isoformat(), 0) >= target:
                current += 1
                best = max(best, current)
            else:
                current = 0
        cursor += timedelta(days=1)
    return best
