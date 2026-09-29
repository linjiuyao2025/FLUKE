"""Local-first fitness records and plans backed by SQLite.

The imported ``richangji-state-v1`` snapshot is kept as an immutable base.
Native additions, record tombstones, and settings overrides live in a separate
runtime row. ``records()`` exposes the imported records plus this module's
fitness overlay; a cross-module daily-review merger should combine each module's
stream by ``(type, id)`` and apply all modules' tombstone keys. ``fitness_records()``
is the fitness-page projection.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any
from uuid import uuid4

from .database import load_imported_data
from .json_utils import copy_json
from .migration import MigrationPackage
from .spreadsheet_export import SpreadsheetExportError, export_xlsx


LEGACY_STATE_KEY = "richangji-state-v1"
_TABLE = "fitness_module_state"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_PROFILE: dict[str, Any] = {
    "height": 165,
    "target": 55,
    "startWeight": 60,
    "age": 30,
    "sex": "female",
    "activity": 1.375,
}

DEFAULT_WEEKLY_PLAN: tuple[dict[str, Any], ...] = (
    {"id": "move-1", "group": "运动", "title": "力量训练 2 次", "titleEn": "Strength training ×2",
     "note": "每次 30–40 分钟", "noteEn": "30–40 min each", "done": False},
    {"id": "move-2", "group": "运动", "title": "中低强度有氧 3 次", "titleEn": "Moderate cardio ×3",
     "note": "快走、骑行或游泳", "noteEn": "Walk / cycle / swim", "done": False},
    {"id": "meal-1", "group": "饮食", "title": "每餐一掌心蛋白质", "titleEn": "Palm-size protein per meal",
     "note": "鱼、蛋、瘦肉或豆制品", "noteEn": "Fish, eggs, lean meat or tofu", "done": False},
    {"id": "meal-2", "group": "饮食", "title": "午晚餐蔬菜占一半", "titleEn": "Veggies = half the plate",
     "note": "优先深色蔬菜", "noteEn": "Prefer dark greens", "done": False},
    {"id": "meal-3", "group": "饮食", "title": "主食不过度削减", "titleEn": "Don't cut carbs too much",
     "note": "每餐约一拳头", "noteEn": "~one fist per meal", "done": False},
    {"id": "meal-4", "group": "恢复", "title": "睡够 7 小时", "titleEn": "Sleep 7+ hours",
     "note": "恢复也是减脂计划", "noteEn": "Rest is part of fat loss", "done": False},
)
PLAN_GROUPS: tuple[str, ...] = ("运动", "饮食", "恢复", "其他")


class FitnessRepositoryError(ValueError):
    """Readable validation or persistence error for fitness operations."""


def _json_copy(value: Any, label: str) -> Any:
    return copy_json(value, label, FitnessRepositoryError)


def _date_value(value: Any, label: str = "日期") -> str:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise FitnessRepositoryError(f"{label} 必须使用 YYYY-MM-DD 日期。")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise FitnessRepositoryError(f"{label} 必须是有效日期。") from exc
    if parsed.isoformat() != value:
        raise FitnessRepositoryError(f"{label} 必须是有效日期。")
    return value


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise FitnessRepositoryError(f"{label} 必须是有效数值。")
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise FitnessRepositoryError(f"{label} 必须是有效数值。") from exc
    if not number.is_finite():
        raise FitnessRepositoryError(f"{label} 必须是有限数值。")
    return number


def _number_result(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _nonnegative_counter(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, number)


def _record_data(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data")
    return data if isinstance(data, dict) else {}


def _legacy_source(source: Any) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    """Copy the old state from a package, database snapshot, or parsed state."""
    main: Any = None
    has_main = False
    if isinstance(source, MigrationPackage):
        main = source.parsed_values.get(LEGACY_STATE_KEY)
        has_main = isinstance(main, dict)
    elif isinstance(source, list):
        main = {"records": source}
        has_main = True
    elif isinstance(source, dict):
        for container_name in ("parsed_values", "documents"):
            container = source.get(container_name)
            if isinstance(container, dict) and LEGACY_STATE_KEY in container:
                main = container[LEGACY_STATE_KEY]
                has_main = isinstance(main, dict)
                break
        if main is None and LEGACY_STATE_KEY in source:
            main = source[LEGACY_STATE_KEY]
            has_main = isinstance(main, dict)
        if main is None:
            for container_name in ("raw_values", "keys"):
                container = source.get(container_name)
                if isinstance(container, dict) and LEGACY_STATE_KEY in container:
                    raw = container[LEGACY_STATE_KEY]
                    if raw is not None:
                        if not isinstance(raw, str):
                            raise FitnessRepositoryError("旧版主状态原文必须是 JSON 字符串。")
                        try:
                            main = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            raise FitnessRepositoryError("旧版主状态原文不是有效 JSON。") from exc
                        has_main = isinstance(main, dict)
                        break
        if main is None:
            entities = source.get("entities")
            if isinstance(entities, dict) and "records" in entities:
                main = {"records": entities.get("records", []), "settings": {}}
                has_main = True
        if main is None and ("records" in source or "settings" in source):
            main = source
            has_main = True

    if main is None:
        return [], {}, False
    if not isinstance(main, dict):
        raise FitnessRepositoryError("旧版主状态必须是对象。")
    records = main.get("records", [])
    settings = main.get("settings", {})
    if records is None:
        records = []
    if settings is None:
        settings = {}
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise FitnessRepositoryError("旧版 records 必须是对象数组。")
    if not isinstance(settings, dict):
        raise FitnessRepositoryError("旧版 settings 必须是对象。")
    return _json_copy(records, "旧版 records"), _json_copy(settings, "旧版 settings"), has_main


def _normalize_runtime(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise FitnessRepositoryError("本机健身状态结构无效。")
    legacy_records = state.get("legacyRecords", [])
    local_records = state.get("localRecords", [])
    legacy_settings = state.get("legacySettings", {})
    setting_overrides = state.get("settingsOverrides", {})
    deleted = state.get("deletedRecords", [])
    local_fields = state.get("localFields", [])
    if not isinstance(legacy_records, list) or any(not isinstance(item, dict) for item in legacy_records):
        raise FitnessRepositoryError("本机旧记录必须是对象数组。")
    if not isinstance(local_records, list) or any(not isinstance(item, dict) for item in local_records):
        raise FitnessRepositoryError("本机新增记录必须是对象数组。")
    if not isinstance(legacy_settings, dict) or not isinstance(setting_overrides, dict):
        raise FitnessRepositoryError("本机设置结构无效。")
    if not isinstance(deleted, list):
        raise FitnessRepositoryError("本机删除标记必须是数组。")
    normalized_deleted: list[dict[str, Any]] = []
    seen_deleted: set[tuple[str, str]] = set()
    for item in deleted:
        if not isinstance(item, dict):
            raise FitnessRepositoryError("本机删除标记结构无效。")
        kind, record_id = item.get("type"), item.get("id")
        if not isinstance(kind, str) or not isinstance(record_id, str) or not record_id:
            raise FitnessRepositoryError("本机删除标记缺少记录类型或 id。")
        key = (kind, record_id)
        if key not in seen_deleted:
            normalized_deleted.append({**item, "type": kind, "id": record_id})
            seen_deleted.add(key)
    if not isinstance(local_fields, list) or any(not isinstance(item, str) for item in local_fields):
        raise FitnessRepositoryError("本机字段来源标记无效。")
    return {
        **state,
        "legacyRecords": _json_copy(legacy_records, "本机旧记录"),
        "localRecords": _json_copy(local_records, "本机新增记录"),
        "deletedRecords": normalized_deleted,
        "legacySettings": _json_copy(legacy_settings, "本机旧设置"),
        "settingsOverrides": _json_copy(setting_overrides, "本机设置覆盖"),
        "localFields": list(dict.fromkeys(local_fields)),
    }


def _initial_state(legacy_records: list[dict[str, Any]], legacy_settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "legacyRecords": legacy_records,
        "localRecords": [],
        "deletedRecords": [],
        "legacySettings": legacy_settings,
        "settingsOverrides": {},
        "localFields": [],
    }


def _read_runtime(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    connection: sqlite3.Connection | None = None
    try:
        uri = f"{path.expanduser().resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.execute("PRAGMA query_only=ON")
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_TABLE,)
        ).fetchone()
        if exists is None:
            return None
        row = connection.execute(f"SELECT state_json FROM {_TABLE} WHERE singleton=1").fetchone()
        return _normalize_runtime(json.loads(row[0])) if row else None
    except FitnessRepositoryError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise FitnessRepositoryError(f"无法读取本机健身状态：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()


class FitnessRepository:
    """Transactional fitness records, profile, and weekly-plan state."""

    def __init__(self, database_path: str | Path, legacy_store: Any = None) -> None:
        self.database_path = Path(database_path).expanduser()
        self._lock = RLock()
        source = legacy_store
        if source is None:
            imported = load_imported_data(self.database_path)
            if imported.get("status") == "unavailable":
                raise FitnessRepositoryError(imported.get("error") or "无法读取旧版导入数据。")
            source = imported
        records, settings, _ = _legacy_source(source)
        self._materialize_if_missing(_initial_state(records, settings))
        runtime = _read_runtime(self.database_path)
        if runtime is None:
            raise FitnessRepositoryError("无法初始化本机健身状态。")
        self._state = runtime

    def _materialize_if_missing(self, initial: dict[str, Any]) -> None:
        path = self.database_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1), state_json TEXT NOT NULL)"
            )
            row = connection.execute(f"SELECT 1 FROM {_TABLE} WHERE singleton=1").fetchone()
            if row is None:
                encoded = json.dumps(_normalize_runtime(initial), ensure_ascii=False,
                                     allow_nan=False, separators=(",", ":"))
                connection.execute(f"INSERT INTO {_TABLE}(singleton,state_json) VALUES(1,?)", (encoded,))
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise FitnessRepositoryError(f"初始化本机健身状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _commit(self, state: dict[str, Any]) -> None:
        cloned = _normalize_runtime(_json_copy(state, "健身状态"))
        encoded = json.dumps(cloned, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        connection: sqlite3.Connection | None = None
        try:
            path = self.database_path.resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1), state_json TEXT NOT NULL)"
            )
            connection.execute(
                f"INSERT INTO {_TABLE}(singleton,state_json) VALUES(1,?) "
                "ON CONFLICT(singleton) DO UPDATE SET state_json=excluded.state_json",
                (encoded,),
            )
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise FitnessRepositoryError(f"保存本机健身状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        self._state = cloned

    def _visible_records(self, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        source = state or self._state
        local_by_key = {
            (str(record.get("type", "")), str(record.get("id", ""))): record
            for record in source["localRecords"] if record.get("id") is not None
        }
        hidden = {
            (item["type"], item["id"])
            for item in source["deletedRecords"]
            if item["type"] == "fitness"
        }
        rows: list[dict[str, Any]] = []
        for record in source["legacyRecords"]:
            key = (str(record.get("type", "")), str(record.get("id", "")))
            if key not in hidden and key not in local_by_key:
                rows.append(record)
        for record in source["localRecords"]:
            key = (str(record.get("type", "")), str(record.get("id", "")))
            if key not in hidden:
                rows.append(record)
        return rows

    @staticmethod
    def _sort_records(records: list[dict[str, Any]], *, ascending: bool = False) -> list[dict[str, Any]]:
        return sorted(
            records,
            key=lambda item: (str(item.get("date", "")), _nonnegative_counter(item.get("createdAt", 0))),
            reverse=not ascending,
        )

    def records(self) -> list[dict[str, Any]]:
        """Return every effective record type; only fitness tombstones hide rows."""
        with self._lock:
            return _json_copy(self._visible_records(), "健身跨模块记录")

    def fitness_records(self, *, ascending: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            rows = [item for item in self._visible_records() if item.get("type") == "fitness"]
            return _json_copy(self._sort_records(rows, ascending=ascending), "健身记录")

    def deleted_record_keys(self) -> list[dict[str, str]]:
        with self._lock:
            fitness_deletions = [
                item for item in self._state["deletedRecords"] if item["type"] == "fitness"
            ]
            return _json_copy(fitness_deletions, "健身删除标记")

    def settings(self) -> dict[str, Any]:
        """Return full old settings, merging profile overrides field by field."""
        with self._lock:
            legacy = deepcopy(self._state["legacySettings"])
            overrides = deepcopy(self._state["settingsOverrides"])
            result = {**legacy, **overrides}
            old_profile = legacy.get("fitnessProfile")
            profile_override = overrides.get("fitnessProfile")
            profile = dict(DEFAULT_PROFILE)
            if isinstance(old_profile, dict):
                profile.update(deepcopy(old_profile))
            if isinstance(profile_override, dict):
                profile.update(deepcopy(profile_override))
            result["fitnessProfile"] = profile
            plan = overrides.get("weeklyPlan", legacy.get("weeklyPlan"))
            if not isinstance(plan, list) or any(not isinstance(item, dict) for item in plan):
                plan = [deepcopy(item) for item in DEFAULT_WEEKLY_PLAN]
            result["weeklyPlan"] = _json_copy(plan, "周计划")
            return _json_copy(result, "健身设置")

    def profile(self) -> dict[str, Any]:
        return deepcopy(self.settings()["fitnessProfile"])

    def profile_fields(self) -> list[str]:
        """Return only profile values supplied by imported data or the user."""
        with self._lock:
            fields: set[str] = set()
            for settings in (self._state["legacySettings"], self._state["settingsOverrides"]):
                profile = settings.get("fitnessProfile")
                if isinstance(profile, dict):
                    fields.update(
                        key for key in ("height", "target", "startWeight")
                        if key in profile and profile[key] is not None
                    )
            return sorted(fields)

    def weekly_plan(self) -> list[dict[str, Any]]:
        return deepcopy(self.settings()["weeklyPlan"])

    def _mark_local(self, state: dict[str, Any], field: str) -> None:
        if field not in state["localFields"]:
            state["localFields"].append(field)

    @staticmethod
    def _weight_input(value: Any) -> int | float:
        number = _decimal(value, "体重")
        if number < Decimal("20") or number > Decimal("300"):
            raise FitnessRepositoryError("体重必须在 20–300 kg 之间。")
        if number != number.quantize(Decimal("0.1")):
            raise FitnessRepositoryError("体重最多保留一位小数。")
        return _number_result(number)

    @staticmethod
    def _duration_input(value: Any) -> int:
        number = _decimal(value, "运动分钟")
        if number != number.to_integral_value() or number < 0 or number > 1440:
            raise FitnessRepositoryError("运动分钟必须是 0–1440 的整数。")
        return int(number)

    def add_record(
        self,
        weight: Any,
        duration: Any,
        day: str,
        note: str = "",
        *,
        record_id: str | None = None,
        created_at: int | None = None,
    ) -> dict[str, Any]:
        normalized_weight = self._weight_input(weight)
        normalized_duration = self._duration_input(0 if duration in (None, "") else duration)
        valid_day = _date_value(day)
        if not isinstance(note, str):
            raise FitnessRepositoryError("备注必须是文本。")
        normalized_note = note.strip()
        if len(normalized_note) > 60:
            raise FitnessRepositoryError("备注最多 60 个字符。")
        new_id = record_id or str(uuid4())
        if not isinstance(new_id, str) or not new_id.strip():
            raise FitnessRepositoryError("记录 id 必须是非空文本。")
        if created_at is not None and (
            isinstance(created_at, bool) or not isinstance(created_at, int) or created_at < 0
        ):
            raise FitnessRepositoryError("记录创建时间无效。")
        record = {
            "id": new_id,
            "type": "fitness",
            "date": valid_day,
            "createdAt": created_at if created_at is not None else int(datetime.now().astimezone().timestamp() * 1000),
            "sample": False,
            "data": {"weight": normalized_weight, "duration": normalized_duration, "note": normalized_note},
        }
        with self._lock:
            if any(item.get("id") == new_id for item in self._visible_records()):
                raise FitnessRepositoryError("记录 id 已存在。")
            if ("fitness", new_id) in {
                (item["type"], item["id"]) for item in self._state["deletedRecords"]
            }:
                raise FitnessRepositoryError("记录 id 已被本机删除标记占用。")
            state = deepcopy(self._state)
            state["localRecords"].append(record)
            self._mark_local(state, "records")
            self._commit(state)
        return deepcopy(record)

    def delete_record(self, record_id: str) -> bool:
        if not isinstance(record_id, str) or not record_id:
            raise FitnessRepositoryError("记录 id 无效。")
        with self._lock:
            target = next((item for item in self._visible_records()
                           if item.get("type") == "fitness" and item.get("id") == record_id), None)
            if target is None:
                return False
            state = deepcopy(self._state)
            local_index = next((index for index, item in enumerate(state["localRecords"])
                                if item.get("type") == "fitness" and item.get("id") == record_id), None)
            if local_index is not None:
                state["localRecords"].pop(local_index)
            else:
                tombstone = {"type": "fitness", "id": record_id}
                if tombstone not in state["deletedRecords"]:
                    state["deletedRecords"].append(tombstone)
            self._mark_local(state, "records")
            self._commit(state)
            return True

    def set_profile(
        self, *, height: Any = None, target: Any = None, start_weight: Any = None
    ) -> dict[str, Any]:
        updates: dict[str, int | float] = {}
        if height is not None:
            height_value = _decimal(height, "身高")
            if height_value != height_value.to_integral_value() or not Decimal("100") <= height_value <= Decimal("230"):
                raise FitnessRepositoryError("身高必须是 100–230 cm 的整数。")
            updates["height"] = int(height_value)
        if target is not None:
            target_value = _decimal(target, "目标体重")
            if not Decimal("30") <= target_value <= Decimal("200"):
                raise FitnessRepositoryError("目标体重必须在 30–200 kg 之间。")
            if target_value != target_value.quantize(Decimal("0.1")):
                raise FitnessRepositoryError("目标体重最多保留一位小数。")
            updates["target"] = _number_result(target_value)
        if start_weight is not None:
            start_value = _decimal(start_weight, "起始体重")
            if not Decimal("20") <= start_value <= Decimal("300"):
                raise FitnessRepositoryError("起始体重必须在 20–300 kg 之间。")
            if start_value != start_value.quantize(Decimal("0.1")):
                raise FitnessRepositoryError("起始体重最多保留一位小数。")
            updates["startWeight"] = _number_result(start_value)
        if not updates:
            return self.profile()
        with self._lock:
            state = deepcopy(self._state)
            current_override = state["settingsOverrides"].get("fitnessProfile")
            if not isinstance(current_override, dict):
                current_override = {}
            current_override.update(updates)
            state["settingsOverrides"]["fitnessProfile"] = current_override
            self._mark_local(state, "fitnessProfile")
            self._commit(state)
            return self.profile()

    def add_plan(self, group: str, title: str, note: str = "") -> dict[str, Any]:
        if not isinstance(group, str) or group not in PLAN_GROUPS:
            raise FitnessRepositoryError("计划类别必须是运动、饮食、恢复或其他。")
        if not isinstance(title, str) or not title.strip():
            raise FitnessRepositoryError("计划名称不能为空。")
        normalized_title = title.strip()
        if len(normalized_title) > 28:
            raise FitnessRepositoryError("计划名称最多 28 个字符。")
        if not isinstance(note, str):
            raise FitnessRepositoryError("计划说明必须是文本。")
        normalized_note = note.strip() or "按自己的节奏完成"
        if len(normalized_note) > 60:
            raise FitnessRepositoryError("计划说明最多 60 个字符。")
        item = {"id": str(uuid4()), "group": group, "title": normalized_title,
                "note": normalized_note, "done": False}
        with self._lock:
            state = deepcopy(self._state)
            settings = self.settings()
            plan = settings["weeklyPlan"]
            plan.append(item)
            state["settingsOverrides"]["weeklyPlan"] = plan
            self._mark_local(state, "weeklyPlan")
            self._commit(state)
        return deepcopy(item)

    def toggle_plan(self, plan_id: str) -> dict[str, Any] | None:
        if not isinstance(plan_id, str) or not plan_id:
            raise FitnessRepositoryError("计划 id 无效。")
        with self._lock:
            state = deepcopy(self._state)
            plan = self.settings()["weeklyPlan"]
            item = next((entry for entry in plan if str(entry.get("id", "")) == plan_id), None)
            if item is None:
                return None
            item["done"] = not bool(item.get("done", False))
            state["settingsOverrides"]["weeklyPlan"] = plan
            self._mark_local(state, "weeklyPlan")
            self._commit(state)
            return deepcopy(item)

    def delete_plan(self, plan_id: str) -> bool:
        if not isinstance(plan_id, str) or not plan_id:
            raise FitnessRepositoryError("计划 id 无效。")
        with self._lock:
            state = deepcopy(self._state)
            plan = self.settings()["weeklyPlan"]
            remaining = [item for item in plan if str(item.get("id", "")) != plan_id]
            if len(remaining) == len(plan):
                return False
            state["settingsOverrides"]["weeklyPlan"] = remaining
            self._mark_local(state, "weeklyPlan")
            self._commit(state)
            return True

    def _weighted_records(self) -> list[tuple[dict[str, Any], Decimal]]:
        rows: list[tuple[dict[str, Any], Decimal]] = []
        for record in self.fitness_records(ascending=True):
            raw = _record_data(record).get("weight")
            if raw in (None, "", 0, "0"):
                continue
            try:
                weight = _decimal(raw, "体重")
            except FitnessRepositoryError:
                continue
            if weight > 0:
                rows.append((record, weight))
        return rows

    def trend_points(
        self,
        days: int | None = None,
        today: str | date | None = None,
        all_records: bool = False,
    ) -> list[dict[str, Any]]:
        """Return chronological weight points, optionally limited by calendar days.

        The unfiltered form keeps the historical 30-measurement contract used by
        existing exports and callers. UI range filters are calendar based so
        sparse records are not mistaken for evenly spaced measurements.
        """
        weighted = self._weighted_records()
        if all_records:
            points = weighted
        elif days is None:
            points = weighted[-30:]
        else:
            if isinstance(days, bool) or days not in {30, 90, 365}:
                raise FitnessRepositoryError("趋势范围必须是 30、90 或 365 天。")
            if isinstance(today, datetime):
                today = today.date()
            if isinstance(today, date):
                end = today
            else:
                end = date.fromisoformat(_date_value(today, "今天")) if today is not None else date.today()
            start = end - timedelta(days=days - 1)
            points = []
            for item in weighted:
                raw_day = item[0].get("date")
                try:
                    record_day = date.fromisoformat(_date_value(raw_day))
                except FitnessRepositoryError:
                    continue
                if start <= record_day <= end:
                    points.append(item)
        result: list[dict[str, Any]] = []
        values = [weight for _, weight in points]
        for index, ((record, weight), _) in enumerate(zip(points, values)):
            window = values[max(0, index - 6):index + 1]
            average = sum(window, Decimal(0)) / Decimal(len(window))
            result.append({
                "date": str(record.get("date", "")),
                "weight": _number_result(weight),
                "average": float(average),
            })
        return result

    def summary(self, today: str | date | None = None) -> dict[str, Any]:
        if isinstance(today, datetime):
            today = today.date()
        if isinstance(today, date):
            today = today.isoformat()
        if today is not None:
            _date_value(today, "今天")
        weights = self._weighted_records()
        profile = self.profile()
        configured_fields = set(self.profile_fields())
        has_start = "startWeight" in configured_fields
        has_target = "target" in configured_fields
        has_height = "height" in configured_fields
        try:
            configured_start = _decimal(profile.get("startWeight", 60), "起始体重")
            if configured_start <= 0:
                configured_start = Decimal(60)
        except FitnessRepositoryError:
            configured_start = Decimal(60)
        try:
            target = _decimal(profile.get("target", 55), "目标体重")
            if target <= 0:
                target = Decimal(55)
        except FitnessRepositoryError:
            target = Decimal(55)
        try:
            height = _decimal(profile.get("height", 165), "身高")
            if height <= 0:
                height = Decimal(165)
        except FitnessRepositoryError:
            height = Decimal(165)

        current = weights[-1][1] if weights else (configured_start if has_start else None)
        start = configured_start if has_start else (weights[0][1] if weights else None)
        target_value = target if has_target else None
        height_value = height if has_height else None
        try:
            if current is None or height_value is None:
                raise InvalidOperation
            height_m = height_value / Decimal(100)
            bmi = current / (height_m * height_m)
        except (InvalidOperation, ZeroDivisionError):
            bmi = None
        remaining = max(Decimal(0), current - target_value) if current is not None and target_value is not None else None
        rate = Decimal(0)
        elapsed_days = 0
        if len(weights) >= 2:
            try:
                first_day = date.fromisoformat(str(weights[0][0].get("date", "")))
                last_day = date.fromisoformat(str(weights[-1][0].get("date", "")))
                elapsed_days = max(1, (last_day - first_day).days)
                rate = (weights[0][1] - weights[-1][1]) / Decimal(elapsed_days)
            except (TypeError, ValueError):
                elapsed_days = 0
                rate = Decimal(0)
        days = math.ceil(float(remaining / rate)) if remaining is not None and remaining > 0 and rate > 0 else None
        progress = None
        if start is not None and current is not None and target_value is not None:
            progress = Decimal(100) if start == target_value else (start - current) / (start - target_value) * Decimal(100)
            progress = min(Decimal(100), max(Decimal(0), progress))
        return {
            "records": [deepcopy(record) for record, _ in weights],
            "hasWeightRecord": bool(weights),
            "current": _number_result(current) if current is not None else None,
            "start": _number_result(start) if start is not None else None,
            "target": _number_result(target_value) if target_value is not None else None,
            "height": _number_result(height_value) if height_value is not None else None,
            "bmi": float(bmi) if bmi is not None else None,
            "remaining": _number_result(remaining) if remaining is not None else None,
            "dailyRate": float(rate),
            "elapsedDays": elapsed_days,
            "days": days,
            "progress": float(progress) if progress is not None else None,
        }

    def state(
        self,
        today: str | date | None = None,
        trend_days: int | None = None,
        trend_all: bool = False,
    ) -> dict[str, Any]:
        """Return a QML-ready fitness projection without losing source records."""
        return {
            "records": self.fitness_records(),
            "profile": self.profile(),
            "profileFields": self.profile_fields(),
            "weeklyPlan": self.weekly_plan(),
            "summary": self.summary(today),
            "trend": self.trend_points(days=trend_days, today=today, all_records=trend_all),
        }

    def excel_export_data(self, language: str = "zh") -> dict[str, Any]:
        if language not in {"zh", "en"}:
            raise FitnessRepositoryError("导出语言必须是 zh 或 en。")
        headers = (
            ["日期", "体重(kg)", "运动分钟", "备注"]
            if language == "zh"
            else ["Date", "Weight (kg)", "Exercise (min)", "Note"]
        )
        rows = []
        for record in self.fitness_records():
            data = _record_data(record)
            rows.append([
                record.get("date", ""),
                data.get("weight") or "",
                data.get("duration") or "",
                data.get("note") or "",
            ])
        return {"headers": headers, "rows": rows}

    def export_excel(self, target_path: str | Path, language: str = "zh") -> Path:
        """Export local records through the shared atomic XLSX helper."""
        data = self.excel_export_data(language)
        try:
            return export_xlsx(
                target_path,
                "健身记录" if language == "zh" else "Fitness",
                data["headers"],
                data["rows"],
            )
        except SpreadsheetExportError as exc:
            raise FitnessRepositoryError(str(exc)) from exc

    def adopt_imported_data(self, legacy_store: Any) -> bool:
        """Refresh the imported base while retaining native edits/tombstones."""
        records, settings, has_main = _legacy_source(legacy_store)
        if not has_main:
            return False
        with self._lock:
            state = deepcopy(self._state)
            state["legacyRecords"] = records
            state["legacySettings"] = settings
            self._commit(state)
        return True


__all__ = [
    "DEFAULT_PROFILE",
    "DEFAULT_WEEKLY_PLAN",
    "PLAN_GROUPS",
    "FitnessRepository",
    "FitnessRepositoryError",
]
