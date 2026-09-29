"""Daily reflection, today's work, and focus-session business state.

The imported legacy snapshot is read-only. Mutable flow preferences and the
question desk are materialized in a separate SQLite table. Activity summaries
are projections over caller-supplied current records/habits/media (or the
read-only imported snapshot until runtime repositories are connected).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import json
import math
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4

from PySide6.QtGui import QGuiApplication
from PySide6.QtWebEngineQuick import QtWebEngineQuick

from .database import load_imported_data
from .json_utils import copy_json
from .migration import MigrationPackage


LEGACY_STATE_KEY = "richangji-state-v1"
LEGACY_QUESTIONS_KEY = "wanxiang-issue-questions-v1"
SPOTIFY_MIGRATION_DECISION = "external_link"
SPOTIFY_DECISION_NOTE = (
    "新版保留有效 Spotify 链接，并在专注页载入 Spotify 官方嵌入播放器。"
    "登录状态、内容地区和网络可能影响播放。"
)

# Qt Quick WebEngine must initialize its shared OpenGL context before the app
# creates QGuiApplication; main.py imports this module before doing so.
if QGuiApplication.instance() is None:
    QtWebEngineQuick.initialize()

_TABLE = "daily_flow_state"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FOCUS_MODES = {"pomodoro", "flowtime", "countdown"}
_MAX_TIMER_SECONDS = 10 * 365 * 24 * 60 * 60
_SPOTIFY_PATH_RE = re.compile(
    r"^/(?:intl-[a-z]{2}(?:-[A-Z]{2})?/)?"
    r"(?:track|album|playlist|episode|show)/[A-Za-z0-9]{10,40}/?$"
)
_TYPE_LABELS = {
    "money": "财务",
    "fitness": "健康",
    "planner": "日程",
    "home": "待买",
}


class DailyRepositoryError(ValueError):
    """Readable validation or persistence error for daily-flow state."""


def _json_copy(value: Any, label: str) -> Any:
    return copy_json(value, label, DailyRepositoryError)


def _valid_date(value: Any, label: str = "日期") -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise DailyRepositoryError(f"{label} 必须使用 YYYY-MM-DD 日期。")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise DailyRepositoryError(f"{label} 必须使用有效日期。") from exc
    if parsed.isoformat() != value:
        raise DailyRepositoryError(f"{label} 必须使用有效日期。")
    return value


def _text(value: Any, label: str, *, maximum: int | None = None) -> str:
    if not isinstance(value, str):
        raise DailyRepositoryError(f"{label} 必须是文本。")
    if maximum is not None and len(value) > maximum:
        raise DailyRepositoryError(f"{label} 最多 {maximum} 个字符。")
    return value


def _timer_seconds(value: Any, fallback: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    if isinstance(value, int):
        return max(0, min(_MAX_TIMER_SECONDS, value))
    try:
        numeric = float(value)
    except (OverflowError, ValueError):
        return fallback
    if not math.isfinite(numeric):
        return fallback
    return max(0, min(_MAX_TIMER_SECONDS, int(math.floor(numeric))))


def _parse_timer_datetime(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        # Legacy localStorage stores Date.now() values in milliseconds.
        try:
            numeric = float(value)
            if not math.isfinite(numeric):
                return None
            return datetime.fromtimestamp(numeric / 1000, datetime.now().astimezone().tzinfo)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _normalize_focus_timer(value: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Normalize legacy or runtime timer values without failing app startup."""
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.astimezone()
    raw = value if isinstance(value, dict) else {}
    raw_mode = raw.get("mode")
    mode = raw_mode if isinstance(raw_mode, str) and raw_mode in _FOCUS_MODES else "pomodoro"
    if mode == "pomodoro":
        duration = 1500
    elif mode == "flowtime":
        duration = 0
    else:
        raw_duration = _timer_seconds(raw.get("durationSeconds"), 1500)
        minutes = int(round(raw_duration / 60)) if raw_duration else 25
        duration = max(300, min(28_800, minutes * 60))
    elapsed = _timer_seconds(raw.get("elapsedSeconds"), 0)
    if mode == "flowtime":
        remaining = 0
    else:
        remaining = min(duration, _timer_seconds(raw.get("remainingSeconds"), duration))
    checkpoint = _parse_timer_datetime(raw.get("checkpointAt"))
    running = raw.get("running") is True and checkpoint is not None
    if checkpoint is None:
        checkpoint = current
    else:
        checkpoint = checkpoint.astimezone(current.tzinfo)
    # Ignore hostile/future checkpoints. The timer is re-anchored at startup.
    if checkpoint.timestamp() > current.timestamp() + 60:
        checkpoint = current
    session_id = raw.get("sessionId")
    task_id = raw.get("taskId")
    task_title = raw.get("taskTitle")
    return {
        "mode": mode,
        "durationSeconds": duration,
        "remainingSeconds": remaining,
        "elapsedSeconds": elapsed,
        "running": running and (mode == "flowtime" or remaining > 0),
        "checkpointAt": checkpoint.isoformat(timespec="milliseconds"),
        "sessionId": session_id[:80] if isinstance(session_id, str) else "",
        "taskId": task_id[:160] if isinstance(task_id, str) else "",
        "taskTitle": task_title[:300] if isinstance(task_title, str) else "",
    }


