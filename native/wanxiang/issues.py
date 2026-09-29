"""Local repository for daily news issues and their editing state."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any

from .database import initialize_schema, load_imported_data
from .migration import MigrationPackage
from .news_import import NewsImportError, normalize_issue, normalize_news_url


ISSUE_SETTING = "dailyIssueStore"
DRAFT_SETTING = "dailyIssueDraft"
INBOX_SETTING = "newsLinkInbox"
LAYOUT_SETTING = "newsIssueLayout"
LEGACY_ISSUE_KEY = "wanxiang-daily-issues-v1"
MAX_ARCHIVE_ITEMS = 40

_MISSING = object()
_ISSUE_GROUPS = {"focus", "highlights", "articles"}


class IssueRepositoryError(ValueError):
    """Readable error raised for invalid persisted or requested issue state."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IssueRepositoryError(f"设置 JSON 包含重复字段：{key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise IssueRepositoryError(f"设置 JSON 包含非标准数值：{value}")


def _read_settings(database_path: Path) -> dict[str, Any]:
    """Read app settings without creating or modifying the database."""
    if not database_path.is_file():
        return {}

    connection: sqlite3.Connection | None = None
    try:
        uri = f"{database_path.expanduser().resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.execute("PRAGMA query_only = ON")
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_settings'"
        ).fetchone()
        if table is None:
            return {}
        result: dict[str, Any] = {}
        for key, raw in connection.execute(
            "SELECT key, value_json FROM app_settings WHERE key IN (?, ?, ?, ?)",
            (ISSUE_SETTING, DRAFT_SETTING, INBOX_SETTING, LAYOUT_SETTING),
        ):
            try:
                result[key] = json.loads(
                    raw,
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_constant,
                )
            except (json.JSONDecodeError, TypeError) as exc:
                raise IssueRepositoryError(f"本机设置 {key} 不是有效 JSON。") from exc
        return result
    except IssueRepositoryError:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise IssueRepositoryError(f"无法读取本机新闻设置：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def _json_clone(value: Any, label: str) -> Any:
    def check(item: Any) -> None:
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise IssueRepositoryError(f"{label} 的对象字段名必须是字符串。")
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise IssueRepositoryError(f"{label} 包含不能保存的数据类型。")

    check(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise IssueRepositoryError(f"{label} 不是有效的 JSON 数据。") from exc


def _legacy_document(source: Any, key: str) -> Any:
    """Extract one parsed migration document from supported legacy inputs."""
    if isinstance(source, MigrationPackage):
        return source.parsed_values.get(key, _MISSING)
    if isinstance(source, dict):
        for container_name in ("parsed_values", "documents"):
            container = source.get(container_name)
            if isinstance(container, dict) and key in container:
                return container[key]
        if key in source:
            return source[key]
        for container_name in ("raw_values", "keys"):
            raw_values = source.get(container_name)
            if isinstance(raw_values, dict) and key in raw_values:
                raw = raw_values[key]
                if raw is None:
                    return _MISSING
                if isinstance(raw, str):
                    try:
                        return json.loads(
                            raw,
                            object_pairs_hook=_reject_duplicate_keys,
                            parse_constant=_reject_constant,
                        )
                    except (
                        IssueRepositoryError,
                        json.JSONDecodeError,
                        TypeError,
                    ) as exc:
                        raise IssueRepositoryError(
                            f"旧版存储键 {key} 不是有效 JSON。"
                        ) from exc
        # Also accept the issue-store object itself for direct construction.
        if key == LEGACY_ISSUE_KEY and (
            "active" in source or "archive" in source
        ):
            return source
    return _MISSING


def _normalize_store(value: Any) -> dict[str, Any]:
    if value is None:
        value = {"active": None, "archive": []}
    if not isinstance(value, dict):
        raise IssueRepositoryError("dailyIssueStore 必须是对象。")

    raw_active = value.get("active")
    try:
        active = None if raw_active is None else normalize_issue(raw_active)
    except NewsImportError as exc:
        raise IssueRepositoryError(f"当前刊期无效：{exc}") from exc

    raw_archive = value.get("archive", [])
    if not isinstance(raw_archive, list):
        raise IssueRepositoryError("历史刊期 archive 必须是数组。")
    archive: list[dict[str, Any]] = []
    for index, entry in enumerate(raw_archive[:MAX_ARCHIVE_ITEMS], start=1):
        if not isinstance(entry, dict) or not isinstance(entry.get("issue"), dict):
            raise IssueRepositoryError(f"历史刊期第 {index} 项缺少 issue 对象。")
        try:
            normalized_issue = normalize_issue(entry["issue"])
        except NewsImportError as exc:
            raise IssueRepositoryError(f"历史刊期第 {index} 项无效：{exc}") from exc
        normalized_entry = _json_clone(entry, f"历史刊期第 {index} 项")
        normalized_entry["issue"] = normalized_issue
        published_at = normalized_entry.get("publishedAt", "")
        if not isinstance(published_at, str):
            published_at = str(published_at)
        normalized_entry["publishedAt"] = published_at[:80]
        archive.append(normalized_entry)
    return {"active": active, "archive": archive}


def _normalize_links(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise IssueRepositoryError("newsLinkInbox 必须是数组。")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise IssueRepositoryError(f"素材箱第 {index} 项必须是对象。")
        try:
            url = normalize_news_url(item.get("url"))
        except NewsImportError as exc:
            raise IssueRepositoryError(f"素材箱第 {index} 项链接无效：{exc}") from exc
        if url in seen:
            continue
        seen.add(url)
        added_at = item.get("addedAt", "")
        if not isinstance(added_at, str):
            raise IssueRepositoryError(f"素材箱第 {index} 项 addedAt 必须是字符串。")
        result.append({"url": url, "addedAt": added_at[:80]})
    return result


def _normalize_layout(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise IssueRepositoryError("newsIssueLayout 必须是对象。")
    normalized = _json_clone(value, "newsIssueLayout")
    if "order" in normalized and (
        not isinstance(normalized["order"], list)
        or any(not isinstance(item, str) for item in normalized["order"])
    ):
        raise IssueRepositoryError("newsIssueLayout order 必须是字符串数组。")
    if "slots" in normalized and not isinstance(normalized["slots"], dict):
        raise IssueRepositoryError("newsIssueLayout slots 必须是对象。")
    if "hidden" in normalized and (
        not isinstance(normalized["hidden"], list)
        or any(not isinstance(item, str) for item in normalized["hidden"])
    ):
        raise IssueRepositoryError("newsIssueLayout hidden 必须是字符串数组。")
    return normalized


def _timestamp(value: str | None, label: str) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
    if not isinstance(value, str) or not value.strip():
        raise IssueRepositoryError(f"{label} 必须是有效的 ISO 日期时间。")
    normalized = value.strip()
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IssueRepositoryError(f"{label} 必须是有效的 ISO 日期时间。") from exc
    return normalized[:80]


def _write_settings(database_path: Path, values: dict[str, Any]) -> None:
    """Atomically write one or more settings; caller updates memory afterwards."""
    encoded_values = {
        key: json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        for key, value in values.items()
    }
    path = database_path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 30000")
        initialize_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        for key, value_json in encoded_values.items():
            connection.execute(
                """
                INSERT INTO app_settings(key, value_json) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (key, value_json),
            )
        connection.commit()
    except Exception:
        if connection is not None:
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
        raise
    finally:
        if connection is not None:
            connection.close()


class IssueRepository:
    """SQLite-backed editing/publishing state for the daily news module."""

    def __init__(
        self,
        database_path: str | Path,
        legacy_store: Any = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser()
        self._lock = RLock()

        settings = _read_settings(self.database_path)
        issue_fallback = _legacy_document(legacy_store, LEGACY_ISSUE_KEY)
        if ISSUE_SETTING not in settings and issue_fallback is _MISSING:
            imported = load_imported_data(self.database_path)
            if imported["status"] == "unavailable":
                raise IssueRepositoryError(
                    imported.get("error") or "无法读取迁移包中的新闻数据。"
                )
            if issue_fallback is _MISSING:
                issue_fallback = _legacy_document(imported, LEGACY_ISSUE_KEY)

        issue_value = settings.get(ISSUE_SETTING, issue_fallback)
        layout_value = settings.get(LAYOUT_SETTING, _MISSING)
        if issue_value is _MISSING:
            issue_value = None
        if layout_value is _MISSING:
            layout_value = None

        draft_value = settings.get(DRAFT_SETTING)
        if draft_value is not None:
            try:
                draft_value = normalize_issue(draft_value)
            except NewsImportError as exc:
                raise IssueRepositoryError(f"草稿无效：{exc}") from exc

        self._state: dict[str, Any] = {
            **_normalize_store(issue_value),
            "draft": draft_value,
            "linkInbox": _normalize_links(settings.get(INBOX_SETTING)),
            "layout": _normalize_layout(layout_value),
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a detached copy of all persisted news-module state."""
        with self._lock:
            return deepcopy(self._state)

    def _commit(self, next_state: dict[str, Any], changed: dict[str, Any]) -> None:
        try:
            _write_settings(self.database_path, changed)
        except Exception as exc:
            raise IssueRepositoryError(f"保存新闻数据失败：{exc}") from exc
        self._state = next_state

    def save_draft(self, issue: Any) -> dict[str, Any]:
        try:
            draft = normalize_issue(issue)
        except NewsImportError as exc:
            raise IssueRepositoryError(f"草稿无效：{exc}") from exc
        with self._lock:
            next_state = deepcopy(self._state)
            next_state["draft"] = draft
            self._commit(next_state, {DRAFT_SETTING: draft})
            return deepcopy(draft)

    def publish_draft(self, published_at: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._state["draft"] is None:
                raise IssueRepositoryError("当前没有可发布的草稿。")
            return self._publish_normalized_issue(
                deepcopy(self._state["draft"]), published_at
            )

    def publish_issue(
        self, issue: Any, published_at: str | None = None
    ) -> dict[str, Any]:
        """Atomically publish an in-memory issue without staging a draft first."""
        try:
            normalized_issue = normalize_issue(issue)
        except NewsImportError as exc:
            raise IssueRepositoryError(f"待发布刊期无效：{exc}") from exc
        with self._lock:
            return self._publish_normalized_issue(normalized_issue, published_at)

    def _publish_normalized_issue(
        self, issue: dict[str, Any], published_at: str | None
    ) -> dict[str, Any]:
        timestamp = _timestamp(published_at, "published_at")
        next_state = deepcopy(self._state)
        if next_state["active"] is not None:
            next_state["archive"].insert(
                0,
                {
                    "issue": deepcopy(next_state["active"]),
                    "publishedAt": timestamp,
                },
            )
        next_state["archive"] = next_state["archive"][:MAX_ARCHIVE_ITEMS]
        next_state["active"] = deepcopy(issue)
        next_state["draft"] = None
        store = {
            "active": next_state["active"],
            "archive": next_state["archive"],
        }
        self._commit(
            next_state,
            {ISSUE_SETTING: store, DRAFT_SETTING: None},
        )
        return deepcopy(next_state["active"])

    def load_history(self, index: int) -> dict[str, Any]:
        with self._lock:
            if isinstance(index, bool) or not isinstance(index, int):
                raise IssueRepositoryError("历史刊期序号必须是整数。")
            if not 0 <= index < len(self._state["archive"]):
                raise IssueRepositoryError("所选历史刊期不存在。")
            draft = deepcopy(self._state["archive"][index]["issue"])
            next_state = deepcopy(self._state)
            next_state["draft"] = draft
            self._commit(next_state, {DRAFT_SETTING: draft})
            return deepcopy(draft)

    def move_draft_item(self, group: str, index: int, delta: int) -> bool:
        if not isinstance(group, str) or group not in _ISSUE_GROUPS:
            raise IssueRepositoryError("只能调整 focus、highlights 或 articles 分组。")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (index, delta)):
            raise IssueRepositoryError("排序位置和移动距离必须是整数。")
        with self._lock:
            if self._state["draft"] is None:
                raise IssueRepositoryError("当前没有可调整的草稿。")
            next_index = index + delta
            items = self._state["draft"][group]
            if not 0 <= index < len(items):
                raise IssueRepositoryError("所选草稿条目不存在。")
            if delta == 0 or not 0 <= next_index < len(items):
                return False
            next_state = deepcopy(self._state)
            ordered_items = next_state["draft"][group]
            ordered_items[index], ordered_items[next_index] = (
                ordered_items[next_index],
                ordered_items[index],
            )
            draft = next_state["draft"]
            self._commit(next_state, {DRAFT_SETTING: draft})
            return True

    def add_link(self, url: str, added_at: str | None = None) -> bool:
        try:
            normalized_url = normalize_news_url(url)
        except NewsImportError as exc:
            raise IssueRepositoryError(f"新闻链接无效：{exc}") from exc
        timestamp = _timestamp(added_at, "addedAt")
        with self._lock:
            if any(item["url"] == normalized_url for item in self._state["linkInbox"]):
                return False
            next_state = deepcopy(self._state)
            next_state["linkInbox"].append(
                {"url": normalized_url, "addedAt": timestamp}
            )
            self._commit(
                next_state,
                {INBOX_SETTING: next_state["linkInbox"]},
            )
            return True

    def remove_link(self, index: int) -> dict[str, str]:
        if isinstance(index, bool) or not isinstance(index, int):
            raise IssueRepositoryError("素材箱序号必须是整数。")
        with self._lock:
            if not 0 <= index < len(self._state["linkInbox"]):
                raise IssueRepositoryError("所选素材链接不存在。")
            next_state = deepcopy(self._state)
            removed = next_state["linkInbox"].pop(index)
            self._commit(
                next_state,
                {INBOX_SETTING: next_state["linkInbox"]},
            )
            return deepcopy(removed)

    def save_layout(self, layout: Any) -> dict[str, Any]:
        normalized = _normalize_layout(layout)
        with self._lock:
            next_state = deepcopy(self._state)
            next_state["layout"] = normalized
            self._commit(next_state, {LAYOUT_SETTING: normalized})
            return deepcopy(normalized)


__all__ = ["IssueRepository", "IssueRepositoryError", "MAX_ARCHIVE_ITEMS"]
