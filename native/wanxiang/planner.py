"""SQLite-backed planner state with an immutable legacy-record seed."""

from __future__ import annotations

import csv
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock
import tempfile
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4
from tzlocal import get_localzone

from .calendar_exchange import (
    CalendarExchangeError,
    calendar_occurrences_for_day,
    normalize_calendar_events,
    parse_ics,
    parse_ical_vtodos,
    task_events_to_ics,
    write_ics_file,
)
from .database import load_imported_data
from .json_utils import strict_copy_json, strict_json_loads
from .migration import MigrationPackage
from .planner_sync import is_syncable_task, normalize_snapshot, snapshot_from_state


LEGACY_STATE_KEY = "richangji-state-v1"
_TABLE = "planner_module_state"
_FILTERS = {"all", "today", "scheduled", "done"}
_VIEW_MODES = {"list", "kanban", "matrix"}
_TASK_STATUSES = {"todo", "doing", "done"}
_BOARD_STATUSES = ("todo", "doing", "done")
_MAX_BOARD_ORDER_IDS = 100_000
_CUSTOM_BOARD_PREFIX = "custom-board:"
_LISTS = {"生活", "工作", "家庭", "个人"}
_PRIORITIES = {"normal", "high", "low"}
_REPEATS = {"none", "daily", "weekdays", "weekly", "monthly"}
_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_CALDAV_SOURCE_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")
_MAX_TAGS = 12
_MAX_TAG_LENGTH = 30


class PlannerRepositoryError(ValueError):
    """Readable validation or persistence error for planner operations."""


def _json_copy(value: Any, label: str) -> Any:
    return strict_copy_json(value, label, PlannerRepositoryError)


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise PlannerRepositoryError("日程状态无法编码为有效 JSON。") from exc


def _strict_json_loads(raw: str, label: str) -> Any:
    return strict_json_loads(raw, label, PlannerRepositoryError)


def _valid_date(value: Any, label: str = "日期") -> str:
    if not isinstance(value, str):
        raise PlannerRepositoryError(f"{label} 必须是 YYYY-MM-DD 格式。")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise PlannerRepositoryError(f"{label} 必须是有效的 YYYY-MM-DD 日期。") from exc
    if parsed.isoformat() != value:
        raise PlannerRepositoryError(f"{label} 必须是 YYYY-MM-DD 格式。")
    return value