def _normalize_focus_sessions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    sessions: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            continue
        try:
            day = _valid_date(raw.get("date"), "专注记录日期")
        except DailyRepositoryError:
            continue
        seconds = _timer_seconds(raw.get("seconds"), 0)
        if seconds < 1:
            continue
        raw_mode = raw.get("mode")
        mode = raw_mode if isinstance(raw_mode, str) and raw_mode in _FOCUS_MODES else "pomodoro"
        session_id = raw.get("id")
        started = raw.get("startedAt", "")
        ended = raw.get("endedAt", "")
        if not isinstance(started, str):
            started = ""
        if not isinstance(ended, str):
            ended = ""
        try:
            cloned = _json_copy(raw, "专注记录")
        except DailyRepositoryError:
            continue
        cloned.update({
            "id": session_id[:80] if isinstance(session_id, str) and session_id else f"legacy-focus-{day}-{index}",
            "date": day,
            "seconds": seconds,
            "mode": mode,
            "startedAt": started[:80],
            "endedAt": ended[:80],
            "taskId": raw.get("taskId")[:160] if isinstance(raw.get("taskId"), str) else "",
            "taskTitle": raw.get("taskTitle")[:300] if isinstance(raw.get("taskTitle"), str) else "",
            "standalone": True,
        })
        sessions.append(cloned)
    return sessions


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _timer_now(clock: Callable[[], datetime], supplied: datetime | None) -> datetime:
    value = supplied if supplied is not None else clock()
    if not isinstance(value, datetime):
        raise DailyRepositoryError("计时器时钟必须返回日期时间。")
    return value.astimezone() if value.tzinfo is None else value


def _split_focus_interval(start: datetime, seconds: int) -> list[tuple[str, int, datetime, datetime]]:
    """Split integer work seconds at local midnight, including DST boundaries."""
    if seconds <= 0:
        return []
    cursor = start.astimezone() if start.tzinfo is None else start
    remaining = seconds
    pieces: list[tuple[str, int, datetime, datetime]] = []
    while remaining > 0:
        local_cursor = cursor.astimezone()
        day = local_cursor.date()
        boundary = datetime.combine(day + timedelta(days=1), time.min, tzinfo=local_cursor.tzinfo)
        until_boundary = boundary.timestamp() - local_cursor.timestamp()
        # Integer accounting assigns a fractional final second to the day it began in.
        day_seconds = max(1, int(math.ceil(until_boundary)))
        allocated = min(remaining, day_seconds)
        end = datetime.fromtimestamp(cursor.timestamp() + allocated, cursor.tzinfo)
        pieces.append((day.isoformat(), allocated, local_cursor, end.astimezone()))
        cursor = end
        remaining -= allocated
    return pieces


def _source_parts(source: Any) -> tuple[dict[str, Any], list[Any], bool]:
    """Extract main state and issue questions without mutating source data."""
    if isinstance(source, MigrationPackage):
        parsed = source.parsed_values
        main = parsed.get(LEGACY_STATE_KEY)
        questions = parsed.get(LEGACY_QUESTIONS_KEY) or []
        return _state_from_value(main), _questions_from_value(questions), isinstance(main, dict)
    if not isinstance(source, dict):
        raise DailyRepositoryError("旧版每日流程来源必须是对象。")

    main: Any = None
    questions: Any = None
    has_main = False
    for container_name in ("parsed_values", "documents"):
        container = source.get(container_name)
        if isinstance(container, dict):
            if LEGACY_STATE_KEY in container:
                main = container[LEGACY_STATE_KEY]
                has_main = isinstance(main, dict)
            if LEGACY_QUESTIONS_KEY in container:
                questions = container[LEGACY_QUESTIONS_KEY]
    if LEGACY_STATE_KEY in source:
        main = source[LEGACY_STATE_KEY]
        has_main = isinstance(main, dict)
    if LEGACY_QUESTIONS_KEY in source:
        questions = source[LEGACY_QUESTIONS_KEY]

    raw_values = source.get("raw_values")
    if isinstance(raw_values, dict):
        if LEGACY_STATE_KEY in raw_values and main is None:
            main = _parse_raw(raw_values[LEGACY_STATE_KEY], "旧版主状态")
            has_main = isinstance(main, dict)
        if LEGACY_QUESTIONS_KEY in raw_values and questions is None:
            questions = _parse_raw(raw_values[LEGACY_QUESTIONS_KEY], "旧版问题簿")

    entities = source.get("entities")
    if main is None and isinstance(entities, dict):
        main = {
            "records": entities.get("records", []),
            "habits": entities.get("habits", []),
            "mediaItems": entities.get("media_items", []),
            "settings": {},
        }
    if main is None and ("records" in source or "settings" in source):
        main = source
        has_main = True
    if not isinstance(main, dict):
        main = {}
    if questions is None:
        questions = []
    if not isinstance(questions, list):
        raise DailyRepositoryError("旧版问题簿必须是数组。")
    return _state_from_value(main), _questions_from_value(questions), has_main


def _parse_raw(raw: Any, label: str) -> Any:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise DailyRepositoryError(f"{label}原文必须是 JSON 字符串。")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DailyRepositoryError(f"{label}原文不是有效 JSON。") from exc


