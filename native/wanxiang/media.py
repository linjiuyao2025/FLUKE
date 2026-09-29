"""Local-first bookshelf/media tracking backed by a SQLite overlay.

The imported ``richangji-state-v1`` mediaItems are kept as an immutable base.
Native additions, view/filter preferences, and delete tombstones live in this
module's own row. Existing item dictionaries are copied without projecting
away unknown fields, cover data, or ``remoteId`` values.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import base64
import binascii
import json
import math
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Callable
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from .database import load_imported_data
from .json_utils import copy_json
from .migration import MigrationPackage


LEGACY_STATE_KEY = "richangji-state-v1"
_TABLE = "media_module_state"
MEDIA_TYPES = ("电影", "剧", "书", "番")
MEDIA_STATUSES = ("想看", "在看", "看完", "弃了")
MEDIA_STATUS_FILTERS = ("all", *MEDIA_STATUSES)
MEDIA_VIEWS = ("wall", "list")
MEDIA_RATING_FILTERS = (0, 3, 4, 5)
MAX_NAME_LENGTH = 60
MAX_REVIEW_LENGTH = 100
MAX_COVER_SOURCE_BYTES = 12 * 1024 * 1024
MAX_COVER_DIMENSIONS = (360, 480)
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COVER_PREFIX = "data:image/jpeg;base64,"


class MediaRepositoryError(ValueError):
    """Readable validation or persistence error for the media module."""


def _json_copy(value: Any, label: str) -> Any:
    return copy_json(value, label, MediaRepositoryError)


def _date_value(value: Any, label: str = "日期") -> str:
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise MediaRepositoryError(f"{label} 必须使用 YYYY-MM-DD 日期。")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MediaRepositoryError(f"{label} 必须是有效日期。") from exc
    if parsed.isoformat() != value:
        raise MediaRepositoryError(f"{label} 必须是有效日期。")
    return value


def _today_string(value: str | date | datetime | None) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        value = value.isoformat()
    return _date_value(value or date.today().isoformat(), "今天")


def _source_containers(source: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return parsed and raw migration mappings from any supported envelope."""
    if isinstance(source, MigrationPackage):
        return source.parsed_values, source.raw_values
    if isinstance(source, dict):
        parsed: dict[str, Any] = {}
        raw: dict[str, Any] = {}
        for name in ("parsed_values", "documents"):
            value = source.get(name)
            if isinstance(value, dict):
                parsed = value
                break
        for name in ("raw_values", "keys"):
            value = source.get(name)
            if isinstance(value, dict):
                raw = value
                break
        return parsed, raw
    return {}, {}


def _legacy_source(source: Any) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], bool]:
    """Copy legacy mediaItems/settings while retaining each full item object."""
    if isinstance(source, list):
        items = source
        settings: Any = {}
        draft: Any = {}
        has_main = True
    else:
        parsed, raw = _source_containers(source)
        main = parsed.get(LEGACY_STATE_KEY)
        if main is None and isinstance(source, dict) and LEGACY_STATE_KEY in source:
            main = source[LEGACY_STATE_KEY]
        if main is None and LEGACY_STATE_KEY in raw:
            encoded = raw.get(LEGACY_STATE_KEY)
            if encoded is not None:
                if not isinstance(encoded, str):
                    raise MediaRepositoryError("旧版主状态原文必须是 JSON 字符串。")
                try:
                    main = json.loads(encoded)
                except json.JSONDecodeError as exc:
                    raise MediaRepositoryError("旧版主状态原文不是有效 JSON。") from exc

        has_main = isinstance(main, dict)
        if main is not None and not isinstance(main, dict):
            raise MediaRepositoryError("旧版主状态必须是对象。")
        if has_main:
            items = main.get("mediaItems", [])
            settings = main.get("settings", {})
            drafts = main.get("drafts", {})
            if drafts is None:
                drafts = {}
            if not isinstance(drafts, dict):
                raise MediaRepositoryError("旧版表单草稿结构无效。")
            draft = drafts.get("mediaForm", {})
            if draft is None:
                draft = {}
        else:
            items = None
            settings = {}
            draft = {}
            if isinstance(source, dict):
                # The imported-data reader also returns normalized media rows.
                # This fallback is useful only for snapshots that have no
                # main document; the raw document remains preferred above.
                entities = source.get("entities")
                empty_snapshot = source.get("hasData") is False or source.get("status") in {
                    "empty", "unavailable",
                }
                if isinstance(entities, dict) and "media_items" in entities and not empty_snapshot:
                    items = entities.get("media_items", [])
                    has_main = True
                if items is None and "mediaItems" in source:
                    items = source.get("mediaItems")
                    settings = source.get("settings", {})
                    has_main = True
            if items is None:
                items = []

    if items is None:
        items = []
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise MediaRepositoryError("旧版 mediaItems 必须是对象数组。")
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise MediaRepositoryError("旧版 settings 必须是对象。")
    if draft is None:
        draft = {}
    if not isinstance(draft, dict):
        raise MediaRepositoryError("旧版书影音草稿必须是对象。")
    return (
        _json_copy(items, "旧版 mediaItems"),
        _json_copy(settings, "旧版媒体设置"),
        _json_copy(draft, "旧版书影音草稿"),
        has_main,
    )


