from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit


STORAGE_KEYS_V1 = (
    "richangji-state-v1",
    "richangji-samples-cleared",
    "wanxiang-paper-layout-v2",
    "wanxiang-daily-issues-v1",
    "wanxiang-issue-questions-v1",
    "wanxiang-issue-topics-v1",
    "wanxiang-issue-preferences-v1",
    "wanxiang-issue-clippings-v1",
    "wanxiang-saved-knowledge",
)
STORAGE_KEYS = STORAGE_KEYS_V1 + ("wanxiang-planner-sync-device-v1",)

PACKAGE_FORMAT = "wanxiang-legacy-migration"
PACKAGE_SCHEMA_VERSION = 2
STORAGE_KEYS_BY_SCHEMA = {
    1: STORAGE_KEYS_V1,
    PACKAGE_SCHEMA_VERSION: STORAGE_KEYS,
}
SOURCE_IDENTITY = "wanxiang-localstorage-v1"
MAX_PACKAGE_BYTES = 256 * 1024 * 1024


class MigrationPackageError(ValueError):
    """迁移包缺失、损坏或与当前格式不兼容。"""


@dataclass(frozen=True)
class MigrationPackage:
    schema_version: int
    exported_at: str
    source_version: str
    checksum: str
    raw_values: dict[str, str | None]
    parsed_values: dict[str, Any]
    summary: dict[str, int]


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MigrationPackageError(f"JSON 对象包含重复字段：{key}")
        result[key] = value
    return result


def _reject_non_json_constant(value: str) -> None:
    raise MigrationPackageError(f"JSON 中不支持非标准数值：{value}")


def _json_loads(raw: str, label: str) -> Any:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_non_json_constant,
        )
    except MigrationPackageError:
        raise
    except (json.JSONDecodeError, TypeError) as exc:
        raise MigrationPackageError(f"{label} 不是有效 JSON：{exc}") from exc


