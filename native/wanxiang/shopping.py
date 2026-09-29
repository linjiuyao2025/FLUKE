"""Local-first shopping records backed by SQLite.

The imported ``richangji-state-v1`` envelope is kept as an immutable source.
New shopping rows, legacy-record field patches, tombstones, and the shopping
filter are stored in this module's local overlay.  The legacy ``home`` record
payload (including fields this version does not know about) is never rewritten.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from .database import load_imported_data
from .json_utils import copy_json
from .migration import MigrationPackage


LEGACY_STATE_KEY = "richangji-state-v1"
_TABLE = "shopping_module_state"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHOPPING_FILTERS = ("pending", "all", "bought")
SHOPPING_CATEGORIES = ("食品", "日用品", "家居", "数码", "药品", "其他")
SHOPPING_PRIORITIES = ("normal", "high", "low")


class ShoppingRepositoryError(ValueError):
    """Readable validation or persistence error for shopping operations."""


def _json_copy(value: Any, label: str) -> Any:
    return copy_json(value, label, ShoppingRepositoryError)


def _date_value(value: Any, label: str = "日期") -> str:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise ShoppingRepositoryError(f"{label} 必须使用 YYYY-MM-DD 日期。")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ShoppingRepositoryError(f"{label} 必须是有效日期。") from exc
    if parsed.isoformat() != value:
        raise ShoppingRepositoryError(f"{label} 必须是有效日期。")
    return value


def _today_string(value: str | date | None) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        value = value.isoformat()
    return _date_value(value or date.today().isoformat(), "今天")


def _record_data(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data")
    return data if isinstance(data, dict) else {}


def _legacy_source(source: Any) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    """Copy the old state from a package, imported snapshot, or parsed state."""
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
                            raise ShoppingRepositoryError("旧版主状态原文必须是 JSON 字符串。")
                        try:
                            main = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            raise ShoppingRepositoryError("旧版主状态原文不是有效 JSON。") from exc
                        has_main = isinstance(main, dict)
                        break
        if main is None:
            entities = source.get("entities")
            empty_snapshot = source.get("hasData") is False or source.get("status") in {
                "empty", "unavailable",
            }
            if isinstance(entities, dict) and "records" in entities and not empty_snapshot:
                main = {"records": entities.get("records", []), "settings": {}}
                has_main = True
        if main is None and ("records" in source or "settings" in source):
            main = source
            has_main = isinstance(main, dict)

    if main is None:
        return [], {}, False
    if not isinstance(main, dict):
        raise ShoppingRepositoryError("旧版主状态必须是对象。")
    records = main.get("records", [])
    settings = main.get("settings", {})
    if records is None:
        records = []
    if settings is None:
        settings = {}
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise ShoppingRepositoryError("旧版 records 必须是对象数组。")
    if not isinstance(settings, dict):
        raise ShoppingRepositoryError("旧版 settings 必须是对象。")
    return _json_copy(records, "旧版 records"), _json_copy(settings, "旧版 settings"), has_main


def _normalize_runtime(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ShoppingRepositoryError("本机待买状态结构无效。")
    legacy_records = state.get("legacyRecords", [])
    local_records = state.get("localRecords", [])
    record_overrides = state.get("recordOverrides", [])
    legacy_settings = state.get("legacySettings", {})
    setting_overrides = state.get("settingsOverrides", {})
    deleted = state.get("deletedRecords", [])
    local_fields = state.get("localFields", [])
    if not isinstance(legacy_records, list) or any(not isinstance(item, dict) for item in legacy_records):
        raise ShoppingRepositoryError("本机旧记录必须是对象数组。")
    if not isinstance(local_records, list) or any(not isinstance(item, dict) for item in local_records):
        raise ShoppingRepositoryError("本机新增记录必须是对象数组。")
    if not isinstance(record_overrides, list) or any(not isinstance(item, dict) for item in record_overrides):
        raise ShoppingRepositoryError("本机记录覆盖结构无效。")
    if not isinstance(legacy_settings, dict) or not isinstance(setting_overrides, dict):
        raise ShoppingRepositoryError("本机设置结构无效。")
    if not isinstance(deleted, list):
        raise ShoppingRepositoryError("本机删除标记必须是数组。")
    if not isinstance(local_fields, list) or any(not isinstance(item, str) for item in local_fields):
        raise ShoppingRepositoryError("本机字段来源标记无效。")

    normalized_deleted: list[dict[str, Any]] = []
    seen_deleted: set[tuple[str, str]] = set()
    for item in deleted:
        if not isinstance(item, dict):
            raise ShoppingRepositoryError("本机删除标记结构无效。")
        kind, record_id = item.get("type"), item.get("id")
        if not isinstance(kind, str) or not isinstance(record_id, str) or not record_id:
            raise ShoppingRepositoryError("本机删除标记缺少记录类型或 id。")
        key = (kind, record_id)
        if key not in seen_deleted:
            normalized_deleted.append({**item, "type": kind, "id": record_id})
            seen_deleted.add(key)

    for item in record_overrides:
        if item.get("type") != "home" or not isinstance(item.get("id"), str) or not item["id"]:
            raise ShoppingRepositoryError("本机待买记录覆盖缺少有效 id。")
        fields = item.get("fields", {})
        removed = item.get("removedDataFields", [])
        if not isinstance(fields, dict) or not isinstance(removed, list) or any(not isinstance(x, str) for x in removed):
            raise ShoppingRepositoryError("本机待买记录覆盖字段无效。")
    return {
        **state,
        "legacyRecords": _json_copy(legacy_records, "本机旧记录"),
        "localRecords": _json_copy(local_records, "本机新增记录"),
        "recordOverrides": _json_copy(record_overrides, "本机记录覆盖"),
        "deletedRecords": normalized_deleted,
        "legacySettings": _json_copy(legacy_settings, "本机旧设置"),
        "settingsOverrides": _json_copy(setting_overrides, "本机设置覆盖"),
        "localFields": list(dict.fromkeys(local_fields)),
    }


def _initial_state(
    legacy_records: list[dict[str, Any]], legacy_settings: dict[str, Any]
) -> dict[str, Any]:
    return {
        "legacyRecords": legacy_records,
        "localRecords": [],
        "recordOverrides": [],
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
        row = connection.execute(
            f"SELECT state_json FROM {_TABLE} WHERE singleton=1"
        ).fetchone()
        return _normalize_runtime(json.loads(row[0])) if row else None
    except ShoppingRepositoryError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise ShoppingRepositoryError(f"无法读取本机待买状态：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()


class ShoppingRepository:
    """Transactional shopping records, overlays, and filter persistence."""

    def __init__(
        self,
        database_path: str | Path,
        legacy_store: Any = None,
        *,
        today_provider: Callable[[], str | date] | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser()
        self._lock = RLock()
        self._today_provider = today_provider or date.today
        source = legacy_store
        if source is None:
            imported = load_imported_data(self.database_path)
            if imported.get("status") == "unavailable":
                raise ShoppingRepositoryError(imported.get("error") or "无法读取旧版导入数据。")
            source = imported
        legacy_records, legacy_settings, _ = _legacy_source(source)
        self._materialize_if_missing(_initial_state(legacy_records, legacy_settings))
        runtime = _read_runtime(self.database_path)
        if runtime is None:
            raise ShoppingRepositoryError("无法初始化本机待买状态。")
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
            row = connection.execute(
                f"SELECT 1 FROM {_TABLE} WHERE singleton=1"
            ).fetchone()
            if row is None:
                encoded = json.dumps(
                    _normalize_runtime(initial), ensure_ascii=False, allow_nan=False,
                    separators=(",", ":"),
                )
                connection.execute(
                    f"INSERT INTO {_TABLE}(singleton,state_json) VALUES(1,?)", (encoded,)
                )
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise ShoppingRepositoryError(f"初始化本机待买状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _commit(self, state: dict[str, Any]) -> None:
        cloned = _normalize_runtime(_json_copy(state, "待买状态"))
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
            raise ShoppingRepositoryError(f"保存本机待买状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        self._state = cloned

    def _today(self) -> str:
        try:
            value = self._today_provider()
            return _today_string(value)
        except (TypeError, ValueError) as exc:
            raise ShoppingRepositoryError("本机日期来源无效。") from exc

    def _mark_local(self, state: dict[str, Any], field: str) -> None:
        if field not in state["localFields"]:
            state["localFields"].append(field)

    def legacy_records(self) -> list[dict[str, Any]]:
        """Return the untouched imported envelope records, for audits and projections."""
        with self._lock:
            return _json_copy(self._state["legacyRecords"], "旧版 records")

    def _deleted_keys(self) -> set[tuple[str, str]]:
        return {
            (item["type"], item["id"])
            for item in self._state["deletedRecords"]
            if item["type"] == "home"
        }

    def _override_map(self) -> dict[tuple[str, str], dict[str, Any]]:
        return {
            (item["type"], item["id"]): item
            for item in self._state["recordOverrides"]
        }

    @staticmethod
    def _apply_override(record: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(record)
        data = result.get("data")
        if not isinstance(data, dict):
            data = {}
            result["data"] = data
        data.update(deepcopy(override.get("fields", {})))
        for key in override.get("removedDataFields", []):
            data.pop(key, None)
        return result

    def records(self) -> list[dict[str, Any]]:
        """Return all effective records, applying only this module's home overlays."""
        with self._lock:
            deleted = self._deleted_keys()
            overrides = self._override_map()
            local_by_key = {
                (str(item.get("type", "")), str(item.get("id", ""))): item
                for item in self._state["localRecords"] if item.get("id") is not None
            }
            rows: list[dict[str, Any]] = []
            for record in self._state["legacyRecords"]:
                key = (str(record.get("type", "")), str(record.get("id", "")))
                if key[0] == "home" and key in deleted:
                    continue
                if key in local_by_key:
                    continue
                override = overrides.get(key) if key[0] == "home" else None
                rows.append(self._apply_override(record, override) if override else deepcopy(record))
            for record in self._state["localRecords"]:
                key = (str(record.get("type", "")), str(record.get("id", "")))
                if key[0] == "home" and key not in deleted:
                    rows.append(deepcopy(record))
            return _json_copy(rows, "待买跨模块记录")

    def deleted_record_keys(self) -> list[dict[str, str]]:
        with self._lock:
            return _json_copy(
                [item for item in self._state["deletedRecords"] if item["type"] == "home"],
                "待买删除标记",
            )

    def settings(self) -> dict[str, Any]:
        """Return all old settings merged with local overrides, preserving unknown keys."""
        with self._lock:
            result = {
                **deepcopy(self._state["legacySettings"]),
                **deepcopy(self._state["settingsOverrides"]),
            }
            return _json_copy(result, "待买设置")

    def current_filter(self) -> str:
        value = self.settings().get("shoppingFilter", "pending")
        return value if isinstance(value, str) and value in SHOPPING_FILTERS else "pending"

    @staticmethod
    def _sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def created_at(item: dict[str, Any]) -> int:
            value = item.get("createdAt", 0)
            try:
                return max(0, int(value)) if not isinstance(value, bool) else 0
            except (TypeError, ValueError, OverflowError):
                return 0

        return sorted(
            records,
            key=lambda item: (str(item.get("date", "")), created_at(item)),
            reverse=True,
        )

    @staticmethod
    def _price_value(value: Any) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
            return Decimal(0)
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return Decimal(0)
        return number if number.is_finite() else Decimal(0)

    @staticmethod
    def _decimal_result(value: Decimal) -> int | float:
        if value == value.to_integral_value():
            return int(value)
        return float(value)

    def shopping_records(self, filter_value: str | None = None) -> list[dict[str, Any]]:
        selected = self.current_filter() if filter_value is None else filter_value
        if not isinstance(selected, str) or selected not in SHOPPING_FILTERS:
            raise ShoppingRepositoryError("待买清单筛选必须是 pending、all 或 bought。")
        with self._lock:
            rows = [item for item in self.records() if item.get("type") == "home"]
            if selected == "pending":
                rows = [item for item in rows if not _record_data(item).get("bought")]
            elif selected == "bought":
                rows = [item for item in rows if bool(_record_data(item).get("bought"))]
            return self._sort_records(rows)

    def summary(self, today: str | date | None = None) -> dict[str, Any]:
        today_key = _today_string(today if today is not None else self._today())
        today_date = date.fromisoformat(today_key)
        month_key = today_key[:7]
        rows = [item for item in self.records() if item.get("type") == "home"]
        pending = [item for item in rows if not _record_data(item).get("bought")]
        bought = [item for item in rows if bool(_record_data(item).get("bought"))]
        pending_total = sum((self._price_value(_record_data(item).get("price", 0)) for item in pending), Decimal(0))
        month_bought = 0
        for item in bought:
            data = _record_data(item)
            purchased_on = data.get("boughtDate") or item.get("date", "")
            if isinstance(purchased_on, str) and purchased_on.startswith(month_key):
                month_bought += 1

        dated_pending: list[tuple[date, dict[str, Any]]] = []
        aged_pending: list[tuple[date, dict[str, Any]]] = []
        for item in pending:
            value = item.get("date")
            if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
                continue
            try:
                added_on = date.fromisoformat(value)
            except ValueError:
                continue
            if added_on <= today_date:
                dated_pending.append((added_on, item))
            age = (today_date - added_on).days
            if 0 <= age and age >= 7:
                aged_pending.append((added_on, item))

        earliest: dict[str, Any] | None = None
        if dated_pending:
            added_on, item = min(dated_pending, key=lambda pair: pair[0])
            data = _record_data(item)
            earliest = {
                "id": item.get("id", ""),
                "name": str(data.get("name", "待买物品")),
                "date": added_on.isoformat(),
                "days": max(0, (today_date - added_on).days),
            }

        # Mirror the old home insight: show the oldest three aged entries when
        # any have reached seven days; otherwise show the three highest prices.
        if aged_pending:
            insight_rows = [item for _, item in sorted(aged_pending, key=lambda pair: pair[0])[:3]]
        else:
            insight_rows = sorted(
                pending,
                key=lambda item: self._price_value(_record_data(item).get("price", 0)),
                reverse=True,
            )[:3]
        insights = [
            {
                "id": item.get("id", ""),
                "name": str(_record_data(item).get("name", "待买物品")),
                "date": str(item.get("date", "")),
                "price": self._decimal_result(self._price_value(_record_data(item).get("price", 0))),
                "aged": any(item.get("id") == aged.get("id") for _, aged in aged_pending),
            }
            for item in insight_rows
        ]
        return {
            "pendingCount": len(pending),
            "pendingAmount": self._decimal_result(pending_total),
            "purchasedThisMonthCount": month_bought,
            "addedAtLeastSevenDaysCount": len(aged_pending),
            "earliestPending": earliest,
            "insights": insights,
            "month": month_key,
        }

    def state(self, today: str | date | None = None) -> dict[str, Any]:
        return {
            "records": self.records(),
            "shoppingRecords": self.shopping_records(),
            "settings": self.settings(),
            "filter": self.current_filter(),
            "summary": self.summary(today),
        }

    def adopt_imported_data(self, snapshot: Any) -> bool:
        """Adopt a later migration snapshot without dropping local overlays.

        New legacy records replace the previous imported base. Legacy settings
        are refreshed key-by-key so keys unknown to this module survive if a
        later snapshot omits them; ``settingsOverrides`` remains authoritative
        for every setting changed locally.
        """
        records, settings, has_main = _legacy_source(snapshot)
        if not has_main:
            return False
        with self._lock:
            state = deepcopy(self._state)
            state["legacyRecords"] = records
            state["legacySettings"] = {
                **deepcopy(state["legacySettings"]),
                **settings,
            }
            self._commit(state)
        return True

    def set_filter(self, value: str) -> str:
        if not isinstance(value, str) or value not in SHOPPING_FILTERS:
            raise ShoppingRepositoryError("待买清单筛选必须是 pending、all 或 bought。")
        with self._lock:
            state = deepcopy(self._state)
            state["settingsOverrides"]["shoppingFilter"] = value
            self._mark_local(state, "shoppingFilter")
            self._commit(state)
        return value

    def add_item(
        self,
        name: str,
        quantity: str = "",
        category: str = "其他",
        price: Any = 0,
        priority: str = "normal",
        note: str = "",
        *,
        record_id: str | None = None,
        day: str | date | None = None,
        created_at: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise ShoppingRepositoryError("物品名称不能为空。")
        normalized_name = name.strip()
        if len(normalized_name) > 40:
            raise ShoppingRepositoryError("物品名称最多 40 个字符。")
        if not isinstance(quantity, str):
            raise ShoppingRepositoryError("数量必须是文本。")
        normalized_quantity = quantity.strip()
        if len(normalized_quantity) > 16:
            raise ShoppingRepositoryError("数量最多 16 个字符。")
        if not isinstance(category, str) or category not in SHOPPING_CATEGORIES:
            raise ShoppingRepositoryError("请选择有效的物品分类。")
        if not isinstance(priority, str) or priority not in SHOPPING_PRIORITIES:
            raise ShoppingRepositoryError("请选择有效的优先级。")
        if not isinstance(note, str):
            raise ShoppingRepositoryError("备注必须是文本。")
        normalized_note = note.strip()
        if len(normalized_note) > 60:
            raise ShoppingRepositoryError("备注最多 60 个字符。")
        price_value = Decimal(0) if price in (None, "") else self._price_value(price)
        if price not in (None, "") and (isinstance(price, bool) or not isinstance(price, (int, float, str, Decimal))):
            raise ShoppingRepositoryError("预计单价必须是有效数值。")
        if price not in (None, ""):
            try:
                parsed_price = Decimal(str(price).strip())
            except (InvalidOperation, ValueError) as exc:
                raise ShoppingRepositoryError("预计单价必须是有效数值。") from exc
            if not parsed_price.is_finite() or parsed_price < 0:
                raise ShoppingRepositoryError("预计单价不能小于 0。")
            try:
                if parsed_price != parsed_price.quantize(Decimal("0.01")):
                    raise ShoppingRepositoryError("预计单价最多保留两位小数。")
            except InvalidOperation as exc:
                raise ShoppingRepositoryError("预计单价最多保留两位小数。") from exc
            price_value = parsed_price
        new_id = record_id or str(uuid4())
        if not isinstance(new_id, str) or not new_id.strip():
            raise ShoppingRepositoryError("记录 id 必须是非空文本。")
        if created_at is not None and (
            isinstance(created_at, bool) or not isinstance(created_at, int) or created_at < 0
        ):
            raise ShoppingRepositoryError("记录创建时间无效。")
        day_key = _today_string(day if day is not None else self._today())
        record = {
            "id": new_id,
            "type": "home",
            "date": day_key,
            "createdAt": created_at if created_at is not None else int(datetime.now().astimezone().timestamp() * 1000),
            "sample": False,
            "data": {
                "name": normalized_name,
                "quantity": normalized_quantity,
                "category": category,
                "price": self._decimal_result(price_value),
                "priority": priority,
                "note": normalized_note,
                "bought": False,
            },
        }
        with self._lock:
            visible = self.records()
            if any(str(item.get("id", "")) == new_id for item in visible):
                raise ShoppingRepositoryError("记录 id 已存在。")
            if ("home", new_id) in self._deleted_keys():
                raise ShoppingRepositoryError("记录 id 已被本机删除标记占用。")
            state = deepcopy(self._state)
            state["localRecords"].append(record)
            self._mark_local(state, "records")
            self._commit(state)
        return deepcopy(record)

    def toggle_bought(
        self,
        record_id: str,
        bought: bool | None = None,
        *,
        bought_date: str | date | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(record_id, str) or not record_id:
            raise ShoppingRepositoryError("记录 id 无效。")
        with self._lock:
            target = next(
                (item for item in self.shopping_records("all") if str(item.get("id", "")) == record_id),
                None,
            )
            if target is None:
                return None
            data = _record_data(target)
            new_bought = not bool(data.get("bought")) if bought is None else bought
            if not isinstance(new_bought, bool):
                raise ShoppingRepositoryError("已买状态必须是布尔值。")
            state = deepcopy(self._state)
            local_index = next(
                (i for i, item in enumerate(state["localRecords"])
                 if item.get("type") == "home" and str(item.get("id", "")) == record_id),
                None,
            )
            if local_index is not None:
                local_copy = deepcopy(state["localRecords"][local_index])
                local_data = local_copy.get("data")
                if not isinstance(local_data, dict):
                    local_data = {}
                    local_copy["data"] = local_data
                local_data["bought"] = new_bought
                if new_bought:
                    local_data["boughtDate"] = _today_string(
                        bought_date if bought_date is not None else self._today()
                    )
                else:
                    local_data.pop("boughtDate", None)
                state["localRecords"][local_index] = local_copy
            else:
                fields: dict[str, Any] = {"bought": new_bought}
                removed_fields: list[str] = []
                if new_bought:
                    fields["boughtDate"] = _today_string(
                        bought_date if bought_date is not None else self._today()
                    )
                else:
                    removed_fields.append("boughtDate")
                override = {
                    "type": "home",
                    "id": record_id,
                    "fields": fields,
                    "removedDataFields": removed_fields,
                }
                existing = next(
                    (i for i, item in enumerate(state["recordOverrides"])
                     if item.get("type") == "home" and item.get("id") == record_id),
                    None,
                )
                if existing is None:
                    state["recordOverrides"].append(override)
                else:
                    state["recordOverrides"][existing] = override
            self._mark_local(state, "records")
            self._commit(state)
            return next(
                item for item in self.shopping_records("all") if str(item.get("id", "")) == record_id
            )

    def delete_item(self, record_id: str) -> bool:
        if not isinstance(record_id, str) or not record_id:
            raise ShoppingRepositoryError("记录 id 无效。")
        with self._lock:
            target = next(
                (item for item in self.shopping_records("all") if str(item.get("id", "")) == record_id),
                None,
            )
            if target is None:
                return False
            state = deepcopy(self._state)
            local_index = next(
                (i for i, item in enumerate(state["localRecords"])
                 if item.get("type") == "home" and str(item.get("id", "")) == record_id),
                None,
            )
            if local_index is not None:
                state["localRecords"].pop(local_index)
            else:
                key = {"type": "home", "id": record_id}
                if key not in state["deletedRecords"]:
                    state["deletedRecords"].append(key)
            state["recordOverrides"] = [
                item for item in state["recordOverrides"]
                if not (item.get("type") == "home" and item.get("id") == record_id)
            ]
            self._mark_local(state, "records")
            self._commit(state)
            return True