def _valid_rating_filter(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return number if number in MEDIA_RATING_FILTERS else 0


def _normalize_settings(settings: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(settings)
    view = result.get("mediaView", "wall")
    status = result.get("mediaStatusFilter", "all")
    result["mediaView"] = view if isinstance(view, str) and view in MEDIA_VIEWS else "wall"
    result["mediaStatusFilter"] = (
        status if isinstance(status, str) and status in MEDIA_STATUS_FILTERS else "all"
    )
    result["mediaRatingFilter"] = _valid_rating_filter(result.get("mediaRatingFilter", 0))
    return result


def _initial_state(
    legacy_items: list[dict[str, Any]], legacy_settings: dict[str, Any], legacy_draft: dict[str, Any]
) -> dict[str, Any]:
    return {
        "legacyItems": legacy_items,
        "localItems": [],
        "deletedItems": [],
        "legacySettings": legacy_settings,
        "settingsOverrides": {},
        "localFields": [],
        "legacyDraft": legacy_draft,
        "draftFields": {},
        "draftCleared": False,
    }


def _normalize_runtime(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise MediaRepositoryError("本机书影音状态结构无效。")
    legacy = state.get("legacyItems", [])
    local = state.get("localItems", [])
    deleted = state.get("deletedItems", [])
    legacy_settings = state.get("legacySettings", {})
    overrides = state.get("settingsOverrides", {})
    local_fields = state.get("localFields", [])
    legacy_draft = state.get("legacyDraft", {})
    draft_fields = state.get("draftFields", {})
    draft_cleared = state.get("draftCleared", False)
    for value, label in ((legacy, "旧版媒体"), (local, "本机媒体")):
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise MediaRepositoryError(f"{label}必须是对象数组。")
    if not isinstance(deleted, list):
        raise MediaRepositoryError("本机媒体删除标记必须是数组。")
    clean_deleted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in deleted:
        if not isinstance(item, dict):
            raise MediaRepositoryError("本机媒体删除标记结构无效。")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise MediaRepositoryError("本机媒体删除标记缺少 id。")
        if item_id not in seen:
            clean_deleted.append({**item, "id": item_id})
            seen.add(item_id)
    if not isinstance(legacy_settings, dict) or not isinstance(overrides, dict):
        raise MediaRepositoryError("本机媒体设置结构无效。")
    if not isinstance(legacy_draft, dict) or not isinstance(draft_fields, dict):
        raise MediaRepositoryError("本机书影音草稿结构无效。")
    if not isinstance(draft_cleared, bool):
        raise MediaRepositoryError("本机书影音草稿状态无效。")
    if not isinstance(local_fields, list) or any(not isinstance(field, str) for field in local_fields):
        raise MediaRepositoryError("本机媒体设置来源标记无效。")
    allowed_fields = {"mediaView", "mediaStatusFilter", "mediaRatingFilter"}
    if any(field not in allowed_fields for field in local_fields):
        raise MediaRepositoryError("本机媒体设置来源标记包含不支持的字段。")
    clean_overrides = {key: value for key, value in overrides.items() if key in allowed_fields}
    normalized = {
        **state,
        "legacyItems": _json_copy(legacy, "旧版媒体"),
        "localItems": _json_copy(local, "本机媒体"),
        "deletedItems": _json_copy(clean_deleted, "本机媒体删除标记"),
        "legacySettings": _json_copy(legacy_settings, "旧版媒体设置"),
        "settingsOverrides": _json_copy(clean_overrides, "本机媒体设置覆盖"),
        "localFields": list(dict.fromkeys(local_fields)),
        "legacyDraft": _json_copy(legacy_draft, "旧版书影音草稿"),
        "draftFields": _json_copy(draft_fields, "本机书影音草稿覆盖"),
        "draftCleared": draft_cleared,
    }
    return normalized


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
    except MediaRepositoryError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise MediaRepositoryError(f"无法读取本机书影音状态：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def prepare_cover_file(path: str | Path) -> dict[str, Any]:
    """Decode one local image and mirror the old 12 MiB / 360x480 JPEG rule.

    No network or upload path is used. The result is a self-contained JPEG
    data URI suitable for storing in the local SQLite JSON overlay.
    """
    try:
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
        from PySide6.QtGui import QImageReader
    except ImportError as exc:  # pragma: no cover - runtime packaging failure path
        raise MediaRepositoryError("图片处理组件不可用，请检查桌面运行环境。") from exc

    raw_path = str(path)
    parsed = urlsplit(raw_path)
    is_windows_drive = bool(re.match(r"^[A-Za-z]:[\\/]", raw_path))
    if parsed.scheme and not is_windows_drive:
        if parsed.scheme.lower() != "file":
            raise MediaRepositoryError("封面必须来自本机图片文件。")
        local_path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:/", local_path):
            local_path = local_path[1:]
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            local_path = f"//{parsed.netloc}{local_path}"
    else:
        local_path = raw_path
    file_path = Path(local_path).expanduser()
    try:
        size_bytes = file_path.stat().st_size
    except OSError as exc:
        raise MediaRepositoryError("封面文件无法读取。") from exc
    if size_bytes <= 0:
        raise MediaRepositoryError("封面文件为空。")
    if size_bytes > MAX_COVER_SOURCE_BYTES:
        raise MediaRepositoryError("封面图片请控制在 12MB 以内。")

    reader = QImageReader(str(file_path))
    reader.setAutoTransform(True)
    if not reader.canRead():
        raise MediaRepositoryError("封面格式不支持或图片已损坏。")
    image = reader.read()
    if image.isNull() or image.width() <= 0 or image.height() <= 0:
        raise MediaRepositoryError("封面格式不支持或图片已损坏。")

    max_width, max_height = MAX_COVER_DIMENSIONS
    ratio = min(max_width / image.width(), max_height / image.height(), 1.0)
    if ratio < 1.0:
        target_width = max(1, round(image.width() * ratio))
        target_height = max(1, round(image.height() * ratio))
        image = image.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    output = QByteArray()
    buffer = QBuffer(output)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise MediaRepositoryError("封面暂时无法转换。")
    try:
        saved = image.save(buffer, "JPEG", 72)
    finally:
        buffer.close()
    if not saved:
        raise MediaRepositoryError("封面暂时无法转换为 JPEG。")
    encoded = bytes(output.toBase64()).decode("ascii")
    return {
        "dataUri": _COVER_PREFIX + encoded,
        "width": int(image.width()),
        "height": int(image.height()),
        "format": "JPEG",
    }


class MediaRepository:
    """Transactional media items and persistent wall/list filters."""

    def __init__(
        self,
        database_path: str | Path,
        legacy_store: Any = None,
        *,
        today_provider: Callable[[], str | date | datetime] | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser()
        self._lock = RLock()
        self._today_provider = today_provider or date.today
        source = legacy_store
        if source is None:
            imported = load_imported_data(self.database_path)
            if imported.get("status") == "unavailable":
                raise MediaRepositoryError(imported.get("error") or "无法读取旧版导入数据。")
            source = imported
        legacy_items, legacy_settings, legacy_draft, _ = _legacy_source(source)
        self._materialize_if_missing(_initial_state(legacy_items, legacy_settings, legacy_draft))
        runtime = _read_runtime(self.database_path)
        if runtime is None:
            raise MediaRepositoryError("无法初始化本机书影音状态。")
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
            raise MediaRepositoryError(f"初始化本机书影音状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _commit(self, state: dict[str, Any]) -> None:
        cloned = _normalize_runtime(_json_copy(state, "本机书影音状态"))
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
            raise MediaRepositoryError(f"保存本机书影音状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        self._state = cloned

    def _today(self) -> str:
        try:
            return _today_string(self._today_provider())
        except (TypeError, ValueError) as exc:
            raise MediaRepositoryError("本机日期来源无效。") from exc

    def legacy_items(self) -> list[dict[str, Any]]:
        """Return a copy of the immutable imported array, including unknown fields."""
        with self._lock:
            return _json_copy(self._state["legacyItems"], "旧版媒体")

    def deleted_item_ids(self) -> list[str]:
        with self._lock:
            return [item["id"] for item in self._state["deletedItems"]]

    def settings(self) -> dict[str, Any]:
        with self._lock:
            merged = {
                **deepcopy(self._state["legacySettings"]),
                **deepcopy(self._state["settingsOverrides"]),
            }
        return _normalize_settings(merged)

    def _visible_items(self) -> list[dict[str, Any]]:
        deleted = set(self.deleted_item_ids())
        local_ids = {
            str(item.get("id", "")) for item in self._state["localItems"]
            if item.get("id") is not None
        }
        rows = [
            item for item in self._state["legacyItems"]
            if str(item.get("id", "")) not in deleted
            and str(item.get("id", "")) not in local_ids
        ]
        rows.extend(
            item for item in self._state["localItems"]
            if str(item.get("id", "")) not in deleted
        )
        return _json_copy(rows, "有效书影音条目")

    @staticmethod
    def _sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda item: str(item.get("date", "")), reverse=True)

    def items(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._sort_items(self._visible_items())

    def filtered_items(self) -> list[dict[str, Any]]:
        settings = self.settings()
        rows = self.items()
        status_filter = settings["mediaStatusFilter"]
        rating_filter = settings["mediaRatingFilter"]
        return [
            item for item in rows
            if (status_filter == "all" or item.get("status") == status_filter)
            and (rating_filter == 0 or self._rating(item) >= rating_filter)
        ]

    @staticmethod
    def _rating(item: dict[str, Any]) -> int:
        value = item.get("rating", 0)
        if isinstance(value, bool):
            return 0
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return 0
        return int(number) if math.isfinite(number) and number.is_integer() else 0

    @staticmethod
    def _name(item: dict[str, Any]) -> str:
        value = item.get("name", "")
        return value if isinstance(value, str) else ""

    def summary(self, today: str | date | None = None) -> dict[str, Any]:
        today_key = _today_string(today) if today is not None else self._today()
        year = today_key[:4]
        items = self.items()
        finished = [
            item for item in items
            if item.get("status") == "看完"
            and isinstance(item.get("date"), str)
            and item["date"].startswith(year)
        ]
        rated = [item for item in finished if 1 <= self._rating(item) <= 5]
        average = sum(self._rating(item) for item in rated) / len(rated) if rated else None
        counts: dict[str, int] = {}
        for item in finished:
            kind = item.get("type")
            if isinstance(kind, str) and kind:
                counts[kind] = counts.get(kind, 0) + 1
        # Python dictionaries retain first-seen order, matching the old stable
        # sort when two media types share the same count.
        favorite = max(counts.items(), key=lambda entry: entry[1], default=("", 0))
        distribution = {
            str(rating): sum(self._rating(item) == rating for item in rated)
            for rating in range(1, 6)
        }
        queue = [item for item in items if item.get("status") in {"想看", "在看"}]
        in_progress = sum(item.get("status") == "在看" for item in items)
        return {
            "year": year,
            "yearFinishedCount": len(finished),
            "yearAverageRating": round(average, 1) if average is not None else None,
            "favoriteType": favorite[0],
            "ratingDistribution": distribution,
            "inProgressCount": in_progress,
            "wantCount": sum(item.get("status") == "想看" for item in items),
            "queue": [
                {"id": item.get("id", ""), "name": self._name(item),
                 "type": item.get("type", ""), "status": item.get("status", "")}
                for item in queue[:3]
            ],
        }

    def state(self, today: str | date | None = None) -> dict[str, Any]:
        return {
            "items": self.items(),
            "filteredItems": self.filtered_items(),
            "settings": self.settings(),
            "summary": self.summary(today),
            "today": _today_string(today) if today is not None else self._today(),
            "draft": self.draft(),
            "filter": {
                "status": self.settings()["mediaStatusFilter"],
                "rating": self.settings()["mediaRatingFilter"],
                "view": self.settings()["mediaView"],
            },
        }

    def adopt_imported_data(self, snapshot: Any) -> bool:
        """Refresh imported media/settings while retaining all native overlays."""
        items, settings, draft, has_main = _legacy_source(snapshot)
        if not has_main:
            return False
        with self._lock:
            state = deepcopy(self._state)
            state["legacyItems"] = items
            state["legacySettings"] = {
                **deepcopy(state["legacySettings"]),
                **settings,
            }
            if not state["draftCleared"] and not state["draftFields"]:
                state["legacyDraft"] = draft
            self._commit(state)
        return True

    def _set_setting(self, key: str, value: Any) -> Any:
        with self._lock:
            state = deepcopy(self._state)
            state["settingsOverrides"][key] = value
            if key not in state["localFields"]:
                state["localFields"].append(key)
            self._commit(state)
        return value

    def set_view(self, value: str) -> str:
        if not isinstance(value, str) or value not in MEDIA_VIEWS:
            raise MediaRepositoryError("视图必须是 wall 或 list。")
        return self._set_setting("mediaView", value)

    def set_status_filter(self, value: str) -> str:
        if not isinstance(value, str) or value not in MEDIA_STATUS_FILTERS:
            raise MediaRepositoryError("请选择有效的作品状态筛选。")
        return self._set_setting("mediaStatusFilter", value)

    def set_rating_filter(self, value: Any) -> int:
        if isinstance(value, bool):
            raise MediaRepositoryError("评分筛选必须为 0、3、4 或 5。")
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise MediaRepositoryError("评分筛选必须为 0、3、4 或 5。") from exc
        if not math.isfinite(numeric) or not numeric.is_integer():
            raise MediaRepositoryError("评分筛选必须为 0、3、4 或 5。")
        number = int(numeric)
        if number not in MEDIA_RATING_FILTERS:
            raise MediaRepositoryError("评分筛选必须为 0、3、4 或 5。")
        return self._set_setting("mediaRatingFilter", number)

    def draft(self) -> dict[str, Any]:
        """Return the effective media form draft without modifying its source."""
        with self._lock:
            if self._state["draftCleared"]:
                return {}
            return _json_copy(
                {**self._state["legacyDraft"], **self._state["draftFields"]},
                "书影音表单草稿",
            )

    def save_draft(self, fields: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(fields, dict):
            raise MediaRepositoryError("书影音表单草稿必须是对象。")
        copied = _json_copy(fields, "书影音表单草稿")
        with self._lock:
            state = deepcopy(self._state)
            state["draftFields"].update(copied)
            state["draftCleared"] = False
            self._commit(state)
            return self.draft()

    def clear_draft(self) -> None:
        """Hide imported draft data locally after a successful submission."""
        with self._lock:
            state = deepcopy(self._state)
            state["draftFields"] = {}
            state["draftCleared"] = True
            self._commit(state)

    def add_item(
        self,
        name: str,
        kind: str,
        status: str,
        rating: Any = 0,
        review: str = "",
        day: str | date | None = None,
        cover: str = "",
        *,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise MediaRepositoryError("作品名称不能为空。")
        clean_name = name.strip()
        if len(clean_name) > MAX_NAME_LENGTH:
            raise MediaRepositoryError("作品名称最多 60 个字符。")
        if not isinstance(kind, str) or kind not in MEDIA_TYPES:
            raise MediaRepositoryError("请选择电影、剧、书或番。")
        if not isinstance(status, str) or status not in MEDIA_STATUSES:
            raise MediaRepositoryError("请选择有效的作品状态。")
        if isinstance(rating, bool):
            raise MediaRepositoryError("评分必须是 0 到 5 的整数。")
        try:
            numeric_rating = float(rating)
        except (TypeError, ValueError, OverflowError) as exc:
            raise MediaRepositoryError("评分必须是 0 到 5 的整数。") from exc
        if not math.isfinite(numeric_rating) or not numeric_rating.is_integer() or not 0 <= numeric_rating <= 5:
            raise MediaRepositoryError("评分必须是 0 到 5 的整数。")
        if not isinstance(review, str):
            raise MediaRepositoryError("短评必须是文本。")
        clean_review = review.strip()
        if len(clean_review) > MAX_REVIEW_LENGTH:
            raise MediaRepositoryError("短评最多 100 个字符。")
        day_key = _today_string(day) if day is not None else self._today()
        if not isinstance(cover, str):
            raise MediaRepositoryError("封面数据无效。")
        if cover:
            if not cover.startswith(_COVER_PREFIX):
                raise MediaRepositoryError("新增封面必须是本机处理后的 JPEG 图片。")
            encoded = cover[len(_COVER_PREFIX):]
            try:
                base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise MediaRepositoryError("封面数据无效，请重新选择图片。") from exc
            if len(cover.encode("ascii", errors="ignore")) > MAX_COVER_SOURCE_BYTES:
                raise MediaRepositoryError("处理后的封面图片过大。")
        new_id = item_id or str(uuid4())
        if not isinstance(new_id, str) or not new_id.strip():
            raise MediaRepositoryError("媒体记录 id 必须是非空文本。")
        item = {
            "id": new_id,
            "name": clean_name,
            "type": kind,
            "status": status,
            "rating": int(numeric_rating),
            "review": clean_review,
            "date": day_key,
            "cover": cover,
            "sample": False,
        }
        with self._lock:
            visible = self._visible_items()
            if any(str(existing.get("id", "")) == new_id for existing in visible):
                raise MediaRepositoryError("媒体记录 id 已存在。")
            if new_id in {entry["id"] for entry in self._state["deletedItems"]}:
                raise MediaRepositoryError("媒体记录 id 已被本机删除标记占用。")
            state = deepcopy(self._state)
            state["localItems"].append(item)
            state["draftFields"] = {}
            state["draftCleared"] = True
            self._commit(state)
        return deepcopy(item)

    def delete_item(self, item_id: str) -> bool:
        if not isinstance(item_id, str) or not item_id:
            raise MediaRepositoryError("媒体记录 id 无效。")
        with self._lock:
            target = next(
                (item for item in self._visible_items() if str(item.get("id", "")) == item_id),
                None,
            )
            if target is None:
                return False
            state = deepcopy(self._state)
            local_index = next(
                (index for index, item in enumerate(state["localItems"])
                 if str(item.get("id", "")) == item_id),
                None,
            )
            if local_index is not None:
                state["localItems"].pop(local_index)
            elif not any(item.get("id") == item_id for item in state["deletedItems"]):
                state["deletedItems"].append({"id": item_id})
            self._commit(state)
            return True

    def activity_items(self) -> list[dict[str, Any]]:
        """Return effective imported/local items for the daily-review bridge.

        DailyRepository applies the old rule (personal, non-sample, exact
        yesterday date). This list is intentionally not an archive record set.
        """
        return self.items()


__all__ = [
    "MAX_COVER_DIMENSIONS",
    "MAX_COVER_SOURCE_BYTES",
    "MAX_NAME_LENGTH",
    "MAX_REVIEW_LENGTH",
    "MEDIA_RATING_FILTERS",
    "MEDIA_STATUSES",
    "MEDIA_STATUS_FILTERS",
    "MEDIA_TYPES",
    "MEDIA_VIEWS",
    "MediaRepository",
    "MediaRepositoryError",
    "prepare_cover_file",
]
