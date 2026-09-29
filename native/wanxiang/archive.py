"""Read-only archive projection over the application's effective records.

The archive never stores or edits records.  Callers pass the cross-module
``records`` stream assembled by the application; this repository persists only
the user's archive filter in its own SQLite row.  The separate ``mediaItems``
collection is deliberately not accepted as an input.

Qt controller contract (implemented by the application shell): expose a
read-only ``state`` property returning ``repository.state(records_provider())``
and a ``setFilter(str)`` slot that calls ``repository.set_filter(value)`` then
emits ``stateChanged``.  The ``records_provider`` must return the effective,
deduplicated finance/fitness/planner/home stream after module overlays and
tombstones have been applied.  The QML page does not call any record mutation
method because none exists on this repository.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any

from .database import load_imported_data
from .json_utils import copy_json
from .migration import MigrationPackage


LEGACY_STATE_KEY = "richangji-state-v1"
_TABLE = "archive_module_state"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ARCHIVE_TYPES: tuple[str, ...] = ("money", "fitness", "planner", "home")
ARCHIVE_FILTERS: tuple[str, ...] = ("all", *ARCHIVE_TYPES)
TYPE_LABELS: dict[str, str] = {
    "money": "财务",
    "fitness": "健康",
    "planner": "日程",
    "home": "待买",
}


class ArchiveRepositoryError(ValueError):
    """Readable validation or persistence error for archive preferences."""


def _json_copy(value: Any, label: str) -> Any:
    return copy_json(value, label, ArchiveRepositoryError)


def _date_key(value: Any, label: str = "日期") -> str:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise ArchiveRepositoryError(f"{label} 必须使用 YYYY-MM-DD 日期。")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ArchiveRepositoryError(f"{label} 必须是有效日期。") from exc
    if parsed.isoformat() != value:
        raise ArchiveRepositoryError(f"{label} 必须是有效日期。")
    return value


def _today_key(value: str | date | None) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        value = value.isoformat()
    return _date_key(value or date.today().isoformat(), "今天")


def _source_settings(source: Any) -> tuple[dict[str, Any], bool]:
    """Read only the legacy settings envelope; never retain its records."""
    main: Any = None
    if isinstance(source, MigrationPackage):
        main = source.parsed_values.get(LEGACY_STATE_KEY)
    elif isinstance(source, dict):
        for key in ("parsed_values", "documents"):
            container = source.get(key)
            if isinstance(container, dict) and LEGACY_STATE_KEY in container:
                main = container[LEGACY_STATE_KEY]
                break
        if main is None:
            for key in ("raw_values", "keys"):
                container = source.get(key)
                if isinstance(container, dict) and LEGACY_STATE_KEY in container:
                    raw = container[LEGACY_STATE_KEY]
                    if raw is None:
                        break
                    if not isinstance(raw, str):
                        raise ArchiveRepositoryError("旧版主状态原文必须是 JSON 字符串。")
                    try:
                        main = json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise ArchiveRepositoryError("旧版主状态原文不是有效 JSON。") from exc
                    break
        if main is None and ("records" in source or "settings" in source):
            main = source
    if main is None:
        return {}, False
    if not isinstance(main, dict):
        raise ArchiveRepositoryError("旧版主状态必须是对象。")
    settings = main.get("settings", {})
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise ArchiveRepositoryError("旧版 settings 必须是对象。")
    return _json_copy(settings, "旧版设置"), True


def _initial_state(settings: dict[str, Any]) -> dict[str, Any]:
    old_filter = settings.get("archiveFilter", "all")
    if not isinstance(old_filter, str) or old_filter not in ARCHIVE_FILTERS:
        old_filter = "all"
    return {"legacyFilter": old_filter, "filterOverride": None}


def _normalize_state(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ArchiveRepositoryError("本机档案设置结构无效。")
    legacy_filter = state.get("legacyFilter", "all")
    override = state.get("filterOverride")
    if not isinstance(legacy_filter, str) or legacy_filter not in ARCHIVE_FILTERS:
        legacy_filter = "all"
    if override is not None and (not isinstance(override, str) or override not in ARCHIVE_FILTERS):
        raise ArchiveRepositoryError("本机档案筛选设置无效。")
    return {"legacyFilter": legacy_filter, "filterOverride": override}


def _read_runtime(path: Path) -> dict[str, Any] | None:
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(str(path), timeout=30)
        row = connection.execute(
            f"SELECT state_json FROM {_TABLE} WHERE singleton=1"
        ).fetchone()
        if row is None:
            return None
        try:
            return _normalize_state(json.loads(row[0]))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ArchiveRepositoryError("本机档案筛选数据无法解析。") from exc
    except ArchiveRepositoryError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise ArchiveRepositoryError(f"无法读取本机档案设置：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()


class ArchiveRepository:
    """Persist a filter and derive archive views without owning any records."""

    def __init__(self, database_path: str | Path, legacy_store: Any = None) -> None:
        self.database_path = Path(database_path).expanduser()
        self._lock = RLock()
        source = legacy_store
        if source is None:
            imported = load_imported_data(self.database_path)
            if imported.get("status") == "unavailable":
                raise ArchiveRepositoryError(imported.get("error") or "无法读取旧版导入数据。")
            source = imported
        settings, _ = _source_settings(source)
        self._materialize_if_missing(_initial_state(settings))
        runtime = _read_runtime(self.database_path)
        if runtime is None:
            raise ArchiveRepositoryError("无法初始化本机档案设置。")
        self._state = runtime

    def _materialize_if_missing(self, initial: dict[str, Any]) -> None:
        path = self.database_path.resolve()
        connection: sqlite3.Connection | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1), state_json TEXT NOT NULL)"
            )
            present = connection.execute(
                f"SELECT 1 FROM {_TABLE} WHERE singleton=1"
            ).fetchone()
            if present is None:
                encoded = json.dumps(initial, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
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
            if isinstance(exc, ArchiveRepositoryError):
                raise
            raise ArchiveRepositoryError(f"初始化本机档案设置失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _commit(self, state: dict[str, Any]) -> None:
        normalized = _normalize_state(_json_copy(state, "档案设置"))
        encoded = json.dumps(normalized, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
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
            if isinstance(exc, ArchiveRepositoryError):
                raise
            raise ArchiveRepositoryError(f"保存本机档案设置失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        self._state = normalized

    @staticmethod
    def _record_created_at(record: dict[str, Any]) -> int | float:
        value = record.get("createdAt", 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0
        return value if value == value and abs(value) != float("inf") else 0

    @classmethod
    def _effective_records(cls, records: Any) -> list[dict[str, Any]]:
        if records is None:
            records = []
        if not isinstance(records, (list, tuple)):
            raise ArchiveRepositoryError("档案输入必须是 records 对象数组。")
        result: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                raise ArchiveRepositoryError("档案 records 中的每项都必须是对象。")
            if record.get("type") not in ARCHIVE_TYPES:
                continue
            result.append(_json_copy(record, "档案记录"))

        def sort_date(record: dict[str, Any]) -> tuple[int, str]:
            value = record.get("date")
            try:
                return (1, _date_key(value))
            except ArchiveRepositoryError:
                return (0, "")

        result.sort(
            key=lambda item: (
                sort_date(item),
                cls._record_created_at(item),
            ),
            reverse=True,
        )
        return result

    @classmethod
    def filter_records(cls, records: Any, filter_value: str = "all") -> list[dict[str, Any]]:
        if not isinstance(filter_value, str) or filter_value not in ARCHIVE_FILTERS:
            raise ArchiveRepositoryError("档案筛选必须是 all、money、fitness、planner 或 home。")
        rows = cls._effective_records(records)
        if filter_value != "all":
            rows = [item for item in rows if item.get("type") == filter_value]
        return rows

    @classmethod
    def group_by_date(cls, records: Any) -> list[dict[str, Any]]:
        """Group newest-first rows, retaining malformed historical dates last."""
        groups: dict[str, list[dict[str, Any]]] = {}
        for record in cls._effective_records(records):
            value = record.get("date")
            try:
                key = _date_key(value)
            except ArchiveRepositoryError:
                key = "未标日期"
            groups.setdefault(key, []).append(record)
        return [
            {"date": key, "count": len(items), "records": items}
            for key, items in groups.items()
        ]

    @classmethod
    def monthly_summary(
        cls,
        records: Any,
        *,
        today: str | date | None = None,
    ) -> dict[str, Any]:
        today_value = _today_key(today)
        today_date = date.fromisoformat(today_value)
        month_key = today_value[:7]
        month_rows: list[dict[str, Any]] = []
        for record in cls._effective_records(records):
            value = record.get("date")
            if not isinstance(value, str) or not value.startswith(month_key):
                continue
            try:
                _date_key(value)
            except ArchiveRepositoryError:
                continue
            month_rows.append(record)

        type_counts: dict[str, int] = {}
        first_seen: dict[str, int] = {}
        for index, record in enumerate(month_rows):
            kind = str(record["type"])
            type_counts[kind] = type_counts.get(kind, 0) + 1
            first_seen.setdefault(kind, index)
        favorite_type = min(
            type_counts,
            key=lambda kind: (-type_counts[kind], first_seen[kind]),
        ) if type_counts else None

        recent_days: list[dict[str, Any]] = []
        for offset in range(6, -1, -1):
            day_key = (today_date - timedelta(days=offset)).isoformat()
            count = sum(1 for record in month_rows if record.get("date") == day_key)
            recent_days.append({"date": day_key, "count": count})

        return {
            "today": today_value,
            "month": month_key,
            "recordCount": len(month_rows),
            "dateCount": len({item["date"] for item in month_rows}),
            "favoriteType": favorite_type,
            "favoriteLabel": TYPE_LABELS.get(favorite_type or "", ""),
            "favoriteCount": type_counts.get(favorite_type or "", 0),
            "typeCounts": type_counts,
            "recentSevenDayCount": sum(item["count"] for item in recent_days),
            "maxRecentDayCount": max((item["count"] for item in recent_days), default=0),
            "recentDays": recent_days,
        }

    def current_filter(self) -> str:
        with self._lock:
            value = self._state.get("filterOverride") or self._state.get("legacyFilter", "all")
            return value if value in ARCHIVE_FILTERS else "all"

    def set_filter(self, value: str) -> str:
        if not isinstance(value, str) or value not in ARCHIVE_FILTERS:
            raise ArchiveRepositoryError("档案筛选必须是 all、money、fitness、planner 或 home。")
        with self._lock:
            state = deepcopy(self._state)
            state["filterOverride"] = value
            self._commit(state)
        return value

    def adopt_imported_data(self, snapshot: Any) -> bool:
        """Adopt only the old filter; never copy records into the archive DB."""
        settings, has_main = _source_settings(snapshot)
        if not has_main:
            return False
        value = settings.get("archiveFilter", "all")
        if not isinstance(value, str) or value not in ARCHIVE_FILTERS:
            value = "all"
        with self._lock:
            state = deepcopy(self._state)
            state["legacyFilter"] = value
            self._commit(state)
        return True

    def state(
        self,
        records: Any,
        *,
        today: str | date | None = None,
    ) -> dict[str, Any]:
        """Return QML-ready read-only data derived from effective records."""
        with self._lock:
            filter_value = self.current_filter()
        filtered = self.filter_records(records, filter_value)
        return {
            "filter": filter_value,
            "recordCount": len(filtered),
            "groups": self.group_by_date(filtered),
            "summary": self.monthly_summary(filtered, today=today),
        }