def _json_compact(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def calculate_checksum(
    raw_values: dict[str, str | None], schema_version: int | None = None
) -> str:
    """按对应迁移包版本的固定键顺序校验原始 localStorage 字符串。"""
    version = PACKAGE_SCHEMA_VERSION if schema_version is None else schema_version
    keys = STORAGE_KEYS_BY_SCHEMA.get(version)
    if keys is None:
        raise MigrationPackageError("迁移包版本不受支持")
    pairs = [[key, raw_values[key]] for key in keys]
    canonical = json.dumps(
        pairs,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _expect_json_value(
    raw_values: dict[str, str | None],
    parsed_values: dict[str, Any],
    key: str,
    expected_type: type | tuple[type, ...],
    label: str,
) -> Any:
    raw = raw_values[key]
    if raw is None:
        return None
    value = _json_loads(raw, label)
    if not isinstance(value, expected_type):
        expected = (
            " 或 ".join(item.__name__ for item in expected_type)
            if isinstance(expected_type, tuple)
            else expected_type.__name__
        )
        raise MigrationPackageError(f"{label} 顶层必须是 {expected}")
    parsed_values[key] = value
    return value


def _array_of_objects(value: Any, label: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MigrationPackageError(f"{label} 必须是 JSON 数组")
    if any(not isinstance(item, dict) for item in value):
        raise MigrationPackageError(f"{label} 中每一项都必须是 JSON 对象")
    return value


def _date_shape(value: Any) -> bool:
    # 与旧版 normalizeState 的校验边界一致：要求 YYYY-MM-DD 形状。
    return isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_issue(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise MigrationPackageError(f"{label} 必须是对象")
    if str(value.get("version", "")) != "1":
        raise MigrationPackageError(f"{label} version 必须为 1")
    if not _date_shape(value.get("date")):
        raise MigrationPackageError(f"{label} date 必须使用 YYYY-MM-DD 格式")
    if not _nonempty_text(value.get("topic")):
        raise MigrationPackageError(f"{label} topic 不能为空")

    groups = (("focus", 1, 5), ("highlights", 1, 8), ("articles", 0, 12))
    article_ids: list[str] = []
    for key, minimum, maximum in groups:
        items = value.get(key, [] if key == "articles" else None)
        if not isinstance(items, list) or not minimum <= len(items) <= maximum:
            raise MigrationPackageError(
                f"{label} {key} 必须包含 {minimum}–{maximum} 项"
            )
        for index, item in enumerate(items, start=1):
            item_label = f"{label} {key} 第 {index} 项"
            if not isinstance(item, dict):
                raise MigrationPackageError(f"{item_label} 必须是对象")
            for field in ("id", "label", "title", "summary", "publisher", "publishedAt"):
                if not _nonempty_text(item.get(field)):
                    raise MigrationPackageError(f"{item_label} 缺少 {field}")
            article_ids.append(item["id"])
            source = item.get("sourceUrl")
            try:
                parsed_source = urlsplit(source) if isinstance(source, str) else None
            except ValueError:
                parsed_source = None
            if not parsed_source or parsed_source.scheme != "https" or not parsed_source.netloc:
                raise MigrationPackageError(f"{item_label} 需要有效的 HTTPS sourceUrl")
            body = item.get("body")
            if isinstance(body, str):
                body_items = [part for part in re.split(r"\n\s*\n", body) if part.strip()]
            elif isinstance(body, list):
                body_items = body
            else:
                body_items = []
            if not body_items or any(not _nonempty_text(part) for part in body_items):
                raise MigrationPackageError(f"{item_label} body 必须包含非空段落")
    if len(article_ids) != len(set(article_ids)):
        raise MigrationPackageError(f"{label} 所有条目的 id 必须唯一")


def _make_summary(
    raw_values: dict[str, str | None],
    parsed_values: dict[str, Any],
    keys: tuple[str, ...] | None = None,
) -> dict[str, int]:
    state = parsed_values.get("richangji-state-v1") or {}
    issue_store = parsed_values.get("wanxiang-daily-issues-v1") or {}
    summary_keys = tuple(raw_values) if keys is None else keys
    return {
        "keys_total": len(summary_keys),
        "keys_present": sum(raw_values.get(key) is not None for key in summary_keys),
        "records": len(state.get("records") or []),
        "habits": len(state.get("habits") or []),
        "media_items": len(state.get("mediaItems") or []),
        "active_issue": int(bool(issue_store.get("active"))),
        "archived_issues": len(issue_store.get("archive") or []),
        "questions": len(parsed_values.get("wanxiang-issue-questions-v1") or []),
        "topics": len(parsed_values.get("wanxiang-issue-topics-v1") or []),
        "clippings": len(parsed_values.get("wanxiang-issue-clippings-v1") or []),
    }


def validate_package(payload: Any) -> MigrationPackage:
    if not isinstance(payload, dict):
        raise MigrationPackageError("迁移包最外层必须是 JSON 对象")
    if payload.get("format") != PACKAGE_FORMAT:
        raise MigrationPackageError("文件不是受支持的 FLUKE 旧版迁移包")
    schema_version = payload.get("schemaVersion")
    if type(schema_version) is not int or schema_version not in STORAGE_KEYS_BY_SCHEMA:
        raise MigrationPackageError("迁移包版本不受支持")
    schema_keys = STORAGE_KEYS_BY_SCHEMA[schema_version]

    exported_at = payload.get("exportedAt")
    if not isinstance(exported_at, str) or not exported_at:
        raise MigrationPackageError("迁移包缺少导出时间")
    try:
        datetime.fromisoformat(exported_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MigrationPackageError("迁移包导出时间无效") from exc

    source_version = payload.get("sourceVersion", "unknown")
    if not isinstance(source_version, str):
        raise MigrationPackageError("sourceVersion 必须是字符串")

    raw_values = payload.get("keys")
    if not isinstance(raw_values, dict):
        raise MigrationPackageError("迁移包缺少 keys 对象")
    received = set(raw_values)
    expected = set(schema_keys)
    missing = [key for key in schema_keys if key not in received]
    extra = sorted(received - expected)
    if missing or extra:
        details = []
        if missing:
            details.append("缺少：" + "、".join(missing))
        if extra:
            details.append("未知：" + "、".join(extra))
        raise MigrationPackageError("迁移键清单不匹配（" + "；".join(details) + "）")
    if any(value is not None and not isinstance(value, str) for value in raw_values.values()):
        raise MigrationPackageError("每个存储值必须是原始字符串或 null")
    ordered_values = {key: raw_values[key] for key in schema_keys}

    expected_checksum = payload.get("checksum")
    if not isinstance(expected_checksum, str) or len(expected_checksum) != 64:
        raise MigrationPackageError("迁移包缺少 SHA-256 校验值")
    actual_checksum = calculate_checksum(ordered_values, schema_version)
    if actual_checksum != expected_checksum.lower():
        raise MigrationPackageError("SHA-256 校验失败，迁移包内容可能不完整或已被修改")

    parsed_values: dict[str, Any] = {}
    state = _expect_json_value(
        ordered_values,
        parsed_values,
        "richangji-state-v1",
        dict,
        "主状态",
    )
    if state is not None:
        if "records" not in state or not isinstance(state["records"], list):
            raise MigrationPackageError("主状态缺少 records 数组")
        for field in ("habits", "mediaItems"):
            if field in state and not isinstance(state[field], list):
                raise MigrationPackageError(f"主状态 {field} 必须是数组")
        for field in ("records", "habits", "mediaItems"):
            _array_of_objects(state.get(field), f"主状态 {field}")
        valid_record_types = {"money", "fitness", "planner", "home"}
        for index, record in enumerate(state["records"], start=1):
            label = f"主状态 records 第 {index} 项"
            if record.get("type") not in valid_record_types:
                raise MigrationPackageError(f"{label} type 无法识别")
            if not _date_shape(record.get("date")):
                raise MigrationPackageError(f"{label} date 必须使用 YYYY-MM-DD 格式")
            if not isinstance(record.get("data"), dict):
                raise MigrationPackageError(f"{label} data 必须是对象")
        for index, habit in enumerate(state.get("habits", []), start=1):
            label = f"主状态 habits 第 {index} 项"
            if "entries" in habit and not isinstance(habit["entries"], dict):
                raise MigrationPackageError(f"{label} entries 必须是对象")
            if "completedDates" in habit and not isinstance(habit["completedDates"], list):
                raise MigrationPackageError(f"{label} completedDates 必须是数组")
        for index, item in enumerate(state.get("mediaItems", []), start=1):
            if not _nonempty_text(item.get("name")):
                raise MigrationPackageError(f"主状态 mediaItems 第 {index} 项 name 不能为空")

    layout = _expect_json_value(
        ordered_values,
        parsed_values,
        "wanxiang-paper-layout-v2",
        dict,
        "版面布局",
    )
    if layout is not None:
        if "order" in layout and (
            not isinstance(layout["order"], list)
            or any(not isinstance(item, str) for item in layout["order"])
        ):
            raise MigrationPackageError("版面布局 order 必须是字符串数组")
        if "slots" in layout and not isinstance(layout["slots"], dict):
            raise MigrationPackageError("版面布局 slots 必须是对象")
        if "hidden" in layout and (
            not isinstance(layout["hidden"], list)
            or any(not isinstance(item, str) for item in layout["hidden"])
        ):
            raise MigrationPackageError("版面布局 hidden 必须是字符串数组")

    issue_store = _expect_json_value(
        ordered_values,
        parsed_values,
        "wanxiang-daily-issues-v1",
        dict,
        "新闻刊期",
    )
    if issue_store is not None:
        if issue_store.get("active") is not None and not isinstance(issue_store["active"], dict):
            raise MigrationPackageError("新闻刊期 active 必须是对象或 null")
        if issue_store.get("active") is not None:
            _valid_issue(issue_store["active"], "新闻刊期 active")
        if "archive" in issue_store:
            archive = _array_of_objects(issue_store["archive"], "新闻刊期 archive")
            for index, entry in enumerate(archive, start=1):
                if not isinstance(entry.get("issue"), dict):
                    raise MigrationPackageError(f"新闻刊期 archive 第 {index} 项缺少 issue 对象")
                _valid_issue(entry["issue"], f"新闻刊期 archive 第 {index} 项 issue")

    for key, label in (
        ("wanxiang-issue-questions-v1", "问题簿"),
        ("wanxiang-issue-topics-v1", "关注主题"),
        ("wanxiang-issue-clippings-v1", "新闻剪报"),
    ):
        _expect_json_value(ordered_values, parsed_values, key, list, label)

    _expect_json_value(
        ordered_values,
        parsed_values,
        "wanxiang-issue-preferences-v1",
        dict,
        "媒体偏好",
    )

    for key in ("wanxiang-issue-questions-v1", "wanxiang-issue-topics-v1"):
        value = parsed_values.get(key)
        if value is not None and any(
            not isinstance(item, str)
            and not (
                key == "wanxiang-issue-questions-v1"
                and isinstance(item, dict)
            )
            for item in value
        ):
            raise MigrationPackageError(f"{key} 包含无法识别的条目")

    clippings = parsed_values.get("wanxiang-issue-clippings-v1")
    if clippings is not None:
        for index, item in enumerate(clippings, start=1):
            label = f"新闻剪报第 {index} 项"
            if not isinstance(item, dict):
                raise MigrationPackageError("新闻剪报必须由对象组成")
            if not _nonempty_text(item.get("key")) or not _date_shape(item.get("date")):
                raise MigrationPackageError(f"{label}缺少 key 或有效 date")
            saved_item = item.get("item")
            if not isinstance(saved_item, dict) or not _nonempty_text(saved_item.get("id")) or not _nonempty_text(saved_item.get("title")):
                raise MigrationPackageError(f"{label} item 必须包含 id 和 title")

    preferences = parsed_values.get("wanxiang-issue-preferences-v1")
    if preferences is not None:
        for field in ("subtopics", "sources"):
            if field in preferences and not isinstance(preferences[field], str):
                raise MigrationPackageError(f"媒体偏好 {field} 必须是字符串")
        if "presetSources" in preferences and (
            not isinstance(preferences["presetSources"], list)
            or any(not isinstance(item, str) for item in preferences["presetSources"])
        ):
            raise MigrationPackageError("媒体偏好 presetSources 必须是字符串数组")

    return MigrationPackage(
        schema_version=schema_version,
        exported_at=exported_at,
        source_version=source_version,
        checksum=actual_checksum,
        raw_values=ordered_values,
        parsed_values=parsed_values,
        summary=_make_summary(ordered_values, parsed_values, schema_keys),
    )


def read_package_file(path: Path) -> MigrationPackage:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MigrationPackageError(f"无法读取迁移包：{exc}") from exc
    if size > MAX_PACKAGE_BYTES:
        raise MigrationPackageError(
            f"迁移包超过 {MAX_PACKAGE_BYTES // (1024 * 1024)} MB 限制"
        )
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            payload = json.load(
                stream,
                object_pairs_hook=_reject_duplicate_object_keys,
                parse_constant=_reject_non_json_constant,
            )
    except MigrationPackageError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationPackageError(f"迁移包读取失败：{exc}") from exc
    return validate_package(payload)


def compact_json(value: Any) -> str:
    """给 SQLite 的查询副本使用；原始值另存以保证逐字节迁移核对。"""
    return _json_compact(value)
