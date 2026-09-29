"""SQLite-backed preferences for the daily news topic and source chooser.

The legacy application stores topics and source preferences in two independent
localStorage keys. This repository presents them as one native state record,
while leaving the imported legacy JSON untouched in the migration tables.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any

from .database import load_imported_data
from .json_utils import strict_json_loads
from .migration import MigrationPackage


LEGACY_TOPICS_KEY = "wanxiang-issue-topics-v1"
LEGACY_PREFERENCES_KEY = "wanxiang-issue-preferences-v1"
_TABLE = "issue_preferences_state"
_SOURCE_DELIMITERS = str.maketrans({",": "、", "，": "、", ";": "、", "；": "、"})

TOPIC_OPTIONS: tuple[tuple[str, str], ...] = (
    ("news", "新闻与时事"),
    ("domestic", "国内"),
    ("international", "国际"),
    ("finance", "财经商业"),
    ("technology", "科技数码"),
    ("ai", "人工智能"),
    ("games", "游戏"),
    ("culture", "文化影视"),
    ("health", "健康"),
    ("life", "生活方式"),
    ("other", "其他"),
)

PRESET_SOURCES: tuple[str, ...] = (
    "财新网",
    "澎湃明查",
    "端传媒",
    "新华社",
    "Reuters",
    "Associated Press",
    "ProPublica",
    "Rest of World",
    "Ars Technica",
    "The Guardian",
    "Floodlight",
    "Nature",
    "Science",
    "IEEE Spectrum",
    "Game Developer",
)

_TOPIC_LABELS = dict(TOPIC_OPTIONS)
_PRESET_SOURCE_SET = frozenset(PRESET_SOURCES)
_DEFAULT_STATE: dict[str, Any] = {
    "topics": [],
    "preferences": {"subtopics": "", "sources": "", "presetSources": []},
}
_MISSING = object()


class PreferencesRepositoryError(ValueError):
    """Readable validation or persistence error for news preferences."""


def _strict_json_loads(raw: str, label: str) -> Any:
    return strict_json_loads(raw, label, PreferencesRepositoryError)


def _limited_text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _split_sources(value: Any) -> list[str]:
    """Match the legacy chooser's comma/semicolon source list behavior."""
    if value is None or value is False or value == 0:
        raw = ""
    elif isinstance(value, str):
        raw = value
    else:
        # The old page used String(preferences.sources || "") when loading.
        raw = str(value)
    items = (_limited_text(part, 60) for part in raw.translate(_SOURCE_DELIMITERS).split("、"))
    return list(dict.fromkeys(item for item in items if item))


def _normalize_state(topics_value: Any, preferences_value: Any) -> dict[str, Any]:
    if not isinstance(topics_value, list):
        topics_value = []
    topics = list(
        dict.fromkeys(
            item.strip()
            for item in topics_value
            if isinstance(item, str) and item.strip()
        )
    )

    preferences = preferences_value if isinstance(preferences_value, dict) else {}
    subtopics = _limited_text(preferences.get("subtopics"), 240)
    raw_presets = preferences.get("presetSources", [])
    if not isinstance(raw_presets, list):
        raw_presets = []
    preset_candidates = [
        item.strip()
        for item in raw_presets
        if isinstance(item, str) and item.strip()
    ]
    # The old UI no longer had checkboxes for removed presets. On render it
    # moved those names into the editable custom-source field and disclosed it.
    presets = list(
        dict.fromkeys(item for item in preset_candidates if item in _PRESET_SOURCE_SET)
    )
    legacy_sources = [
        _limited_text(item, 60)
        for item in preset_candidates
        if item not in _PRESET_SOURCE_SET
    ]
    sources = list(
        dict.fromkeys([*_split_sources(preferences.get("sources", "")), *legacy_sources])
    )
    custom_sources = "、".join(sources)[:240]

    return {
        "topics": topics,
        "preferences": {
            "subtopics": subtopics,
            "sources": custom_sources,
            "presetSources": presets,
        },
    }


def _extract_legacy_value(source: Any, key: str) -> Any:
    if isinstance(source, MigrationPackage):
        value = source.parsed_values.get(key, _MISSING)
        if value is not _MISSING:
            return value
        raw = source.raw_values.get(key)
        return _MISSING if raw is None else _strict_json_loads(raw, key)

    if not isinstance(source, dict):
        return _MISSING

    for container_name in ("parsed_values", "documents"):
        container = source.get(container_name)
        if isinstance(container, dict) and key in container:
            return container[key]

    raw_values = source.get("raw_values")
    if isinstance(raw_values, dict) and key in raw_values:
        raw = raw_values[key]
        return _MISSING if raw is None else _strict_json_loads(raw, key)

    if key in source:
        value = source[key]
        if isinstance(value, str):
            # A direct dictionary may carry either the parsed key value or the
            # raw localStorage string. JSON arrays/objects have distinct types.
            return _strict_json_loads(value, key)
        return value

    direct_name = "topics" if key == LEGACY_TOPICS_KEY else "preferences"
    if direct_name in source:
        return source[direct_name]
    return _MISSING


def _seed_state(source: Any) -> dict[str, Any]:
    if source is None:
        return deepcopy(_DEFAULT_STATE)
    topics = _extract_legacy_value(source, LEGACY_TOPICS_KEY)
    preferences = _extract_legacy_value(source, LEGACY_PREFERENCES_KEY)
    if topics is _MISSING and preferences is _MISSING:
        return deepcopy(_DEFAULT_STATE)
    return _normalize_state(
        [] if topics is _MISSING else topics,
        {} if preferences is _MISSING else preferences,
    )