def _normalize_project(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PlannerRepositoryError("项目名称必须是文本。")
    project = value.strip()
    if len(project) > 60:
        raise PlannerRepositoryError("项目名称最多 60 个字符。")
    if any(ord(char) < 32 for char in project):
        raise PlannerRepositoryError("项目名称不能包含控制字符。")
    return project


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PlannerRepositoryError("标签必须是文本数组。")
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in value:
        if not isinstance(raw_tag, str):
            raise PlannerRepositoryError("每个标签都必须是文本。")
        tag = raw_tag.strip()
        if not tag:
            continue
        if len(tag) > _MAX_TAG_LENGTH:
            raise PlannerRepositoryError(f"每个标签最多 {_MAX_TAG_LENGTH} 个字符。")
        if any(ord(char) < 32 for char in tag):
            raise PlannerRepositoryError("标签不能包含控制字符。")
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
        if len(tags) > _MAX_TAGS:
            raise PlannerRepositoryError(f"每项待办最多添加 {_MAX_TAGS} 个标签。")
    return tags


def _effective_estimate_minutes(value: Any) -> int:
    """Normalize legacy task estimates to the five-minute planner grid."""
    if isinstance(value, bool) or not isinstance(value, int) or not 5 <= value <= 480:
        return 30
    return min(480, ((value + 4) // 5) * 5)


def _normalize_custom_boards(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 12:
        raise PlannerRepositoryError("最多只能保存 12 个自定义看板。")
    boards: list[dict[str, Any]] = []
    board_ids: set[str] = set()
    for raw_board in value:
        if not isinstance(raw_board, dict):
            raise PlannerRepositoryError("自定义看板结构无效。")
        board_id = raw_board.get("id")
        name = raw_board.get("name")
        columns = raw_board.get("columns")
        if not isinstance(board_id, str) or not board_id.strip() or len(board_id) > 80 or board_id in board_ids:
            raise PlannerRepositoryError("自定义看板 id 缺失或重复。")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40:
            raise PlannerRepositoryError("看板名称须为 1 至 40 个字符。")
        if not isinstance(columns, list) or not 2 <= len(columns) <= 8:
            raise PlannerRepositoryError("自定义看板须有 2 至 8 个列。")
        normalized_columns: list[dict[str, str]] = []
        column_ids: set[str] = set()
        column_names: set[str] = set()
        for raw_column in columns:
            if not isinstance(raw_column, dict):
                raise PlannerRepositoryError("看板列结构无效。")
            column_id = raw_column.get("id")
            title = raw_column.get("title")
            status = raw_column.get("status")
            tag_values = _normalize_tags([raw_column.get("tag", "")])
            tag = tag_values[0] if tag_values else ""
            if not isinstance(column_id, str) or not column_id.strip() or len(column_id) > 80 or column_id in column_ids:
                raise PlannerRepositoryError("看板列 id 缺失或重复。")
            if not isinstance(title, str) or not title.strip() or len(title.strip()) > 32:
                raise PlannerRepositoryError("看板列名称须为 1 至 32 个字符。")
            if title.strip().casefold() in column_names:
                raise PlannerRepositoryError("同一看板中的列名称不能重复。")
            if not isinstance(status, str) or status not in _TASK_STATUSES:
                raise PlannerRepositoryError("看板列须对应有效的任务状态。")
            column_ids.add(column_id)
            column_names.add(title.strip().casefold())
            normalized_columns.append({
                "id": column_id,
                "title": title.strip(),
                "status": status,
                "tag": tag,
            })
        board_ids.add(board_id)
        boards.append({"id": board_id, "name": name.strip(), "columns": normalized_columns})
    return boards


def _normalize_custom_board_orders(value: Any) -> dict[str, dict[str, list[str]]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, list[str]]] = {}
    for board_id, raw_columns in list(value.items())[:12]:
        if not isinstance(board_id, str) or not board_id.strip() or len(board_id) > 80:
            continue
        if not isinstance(raw_columns, dict):
            continue
        columns: dict[str, list[str]] = {}
        for column_id, raw_ids in list(raw_columns.items())[:8]:
            if not isinstance(column_id, str) or not column_id.strip() or len(column_id) > 80:
                continue
            if not isinstance(raw_ids, list):
                continue
            task_ids: list[str] = []
            seen: set[str] = set()
            for task_id in raw_ids[:10000]:
                if not isinstance(task_id, str) or not task_id or len(task_id) > 160 or task_id in seen:
                    continue
                seen.add(task_id)
                task_ids.append(task_id)
            columns[column_id] = task_ids
        result[board_id] = columns
    return result


def _normalize_board_order_ids(value: Any, *, strict: bool = False) -> list[str]:
    if not isinstance(value, list):
        if strict:
            raise PlannerRepositoryError("标准看板顺序必须是 id 数组。")
        return []
    if len(value) > _MAX_BOARD_ORDER_IDS:
        raise PlannerRepositoryError("标准看板排序项目过多。")
    result: list[str] = []
    seen: set[str] = set()
    for task_id in value:
        if (
            not isinstance(task_id, str)
            or not task_id.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in task_id)
        ):
            if strict:
                raise PlannerRepositoryError("标准看板排序中的任务 id 无效。")
            continue
        if task_id not in seen:
            result.append(task_id)
            seen.add(task_id)
    return result


def _normalize_board_orders(value: Any, *, legacy: bool = False) -> dict[str, list[str]]:
    result = {status: [] for status in _BOARD_STATUSES}
    if not isinstance(value, dict):
        return result
    for status in _BOARD_STATUSES:
        source_key = "inprogress" if legacy and status == "doing" else status
        raw_ids = value.get(source_key, [])
        # Match the legacy normalizer's 5,000 id cap for imported preferences.
        if legacy and isinstance(raw_ids, list):
            raw_ids = raw_ids[:5000]
        result[status] = _normalize_board_order_ids(raw_ids)
    return result


def _board_task_status(record: dict[str, Any]) -> str:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    if data.get("done"):
        return "done"
    status = data.get("status")
    if isinstance(status, str) and status in {"doing", "inprogress"}:
        return "doing"
    return "todo"


def _board_fallback_order(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a stable task-list order for IDs absent from a saved lane order."""
    by_id = {str(record.get("id", "")): record for record in records}

    def root_for(record: dict[str, Any]) -> dict[str, Any]:
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        parent_id = data.get("parentTaskId")
        return by_id.get(str(parent_id), record) if parent_id else record

    def created_value(record: dict[str, Any]) -> float:
        value = record.get("createdAt", 0) or 0
        if isinstance(value, bool):
            return float(int(value))
        try:
            result = float(value)
            return result if math.isfinite(result) else 0.0
        except (TypeError, ValueError):
            return 0.0

    def order_key(record: dict[str, Any]) -> tuple[Any, ...]:
        root = root_for(record)
        root_data = root.get("data") if isinstance(root.get("data"), dict) else {}
        root_id = str(root.get("id", ""))
        record_id = str(record.get("id", ""))
        return (
            str(record.get("date", "")),
            str(root_data.get("time", "") or ""),
            created_value(root),
            root_id,
            0 if record_id == root_id else 1,
            created_value(record),
        )

    return sorted(records, key=order_key)


def _normalize_calendar_subscriptions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 24:
        raise PlannerRepositoryError("最多只能保存 24 个日历订阅。")
    subscriptions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise PlannerRepositoryError("日历订阅结构无效。")
        subscription_id = raw.get("id")
        name = raw.get("name")
        host = raw.get("host", "")
        protected_url = raw.get("urlProtected")
        etag = raw.get("etag", "")
        last_modified = raw.get("lastModified", "")
        last_attempt = raw.get("lastAttemptAt", "")
        last_success = raw.get("lastSuccessAt", "")
        last_error = raw.get("lastError", "")
        if (
            not isinstance(subscription_id, str) or not subscription_id.strip()
            or len(subscription_id) > 80 or subscription_id in seen_ids
        ):
            raise PlannerRepositoryError("日历订阅 id 缺失或重复。")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise PlannerRepositoryError("订阅名称须为 1 至 80 个字符。")
        if not isinstance(host, str) or not host or len(host) > 255:
            raise PlannerRepositoryError("订阅服务器名称无效。")
        if not isinstance(protected_url, str) or not protected_url or len(protected_url) > 16_384:
            raise PlannerRepositoryError("受保护的订阅地址无效。")
        if (
            not isinstance(etag, str) or len(etag) > 1_024
            or not isinstance(last_modified, str) or len(last_modified) > 128
            or not isinstance(last_error, str) or len(last_error) > 300
            or any(ord(char) < 32 or ord(char) == 127 for char in etag + last_modified)
            or any(ord(char) < 32 or ord(char) == 127 for char in last_error)
        ):
            raise PlannerRepositoryError("日历订阅状态字段无效。")
        for timestamp in (last_attempt, last_success):
            if not isinstance(timestamp, str) or (timestamp and len(timestamp) > 64):
                raise PlannerRepositoryError("日历订阅时间字段无效。")
            if timestamp:
                try:
                    datetime.fromisoformat(timestamp)
                except ValueError as exc:
                    raise PlannerRepositoryError("日历订阅时间字段无效。") from exc
        normalized = {
            **raw,
            "id": subscription_id,
            "name": name.strip(),
            "host": host,
            "urlProtected": protected_url,
            "etag": etag,
            "lastModified": last_modified,
            "lastAttemptAt": last_attempt,
            "lastSuccessAt": last_success,
            "lastError": last_error,
        }
        subscriptions.append(normalized)
        seen_ids.add(subscription_id)
    return subscriptions


def _normalize_caldav_accounts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 12:
        raise PlannerRepositoryError("最多只能保存 12 个 CalDAV 账户。")
    accounts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise PlannerRepositoryError("CalDAV 账户结构无效。")
        account_id = raw.get("id")
        name = raw.get("name")
        host = raw.get("host")
        protected_url = raw.get("urlProtected")
        protected_credentials = raw.get("credentialsProtected")
        last_checked = raw.get("lastCheckedAt", "")
        last_success = raw.get("lastSuccessAt", "")
        last_error = raw.get("lastError", "")
        last_sync = raw.get("lastSyncAt", "")
        last_sync_success = raw.get("lastSyncSuccessAt", "")
        last_sync_error = raw.get("lastSyncError", "")
        sync_token = raw.get("syncToken", "")
        sync_collection_unsupported = raw.get("syncCollectionUnsupported", False)
        source_key = raw.get("sourceKey", "")
        calendars = raw.get("calendars", [])
        if (
            not isinstance(account_id, str) or not account_id.strip()
            or len(account_id) > 80 or account_id in seen_ids
        ):
            raise PlannerRepositoryError("CalDAV 账户 id 缺失或重复。")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise PlannerRepositoryError("CalDAV 账户名称须为 1 至 80 个字符。")
        if not isinstance(host, str) or not host or len(host) > 255:
            raise PlannerRepositoryError("CalDAV 服务器名称无效。")
        if not isinstance(protected_url, str) or not protected_url or len(protected_url) > 16_384:
            raise PlannerRepositoryError("受保护的 CalDAV 地址无效。")
        if not isinstance(protected_credentials, str) or not protected_credentials or len(protected_credentials) > 16_384:
            raise PlannerRepositoryError("受保护的 CalDAV 登录信息无效。")
        if (
            not isinstance(last_error, str) or len(last_error) > 300
            or any(ord(char) < 32 or ord(char) == 127 for char in last_error)
        ):
            raise PlannerRepositoryError("CalDAV 连接状态无效。")
        for timestamp in (last_checked, last_success):
            if not isinstance(timestamp, str) or (timestamp and len(timestamp) > 64):
                raise PlannerRepositoryError("CalDAV 检查时间无效。")
            if timestamp:
                try:
                    datetime.fromisoformat(timestamp)
                except ValueError as exc:
                    raise PlannerRepositoryError("CalDAV 检查时间无效。") from exc
        for timestamp in (last_sync, last_sync_success):
            if not isinstance(timestamp, str) or (timestamp and len(timestamp) > 64):
                raise PlannerRepositoryError("CalDAV 同步时间无效。")
            if timestamp:
                try:
                    datetime.fromisoformat(timestamp)
                except ValueError as exc:
                    raise PlannerRepositoryError("CalDAV 同步时间无效。") from exc
        if (
            not isinstance(last_sync_error, str) or len(last_sync_error) > 300
            or any(ord(char) < 32 or ord(char) == 127 for char in last_sync_error)
        ):
            raise PlannerRepositoryError("CalDAV 同步状态无效。")
        if (
            not isinstance(sync_token, str) or len(sync_token.encode("utf-8")) > 4_096
            or any(ord(char) < 32 or ord(char) == 127 for char in sync_token)
        ):
            raise PlannerRepositoryError("CalDAV 同步令牌无效。")
        if not isinstance(sync_collection_unsupported, bool):
            raise PlannerRepositoryError("CalDAV 增量同步能力标记无效。")
        if source_key != "" and (
            not isinstance(source_key, str)
            or not _CALDAV_SOURCE_KEY_PATTERN.fullmatch(source_key)
        ):
            raise PlannerRepositoryError("CalDAV 来源标识无效。")
        if not isinstance(calendars, list) or len(calendars) > 100:
            raise PlannerRepositoryError("CalDAV 日历列表无效。")
        normalized_calendars: list[dict[str, Any]] = []
        for calendar in calendars:
            if not isinstance(calendar, dict):
                raise PlannerRepositoryError("CalDAV 日历列表无效。")
            calendar_name = calendar.get("name", "")
            components = calendar.get("components", [])
            if not isinstance(calendar_name, str) or len(calendar_name) > 160:
                raise PlannerRepositoryError("CalDAV 日历名称无效。")
            if (
                not isinstance(components, list) or len(components) > 2
                or any(component not in {"VEVENT", "VTODO"} for component in components)
                or len(set(components)) != len(components)
            ):
                raise PlannerRepositoryError("CalDAV 日历组件列表无效。")
            normalized_calendars.append({
                "name": calendar_name,
                "components": list(components),
            })
        accounts.append({
            **raw,
            "id": account_id,
            "name": name.strip(),
            "host": host,
            "urlProtected": protected_url,
            "credentialsProtected": protected_credentials,
            "lastCheckedAt": last_checked,
            "lastSuccessAt": last_success,
            "lastError": last_error,
            "lastSyncAt": last_sync,
            "lastSyncSuccessAt": last_sync_success,
            "lastSyncError": last_sync_error,
            "syncToken": sync_token,
            "syncCollectionUnsupported": sync_collection_unsupported,
            "calendars": normalized_calendars,
        })
        seen_ids.add(account_id)
    return accounts


def _safe_csv_text(value: str) -> str:
    candidate = value.lstrip(" \t\r\n")
    if candidate.startswith(("=", "@")):
        return "'" + value
    if candidate.startswith(("+", "-")):
        try:
            float(candidate)
        except ValueError:
            return "'" + value
    return value


def _legacy_source(
    source: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], bool]:
    """Read planner records, settings and form draft from an imported snapshot."""
    main: Any = None
    if isinstance(source, MigrationPackage):
        main = source.parsed_values.get(LEGACY_STATE_KEY)
    elif isinstance(source, list):
        main = {"records": source}
    elif isinstance(source, dict):
        for container_name in ("parsed_values", "documents"):
            container = source.get(container_name)
            if isinstance(container, dict) and LEGACY_STATE_KEY in container:
                main = container[LEGACY_STATE_KEY]
                break
        if main is None and LEGACY_STATE_KEY in source:
            main = source[LEGACY_STATE_KEY]
        if main is None:
            for container_name in ("raw_values", "keys"):
                container = source.get(container_name)
                if isinstance(container, dict) and LEGACY_STATE_KEY in container:
                    raw = container[LEGACY_STATE_KEY]
                    if raw is not None:
                        if not isinstance(raw, str):
                            raise PlannerRepositoryError("旧版主状态原文必须是 JSON 字符串。")
                        main = _strict_json_loads(raw, "旧版主状态原文")
                        break
        if main is None:
            entities = source.get("entities")
            if isinstance(entities, dict) and "records" in entities:
                main = {"records": entities.get("records", []), "settings": {}, "drafts": {}}
        if main is None and ("records" in source or "settings" in source):
            main = source

    if main is None:
        return [], {}, {}, False
    if not isinstance(main, dict):
        raise PlannerRepositoryError("旧版主状态必须是对象。")
    records = main.get("records", [])
    settings = main.get("settings", {})
    drafts = main.get("drafts", {})
    if records is None:
        records = []
    if settings is None:
        settings = {}
    if drafts is None:
        drafts = {}
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise PlannerRepositoryError("旧版 records 必须是对象数组。")
    if not isinstance(settings, dict):
        raise PlannerRepositoryError("旧版 settings 必须是对象。")
    if not isinstance(drafts, dict):
        raise PlannerRepositoryError("旧版 drafts 必须是对象。")
    planner_records = [
        _json_copy(item, "旧版日程记录")
        for item in records
        if item.get("type") == "planner"
    ]
    seen_ids: set[str] = set()
    for item in planner_records:
        record_id = item.get("id")
        if not isinstance(record_id, str) or not record_id:
            raise PlannerRepositoryError("旧版日程记录缺少有效 id，无法安全关联操作。")
        if record_id in seen_ids:
            raise PlannerRepositoryError("旧版日程记录 id 重复，无法安全保存操作覆盖。")
        seen_ids.add(record_id)
        if not isinstance(item.get("data"), dict):
            raise PlannerRepositoryError("旧版日程记录 data 必须是对象。")
    draft = drafts.get("plannerForm", {})
    if draft is None:
        draft = {}
    if not isinstance(draft, dict):
        raise PlannerRepositoryError("旧版日程草稿必须是对象。")
    return (
        planner_records,
        _json_copy(settings, "旧版日程设置"),
        _json_copy(draft, "旧版日程草稿"),
        True,
    )


def _normalize_runtime(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise PlannerRepositoryError("本机日程状态结构无效。")
    legacy_records = state.get("legacyRecords", [])
    local_records = state.get("localRecords", [])
    overrides = state.get("recordOverrides", {})
    deleted = state.get("deletedRecords", [])
    legacy_settings = state.get("legacySettings", {})
    setting_overrides = state.get("settingsOverrides", {})
    draft = state.get("draft", {})
    draft_overridden = state.get("draftOverridden", False)
    active_tracking = state.get("activeTracking")
    calendar_events = state.get("calendarEvents", [])
    calendar_subscriptions = state.get("calendarSubscriptions", [])
    caldav_accounts = state.get("caldavAccounts", [])
    if not isinstance(legacy_records, list) or any(not isinstance(item, dict) for item in legacy_records):
        raise PlannerRepositoryError("本机旧日程必须是对象数组。")
    if not isinstance(local_records, list) or any(not isinstance(item, dict) for item in local_records):
        raise PlannerRepositoryError("本机新增日程必须是对象数组。")
    if not isinstance(overrides, dict) or any(not isinstance(key, str) or not isinstance(value, dict) for key, value in overrides.items()):
        raise PlannerRepositoryError("本机日程覆盖结构无效。")
    for changes in overrides.values():
        if "date" in changes:
            _valid_date(changes["date"], "本机日程覆盖日期")
    if not isinstance(deleted, list) or not isinstance(legacy_settings, dict) or not isinstance(setting_overrides, dict):
        raise PlannerRepositoryError("本机日程设置或删除标记结构无效。")
    if draft is None:
        draft = {}
    if not isinstance(draft, dict):
        raise PlannerRepositoryError("本机日程草稿结构无效。")
    if not isinstance(draft_overridden, bool):
        raise PlannerRepositoryError("本机日程草稿来源标记无效。")
    try:
        calendar_events = normalize_calendar_events(calendar_events)
    except CalendarExchangeError as exc:
        raise PlannerRepositoryError(str(exc)) from exc
    calendar_subscriptions = _normalize_calendar_subscriptions(calendar_subscriptions)
    caldav_accounts = _normalize_caldav_accounts(caldav_accounts)
    if active_tracking is not None:
        if not isinstance(active_tracking, dict):
            raise PlannerRepositoryError("当前计时状态无效。")
        task_id = active_tracking.get("taskId")
        started_at = active_tracking.get("startedAt")
        checkpoint_at = active_tracking.get("checkpointAt", started_at)
        accumulated = active_tracking.get("accumulatedSeconds", 0)
        if (
            not isinstance(task_id, str) or not task_id
            or not isinstance(started_at, str) or not isinstance(checkpoint_at, str)
        ):
            raise PlannerRepositoryError("当前计时缺少任务或开始时间。")
        try:
            datetime.fromisoformat(started_at)
            datetime.fromisoformat(checkpoint_at)
        except ValueError as exc:
            raise PlannerRepositoryError("当前计时的开始或检查点时间无效。") from exc
        if isinstance(accumulated, bool) or not isinstance(accumulated, int) or accumulated < 0:
            raise PlannerRepositoryError("当前计时的累计秒数无效。")
        mode = active_tracking.get("mode", "stopwatch")
        target_seconds = active_tracking.get("targetSeconds", 0)
        paused = active_tracking.get("paused", False)
        session_logged = active_tracking.get("sessionLoggedSeconds", 0)
        segment_started = active_tracking.get("segmentStartedAt", started_at)
        session_id = active_tracking.get("sessionId", "")
        if not isinstance(mode, str) or mode not in {"stopwatch", "pomodoro", "flowtime", "countdown"}:
            raise PlannerRepositoryError("当前计时模式无效。")
        if isinstance(target_seconds, bool) or not isinstance(target_seconds, int) or target_seconds < 0:
            raise PlannerRepositoryError("当前计时的目标时长无效。")
        if not isinstance(paused, bool):
            raise PlannerRepositoryError("当前计时的暂停状态无效。")
        if isinstance(session_logged, bool) or not isinstance(session_logged, int) or session_logged < 0:
            raise PlannerRepositoryError("当前计时已记录时长无效。")
        if not isinstance(segment_started, str):
            raise PlannerRepositoryError("当前计时的分段开始时间无效。")
        try:
            datetime.fromisoformat(segment_started)
        except ValueError as exc:
            raise PlannerRepositoryError("当前计时的分段开始时间无效。") from exc
        if not isinstance(session_id, str):
            raise PlannerRepositoryError("当前计时的会话 id 无效。")
        active_tracking = {
            **active_tracking,
            "checkpointAt": checkpoint_at,
            "accumulatedSeconds": accumulated,
            "mode": mode,
            "targetSeconds": target_seconds,
            "paused": paused,
            "sessionLoggedSeconds": session_logged,
            "segmentStartedAt": segment_started,
            "sessionId": session_id,
        }

    for records in (legacy_records, local_records):
        seen: set[str] = set()
        for record in records:
            if record.get("type") != "planner":
                raise PlannerRepositoryError("本机日程记录类型无效。")
            record_id = record.get("id")
            if not isinstance(record_id, str) or not record_id or record_id in seen:
                raise PlannerRepositoryError("本机日程记录 id 缺失或重复。")
            seen.add(record_id)
            if not isinstance(record.get("data"), dict):
                raise PlannerRepositoryError("本机日程记录 data 必须是对象。")

    normalized_deleted: list[dict[str, str]] = []
    seen_deleted: set[tuple[str, str]] = set()
    for item in deleted:
        if not isinstance(item, dict):
            raise PlannerRepositoryError("本机日程删除标记结构无效。")
        kind, record_id = item.get("type"), item.get("id")
        if kind != "planner" or not isinstance(record_id, str) or not record_id:
            raise PlannerRepositoryError("本机日程删除标记缺少有效类型或 id。")
        key = (kind, record_id)
        if key not in seen_deleted:
            normalized_deleted.append({**item, "type": kind, "id": record_id})
            seen_deleted.add(key)
    return {
        **_json_copy(state, "本机日程状态"),
        "legacyRecords": _json_copy(legacy_records, "本机旧日程"),
        "localRecords": _json_copy(local_records, "本机新增日程"),
        "recordOverrides": _json_copy(overrides, "本机日程覆盖"),
        "deletedRecords": normalized_deleted,
        "legacySettings": _json_copy(legacy_settings, "本机旧日程设置"),
        "settingsOverrides": _json_copy(setting_overrides, "本机日程设置覆盖"),
        "draft": _json_copy(draft, "本机日程草稿"),
        "draftOverridden": draft_overridden,
        "activeTracking": _json_copy(active_tracking, "当前计时"),
        "calendarEvents": _json_copy(calendar_events, "外部日历事件"),
        "calendarSubscriptions": _json_copy(calendar_subscriptions, "日历订阅"),
        "caldavAccounts": _json_copy(caldav_accounts, "CalDAV 账户"),
    }


def _initial_state(
    records: list[dict[str, Any]], settings: dict[str, Any], draft: dict[str, Any]
) -> dict[str, Any]:
    return {
        "legacyRecords": records,
        "localRecords": [],
        "recordOverrides": {},
        "deletedRecords": [],
        "legacySettings": settings,
        "settingsOverrides": {},
        "draft": draft,
        "draftOverridden": False,
        "activeTracking": None,
        "calendarEvents": [],
        "calendarSubscriptions": [],
        "caldavAccounts": [],
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
        return _normalize_runtime(_strict_json_loads(row[0], "本机日程状态")) if row else None
    except PlannerRepositoryError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise PlannerRepositoryError(f"无法读取本机日程状态：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()


class PlannerRepository:
    """Transactional planner with immutable imported rows and local overlays.

    Imported envelopes are retained byte-for-byte at the JSON-value level in
    ``legacyRecords``. Completion and reminder timestamps live in
    ``recordOverrides``; deleting an imported row writes a local tombstone.
    """

    def __init__(
        self,
        database_path: str | Path,
        legacy_store: Any = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser()
        self._lock = RLock()
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._calendar_occurrence_cache: dict[str, list[dict[str, Any]]] = {}
        existing = _read_runtime(self.database_path)
        if existing is None:
            source = legacy_store
            if source is None:
                imported = load_imported_data(self.database_path)
                if imported.get("status") == "unavailable":
                    raise PlannerRepositoryError(imported.get("error") or "无法读取旧版导入数据。")
                source = imported
            records, settings, draft, _ = _legacy_source(source)
            self._materialize_if_missing(_initial_state(records, settings, draft))
            existing = _read_runtime(self.database_path)
            if existing is None:
                raise PlannerRepositoryError("无法初始化本机日程状态。")
        self._state = existing
        active_tracking = self._state.get("activeTracking")
        if isinstance(active_tracking, dict):
            # Recover to the last persisted checkpoint. Timed focus sessions remain
            # available but paused, so time spent with the app closed is never counted.
            recovered = deepcopy(self._state)
            checkpoint = datetime.fromisoformat(active_tracking["checkpointAt"])
            if active_tracking.get("mode", "stopwatch") == "stopwatch":
                self._finish_tracking_in(recovered, checkpoint)
            else:
                self._pause_tracking_in(recovered, checkpoint)
            self._commit(recovered)

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
            present = connection.execute(f"SELECT 1 FROM {_TABLE} WHERE singleton=1").fetchone()
            if present is None:
                normalized = _normalize_runtime(initial)
                connection.execute(
                    f"INSERT INTO {_TABLE}(singleton,state_json) VALUES(1,?)",
                    (_json_dumps(normalized),),
                )
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            if isinstance(exc, PlannerRepositoryError):
                raise
            raise PlannerRepositoryError(f"初始化本机日程状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _commit(self, state: dict[str, Any]) -> None:
        cloned = _normalize_runtime(_json_copy(state, "日程状态"))
        encoded = _json_dumps(cloned)
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
            current_row = connection.execute(
                f"SELECT state_json FROM {_TABLE} WHERE singleton=1"
            ).fetchone()
            if current_row is None:
                raise PlannerRepositoryError(
                    "日程存储在保存期间被移除；已阻止旧状态覆盖。"
                )
            try:
                current_state = _normalize_runtime(json.loads(current_row[0]))
            except (TypeError, ValueError, PlannerRepositoryError) as exc:
                raise PlannerRepositoryError(
                    "日程存储在保存期间变得无效；已阻止旧状态覆盖。"
                ) from exc
            if current_state != self._state:
                connection.rollback()
                self._state = current_state
                raise PlannerRepositoryError(
                    "日程已被另一个工作台实例更新；当前状态已刷新，请检查后重新执行刚才的操作。"
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
            raise PlannerRepositoryError(f"保存本机日程数据失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        self._state = cloned

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise PlannerRepositoryError("日程时钟必须返回 datetime。")
        return value.astimezone() if value.tzinfo is not None else value

    @staticmethod
    def _record_id(record: dict[str, Any]) -> str:
        return str(record.get("id", ""))

    def _visible_records(self, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        source = state or self._state
        hidden = {(item["type"], item["id"]) for item in source["deletedRecords"]}
        local_ids = {str(record.get("id", "")) for record in source["localRecords"]}
        rows: list[dict[str, Any]] = []
        for raw in source["legacyRecords"]:
            record_id = self._record_id(raw)
            if ("planner", record_id) in hidden or record_id in local_ids:
                continue
            row = deepcopy(raw)
            changes = source["recordOverrides"].get(record_id, {})
            if "date" in changes:
                row["date"] = deepcopy(changes["date"])
            data_changes = changes.get("data", {})
            if isinstance(data_changes, dict):
                row["data"] = {**row["data"], **deepcopy(data_changes)}
            if "estimateMinutes" in row["data"]:
                row["data"]["estimateMinutes"] = _effective_estimate_minutes(
                    row["data"]["estimateMinutes"]
                )
            rows.append(row)
        for raw in source["localRecords"]:
            record_id = self._record_id(raw)
            if ("planner", record_id) in hidden:
                continue
            row = deepcopy(raw)
            changes = source["recordOverrides"].get(record_id, {})
            if "date" in changes:
                row["date"] = deepcopy(changes["date"])
            data_changes = changes.get("data", {})
            if isinstance(data_changes, dict):
                row["data"] = {**row["data"], **deepcopy(data_changes)}
            if "estimateMinutes" in row["data"]:
                row["data"]["estimateMinutes"] = _effective_estimate_minutes(
                    row["data"]["estimateMinutes"]
                )
            rows.append(row)
        return rows

    @staticmethod
    def _sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def created_value(record: dict[str, Any]) -> float:
            value = record.get("createdAt", 0)
            if isinstance(value, bool):
                return float(int(value))
            try:
                result = float(value)
                return result if math.isfinite(result) else 0.0
            except (TypeError, ValueError):
                return 0.0

        # The old app orders by date and then by creation time, ascending.
        return sorted(records, key=lambda item: (str(item.get("date", "")), created_value(item)))

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return _json_copy(self._sort_records(self._visible_records()), "日程记录")

    def all_records(self) -> list[dict[str, Any]]:
        """Alias intended for projection bridges that need the full visible set."""
        return self.records()

    def settings(self) -> dict[str, Any]:
        with self._lock:
            result = {**deepcopy(self._state["legacySettings"]), **deepcopy(self._state["settingsOverrides"])}
            # The old custom-board schema called the in-progress state
            # ``inprogress``; native task status uses ``doing``. Translate
            # only the imported base, leaving its original payload untouched.
            if "plannerCustomBoards" not in self._state["settingsOverrides"]:
                legacy_boards = deepcopy(
                    self._state["legacySettings"].get("plannerCustomBoards", [])
                )
                if isinstance(legacy_boards, list):
                    for board in legacy_boards:
                        if not isinstance(board, dict) or not isinstance(board.get("columns"), list):
                            continue
                        for column in board["columns"]:
                            if isinstance(column, dict) and column.get("status") == "inprogress":
                                column["status"] = "doing"
                    result["plannerCustomBoards"] = legacy_boards
            # The legacy UI persisted its view as ``plannerDisplay``. Keep
            # that source value intact and derive the native view only until
            # a native ``plannerViewMode`` override has been saved.
            if "plannerViewMode" not in self._state["settingsOverrides"]:
                legacy_display = self._state["legacySettings"].get("plannerDisplay")
                if legacy_display == "board":
                    result["plannerViewMode"] = "kanban"
                elif legacy_display == "matrix":
                    result["plannerViewMode"] = "matrix"
                elif legacy_display == "timeline":
                    result["plannerViewMode"] = "list"
                elif isinstance(legacy_display, str) and legacy_display.startswith(_CUSTOM_BOARD_PREFIX):
                    custom_id = legacy_display[len(_CUSTOM_BOARD_PREFIX):]
                    boards = _normalize_custom_boards(result.get("plannerCustomBoards", []))
                    if custom_id and any(board["id"] == custom_id for board in boards):
                        result["plannerViewMode"] = legacy_display
                    else:
                        # An orphaned old preference remains in legacySettings
                        # for audit/rollback, while the UI starts safely.
                        result["plannerViewMode"] = "list"
                else:
                    result["plannerViewMode"] = "list"
            value = result.get("plannerFilter", "all")
            result["plannerFilter"] = value if isinstance(value, str) and value in _FILTERS else "all"
            try:
                result["plannerProjectFilter"] = _normalize_project(result.get("plannerProjectFilter", ""))
            except PlannerRepositoryError:
                result["plannerProjectFilter"] = ""
            try:
                tags = _normalize_tags([result.get("plannerTagFilter", "")])
                result["plannerTagFilter"] = tags[0] if tags else ""
            except PlannerRepositoryError:
                result["plannerTagFilter"] = ""
            selected = result.get("plannerSelectedDate")
            try:
                result["plannerSelectedDate"] = _valid_date(selected, "已选日期")
            except PlannerRepositoryError:
                result.pop("plannerSelectedDate", None)
            try:
                result["plannerCustomBoards"] = _normalize_custom_boards(
                    result.get("plannerCustomBoards", [])
                )
            except PlannerRepositoryError:
                result["plannerCustomBoards"] = []
            result["plannerCustomBoardOrders"] = _normalize_custom_board_orders(
                result.get("plannerCustomBoardOrders", {})
            )
            if "plannerBoardOrder" in self._state["settingsOverrides"]:
                result["plannerBoardOrder"] = _normalize_board_orders(
                    self._state["settingsOverrides"]["plannerBoardOrder"]
                )
            else:
                result["plannerBoardOrder"] = _normalize_board_orders(
                    self._state["legacySettings"].get("plannerBoardOrder", {}),
                    legacy=True,
                )
            return _json_copy(result, "日程设置")

    def _effective_board_orders(
        self, records: list[dict[str, Any]] | None = None
    ) -> dict[str, list[str]]:
        """Return saved lane order plus every visible task in deterministic order."""
        source_records = records if records is not None else self._sort_records(
            self._visible_records()
        )
        orders = self.settings()["plannerBoardOrder"]
        seen_by_status = {status: set(orders[status]) for status in _BOARD_STATUSES}
        for record in _board_fallback_order(source_records):
            record_id = str(record.get("id", ""))
            status = _board_task_status(record)
            if record_id and record_id not in seen_by_status[status]:
                orders[status].append(record_id)
                seen_by_status[status].add(record_id)
        return orders

    def draft(self) -> dict[str, Any]:
        with self._lock:
            return _json_copy(self._state["draft"], "日程草稿")

    def deleted_record_keys(self) -> list[dict[str, str]]:
        with self._lock:
            return _json_copy(self._state["deletedRecords"], "日程删除标记")

    def webdav_sync_state(self) -> dict[str, Any]:
        """Return only the planner rows and vectors used by the WebDAV protocol."""
        with self._lock:
            settings = self.settings()
            return _json_copy({
                "records": self._sort_records(self._visible_records()),
                "settings": {
                    key: deepcopy(settings[key])
                    for key in (
                        "webdavPlannerVector",
                        "webdavPlannerTombstones",
                        "webdavPlannerConflicts",
                    )
                    if key in settings
                },
            }, "跨设备日程状态")

    def apply_webdav_sync_snapshot(self, snapshot: Any) -> None:
        """Apply a validated merge while keeping the imported legacy payload intact."""
        merged = normalize_snapshot(snapshot)
        if merged is None:
            raise PlannerRepositoryError("合并后的跨设备日程快照无效，未应用。")
        incoming = {record["id"]: record for record in merged["tasks"]}
        with self._lock:
            visible = self._visible_records()
            existing_ids = {
                record["id"] for record in visible if is_syncable_task(record)
            }
            legacy_ids = {
                record["id"] for record in self._state["legacyRecords"]
                if is_syncable_task(record)
            }
            candidate = deepcopy(self._state)
            candidate["localRecords"] = [
                record for record in candidate["localRecords"]
                if not is_syncable_task(record)
            ]
            candidate["recordOverrides"] = {
                key: value for key, value in candidate["recordOverrides"].items()
                if key not in existing_ids and key not in incoming
            }
            deleted = [
                item for item in candidate["deletedRecords"]
                if not (item.get("type") == "planner" and item.get("id") in incoming)
            ]
            deleted_ids = {item.get("id") for item in deleted}
            for record_id in existing_ids - incoming.keys():
                if record_id in legacy_ids and record_id not in deleted_ids:
                    deleted.append({"type": "planner", "id": record_id})
            candidate["deletedRecords"] = deleted
            candidate["localRecords"].extend(deepcopy(list(incoming.values())))
            candidate["settingsOverrides"].update({
                "webdavPlannerVector": merged["vector"],
                "webdavPlannerTombstones": merged["tombstones"],
                "webdavPlannerConflicts": merged["conflicts"],
            })
            self._commit(candidate)

    def save_webdav_sync_state(self, state: Any, device_id: str) -> None:
        """Persist version stamps and vector metadata after a local planner edit."""
        snapshot = snapshot_from_state(state, device_id)
        if normalize_snapshot(snapshot) is None:
            raise PlannerRepositoryError("本机跨设备日程状态无效，尚未保存。")
        self.apply_webdav_sync_snapshot(snapshot)

    @staticmethod
    def _date_today(value: str | date | datetime | None, fallback: date) -> str:
        if value is None:
            return fallback.isoformat()
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return _valid_date(value, "查询日期")

    @staticmethod
    def _filtered(
        records: list[dict[str, Any]], filter_name: str, today: str,
        project_filter: str = "", tag_filter: str = "",
    ) -> list[dict[str, Any]]:
        if filter_name == "today":
            filtered = [item for item in records if item.get("date") == today and not item["data"].get("done")]
        elif filter_name == "scheduled":
            filtered = [item for item in records if str(item.get("date", "")) >= today and not item["data"].get("done")]
        elif filter_name == "done":
            filtered = [item for item in records if item["data"].get("done")]
        else:
            filtered = list(records)
        if project_filter:
            filtered = [
                item for item in filtered
                if str(item["data"].get("project", "")).casefold() == project_filter.casefold()
            ]
        if tag_filter:
            filtered = [
                item for item in filtered
                if isinstance(item["data"].get("tags", []), list) and any(
                    isinstance(tag, str) and tag.casefold() == tag_filter.casefold()
                    for tag in item["data"].get("tags", [])
                )
            ]
        return filtered

    @staticmethod
    def _date_metrics(records: list[dict[str, Any]], today: str) -> tuple[dict[str, int], list[dict[str, Any]]]:
        current = date.fromisoformat(today)
        end = (current + timedelta(days=6)).isoformat()
        pending = [item for item in records if not item["data"].get("done")]
        metrics = {
            "today": sum(item.get("date") == today for item in pending),
            "overdue": sum(isinstance(item.get("date"), str) and item["date"] < today for item in pending),
            "week": sum(isinstance(item.get("date"), str) and today <= item["date"] <= end for item in pending),
        }
        week_days = []
        for offset in range(7):
            day = current + timedelta(days=offset)
            day_key = day.isoformat()
            count = sum(item.get("date") == day_key and not item["data"].get("done") for item in records)
            week_days.append({
                "date": day_key,
                "weekday": _WEEKDAYS[day.weekday()],
                "day": day.day,
                "count": count,
                "isToday": offset == 0,
            })
        return metrics, week_days

    @staticmethod
    def _schedule_info(record: dict[str, Any]) -> dict[str, Any] | None:
        """Return an effective timebox while keeping legacy timed tasks visible."""
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        raw_start = data.get("plannedStart", "")
        legacy_time = False
        if not raw_start and "plannedStart" not in data:
            raw_start = data.get("time", "")
            legacy_time = bool(raw_start)
        if not isinstance(raw_start, str) or not _TIME_PATTERN.fullmatch(raw_start):
            return None
        raw_day = data.get("plannedDate") or record.get("date")
        try:
            day = _valid_date(raw_day, "排程日期")
        except PlannerRepositoryError:
            return None
        estimate = _effective_estimate_minutes(data.get("estimateMinutes", 30))
        hour, minute = (int(part) for part in raw_start.split(":"))
        start_minute = hour * 60 + minute
        return {
            "scheduleDate": day,
            "start": raw_start,
            "startMinute": start_minute,
            "endMinute": min(24 * 60, start_minute + estimate),
            "estimateMinutes": estimate,
            "legacyTimeOnly": legacy_time,
        }

    @classmethod
    def _timeline_for_day(
        cls,
        records: list[dict[str, Any]],
        selected_day: str,
        calendar_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        scheduled: list[dict[str, Any]] = []
        unscheduled: list[dict[str, Any]] = []
        for record in records:
            data = record.get("data") if isinstance(record.get("data"), dict) else {}
            external_todo = data.get("externalTodo") if isinstance(data.get("externalTodo"), dict) else {}
            if external_todo.get("cancelled"):
                continue
            info = cls._schedule_info(record)
            if info and info["scheduleDate"] == selected_day:
                scheduled.append({**record, **info})
            elif not info and not data.get("done"):
                unscheduled.append(record)

        scheduled.sort(key=lambda row: (
            row["startMinute"],
            0 if row["data"].get("priority") == "high" else 1,
            str(row.get("id", "")),
        ))
        selected = date.fromisoformat(selected_day)
        local_zone = get_localzone()
        day_start = datetime.combine(selected, time.min, tzinfo=local_zone)
        day_end = datetime.combine(selected + timedelta(days=1), time.min, tzinfo=local_zone)
        day_start_utc = day_start.astimezone(timezone.utc)
        day_end_utc = day_end.astimezone(timezone.utc)
        visible_start = 7 * 60
        visible_end = 23 * 60
        event_blocks: list[dict[str, Any]] = []
        for event in calendar_events or []:
            if not isinstance(event, dict) or event.get("transparency", "OPAQUE") != "OPAQUE":
                continue
            if event.get("allDay"):
                start_minute, end_minute = visible_start, visible_end
            else:
                try:
                    event_start = datetime.fromisoformat(event.get("startAt", ""))
                    event_end = datetime.fromisoformat(event.get("endAt", ""))
                    if event_end <= event_start:
                        continue
                    event_start_utc = event_start.astimezone(timezone.utc)
                    event_end_utc = event_end.astimezone(timezone.utc)
                except (TypeError, ValueError):
                    continue
                if event_start_utc < day_start_utc:
                    start_minute = 0
                else:
                    local_start = event_start.astimezone(local_zone)
                    start_minute = local_start.hour * 60 + local_start.minute
                if event_end_utc > day_end_utc:
                    end_minute = 24 * 60
                else:
                    local_end = event_end.astimezone(local_zone)
                    end_minute = local_end.hour * 60 + local_end.minute
                    if local_end.second or local_end.microsecond:
                        end_minute += 1
                if end_minute <= visible_start or start_minute >= visible_end:
                    continue
                start_minute = max(visible_start, start_minute)
                end_minute = min(visible_end, end_minute)
            event_blocks.append({
                "id": str(event.get("id", event.get("uid", ""))),
                "title": str(event.get("title", "外部日历事件")),
                "displayTime": str(event.get("displayTime", "全天" if event.get("allDay") else "")),
                "sourceCalendar": str(event.get("sourceCalendar", "")),
                "allDay": bool(event.get("allDay")),
                "startMinute": start_minute,
                "endMinute": end_minute,
                "withinVisibleRange": True,
            })

        event_lane_ends: list[int] = []
        for event in sorted(event_blocks, key=lambda row: (row["startMinute"], row["endMinute"], row["id"])):
            lane = next(
                (index for index, lane_end in enumerate(event_lane_ends) if lane_end <= event["startMinute"]),
                len(event_lane_ends),
            )
            if lane == len(event_lane_ends):
                event_lane_ends.append(event["endMinute"])
            else:
                event_lane_ends[lane] = event["endMinute"]
            event["lane"] = lane
        event_lane_count = max(1, len(event_lane_ends))
        for event in event_blocks:
            event["lanes"] = event_lane_count

        lane_ends: list[int] = []
        conflict_count = 0
        for row in scheduled:
            start, end = row["startMinute"], row["endMinute"]
            task_conflict = any(
                start < other["endMinute"] and end > other["startMinute"]
                for other in scheduled if other is not row
            )
            calendar_conflict = any(
                start < event["endMinute"] and end > event["startMinute"]
                for event in event_blocks
            )
            row["conflict"] = task_conflict or calendar_conflict
            if row["conflict"]:
                conflict_count += 1
            lane = next((index for index, lane_end in enumerate(lane_ends) if lane_end <= start), len(lane_ends))
            if lane == len(lane_ends):
                lane_ends.append(end)
            else:
                lane_ends[lane] = end
            row["lane"] = lane

        lanes = max(1, len(lane_ends))
        for row in scheduled:
            row["lanes"] = lanes
            row["withinVisibleRange"] = 7 * 60 <= row["startMinute"] and row["endMinute"] <= 23 * 60
        unscheduled.sort(key=lambda row: (
            0 if row.get("data", {}).get("priority") == "high" else 1,
            str(row.get("date", "")),
            str(row.get("data", {}).get("title", "")).casefold(),
        ))
        planned_minutes = sum(row["estimateMinutes"] for row in scheduled if not row["data"].get("done"))
        occupied = [
            (max(visible_start, row["startMinute"]), min(visible_end, row["endMinute"]))
            for row in scheduled
            if not row["data"].get("done") and row["startMinute"] < visible_end and row["endMinute"] > visible_start
        ]
        occupied.extend((row["startMinute"], row["endMinute"]) for row in event_blocks)
        occupied.sort()
        occupied_minutes = 0
        occupied_start = occupied_end = None
        for start, end in occupied:
            if occupied_end is None or start > occupied_end:
                if occupied_end is not None:
                    occupied_minutes += occupied_end - occupied_start
                occupied_start, occupied_end = start, end
            else:
                occupied_end = max(occupied_end, end)
        if occupied_end is not None:
            occupied_minutes += occupied_end - occupied_start
        return {
            "date": selected_day,
            "blocks": scheduled,
            "eventBlocks": event_blocks,
            "unscheduled": unscheduled,
            "conflictCount": conflict_count,
            "plannedMinutes": planned_minutes,
            "freeMinutes": max(0, (23 - 7) * 60 - occupied_minutes),
            "backlogCount": len(unscheduled),
            "visibleStartHour": 7,
            "visibleEndHour": 23,
            "pixelsPerHour": 48,
        }

    @staticmethod
    def _group_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        by_date: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            key = str(record.get("date", ""))
            by_date.setdefault(key, []).append(record)
        for day_key, rows in by_date.items():
            groups.append({"date": day_key, "pending": sum(not row["data"].get("done") for row in rows), "records": rows})
        return groups

    def _calendar_events_for_day(self, day_key: str) -> list[dict[str, Any]]:
        selected = date.fromisoformat(day_key)
        local_zone = get_localzone()
        day_start = datetime.combine(selected, time.min, tzinfo=local_zone).astimezone(timezone.utc)
        day_end = datetime.combine(selected + timedelta(days=1), time.min, tzinfo=local_zone).astimezone(timezone.utc)
        result: list[dict[str, Any]] = []
        day_events = self._calendar_occurrence_cache.get(day_key)
        if day_events is None:
            day_events = calendar_occurrences_for_day(self._state.get("calendarEvents", []), day_key)
            if len(self._calendar_occurrence_cache) >= 31:
                self._calendar_occurrence_cache.pop(next(iter(self._calendar_occurrence_cache)))
            self._calendar_occurrence_cache[day_key] = day_events
        for raw in day_events:
            if raw.get("allDay"):
                start_day = date.fromisoformat(raw["startDate"])
                end_day = date.fromisoformat(raw["endDate"])
                if not start_day <= selected < end_day:
                    continue
                display_time = "全天"
            else:
                start_at = datetime.fromisoformat(raw["startAt"])
                end_at = datetime.fromisoformat(raw["endAt"])
                start_local = start_at.astimezone()
                end_local = end_at.astimezone()
                start_utc = start_local.astimezone(timezone.utc)
                end_utc = end_local.astimezone(timezone.utc)
                intersects = (start_utc < day_end and end_utc > day_start) or (
                    start_utc == end_utc and day_start <= start_utc < day_end
                )
                if not intersects:
                    continue
                visible_start = datetime.combine(selected, time.min, tzinfo=local_zone) if start_utc < day_start else start_local
                visible_end = datetime.combine(selected + timedelta(days=1), time.min, tzinfo=local_zone) if end_utc >= day_end else end_local
                start_label = "00:00" if start_utc < day_start else visible_start.strftime("%H:%M")
                end_label = "24:00" if end_utc >= day_end else visible_end.strftime("%H:%M")
                display_time = start_label if start_utc == end_utc else f"{start_label}–{end_label}"
            result.append({**deepcopy(raw), "displayTime": display_time})
        return sorted(result, key=lambda item: (
            0 if item.get("allDay") else 1,
            str(item.get("startAt", "")),
            str(item.get("title", "")).casefold(),
        ))

    def state(self, today: str | date | datetime | None = None) -> dict[str, Any]:
        with self._lock:
            now = self._now()
            day_key = self._date_today(today, now.date())
            rows = self._sort_records(self._visible_records())
            settings = self.settings()
            filter_name = settings.get("plannerFilter", "all")
            selected_day = settings.get("plannerSelectedDate") or day_key
            active_tracking = deepcopy(self._state.get("activeTracking"))
            elapsed_seconds = 0
            if active_tracking:
                checkpoint = datetime.fromisoformat(active_tracking["checkpointAt"])
                elapsed_now = now
                if elapsed_now.tzinfo is None and checkpoint.tzinfo is not None:
                    elapsed_now = elapsed_now.replace(tzinfo=checkpoint.tzinfo)
                elif elapsed_now.tzinfo is not None and checkpoint.tzinfo is None:
                    checkpoint = checkpoint.replace(tzinfo=elapsed_now.tzinfo)
                elapsed_seconds = int(active_tracking["accumulatedSeconds"])
                if not active_tracking.get("paused", False):
                    elapsed_seconds += max(0, int((elapsed_now - checkpoint).total_seconds()))
                target_seconds = int(active_tracking.get("targetSeconds", 0) or 0)
                if target_seconds:
                    elapsed_seconds = min(elapsed_seconds, target_seconds)
                active_tracking["elapsedSeconds"] = elapsed_seconds
                active_tracking["remainingSeconds"] = max(0, target_seconds - elapsed_seconds) if target_seconds else 0
                for row in rows:
                    data = row.get("data") if isinstance(row.get("data"), dict) else {}
                    stored = data.get("trackedSeconds", 0)
                    data["trackedSeconds"] = stored if isinstance(stored, int) and not isinstance(stored, bool) and stored >= 0 else 0
                    if str(row.get("id", "")) == active_tracking["taskId"]:
                        logged_seconds = int(active_tracking.get("sessionLoggedSeconds", 0) or 0)
                        data["trackedSeconds"] += max(0, elapsed_seconds - logged_seconds)
            metrics, week_days = self._date_metrics(rows, day_key)
            if selected_day != day_key:
                _, week_days = self._date_metrics(rows, selected_day)
            for week_day in week_days:
                day_rows = [
                    row for row in rows
                    if (self._schedule_info(row) or {}).get("scheduleDate") == week_day["date"]
                    and not row["data"].get("done")
                    and not (
                        isinstance(row["data"].get("externalTodo"), dict)
                        and row["data"]["externalTodo"].get("cancelled")
                    )
                ]
                week_day["plannedCount"] = len(day_rows)
                week_day["plannedMinutes"] = sum(
                    (self._schedule_info(row) or {}).get("estimateMinutes", 0) for row in day_rows
                )
            project_filter = settings.get("plannerProjectFilter", "")
            tag_filter = settings.get("plannerTagFilter", "")
            filtered = self._filtered(rows, filter_name, day_key, project_filter, tag_filter)
            calendar_events = self._calendar_events_for_day(selected_day)
            timeline = self._timeline_for_day(rows, selected_day, calendar_events)
            view_mode = settings.get("plannerViewMode", "list")
            if view_mode not in _VIEW_MODES and not any(
                view_mode == _CUSTOM_BOARD_PREFIX + board["id"]
                for board in settings["plannerCustomBoards"]
            ):
                view_mode = "list"
            board_orders = self._effective_board_orders(rows)
            return {
                "today": day_key,
                "localTime": now.strftime("%H:%M"),
                "selectedDate": selected_day,
                "filter": filter_name,
                "projectFilter": project_filter,
                "tagFilter": tag_filter,
                "viewMode": view_mode,
                "customBoards": settings["plannerCustomBoards"],
                "customBoardOrders": settings["plannerCustomBoardOrders"],
                "boardOrders": board_orders,
                "records": rows,
                "allRecords": rows,
                "projects": sorted({
                    project.strip()
                    for row in rows
                    for project in [str((row.get("data") or {}).get("project", ""))]
                    if project.strip()
                }, key=str.casefold),
                "tags": sorted({
                    tag.strip()
                    for row in rows
                    for tag in ((row.get("data") or {}).get("tags", []) if isinstance((row.get("data") or {}).get("tags", []), list) else [])
                    if isinstance(tag, str) and tag.strip()
                }, key=str.casefold),
                "groups": self._group_records(filtered),
                "weekDays": week_days,
                "metrics": metrics,
                "timeline": timeline,
                "calendarEvents": calendar_events,
                "calendarSubscriptions": self._calendar_subscriptions_for_ui(),
                "caldavAccounts": self._caldav_accounts_for_ui(),
                "activeTracking": active_tracking or {},
                "activeTrackingElapsed": elapsed_seconds,
                "draft": _json_copy(self._state["draft"], "日程草稿"),
                "deletedRecords": _json_copy(self._state["deletedRecords"], "日程删除标记"),
            }

    def set_filter(self, filter_name: Any) -> str:
        if not isinstance(filter_name, str) or filter_name not in _FILTERS:
            raise PlannerRepositoryError("日程筛选条件无效。")
        with self._lock:
            candidate = deepcopy(self._state)
            candidate["settingsOverrides"]["plannerFilter"] = filter_name
            self._commit(candidate)
            return filter_name

    def set_task_filters(self, project: Any = "", tag: Any = "") -> dict[str, str]:
        project_filter = _normalize_project(project)
        normalized_tags = _normalize_tags([tag])
        tag_filter = normalized_tags[0] if normalized_tags else ""
        with self._lock:
            candidate = deepcopy(self._state)
            candidate["settingsOverrides"]["plannerProjectFilter"] = project_filter
            candidate["settingsOverrides"]["plannerTagFilter"] = tag_filter
            self._commit(candidate)
            return {"project": project_filter, "tag": tag_filter}

    def set_view_mode(self, view_mode: Any) -> str:
        if not isinstance(view_mode, str):
            raise PlannerRepositoryError("日程视图无效。")
        with self._lock:
            valid_custom_board = view_mode.startswith(_CUSTOM_BOARD_PREFIX) and any(
                view_mode == _CUSTOM_BOARD_PREFIX + board["id"]
                for board in self.settings().get("plannerCustomBoards", [])
            )
            if view_mode not in _VIEW_MODES and not valid_custom_board:
                raise PlannerRepositoryError("日程视图无效。")
            candidate = deepcopy(self._state)
            candidate["settingsOverrides"]["plannerViewMode"] = view_mode
            self._commit(candidate)
            return view_mode

    def set_board_order(self, status: Any, ordered_ids: Any) -> list[str]:
        """Persist the complete requested order for one standard Kanban lane.

        IDs omitted by a filtered or partial caller retain their previous
        relative order after the submitted IDs. Unknown IDs and IDs currently
        assigned to another lane are rejected. Duplicate IDs are ignored.
        """
        if not isinstance(status, str) or status not in _BOARD_STATUSES:
            raise PlannerRepositoryError("标准看板状态无效。")
        requested = _normalize_board_order_ids(ordered_ids, strict=True)
        with self._lock:
            records = self._sort_records(self._visible_records())
            active_ids = {
                str(record.get("id", ""))
                for record in records
                if _board_task_status(record) == status
            }
            unknown_ids = [task_id for task_id in requested if task_id not in active_ids]
            if unknown_ids:
                raise PlannerRepositoryError("标准看板顺序包含不存在或状态不匹配的任务。")

            orders = self._effective_board_orders(records)
            requested_set = set(requested)
            saved = requested + [task_id for task_id in orders[status] if task_id not in requested_set]
            orders[status] = saved
            candidate = deepcopy(self._state)
            candidate["settingsOverrides"]["plannerBoardOrder"] = orders
            self._commit(candidate)
            return self._effective_board_orders()[status]

    def move_task_on_standard_board(
        self,
        task_id: Any,
        target_status: Any,
        before_task_id: Any = "",
    ) -> dict[str, Any] | None:
        """Move/reorder a task and persist the complete three-lane order atomically.

        ``before_task_id`` identifies the task to insert before in the target
        lane. An empty value appends to the lane. The returned order is built
        from every visible record, so changing a filtered view cannot discard
        the relative order of tasks hidden by that filter.
        """
        if not isinstance(target_status, str) or target_status not in _BOARD_STATUSES:
            raise PlannerRepositoryError("标准看板目标状态无效。")
        if before_task_id is None:
            before_id = ""
        elif isinstance(before_task_id, str):
            before_id = before_task_id
        else:
            raise PlannerRepositoryError("标准看板排序位置无效。")

        with self._lock:
            target = self._target(task_id)
            if target is None:
                return None
            if not isinstance(task_id, str) or not task_id:
                # _target reports this for malformed identifiers; keep the
                # type narrowing explicit for the state updates below.
                raise PlannerRepositoryError("日程 id 无效。")

            data = target.get("data") if isinstance(target.get("data"), dict) else {}
            external_todo = data.get("externalTodo")
            source_status = _board_task_status(target)
            if (
                source_status != target_status
                and isinstance(external_todo, dict)
                and external_todo.get("cancelled")
            ):
                raise PlannerRepositoryError("来源已取消的任务不能修改状态。")
            active = self._state.get("activeTracking")
            if (
                isinstance(active, dict)
                and active.get("taskId") == task_id
                and target_status != "doing"
            ):
                raise PlannerRepositoryError("请先结束这项任务的计时，再移动到该看板列。")
            if target_status == "done":
                pending_children = [
                    row for row in self._visible_records()
                    if (row.get("data") or {}).get("parentTaskId") == task_id
                    and not (row.get("data") or {}).get("done")
                ]
                if pending_children:
                    raise PlannerRepositoryError("请先完成全部子任务，再移动到完成列。")

            records_before = self._sort_records(self._visible_records())
            orders_before = self._effective_board_orders(records_before)
            source_order = orders_before[source_status]
            source_index = source_order.index(task_id) if task_id in source_order else len(source_order)

            was_done = bool(data.get("done"))
            status_changed = (
                was_done != (target_status == "done")
                or data.get("status") != target_status
            )
            now = self._now() if status_changed and target_status == "done" else None
            candidate = deepcopy(self._state)
            changes = candidate["recordOverrides"].setdefault(task_id, {}).setdefault("data", {})
            changes["status"] = target_status
            changes["done"] = target_status == "done"
            if target_status == "done":
                changes["completedAt"] = (
                    now.isoformat(timespec="seconds") if now is not None
                    else data.get("completedAt", "")
                )
                if status_changed:
                    self._create_next_repeat(candidate, target, now or self._now())
            else:
                changes["completedAt"] = ""
                if was_done:
                    self._clear_reminder_receipt(candidate, task_id)

            records_after = self._sort_records(self._visible_records(candidate))
            lane_members = {
                status: {
                    str(record.get("id", ""))
                    for record in records_after
                    if _board_task_status(record) == status
                }
                for status in _BOARD_STATUSES
            }
            complete_orders = {status: [] for status in _BOARD_STATUSES}
            included_ids = {status: set() for status in _BOARD_STATUSES}
            for status in _BOARD_STATUSES:
                for record_id in orders_before[status]:
                    if (
                        record_id in lane_members[status]
                        and record_id != task_id
                        and record_id not in included_ids[status]
                    ):
                        complete_orders[status].append(record_id)
                        included_ids[status].add(record_id)
            for record in _board_fallback_order(records_after):
                record_id = str(record.get("id", ""))
                lane = _board_task_status(record)
                if record_id and record_id != task_id and record_id not in included_ids[lane]:
                    complete_orders[lane].append(record_id)
                    included_ids[lane].add(record_id)

            target_order = complete_orders[target_status]
            if before_id:
                if before_id == task_id:
                    if source_status != target_status:
                        raise PlannerRepositoryError("跨列移动时不能把任务自身设为排序目标。")
                    insertion_index = min(source_index, len(target_order))
                else:
                    if before_id not in lane_members[target_status]:
                        raise PlannerRepositoryError("排序目标已离开此列，请刷新后重试。")
                    insertion_index = target_order.index(before_id)
                target_order.insert(insertion_index, task_id)
            else:
                target_order.append(task_id)

            candidate["settingsOverrides"]["plannerBoardOrder"] = complete_orders
            self._commit(candidate)
            return {
                "task": self._target(task_id),
                "boardOrders": deepcopy(complete_orders),
            }

    def save_custom_board(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise PlannerRepositoryError("自定义看板数据无效。")
        board_id = value.get("id", "")
        if not isinstance(board_id, str):
            raise PlannerRepositoryError("自定义看板 id 无效。")
        with self._lock:
            boards = self.settings().get("plannerCustomBoards", [])
            if board_id:
                if not any(board["id"] == board_id for board in boards):
                    raise PlannerRepositoryError("要编辑的自定义看板已不存在。")
            elif len(boards) >= 12:
                raise PlannerRepositoryError("最多只能保存 12 个自定义看板。")

            raw = deepcopy(value)
            raw["id"] = board_id or str(uuid4())
            raw_columns = raw.get("columns")
            if isinstance(raw_columns, list):
                raw["columns"] = [
                    {**column, "id": column.get("id") or str(uuid4())}
                    if isinstance(column, dict) else column
                    for column in raw_columns
                ]
            normalized = _normalize_custom_boards([raw])[0]
            updated = [
                normalized if board["id"] == normalized["id"] else board
                for board in boards
            ]
            if not board_id:
                updated.append(normalized)
            candidate = deepcopy(self._state)
            candidate["settingsOverrides"]["plannerCustomBoards"] = updated
            board_orders = _normalize_custom_board_orders(
                candidate["settingsOverrides"].get("plannerCustomBoardOrders", {})
            )
            retained_column_ids = {column["id"] for column in normalized["columns"]}
            if normalized["id"] in board_orders:
                board_orders[normalized["id"]] = {
                    column_id: order
                    for column_id, order in board_orders[normalized["id"]].items()
                    if column_id in retained_column_ids
                }
            candidate["settingsOverrides"]["plannerCustomBoardOrders"] = board_orders
            self._commit(candidate)
            return _json_copy(normalized, "自定义看板")

    def delete_custom_board(self, board_id: Any) -> bool:
        if not isinstance(board_id, str) or not board_id.strip():
            raise PlannerRepositoryError("自定义看板 id 无效。")
        with self._lock:
            boards = self.settings().get("plannerCustomBoards", [])
            if not any(board["id"] == board_id for board in boards):
                return False
            candidate = deepcopy(self._state)
            candidate["settingsOverrides"]["plannerCustomBoards"] = [
                board for board in boards if board["id"] != board_id
            ]
            board_orders = _normalize_custom_board_orders(
                candidate["settingsOverrides"].get("plannerCustomBoardOrders", {})
            )
            board_orders.pop(board_id, None)
            candidate["settingsOverrides"]["plannerCustomBoardOrders"] = board_orders
            if candidate["settingsOverrides"].get("plannerViewMode") == _CUSTOM_BOARD_PREFIX + board_id:
                candidate["settingsOverrides"]["plannerViewMode"] = "kanban"
            self._commit(candidate)
            return True

    def move_task_to_custom_board_column(
        self,
        record_id: Any,
        status: Any,
        tag: Any = "",
        board_id: Any = "",
        column_id: Any = "",
        before_task_id: Any = "",
    ) -> dict[str, Any] | None:
        if not isinstance(status, str) or status not in _TASK_STATUSES:
            raise PlannerRepositoryError("看板列对应的任务状态无效。")
        tag_values = _normalize_tags([tag])
        tag_value = tag_values[0] if tag_values else ""
        if not isinstance(record_id, str) or not record_id:
            raise PlannerRepositoryError("待办 id 无效。")
        if not isinstance(board_id, str) or not isinstance(column_id, str):
            raise PlannerRepositoryError("看板排序目标无效。")
        if not isinstance(before_task_id, str):
            raise PlannerRepositoryError("看板排序位置无效。")
        if bool(board_id) != bool(column_id) or (before_task_id and not board_id):
            raise PlannerRepositoryError("看板排序目标无效。")
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return None
            selected_column: dict[str, str] | None = None
            if board_id:
                board = next((
                    item for item in self.settings().get("plannerCustomBoards", [])
                    if item["id"] == board_id
                ), None)
                selected_column = next((
                    item for item in board["columns"]
                    if item["id"] == column_id
                ), None) if board else None
                if (
                    selected_column is None
                    or selected_column["status"] != status
                    or selected_column["tag"].casefold() != tag_value.casefold()
                ):
                    raise PlannerRepositoryError("目标看板列已变更，请刷新后重试。")
            active = self._state.get("activeTracking")
            if isinstance(active, dict) and active.get("taskId") == record_id and status != "doing":
                raise PlannerRepositoryError("请先结束这项任务的计时，再移动到该看板列。")
            if status == "done":
                pending_children = [
                    row for row in self._visible_records()
                    if (row.get("data") or {}).get("parentTaskId") == record_id
                    and not (row.get("data") or {}).get("done")
                ]
                if pending_children:
                    raise PlannerRepositoryError("请先完成全部子任务，再移动到完成列。")
            tags = _normalize_tags((target.get("data") or {}).get("tags", []))
            if tag_value and tag_value.casefold() not in {item.casefold() for item in tags}:
                tags = _normalize_tags([*tags, tag_value])
            candidate = deepcopy(self._state)
            changes = candidate["recordOverrides"].setdefault(record_id, {}).setdefault("data", {})
            was_done = bool((target.get("data") or {}).get("done"))
            changes["status"] = status
            changes["done"] = status == "done"
            if status == "done":
                changes["completedAt"] = (
                    (target.get("data") or {}).get("completedAt", "")
                    if was_done else self._now().isoformat(timespec="seconds")
                )
            else:
                changes["completedAt"] = ""
            changes["tags"] = tags
            if status == "done" and not was_done:
                self._create_next_repeat(candidate, target, self._now())
            if selected_column is not None:
                members = [
                    row for row in self._visible_records(candidate)
                    if str((row.get("data") or {}).get("status", "done" if (row.get("data") or {}).get("done") else "todo")) == status
                    and (
                        not tag_value
                        or tag_value.casefold() in {
                            value.casefold()
                            for value in _normalize_tags((row.get("data") or {}).get("tags", []))
                        }
                    )
                ]
                member_ids = [str(row.get("id", "")) for row in members]
                member_set = set(member_ids)
                orders = _normalize_custom_board_orders(
                    candidate["settingsOverrides"].get("plannerCustomBoardOrders", {})
                )
                board_orders = orders.setdefault(board_id, {})
                old_order = board_orders.get(column_id, [])
                old_index = old_order.index(record_id) if record_id in old_order else None
                ordered_ids = [
                    task_id for task_id in old_order
                    if task_id in member_set and task_id != record_id
                ]
                ordered_set = set(ordered_ids)
                ordered_ids.extend(
                    task_id for task_id in member_ids
                    if task_id not in ordered_set and task_id != record_id
                )
                if before_task_id:
                    if before_task_id not in member_set:
                        raise PlannerRepositoryError("排序目标已离开此列，请刷新后重试。")
                    if before_task_id == record_id:
                        current_index = member_ids.index(record_id) if old_index is None else old_index
                        insertion_index = min(current_index, len(ordered_ids))
                    else:
                        insertion_index = ordered_ids.index(before_task_id)
                    ordered_ids.insert(insertion_index, record_id)
                else:
                    ordered_ids.append(record_id)
                board_orders[column_id] = ordered_ids
                candidate["settingsOverrides"]["plannerCustomBoardOrders"] = orders
            self._commit(candidate)
            return self._target(record_id)

    def set_selected_day(self, value: Any) -> str:
        selected_day = _valid_date(value, "已选日期")
        with self._lock:
            candidate = deepcopy(self._state)
            candidate["settingsOverrides"]["plannerSelectedDate"] = selected_day
            self._commit(candidate)
            return selected_day

    def _calendar_subscriptions_for_ui(self) -> list[dict[str, Any]]:
        event_counts: dict[str, int] = {}
        for event in self._state.get("calendarEvents", []):
            subscription_id = event.get("subscriptionId", "")
            if subscription_id:
                event_counts[subscription_id] = event_counts.get(subscription_id, 0) + 1
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "host": item["host"],
                "lastAttemptAt": item["lastAttemptAt"],
                "lastSuccessAt": item["lastSuccessAt"],
                "lastError": item["lastError"],
                "eventCount": event_counts.get(item["id"], 0),
            }
            for item in self._state.get("calendarSubscriptions", [])
        ]

    def calendar_subscription_details(self, subscription_id: Any) -> dict[str, Any] | None:
        if not isinstance(subscription_id, str) or not subscription_id:
            return None
        with self._lock:
            item = next((
                raw for raw in self._state.get("calendarSubscriptions", [])
                if raw["id"] == subscription_id
            ), None)
            return _json_copy(item, "日历订阅") if item else None

    def add_calendar_subscription(
        self, name: Any, host: Any, protected_url: Any
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise PlannerRepositoryError("订阅名称须为 1 至 80 个字符。")
        if not isinstance(host, str) or not host or len(host) > 255:
            raise PlannerRepositoryError("订阅服务器名称无效。")
        if not isinstance(protected_url, str) or not protected_url or len(protected_url) > 16_384:
            raise PlannerRepositoryError("受保护的订阅地址无效。")
        with self._lock:
            subscriptions = self._state.get("calendarSubscriptions", [])
            if len(subscriptions) >= 24:
                raise PlannerRepositoryError("最多只能保存 24 个日历订阅。")
            item = {
                "id": str(uuid4()),
                "name": name.strip(),
                "host": host,
                "urlProtected": protected_url,
                "etag": "",
                "lastModified": "",
                "lastAttemptAt": "",
                "lastSuccessAt": "",
                "lastError": "",
            }
            candidate = deepcopy(self._state)
            candidate["calendarSubscriptions"].append(item)
            self._commit(candidate)
            return {
                key: value for key, value in item.items() if key != "urlProtected"
            }

    @staticmethod
    def _caldav_account_for_ui(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: _json_copy(item[key], "CalDAV 账户")
            for key in (
                "id", "name", "host", "lastCheckedAt", "lastSuccessAt",
                "lastError", "lastSyncAt", "lastSyncSuccessAt", "lastSyncError",
                "calendars",
            )
            if key in item
        }

    @staticmethod
    def _caldav_source_key(account: dict[str, Any]) -> str:
        source_key = account.get("sourceKey")
        if isinstance(source_key, str) and _CALDAV_SOURCE_KEY_PATTERN.fullmatch(source_key):
            return source_key
        return hashlib.sha256(
            f"caldav:{account.get('id', '')}".casefold().encode("utf-8")
        ).hexdigest()

    def _caldav_accounts_for_ui(self) -> list[dict[str, Any]]:
        return [
            self._caldav_account_for_ui(item)
            for item in self._state.get("caldavAccounts", [])
        ]

    def caldav_account_details(self, account_id: Any) -> dict[str, Any] | None:
        if not isinstance(account_id, str) or not account_id:
            return None
        with self._lock:
            item = next((
                raw for raw in self._state.get("caldavAccounts", [])
                if raw["id"] == account_id
            ), None)
            return _json_copy(item, "CalDAV 账户") if item else None

    def caldav_pending_resource_hrefs(self, account_id: Any) -> list[str]:
        if not isinstance(account_id, str) or not account_id:
            return []
        with self._lock:
            account = next((
                raw for raw in self._state.get("caldavAccounts", [])
                if raw["id"] == account_id
            ), None)
            if account is None:
                return []
            source_key = self._caldav_source_key(account)
            pending: list[str] = []
            for row in self._visible_records():
                data = row.get("data") if isinstance(row.get("data"), dict) else {}
                external = data.get("externalTodo") if isinstance(data.get("externalTodo"), dict) else {}
                synced_done = external.get("syncedDone")
                href = external.get("resourceHref")
                if (
                    external.get("provider") == "caldav"
                    and external.get("sourceKey") == source_key
                    and isinstance(synced_done, bool)
                    and bool(data.get("done")) != synced_done
                    and not external.get("cancelled")
                    and not external.get("sourceMissing")
                    and isinstance(href, str) and href
                ):
                    if href not in pending:
                        pending.append(href)
                        if len(pending) > 500:
                            raise PlannerRepositoryError("一次最多回写 500 个 CalDAV 待办。")
            return pending

    def add_caldav_account(
        self,
        name: Any,
        host: Any,
        protected_url: Any,
        protected_credentials: Any,
        *,
        source_identity: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise PlannerRepositoryError("CalDAV 账户名称须为 1 至 80 个字符。")
        if not isinstance(host, str) or not host or len(host) > 255:
            raise PlannerRepositoryError("CalDAV 服务器名称无效。")
        if not isinstance(protected_url, str) or not protected_url or len(protected_url) > 16_384:
            raise PlannerRepositoryError("受保护的 CalDAV 地址无效。")
        if not isinstance(protected_credentials, str) or not protected_credentials or len(protected_credentials) > 16_384:
            raise PlannerRepositoryError("受保护的 CalDAV 登录信息无效。")
        if source_identity is not None and (
            not isinstance(source_identity, str)
            or not source_identity
            or len(source_identity.encode("utf-8")) > 16_384
            or any(ord(char) < 32 or ord(char) == 127 for char in source_identity)
        ):
            raise PlannerRepositoryError("CalDAV 来源地址无效。")
        with self._lock:
            accounts = self._state.get("caldavAccounts", [])
            if len(accounts) >= 12:
                raise PlannerRepositoryError("最多只能保存 12 个 CalDAV 账户。")
            account_id = str(uuid4())
            source_key = hashlib.sha256(
                f"caldav:{source_identity if source_identity is not None else account_id}".encode("utf-8")
            ).hexdigest()
            if source_identity is not None:
                parts = urlsplit(source_identity)
                collection_path = parts.path.rstrip("/") + "/"
                legacy_source_keys: set[str] = set()
                for row in self._visible_records():
                    data = row.get("data") if isinstance(row.get("data"), dict) else {}
                    external = data.get("externalTodo") if isinstance(data.get("externalTodo"), dict) else {}
                    href = external.get("resourceHref")
                    old_key = external.get("sourceKey")
                    if (
                        external.get("provider") == "caldav"
                        and isinstance(href, str)
                        and isinstance(old_key, str)
                        and _CALDAV_SOURCE_KEY_PATTERN.fullmatch(old_key)
                    ):
                        href_parts = urlsplit(href)
                        same_origin = (
                            href_parts.scheme.casefold() == parts.scheme.casefold()
                            and href_parts.netloc.casefold() == parts.netloc.casefold()
                        )
                        if same_origin and href_parts.path.startswith(collection_path):
                            legacy_source_keys.add(old_key)
                if len(legacy_source_keys) == 1:
                    if any(
                        self._caldav_source_key(raw) in legacy_source_keys
                        for raw in accounts
                    ):
                        raise PlannerRepositoryError("这个 CalDAV 日历地址已经添加。")
                    # Upgrade a collection first imported before source identities
                    # were persisted, preserving the existing task IDs.
                    source_key = next(iter(legacy_source_keys))
            if source_identity is not None and any(
                self._caldav_source_key(raw) == source_key for raw in accounts
            ):
                raise PlannerRepositoryError("这个 CalDAV 日历地址已经添加。")
            item = {
                "id": account_id,
                "name": name.strip(),
                "host": host,
                "urlProtected": protected_url,
                "credentialsProtected": protected_credentials,
                "lastCheckedAt": "",
                "lastSuccessAt": "",
                "lastError": "",
                "lastSyncAt": "",
                "lastSyncSuccessAt": "",
                "lastSyncError": "",
                "syncToken": "",
                "syncCollectionUnsupported": False,
                "sourceKey": source_key,
                "calendars": [],
            }
            candidate = deepcopy(self._state)
            candidate["caldavAccounts"].append(item)
            self._commit(candidate)
            return self._caldav_account_for_ui(item)

    def remove_caldav_account(self, account_id: Any) -> bool:
        if not isinstance(account_id, str) or not account_id:
            raise PlannerRepositoryError("CalDAV 账户 id 无效。")
        with self._lock:
            account = next((
                item for item in self._state.get("caldavAccounts", [])
                if item["id"] == account_id
            ), None)
            if account is None:
                return False
            candidate = deepcopy(self._state)
            source_key = self._caldav_source_key(account)
            for record in candidate.get("localRecords", []):
                data = record.get("data") if isinstance(record.get("data"), dict) else {}
                external = data.get("externalTodo") if isinstance(data.get("externalTodo"), dict) else None
                if external and external.get("provider") == "caldav" and external.get("sourceKey") == source_key:
                    external["accountRemoved"] = True
                    external["sourceMissing"] = True
            candidate["calendarEvents"] = [
                item for item in candidate.get("calendarEvents", [])
                if item.get("sourceKey") != source_key
            ]
            candidate["caldavAccounts"] = [
                item for item in candidate["caldavAccounts"]
                if item["id"] != account_id
            ]
            self._commit(candidate)
            self._calendar_occurrence_cache.clear()
            return True

    def record_caldav_sync_result(self, account_id: Any, error: Any = "") -> bool:
        if not isinstance(account_id, str) or not account_id:
            return False
        if not isinstance(error, str) or len(error) > 300 or any(
            ord(char) < 32 or ord(char) == 127 for char in error
        ):
            raise PlannerRepositoryError("CalDAV 同步错误状态无效。")
        with self._lock:
            candidate = deepcopy(self._state)
            item = next((
                raw for raw in candidate.get("caldavAccounts", [])
                if raw["id"] == account_id
            ), None)
            if item is None:
                return False
            now = self._now().isoformat(timespec="seconds")
            item["lastSyncAt"] = now
            item["lastSyncError"] = error
            if not error:
                item["lastSyncSuccessAt"] = now
            self._commit(candidate)
            return True

    def sync_caldav_vtodos(
        self,
        account_id: Any,
        resources: Any,
        *,
        complete_snapshot: bool = True,
        removed_resource_hrefs: Any = None,
        sync_token: Any = None,
        sync_collection_unsupported: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(account_id, str) or not account_id:
            raise PlannerRepositoryError("CalDAV 账户 id 无效。")
        if not isinstance(resources, list) or len(resources) > 500:
            raise PlannerRepositoryError("CalDAV 待办快照无效或超过 500 项。")
        if not isinstance(complete_snapshot, bool):
            raise PlannerRepositoryError("CalDAV 快照类型无效。")
        if removed_resource_hrefs is None:
            removed_resource_hrefs = []
        if (
            not isinstance(removed_resource_hrefs, list)
            or len(removed_resource_hrefs) > 1_000
            or any(not isinstance(href, str) or not href or len(href) > 4_096 for href in removed_resource_hrefs)
        ):
            raise PlannerRepositoryError("CalDAV 资源删除列表无效。")
        if sync_token is not None and (
            not isinstance(sync_token, str)
            or len(sync_token.encode("utf-8")) > 4_096
            or any(ord(char) < 32 or ord(char) == 127 for char in sync_token)
        ):
            raise PlannerRepositoryError("CalDAV 同步令牌无效。")
        if sync_collection_unsupported is not None and not isinstance(sync_collection_unsupported, bool):
            raise PlannerRepositoryError("CalDAV 增量同步能力标记无效。")
        with self._lock:
            account = next((
                item for item in self._state.get("caldavAccounts", [])
                if item.get("id") == account_id
            ), None)
            if account is None:
                raise PlannerRepositoryError("CalDAV 账户已移除。")
            account_name = str(account.get("name", "CalDAV"))
            source_key = self._caldav_source_key(account)
            visible_by_uid: dict[str, dict[str, Any]] = {}
            for row in self._visible_records():
                data = row.get("data") if isinstance(row.get("data"), dict) else {}
                external = data.get("externalTodo") if isinstance(data.get("externalTodo"), dict) else {}
                if external.get("provider") == "caldav" and external.get("sourceKey") == source_key:
                    visible_by_uid[str(external.get("uid", ""))] = row

            imported_todos: list[dict[str, Any]] = []
            metadata_by_uid: dict[str, dict[str, Any]] = {}
            writebacks: list[dict[str, Any]] = []
            conflicts = 0
            seen_uids: set[str] = set()
            seen_hrefs: set[str] = set()
            non_todo_hrefs: list[str] = []
            imported_events: list[dict[str, Any]] = []
            unsupported_resources = 0
            removed_event_hrefs: set[str] = set(removed_resource_hrefs)
            for resource in resources:
                if not isinstance(resource, dict):
                    raise PlannerRepositoryError("CalDAV 资源数据无效。")
                todo = resource.get("todo")
                href = resource.get("href")
                etag = resource.get("etag", "")
                calendar_data = resource.get("calendarData")
                if (
                    (todo is not None and not isinstance(todo, dict))
                    or not isinstance(href, str) or not href or len(href) > 4_096
                    or not isinstance(etag, str) or len(etag) > 1_024
                    or not isinstance(calendar_data, str) or len(calendar_data.encode("utf-8")) > 2_000_000
                ):
                    raise PlannerRepositoryError("CalDAV 资源字段无效。")
                unsupported_error = resource.get("unsupportedError", "")
                if (
                    not isinstance(unsupported_error, str)
                    or len(unsupported_error) > 300
                    or any(ord(char) < 32 or ord(char) == 127 for char in unsupported_error)
                ):
                    raise PlannerRepositoryError("CalDAV 不支持资源的说明无效。")
                if unsupported_error:
                    unsupported_resources += 1
                if href in seen_hrefs:
                    raise PlannerRepositoryError("CalDAV 资源地址重复。")
                seen_hrefs.add(href)
                try:
                    _event_calendar_name, resource_events = parse_ics(
                        calendar_data, source_name=account_name, allow_empty=True,
                    )
                except CalendarExchangeError as exc:
                    raise PlannerRepositoryError(str(exc)) from exc
                if resource_events:
                    for event in resource_events:
                        imported_events.append({**event, "resourceHref": href})
                        if len(imported_events) > 500:
                            raise PlannerRepositoryError("一次最多同步 500 个 CalDAV 日程。")
                else:
                    removed_event_hrefs.add(href)
                if todo is None:
                    non_todo_hrefs.append(href)
                    continue
                uid = todo.get("uid")
                if not isinstance(uid, str) or not uid or len(uid) > 512 or uid in seen_uids:
                    raise PlannerRepositoryError("CalDAV 待办 UID 缺失或重复。")
                if not isinstance(todo.get("done"), bool) or not isinstance(todo.get("cancelled"), bool):
                    raise PlannerRepositoryError("CalDAV 完成或取消状态无效。")
                seen_uids.add(uid)
                remote_done = bool(todo["done"])
                imported_todo = deepcopy(todo)
                local = visible_by_uid.get(uid)
                old_external = (
                    local.get("data", {}).get("externalTodo", {})
                    if isinstance(local, dict) and isinstance(local.get("data"), dict)
                    else {}
                )
                local_done = bool(local.get("data", {}).get("done")) if isinstance(local, dict) else remote_done
                baseline = old_external.get("syncedDone")
                if not isinstance(baseline, bool):
                    baseline = local_done if isinstance(local, dict) else remote_done
                local_changed = isinstance(local, dict) and local_done != baseline
                remote_changed = remote_done != baseline
                metadata: dict[str, Any] = {
                    "accountId": account_id,
                    "resourceHref": href,
                    "etag": etag,
                    "remoteDone": remote_done,
                    "syncedDone": remote_done,
                }
                if todo["cancelled"]:
                    # Cancellation is not completion; retain local state and make the task non-actionable.
                    if isinstance(local, dict):
                        imported_todo["done"] = local_done
                        imported_todo["partial"] = bool(local.get("data", {}).get("status") == "doing")
                        imported_todo["completedAt"] = local.get("data", {}).get("completedAt", "")
                    metadata["syncedDone"] = baseline
                elif local_changed and remote_changed and local_done != remote_done:
                    conflicts += 1
                    imported_todo["done"] = local_done
                    imported_todo["partial"] = bool(local.get("data", {}).get("status") == "doing")
                    imported_todo["completedAt"] = local.get("data", {}).get("completedAt", "")
                    metadata.update({
                        "syncedDone": baseline,
                        "syncConflict": True,
                        "conflictRemoteDone": remote_done,
                        "conflictRemoteCompletedAt": todo.get("completedAt", ""),
                    })
                elif local_changed and not remote_changed:
                    imported_todo["done"] = local_done
                    imported_todo["partial"] = bool(local.get("data", {}).get("status") == "doing")
                    imported_todo["completedAt"] = local.get("data", {}).get("completedAt", "")
                    imported_todo["percentComplete"] = 100 if local_done else (25 if imported_todo["partial"] else 0)
                    metadata["syncedDone"] = baseline
                    writebacks.append({
                        "uid": uid,
                        "href": href,
                        "etag": etag,
                        "calendarData": calendar_data,
                        "done": local_done,
                        "recordId": local["id"],
                    })
                imported_todos.append(imported_todo)
                metadata_by_uid[uid] = metadata

            empty_calendar = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
            imported_result = self.import_calendar(
                empty_calendar,
                account_name,
                f"caldav:{account_id}",
                todo_provider="caldav",
                todo_metadata_by_uid=metadata_by_uid,
                parsed_events=imported_events,
                parsed_todos=imported_todos,
                complete_snapshot=complete_snapshot,
                removed_resource_hrefs=list(set(removed_resource_hrefs) | set(non_todo_hrefs)),
                removed_event_resource_hrefs=sorted(removed_event_hrefs),
                caldav_account_id=account_id,
                source_key_override=source_key,
                caldav_sync_token=sync_token,
                caldav_sync_collection_unsupported=sync_collection_unsupported,
            )
            return {
                "import": imported_result,
                "writebacks": writebacks,
                "conflicts": conflicts,
                "resourceCount": len(imported_todos),
                "eventCount": imported_result["total"],
                "unsupportedResourceCount": unsupported_resources,
            }

    def record_caldav_task_writeback(
        self, account_id: Any, uid: Any, done: Any, etag: Any = "",
    ) -> bool:
        if not isinstance(account_id, str) or not account_id or not isinstance(uid, str) or not uid:
            return False
        if not isinstance(done, bool):
            raise PlannerRepositoryError("CalDAV 待办完成状态无效。")
        if not isinstance(etag, str) or len(etag) > 1_024 or any(
            ord(char) < 32 or ord(char) == 127 for char in etag
        ):
            raise PlannerRepositoryError("CalDAV 服务器的 ETag 无效。")
        with self._lock:
            account = next((
                raw for raw in self._state.get("caldavAccounts", [])
                if raw["id"] == account_id
            ), None)
            if account is None:
                return False
            source_key = self._caldav_source_key(account)
            candidate = deepcopy(self._state)
            record = None
            for item in candidate.get("localRecords", []):
                data = item.get("data") if isinstance(item.get("data"), dict) else {}
                external = data.get("externalTodo") if isinstance(data.get("externalTodo"), dict) else {}
                if (
                    external.get("provider") == "caldav"
                    and external.get("sourceKey") == source_key
                    and external.get("uid") == uid
                ):
                    record = item
                    break
            if record is None:
                return False
            external = record["data"]["externalTodo"]
            external["syncedDone"] = done
            external["remoteDone"] = done
            external["etag"] = etag
            external["sourceMissing"] = False
            external["cancelled"] = False
            external.pop("syncConflict", None)
            external.pop("conflictRemoteDone", None)
            external.pop("conflictRemoteCompletedAt", None)
            self._commit(candidate)
            return True

    def resolve_caldav_task_conflict(self, record_id: Any, choice: Any) -> dict[str, Any] | None:
        if choice not in {"remote", "local"}:
            raise PlannerRepositoryError("CalDAV 冲突处理选项无效。")
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return None
            external = target.get("data", {}).get("externalTodo")
            if not isinstance(external, dict) or not external.get("syncConflict"):
                raise PlannerRepositoryError("这项待办当前没有待处理的同步冲突。")
            candidate = deepcopy(self._state)
            record = next((item for item in candidate["localRecords"] if item.get("id") == record_id), None)
            if record is None:
                raise PlannerRepositoryError("CalDAV 待办本机记录不存在。")
            metadata = record.get("data", {}).get("externalTodo", {})
            remote_done = bool(metadata.get("conflictRemoteDone"))
            if choice == "remote":
                changes = candidate["recordOverrides"].setdefault(record_id, {}).setdefault("data", {})
                changes.update({
                    "done": remote_done,
                    "status": "done" if remote_done else "todo",
                    "completedAt": metadata.get("conflictRemoteCompletedAt", "") if remote_done else "",
                })
            metadata["syncedDone"] = remote_done
            metadata["remoteDone"] = remote_done
            metadata.pop("syncConflict", None)
            metadata.pop("conflictRemoteDone", None)
            metadata.pop("conflictRemoteCompletedAt", None)
            self._commit(candidate)
            return self._target(record_id)

    def record_caldav_probe_result(
        self,
        account_id: Any,
        calendars: Any = None,
        error: Any = "",
    ) -> bool:
        if not isinstance(account_id, str) or not account_id:
            return False
        if not isinstance(error, str) or len(error) > 300:
            raise PlannerRepositoryError("CalDAV 错误状态无效。")
        clean_calendars: list[dict[str, Any]] = []
        if not error:
            clean_calendars = _normalize_caldav_accounts([{
                "id": account_id,
                "name": "Probe",
                "host": "probe.example",
                "urlProtected": "probe",
                "credentialsProtected": "probe",
                "calendars": calendars,
            }])[0]["calendars"]
        with self._lock:
            candidate = deepcopy(self._state)
            item = next((
                raw for raw in candidate.get("caldavAccounts", [])
                if raw["id"] == account_id
            ), None)
            if item is None:
                return False
            now = self._now().isoformat(timespec="seconds")
            item["lastCheckedAt"] = now
            item["lastError"] = error
            if not error:
                item["lastSuccessAt"] = now
                item["calendars"] = clean_calendars
            self._commit(candidate)
            return True

    def remove_calendar_subscription(self, subscription_id: Any) -> bool:
        if not isinstance(subscription_id, str) or not subscription_id:
            raise PlannerRepositoryError("日历订阅 id 无效。")
        with self._lock:
            if not any(
                item["id"] == subscription_id
                for item in self._state.get("calendarSubscriptions", [])
            ):
                return False
            candidate = deepcopy(self._state)
            candidate["calendarSubscriptions"] = [
                item for item in candidate["calendarSubscriptions"]
                if item["id"] != subscription_id
            ]
            candidate["calendarEvents"] = [
                item for item in candidate.get("calendarEvents", [])
                if item.get("subscriptionId", "") != subscription_id
            ]
            self._commit(candidate)
            self._calendar_occurrence_cache.clear()
            return True

    def mark_calendar_subscription_error(self, subscription_id: Any, message: Any) -> bool:
        if not isinstance(subscription_id, str) or not subscription_id:
            return False
        if not isinstance(message, str) or not message.strip():
            message = "日历订阅刷新失败。"
        message = "".join(
            char if ord(char) >= 32 and ord(char) != 127 else " "
            for char in message
        ).strip()[:300]
        with self._lock:
            candidate = deepcopy(self._state)
            item = next((
                raw for raw in candidate.get("calendarSubscriptions", [])
                if raw["id"] == subscription_id
            ), None)
            if item is None:
                return False
            item["lastAttemptAt"] = self._now().isoformat(timespec="seconds")
            item["lastError"] = message
            self._commit(candidate)
            return True

    def record_calendar_subscription_not_modified(
        self,
        subscription_id: Any,
        etag: Any = None,
        last_modified: Any = None,
    ) -> bool:
        if not isinstance(subscription_id, str) or not subscription_id:
            return False
        if etag is not None and (
            not isinstance(etag, str) or len(etag) > 1_024
            or any(ord(char) < 32 or ord(char) == 127 for char in etag)
        ):
            raise PlannerRepositoryError("日历服务器的 ETag 无效。")
        if last_modified is not None and (
            not isinstance(last_modified, str) or len(last_modified) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in last_modified)
        ):
            raise PlannerRepositoryError("日历服务器的更新时间无效。")
        with self._lock:
            candidate = deepcopy(self._state)
            item = next((
                raw for raw in candidate.get("calendarSubscriptions", [])
                if raw["id"] == subscription_id
            ), None)
            if item is None:
                return False
            now = self._now().isoformat(timespec="seconds")
            item["lastAttemptAt"] = now
            item["lastSuccessAt"] = now
            item["lastError"] = ""
            if etag is not None:
                item["etag"] = etag
            if last_modified is not None:
                item["lastModified"] = last_modified
            self._commit(candidate)
            return True

    def replace_calendar_subscription_events(
        self,
        subscription_id: Any,
        text: Any,
        etag: Any = "",
        last_modified: Any = "",
    ) -> dict[str, Any]:
        if not isinstance(subscription_id, str) or not subscription_id:
            raise PlannerRepositoryError("日历订阅 id 无效。")
        if (
            not isinstance(etag, str) or len(etag) > 1_024
            or any(ord(char) < 32 or ord(char) == 127 for char in etag)
        ):
            raise PlannerRepositoryError("日历服务器的 ETag 无效。")
        if (
            not isinstance(last_modified, str) or len(last_modified) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in last_modified)
        ):
            raise PlannerRepositoryError("日历服务器的更新时间无效。")
        with self._lock:
            current_subscription = next((
                raw for raw in self._state.get("calendarSubscriptions", [])
                if raw["id"] == subscription_id
            ), None)
            if current_subscription is None:
                raise PlannerRepositoryError("日历订阅已移除。")
            subscription_name = current_subscription["name"]
        try:
            _calendar_name, parsed_events = parse_ics(
                text, source_name=subscription_name, allow_empty=True
            )
            tagged_events: list[dict[str, Any]] = []
            for event in parsed_events:
                source_uid = event["uid"]
                unique_uid = "sub-" + hashlib.sha256(
                    f"{subscription_id}\0{source_uid}".encode("utf-8")
                ).hexdigest()
                tagged_events.append({
                    **event,
                    "id": unique_uid,
                    "uid": unique_uid,
                    "sourceCalendar": subscription_name,
                    "subscriptionId": subscription_id,
                    "sourceEventUid": source_uid,
                })
            imported_events = normalize_calendar_events(tagged_events)
        except CalendarExchangeError as exc:
            raise PlannerRepositoryError(str(exc)) from exc

        with self._lock:
            candidate = deepcopy(self._state)
            subscription = next((
                raw for raw in candidate.get("calendarSubscriptions", [])
                if raw["id"] == subscription_id
            ), None)
            if subscription is None:
                raise PlannerRepositoryError("日历订阅已移除。")
            previous = {
                item["uid"]: item for item in candidate.get("calendarEvents", [])
                if item.get("subscriptionId", "") == subscription_id
            }
            incoming = {item["uid"]: item for item in imported_events}
            added = sum(uid not in previous for uid in incoming)
            updated = sum(uid in previous and previous[uid] != event for uid, event in incoming.items())
            unchanged = sum(uid in previous and previous[uid] == event for uid, event in incoming.items())
            removed = sum(uid not in incoming for uid in previous)
            other_events = [
                item for item in candidate.get("calendarEvents", [])
                if item.get("subscriptionId", "") != subscription_id
            ]
            candidate["calendarEvents"] = normalize_calendar_events([
                *other_events, *imported_events,
            ])
            now = self._now().isoformat(timespec="seconds")
            subscription["etag"] = etag
            subscription["lastModified"] = last_modified
            subscription["lastAttemptAt"] = now
            subscription["lastSuccessAt"] = now
            subscription["lastError"] = ""
            self._commit(candidate)
            if previous != incoming:
                self._calendar_occurrence_cache.clear()
            return {
                "calendarName": subscription_name,
                "added": added,
                "updated": updated,
                "unchanged": unchanged,
                "removed": removed,
                "total": len(imported_events),
            }

    def import_calendar(
        self,
        text: Any,
        source_name: Any = "",
        source_id: Any = "",
        *,
        todo_provider: str = "ical-file",
        todo_metadata_by_uid: dict[str, dict[str, Any]] | None = None,
        parsed_todos: list[dict[str, Any]] | None = None,
        parsed_events: list[dict[str, Any]] | None = None,
        complete_snapshot: bool = True,
        removed_resource_hrefs: list[str] | None = None,
        removed_event_resource_hrefs: list[str] | None = None,
        caldav_account_id: str = "",
        source_key_override: str = "",
        caldav_sync_token: str | None = None,
        caldav_sync_collection_unsupported: bool | None = None,
    ) -> dict[str, Any]:
        if not isinstance(source_name, str):
            source_name = ""
        if not isinstance(source_id, str):
            source_id = ""
        if todo_provider not in {"ical-file", "caldav"}:
            raise PlannerRepositoryError("iCalendar 待办来源类型无效。")
        if not isinstance(complete_snapshot, bool):
            raise PlannerRepositoryError("iCalendar 快照类型无效。")
        if removed_resource_hrefs is None:
            removed_resource_hrefs = []
        if (
            not isinstance(removed_resource_hrefs, list)
            or len(removed_resource_hrefs) > 1_000
            or any(not isinstance(href, str) or not href or len(href) > 4_096 for href in removed_resource_hrefs)
        ):
            raise PlannerRepositoryError("CalDAV 资源删除列表无效。")
        if removed_event_resource_hrefs is None:
            removed_event_resource_hrefs = []
        if (
            not isinstance(removed_event_resource_hrefs, list)
            or len(removed_event_resource_hrefs) > 1_000
            or any(not isinstance(href, str) or not href or len(href) > 4_096 for href in removed_event_resource_hrefs)
        ):
            raise PlannerRepositoryError("CalDAV 日程删除列表无效。")
        if caldav_account_id and (todo_provider != "caldav" or len(caldav_account_id) > 80):
            raise PlannerRepositoryError("CalDAV 账户 id 无效。")
        if caldav_sync_token is not None and (
            not isinstance(caldav_sync_token, str)
            or len(caldav_sync_token.encode("utf-8")) > 4_096
            or any(ord(char) < 32 or ord(char) == 127 for char in caldav_sync_token)
        ):
            raise PlannerRepositoryError("CalDAV 同步令牌无效。")
        if caldav_sync_collection_unsupported is not None and not isinstance(caldav_sync_collection_unsupported, bool):
            raise PlannerRepositoryError("CalDAV 增量同步能力标记无效。")
        if parsed_events is not None and (
            not isinstance(parsed_events, list)
            or len(parsed_events) > 500
            or any(not isinstance(event, dict) for event in parsed_events)
        ):
            raise PlannerRepositoryError("导入的日历事件无效或超过 500 项。")
        try:
            calendar_name, parsed_events_from_text = parse_ics(
                text, source_name=source_name, allow_empty=True,
            )
            imported = deepcopy(parsed_events) if parsed_events is not None else parsed_events_from_text
            if parsed_todos is None:
                _todo_calendar_name, imported_todos = parse_ical_vtodos(
                    text, source_name=source_name,
                )
            else:
                imported_todos = deepcopy(parsed_todos)
        except CalendarExchangeError as exc:
            raise PlannerRepositoryError(str(exc)) from exc
        source_identity = (source_id or source_name).strip().casefold()
        source_key = hashlib.sha256(source_identity.encode("utf-8")).hexdigest()
        if source_key_override:
            if not _CALDAV_SOURCE_KEY_PATTERN.fullmatch(source_key_override):
                raise PlannerRepositoryError("日历来源标识无效。")
            source_key = source_key_override
        with self._lock:
            candidate = deepcopy(self._state)
            if todo_provider == "ical-file":
                imported_todos_uid_set = {
                    str(item.get("uid", "")) for item in imported_todos
                    if isinstance(item.get("uid"), str) and item.get("uid")
                }
                imported_uids = {
                    str(item.get("uid", "")) for item in imported
                } | {
                    *imported_todos_uid_set,
                }
                source_snapshots: dict[str, dict[str, set[str]]] = {}
                for event in candidate.get("calendarEvents", []):
                    key = event.get("sourceKey")
                    uid = event.get("sourceEventUid", event.get("uid", ""))
                    if (
                        isinstance(key, str)
                        and event.get("provider") != "caldav"
                        and isinstance(uid, str)
                        and uid
                    ):
                        snapshot = source_snapshots.setdefault(key, {"uids": set(), "names": set()})
                        snapshot["uids"].add(uid)
                        name = event.get("sourceCalendar")
                        if isinstance(name, str) and name:
                            snapshot["names"].add(name)
                for row in self._visible_records(candidate):
                    data = row.get("data") if isinstance(row.get("data"), dict) else {}
                    external = data.get("externalTodo") if isinstance(data.get("externalTodo"), dict) else {}
                    key, uid = external.get("sourceKey"), external.get("uid")
                    if (
                        external.get("provider") == "ical-file"
                        and isinstance(key, str)
                        and isinstance(uid, str)
                        and uid
                    ):
                        snapshot = source_snapshots.setdefault(key, {"uids": set(), "names": set()})
                        snapshot["uids"].add(uid)
                        name = external.get("sourceName")
                        if isinstance(name, str) and name:
                            snapshot["names"].add(name)
                deleted_todo_ids = {
                    marker.get("id") for marker in candidate.get("deletedRecords", [])
                    if marker.get("type") == "planner" and isinstance(marker.get("id"), str)
                }
                for key, snapshot in source_snapshots.items():
                    for uid in imported_todos_uid_set:
                        deleted_id = "ical-todo-" + hashlib.sha256(
                            f"{key}\0{uid}".encode("utf-8")
                        ).hexdigest()
                        if deleted_id in deleted_todo_ids:
                            snapshot["uids"].add(uid)
                moved_source_candidates = [
                    key for key, snapshot in source_snapshots.items()
                    if calendar_name.casefold() in {
                        name.casefold() for name in snapshot["names"] if name
                    }
                    and snapshot["uids"] == imported_uids
                ]
                if len(moved_source_candidates) == 1:
                    source_key = moved_source_candidates[0]
                elif not moved_source_candidates and imported_uids:
                    # A moved file may change after the first import that
                    # recognizes its new path. When its current UIDs form a
                    # non-empty subset of one uniquely named source snapshot,
                    # keep that source identity so removals update the right
                    # records. Do not guess when multiple calendars overlap.
                    subset_candidates = [
                        key for key, snapshot in source_snapshots.items()
                        if calendar_name.casefold() in {
                            name.casefold() for name in snapshot["names"] if name
                        }
                        and imported_uids.issubset(snapshot["uids"])
                    ]
                    if len(subset_candidates) == 1:
                        source_key = subset_candidates[0]

            tagged_events = []
            for event in imported:
                original_uid = str(event["uid"])
                prefix = "caldav-event-" if todo_provider == "caldav" else "ics-file-"
                scoped_uid = prefix + hashlib.sha256(
                    f"{source_key}\0{original_uid}".encode("utf-8")
                ).hexdigest()
                tagged_event = {
                    **event,
                    "id": scoped_uid,
                    "uid": scoped_uid,
                    "sourceCalendar": calendar_name,
                    "sourceKey": source_key,
                    "sourceEventUid": original_uid,
                }
                if todo_provider == "caldav":
                    tagged_event["provider"] = "caldav"
                tagged_events.append(tagged_event)
            try:
                imported = normalize_calendar_events(tagged_events)
            except CalendarExchangeError as exc:
                raise PlannerRepositoryError(str(exc)) from exc

            current = {item["uid"]: item for item in candidate.get("calendarEvents", [])}
            previous_source = {
                item["uid"]: item for item in current.values()
                if item.get("sourceKey") == source_key
            }
            incoming_source = {item["uid"]: item for item in imported}
            incoming_resource_hrefs = {
                str(event.get("resourceHref")) for event in imported
                if isinstance(event.get("resourceHref"), str) and event.get("resourceHref")
            }
            incoming_resource_hrefs.update(
                str(metadata.get("resourceHref"))
                for metadata in (todo_metadata_by_uid or {}).values()
                if isinstance(metadata, dict)
                and isinstance(metadata.get("resourceHref"), str)
                and metadata.get("resourceHref")
            )
            added = 0
            updated = 0
            unchanged = 0
            for event in imported:
                old = previous_source.get(event["uid"])
                if old is None:
                    added += 1
                elif old == event:
                    unchanged += 1
                else:
                    updated += 1
                current[event["uid"]] = event
            removed = 0
            if complete_snapshot:
                for missing_uid in set(previous_source) - set(incoming_source):
                    current.pop(missing_uid, None)
                    removed += 1
            else:
                removed_hrefs = set(removed_event_resource_hrefs)
                for old_uid, old_event in previous_source.items():
                    resource_href = old_event.get("resourceHref")
                    if (
                        resource_href in removed_hrefs
                        or (resource_href in incoming_resource_hrefs and old_uid not in incoming_source)
                    ):
                        current.pop(old_uid, None)
                        removed += 1

            todo_added = 0
            todo_updated = 0
            todo_unchanged = 0
            todo_cancelled = 0
            incoming_todo_uids = {str(todo.get("uid", "")) for todo in imported_todos}
            now = self._now()
            managed_fields = {
                "title", "note", "priority", "done", "status", "completedAt",
                "time", "plannedDate", "plannedStart", "externalTodo",
            }
            if todo_provider == "caldav":
                # A local timebox is a planner decision. Keep it across CalDAV
                # refreshes even when the remote VTODO has no DTSTART.
                managed_fields.difference_update({"time", "plannedDate", "plannedStart"})
            for todo in imported_todos:
                uid = todo.get("uid")
                if not isinstance(uid, str) or not uid or len(uid) > 512:
                    raise PlannerRepositoryError("iCalendar 待办缺少有效 UID。")
                extra_metadata = (todo_metadata_by_uid or {}).get(uid, {})
                if not isinstance(extra_metadata, dict):
                    raise PlannerRepositoryError("iCalendar 来源信息无效。")
                allowed_metadata = {
                    "accountId", "resourceHref", "etag", "syncedDone", "remoteDone",
                    "syncConflict", "conflictRemoteDone", "conflictRemoteCompletedAt",
                }
                external_extra = {
                    key: deepcopy(value) for key, value in extra_metadata.items()
                    if key in allowed_metadata
                }
                for key in ("syncedDone", "remoteDone", "syncConflict", "conflictRemoteDone"):
                    if key in external_extra and not isinstance(external_extra[key], bool):
                        raise PlannerRepositoryError("CalDAV 完成状态无效。")
                if "resourceHref" in external_extra and (
                    not isinstance(external_extra["resourceHref"], str)
                    or len(external_extra["resourceHref"]) > 4_096
                ):
                    raise PlannerRepositoryError("CalDAV 资源地址无效。")
                if "etag" in external_extra and (
                    not isinstance(external_extra["etag"], str)
                    or len(external_extra["etag"]) > 1_024
                ):
                    raise PlannerRepositoryError("CalDAV ETag 无效。")
                if "accountId" in external_extra and (
                    not isinstance(external_extra["accountId"], str)
                    or len(external_extra["accountId"]) > 80
                ):
                    raise PlannerRepositoryError("CalDAV 账户 id 无效。")
                if "conflictRemoteCompletedAt" in external_extra and (
                    not isinstance(external_extra["conflictRemoteCompletedAt"], str)
                    or len(external_extra["conflictRemoteCompletedAt"]) > 64
                ):
                    raise PlannerRepositoryError("CalDAV 远端完成时间无效。")
                record_id = "ical-todo-" + hashlib.sha256(
                    f"{source_key}\0{uid}".encode("utf-8")
                ).hexdigest()
                if todo["cancelled"]:
                    todo_cancelled += 1
                    cancelled_record = next((
                        row for row in candidate["localRecords"]
                        if row.get("id") == record_id
                    ), None)
                    if cancelled_record is not None:
                        metadata = cancelled_record.get("data", {}).get("externalTodo", {})
                        if metadata.get("sourceKey") == source_key:
                            changed_metadata = (
                                not metadata.get("cancelled")
                                or metadata.get("sourceMissing")
                                or any(metadata.get(key) != value for key, value in external_extra.items())
                            )
                            metadata["cancelled"] = True
                            metadata["sourceMissing"] = False
                            metadata.update(external_extra)
                            if changed_metadata:
                                todo_updated += 1
                    continue
                if any(
                    marker.get("type") == "planner" and marker.get("id") == record_id
                    for marker in candidate.get("deletedRecords", [])
                ):
                    # Respect an explicit local deletion across repeat imports.
                    todo_unchanged += 1
                    continue
                status = "done" if todo["done"] else "doing" if todo["partial"] else "todo"
                due_day = todo["dueDate"]
                start_day = todo["startDate"]
                record_day = due_day or start_day or now.date().isoformat()
                external_todo = {
                    "provider": todo_provider,
                    "sourceKey": source_key,
                    "sourceName": calendar_name[:160],
                    "uid": uid,
                    "cancelled": False,
                    "sourceMissing": False,
                    "dueDate": due_day,
                    "dueTime": todo["dueTime"],
                    "url": todo["url"],
                    "percentComplete": todo["percentComplete"],
                    **external_extra,
                }
                incoming_data = {
                    "title": todo["title"],
                    "note": todo["description"],
                    "priority": todo["priority"],
                    "done": todo["done"],
                    "status": status,
                    "completedAt": todo["completedAt"],
                    "time": todo["startTime"],
                    "plannedDate": start_day if todo["startTime"] else "",
                    "plannedStart": todo["startTime"],
                    "externalTodo": external_todo,
                }
                raw_record = next((
                    row for row in candidate["localRecords"]
                    if row.get("id") == record_id
                ), None)
                if raw_record is None:
                    local_record = {
                        "id": record_id,
                        "type": "planner",
                        "date": record_day,
                        "createdAt": int(now.timestamp() * 1000),
                        "sample": False,
                        "data": {
                            **incoming_data,
                            "time": todo["startTime"],
                            "list": "生活",
                            "remind": False,
                            "estimateMinutes": 30,
                            "trackedSeconds": 0,
                            "sessions": [],
                            "repeat": "none",
                            "repeatDayOfMonth": 0,
                            "repeatSeriesId": "",
                        },
                    }
                    candidate["localRecords"].append(local_record)
                    todo_added += 1
                    continue

                visible_record = self._target(record_id, candidate) or raw_record
                visible_data = visible_record.get("data", {})
                overrides = candidate["recordOverrides"].get(record_id, {})
                data_overrides = overrides.get("data", {}) if isinstance(overrides, dict) else {}
                local_schedule_fields = (
                    {"time", "plannedDate", "plannedStart"} & set(data_overrides)
                    if todo_provider == "caldav" and isinstance(data_overrides, dict)
                    else set()
                )
                changed = (
                    visible_record.get("date") != record_day
                    or any(
                        key not in local_schedule_fields and visible_data.get(key) != value
                        for key, value in incoming_data.items()
                    )
                )
                if not changed:
                    todo_unchanged += 1
                    continue
                raw_record["date"] = record_day
                raw_record["data"].update(incoming_data)
                overrides = candidate["recordOverrides"].get(record_id, {})
                data_overrides = overrides.get("data", {}) if isinstance(overrides, dict) else {}
                if isinstance(data_overrides, dict):
                    for key in managed_fields:
                        data_overrides.pop(key, None)
                    if not data_overrides:
                        overrides.pop("data", None)
                    if not overrides:
                        candidate["recordOverrides"].pop(record_id, None)
                todo_updated += 1

            removed_todos = 0
            removed_hrefs = set(removed_resource_hrefs)
            replaced_hrefs = incoming_resource_hrefs
            for row in candidate.get("localRecords", []):
                data = row.get("data") if isinstance(row.get("data"), dict) else {}
                external = data.get("externalTodo") if isinstance(data.get("externalTodo"), dict) else None
                if not external or external.get("provider") != todo_provider or external.get("sourceKey") != source_key:
                    continue
                is_missing = (
                    external.get("uid") not in incoming_todo_uids
                    if complete_snapshot
                    else (
                        external.get("resourceHref") in removed_hrefs
                        or (
                            external.get("resourceHref") in replaced_hrefs
                            and external.get("uid") not in incoming_todo_uids
                        )
                    )
                )
                if is_missing and not external.get("sourceMissing"):
                    external["sourceMissing"] = True
                    removed_todos += 1
            todo_updated += removed_todos

            sync_state_changed = False
            if caldav_account_id:
                account = next((
                    item for item in candidate.get("caldavAccounts", [])
                    if item.get("id") == caldav_account_id
                ), None)
                if account is None:
                    raise PlannerRepositoryError("CalDAV 账户已移除。")
                if caldav_sync_token is not None and account.get("syncToken", "") != caldav_sync_token:
                    account["syncToken"] = caldav_sync_token
                    sync_state_changed = True
                if (
                    caldav_sync_collection_unsupported is not None
                    and account.get("syncCollectionUnsupported", False) != caldav_sync_collection_unsupported
                ):
                    account["syncCollectionUnsupported"] = caldav_sync_collection_unsupported
                    sync_state_changed = True

            if added or updated or removed or todo_added or todo_updated or sync_state_changed:
                try:
                    candidate["calendarEvents"] = normalize_calendar_events(list(current.values()))
                except CalendarExchangeError as exc:
                    raise PlannerRepositoryError(str(exc)) from exc
                self._commit(candidate)
                self._calendar_occurrence_cache.clear()
            return {
                "calendarName": calendar_name,
                "added": added,
                "updated": updated,
                "unchanged": unchanged,
                "removed": removed,
                "total": len(imported),
                "tasks": {
                    "added": todo_added,
                    "updated": todo_updated,
                    "unchanged": todo_unchanged,
                    "cancelled": todo_cancelled,
                    "sourceMissing": removed_todos,
                    "total": len(imported_todos),
                },
            }

    def export_calendar_ics(self, target_path: str | Path, start_date: Any, end_date: Any) -> Path:
        try:
            payload = task_events_to_ics(self.records(), start_date, end_date, self._now())
            return write_ics_file(target_path, payload)
        except CalendarExchangeError as exc:
            raise PlannerRepositoryError(str(exc)) from exc

    def save_draft(self, draft: Any) -> dict[str, Any]:
        if not isinstance(draft, dict):
            raise PlannerRepositoryError("日程草稿必须是对象。")
        cloned = _json_copy(draft, "日程草稿")
        with self._lock:
            candidate = deepcopy(self._state)
            candidate["draft"] = cloned
            candidate["draftOverridden"] = True
            self._commit(candidate)
            return _json_copy(self._state["draft"], "日程草稿")

    def clear_draft(self) -> None:
        with self._lock:
            candidate = deepcopy(self._state)
            candidate["draft"] = {}
            candidate["draftOverridden"] = True
            self._commit(candidate)

    def add_task(
        self,
        title: Any,
        date: Any,
        time: Any = "",
        priority: Any = "normal",
        list_name: Any = "生活",
        note: Any = "",
        remind: Any = False,
        estimate_minutes: Any = 30,
        repeat: Any = "none",
        project: Any = "",
        tags: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(title, str) or not title.strip():
            raise PlannerRepositoryError("待办标题不能为空。")
        title = title.strip()
        if len(title) > 60:
            raise PlannerRepositoryError("待办标题最多 60 个字符。")
        date_value = _valid_date(date)
        if time is None:
            time = ""
        if not isinstance(time, str) or (time and not _TIME_PATTERN.fullmatch(time)):
            raise PlannerRepositoryError("时间必须是有效的 HH:MM 格式，或留空。")
        if not isinstance(priority, str) or priority not in _PRIORITIES:
            raise PlannerRepositoryError("优先级无效。")
        if not isinstance(list_name, str) or list_name not in _LISTS:
            raise PlannerRepositoryError("清单无效。")
        if not isinstance(note, str):
            raise PlannerRepositoryError("备注必须是文本。")
        note = note.strip()
        if len(note) > 100:
            raise PlannerRepositoryError("备注最多 100 个字符。")
        if not isinstance(remind, bool):
            raise PlannerRepositoryError("提醒开关必须是布尔值。")
        if isinstance(estimate_minutes, bool) or not isinstance(estimate_minutes, int) or not 5 <= estimate_minutes <= 480 or estimate_minutes % 5:
            raise PlannerRepositoryError("预计用时须为 5 至 480 分钟之间的 5 分钟倍数。")
        if not isinstance(repeat, str) or repeat not in _REPEATS:
            raise PlannerRepositoryError("重复周期无效。")
        project_value = _normalize_project(project)
        tag_values = _normalize_tags(tags)
        now = self._now()
        data = {
            "title": title,
            "time": time,
            "priority": priority,
            "list": list_name,
            "note": note,
            "remind": remind,
            "done": False,
            "estimateMinutes": estimate_minutes,
            "plannedDate": date_value if time else "",
            "plannedStart": time,
            "trackedSeconds": 0,
            "sessions": [],
            "repeat": repeat,
            "repeatDayOfMonth": datetime.fromisoformat(date_value).day if repeat == "monthly" else 0,
            "repeatSeriesId": str(uuid4()) if repeat != "none" else "",
        }
        if project_value:
            data["project"] = project_value
        if tag_values:
            data["tags"] = tag_values
        task = {
            "id": str(uuid4()),
            "type": "planner",
            "date": date_value,
            "createdAt": int(now.timestamp() * 1000),
            "sample": False,
            "data": data,
        }
        with self._lock:
            candidate = deepcopy(self._state)
            candidate["localRecords"].append(task)
            self._commit(candidate)
            return _json_copy(task, "新建日程")

    def update_task(
        self,
        record_id: Any,
        title: Any,
        date: Any,
        time: Any,
        priority: Any,
        list_name: Any,
        note: Any,
        remind: Any,
        estimate_minutes: Any,
        repeat: Any,
        project: Any,
        tags: Any,
    ) -> dict[str, Any] | None:
        """Replace editable task fields while preserving all other record data."""
        if not isinstance(title, str) or not title.strip():
            raise PlannerRepositoryError("待办标题不能为空。")
        title_value = title.strip()
        if len(title_value) > 60:
            raise PlannerRepositoryError("待办标题最多 60 个字符。")
        date_value = _valid_date(date)
        if time is None:
            time = ""
        if not isinstance(time, str) or (time and not _TIME_PATTERN.fullmatch(time)):
            raise PlannerRepositoryError("时间必须是有效的 HH:MM 格式，或留空。")
        if not isinstance(priority, str) or priority not in _PRIORITIES:
            raise PlannerRepositoryError("优先级无效。")
        if not isinstance(list_name, str) or list_name not in _LISTS:
            raise PlannerRepositoryError("清单无效。")
        if not isinstance(note, str):
            raise PlannerRepositoryError("备注必须是文本。")
        note_value = note.strip()
        if len(note_value) > 100:
            raise PlannerRepositoryError("备注最多 100 个字符。")
        if not isinstance(remind, bool):
            raise PlannerRepositoryError("提醒开关必须是布尔值。")
        if (
            isinstance(estimate_minutes, bool)
            or not isinstance(estimate_minutes, int)
            or not 5 <= estimate_minutes <= 480
            or estimate_minutes % 5
        ):
            raise PlannerRepositoryError("预计用时须为 5 至 480 分钟之间的 5 分钟倍数。")
        if not isinstance(repeat, str) or repeat not in _REPEATS:
            raise PlannerRepositoryError("重复周期无效。")
        project_value = _normalize_project(project)
        tag_values = _normalize_tags(tags)

        if not isinstance(record_id, str) or not record_id:
            raise PlannerRepositoryError("日程 id 无效。")
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return None
            if target.get("sample"):
                raise PlannerRepositoryError("样例日程不能编辑。")
            old_data = target.get("data") if isinstance(target.get("data"), dict) else {}
            external_todo = old_data.get("externalTodo")
            if isinstance(external_todo, dict) and external_todo.get("cancelled"):
                raise PlannerRepositoryError("来源已取消的任务不能修改。")

            previous_signature = (
                target.get("date"),
                old_data.get("time", ""),
                bool(old_data.get("remind")),
            )
            next_signature = (date_value, time, remind)

            previous_repeat = old_data.get("repeat", "none")
            if repeat == "none":
                repeat_day_of_month = 0
                repeat_series_id = ""
            else:
                old_series_id = old_data.get("repeatSeriesId")
                repeat_series_id = (
                    old_series_id
                    if previous_repeat == repeat and isinstance(old_series_id, str) and old_series_id
                    else str(uuid4())
                )
                if repeat != "monthly":
                    repeat_day_of_month = 0
                else:
                    old_anchor = old_data.get("repeatDayOfMonth")
                    preserve_anchor = (
                        previous_repeat == repeat
                        and target.get("date") == date_value
                        and isinstance(old_anchor, int)
                        and not isinstance(old_anchor, bool)
                        and 1 <= old_anchor <= 31
                    )
                    repeat_day_of_month = old_anchor if preserve_anchor else int(date_value[8:10])

            data_changes: dict[str, Any] = {
                "title": title_value,
                "time": time,
                "priority": priority,
                "list": list_name,
                "note": note_value,
                "remind": remind,
                "estimateMinutes": estimate_minutes,
                "plannedDate": date_value if time else "",
                "plannedStart": time,
                "repeat": repeat,
                "repeatDayOfMonth": repeat_day_of_month,
                "repeatSeriesId": repeat_series_id,
                "project": project_value,
                "tags": tag_values,
            }
            candidate = deepcopy(self._state)
            changes = candidate["recordOverrides"].setdefault(record_id, {})
            changes["date"] = date_value
            changes.setdefault("data", {}).update(data_changes)
            if previous_signature != next_signature:
                self._clear_reminder_receipt(candidate, record_id)
            self._commit(candidate)
            return self._target(record_id)

    def set_task_organization(
        self, record_id: Any, project: Any, tags: Any
    ) -> dict[str, Any] | None:
        project_value = _normalize_project(project)
        tag_values = _normalize_tags(tags)
        if not isinstance(record_id, str) or not record_id:
            raise PlannerRepositoryError("待办 id 无效。")
        with self._lock:
            if self._target(record_id) is None:
                return None
            candidate = deepcopy(self._state)
            changes = candidate["recordOverrides"].setdefault(record_id, {}).setdefault("data", {})
            changes["project"] = project_value
            changes["tags"] = tag_values
            self._commit(candidate)
            return self._target(record_id)

    def set_task_status(self, record_id: Any, status: Any) -> dict[str, Any] | None:
        if not isinstance(status, str) or status not in _TASK_STATUSES:
            raise PlannerRepositoryError("任务状态无效。")
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return None
            external_todo = target["data"].get("externalTodo")
            if isinstance(external_todo, dict) and external_todo.get("cancelled"):
                raise PlannerRepositoryError("来源已取消的任务不能修改状态。")
            current_done = bool(target["data"].get("done"))
            if current_done == (status == "done") and target["data"].get("status") == status:
                return target
            active = self._state.get("activeTracking")
            if isinstance(active, dict) and active.get("taskId") == record_id and status != "doing":
                raise PlannerRepositoryError("请先结束这项任务的计时，再更改它的状态。")
            if status == "done":
                pending_children = [
                    row for row in self._visible_records()
                    if (row.get("data") or {}).get("parentTaskId") == record_id
                    and not (row.get("data") or {}).get("done")
                ]
                if pending_children:
                    raise PlannerRepositoryError("请先完成全部子任务，再完成这项任务。")

            candidate = deepcopy(self._state)
            changes = candidate["recordOverrides"].setdefault(str(record_id), {}).setdefault("data", {})
            changes["status"] = status
            changes["done"] = status == "done"
            changes["completedAt"] = self._now().isoformat(timespec="seconds") if status == "done" else ""
            if current_done and status != "done":
                self._clear_reminder_receipt(candidate, str(record_id))
            if status == "done":
                self._create_next_repeat(candidate, target, self._now())
            self._commit(candidate)
            return self._target(record_id)

    def add_subtask(self, parent_id: Any, title: Any) -> dict[str, Any] | None:
        if not isinstance(parent_id, str) or not parent_id:
            raise PlannerRepositoryError("父任务 id 无效。")
        if not isinstance(title, str) or not title.strip():
            raise PlannerRepositoryError("子任务标题不能为空。")
        title_value = title.strip()
        if len(title_value) > 60:
            raise PlannerRepositoryError("子任务标题最多 60 个字符。")

        with self._lock:
            parent = self._target(parent_id)
            if parent is None:
                return None
            parent_data = parent.get("data") if isinstance(parent.get("data"), dict) else {}
            if parent_data.get("parentTaskId"):
                raise PlannerRepositoryError("目前只支持一层子任务，请在上级任务下新建。")
            if parent_data.get("done"):
                raise PlannerRepositoryError("已完成的任务不能添加子任务。")
            children = [
                row for row in self._visible_records()
                if (row.get("data") or {}).get("parentTaskId") == parent_id
            ]
            if len(children) >= 50:
                raise PlannerRepositoryError("每项任务最多添加 50 个子任务。")

            project_value = _normalize_project(parent_data.get("project", ""))
            raw_tags = parent_data.get("tags", [])
            tag_values = _normalize_tags(raw_tags if isinstance(raw_tags, list) else [])
            parent_list = parent_data.get("list", "生活")
            if parent_list not in _LISTS:
                parent_list = "生活"
            parent_priority = parent_data.get("priority", "normal")
            if parent_priority not in _PRIORITIES:
                parent_priority = "normal"
            task_data: dict[str, Any] = {
                "title": title_value,
                "time": "",
                "priority": parent_priority,
                "list": parent_list,
                "note": "",
                "remind": False,
                "done": False,
                "estimateMinutes": 15,
                "plannedDate": "",
                "plannedStart": "",
                "trackedSeconds": 0,
                "sessions": [],
                "repeat": "none",
                "repeatDayOfMonth": 0,
                "repeatSeriesId": "",
                "parentTaskId": parent_id,
            }
            if project_value:
                task_data["project"] = project_value
            if tag_values:
                task_data["tags"] = tag_values
            now = self._now()
            child = {
                "id": str(uuid4()),
                "type": "planner",
                "date": _valid_date(parent.get("date")),
                "createdAt": int(now.timestamp() * 1000),
                "sample": False,
                "data": task_data,
            }
            candidate = deepcopy(self._state)
            candidate["localRecords"].append(child)
            self._commit(candidate)
            return self._target(child["id"])

    def schedule_task(self, record_id: Any, day: Any, start_time: Any, duration_minutes: Any) -> dict[str, Any] | None:
        selected_day = _valid_date(day, "排程日期")
        if not isinstance(start_time, str) or not _TIME_PATTERN.fullmatch(start_time):
            raise PlannerRepositoryError("排程开始时间须为有效的 HH:MM 格式。")
        if isinstance(duration_minutes, bool) or not isinstance(duration_minutes, int) or not 5 <= duration_minutes <= 480 or duration_minutes % 5:
            raise PlannerRepositoryError("任务时长须为 5 至 480 分钟之间的 5 分钟倍数。")
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return None
            if target["data"].get("done"):
                raise PlannerRepositoryError("已完成的事项不能加入时间安排。")
            external_todo = target["data"].get("externalTodo")
            if isinstance(external_todo, dict) and external_todo.get("cancelled"):
                raise PlannerRepositoryError("来源已取消的任务不能加入时间安排。")
            previous_time = self._reminder_time(target)
            candidate = deepcopy(self._state)
            changes = candidate["recordOverrides"].setdefault(str(record_id), {}).setdefault("data", {})
            changes.update({
                "plannedDate": selected_day,
                "plannedStart": start_time,
                "estimateMinutes": duration_minutes,
            })
            updated = self._target(record_id, candidate)
            next_time = self._reminder_time(updated) if updated is not None else None
            if previous_time != next_time:
                self._clear_reminder_receipt(candidate, str(record_id))
            self._commit(candidate)
            return self._target(record_id)

    def unschedule_task(self, record_id: Any) -> dict[str, Any] | None:
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return None
            previous_time = self._reminder_time(target)
            candidate = deepcopy(self._state)
            changes = candidate["recordOverrides"].setdefault(str(record_id), {}).setdefault("data", {})
            changes["plannedDate"] = ""
            changes["plannedStart"] = ""
            changes["time"] = ""
            updated = self._target(record_id, candidate)
            next_time = self._reminder_time(updated) if updated is not None else None
            if previous_time != next_time:
                self._clear_reminder_receipt(candidate, str(record_id))
            self._commit(candidate)
            return self._target(record_id)

    def set_task_reminder(self, record_id: Any, remind: Any) -> dict[str, Any] | None:
        """Toggle a task reminder and clear a receipt when its opt-in changes."""
        if not isinstance(remind, bool):
            raise PlannerRepositoryError("提醒开关必须是布尔值。")
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return None
            if bool(target["data"].get("remind")) == remind:
                return target
            candidate = deepcopy(self._state)
            changes = candidate["recordOverrides"].setdefault(str(record_id), {}).setdefault("data", {})
            changes["remind"] = remind
            self._clear_reminder_receipt(candidate, str(record_id))
            self._commit(candidate)
            return self._target(record_id)

    def set_estimate(self, record_id: Any, duration_minutes: Any) -> dict[str, Any] | None:
        if isinstance(duration_minutes, bool) or not isinstance(duration_minutes, int) or not 5 <= duration_minutes <= 480 or duration_minutes % 5:
            raise PlannerRepositoryError("预计用时须为 5 至 480 分钟之间的 5 分钟倍数。")
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return None
            candidate = deepcopy(self._state)
            changes = candidate["recordOverrides"].setdefault(str(record_id), {}).setdefault("data", {})
            changes["estimateMinutes"] = duration_minutes
            self._commit(candidate)
            return self._target(record_id)

    @staticmethod
    def _session_day_slices(
        started_at: Any, ended_at: Any, seconds: int,
    ) -> list[tuple[str, int, str, str]]:
        try:
            started = datetime.fromisoformat(started_at)
            ended = datetime.fromisoformat(ended_at)
        except (TypeError, ValueError):
            return []
        started_local = started.astimezone()
        ended_local = ended.astimezone()
        started_utc = started_local.astimezone(timezone.utc)
        ended_utc = ended_local.astimezone(timezone.utc)
        if ended_utc <= started_utc:
            return [(started_local.date().isoformat(), seconds, started_local.isoformat(timespec="seconds"), ended_local.isoformat(timespec="seconds"))]
        duration = (ended_utc - started_utc).total_seconds()
        slices: list[tuple[str, float, datetime, datetime]] = []
        cursor = started_utc
        while cursor < ended_utc:
            local_cursor = cursor.astimezone()
            next_local_day = local_cursor.date() + timedelta(days=1)
            boundary_utc = datetime.combine(next_local_day, time.min).astimezone(timezone.utc)
            next_cursor = min(ended_utc, boundary_utc)
            if next_cursor <= cursor:
                next_cursor = min(ended_utc, cursor + timedelta(hours=1))
            slices.append((
                local_cursor.date().isoformat(),
                (next_cursor - cursor).total_seconds(),
                cursor.astimezone().isoformat(timespec="seconds"),
                next_cursor.astimezone().isoformat(timespec="seconds"),
            ))
            cursor = next_cursor
        result: list[tuple[str, int, str, str]] = []
        remaining = seconds
        for index, (day_key, overlap, piece_start, piece_end) in enumerate(slices):
            allocation = remaining if index == len(slices) - 1 else min(
                remaining, max(0, int(round(seconds * overlap / duration)))
            )
            remaining -= allocation
            if allocation:
                result.append((day_key, allocation, piece_start, piece_end))
        return result

    def timesheet(self, start_date: Any, end_date: Any) -> dict[str, Any]:
        start_key = _valid_date(start_date, "报表开始日期")
        end_key = _valid_date(end_date, "报表结束日期")
        start = date.fromisoformat(start_key)
        end = date.fromisoformat(end_key)
        if start > end:
            raise PlannerRepositoryError("报表开始日期不能晚于结束日期。")
        if (end - start).days > 365:
            raise PlannerRepositoryError("一次最多查看连续 366 天的工时。")
        with self._lock:
            rows = self._sort_records(self._visible_records())
            now = self._now()
            active = deepcopy(self._state.get("activeTracking"))

        entries: list[dict[str, Any]] = []
        summaries: dict[str, dict[str, Any]] = {}
        day_values: dict[str, dict[str, int]] = {}
        task_session_ids: dict[str, set[str]] = {}
        day_session_ids: dict[str, set[str]] = {}
        all_session_ids: set[str] = set()
        session_actuals: dict[str, int] = {}
        record_lookup = {str(row.get("id", "")): row for row in rows}

        def report_summary(row: dict[str, Any]) -> dict[str, Any]:
            record_id = str(row.get("id", ""))
            if record_id not in summaries:
                data = row.get("data") if isinstance(row.get("data"), dict) else {}
                project = str(data.get("project", "")).strip()
                tags = [tag.strip() for tag in data.get("tags", []) if isinstance(tag, str) and tag.strip()] \
                    if isinstance(data.get("tags", []), list) else []
                try:
                    estimate = int(data.get("estimateMinutes", 0)) * 60
                except (TypeError, ValueError):
                    estimate = 0
                planned_day = str(data.get("plannedDate", "") or row.get("date", ""))
                estimate_seconds = estimate if start_key <= planned_day <= end_key else 0
                summaries[record_id] = {
                    "taskId": record_id,
                    "title": str(data.get("title", "未命名待办")),
                    "project": project,
                    "tags": tags,
                    "estimatedSeconds": max(0, estimate_seconds),
                    "actualSeconds": 0,
                    "sessionCount": 0,
                }
            return summaries[record_id]

        def add_entry(
            row: dict[str, Any], day_key: str, seconds: int, started_at: str, ended_at: str,
            mode: str, source: str, session_id: str,
        ) -> None:
            if not start_key <= day_key <= end_key or seconds <= 0:
                return
            info = report_summary(row)
            entry = {
                "date": day_key,
                "taskId": info["taskId"],
                "title": info["title"],
                "project": info["project"],
                "tags": list(info["tags"]),
                "startedAt": started_at,
                "endedAt": ended_at,
                "seconds": seconds,
                "mode": mode,
                "source": source,
                "sessionId": session_id,
            }
            entries.append(entry)
            info["actualSeconds"] += seconds
            session_actuals[session_id] = session_actuals.get(session_id, 0) + seconds
            daily = day_values.setdefault(day_key, {"actualSeconds": 0, "estimatedSeconds": 0, "sessionCount": 0})
            daily["actualSeconds"] += seconds
            task_ids = task_session_ids.setdefault(info["taskId"], set())
            if session_id not in task_ids:
                task_ids.add(session_id)
                info["sessionCount"] += 1
            day_ids = day_session_ids.setdefault(day_key, set())
            if session_id not in day_ids:
                day_ids.add(session_id)
                daily["sessionCount"] += 1
            all_session_ids.add(session_id)

        for row in rows:
            record_id = str(row.get("id", ""))
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            info = report_summary(row)
            if info["estimatedSeconds"]:
                planned_day = str(data.get("plannedDate", "") or row.get("date", ""))
                day_values.setdefault(planned_day, {"actualSeconds": 0, "estimatedSeconds": 0, "sessionCount": 0})[
                    "estimatedSeconds"
                ] += info["estimatedSeconds"]
            raw_sessions = data.get("sessions", [])
            if not isinstance(raw_sessions, list):
                raw_sessions = []
            valid_total = 0
            for session_index, session in enumerate(raw_sessions):
                if not isinstance(session, dict):
                    continue
                seconds = session.get("seconds", 0)
                if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
                    continue
                started_at, ended_at = session.get("startedAt", ""), session.get("endedAt", "")
                if seconds == 0 and isinstance(started_at, str) and isinstance(ended_at, str):
                    try:
                        seconds = max(0, int((datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds()))
                    except (TypeError, ValueError):
                        seconds = 0
                if seconds <= 0:
                    continue
                slices = self._session_day_slices(started_at, ended_at, seconds)
                if not slices:
                    continue
                valid_total += seconds
                for day_key, allocated, piece_start, piece_end in slices:
                    add_entry(
                        row, day_key, allocated, piece_start, piece_end,
                        str(session.get("mode", "stopwatch")), "session",
                        str(session.get("sessionId", "") or f"{record_id}:{session_index}"),
                    )

            stored_actual = data.get("trackedSeconds", 0)
            if isinstance(stored_actual, int) and not isinstance(stored_actual, bool) and stored_actual > valid_total:
                missing = stored_actual - valid_total
                legacy_day = str(data.get("lastTrackedDate", "") or row.get("date", ""))
                try:
                    _valid_date(legacy_day, "历史工时日期")
                except PlannerRepositoryError:
                    try:
                        legacy_day = _valid_date(str(row.get("date", "")), "历史工时日期")
                    except PlannerRepositoryError:
                        legacy_day = ""
                if legacy_day and start_key <= legacy_day <= end_key:
                    add_entry(row, legacy_day, missing, "", "", "legacy", "历史汇总", f"{record_id}:legacy")

        if isinstance(active, dict) and not active.get("paused", False):
            record_id = str(active.get("taskId", ""))
            row = record_lookup.get(record_id)
            if row is not None:
                try:
                    checkpoint = datetime.fromisoformat(active["checkpointAt"])
                    elapsed_now = now
                    if elapsed_now.tzinfo is None and checkpoint.tzinfo is not None:
                        elapsed_now = elapsed_now.replace(tzinfo=checkpoint.tzinfo)
                    elif elapsed_now.tzinfo is not None and checkpoint.tzinfo is None:
                        checkpoint = checkpoint.replace(tzinfo=elapsed_now.tzinfo)
                    elapsed = int(active.get("accumulatedSeconds", 0)) + max(0, int((elapsed_now - checkpoint).total_seconds()))
                except (KeyError, TypeError, ValueError):
                    elapsed = 0
                target_seconds = int(active.get("targetSeconds", 0) or 0)
                if target_seconds:
                    elapsed = min(elapsed, target_seconds)
                unlogged = max(0, elapsed - int(active.get("sessionLoggedSeconds", 0) or 0))
                if unlogged:
                    segment_start = str(active.get("segmentStartedAt", active.get("startedAt", "")))
                    now_iso = now.isoformat(timespec="seconds")
                    for day_key, allocated, piece_start, piece_end in self._session_day_slices(
                        segment_start, now_iso, unlogged,
                    ):
                        add_entry(
                            row, day_key, allocated, piece_start, piece_end,
                            str(active.get("mode", "stopwatch")), "当前计时",
                            str(active.get("sessionId", "") or f"active:{record_id}:{segment_start}"),
                        )

        tasks = [item for item in summaries.values() if item["actualSeconds"] or item["estimatedSeconds"]]
        tasks.sort(key=lambda item: (item["project"].casefold(), item["title"].casefold(), item["taskId"]))
        project_values: dict[str, dict[str, Any]] = {}
        tag_values: dict[str, dict[str, Any]] = {}
        for item in tasks:
            project = item["project"] or "未归入项目"
            aggregate = project_values.setdefault(project, {"name": project, "actualSeconds": 0, "estimatedSeconds": 0, "taskCount": 0})
            aggregate["actualSeconds"] += item["actualSeconds"]
            aggregate["estimatedSeconds"] += item["estimatedSeconds"]
            aggregate["taskCount"] += 1
            for tag in item["tags"]:
                tagged = tag_values.setdefault(tag, {"name": tag, "actualSeconds": 0, "estimatedSeconds": 0, "taskCount": 0})
                tagged["actualSeconds"] += item["actualSeconds"]
                tagged["estimatedSeconds"] += item["estimatedSeconds"]
                tagged["taskCount"] += 1

        days = []
        current = start
        while current <= end:
            day_key = current.isoformat()
            values = day_values.get(day_key, {"actualSeconds": 0, "estimatedSeconds": 0, "sessionCount": 0})
            days.append({"date": day_key, **values})
            current += timedelta(days=1)
        entries.sort(key=lambda item: (item["date"], item["startedAt"], item["taskId"]))
        totals = {
            "actualSeconds": sum(item["actualSeconds"] for item in tasks),
            "estimatedSeconds": sum(item["estimatedSeconds"] for item in tasks),
            "sessionCount": len(all_session_ids),
        }
        totals["varianceSeconds"] = totals["actualSeconds"] - totals["estimatedSeconds"]
        active_days = sum(1 for item in days if item["actualSeconds"] > 0)
        totals["activeDays"] = active_days
        totals["averageFocusSecondsPerActiveDay"] = (
            int(round(totals["actualSeconds"] / active_days)) if active_days else 0
        )
        totals["longestSessionSeconds"] = max(session_actuals.values(), default=0)
        totals["estimateAccuracyPercent"] = (
            max(0, min(100, int(round(100 - abs(totals["varianceSeconds"]) * 100 / totals["estimatedSeconds"]))))
            if totals["estimatedSeconds"] else 0
        )
        return {
            "startDate": start_key,
            "endDate": end_key,
            "days": days,
            "entries": entries,
            "tasks": tasks,
            "projects": sorted(project_values.values(), key=lambda item: item["name"].casefold()),
            "tags": sorted(tag_values.values(), key=lambda item: item["name"].casefold()),
            "totals": totals,
        }

    def export_timesheet_csv(self, target_path: str | Path, start_date: Any, end_date: Any) -> Path:
        report = self.timesheet(start_date, end_date)
        target = Path(target_path).expanduser()
        if target.suffix.lower() != ".csv":
            raise PlannerRepositoryError("工时导出文件须使用 .csv 扩展名。")
        parent = target.parent.resolve()
        if not parent.is_dir():
            raise PlannerRepositoryError("CSV 保存文件夹不存在。")
        handle: int | None = None
        temporary: str | None = None
        try:
            handle, temporary = tempfile.mkstemp(prefix=f".{target.stem}-", suffix=".tmp", dir=parent)
            with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as stream:
                handle = None
                writer = csv.writer(stream)
                writer.writerow(["日期", "任务", "项目", "标签", "开始", "结束", "计时方式", "来源", "实际秒数"])
                for row in report["entries"]:
                    writer.writerow([
                        row["date"], _safe_csv_text(row["title"]), _safe_csv_text(row["project"]),
                        _safe_csv_text(", ".join(row["tags"])), row["startedAt"], row["endedAt"],
                        row["mode"], row["source"], row["seconds"],
                    ])
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
            return target.resolve()
        finally:
            if handle is not None:
                os.close(handle)
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _record_tracking_segment_in(
        state: dict[str, Any], active: dict[str, Any], ended_at: datetime, total_seconds: int,
    ) -> int:
        record_id = str(active.get("taskId", ""))
        target = next((
            row for row in PlannerRepository._visible_records_from(state)
            if row.get("id") == record_id
        ), None)
        logged_seconds = active.get("sessionLoggedSeconds", 0)
        if isinstance(logged_seconds, bool) or not isinstance(logged_seconds, int) or logged_seconds < 0:
            logged_seconds = 0
        seconds = max(0, total_seconds - logged_seconds)
        if target is None or seconds <= 0:
            active["sessionLoggedSeconds"] = max(logged_seconds, total_seconds)
            return 0
        current_data = target.get("data") if isinstance(target.get("data"), dict) else {}
        changes = state["recordOverrides"].setdefault(record_id, {}).setdefault("data", {})
        current_seconds = current_data.get("trackedSeconds", 0)
        if isinstance(current_seconds, bool) or not isinstance(current_seconds, int) or current_seconds < 0:
            current_seconds = 0
        changes["trackedSeconds"] = current_seconds + seconds
        sessions = current_data.get("sessions", [])
        if not isinstance(sessions, list):
            sessions = []
        segment_started = active.get("segmentStartedAt", active.get("startedAt", ""))
        try:
            segment_start = datetime.fromisoformat(segment_started)
        except (TypeError, ValueError):
            segment_start = datetime.fromisoformat(active["startedAt"])
        end = ended_at
        if end.tzinfo is None and segment_start.tzinfo is not None:
            end = end.replace(tzinfo=segment_start.tzinfo)
        elif end.tzinfo is not None and segment_start.tzinfo is None:
            segment_start = segment_start.replace(tzinfo=end.tzinfo)
        session = {
            "sessionId": str(active.get("sessionId", "")),
            "startedAt": segment_start.isoformat(timespec="seconds"),
            "endedAt": end.isoformat(timespec="seconds"),
            "seconds": seconds,
            "mode": str(active.get("mode", "stopwatch")),
        }
        changes["sessions"] = [*sessions, session][-500:]
        active["sessionLoggedSeconds"] = max(logged_seconds, total_seconds)
        return seconds

    @staticmethod
    def _finish_tracking_in(state: dict[str, Any], now: datetime) -> int:
        active = state.get("activeTracking")
        if not isinstance(active, dict):
            return 0
        try:
            started = datetime.fromisoformat(active["startedAt"])
            checkpoint = datetime.fromisoformat(active.get("checkpointAt", active["startedAt"]))
        except (KeyError, TypeError, ValueError):
            state["activeTracking"] = None
            return 0
        end = now
        if end.tzinfo is None and checkpoint.tzinfo is not None:
            end = end.replace(tzinfo=checkpoint.tzinfo)
        elif end.tzinfo is not None and checkpoint.tzinfo is None:
            checkpoint = checkpoint.replace(tzinfo=end.tzinfo)
        if started.tzinfo is None and end.tzinfo is not None:
            started = started.replace(tzinfo=end.tzinfo)
        elif started.tzinfo is not None and end.tzinfo is None:
            end = end.replace(tzinfo=started.tzinfo)
        accumulated = active.get("accumulatedSeconds", 0)
        if isinstance(accumulated, bool) or not isinstance(accumulated, int) or accumulated < 0:
            accumulated = 0
        seconds = accumulated
        if not active.get("paused", False):
            seconds += max(0, int((end - checkpoint).total_seconds()))
        target_seconds = active.get("targetSeconds", 0)
        if isinstance(target_seconds, int) and not isinstance(target_seconds, bool) and target_seconds > 0:
            seconds = min(seconds, target_seconds)
        PlannerRepository._record_tracking_segment_in(state, active, end, seconds)
        state["activeTracking"] = None
        return seconds

    @staticmethod
    def _visible_records_from(state: dict[str, Any]) -> list[dict[str, Any]]:
        hidden = {(item["type"], item["id"]) for item in state["deletedRecords"]}
        local_ids = {str(record.get("id", "")) for record in state["localRecords"]}
        rows: list[dict[str, Any]] = []
        for raw in state["legacyRecords"]:
            record_id = str(raw.get("id", ""))
            if raw.get("type") != "planner" or ("planner", record_id) in hidden:
                continue
            if record_id in local_ids:
                continue
            row = deepcopy(raw)
            changes = state["recordOverrides"].get(record_id, {}).get("data", {})
            if isinstance(changes, dict):
                row["data"] = {**row.get("data", {}), **deepcopy(changes)}
            if "estimateMinutes" in row["data"]:
                row["data"]["estimateMinutes"] = _effective_estimate_minutes(
                    row["data"]["estimateMinutes"]
                )
            rows.append(row)
        for raw in state["localRecords"]:
            record_id = str(raw.get("id", ""))
            if raw.get("type") != "planner" or ("planner", record_id) in hidden:
                continue
            row = deepcopy(raw)
            changes = state["recordOverrides"].get(record_id, {}).get("data", {})
            if isinstance(changes, dict):
                row["data"] = {**row.get("data", {}), **deepcopy(changes)}
            if "estimateMinutes" in row["data"]:
                row["data"]["estimateMinutes"] = _effective_estimate_minutes(
                    row["data"]["estimateMinutes"]
                )
            rows.append(row)
        return rows

    def start_tracking(self, record_id: Any) -> dict[str, Any] | None:
        if not isinstance(record_id, str) or not record_id:
            raise PlannerRepositoryError("计时任务无效。")
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return None
            if target["data"].get("done"):
                raise PlannerRepositoryError("已完成的事项不能开始计时。")
            external_todo = target["data"].get("externalTodo")
            if isinstance(external_todo, dict) and external_todo.get("cancelled"):
                raise PlannerRepositoryError("来源已取消的任务不能开始计时。")
            active = self._state.get("activeTracking")
            if isinstance(active, dict):
                if active.get("taskId") == record_id:
                    return target
                raise PlannerRepositoryError("请先结束当前任务的计时，再开始另一项。")
            candidate = deepcopy(self._state)
            started = self._now().isoformat(timespec="seconds")
            candidate["activeTracking"] = {
                "taskId": record_id,
                "startedAt": started,
                "checkpointAt": started,
                "accumulatedSeconds": 0,
                "mode": "stopwatch",
                "targetSeconds": 0,
                "paused": False,
                "sessionLoggedSeconds": 0,
                "segmentStartedAt": started,
                "sessionId": str(uuid4()),
            }
            self._commit(candidate)
            return self._target(record_id)

    def start_focus_tracking(
        self, record_id: Any, mode: Any, duration_minutes: Any = 25,
    ) -> dict[str, Any] | None:
        if not isinstance(mode, str) or mode not in {"pomodoro", "flowtime", "countdown"}:
            raise PlannerRepositoryError("专注计时模式无效。")
        if mode == "countdown" and (
            isinstance(duration_minutes, bool)
            or not isinstance(duration_minutes, int)
            or not 5 <= duration_minutes <= 480
        ):
            raise PlannerRepositoryError("倒计时须为 5 至 480 分钟。")
        if mode == "pomodoro":
            target_seconds = 25 * 60
        elif mode == "countdown":
            target_seconds = duration_minutes * 60
        else:
            target_seconds = 0
        target = self._target(record_id)
        if target is None:
            return None
        if target["data"].get("done"):
            raise PlannerRepositoryError("已完成的事项不能开始计时。")
        external_todo = target["data"].get("externalTodo")
        if isinstance(external_todo, dict) and external_todo.get("cancelled"):
            raise PlannerRepositoryError("来源已取消的任务不能开始计时。")
        with self._lock:
            active = self._state.get("activeTracking")
            if isinstance(active, dict):
                if active.get("taskId") == record_id and active.get("mode") == mode:
                    return target
                raise PlannerRepositoryError("请先结束当前任务的计时，再开始另一项。")
            candidate = deepcopy(self._state)
            started = self._now().isoformat(timespec="seconds")
            candidate["activeTracking"] = {
                "taskId": record_id,
                "startedAt": started,
                "checkpointAt": started,
                "accumulatedSeconds": 0,
                "mode": mode,
                "targetSeconds": target_seconds,
                "paused": False,
                "sessionLoggedSeconds": 0,
                "segmentStartedAt": started,
                "sessionId": str(uuid4()),
            }
            self._commit(candidate)
            return self._target(record_id)

    @staticmethod
    def _pause_tracking_in(state: dict[str, Any], now: datetime) -> bool:
        active = state.get("activeTracking")
        if not isinstance(active, dict) or active.get("paused", False):
            return False
        try:
            checkpoint = datetime.fromisoformat(active["checkpointAt"])
        except (KeyError, TypeError, ValueError):
            raise PlannerRepositoryError("当前计时的检查点时间无效。")
        end = now
        if end.tzinfo is None and checkpoint.tzinfo is not None:
            end = end.replace(tzinfo=checkpoint.tzinfo)
        elif end.tzinfo is not None and checkpoint.tzinfo is None:
            checkpoint = checkpoint.replace(tzinfo=end.tzinfo)
        elapsed = max(0, int((end - checkpoint).total_seconds()))
        accumulated = int(active.get("accumulatedSeconds", 0)) + elapsed
        target_seconds = active.get("targetSeconds", 0)
        if isinstance(target_seconds, int) and not isinstance(target_seconds, bool) and target_seconds > 0:
            accumulated = min(accumulated, target_seconds)
        active["accumulatedSeconds"] = accumulated
        active["checkpointAt"] = end.isoformat(timespec="seconds")
        PlannerRepository._record_tracking_segment_in(state, active, end, accumulated)
        active["paused"] = True
        return True

    def pause_tracking(self) -> bool:
        with self._lock:
            candidate = deepcopy(self._state)
            if not self._pause_tracking_in(candidate, self._now()):
                return False
            self._commit(candidate)
            return True

    def resume_tracking(self) -> bool:
        with self._lock:
            active = self._state.get("activeTracking")
            if not isinstance(active, dict) or not active.get("paused", False):
                return False
            candidate = deepcopy(self._state)
            updated = candidate["activeTracking"]
            resumed_at = self._now().isoformat(timespec="seconds")
            updated["checkpointAt"] = resumed_at
            updated["segmentStartedAt"] = resumed_at
            updated["sessionId"] = str(uuid4())
            updated["paused"] = False
            self._commit(candidate)
            return True

    def complete_tracking_if_due(self) -> str:
        with self._lock:
            active = self._state.get("activeTracking")
            if not isinstance(active, dict) or active.get("paused", False):
                return ""
            mode = str(active.get("mode", "stopwatch"))
            target_seconds = int(active.get("targetSeconds", 0) or 0)
            if mode not in {"pomodoro", "countdown"} or target_seconds <= 0:
                return ""
            snapshot = self.state()
            current = snapshot.get("activeTracking", {})
            if int(current.get("remainingSeconds", target_seconds)) > 0:
                return ""
            candidate = deepcopy(self._state)
            self._finish_tracking_in(candidate, self._now())
            self._commit(candidate)
            return mode

    def checkpoint_tracking(self) -> bool:
        with self._lock:
            active = self._state.get("activeTracking")
            if not isinstance(active, dict):
                return False
            if active.get("paused", False):
                return False
            try:
                checkpoint = datetime.fromisoformat(active.get("checkpointAt", active["startedAt"]))
            except (KeyError, TypeError, ValueError):
                raise PlannerRepositoryError("当前计时的检查点时间无效。")
            now = self._now()
            end = now
            if end.tzinfo is None and checkpoint.tzinfo is not None:
                end = end.replace(tzinfo=checkpoint.tzinfo)
            elif end.tzinfo is not None and checkpoint.tzinfo is None:
                checkpoint = checkpoint.replace(tzinfo=end.tzinfo)
            elapsed = max(0, int((end - checkpoint).total_seconds()))
            if elapsed < 30:
                return False
            candidate = deepcopy(self._state)
            updated = candidate["activeTracking"]
            updated["accumulatedSeconds"] = int(updated.get("accumulatedSeconds", 0)) + elapsed
            updated["checkpointAt"] = end.isoformat(timespec="seconds")
            self._commit(candidate)
            return True

    def stop_tracking(self) -> int:
        with self._lock:
            if not isinstance(self._state.get("activeTracking"), dict):
                return 0
            candidate = deepcopy(self._state)
            seconds = self._finish_tracking_in(candidate, self._now())
            self._commit(candidate)
            return seconds

    @staticmethod
    def _next_repeat_day(current_day: str, repeat: str, day_of_month: int | None = None) -> str | None:
        current = date.fromisoformat(current_day)
        if repeat == "daily":
            return (current + timedelta(days=1)).isoformat()
        if repeat == "weekdays":
            next_day = current + timedelta(days=1)
            while next_day.weekday() >= 5:
                next_day += timedelta(days=1)
            return next_day.isoformat()
        if repeat == "weekly":
            return (current + timedelta(days=7)).isoformat()
        if repeat == "monthly":
            first_next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
            last_day = ((first_next_month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).day
            anchor = day_of_month if isinstance(day_of_month, int) and not isinstance(day_of_month, bool) and 1 <= day_of_month <= 31 else current.day
            return first_next_month.replace(day=min(anchor, last_day)).isoformat()
        return None

    def _create_next_repeat(self, state: dict[str, Any], completed: dict[str, Any], now: datetime) -> None:
        data = completed.get("data") if isinstance(completed.get("data"), dict) else {}
        repeat = data.get("repeat", "none")
        series_id = data.get("repeatSeriesId")
        if not isinstance(repeat, str) or repeat not in _REPEATS - {"none"} or not isinstance(series_id, str) or not series_id:
            return
        anchor_day = data.get("repeatDayOfMonth")
        next_day = self._next_repeat_day(str(completed.get("date", "")), repeat, anchor_day)
        if not next_day:
            return
        if any(
            row.get("date") == next_day
            and row.get("data", {}).get("repeatSeriesId") == series_id
            for row in self._visible_records(state)
        ):
            return
        next_data = deepcopy(data)
        next_data["done"] = False
        next_data["status"] = "todo"
        next_data["completedAt"] = ""
        next_data["remindedAt"] = ""
        next_data["trackedSeconds"] = 0
        next_data["sessions"] = []
        if next_data.get("plannedStart"):
            next_data["plannedDate"] = next_day
        next_task = {
            "id": str(uuid4()),
            "type": "planner",
            "date": next_day,
            "createdAt": int(now.timestamp() * 1000),
            "sample": False,
            "data": next_data,
        }
        state["localRecords"].append(next_task)

    def _target(self, record_id: Any, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not isinstance(record_id, str) or not record_id:
            raise PlannerRepositoryError("日程 id 无效。")
        return next((item for item in self._visible_records(state) if item.get("id") == record_id), None)

    @staticmethod
    def _clear_reminder_receipt(state: dict[str, Any], record_id: str) -> None:
        """Mask inherited reminder receipts when their schedule is changed."""
        changes = state["recordOverrides"].setdefault(record_id, {}).setdefault("data", {})
        changes["remindedAt"] = ""

    def toggle_task(self, record_id: Any) -> dict[str, Any] | None:
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return None
            external_todo = target["data"].get("externalTodo")
            if isinstance(external_todo, dict) and external_todo.get("cancelled"):
                raise PlannerRepositoryError("来源已取消的任务不能修改完成状态。")
            current = bool(target["data"].get("done"))
            if not current:
                pending_children = [
                    row for row in self._visible_records()
                    if (row.get("data") or {}).get("parentTaskId") == record_id
                    and not (row.get("data") or {}).get("done")
                ]
                if pending_children:
                    raise PlannerRepositoryError("请先完成全部子任务，再完成这项任务。")
            candidate = deepcopy(self._state)
            changes = candidate["recordOverrides"].setdefault(record_id, {})
            changes.setdefault("data", {})["done"] = not current
            changes["data"]["status"] = "todo" if current else "done"
            if not current:
                changes["data"]["completedAt"] = self._now().isoformat(timespec="seconds")
                active = candidate.get("activeTracking")
                if isinstance(active, dict) and active.get("taskId") == record_id:
                    self._finish_tracking_in(candidate, self._now())
                self._create_next_repeat(candidate, target, self._now())
            else:
                changes["data"]["completedAt"] = ""
                self._clear_reminder_receipt(candidate, str(record_id))
            self._commit(candidate)
            return self._target(record_id)

    def delete_task(self, record_id: Any) -> bool:
        with self._lock:
            target = self._target(record_id)
            if target is None:
                return False
            active = self._state.get("activeTracking")
            child_ids = [
                str(row.get("id", ""))
                for row in self._visible_records()
                if (row.get("data") or {}).get("parentTaskId") == record_id
            ]
            delete_ids = {record_id, *child_ids}
            if isinstance(active, dict) and active.get("taskId") in delete_ids:
                raise PlannerRepositoryError("请先结束这项任务的计时，再删除它。")
            candidate = deepcopy(self._state)
            for delete_id in delete_ids:
                local = next((
                    item for item in candidate["localRecords"] if item.get("id") == delete_id
                ), None)
                local_data = local.get("data") if isinstance(local, dict) and isinstance(local.get("data"), dict) else {}
                external_todo = local_data.get("externalTodo") if isinstance(local_data.get("externalTodo"), dict) else {}
                candidate["localRecords"] = [
                    item for item in candidate["localRecords"] if item.get("id") != delete_id
                ]
                candidate["recordOverrides"].pop(delete_id, None)
                if any(
                    item.get("type") == "planner" and item.get("id") == delete_id
                    for item in candidate["legacyRecords"]
                ) or external_todo.get("provider") in {"ical-file", "caldav"}:
                    tombstone = {"type": "planner", "id": delete_id}
                    if tombstone not in candidate["deletedRecords"]:
                        candidate["deletedRecords"].append(tombstone)
            self._commit(candidate)
            return True

    def adopt_imported_data(self, snapshot: Any) -> bool:
        """Adopt a later legacy snapshot while preserving local work and overlays."""
        records, settings, imported_draft, has_main = _legacy_source(snapshot)
        if not has_main:
            return False
        with self._lock:
            candidate = deepcopy(self._state)
            candidate["legacyRecords"] = records
            candidate["legacySettings"] = settings
            if not candidate.get("draftOverridden", False):
                candidate["draft"] = imported_draft
            self._commit(candidate)
            return True

    @staticmethod
    def _reminder_time(record: dict[str, Any]) -> datetime | None:
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        record_date = data.get("plannedDate") or record.get("date")
        raw_time = data.get("plannedStart") or data.get("time")
        if not isinstance(record_date, str) or not isinstance(raw_time, str) or not _TIME_PATTERN.fullmatch(raw_time):
            return None
        try:
            return datetime.combine(date.fromisoformat(_valid_date(record_date)), time.fromisoformat(raw_time))
        except ValueError:
            return None

    def has_pending_reminders(self, now: datetime | None = None) -> bool:
        """Return whether a valid, unfired reminder is due today or later."""
        current = self._now() if now is None else (now.astimezone() if now.tzinfo else now)
        today = current.date().isoformat()
        with self._lock:
            for record in self._visible_records():
                data = record.get("data") if isinstance(record.get("data"), dict) else {}
                if (
                    record.get("sample")
                    or data.get("done")
                    or not data.get("remind")
                    or data.get("remindedAt")
                ):
                    continue
                due_time = self._reminder_time(record)
                if due_time is not None and due_time.date().isoformat() >= today:
                    return True
            return False

    def check_due_reminders(self, now: datetime | None = None) -> list[dict[str, str]]:
        """Mark and return reminders due today; each record can trigger only once."""
        current = self._now() if now is None else (now.astimezone() if now.tzinfo else now)
        today = current.date().isoformat()
        current_local = current.replace(tzinfo=None)
        timestamp = current.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._lock:
            rows = self._visible_records()
            due: list[dict[str, str]] = []
            candidate = deepcopy(self._state)
            for record in rows:
                data = record["data"]
                if record.get("sample") or data.get("done") or not data.get("remind") or data.get("remindedAt"):
                    continue
                due_time = self._reminder_time(record)
                if due_time is None or due_time.date().isoformat() != today or due_time > current_local:
                    continue
                record_id = record["id"]
                changes = candidate["recordOverrides"].setdefault(record_id, {})
                changes.setdefault("data", {})["remindedAt"] = timestamp
                title = data.get("title")
                note = data.get("note")
                due.append({
                    "id": record_id,
                    "title": title if isinstance(title, str) and title else "日程提醒",
                    "body": note if isinstance(note, str) and note else "该处理这件日程了。",
                })
            if due:
                self._commit(candidate)
            return due