def _state_from_value(main: Any) -> dict[str, Any]:
    if main is None:
        return {}
    if not isinstance(main, dict):
        raise DailyRepositoryError("旧版主状态必须是对象。")
    settings = main.get("settings", {})
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise DailyRepositoryError("旧版 settings 必须是对象。")
    notes = settings.get("dailyFlowNotes", {})
    if notes is None:
        notes = {}
    if not isinstance(notes, dict):
        raise DailyRepositoryError("旧版 dailyFlowNotes 必须是对象。")
    normalized_notes: dict[str, str] = {}
    for key, value in notes.items():
        day = _valid_date(key, "跟进线索日期")
        if not isinstance(value, str):
            raise DailyRepositoryError("旧版跟进线索必须是文本。")
        normalized_notes[day] = value
    focus_task = settings.get("dailyFlowFocusTask", "")
    if focus_task is None:
        focus_task = ""
    if not isinstance(focus_task, str):
        raise DailyRepositoryError("旧版 dailyFlowFocusTask 必须是文本。")
    spotify_url = settings.get("dailyFlowAudioUrl", "")
    if spotify_url is None:
        spotify_url = ""
    if not isinstance(spotify_url, str):
        raise DailyRepositoryError("旧版 dailyFlowAudioUrl 必须是文本。")
    focus_timer = _normalize_focus_timer(settings.get("flowTimer", {}))
    focus_sessions = _normalize_focus_sessions(settings.get("focusSessions", []))
    activity: dict[str, list[dict[str, Any]]] = {}
    for field in ("records", "habits", "mediaItems"):
        items = main.get(field, [])
        if items is None:
            items = []
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise DailyRepositoryError(f"旧版 {field} 必须是对象数组。")
        activity[field] = _json_copy(items, f"旧版 {field}")
    return {
        "notes": normalized_notes,
        "focusTask": focus_task,
        "spotifyUrl": spotify_url,
        "focusTimer": focus_timer,
        "focusSessions": focus_sessions,
        **activity,
    }


def _questions_from_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DailyRepositoryError("旧版问题簿必须是数组。")
    # Existing legacy string rows and full object rows (including unknown
    # fields) are preserved as-is in the native runtime projection.
    return _json_copy(value, "旧版问题簿")


