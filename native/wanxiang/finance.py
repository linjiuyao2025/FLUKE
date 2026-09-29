"""Local-first finance records and summaries backed by SQLite.

The imported ``richangji-state-v1`` remains an immutable migration snapshot.
This repository keeps a base copy for cross-module projections and applies
native additions/deletions as an overlay. ``records()`` returns the complete
effective record stream (all legacy types plus native additions, less local
tombstones); ``money_records()`` is the finance-page projection. This lets
daily review combine finance, fitness, planner, and shopping records without
discarding records owned by modules that have not migrated yet.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
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


LEGACY_STATE_KEY = "richangji-state-v1"
_TABLE = "finance_module_state"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

EXPENSE_CATEGORIES: tuple[str, ...] = (
    "吃饭", "交通", "购物", "娱乐", "房租", "看病", "学习", "其他"
)
INCOME_CATEGORIES: tuple[str, ...] = ("工资", "奖金", "兼职", "理财", "其他")
ALL_CATEGORIES: tuple[str, ...] = tuple(
    dict.fromkeys((*EXPENSE_CATEGORIES, *INCOME_CATEGORIES))
)


class FinanceRepositoryError(ValueError):
    """Readable validation or persistence error for finance operations."""


def _json_copy(value: Any, label: str) -> Any:
    return copy_json(value, label, FinanceRepositoryError)


def _date_value(value: Any, label: str = "日期") -> str:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise FinanceRepositoryError(f"{label} 必须使用 YYYY-MM-DD 日期。")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise FinanceRepositoryError(f"{label} 必须是有效日期。") from exc
    if parsed.isoformat() != value:
        raise FinanceRepositoryError(f"{label} 必须是有效日期。")
    return value


def _amount_decimal(value: Any, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise FinanceRepositoryError("金额必须是有效数值。")
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise FinanceRepositoryError("金额必须是有效数值。") from exc
    if not amount.is_finite():
        raise FinanceRepositoryError("金额必须是有限数值。")
    if positive and amount <= 0:
        raise FinanceRepositoryError("金额必须大于 0。")
    return amount


def _money_input(value: Any) -> int | float:
    amount = _amount_decimal(value, positive=True)
    try:
        is_cent_value = amount == amount.quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise FinanceRepositoryError("金额最多保留两位小数。") from exc
    if not is_cent_value:
        raise FinanceRepositoryError("金额最多保留两位小数。")
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def _nonnegative_counter(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, number)


def _record_amount(record: dict[str, Any]) -> Decimal:
    try:
        return _amount_decimal(_record_data(record).get("amount", 0))
    except FinanceRepositoryError:
        # Historical imports are retained byte-for-byte in the migration
        # tables. A malformed historical amount contributes zero to summaries.
        return Decimal(0)


def _record_data(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data")
    return data if isinstance(data, dict) else {}


def _today_string(value: str | date | None) -> str:
    if isinstance(value, datetime):
        value = value.date().isoformat()
    elif isinstance(value, date):
        value = value.isoformat()
    return _date_value(value or date.today().isoformat(), "今天")


def _decimal_result(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _legacy_source(source: Any) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    """Copy the old state from a package, SQLite snapshot, or parsed state."""
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
                            raise FinanceRepositoryError("旧版主状态原文必须是 JSON 字符串。")
                        try:
                            main = json.loads(raw)
                        except json.JSONDecodeError as exc:
                            raise FinanceRepositoryError("旧版主状态原文不是有效 JSON。") from exc
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
        raise FinanceRepositoryError("旧版主状态必须是对象。")
    records = main.get("records", [])
    settings = main.get("settings", {})
    if records is None:
        records = []
    if settings is None:
        settings = {}
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise FinanceRepositoryError("旧版 records 必须是对象数组。")
    if not isinstance(settings, dict):
        raise FinanceRepositoryError("旧版 settings 必须是对象。")
    return (
        _json_copy(records, "旧版 records"),
        _json_copy(settings, "旧版 settings"),
        has_main,
    )


def _normalize_runtime(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise FinanceRepositoryError("本机记账状态结构无效。")
    legacy_records = state.get("legacyRecords", [])
    local_records = state.get("localRecords", [])
    legacy_settings = state.get("legacySettings", {})
    setting_overrides = state.get("settingsOverrides", {})
    deleted = state.get("deletedRecords", [])
    local_fields = state.get("localFields", [])
    added = state.get("addedSinceExport", {"records": 0, "money": 0})
    if not isinstance(legacy_records, list) or any(not isinstance(item, dict) for item in legacy_records):
        raise FinanceRepositoryError("本机旧记录必须是对象数组。")
    if not isinstance(local_records, list) or any(not isinstance(item, dict) for item in local_records):
        raise FinanceRepositoryError("本机新增记录必须是对象数组。")
    if not isinstance(legacy_settings, dict) or not isinstance(setting_overrides, dict):
        raise FinanceRepositoryError("本机设置结构无效。")
    if not isinstance(deleted, list):
        raise FinanceRepositoryError("本机删除标记必须是数组。")
    normalized_deleted: list[dict[str, str]] = []
    seen_deleted: set[tuple[str, str]] = set()
    for item in deleted:
        if not isinstance(item, dict):
            raise FinanceRepositoryError("本机删除标记结构无效。")
        kind, record_id = item.get("type"), item.get("id")
        if not isinstance(kind, str) or not isinstance(record_id, str) or not record_id:
            raise FinanceRepositoryError("本机删除标记缺少记录类型或 id。")
        key = (kind, record_id)
        if key not in seen_deleted:
            normalized_deleted.append({**item, "type": kind, "id": record_id})
            seen_deleted.add(key)
    if not isinstance(local_fields, list) or any(not isinstance(item, str) for item in local_fields):
        raise FinanceRepositoryError("本机字段来源标记无效。")
    if not isinstance(added, dict):
        raise FinanceRepositoryError("本机导出计数结构无效。")
    return {
        **state,
        "legacyRecords": _json_copy(legacy_records, "本机旧记录"),
        "localRecords": _json_copy(local_records, "本机新增记录"),
        "deletedRecords": normalized_deleted,
        "legacySettings": _json_copy(legacy_settings, "本机旧设置"),
        "settingsOverrides": _json_copy(setting_overrides, "本机设置覆盖"),
        "localFields": list(dict.fromkeys(local_fields)),
        "addedSinceExport": {
            "records": _nonnegative_counter(added.get("records", 0)),
            "money": _nonnegative_counter(added.get("money", 0)),
        },
        "exportBaselineReset": bool(state.get("exportBaselineReset", False)),
    }


def _initial_state(
    legacy_records: list[dict[str, Any]], legacy_settings: dict[str, Any]
) -> dict[str, Any]:
    return {
        "legacyRecords": legacy_records,
        "localRecords": [],
        "deletedRecords": [],
        "legacySettings": legacy_settings,
        "settingsOverrides": {},
        "localFields": [],
        "addedSinceExport": {"records": 0, "money": 0},
        "exportBaselineReset": False,
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
    except FinanceRepositoryError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise FinanceRepositoryError(f"无法读取本机记账状态：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()


class FinanceRepository:
    """Transactional money state with immutable legacy records and tombstones.

    ``records()`` returns every effective record from the imported source plus
    native finance additions, preserving source order and all fields; local
    tombstones hide deleted rows by ``(type, id)``. Other record types are
    retained and returned unchanged for downstream daily-review merging.
    Use ``money_records()`` for finance UI lists and ``deleted_record_keys()``
    to apply this module's deletions when merging projections from modules.
    """

    def __init__(self, database_path: str | Path, legacy_store: Any = None) -> None:
        self.database_path = Path(database_path).expanduser()
        self._lock = RLock()
        source = legacy_store
        if source is None:
            imported = load_imported_data(self.database_path)
            if imported.get("status") == "unavailable":
                raise FinanceRepositoryError(imported.get("error") or "无法读取旧版导入数据。")
            source = imported
        records, settings, _ = _legacy_source(source)
        self._materialize_if_missing(_initial_state(records, settings))
        runtime = _read_runtime(self.database_path)
        if runtime is None:
            raise FinanceRepositoryError("无法初始化本机记账状态。")
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
                connection.execute(
                    f"INSERT INTO {_TABLE}(singleton,state_json) VALUES(1,?)",
                    (json.dumps(_normalize_runtime(initial), ensure_ascii=False, allow_nan=False,
                                separators=(",", ":")),),
                )
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise FinanceRepositoryError(f"初始化本机记账状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _commit(self, state: dict[str, Any]) -> None:
        cloned = _normalize_runtime(_json_copy(state, "记账状态"))
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
            raise FinanceRepositoryError(f"保存本机记账状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        self._state = cloned

    def _visible_records(self, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        source = state or self._state
        local_by_key = {
            (str(record.get("type", "")), str(record.get("id", ""))): record
            for record in source["localRecords"]
            if record.get("id") is not None
        }
        hidden = {
            (item["type"], item["id"])
            for item in source["deletedRecords"]
        }
        rows = []
        for record in source["legacyRecords"]:
            key = (str(record.get("type", "")), str(record.get("id", "")))
            if key in hidden or key in local_by_key:
                continue
            rows.append(record)
        for record in source["localRecords"]:
            key = (str(record.get("type", "")), str(record.get("id", "")))
            if key not in hidden:
                rows.append(record)
        return rows

    @staticmethod
    def _sort_records(records: list[dict[str, Any]], *, ascending: bool = False) -> list[dict[str, Any]]:
        # Stable ordering mirrors the legacy date/createdAt sort while retaining
        # imported rows that have no creation timestamp.
        return sorted(
            records,
            key=lambda item: (str(item.get("date", "")), _nonnegative_counter(item.get("createdAt", 0))),
            reverse=not ascending,
        )

    def records(self) -> list[dict[str, Any]]:
        """Return all visible legacy types plus local additions, in source order."""
        with self._lock:
            return _json_copy(self._visible_records(), "记账记录")

    def money_records(self, *, ascending: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            rows = [item for item in self._visible_records() if item.get("type") == "money"]
            return _json_copy(self._sort_records(rows, ascending=ascending), "记账记录")

    def settings(self) -> dict[str, Any]:
        """Return full legacy settings, including fields owned by other modules."""
        with self._lock:
            has_configured_budget = (
                "budget" in self._state["legacySettings"]
                or "budget" in self._state["settingsOverrides"]
            )
            result = {**deepcopy(self._state["legacySettings"]),
                      **deepcopy(self._state["settingsOverrides"])}
            result.setdefault("budget", 5000)
            result["budgetIsDefault"] = not has_configured_budget
            result.setdefault("moneyFilter", "all")
            result.setdefault("lastExportAt", None)
            result["recordsSinceExport"], result["moneySinceExport"] = self._export_counts(self._state)
            return _json_copy(result, "记账设置")

    def state(self) -> dict[str, Any]:
        return {"records": self.records(), "settings": self.settings()}

    @staticmethod
    def _export_counts(state: dict[str, Any]) -> tuple[int, int]:
        added = state["addedSinceExport"]
        if state["exportBaselineReset"]:
            return added["records"], added["money"]
        settings = state["legacySettings"]
        return (
            _nonnegative_counter(settings.get("recordsSinceExport", 0)) + added["records"],
            _nonnegative_counter(settings.get("moneySinceExport", 0)) + added["money"],
        )

    def deleted_record_keys(self) -> list[dict[str, str]]:
        """Return module tombstones as ``[{type, id}, ...]`` for cross-module joins."""
        with self._lock:
            return _json_copy(self._state["deletedRecords"], "记账删除标记")

    def category_options(self) -> list[str]:
        """Return the exact expense/income category options shown by the old UI."""
        return list(ALL_CATEGORIES)

    def filtered_records(
        self, category: str | None = None, *, limit: int | None = 60
    ) -> list[dict[str, Any]]:
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 0):
            raise FinanceRepositoryError("流水显示数量无效。")
        if category is None:
            category = self.settings().get("moneyFilter", "all")
        if not isinstance(category, str):
            raise FinanceRepositoryError("分类筛选必须是文本。")
        rows = self.money_records()
        if category != "all":
            rows = [item for item in rows if _record_data(item).get("category") == category]
        return rows if limit is None else rows[:limit]

    def set_filter(self, category: str) -> str:
        if not isinstance(category, str) or not category.strip():
            raise FinanceRepositoryError("分类筛选不能为空。")
        with self._lock:
            state = deepcopy(self._state)
            state["settingsOverrides"]["moneyFilter"] = category
            self._mark_local(state, "moneyFilter")
            self._commit(state)
        return category

    def set_budget(self, budget: Any) -> int | float:
        value = _amount_decimal(budget)
        if value < 0:
            raise FinanceRepositoryError("月度预算不能小于 0。")
        normalized = _decimal_result(value)
        with self._lock:
            state = deepcopy(self._state)
            state["settingsOverrides"]["budget"] = normalized
            self._mark_local(state, "budget")
            self._commit(state)
        return normalized

    def add_record(
        self,
        flow: str,
        amount: Any,
        category: str,
        day: str,
        note: str = "",
        *,
        record_id: str | None = None,
        created_at: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(flow, str) or flow not in {"expense", "income"}:
            raise FinanceRepositoryError("收支类型必须是 expense 或 income。")
        value = _money_input(amount)
        allowed = EXPENSE_CATEGORIES if flow == "expense" else INCOME_CATEGORIES
        if not isinstance(category, str) or category not in allowed:
            raise FinanceRepositoryError("所选分类与收支类型不匹配。")
        valid_day = _date_value(day)
        if not isinstance(note, str):
            raise FinanceRepositoryError("备注必须是文本。")
        note = note.strip()
        if len(note) > 60:
            raise FinanceRepositoryError("备注最多 60 个字符。")
        new_id = record_id or str(uuid4())
        if not isinstance(new_id, str) or not new_id.strip():
            raise FinanceRepositoryError("记录 id 必须是非空文本。")
        if created_at is not None and (
            isinstance(created_at, bool) or not isinstance(created_at, int) or created_at < 0
        ):
            raise FinanceRepositoryError("记录创建时间无效。")
        record = {
            "id": new_id,
            "type": "money",
            "date": valid_day,
            "createdAt": created_at if created_at is not None else int(datetime.now().astimezone().timestamp() * 1000),
            "sample": False,
            "data": {"flow": flow, "amount": value, "category": category, "note": note},
        }
        with self._lock:
            if any(item.get("id") == new_id for item in self._visible_records()):
                raise FinanceRepositoryError("记录 id 已存在。")
            if ("money", new_id) in {
                (item["type"], item["id"]) for item in self._state["deletedRecords"]
            }:
                raise FinanceRepositoryError("记录 id 已被本机删除标记占用。")
            state = deepcopy(self._state)
            state["localRecords"].append(record)
            state["addedSinceExport"]["records"] += 1
            state["addedSinceExport"]["money"] += 1
            self._mark_local(state, "records")
            self._mark_local(state, "exportCounters")
            self._commit(state)
        return deepcopy(record)

    def note_record_created(self, record_type: str, count: int = 1) -> None:
        """Count another module's new record toward legacy backup reminders."""
        if record_type not in {"money", "fitness", "planner", "home"}:
            raise FinanceRepositoryError("记录类型无法识别。")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise FinanceRepositoryError("新增记录数量必须是正整数。")
        with self._lock:
            state = deepcopy(self._state)
            state["addedSinceExport"]["records"] += count
            if record_type == "money":
                state["addedSinceExport"]["money"] += count
            self._mark_local(state, "exportCounters")
            self._commit(state)

    def delete_record(self, record_id: str) -> bool:
        if not isinstance(record_id, str) or not record_id:
            raise FinanceRepositoryError("记录 id 无效。")
        with self._lock:
            target = next(
                (item for item in self._visible_records()
                 if item.get("type") == "money" and item.get("id") == record_id),
                None,
            )
            if target is None:
                return False
            state = deepcopy(self._state)
            local_index = next(
                (index for index, item in enumerate(state["localRecords"])
                 if item.get("type") == "money" and item.get("id") == record_id),
                None,
            )
            if local_index is not None:
                state["localRecords"].pop(local_index)
            else:
                key = {"type": "money", "id": record_id}
                if key not in state["deletedRecords"]:
                    state["deletedRecords"].append(key)
            self._mark_local(state, "records")
            self._commit(state)
            return True

    def summary(self, today: str | date | None = None) -> dict[str, Any]:
        current_day = _today_string(today)
        month = current_day[:7]
        month_day = date.fromisoformat(current_day)
        current_month = date(month_day.year, month_day.month, 1)
        previous_month = date(
            current_month.year - (1 if current_month.month == 1 else 0),
            12 if current_month.month == 1 else current_month.month - 1,
            1,
        )
        previous_key = previous_month.strftime("%Y-%m")
        rows = self.money_records()
        current_rows = [item for item in rows if str(item.get("date", "")).startswith(month)]
        previous_rows = [item for item in rows if str(item.get("date", "")).startswith(previous_key)]
        income = sum(
            (_record_amount(item) for item in current_rows
             if _record_data(item).get("flow") == "income"),
            Decimal(0),
        )
        expense = sum(
            (_record_amount(item) for item in current_rows
             if _record_data(item).get("flow") == "expense"),
            Decimal(0),
        )
        previous_expense = sum(
            (_record_amount(item) for item in previous_rows
             if _record_data(item).get("flow") == "expense"),
            Decimal(0),
        )
        settings = self.settings()
        try:
            budget = _amount_decimal(settings.get("budget", 5000))
        except FinanceRepositoryError:
            budget = Decimal(5000)
        ratio = (expense / budget * Decimal(100)) if budget > 0 else Decimal(0)
        used_percent = int((ratio + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))
        records_since, money_since = self._export_counts(self._state)
        difference = expense - previous_expense
        percentage = (
            int((abs(difference / previous_expense * Decimal(100)) + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR"))
            if previous_expense != 0 else None
        )
        return {
            "month": month,
            "income": _decimal_result(income),
            "expense": _decimal_result(expense),
            "balance": _decimal_result(income - expense),
            "previousMonth": previous_key,
            "previousExpense": _decimal_result(previous_expense),
            "expenseDifference": _decimal_result(difference),
            "expenseDifferencePercent": percentage,
            "budget": _decimal_result(budget),
            "budgetRemaining": _decimal_result(budget - expense),
            "budgetUsedPercent": used_percent,
            "budgetBarPercent": min(100, used_percent),
            "todayRecordCount": sum(item.get("date") == current_day for item in rows),
            "recordsSinceExport": records_since,
            "moneySinceExport": money_since,
            "backupReminderDue": money_since >= 20,
            "overBudget": expense > budget,
            "alertReason": (
                "over_budget" if expense > budget
                else "no_today_record" if not any(item.get("date") == current_day for item in rows)
                else "backup_reminder" if money_since >= 20
                else None
            ),
        }

    def expense_categories(self, today: str | date | None = None) -> list[dict[str, Any]]:
        current = self.summary(today)
        category_totals: dict[str, Decimal] = {}
        for record in self.money_records():
            if _record_data(record).get("flow") != "expense":
                continue
            if not str(record.get("date", "")).startswith(current["month"]):
                continue
            category = _record_data(record).get("category") or "其他"
            if not isinstance(category, str):
                category = "其他"
            category_totals[category] = category_totals.get(category, Decimal(0)) + _record_amount(record)
        total = sum(category_totals.values(), Decimal(0))
        return [
            {"category": name, "amount": _decimal_result(amount),
             "share": float(amount / total) if total > 0 else 0.0}
            for name, amount in sorted(category_totals.items(), key=lambda entry: entry[1], reverse=True)
        ]

    def consumption_summary(self, today: str | date | None = None) -> dict[str, Any]:
        stats = self.summary(today)
        current_day = _today_string(today)
        elapsed_days = max(1, date.fromisoformat(current_day).day)
        rows = [
            item for item in self.money_records()
            if str(item.get("date", "")).startswith(stats["month"])
            and _record_data(item).get("flow") == "expense"
        ]
        category_totals: dict[str, Decimal] = {}
        for record in rows:
            category = _record_data(record).get("category") or "其他"
            category = category if isinstance(category, str) else "其他"
            category_totals[category] = category_totals.get(category, Decimal(0)) + _record_amount(record)
        top = max(category_totals.items(), key=lambda item: item[1], default=None)
        largest = max(rows, key=_record_amount, default=None)
        return {
            "month": stats["month"],
            "elapsedDays": elapsed_days,
            "dailyAverage": _decimal_result(Decimal(str(stats["expense"])) / Decimal(elapsed_days)),
            "topCategory": {"category": top[0], "amount": _decimal_result(top[1])} if top else None,
            "largestExpense": deepcopy(largest) if largest else None,
        }

    def excel_export_data(self, language: str = "zh") -> dict[str, Any]:
        if language not in {"zh", "en"}:
            raise FinanceRepositoryError("导出语言必须是 zh 或 en。")
        headers = (
            ["日期", "类型", "分类", "金额", "备注"]
            if language == "zh"
            else ["Date", "Type", "Category", "Amount", "Note"]
        )
        rows = []
        for record in self.money_records():
            data = _record_data(record)
            flow = data.get("flow")
            rows.append([
                record.get("date", ""),
                ("收入" if flow == "income" else "支出") if language == "zh"
                else ("Income" if flow == "income" else "Expense"),
                data.get("category", ""),
                data.get("amount", ""),
                data.get("note", "") or "",
            ])
        return {"headers": headers, "rows": rows}

    def mark_backup_exported(self, when: datetime | None = None) -> dict[str, Any]:
        timestamp = when or datetime.now().astimezone()
        if not isinstance(timestamp, datetime):
            raise FinanceRepositoryError("备份时间无效。")
        if timestamp.tzinfo is None:
            timestamp = timestamp.astimezone()
        with self._lock:
            state = deepcopy(self._state)
            state["exportBaselineReset"] = True
            state["addedSinceExport"] = {"records": 0, "money": 0}
            state["settingsOverrides"].update({
                "recordsSinceExport": 0,
                "moneySinceExport": 0,
                "lastExportAt": timestamp.isoformat(),
            })
            self._mark_local(state, "exportCounters")
            self._mark_local(state, "lastExportAt")
            self._commit(state)
            return self.settings()

    def _mark_local(self, state: dict[str, Any], field: str) -> None:
        if field not in state["localFields"]:
            state["localFields"].append(field)

    def adopt_imported_data(self, legacy_store: Any) -> bool:
        """Replace the base view after import while preserving native overlays."""
        records, settings, has_main = _legacy_source(legacy_store)
        if not has_main:
            return False
        with self._lock:
            state = deepcopy(self._state)
            state["legacyRecords"] = records
            state["legacySettings"] = settings
            self._commit(state)
        return True