def _encode_state(state: dict[str, Any]) -> str:
    return json.dumps(
        state,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _create_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            state_json TEXT NOT NULL,
            user_modified INTEGER NOT NULL DEFAULT 0
                CHECK (user_modified IN (0, 1))
        )
        """
    )


def _read_row(database_path: Path) -> tuple[dict[str, Any], bool] | None:
    if not database_path.is_file():
        return None
    connection: sqlite3.Connection | None = None
    try:
        uri = f"{database_path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        row = connection.execute(
            f"SELECT state_json, user_modified FROM {_TABLE} WHERE singleton = 1"
        ).fetchone()
        if row is None:
            return None
        state = _strict_json_loads(row[0], "本机关注偏好")
        if not isinstance(state, dict):
            raise PreferencesRepositoryError("本机关注偏好必须是对象。")
        return _normalize_state(state.get("topics"), state.get("preferences")), bool(row[1])
    except PreferencesRepositoryError:
        raise
    except sqlite3.Error:
        # No such table is the normal first-run case. Other SQLite errors are
        # surfaced by the write path when initialization is attempted.
        return None
    finally:
        if connection is not None:
            connection.close()


class IssuePreferencesRepository:
    """Store the daily-news focus topics and candidate sources in SQLite.

    ``legacy_store`` accepts a migration package, a ``load_imported_data``
    snapshot, or a direct ``{"topics": [...], "preferences": {...}}`` value.
    The source is used only when materializing a missing runtime row. Later
    calls to :meth:`adopt_imported_data` refresh that row only until a user has
    saved native preferences.
    """

    def __init__(
        self,
        database_path: str | Path,
        legacy_store: Any = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser()
        self._lock = RLock()

        existing = _read_row(self.database_path)
        if existing is None:
            source = legacy_store
            if source is None:
                imported = load_imported_data(self.database_path)
                if imported.get("status") == "unavailable":
                    raise PreferencesRepositoryError(
                        imported.get("error") or "无法读取旧版导入数据。"
                    )
                source = imported
            seed = _seed_state(source)
            self._materialize_if_missing(seed)
            existing = _read_row(self.database_path)
            if existing is None:
                raise PreferencesRepositoryError("无法初始化关注偏好状态。")

        self._state, self._user_modified = existing

    def _materialize_if_missing(self, state: dict[str, Any]) -> None:
        path = self.database_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("BEGIN IMMEDIATE")
            _create_table(connection)
            connection.execute(
                f"""INSERT OR IGNORE INTO {_TABLE}
                    (singleton, state_json, user_modified) VALUES (1, ?, 0)""",
                (_encode_state(state),),
            )
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise PreferencesRepositoryError(f"初始化关注偏好失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def get(self) -> dict[str, Any]:
        """Return a detached snapshot using legacy-compatible field names."""
        with self._lock:
            return deepcopy(self._state)

    def save(self, topics: Any, preferences: Any) -> dict[str, Any]:
        """Atomically save both legacy preference keys as one native record."""
        if not isinstance(topics, list):
            raise PreferencesRepositoryError("关注主题必须是字符串数组。")
        if any(not isinstance(item, str) for item in topics):
            raise PreferencesRepositoryError("关注主题必须是字符串数组。")
        if not isinstance(preferences, dict):
            raise PreferencesRepositoryError("候选媒体偏好必须是对象。")
        if "subtopics" in preferences and not isinstance(preferences["subtopics"], str):
            raise PreferencesRepositoryError("细分选题必须是文本。")
        if "sources" in preferences and not isinstance(preferences["sources"], str):
            raise PreferencesRepositoryError("自定义来源必须是文本。")
        if "presetSources" in preferences and (
            not isinstance(preferences["presetSources"], list)
            or any(not isinstance(item, str) for item in preferences["presetSources"])
        ):
            raise PreferencesRepositoryError("预设媒体必须是字符串数组。")
        next_state = _normalize_state(topics, preferences)

        with self._lock:
            self._write_state(next_state, user_modified=True)
            self._state = next_state
            self._user_modified = True
            return deepcopy(self._state)

    def adopt_imported_data(self, legacy_store: Any) -> dict[str, Any]:
        """Adopt a newly imported snapshot unless native preferences were saved."""
        incoming = _seed_state(legacy_store)
        with self._lock:
            if self._user_modified:
                return deepcopy(self._state)
            self._write_state(incoming, user_modified=False)
            self._state = incoming
            return deepcopy(self._state)

    def _write_state(self, state: dict[str, Any], *, user_modified: bool) -> None:
        path = self.database_path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("BEGIN IMMEDIATE")
            _create_table(connection)
            connection.execute(
                f"""INSERT INTO {_TABLE} (singleton, state_json, user_modified)
                    VALUES (1, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        state_json = excluded.state_json,
                        user_modified = excluded.user_modified""",
                (_encode_state(state), int(user_modified)),
            )
            connection.commit()
        except Exception as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
            raise PreferencesRepositoryError(f"保存关注偏好失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()


__all__ = [
    "IssuePreferencesRepository",
    "LEGACY_PREFERENCES_KEY",
    "LEGACY_TOPICS_KEY",
    "PRESET_SOURCES",
    "PreferencesRepositoryError",
    "TOPIC_OPTIONS",
]