def _empty_state() -> dict[str, Any]:
    return {
        "notes": {},
        "focusTask": "",
        "spotifyUrl": "",
        "focusTimer": _normalize_focus_timer({}),
        "focusSessions": [],
        "questions": [],
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
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_TABLE,)
        ).fetchone()
        if table is None:
            return None
        row = connection.execute(
            f"SELECT state_json FROM {_TABLE} WHERE singleton=1"
        ).fetchone()
        if row is None:
            return None
        state = json.loads(row[0])
        return _normalize_runtime(state)
    except DailyRepositoryError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        raise DailyRepositoryError(f"无法读取本机每日流程状态：{exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def _normalize_runtime(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise DailyRepositoryError("本机每日流程状态结构无效。")
    notes = state.get("notes", {})
    if not isinstance(notes, dict):
        raise DailyRepositoryError("本机跟进线索结构无效。")
    normalized_notes: dict[str, str] = {}
    for key, value in notes.items():
        normalized_notes[_valid_date(key, "跟进线索日期")] = _text(value, "跟进线索")
    # Initial values may come from old localStorage, whose existing contents
    # must survive even if a historical value exceeds today's input limits.
    focus = _text(state.get("focusTask", ""), "专注任务")
    spotify = _text(state.get("spotifyUrl", ""), "Spotify 链接")
    focus_timer = _normalize_focus_timer(state.get("focusTimer", {}))
    focus_sessions = _normalize_focus_sessions(state.get("focusSessions", []))
    questions = state.get("questions", [])
    if not isinstance(questions, list):
        raise DailyRepositoryError("本机问题簿必须是数组。")
    local_fields = state.get("localFields", [])
    if not isinstance(local_fields, list) or any(not isinstance(x, str) for x in local_fields):
        raise DailyRepositoryError("本机字段来源标记无效。")
    return {
        **state,
        "notes": normalized_notes,
        "focusTask": focus,
        "spotifyUrl": spotify,
        "focusTimer": focus_timer,
        "focusSessions": focus_sessions,
        "questions": _json_copy(questions, "本机问题簿"),
        "localFields": list(dict.fromkeys(local_fields)),
    }


class DailyRepository:
    """Transactional daily-flow state and read-only activity projections.

    ``legacy_store`` accepts a validated migration package, its loaded SQLite
    snapshot, or parsed ``richangji-state-v1`` data. The migrated raw source is
    never modified. Pass current runtime record/habit/media snapshots to the
    projection methods once those module repositories are available.
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
        self._clock = clock or _local_now
        source = legacy_store
        if source is None:
            imported = load_imported_data(self.database_path)
            if imported.get("status") == "unavailable":
                raise DailyRepositoryError(imported.get("error") or "无法读取旧版导入数据。")
            source = imported
        seed, questions, has_legacy = _source_parts(source)
        self._activity = {
            "records": seed.get("records", []),
            "habits": seed.get("habits", []),
            "mediaItems": seed.get("mediaItems", []),
        }
        seeded = {
            "notes": seed.get("notes", {}),
            "focusTask": seed.get("focusTask", ""),
            "spotifyUrl": seed.get("spotifyUrl", ""),
            "focusTimer": seed.get("focusTimer", _normalize_focus_timer({})),
            "focusSessions": seed.get("focusSessions", []),
            "questions": questions,
            "localFields": [],
        }
        self._materialize_if_missing(seeded)
        runtime = _read_runtime(self.database_path)
        if runtime is None:
            raise DailyRepositoryError("无法初始化本机每日流程状态。")
        # Imported state should take precedence only at first materialization.
        # If the table already existed, its runtime values remain authoritative.
        self._state = runtime
        self._has_legacy_snapshot = has_legacy

    @property
    def has_legacy_snapshot(self) -> bool:
        return self._has_legacy_snapshot

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
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                "state_json TEXT NOT NULL)"
            )
            exists = connection.execute(
                f"SELECT 1 FROM {_TABLE} WHERE singleton=1"
            ).fetchone()
            if exists is None:
                connection.execute(
                    f"INSERT INTO {_TABLE}(singleton,state_json) VALUES(1,?)",
                    (json.dumps(_normalize_runtime(initial), ensure_ascii=False, allow_nan=False,
                                separators=(",", ":")),),
                )
            connection.commit()
        except Exception as exc:
            if connection is not None:
                connection.rollback()
            raise DailyRepositoryError(f"初始化每日流程状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _commit(self, state: dict[str, Any]) -> None:
        cloned = _normalize_runtime(_json_copy(state, "每日流程状态"))
        encoded = json.dumps(cloned, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":"))
        connection: sqlite3.Connection | None = None
        try:
            path = self.database_path.resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(path), timeout=30, isolation_level=None)
            connection.execute("PRAGMA busy_timeout=30000")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                "state_json TEXT NOT NULL)"
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
            raise DailyRepositoryError(f"保存每日流程状态失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        self._state = cloned

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "notes": deepcopy(self._state["notes"]),
                "focusTask": self._state["focusTask"],
                "spotifyUrl": self._state["spotifyUrl"],
                "focusTimer": deepcopy(self._state["focusTimer"]),
                "focusSessions": deepcopy(self._state["focusSessions"]),
                "questions": deepcopy(self._state["questions"]),
                "spotifyMigrationDecision": SPOTIFY_MIGRATION_DECISION,
                "spotifyDecisionNote": SPOTIFY_DECISION_NOTE,
            }

    def follow_up_for(self, day: str) -> str:
        day = _valid_date(day)
        with self._lock:
            return self._state["notes"].get(day, "")

    def save_follow_up(self, day: str, text: str) -> str:
        day = _valid_date(day)
        text = _text(text, "明日跟进线索", maximum=500).strip()
        with self._lock:
            state = deepcopy(self._state)
            state["notes"][day] = text
            self._mark_local(state, "notes")
            self._commit(state)
        return text

    def focus_task(self) -> str:
        with self._lock:
            return self._state["focusTask"]

    def focus_timer(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state["focusTimer"])

    def _append_standalone_focus_work(
        self,
        state: dict[str, Any],
        timer: dict[str, Any],
        started: datetime,
        seconds: int,
    ) -> None:
        if timer.get("taskId") or seconds < 1:
            return
        session_id = timer.get("sessionId") or str(uuid4())
        timer["sessionId"] = session_id
        sessions = state["focusSessions"]
        for day, allocated, segment_start, segment_end in _split_focus_interval(started, seconds):
            existing = next((row for row in sessions
                             if row.get("id") == session_id and row.get("date") == day), None)
            if existing is None:
                sessions.append({
                    "id": session_id,
                    "date": day,
                    "seconds": allocated,
                    "mode": timer["mode"],
                    "startedAt": segment_start.isoformat(timespec="seconds"),
                    "endedAt": segment_end.isoformat(timespec="seconds"),
                    "taskId": "",
                    "taskTitle": timer["taskTitle"],
                    "standalone": True,
                })
            else:
                existing["seconds"] = _timer_seconds(existing.get("seconds")) + allocated
                existing["endedAt"] = segment_end.isoformat(timespec="seconds")
                existing["taskTitle"] = timer["taskTitle"]
        state["focusSessions"] = sessions[-100_000:]
        self._mark_local(state, "focusSessions")

    def _advance_focus(
        self,
        state: dict[str, Any],
        now: datetime,
        *,
        pause: bool = False,
        reset: bool = False,
    ) -> tuple[int, bool]:
        timer = FocusTimer.from_state(state["focusTimer"], clock=self._clock)
        started, worked, completed = timer.advance(now)
        if worked:
            if not timer.task_id and not timer.session_id:
                timer.session_id = str(uuid4())
            self._append_standalone_focus_work(state, timer.to_state(), started, worked)
            self._mark_local(state, "focusTimer")
        if pause:
            timer.running = False
            timer.checkpoint_at = now
        if completed:
            timer.session_id = ""
        if reset:
            timer.running = False
            timer.remaining_seconds = timer.duration_seconds
            timer.elapsed_seconds = 0
            timer.checkpoint_at = now
            timer.session_id = ""
        state["focusTimer"] = timer.to_state()
        return worked, completed

    def configure_focus(self, mode: str, duration_minutes: int = 25, *, now: datetime | None = None) -> None:
        if not isinstance(mode, str) or mode not in _FOCUS_MODES:
            raise DailyRepositoryError("专注计时模式无效。")
        if mode == "countdown" and (
            isinstance(duration_minutes, bool)
            or not isinstance(duration_minutes, int)
            or not 5 <= duration_minutes <= 480
        ):
            raise DailyRepositoryError("倒计时须为 5 至 480 分钟。")
        timestamp = _timer_now(self._clock, now)
        duration = 1500 if mode == "pomodoro" else duration_minutes * 60 if mode == "countdown" else 0
        with self._lock:
            state = deepcopy(self._state)
            timer = deepcopy(state["focusTimer"])
            if timer.get("running"):
                raise DailyRepositoryError("请先暂停计时，再调整计时方式。")
            timer.update({
                "mode": mode,
                "durationSeconds": duration,
                "remainingSeconds": duration,
                "elapsedSeconds": 0,
                "running": False,
                "checkpointAt": timestamp.isoformat(timespec="milliseconds"),
                "sessionId": "",
            })
            state["focusTimer"] = timer
            self._mark_local(state, "focusTimer")
            self._commit(state)

    def toggle_focus(
        self,
        task_id: str = "",
        task_title: str = "",
        *,
        now: datetime | None = None,
    ) -> tuple[int, bool, bool]:
        task_id = _text(task_id, "专注任务 id", maximum=160)
        task_title = _text(task_title, "专注任务", maximum=300)
        timestamp = _timer_now(self._clock, now)
        with self._lock:
            state = deepcopy(self._state)
            timer = FocusTimer.from_state(state["focusTimer"], clock=self._clock)
            if timer.running:
                worked, completed = self._advance_focus(state, timestamp, pause=True)
                self._mark_local(state, "focusTimer")
                self._commit(state)
                return worked, completed, False

            fresh = timer.mode != "flowtime" and timer.remaining_seconds == 0
            changed_task = bool(task_id or task_title) and (
                task_id != timer.task_id or task_title != timer.task_title
            )
            if fresh:
                timer.elapsed_seconds = 0
                timer.remaining_seconds = timer.duration_seconds
            if timer.elapsed_seconds == 0 or fresh or not timer.task_title or changed_task:
                timer.task_id = task_id
                timer.task_title = task_title
                timer.session_id = ""
                if task_title:
                    state["focusTask"] = task_title[:100]
                    self._mark_local(state, "focusTask")
            if not timer.session_id:
                timer.session_id = str(uuid4())
            timer.running = True
            timer.checkpoint_at = timestamp
            state["focusTimer"] = timer.to_state()
            self._mark_local(state, "focusTimer")
            self._commit(state)
            return 0, False, True

    def checkpoint_focus(self, *, now: datetime | None = None) -> tuple[int, bool]:
        timestamp = _timer_now(self._clock, now)
        with self._lock:
            if not self._state["focusTimer"].get("running"):
                return 0, False
            state = deepcopy(self._state)
            result = self._advance_focus(state, timestamp)
            self._mark_local(state, "focusTimer")
            self._commit(state)
            return result

    def pause_focus(self, *, now: datetime | None = None) -> tuple[int, bool]:
        timestamp = _timer_now(self._clock, now)
        with self._lock:
            if not self._state["focusTimer"].get("running"):
                return 0, False
            state = deepcopy(self._state)
            result = self._advance_focus(state, timestamp, pause=True)
            self._mark_local(state, "focusTimer")
            self._commit(state)
            return result

    def reset_focus(self, *, now: datetime | None = None) -> tuple[int, bool]:
        timestamp = _timer_now(self._clock, now)
        with self._lock:
            state = deepcopy(self._state)
            result = self._advance_focus(state, timestamp, pause=True, reset=True)
            self._mark_local(state, "focusTimer")
            self._commit(state)
            return result

    def save_focus_task(self, task: str) -> str:
        task = _text(task, "专注任务", maximum=100).strip()
        with self._lock:
            state = deepcopy(self._state)
            state["focusTask"] = task
            self._mark_local(state, "focusTask")
            self._commit(state)
        return task

    def spotify_url(self) -> str:
        with self._lock:
            return self._state["spotifyUrl"]

    def save_spotify_url(self, url: str) -> str:
        url = _text(url, "Spotify 链接", maximum=300).strip()
        if url and not _is_legacy_spotify_url(url):
            raise DailyRepositoryError("请提供旧版支持的 Spotify 单曲、专辑、播放列表或播客链接。")
        with self._lock:
            state = deepcopy(self._state)
            state["spotifyUrl"] = url
            self._mark_local(state, "spotifyUrl")
            self._commit(state)
        return url

    @staticmethod
    def _mark_local(state: dict[str, Any], field: str) -> None:
        if field not in state["localFields"]:
            state["localFields"].append(field)

    def questions(self) -> list[Any]:
        with self._lock:
            return deepcopy(self._state["questions"])

    def add_question(self, text: str, *, now: datetime | None = None) -> dict[str, Any]:
        text = _text(text, "问题", maximum=160).strip()
        if not text:
            raise DailyRepositoryError("问题不能为空。")
        timestamp = now or datetime.now().astimezone()
        if not isinstance(timestamp, datetime):
            raise DailyRepositoryError("问题时间无效。")
        question = {
            "text": text,
            "createdDate": timestamp.date().isoformat(),
            "createdAt": int(timestamp.timestamp() * 1000),
        }
        with self._lock:
            state = deepcopy(self._state)
            state["questions"] = [question, *state["questions"]][:12]
            self._mark_local(state, "questions")
            self._commit(state)
        return deepcopy(question)

    def remove_question(self, index: int) -> Any:
        if isinstance(index, bool) or not isinstance(index, int):
            raise DailyRepositoryError("问题位置无效。")
        with self._lock:
            if not 0 <= index < len(self._state["questions"]):
                raise DailyRepositoryError("这条问题已不存在。")
            state = deepcopy(self._state)
            removed = state["questions"].pop(index)
            self._mark_local(state, "questions")
            self._commit(state)
        return removed

    def adopt_imported_data(self, legacy_store: Any) -> None:
        """Adopt imported flow data for fields the user has not edited locally."""
        seed, questions, has_legacy = _source_parts(legacy_store)
        if not has_legacy:
            return
        with self._lock:
            state = deepcopy(self._state)
            local = set(state["localFields"])
            if "notes" not in local:
                state["notes"] = deepcopy(seed["notes"])
            if "focusTask" not in local:
                state["focusTask"] = seed["focusTask"]
            if "spotifyUrl" not in local:
                state["spotifyUrl"] = seed["spotifyUrl"]
            if "focusTimer" not in local:
                state["focusTimer"] = deepcopy(seed["focusTimer"])
            if "focusSessions" not in local:
                state["focusSessions"] = deepcopy(seed["focusSessions"])
            if "questions" not in local:
                state["questions"] = deepcopy(questions)
            self._commit(state)
            self._activity = {
                "records": seed.get("records", []),
                "habits": seed.get("habits", []),
                "mediaItems": seed.get("mediaItems", []),
            }
            self._has_legacy_snapshot = True

    def update_activity_snapshot(
        self,
        *,
        records: list[dict[str, Any]] | None = None,
        habits: list[dict[str, Any]] | None = None,
        media_items: list[dict[str, Any]] | None = None,
    ) -> None:
        """Supply fresh in-memory snapshots from the native life-module stores."""
        updates = (("records", records), ("habits", habits), ("mediaItems", media_items))
        candidate = deepcopy(self._activity)
        for key, value in updates:
            if value is not None:
                if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
                    raise DailyRepositoryError(f"{key} 必须是对象数组。")
                candidate[key] = _json_copy(value, key)
        self._activity = candidate

    def yesterday_review(self, today: str | None = None) -> dict[str, Any]:
        current = _valid_date(today or date.today().isoformat(), "今天")
        yesterday = (date.fromisoformat(current) - timedelta(days=1)).isoformat()
        with self._lock:
            records = deepcopy(self._activity["records"])
            habits = deepcopy(self._activity["habits"])
            media_items = deepcopy(self._activity["mediaItems"])
            focus_sessions = deepcopy(self._state["focusSessions"])
            previous_note = self._state["notes"].get(yesterday, "")
        items: list[dict[str, Any]] = []
        for index, record in enumerate(records):
            if record.get("sample") or record.get("date") != yesterday:
                continue
            title, detail, value = _record_presentation(record)
            extra = " · ".join(part for part in (detail, value) if part)
            items.append({
                "kind": _TYPE_LABELS.get(record.get("type"), "记录"),
                "title": title,
                "detail": extra,
                "time": _js_number(record.get("createdAt")) or 0,
                "sourceIndex": index,
            })
        for index, habit in enumerate(habits):
            if habit.get("sample"):
                continue
            created = habit.get("createdDate")
            if created and isinstance(created, str) and created > yesterday:
                continue
            entries = habit.get("entries") or {}
            completed = _js_number(entries.get(yesterday, 0)) or 0
            target = _js_number(habit.get("target", 1)) or 1
            unit = habit.get("unit") or ""
            if completed >= target:
                detail = f"昨日完成 · {_format_number(completed)}{unit}"
            elif completed > 0:
                detail = f"昨日进度 · {_format_number(completed)}/{_format_number(target)}{unit}"
            else:
                detail = "昨日未打卡"
            items.append({
                "kind": "习惯",
                "title": str(habit.get("name") or "习惯"),
                "detail": detail,
                "time": 0,
                "sourceIndex": len(records) + index,
            })
        for index, media in enumerate(media_items):
            if media.get("sample") or media.get("date") != yesterday:
                continue
            items.append({
                "kind": "影音",
                "title": str(media.get("name") or ""),
                "detail": media.get("status") or "已记录",
                "time": 0,
                "sourceIndex": len(records) + len(habits) + index,
            })
        focus_offset = len(records) + len(habits) + len(media_items)
        for index, record in enumerate(records):
            if record.get("type") != "planner" or record.get("sample"):
                continue
            data = record.get("data") if isinstance(record.get("data"), dict) else {}
            raw_sessions = data.get("sessions", [])
            if not isinstance(raw_sessions, list):
                continue
            for session_index, session in enumerate(raw_sessions):
                if not isinstance(session, dict):
                    continue
                seconds = _timer_seconds(session.get("seconds"), 0)
                if seconds < 1:
                    continue
                day_key = session.get("date")
                if day_key != yesterday:
                    started = _parse_timer_datetime(session.get("startedAt"))
                    if started is None:
                        continue
                    try:
                        day_slices = _split_focus_interval(started, seconds)
                    except (OverflowError, OSError, ValueError):
                        continue
                    seconds = sum(piece[1] for piece in day_slices if piece[0] == yesterday)
                    if seconds < 1:
                        continue
                mode = session.get("mode")
                mode_label = "Flowtime" if mode == "flowtime" else "倒计时" if mode == "countdown" else "番茄钟"
                title = session.get("taskTitle") or data.get("title") or "待办专注"
                stamp = _parse_timer_datetime(session.get("endedAt")) or _parse_timer_datetime(session.get("startedAt"))
                items.append({
                    "kind": "专注",
                    "title": str(title),
                    "detail": f"{_format_duration(seconds)} · {mode_label}",
                    "time": stamp.timestamp() * 1000 if stamp else 0,
                    "sourceIndex": focus_offset + index * 1000 + session_index,
                })
        for index, session in enumerate(focus_sessions):
            if not isinstance(session, dict) or session.get("date") != yesterday:
                continue
            seconds = _timer_seconds(session.get("seconds"), 0)
            if seconds < 1:
                continue
            mode = session.get("mode")
            mode_label = "Flowtime" if mode == "flowtime" else "倒计时" if mode == "countdown" else "番茄钟"
            title = session.get("taskTitle") or "独立专注"
            stamp = _parse_timer_datetime(session.get("endedAt")) or _parse_timer_datetime(session.get("startedAt"))
            items.append({
                "kind": "专注",
                "title": str(title),
                "detail": f"{_format_duration(seconds)} · {mode_label}",
                "time": stamp.timestamp() * 1000 if stamp else 0,
                "sourceIndex": focus_offset + len(records) * 1000 + index,
            })
        # JavaScript Array.sort is stable: equal timestamps retain source order.
        items.sort(key=lambda item: -item["time"])
        for item in items:
            item.pop("sourceIndex", None)
        return {
            "date": yesterday,
            "items": items,
            "count": len(items),
            "followUp": previous_note or "",
            "emptyMessage": "昨天在这套工作台里还没有个人记录。",
            "scope": "仅汇总此工作台昨日的非样本记录、习惯、书影音与专注时段。",
        }

    def today_work(self, today: str | None = None) -> dict[str, Any]:
        current = _valid_date(today or date.today().isoformat(), "今天")
        with self._lock:
            records = deepcopy(self._activity["records"])
        tasks = [
            item for item in records
            if item.get("type") == "planner" and item.get("date") == current
        ]
        tasks.sort(key=lambda item: -_js_number(item.get("createdAt")))
        unfinished = [item for item in tasks if not (item.get("data") or {}).get("done")
                      and not item.get("sample")]
        rendered = [_task_presentation(task) for task in tasks[:4]]
        candidates = [
            {"id": task.get("id"), "title": _task_title(task)}
            for task in unfinished
        ]
        return {
            "date": current,
            "tasks": rendered,
            "taskCount": len(tasks),
            "focusCandidates": candidates,
            "focusTask": self.focus_task(),
            "taskEmptyMessage": "今天还没有待办，给自己留点空间",
            "mailIntegration": "shortcut_only",
        }


def _js_number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _is_legacy_spotify_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "open.spotify.com"
            and bool(_SPOTIFY_PATH_RE.fullmatch(parsed.path))
        )
    except ValueError:
        return False


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _format_duration(seconds: int) -> str:
    minutes, remainder = divmod(max(0, seconds), 60)
    if minutes == 0:
        return f"{remainder}秒"
    return f"{minutes}分钟" if remainder == 0 else f"{minutes}分钟{remainder}秒"


def _money(value: Any) -> str:
    number = _js_number(value)
    rendered = f"{number:,.2f}".rstrip("0").rstrip(".")
    return f"¥{rendered}"


def _record_presentation(record: dict[str, Any]) -> tuple[str, str, str]:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    kind = record.get("type")
    if kind == "money":
        flow = data.get("flow")
        title = data.get("note") or data.get("category") or "一笔收支"
        detail = f"{data.get('category') or '其他'} · {'收入' if flow == 'income' else '支出'}"
        value = f"{'+' if flow == 'income' else '-'}{_money(data.get('amount'))}"
        return str(title), detail, value
    if kind == "planner":
        title = data.get("title") or "一项日程"
        effective_time = data.get("plannedStart") or data.get("time") or ""
        detail = f"{data.get('list') or '生活'} · {effective_time or '全天'} · {'已完成' if data.get('done') else '待完成'}"
        return str(title), detail, str(effective_time)
    if kind == "fitness":
        title = data.get("note") or "身体记录"
        detail = (f"{_format_number(_js_number(data.get('duration')))} 分钟运动"
                  if data.get("duration") else "体重记录")
        value = f"{data.get('weight')} kg" if data.get("weight") else ""
        return str(title), detail, value
    if kind == "home":
        title = data.get("name") or "待买物品"
        detail = f"{data.get('quantity') or '数量未填'} · {data.get('category') or '未分类'} · {'已买' if data.get('bought') else '待买'}"
        value = _money(data.get("price")) if data.get("price") else ""
        return str(title), detail, value
    return "生活记录", "", ""


def _task_title(record: dict[str, Any]) -> str:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    return str(data.get("title") or "一项日程")


def _task_presentation(record: dict[str, Any]) -> dict[str, Any]:
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    return {
        "id": record.get("id"),
        "title": _task_title(record),
        "list": data.get("list") or "生活",
        "note": data.get("note") or "",
        "time": data.get("plannedStart") or data.get("time") or "全天",
        "done": bool(data.get("done")),
        "sample": bool(record.get("sample")),
        "priority": data.get("priority") or "",
    }


@dataclass
class FocusTimer:
    """Clock-injectable focus timer model shared by storage and desktop bridge."""

    duration_seconds: int = 25 * 60
    remaining_seconds: int = 25 * 60
    running: bool = False
    mode: str = "pomodoro"
    elapsed_seconds: int = 0
    checkpoint_at: datetime | None = None
    session_id: str = ""
    task_id: str = ""
    task_title: str = ""
    clock: Callable[[], datetime] = field(default=_local_now, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.mode not in _FOCUS_MODES:
            raise DailyRepositoryError("专注计时模式无效。")
        if isinstance(self.duration_seconds, bool) or not isinstance(self.duration_seconds, int):
            raise DailyRepositoryError("专注时长必须是正整数秒。")
        if self.mode == "pomodoro":
            self.duration_seconds = 1500
        elif self.mode == "flowtime":
            self.duration_seconds = 0
        elif not 300 <= self.duration_seconds <= 28_800:
            raise DailyRepositoryError("倒计时须为 5 至 480 分钟。")
        if isinstance(self.remaining_seconds, bool) or not isinstance(self.remaining_seconds, int):
            raise DailyRepositoryError("剩余专注时间无效。")
        if self.mode == "flowtime":
            self.remaining_seconds = 0
        elif not 0 <= self.remaining_seconds <= self.duration_seconds:
            raise DailyRepositoryError("剩余专注时间无效。")
        if isinstance(self.elapsed_seconds, bool) or not isinstance(self.elapsed_seconds, int) or self.elapsed_seconds < 0:
            raise DailyRepositoryError("已用专注时间无效。")
        if not isinstance(self.running, bool):
            raise DailyRepositoryError("计时状态无效。")
        if self.checkpoint_at is not None and not isinstance(self.checkpoint_at, datetime):
            parsed = _parse_timer_datetime(self.checkpoint_at)
            if parsed is None:
                raise DailyRepositoryError("当前计时的检查点时间无效。")
            self.checkpoint_at = parsed

    @classmethod
    def from_state(
        cls,
        state: Any,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> "FocusTimer":
        current = _timer_now(clock or _local_now, None)
        normalized = _normalize_focus_timer(state, now=current)
        return cls(
            duration_seconds=normalized["durationSeconds"],
            remaining_seconds=normalized["remainingSeconds"],
            running=normalized["running"],
            mode=normalized["mode"],
            elapsed_seconds=normalized["elapsedSeconds"],
            checkpoint_at=_parse_timer_datetime(normalized["checkpointAt"]),
            session_id=normalized["sessionId"],
            task_id=normalized["taskId"],
            task_title=normalized["taskTitle"],
            clock=clock or _local_now,
        )

    def to_state(self) -> dict[str, Any]:
        checkpoint = self.checkpoint_at or _timer_now(self.clock, None)
        return {
            "mode": self.mode,
            "durationSeconds": self.duration_seconds,
            "remainingSeconds": self.remaining_seconds,
            "elapsedSeconds": self.elapsed_seconds,
            "running": self.running,
            "checkpointAt": checkpoint.isoformat(timespec="milliseconds"),
            "sessionId": self.session_id[:80],
            "taskId": self.task_id[:160],
            "taskTitle": self.task_title[:300],
        }

    def advance(self, at: datetime | None = None) -> tuple[datetime, int, bool]:
        """Apply elapsed wall time since the persisted checkpoint and return work."""
        now = _timer_now(self.clock, at)
        start = self.checkpoint_at or now
        if start.tzinfo is None:
            start = start.astimezone()
        if not self.running:
            return start, 0, False
        elapsed = max(0, int(now.timestamp() - start.timestamp()))
        worked = elapsed if self.mode == "flowtime" else min(elapsed, self.remaining_seconds)
        if worked:
            self.elapsed_seconds = min(_MAX_TIMER_SECONDS, self.elapsed_seconds + worked)
            if self.mode != "flowtime":
                self.remaining_seconds = max(0, self.remaining_seconds - worked)
            self.checkpoint_at = datetime.fromtimestamp(start.timestamp() + worked, start.tzinfo)
        completed = self.mode != "flowtime" and self.remaining_seconds == 0
        if completed:
            self.running = False
        elif elapsed == 0:
            self.checkpoint_at = start
        return start, worked, completed

    def toggle(self) -> str:
        if self.running:
            self.running = False
            self.checkpoint_at = _timer_now(self.clock, None)
            return "继续专注"
        if self.remaining_seconds == 0:
            self.remaining_seconds = self.duration_seconds
            self.elapsed_seconds = 0
        if not self.session_id:
            self.session_id = str(uuid4())
        self.checkpoint_at = _timer_now(self.clock, None)
        self.running = True
        return "暂停"

    def tick(self, seconds: int = 1) -> bool:
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
            raise DailyRepositoryError("计时步进必须是非负整数秒。")
        if not self.running or seconds == 0:
            return False
        worked = seconds if self.mode == "flowtime" else min(seconds, self.remaining_seconds)
        self.elapsed_seconds = min(_MAX_TIMER_SECONDS, self.elapsed_seconds + worked)
        if self.mode != "flowtime":
            self.remaining_seconds = max(0, self.remaining_seconds - worked)
        self.checkpoint_at = _timer_now(self.clock, None)
        if self.remaining_seconds == 0:
            self.running = False
            return True
        return False

    def reset(self) -> None:
        self.running = False
        self.remaining_seconds = 0 if self.mode == "flowtime" else self.duration_seconds
        self.elapsed_seconds = 0
        self.checkpoint_at = _timer_now(self.clock, None)
        self.session_id = ""

    def display(self) -> str:
        shown = self.elapsed_seconds if self.mode == "flowtime" else self.remaining_seconds
        minutes, seconds = divmod(shown, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def progress(self) -> float:
        if self.mode == "flowtime":
            return min(1.0, self.elapsed_seconds / 3600)
        if self.duration_seconds <= 0:
            return 0.0
        return 1.0 - self.remaining_seconds / self.duration_seconds

    def button_label(self) -> str:
        if self.running:
            return "暂停"
        if self.mode != "flowtime" and self.remaining_seconds == 0:
            return "再来一轮"
        if self.elapsed_seconds > 0 or (self.mode != "flowtime" and self.remaining_seconds < self.duration_seconds):
            return "继续专注"
        return "开始专注"
