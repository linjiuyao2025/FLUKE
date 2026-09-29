from __future__ import annotations

import argparse
import atexit
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import math
import os
import sqlite3
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

from PySide6.QtCore import (
    QByteArray,
    QObject,
    Property,
    QProcess,
    QSettings,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtQml import QJSValue, QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMessageBox, QStyle

from migrate_legacy import default_database_path
from wanxiang.backup import BackupError, export_backup, preview_backup, restore_backup
from wanxiang.data_cleanup import DataCleanupError, LocalDataCleanupRepository
from wanxiang.database import (
    get_app_setting,
    initialize_database,
    import_package,
    load_imported_data,
    preview_import,
    set_app_setting,
    set_app_settings,
)
from wanxiang.migration import MigrationPackageError, read_package_file
from wanxiang.issues import IssueRepository, IssueRepositoryError
from wanxiang.habits import HabitRepository, HabitRepositoryError
from wanxiang.daily import DailyRepository, DailyRepositoryError, FocusTimer
from wanxiang.preferences import (
    IssuePreferencesRepository,
    PRESET_SOURCES,
    PreferencesRepositoryError,
    TOPIC_OPTIONS,
)
from wanxiang.reading import ReadingRepository, ReadingRepositoryError
from wanxiang.finance import (
    FinanceRepository,
    FinanceRepositoryError,
    EXPENSE_CATEGORIES,
    INCOME_CATEGORIES,
)
from wanxiang.fitness import FitnessRepository, FitnessRepositoryError
from wanxiang.planner import PlannerRepository, PlannerRepositoryError
from wanxiang.webdav_planner_bridge import WebDavPlannerSyncBridge
from wanxiang.instance_lock import PlannerDatabaseInstanceLock
from wanxiang.calendar_subscriptions import (
    CalendarSubscriptionError,
    normalize_subscription_url,
    protect_subscription_url,
    unprotect_subscription_url,
)
from wanxiang.caldav import (
    CalDAVError,
    basic_authorization_header,
    caldav_calendar_multiget_body,
    caldav_sync_collection_body,
    caldav_propfind_body,
    caldav_vtodo_query_body,
    caldav_sync_token_was_rejected,
    is_strong_caldav_etag,
    normalize_caldav_url,
    parse_caldav_collection_probe,
    parse_caldav_calendar_multiget_report,
    parse_caldav_sync_collection_report,
    parse_caldav_vtodo_report,
    resolve_caldav_resource_url,
    update_vtodo_completion,
    validate_caldav_credentials,
    validate_caldav_transport,
    protect_caldav_credentials,
    unprotect_caldav_credentials,
)
from wanxiang.shopping import ShoppingRepository, ShoppingRepositoryError
from wanxiang.media import MediaRepository, MediaRepositoryError, prepare_cover_file
from wanxiang.archive import ArchiveRepository, ArchiveRepositoryError
from wanxiang.home_layout_bridge import HomeLayoutBridge
from wanxiang.brand import BrandBridge, BrandRepository, BrandRepositoryError
from wanxiang.localization import LocalizationBridge, LocalizationRepository
from wanxiang.converter import ConverterBridge
from wanxiang.converter_engines import ConverterEngineUpdateBridge
from wanxiang.spreadsheet_export import SpreadsheetExportError, export_xlsx
from wanxiang.issue_tools import (
    IssueToolError,
    build_issue_prompt,
    save_issue_json,
)
from wanxiang.recommendation import (
    RecommendationError,
    RecommendationRepository,
    RecommendationRepositoryError,
    personalized_summary,
    rank_group,
)
from wanxiang.news_import import (
    MAX_ISSUE_JSON_BYTES,
    NewsImportError,
    parse_issue_json,
)
from wanxiang.notifications import (
    SystemTrayNotificationAdapter,
    create_qt_system_tray_notifier,
)
from wanxiang.tray_lifecycle import TrayLifecycleController
from wanxiang.weather import (
    WeatherServiceError,
    build_forecast_url,
    build_geocoding_url,
    city_search_candidates,
    parse_geocoding_response,
    simplify_forecast_response,
)


_MAX_CALENDAR_FEED_BYTES = 2_000_000
_MAX_CALDAV_SYNC_BYTES = 2_000_000
_MAX_CALDAV_PUT_RESPONSE_BYTES = 512_000
_CALENDAR_SUBSCRIPTION_REFRESH_SECONDS = 6 * 60 * 60
_CALDAV_SYNC_REFRESH_SECONDS = 60 * 60
_CALENDAR_SUBSCRIPTION_POLL_MS = 60 * 60 * 1000
from wanxiang.windows_location import WindowsLocationProvider


PROJECT_DIR = Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_DIR))
if not getattr(sys, "frozen", False):
    RESOURCE_DIR = PROJECT_DIR
ASSET_DIR = RESOURCE_DIR / "assets"
if not getattr(sys, "frozen", False):
    ASSET_DIR = PROJECT_DIR.parent / "assets"
QML_FILE = RESOURCE_DIR / "qml" / "Main.qml"


def _caldav_sync_is_due(last_sync_at: object, now: datetime, *, force: bool = False) -> bool:
    if force or not isinstance(last_sync_at, str) or not last_sync_at:
        return True
    try:
        last_sync = datetime.fromisoformat(last_sync_at).astimezone()
        current = now.astimezone()
    except (OverflowError, TypeError, ValueError):
        return True
    return (current - last_sync).total_seconds() >= _CALDAV_SYNC_REFRESH_SECONDS


def merge_effective_records(
    base_records: object,
    specialist_streams: tuple[tuple[object, str], ...],
    tombstone_streams: tuple[object, ...],
) -> list[dict[str, object]]:
    """Merge module-owned record overlays by (type,id), then apply tombstones."""
    merged: dict[tuple[str, str], dict[str, object]] = {}
    deleted: set[tuple[str, str]] = set()

    def add_rows(rows: object, *, owner: str | None = None) -> None:
        if not isinstance(rows, (list, tuple)):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            record_type, record_id = row.get("type"), row.get("id")
            if (isinstance(record_type, str) and record_type
                    and isinstance(record_id, str) and record_id
                    and (owner is None or record_type == owner)):
                merged[(record_type, record_id)] = row

    def add_deleted(rows: object) -> None:
        if not isinstance(rows, (list, tuple)):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            record_type, record_id = row.get("type"), row.get("id")
            if isinstance(record_type, str) and isinstance(record_id, str):
                deleted.add((record_type, record_id))

    add_rows(base_records)
    for rows, owner in specialist_streams:
        add_rows(rows, owner=owner)
    for rows in tombstone_streams:
        add_deleted(rows)
    return [row for key, row in merged.items() if key not in deleted]


class MigrationBridge(QObject):
    """只在用户选择文件后预览；写入需由 UI 的二次确认触发。"""

    dataChanged = Signal()
    restartRequested = Signal()

    def __init__(self, database_path: Path | None = None) -> None:
        super().__init__()
        self._pending_package = None
        self._pending_preview = None
        self._database_path = database_path or default_database_path()
        self._data = load_imported_data(self._database_path)
        self._restart_requested = False

    @Property("QVariant", notify=dataChanged)
    def data(self) -> dict[str, object]:
        """最近一次导入快照的只读应用视图；读取不会修改数据库。"""
        return self._data

    @Slot()
    def refreshData(self) -> None:
        self._data = load_imported_data(self._database_path)
        self.dataChanged.emit()

    @Slot(str, "QVariant", result="QVariant")
    def getSetting(self, key: str, default: object = None) -> object:
        return get_app_setting(self._database_path, key, default)

    @Slot(str, "QVariant", result=bool)
    def setSetting(self, key: str, value: object) -> bool:
        try:
            set_app_setting(self._database_path, key, value)
        except (OSError, TypeError, ValueError, RuntimeError, sqlite3.Error):
            return False
        return True

    @Slot(QUrl, result="QVariant")
    def previewPackage(self, file_url: QUrl) -> dict[str, object]:
        file_path = Path(file_url.toLocalFile()) if file_url.isLocalFile() else None
        if file_path is None or not str(file_path):
            return {"ok": False, "error": "请选择本机 JSON 迁移包。"}
        try:
            package = read_package_file(file_path)
            preview = preview_import(package, self._database_path)
        except (MigrationPackageError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._pending_package = None
            self._pending_preview = None
            return {"ok": False, "error": str(exc)}
        self._pending_package = package
        self._pending_preview = preview
        return {
            "ok": True,
            "checksum": package.checksum,
            "summary": package.summary,
            "status": preview["status"],
            "preview": preview,
        }

    @Slot(result="QVariant")
    def applyPreview(self) -> dict[str, object]:
        if self._pending_package is None or self._pending_preview is None:
            return {"ok": False, "error": "请先选择并校验迁移包。"}
        if self._pending_preview.get("historicalInactive"):
            self._pending_package = None
            self._pending_preview = None
            return {
                "ok": False,
                "error": "这份迁移快照已存在于历史记录中，未重新激活。请预览当前活动快照后再选择新导出包。",
            }
        try:
            result = import_package(
                self._pending_package,
                self._database_path,
                expected_active_checksum=self._pending_preview.get("currentChecksum"),
            )
        except (OSError, RuntimeError, MigrationPackageError, sqlite3.Error) as exc:
            return {"ok": False, "error": str(exc)}
        self._pending_package = None
        self._pending_preview = None
        self.refreshData()
        return {
            "ok": True,
            "status": result.status,
            "isActive": result.is_active,
            "summary": result.summary,
        }

    @Slot()
    def cancelPreview(self) -> None:
        self._pending_package = None
        self._pending_preview = None

    @Slot()
    def restartApplication(self) -> None:
        self._restart_requested = True
        self.restartRequested.emit()

    @property
    def restart_requested(self) -> bool:
        return self._restart_requested


class BackupBridge(QObject):
    """QML adapter for full, private backups of the complete native database."""

    stateChanged = Signal()
    restoreRequested = Signal()

    def __init__(self, database_path: Path, finance_bridge: "FinanceBridge") -> None:
        super().__init__()
        self._database_path = database_path
        self._finance_bridge = finance_bridge
        self._pending_backup: Path | None = None
        self._restart_requested = False

    @Slot(QUrl, result="QVariant")
    def exportBackup(self, file_url: QUrl) -> dict[str, object]:
        if not isinstance(file_url, QUrl) or not file_url.isLocalFile():
            return {"ok": False, "error": "请选择本机位置保存完整备份。"}
        target = Path(file_url.toLocalFile())

        def prepare_snapshot(path: Path) -> None:
            # Match the old full-backup behavior while keeping the live DB
            # unchanged until the complete package has been written.
            FinanceRepository(path).mark_backup_exported()

        try:
            result = export_backup(
                self._database_path,
                target,
                prepare_snapshot=prepare_snapshot,
            )
        except (BackupError, FinanceRepositoryError, OSError, RuntimeError,
                sqlite3.Error, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "完整备份导出失败。"}

        counters = self._finance_bridge.markBackupExported()
        warning = ""
        if not counters.get("ok"):
            warning = "备份已保存，但导出计数未能重置：" + str(
                counters.get("error") or "本机状态无法写入。"
            )
        self.stateChanged.emit()
        return {
            "ok": True,
            "path": result["path"],
            "summary": result["summary"],
            "warning": warning,
        }

    @Slot(QUrl, result="QVariant")
    def previewBackup(self, file_url: QUrl) -> dict[str, object]:
        if not isinstance(file_url, QUrl) or not file_url.isLocalFile():
            self._pending_backup = None
            return {"ok": False, "error": "请选择本机万象来信完整备份文件。"}
        path = Path(file_url.toLocalFile())
        try:
            result = preview_backup(path)
        except (BackupError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._pending_backup = None
            return {"ok": False, "error": str(exc) or "完整备份无法读取。"}
        self._pending_backup = path
        return {"ok": True, **result}

    @Slot(result="QVariant")
    def applyPreview(self) -> dict[str, object]:
        if self._pending_backup is None:
            return {"ok": False, "error": "请先选择并校验一份完整备份。"}
        try:
            result = restore_backup(self._pending_backup, self._database_path)
        except (BackupError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "恢复失败，当前数据库未替换。"}
        self._pending_backup = None
        self._restart_requested = True
        self.restoreRequested.emit()
        return {"ok": True, "path": result["path"], "summary": result["summary"]}

    @Slot()
    def cancelPreview(self) -> None:
        self._pending_backup = None

    @property
    def restart_requested(self) -> bool:
        return self._restart_requested


class IssuePreferencesBridge(QObject):
    """QML adapter for the independently stored news focus preferences."""

    stateChanged = Signal()

    def __init__(self, database_path: Path, migration_snapshot: object = None) -> None:
        super().__init__()
        self._repository: IssuePreferencesRepository | None = None
        self._state: dict[str, object] = {"topics": [], "preferences": {}}
        self._notice = ""
        try:
            self._repository = IssuePreferencesRepository(database_path, migration_snapshot)
            self._state = self._repository.get()
        except (PreferencesRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "关注方向暂时无法载入。"

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return deepcopy(self._state)

    @Property(str, notify=stateChanged)
    def notice(self) -> str:
        return self._notice

    @Property("QVariant", notify=stateChanged)
    def topicOptions(self) -> list[dict[str, str]]:
        return [{"key": key, "label": label} for key, label in TOPIC_OPTIONS]

    @Property("QVariant", notify=stateChanged)
    def presetSourceOptions(self) -> list[str]:
        return list(PRESET_SOURCES)

    @staticmethod
    def _variant(value: object) -> object:
        return value.toVariant() if isinstance(value, QJSValue) else value

    @Slot("QVariant", "QVariant", result="QVariant")
    def save(self, topics: object, preferences: object) -> dict[str, object]:
        topics = self._variant(topics)
        preferences = self._variant(preferences)
        if self._repository is None:
            return {"ok": False, "error": self._notice or "关注方向暂不可保存。"}
        try:
            self._state = self._repository.save(topics, preferences)
        except (PreferencesRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "关注方向保存失败。"
            self.stateChanged.emit()
            return {"ok": False, "error": self._notice, "state": self.state}
        self._notice = ""
        self.stateChanged.emit()
        return {"ok": True, "state": self.state}

    @Slot("QVariant")
    def adoptImportedData(self, migration_snapshot: object) -> None:
        if self._repository is None:
            return
        try:
            self._state = self._repository.adopt_imported_data(self._variant(migration_snapshot))
            self._notice = ""
        except (PreferencesRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "导入数据后无法更新关注方向。"
        self.stateChanged.emit()


class ReadingBridge(QObject):
    """QML adapter for the legacy global saved-knowledge flag and clippings."""

    stateChanged = Signal()

    def __init__(self, database_path: Path, migration_snapshot: object = None) -> None:
        super().__init__()
        self._repository: ReadingRepository | None = None
        self._state: dict[str, object] = {"savedKnowledge": False, "clippings": []}
        self._notice = ""
        try:
            self._repository = ReadingRepository(database_path, migration_snapshot)
            self._state = self._repository.snapshot()
        except (ReadingRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "稍后读与剪报数据暂时无法载入。"

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return deepcopy(self._state)

    @Property(str, notify=stateChanged)
    def notice(self) -> str:
        return self._notice

    @staticmethod
    def _variant(value: object) -> object:
        return value.toVariant() if isinstance(value, QJSValue) else value

    def _result(self, ok: bool, error: str = "") -> dict[str, object]:
        result: dict[str, object] = {"ok": ok, "state": self.state}
        if error:
            result["error"] = error
        return result

    def _refresh(self) -> None:
        if self._repository is not None:
            self._state = self._repository.snapshot()
        self.stateChanged.emit()

    @Slot(str, str, result=bool)
    def isClipped(self, item_id: str, issue_date: str) -> bool:
        try:
            return bool(self._repository and self._repository.is_clipped(item_id, issue_date))
        except (ReadingRepositoryError, OSError, RuntimeError, sqlite3.Error):
            return False

    @Slot(result="QVariant")
    def toggleSavedKnowledge(self) -> dict[str, object]:
        if self._repository is None:
            return self._result(False, self._notice or "稍后读暂时不可用。")
        try:
            self._repository.toggle_saved_knowledge()
            self._refresh()
            return self._result(True)
        except (ReadingRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            return self._result(False, str(exc) or "稍后读状态保存失败。")

    @Slot(bool, result="QVariant")
    def setSavedKnowledge(self, enabled: bool) -> dict[str, object]:
        if self._repository is None:
            return self._result(False, self._notice or "稍后读暂时不可用。")
        try:
            self._repository.set_saved_knowledge(enabled)
            self._refresh()
            return self._result(True)
        except (ReadingRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            return self._result(False, str(exc) or "稍后读状态保存失败。")

    @Slot("QVariant", "QVariant", "QVariant", result="QVariant")
    def toggleClipping(self, item: object, issue_date: object, topic: object) -> dict[str, object]:
        if self._repository is None:
            return self._result(False, self._notice or "新闻剪报暂时不可用。")
        try:
            was_saved = self._repository.toggle_clipping(
                self._variant(item), self._variant(issue_date), self._variant(topic)
            )
            self._refresh()
            result = self._result(True)
            result["saved"] = was_saved
            return result
        except (ReadingRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            return self._result(False, str(exc) or "新闻剪报保存失败。")

    @Slot(str, result="QVariant")
    def removeClipping(self, key: str) -> dict[str, object]:
        if self._repository is None:
            return self._result(False, self._notice or "新闻剪报暂时不可用。")
        try:
            removed = self._repository.remove_clipping(key)
            self._refresh()
            result = self._result(True)
            result["removed"] = removed
            return result
        except (ReadingRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            return self._result(False, str(exc) or "无法移出这条剪报。")

    @Slot("QVariant")
    def adoptImportedData(self, migration_snapshot: object) -> None:
        if self._repository is None:
            return
        try:
            self._state = self._repository.adopt_imported_data(self._variant(migration_snapshot))
            self._notice = ""
        except (ReadingRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "导入数据后无法更新稍后读与剪报。"
        self.stateChanged.emit()

class DailyBridge(QObject):
    """QML adapter for review/work projections and the local focus timer."""

    stateChanged = Signal()

    def __init__(
        self,
        database_path: Path,
        migration_snapshot: object = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__()
        self._repository: DailyRepository | None = None
        self._notice = ""
        self._clock_source = clock or (lambda: datetime.now().astimezone())
        self._timer = FocusTimer(clock=self._clock_source)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self.tickFocus)
        self._review: dict[str, object] = {}
        self._today_work: dict[str, object] = {}
        try:
            self._repository = DailyRepository(
                database_path, migration_snapshot, clock=self._clock_source
            )
            if self._repository.focus_timer().get("running"):
                self._repository.checkpoint_focus(now=self._clock_source())
            self._sync_timer()
            if self._timer.running:
                self._clock.start()
            self._refresh(emit=False)
        except (DailyRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "每日流程数据暂时无法载入。"

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        if self._repository is None:
            return {"notice": self._notice, "focusTask": "", "spotifyUrl": "", "questions": []}
        state = self._repository.state()
        state["notice"] = self._notice
        return state

    @Property("QVariant", notify=stateChanged)
    def review(self) -> dict[str, object]:
        return deepcopy(self._review)

    @Property("QVariant", notify=stateChanged)
    def todayWork(self) -> dict[str, object]:
        return deepcopy(self._today_work)

    @Property(str, notify=stateChanged)
    def focusDisplay(self) -> str:
        return self._timer.display()

    @Property(float, notify=stateChanged)
    def focusProgress(self) -> float:
        return self._timer.progress()

    @Property(bool, notify=stateChanged)
    def focusRunning(self) -> bool:
        return self._timer.running

    @Property(str, notify=stateChanged)
    def focusButtonLabel(self) -> str:
        return self._timer.button_label()

    @staticmethod
    def _variant(value: object) -> object:
        return value.toVariant() if isinstance(value, QJSValue) else value

    def _refresh(self, *, emit: bool = True) -> None:
        if self._repository is not None:
            self._review = self._repository.yesterday_review()
            self._today_work = self._repository.today_work()
        if emit:
            self.stateChanged.emit()

    def _sync_timer(self) -> None:
        if self._repository is not None:
            self._timer = FocusTimer.from_state(
                self._repository.focus_timer(), clock=self._clock_source
            )

    def updateHabits(self, habit_state: object) -> None:
        if self._repository is None or not isinstance(habit_state, dict):
            return
        habits = habit_state.get("habits", [])
        try:
            self._repository.update_activity_snapshot(habits=habits)
            self._refresh()
        except (DailyRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "昨日回顾暂时无法更新习惯记录。"
            self.stateChanged.emit()

    def updateActivity(
        self,
        records: object = None,
        habits: object = None,
        media_items: object = None,
    ) -> None:
        """Refresh cross-module projections without persisting source records."""
        if self._repository is None:
            return
        try:
            self._repository.update_activity_snapshot(
                records=records if isinstance(records, list) else None,
                habits=habits if isinstance(habits, list) else None,
                media_items=media_items if isinstance(media_items, list) else None,
            )
            self._refresh()
        except (DailyRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "生活记录暂时无法同步到昨日回顾。"
            self.stateChanged.emit()

    def _save(self, operation: object, success: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "每日流程暂不可用。"}
        try:
            operation()  # type: ignore[operator]
            self._notice = ""
            self._refresh()
            return {"ok": True, "message": success}
        except (DailyRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "保存失败，请检查本机数据后重试。"
            self.stateChanged.emit()
            return {"ok": False, "error": self._notice}

    @Slot(str, str, result="QVariant")
    def saveFollowUp(self, day: str, text: str) -> dict[str, object]:
        return self._save(lambda: self._repository.save_follow_up(day, text), "明日跟进线索已保存。")

    @Slot(str, result="QVariant")
    def saveFocusTask(self, task: str) -> dict[str, object]:
        return self._save(lambda: self._repository.save_focus_task(task), "专注任务已保存。")

    @Slot(str, result="QVariant")
    def saveSpotifyUrl(self, url: str) -> dict[str, object]:
        return self._save(lambda: self._repository.save_spotify_url(url), "Spotify 链接已保存。")

    @Slot(str, result="QVariant")
    def addQuestion(self, text: str) -> dict[str, object]:
        return self._save(lambda: self._repository.add_question(text), "问题已加入问题簿。")

    @Slot(int, result="QVariant")
    def removeQuestion(self, index: int) -> dict[str, object]:
        return self._save(lambda: self._repository.remove_question(index), "问题已从问题簿移除。")

    @Slot("QVariant")
    def adoptImportedData(self, migration_snapshot: object) -> None:
        if self._repository is None or not isinstance(migration_snapshot, dict):
            return
        try:
            self._repository.adopt_imported_data(migration_snapshot)
            self._sync_timer()
            if self._timer.running:
                self._clock.start()
            else:
                self._clock.stop()
            self._notice = ""
            self._refresh()
        except (DailyRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "导入数据后无法更新每日流程。"
            self.stateChanged.emit()

    @Slot(result="QVariant")
    @Slot(str, str, result="QVariant")
    def toggleFocus(self, task_id: str = "", task_title: str = "") -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "每日流程暂不可用。"}
        try:
            worked, completed, started = self._repository.toggle_focus(
                task_id, task_title, now=self._clock_source()
            )
            self._sync_timer()
            if self._timer.running:
                self._clock.start()
            else:
                self._clock.stop()
            self._notice = ""
            self._refresh()
            return {"ok": True, "worked": worked, "completed": completed, "started": started}
        except (DailyRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "计时状态无法保存。"
            self.stateChanged.emit()
            return {"ok": False, "error": self._notice}

    @Slot(str, int, result="QVariant")
    def setFocusMode(self, mode: str, duration_minutes: int = 25) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "每日流程暂不可用。"}
        try:
            self._repository.configure_focus(mode, duration_minutes, now=self._clock_source())
            self._sync_timer()
            self._notice = ""
            self._refresh()
            return {"ok": True, "mode": mode}
        except (DailyRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "计时设置无法保存。"
            self.stateChanged.emit()
            return {"ok": False, "error": self._notice}

    @Slot()
    def tickFocus(self) -> None:
        if self._repository is None:
            return
        try:
            _, completed = self._repository.checkpoint_focus(now=self._clock_source())
            self._sync_timer()
            if completed or not self._timer.running:
                self._clock.stop()
            self._refresh()
        except (DailyRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._clock.stop()
            self._notice = str(exc) or "计时状态无法保存。"
            self.stateChanged.emit()

    @Slot(result="QVariant")
    def resetFocus(self) -> dict[str, object]:
        if self._repository is None:
            self._clock.stop()
            self._timer.reset()
            self.stateChanged.emit()
            return {"ok": False, "error": self._notice or "每日流程暂不可用。"}
        try:
            self._repository.reset_focus(now=self._clock_source())
            self._clock.stop()
            self._sync_timer()
            self._notice = ""
            self._refresh()
            return {"ok": True}
        except (DailyRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "计时状态无法保存。"
            self.stateChanged.emit()
            return {"ok": False, "error": self._notice}

    @Slot()
    def close(self) -> None:
        self._clock.stop()
        if self._repository is None:
            return
        try:
            self._repository.pause_focus(now=self._clock_source())
            self._sync_timer()
        except (DailyRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "退出时无法保存计时状态。"


class HabitBridge(QObject):
    """Local habit tracking API shared by the full page and daily shortcuts."""

    stateChanged = Signal()

    def __init__(
        self,
        database_path: Path,
        migration_snapshot: dict[str, object] | None = None,
    ) -> None:
        super().__init__()
        self._database_path = database_path
        self._notice = ""
        self._repository: HabitRepository | None = None
        try:
            self._repository = self._make_repository(migration_snapshot)
        except HabitRepositoryError as exc:
            self._notice = f"习惯数据暂时无法载入：{exc}"

    @staticmethod
    def _migration_habits(
        migration_snapshot: dict[str, object] | None,
    ) -> tuple[list[dict[str, object]], list[str]]:
        if not isinstance(migration_snapshot, dict):
            return [], []
        entities = migration_snapshot.get("entities")
        habits = entities.get("habits", []) if isinstance(entities, dict) else []
        documents = migration_snapshot.get("documents")
        state = documents.get("richangji-state-v1") if isinstance(documents, dict) else None
        settings = state.get("settings") if isinstance(state, dict) else None
        hidden = settings.get("hiddenHabitKeys", []) if isinstance(settings, dict) else []
        clean_habits = [item for item in habits if isinstance(item, dict)] if isinstance(habits, list) else []
        clean_hidden = [item for item in hidden if isinstance(item, str)] if isinstance(hidden, list) else []
        return clean_habits, clean_hidden

    def _make_repository(
        self,
        migration_snapshot: dict[str, object] | None,
    ) -> HabitRepository:
        return HabitRepository(self._database_path, migration_snapshot)

    def reload_from_database(self) -> None:
        try:
            self._repository = HabitRepository(self._database_path)
            self._notice = ""
        except (HabitRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "习惯数据暂时无法载入。"
        self.stateChanged.emit()

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        today = date.today()
        try:
            if self._repository is None:
                raise HabitRepositoryError(self._notice or "习惯数据暂时无法载入。")
            habits = self._repository.habits()
            raw_metrics = self._repository.metrics(today.isoformat())
        except HabitRepositoryError:
            habits = []
            raw_metrics = {}

        total = int(raw_metrics.get("total", len(habits)) or 0)
        rows = raw_metrics.get("habits", [])
        rows = rows if isinstance(rows, list) else []
        week_info = raw_metrics.get("week", {})
        week_days = week_info.get("days", []) if isinstance(week_info, dict) else []
        week_stats = []
        for day_text in week_days if isinstance(week_days, list) else []:
            done_count = 0
            active_count = 0
            scheduled_count = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                history = row.get("history", [])
                day_row = next(
                    (
                        item
                        for item in history
                        if isinstance(item, dict) and item.get("date") == day_text
                    ),
                    None,
                )
                if not isinstance(day_row, dict):
                    continue
                scheduled_count += int(bool(day_row.get("due", True)))
                if not day_row.get("eligible", day_row.get("active", True)):
                    continue
                active_count += 1
                value = float(day_row.get("value", 0) or 0)
                target = next(
                    (
                        float(habit.get("target", 1) or 1)
                        for habit in habits
                        if isinstance(habit, dict) and habit.get("id") == row.get("id")
                    ),
                    1,
                )
                done_count += int(value >= target)
            weekday = date.fromisoformat(str(day_text)).strftime("%w")
            week_stats.append(
                {
                    "date": day_text,
                    "completed": done_count,
                    "total": active_count,
                    "scheduled": scheduled_count,
                    "rate": done_count / active_count if active_count else 0,
                    "label": ["日", "一", "二", "三", "四", "五", "六"][int(weekday)],
                }
            )

        yesterday = date.fromordinal(today.toordinal() - 1).isoformat()
        review_habits = []
        for habit in habits:
            if habit.get("sample"):
                continue
            habit_stats = next(
                (
                    row
                    for row in rows
                    if isinstance(row, dict) and row.get("id") == habit.get("id")
                ),
                {},
            )
            history_day = next(
                (
                    item
                    for item in habit_stats.get("history", [])
                    if isinstance(item, dict) and item.get("date") == yesterday
                ),
                {},
            )
            if history_day.get("due", True) and history_day.get("eligible", True):
                review_habits.append(habit)
        review_items = []
        for habit in review_habits:
            value = habit.get("entries", {}).get(yesterday, 0)
            try:
                numeric_value = float(value or 0)
                target = float(habit.get("target", 1) or 1)
            except (TypeError, ValueError):
                numeric_value, target = 0, 1
            review_items.append(
                {
                    "id": habit.get("id"),
                    "name": habit.get("name", "习惯"),
                    "value": numeric_value,
                    "status": "已完成" if numeric_value >= target else "未完成",
                    "done": numeric_value >= target,
                }
            )
        review_done = sum(1 for item in review_items if item["done"])
        metrics = {
            **raw_metrics,
            "todayCompleted": raw_metrics.get("done", 0),
            "totalHabits": total,
            "completionRate": float(
                raw_metrics.get("completionRate30Days", 0) or 0
            )
            / 100,
            "habitStats": rows,
            "week": week_stats,
            "yesterdayReview": {
                "items": review_items,
                "completed": review_done,
                "total": len(review_items),
                "summary": f"昨天完成 {review_done} / {len(review_items)} 项习惯。",
            },
        }
        return {
            "habits": habits,
            "today": today.isoformat(),
            "metrics": metrics,
            "notice": self._notice,
        }

    def _run(self, operation: object) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "习惯数据暂时无法载入。"}
        try:
            operation()  # type: ignore[operator]
        except (HabitRepositoryError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "操作没有保存，请检查本机数据后重试。"
            self.stateChanged.emit()
            return {"ok": False, "error": self._notice}
        self._notice = ""
        self.stateChanged.emit()
        return {"ok": True}

    @Slot(str, result="QVariant")
    def quickCheck(self, habit_id: str) -> dict[str, object]:
        return self._run(
            lambda: self._repository.quick_check(habit_id, date.today().isoformat())
        )

    @Slot(str, int, result="QVariant")
    def adjustCounter(self, habit_id: str, delta: int) -> dict[str, object]:
        return self._run(
            lambda: self._repository.adjust_counter(
                habit_id, date.today().isoformat(), delta
            )
        )

    @Slot(str, "QVariant", result="QVariant")
    def setValue(self, habit_id: str, value: object) -> dict[str, object]:
        return self._run(
            lambda: self._repository.set_value(
                habit_id, date.today().isoformat(), value
            )
        )

    @Slot("QVariant", result="QVariant")
    def addHabit(self, definition: object) -> dict[str, object]:
        if isinstance(definition, QJSValue):
            definition = definition.toVariant()
        if not isinstance(definition, dict):
            return {"ok": False, "error": "习惯设置格式无效。"}
        return self._run(lambda: self._repository.add_habit(definition))

    @Slot(str, "QVariant", result="QVariant")
    def updateHabit(self, habit_id: str, definition: object) -> dict[str, object]:
        if isinstance(definition, QJSValue):
            definition = definition.toVariant()
        if not isinstance(definition, dict):
            return {"ok": False, "error": "习惯修改格式无效。"}
        return self._run(lambda: self._repository.update_habit(habit_id, definition))

    @Slot(str, result="QVariant")
    def deleteHabit(self, habit_id: str) -> dict[str, object]:
        return self._run(lambda: self._repository.delete_habit(habit_id))

    @Slot(result="QVariant")
    def clearSamples(self) -> dict[str, object]:
        return self._run(self._repository.clear_samples)

    @Slot("QVariant")
    def adoptImportedData(self, migration_snapshot: object) -> None:
        if isinstance(migration_snapshot, dict):
            try:
                if self._repository is None:
                    self._repository = self._make_repository(migration_snapshot)
                else:
                    habits, hidden = self._migration_habits(migration_snapshot)
                    self._repository.adopt_imported_data(habits, hidden)
            except (HabitRepositoryError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
                self._notice = str(exc) or "已导入数据，但习惯列表暂时无法更新。"
            else:
                self._notice = ""
        self.stateChanged.emit()


class FinanceBridge(QObject):
    """QML adapter for local finance records, summaries and spreadsheet export."""

    stateChanged = Signal()

    def __init__(self, database_path: Path, migration_snapshot: object = None) -> None:
        super().__init__()
        self._database_path = database_path
        self._repository: FinanceRepository | None = None
        self._notice = ""
        self._state: dict[str, object] = {
            "records": [],
            "settings": {"budget": 5000, "budgetIsDefault": True, "moneyFilter": "all"},
            "summary": {},
            "categories": [],
            "consumption": {},
            "notice": "",
        }
        try:
            self._repository = FinanceRepository(database_path, migration_snapshot)
            self._refresh(emit=False)
        except (FinanceRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "记账数据暂时无法载入。"
            self._state["notice"] = self._notice

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return deepcopy(self._state)

    @staticmethod
    def _variant(value: object) -> object:
        return value.toVariant() if isinstance(value, QJSValue) else value

    def _refresh(self, *, emit: bool = True) -> None:
        if self._repository is not None:
            self._state = {
                "records": self._repository.filtered_records(limit=60),
                "settings": self._repository.settings(),
                "summary": self._repository.summary(),
                "categories": self._repository.expense_categories(),
                "consumption": self._repository.consumption_summary(),
                "expenseCategories": list(EXPENSE_CATEGORIES),
                "incomeCategories": list(INCOME_CATEGORIES),
                "notice": self._notice,
            }
        if emit:
            QTimer.singleShot(0, self, self.stateChanged.emit)

    def reload_from_database(self) -> None:
        try:
            self._repository = FinanceRepository(self._database_path)
            self._notice = ""
        except (FinanceRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "记账数据暂时无法载入。"
        self._refresh()

    def _run(self, operation: object) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "记账功能暂不可用。"}
        try:
            operation()  # type: ignore[operator]
        except (FinanceRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "记账操作没有保存，请检查数据后重试。"
            self._refresh()
            return {"ok": False, "error": self._notice, "state": self.state}
        self._notice = ""
        self._refresh()
        return {"ok": True, "state": self.state}

    @Slot(str, str, str, str, str, result="QVariant")
    def addRecord(
        self, flow: str, amount: str, category: str, day: str, note: str
    ) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "记账功能暂不可用。"}
        return self._run(
            lambda: self._repository.add_record(flow, amount, category, day, note)
        )

    @Slot(str, result="QVariant")
    def deleteRecord(self, record_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "记账功能暂不可用。"}

        removed = False

        def remove() -> None:
            nonlocal removed
            removed = self._repository.delete_record(record_id)
            if not removed:
                raise FinanceRepositoryError("这条流水已不存在，列表已刷新。")

        result = self._run(remove)
        if result.get("ok"):
            result["removed"] = removed
        return result

    @Slot(str, result="QVariant")
    def setFilter(self, category: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "记账功能暂不可用。"}
        return self._run(lambda: self._repository.set_filter(category))

    @Slot("QVariant", result="QVariant")
    def setBudget(self, amount: object) -> dict[str, object]:
        amount = self._variant(amount)
        if self._repository is None:
            return {"ok": False, "error": self._notice or "记账功能暂不可用。"}
        return self._run(lambda: self._repository.set_budget(amount))

    @Slot(result="QVariant")
    def markBackupExported(self) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "记账数据暂不可用。"}
        return self._run(self._repository.mark_backup_exported)

    @Slot(QUrl, result="QVariant")
    def exportExcel(self, file_url: QUrl) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "记账功能暂不可用。"}
        if not file_url.isLocalFile():
            return {"ok": False, "error": "请选择本机 Excel 文件保存位置。"}
        target = Path(file_url.toLocalFile())
        try:
            payload = self._repository.excel_export_data("zh")
            saved_path = export_xlsx(
                target,
                "记账流水",
                payload["headers"],
                payload["rows"],
            )
        except (FinanceRepositoryError, SpreadsheetExportError, OSError, RuntimeError,
                sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "Excel 文件导出失败。"
            self._refresh()
            return {"ok": False, "error": self._notice, "state": self.state}
        self._notice = ""
        self._refresh()
        return {"ok": True, "path": str(saved_path), "state": self.state}

    @Slot("QVariant")
    def adoptImportedData(self, migration_snapshot: object) -> None:
        if self._repository is None:
            try:
                self._repository = FinanceRepository(
                    self._database_path, self._variant(migration_snapshot)
                )
            except (FinanceRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
                self._notice = str(exc) or "已导入数据，但记账模块无法载入。"
                self._state["notice"] = self._notice
                self.stateChanged.emit()
                return
        else:
            try:
                self._repository.adopt_imported_data(self._variant(migration_snapshot))
            except (FinanceRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
                self._notice = str(exc) or "已导入数据，但记账列表无法更新。"
                self._refresh()
                return
        self._notice = ""
        self._refresh()

    def activity_records(self) -> list[dict[str, object]]:
        return self._repository.records() if self._repository is not None else []

    def activity_tombstones(self) -> list[dict[str, str]]:
        return self._repository.deleted_record_keys() if self._repository is not None else []


class FitnessBridge(QObject):
    """QML adapter for local fitness records, profile, weekly plan and export."""

    stateChanged = Signal()

    def __init__(self, database_path: Path, migration_snapshot: object = None) -> None:
        super().__init__()
        self._database_path = database_path
        self._repository: FitnessRepository | None = None
        self._notice = ""
        self._trend_range: str = "90"
        self._state: dict[str, object] = {
            "records": [], "profile": {}, "weeklyPlan": [], "summary": {},
            "trend": [], "notice": "",
        }
        try:
            self._repository = FitnessRepository(database_path, migration_snapshot)
            self._refresh(emit=False)
        except (FitnessRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "健身数据暂时无法载入。"
            self._state["notice"] = self._notice

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return deepcopy(self._state)

    @staticmethod
    def _variant(value: object) -> object:
        return value.toVariant() if isinstance(value, QJSValue) else value

    def _refresh(self, *, emit: bool = True) -> None:
        if self._repository is not None:
            days = None if self._trend_range == "all" else int(self._trend_range)
            self._state = self._repository.state(
                trend_days=days,
                trend_all=self._trend_range == "all",
            )
            self._state["trendRange"] = self._trend_range
            self._state["notice"] = self._notice
        if emit:
            QTimer.singleShot(0, self, self.stateChanged.emit)

    def reload_from_database(self) -> None:
        try:
            self._repository = FitnessRepository(self._database_path)
            self._notice = ""
        except (FitnessRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "健身数据暂时无法载入。"
        self._refresh()

    @Slot(str, result="QVariant")
    def setTrendRange(self, value: str) -> dict[str, object]:
        if value not in {"30", "90", "365", "all"}:
            return {"ok": False, "error": "趋势范围无效。"}
        self._trend_range = value
        self._notice = ""
        self._refresh()
        return {"ok": True, "state": self.state}

    def _run(self, operation: object) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "健身功能暂不可用。"}
        try:
            operation()  # type: ignore[operator]
        except (FitnessRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "健身操作没有保存，请检查数据后重试。"
            self._refresh()
            return {"ok": False, "error": self._notice, "state": self.state}
        self._notice = ""
        self._refresh()
        return {"ok": True, "state": self.state}

    @Slot(str, str, str, str, result="QVariant")
    def addRecord(self, weight: str, duration: str, day: str, note: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "健身功能暂不可用。"}
        return self._run(lambda: self._repository.add_record(weight, duration, day, note))

    @Slot(str, result="QVariant")
    def deleteRecord(self, record_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "健身功能暂不可用。"}

        def remove() -> None:
            if not self._repository.delete_record(record_id):
                raise FitnessRepositoryError("这条身体记录已不存在，列表已刷新。")

        return self._run(remove)

    @Slot("QVariant", "QVariant", "QVariant", result="QVariant")
    def saveProfile(
        self, height: object, target: object, start_weight: object
    ) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "健身功能暂不可用。"}
        height_value = self._variant(height)
        target_value = self._variant(target)
        start_value = self._variant(start_weight)
        return self._run(
            lambda: self._repository.set_profile(
                height=height_value, target=target_value, start_weight=start_value
            )
        )

    @Slot(str, str, str, result="QVariant")
    def addPlan(self, group: str, title: str, note: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "健身功能暂不可用。"}
        return self._run(lambda: self._repository.add_plan(group, title, note))

    @Slot(str, result="QVariant")
    def togglePlan(self, plan_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "健身功能暂不可用。"}
        return self._run(lambda: self._repository.toggle_plan(plan_id))

    @Slot(str, result="QVariant")
    def deletePlan(self, plan_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "健身功能暂不可用。"}

        def remove() -> None:
            if not self._repository.delete_plan(plan_id):
                raise FitnessRepositoryError("这项周计划已不存在，列表已刷新。")

        return self._run(remove)

    @Slot(QUrl, result="QVariant")
    def exportExcel(self, file_url: QUrl) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "健身功能暂不可用。"}
        if not file_url.isLocalFile():
            return {"ok": False, "error": "请选择本机 Excel 文件保存位置。"}
        try:
            saved_path = self._repository.export_excel(Path(file_url.toLocalFile()), "zh")
        except (FitnessRepositoryError, SpreadsheetExportError, OSError, RuntimeError,
                sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "健身记录导出失败。"
            self._refresh()
            return {"ok": False, "error": self._notice, "state": self.state}
        self._notice = ""
        self._refresh()
        return {"ok": True, "path": str(saved_path), "state": self.state}

    @Slot("QVariant")
    def adoptImportedData(self, migration_snapshot: object) -> None:
        try:
            if self._repository is None:
                self._repository = FitnessRepository(self._database_path, self._variant(migration_snapshot))
            else:
                self._repository.adopt_imported_data(self._variant(migration_snapshot))
        except (FitnessRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "已导入数据，但健身列表无法更新。"
            self._refresh()
            return
        self._notice = ""
        self._refresh()

    def activity_records(self) -> list[dict[str, object]]:
        return self._repository.records() if self._repository is not None else []

    def activity_tombstones(self) -> list[dict[str, str]]:
        return self._repository.deleted_record_keys() if self._repository is not None else []


class PlannerBridge(QObject):
    """QML adapter for persistent planning, drafts, and in-app reminders."""

    stateChanged = Signal()
    remindersDue = Signal("QVariant")

    def __init__(
        self,
        database_path: Path,
        migration_snapshot: object = None,
        notifier: SystemTrayNotificationAdapter | None = None,
    ) -> None:
        super().__init__()
        self._database_path = database_path
        self._notifier = notifier
        self._repository: PlannerRepository | None = None
        self._notice = ""
        self._notice_is_error = False
        self._state: dict[str, object] = {"records": [], "groups": [], "weekDays": [], "draft": {}, "notice": ""}
        self._calendar_network = QNetworkAccessManager(self)
        self._calendar_network.setTransferTimeout(15_000)
        self._calendar_network.setRedirectPolicy(
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy
        )
        self._calendar_subscription_replies: dict[str, QNetworkReply] = {}
        self._calendar_subscription_buffers: dict[str, bytearray] = {}
        self._caldav_probe_replies: dict[str, QNetworkReply] = {}
        self._caldav_probe_buffers: dict[str, bytearray] = {}
        self._caldav_sync_replies: dict[str, QNetworkReply] = {}
        self._caldav_sync_buffers: dict[str, bytearray | None] = {}
        self._caldav_sync_jobs: dict[str, dict[str, object]] = {}
        self._calendar_refresh_timer = QTimer(self)
        self._calendar_refresh_timer.setInterval(_CALENDAR_SUBSCRIPTION_POLL_MS)
        self._calendar_refresh_timer.timeout.connect(self._refresh_due_calendar_sources)
        self._calendar_startup_refresh_timer = QTimer(self)
        self._calendar_startup_refresh_timer.setSingleShot(True)
        self._calendar_startup_refresh_timer.timeout.connect(self._refresh_calendar_sources_at_startup)
        self._reminder_clock = QTimer(self)
        self._reminder_clock.setInterval(1000)
        self._reminder_clock.timeout.connect(self._clockTick)
        try:
            self._repository = PlannerRepository(database_path, migration_snapshot)
            self._refresh(emit=False)
            self._reminder_clock.start()
            self._calendar_refresh_timer.start()
            self._calendar_startup_refresh_timer.start(1200)
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "日程数据暂时无法载入。"
            self._notice_is_error = True
            self._state["notice"] = self._notice
            self._state["noticeIsError"] = True

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return deepcopy(self._state)

    @staticmethod
    def _variant(value: object) -> object:
        return value.toVariant() if isinstance(value, QJSValue) else value

    def _refresh(self, *, emit: bool = True) -> None:
        if self._repository is not None:
            self._state = self._repository.state()
            self._state["notice"] = self._notice
            self._state["noticeIsError"] = self._notice_is_error
            for item in self._state.get("calendarSubscriptions", []):
                if isinstance(item, dict):
                    item["refreshing"] = item.get("id") in self._calendar_subscription_replies
            for item in self._state.get("caldavAccounts", []):
                if isinstance(item, dict):
                    item["checking"] = item.get("id") in self._caldav_probe_replies
                    item["syncing"] = item.get("id") in self._caldav_sync_jobs
        if emit:
            QTimer.singleShot(0, self, self.stateChanged.emit)

    def _refresh_due_calendar_subscriptions(self) -> None:
        if self._repository is None:
            return
        now = datetime.now().astimezone()
        for item in self._repository.state().get("calendarSubscriptions", []):
            subscription_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(subscription_id, str) or subscription_id in self._calendar_subscription_replies:
                continue
            last_attempt = item.get("lastAttemptAt", "")
            try:
                attempted_at = datetime.fromisoformat(last_attempt).astimezone() if last_attempt else None
            except (TypeError, ValueError):
                attempted_at = None
            if attempted_at is None or (now - attempted_at).total_seconds() >= _CALENDAR_SUBSCRIPTION_REFRESH_SECONDS:
                self._start_calendar_subscription_refresh(subscription_id)

    def _refresh_due_calendar_sources(self) -> None:
        self._refresh_due_calendar_subscriptions()
        self._refresh_due_caldav_accounts()

    def _refresh_calendar_sources_at_startup(self) -> None:
        self._refresh_due_calendar_subscriptions()
        self._refresh_due_caldav_accounts(force=True)

    def _refresh_due_caldav_accounts(self, *, force: bool = False) -> None:
        if self._repository is None:
            return
        now = datetime.now().astimezone()
        for account in self._repository.state().get("caldavAccounts", []):
            account_id = account.get("id") if isinstance(account, dict) else None
            if (
                not isinstance(account_id, str)
                or not account_id
                or account_id in self._caldav_sync_jobs
                or account_id in self._caldav_probe_replies
                or not _caldav_sync_is_due(account.get("lastSyncAt", ""), now, force=force)
            ):
                continue
            self._start_caldav_task_sync(account_id)

    def _subscription_response_header(self, reply: QNetworkReply, name: bytes, maximum: int) -> str | None:
        raw = bytes(reply.rawHeader(name.decode("ascii")))
        if not raw:
            return None
        if len(raw) > maximum or any(byte < 32 or byte == 127 for byte in raw):
            raise CalendarSubscriptionError("日历服务器返回了无效的缓存验证信息。")
        try:
            return raw.decode("latin-1").strip()
        except UnicodeError as exc:
            raise CalendarSubscriptionError("日历服务器返回了无效的缓存验证信息。") from exc

    def _finish_calendar_subscription_refresh(self, subscription_id: str, reply: QNetworkReply) -> None:
        if self._calendar_subscription_replies.get(subscription_id) is not reply:
            reply.deleteLater()
            return
        buffer = self._calendar_subscription_buffers.get(subscription_id, bytearray())
        trailing = bytes(reply.readAll())
        if len(buffer) + len(trailing) <= _MAX_CALENDAR_FEED_BYTES:
            buffer.extend(trailing)
        self._calendar_subscription_replies.pop(subscription_id, None)
        self._calendar_subscription_buffers.pop(subscription_id, None)
        status_value = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            if self._repository is None or self._repository.calendar_subscription_details(subscription_id) is None:
                return
            status = int(status_value) if status_value is not None else 0
            etag = self._subscription_response_header(reply, b"ETag", 1024)
            last_modified = self._subscription_response_header(reply, b"Last-Modified", 128)
            if status == 304:
                self._repository.record_calendar_subscription_not_modified(
                    subscription_id, etag, last_modified,
                )
            elif 200 <= status < 300 and reply.error() == QNetworkReply.NetworkError.NoError:
                if len(buffer) > _MAX_CALENDAR_FEED_BYTES:
                    raise CalendarSubscriptionError("订阅内容超过 2 MB，已保留上次成功同步的日程。")
                body = bytes(buffer)
                try:
                    contents = body.decode("utf-8-sig", errors="strict")
                except UnicodeDecodeError as exc:
                    raise CalendarSubscriptionError("订阅内容不是有效的 UTF-8 iCalendar 文件，已保留旧日程。") from exc
                self._repository.replace_calendar_subscription_events(
                    subscription_id, contents, etag or "", last_modified or "",
                )
            elif status:
                self._repository.mark_calendar_subscription_error(
                    subscription_id,
                    f"日历服务器返回 HTTP {status}，已保留上次成功同步的日程。",
                )
            else:
                self._repository.mark_calendar_subscription_error(
                    subscription_id, "无法连接日历服务器，已保留上次成功同步的日程。",
                )
        except (CalendarSubscriptionError, PlannerRepositoryError, OSError, RuntimeError,
                sqlite3.Error, TypeError, ValueError) as exc:
            safe_message = str(exc) or "日历订阅刷新失败，已保留上次成功同步的日程。"
            self._repository.mark_calendar_subscription_error(subscription_id, safe_message)
        finally:
            reply.deleteLater()
            self._refresh()

    def _start_calendar_subscription_refresh(self, subscription_id: str) -> bool:
        if self._repository is None:
            return False
        details = self._repository.calendar_subscription_details(subscription_id)
        if details is None:
            return False
        previous = self._calendar_subscription_replies.pop(subscription_id, None)
        self._calendar_subscription_buffers.pop(subscription_id, None)
        if previous is not None:
            previous.abort()
        try:
            clear_url = unprotect_subscription_url(details.get("urlProtected"))
            normalized_url, _host = normalize_subscription_url(clear_url)
            request = QNetworkRequest(QUrl(normalized_url))
            request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "FLUKE Calendar/1.0")
            request.setTransferTimeout(15_000)
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
            )
            if details.get("etag"):
                request.setRawHeader(b"If-None-Match", str(details["etag"]).encode("latin-1"))
            if details.get("lastModified"):
                request.setRawHeader(b"If-Modified-Since", str(details["lastModified"]).encode("latin-1"))
            reply = self._calendar_network.get(request)
        except CalendarSubscriptionError as exc:
            safe_message = str(exc)
            self._repository.mark_calendar_subscription_error(subscription_id, safe_message)
            self._refresh()
            return False
        except (UnicodeError, OSError, RuntimeError, TypeError, ValueError):
            safe_message = "无法准备日历订阅请求，已保留上次成功同步的日程。"
            self._repository.mark_calendar_subscription_error(subscription_id, safe_message)
            self._refresh()
            return False
        self._calendar_subscription_replies[subscription_id] = reply
        self._calendar_subscription_buffers[subscription_id] = bytearray()

        def receive_data() -> None:
            if self._calendar_subscription_replies.get(subscription_id) is not reply:
                return
            chunk = bytes(reply.readAll())
            buffer = self._calendar_subscription_buffers.get(subscription_id)
            if buffer is None:
                return
            if len(buffer) + len(chunk) > _MAX_CALENDAR_FEED_BYTES:
                self._calendar_subscription_buffers.pop(subscription_id, None)
                self._calendar_subscription_replies.pop(subscription_id, None)
                self._repository.mark_calendar_subscription_error(
                    subscription_id, "订阅内容超过 2 MB，已保留上次成功同步的日程。",
                )
                reply.abort()
                self._refresh()
                return
            buffer.extend(chunk)

        reply.readyRead.connect(receive_data)
        reply.finished.connect(
            lambda subscription_id=subscription_id, reply=reply:
                self._finish_calendar_subscription_refresh(subscription_id, reply)
        )
        self._refresh()
        return True

    @Slot(str, str, result="QVariant")
    def addCalendarSubscription(self, name: str, url: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        try:
            normalized_url, host = normalize_subscription_url(url)
            protected_url = protect_subscription_url(normalized_url)
            item = self._repository.add_calendar_subscription(name.strip() or host, host, protected_url)
        except (CalendarSubscriptionError, PlannerRepositoryError, OSError, RuntimeError,
                sqlite3.Error, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "日历订阅无法保存。"}
        started = self._start_calendar_subscription_refresh(str(item["id"]))
        return {"ok": True, "refreshStarted": started, "state": self.state}

    @Slot(str, result="QVariant")
    def refreshCalendarSubscription(self, subscription_id: str) -> dict[str, object]:
        started = self._start_calendar_subscription_refresh(subscription_id)
        return {"ok": started, "error": "无法开始刷新此日历订阅。" if not started else "", "state": self.state}

    @Slot(result="QVariant")
    def refreshAllCalendarSubscriptions(self) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        started = 0
        for item in self._repository.state().get("calendarSubscriptions", []):
            if isinstance(item, dict) and self._start_calendar_subscription_refresh(str(item.get("id", ""))):
                started += 1
        return {"ok": True, "started": started, "state": self.state}

    @Slot(str, result="QVariant")
    def removeCalendarSubscription(self, subscription_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        reply = self._calendar_subscription_replies.pop(subscription_id, None)
        self._calendar_subscription_buffers.pop(subscription_id, None)
        if reply is not None:
            reply.abort()
        def remove() -> None:
            if not self._repository.remove_calendar_subscription(subscription_id):
                raise PlannerRepositoryError("这条日历订阅已不存在，列表已刷新。")

        return self._run(remove)

    def _finish_caldav_probe(self, account_id: str, reply: QNetworkReply) -> None:
        if self._caldav_probe_replies.get(account_id) is not reply:
            reply.deleteLater()
            return
        self._caldav_probe_replies.pop(account_id, None)
        buffer = self._caldav_probe_buffers.pop(account_id, None)
        trailing = bytes(reply.readAll())
        status_value = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = int(status_value) if status_value is not None else 0
        safe_error = ""
        calendars: list[dict[str, object]] = []
        if buffer is None:
            safe_error = "服务器返回的 CalDAV 信息超过 512 KB。"
        elif len(buffer) + len(trailing) > 512_000:
            safe_error = "服务器返回的 CalDAV 信息超过 512 KB。"
        elif status == 401:
            safe_error = "服务器拒绝登录，请检查账号和密码。"
        elif status == 403:
            safe_error = "此账户无权读取该日历集。"
        elif status in {301, 302, 303, 307, 308}:
            safe_error = "服务器要求跳转；为保护登录信息，请直接填写跳转后的 HTTPS 地址。"
        elif status != 207:
            safe_error = (
                f"服务器未返回 CalDAV 日历集（HTTP {status}）。"
                if status else "无法连接 CalDAV 服务器，请检查地址和网络。"
            )
        else:
            try:
                payload = bytes(buffer) + trailing if buffer is not None else trailing
                parsed = parse_caldav_collection_probe(payload)
                calendars = parsed["calendars"]
            except CalDAVError as exc:
                safe_error = str(exc)
        reply.deleteLater()
        if self._repository is not None:
            try:
                self._repository.record_caldav_probe_result(
                    account_id,
                    calendars=calendars if not safe_error else None,
                    error=safe_error,
                )
            except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
                self._notice = str(exc) or "CalDAV 连接结果无法保存。"
                self._notice_is_error = True
        self._refresh()

    def _start_caldav_probe(self, account_id: str) -> bool:
        if self._repository is None:
            return False
        details = self._repository.caldav_account_details(account_id)
        if details is None:
            return False
        previous = self._caldav_probe_replies.pop(account_id, None)
        self._caldav_probe_buffers.pop(account_id, None)
        if previous is not None:
            previous.abort()
        try:
            protected_url = details.get("urlProtected")
            protected_credentials = details.get("credentialsProtected")
            url = unprotect_subscription_url(protected_url)
            username, password = unprotect_caldav_credentials(
                protected_credentials, unprotect_subscription_url,
            )
            normalized_url, _host = validate_caldav_transport(
                url, bool(username and password),
            )
            request = QNetworkRequest(QUrl(normalized_url))
            request.setTransferTimeout(15_000)
            request.setHeader(
                QNetworkRequest.KnownHeaders.ContentTypeHeader,
                "application/xml; charset=utf-8",
            )
            request.setRawHeader(QByteArray(b"Depth"), QByteArray(b"0"))
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
            )
            authorization = basic_authorization_header(username, password)
            if authorization:
                request.setRawHeader(QByteArray(b"Authorization"), QByteArray(authorization))
            reply = self._calendar_network.sendCustomRequest(
                request,
                QByteArray(b"PROPFIND"),
                QByteArray(caldav_propfind_body()),
            )
        except (CalDAVError, CalendarSubscriptionError, OSError, RuntimeError, TypeError, ValueError) as exc:
            safe_message = str(exc)[:300] or "无法准备 CalDAV 连接。"
            self._repository.record_caldav_probe_result(account_id, error=safe_message)
            self._refresh()
            return False
        self._caldav_probe_replies[account_id] = reply
        self._caldav_probe_buffers[account_id] = bytearray()

        def receive_data() -> None:
            if self._caldav_probe_replies.get(account_id) is not reply:
                return
            chunk = bytes(reply.readAll())
            buffer = self._caldav_probe_buffers.get(account_id)
            if buffer is None:
                return
            if len(buffer) + len(chunk) > 512_000:
                self._caldav_probe_buffers.pop(account_id, None)
                reply.abort()
                return
            buffer.extend(chunk)

        reply.readyRead.connect(receive_data)
        reply.finished.connect(
            lambda account_id=account_id, reply=reply:
                self._finish_caldav_probe(account_id, reply)
        )
        self._refresh()
        return True

    @Slot(str, str, str, str, result="QVariant")
    def addCalDAVAccount(
        self, name: str, url: str, username: str, password: str,
    ) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        try:
            normalized_url, host = normalize_caldav_url(url)
            normalized_username, normalized_password = validate_caldav_credentials(
                username, password,
            )
            normalized_url, host = validate_caldav_transport(
                normalized_url, bool(normalized_username and normalized_password),
            )
            protected_url = protect_subscription_url(normalized_url)
            protected_credentials = protect_caldav_credentials(
                normalized_username, normalized_password, protect_subscription_url,
            )
            url_parts = urlsplit(normalized_url)
            source_identity = urlunsplit((
                url_parts.scheme.casefold(),
                url_parts.netloc.casefold(),
                url_parts.path or "/",
                url_parts.query,
                "",
            ))
            account = self._repository.add_caldav_account(
                name.strip() or host,
                host,
                protected_url,
                protected_credentials,
                source_identity=source_identity,
            )
        except (CalDAVError, CalendarSubscriptionError, PlannerRepositoryError,
                OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "CalDAV 账户无法保存。"}
        started = self._start_caldav_probe(str(account["id"]))
        return {"ok": True, "checkStarted": started, "state": self.state}

    @Slot(str, result="QVariant")
    def checkCalDAVAccount(self, account_id: str) -> dict[str, object]:
        started = self._start_caldav_probe(account_id)
        return {
            "ok": started,
            "error": "无法开始 CalDAV 连接检查。" if not started else "",
            "state": self.state,
        }

    @Slot(str, result="QVariant")
    def syncCalDAVTasks(self, account_id: str) -> dict[str, object]:
        started = self._start_caldav_task_sync(account_id)
        return {
            "ok": started,
            "error": "无法开始 CalDAV 待办同步。" if not started else "",
            "state": self.state,
        }

    @Slot(str, str, result="QVariant")
    def resolveCalDAVTaskConflict(self, record_id: str, choice: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(lambda: self._repository.resolve_caldav_task_conflict(record_id, choice))

    def _send_caldav_sync_report(
        self, account_id: str, phase: str, body: bytes, depth: str,
    ) -> None:
        job = self._caldav_sync_jobs.get(account_id)
        if job is None:
            return
        try:
            request = QNetworkRequest(QUrl(str(job["collectionUrl"])))
            request.setTransferTimeout(15_000)
            request.setHeader(
                QNetworkRequest.KnownHeaders.ContentTypeHeader,
                "application/xml; charset=utf-8",
            )
            request.setRawHeader(QByteArray(b"Depth"), QByteArray(depth.encode("ascii")))
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
            )
            authorization = job.get("authorization")
            if authorization:
                request.setRawHeader(QByteArray(b"Authorization"), QByteArray(authorization))
            job["phase"] = phase
            reply = self._calendar_network.sendCustomRequest(
                request, QByteArray(b"REPORT"), QByteArray(body),
            )
        except (CalDAVError, OSError, RuntimeError, TypeError, UnicodeError, ValueError) as exc:
            self._finish_caldav_task_sync_error(
                account_id, str(exc)[:300] or "无法准备 CalDAV 待办同步。",
            )
            return
        self._caldav_sync_replies[account_id] = reply
        self._caldav_sync_buffers[account_id] = bytearray()
        self._connect_caldav_sync_reply(account_id, reply, _MAX_CALDAV_SYNC_BYTES)

    def _fallback_caldav_full_report(self, account_id: str) -> None:
        job = self._caldav_sync_jobs.get(account_id)
        if job is None:
            return
        job.update({
            "fullSnapshot": True,
            "nextSyncToken": "",
            "syncCollectionUnsupported": True,
            "changes": {},
            "pageCount": 0,
        })
        self._send_caldav_sync_report(
            account_id, "full-report", caldav_vtodo_query_body(), "1",
        )

    def _apply_caldav_sync_resources(
        self, account_id: str, resources: list[dict[str, object]], removed_hrefs: list[str],
    ) -> None:
        job = self._caldav_sync_jobs.get(account_id)
        if job is None or self._repository is None:
            return
        try:
            result = self._repository.sync_caldav_vtodos(
                account_id,
                resources,
                complete_snapshot=bool(job.get("fullSnapshot")),
                removed_resource_hrefs=removed_hrefs,
                sync_token=str(job.get("nextSyncToken", "")),
                sync_collection_unsupported=bool(job.get("syncCollectionUnsupported")),
            )
        except (CalDAVError, PlannerRepositoryError, OSError, RuntimeError,
                sqlite3.Error, TypeError, ValueError) as exc:
            self._finish_caldav_task_sync_error(
                account_id, str(exc)[:300] or "CalDAV 待办同步失败，已保留上次成功的本机状态。",
            )
            return
        job["writebacks"] = result["writebacks"]
        job["writebackIndex"] = 0
        job["conflicts"] = result["conflicts"]
        job["resourceCount"] = result["resourceCount"]
        job["eventCount"] = result["eventCount"]
        job["unsupportedResourceCount"] = result["unsupportedResourceCount"]
        self._start_next_caldav_writeback(account_id)

    def _finish_caldav_sync_collection_page(self, account_id: str, body: bytes) -> None:
        job = self._caldav_sync_jobs.get(account_id)
        if job is None or self._repository is None:
            return
        try:
            page = parse_caldav_sync_collection_report(body, str(job["collectionUrl"]))
            changes = job.get("changes")
            if not isinstance(changes, dict):
                raise CalDAVError("CalDAV 增量状态无效，未应用本次同步。")
            for change in page["changes"]:
                if not isinstance(change, dict):
                    raise CalDAVError("CalDAV 增量资源状态无效，未应用本次同步。")
                href = str(change["href"])
                changes[href] = change
            if len(changes) > 500:
                raise CalDAVError("一次增量同步最多处理 500 个资源变更。")
            job["nextSyncToken"] = page["syncToken"]
            page_count = int(job.get("pageCount", 0) or 0) + 1
            job["pageCount"] = page_count
            if page["truncated"]:
                if page_count >= 30:
                    raise CalDAVError("CalDAV 分页超过 30 次，已保留上次成功的本机状态。")
                job["requestSyncToken"] = page["syncToken"]
                self._send_caldav_sync_report(
                    account_id,
                    "sync-report",
                    caldav_sync_collection_body(page["syncToken"]),
                    "0",
                )
                return

            changed_hrefs = {
                href for href, item in changes.items()
                if item.get("removed") != "true"
            }
            removed_hrefs = {
                href for href, item in changes.items()
                if item.get("removed") == "true"
            }
            changed_hrefs.update(self._repository.caldav_pending_resource_hrefs(account_id))
            resolved_hrefs = sorted({
                resolve_caldav_resource_url(str(job["collectionUrl"]), href)
                for href in changed_hrefs
            })
            job["removedHrefs"] = sorted(removed_hrefs)
            if len(resolved_hrefs) > 500:
                raise CalDAVError("一次同步最多读取 500 个 CalDAV 资源。")
            if not resolved_hrefs:
                self._apply_caldav_sync_resources(account_id, [], sorted(removed_hrefs))
                return
            job["requestedHrefs"] = resolved_hrefs
            self._send_caldav_sync_report(
                account_id,
                "multiget",
                caldav_calendar_multiget_body(resolved_hrefs),
                "1",
            )
        except (CalDAVError, PlannerRepositoryError, OSError, RuntimeError,
                sqlite3.Error, TypeError, ValueError, KeyError) as exc:
            self._finish_caldav_task_sync_error(
                account_id, str(exc)[:300] or "CalDAV 增量同步失败，已保留上次成功的本机状态。",
            )

    def _finish_caldav_task_sync(self, account_id: str, reply: QNetworkReply) -> None:
        if self._caldav_sync_replies.get(account_id) is not reply:
            reply.deleteLater()
            return
        self._caldav_sync_replies.pop(account_id, None)
        buffer = self._caldav_sync_buffers.pop(account_id, None)
        job = self._caldav_sync_jobs.get(account_id)
        if job is None or self._repository is None:
            reply.deleteLater()
            return
        trailing = bytes(reply.readAll())
        status_value = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = int(status_value) if status_value is not None else 0
        response_etag = bytes(reply.rawHeader("ETag"))
        phase = str(job.get("phase", "report"))
        if buffer is None or len(buffer) + len(trailing) > _MAX_CALDAV_SYNC_BYTES:
            reply.deleteLater()
            self._finish_caldav_task_sync_error(account_id, "CalDAV 响应超过 2 MB，已保留本机任务。")
            return
        body = bytes(buffer) + trailing
        network_error = reply.error()
        reply.deleteLater()
        if phase in {"sync-report", "full-report", "multiget"}:
            if status == 401:
                self._finish_caldav_task_sync_error(account_id, "CalDAV 服务器拒绝登录，请检查账号和密码。")
                return
            if status in {301, 302, 303, 307, 308}:
                self._finish_caldav_task_sync_error(account_id, "服务器要求跳转；为保护登录信息，请改用跳转后的 HTTPS 地址。")
                return

            if phase == "sync-report" and status == 403:
                if caldav_sync_token_was_rejected(body):
                    if str(job.get("requestSyncToken", "")):
                        job.update({
                            "fullSnapshot": True,
                            "nextSyncToken": "",
                            "requestSyncToken": "",
                            "syncCollectionUnsupported": False,
                            "changes": {},
                            "pageCount": 0,
                        })
                        self._send_caldav_sync_report(
                            account_id, "sync-report", caldav_sync_collection_body(""), "0",
                        )
                    else:
                        self._fallback_caldav_full_report(account_id)
                    return
                self._fallback_caldav_full_report(account_id)
                return
            if phase == "sync-report" and status in {400, 405, 501}:
                self._fallback_caldav_full_report(account_id)
                return
            if status != 207 or network_error != QNetworkReply.NetworkError.NoError:
                if status == 403:
                    self._finish_caldav_task_sync_error(account_id, "此账户无权读取 CalDAV 待办。")
                    return
                message = f"CalDAV 待办同步失败（HTTP {status}）。" if status else "无法连接 CalDAV 服务器，已保留本机任务。"
                self._finish_caldav_task_sync_error(account_id, message)
                return

            try:
                if phase == "sync-report":
                    job["requestSyncToken"] = ""
                    self._finish_caldav_sync_collection_page(account_id, body)
                    return
                if phase == "full-report":
                    resources = parse_caldav_vtodo_report(body, str(job["collectionUrl"]))
                    self._apply_caldav_sync_resources(account_id, resources, [])
                    return

                requested = job.get("requestedHrefs")
                if not isinstance(requested, list):
                    raise CalDAVError("CalDAV 多资源请求状态无效。")
                result = parse_caldav_calendar_multiget_report(
                    body, str(job["collectionUrl"]), requested,
                )
                removed = set(job.get("removedHrefs", []))
                removed.update(result["removedHrefs"])
                self._apply_caldav_sync_resources(
                    account_id, result["resources"], sorted(removed),
                )
                return
            except (CalDAVError, PlannerRepositoryError, OSError, RuntimeError,
                    sqlite3.Error, TypeError, ValueError, KeyError) as exc:
                self._finish_caldav_task_sync_error(
                    account_id, str(exc)[:300] or "CalDAV 待办同步失败，已保留上次成功的本机状态。",
                )
                return

        pending = self._current_caldav_writeback(job)
        if pending is None:
            self._finish_caldav_task_sync_error(account_id, "CalDAV 回写队列状态无效。")
            return
        if status == 412:
            self._finish_caldav_task_sync_error(
                account_id, "远端任务在回写前已变化；本机完成状态已保留，请再次同步。",
            )
            return
        if status == 401:
            self._finish_caldav_task_sync_error(account_id, "CalDAV 服务器拒绝回写，请检查账户权限。")
            return
        if status == 403 or status == 405:
            self._finish_caldav_task_sync_error(account_id, "CalDAV 账户没有修改待办的权限；本机完成状态已保留。")
            return
        if status not in {200, 201, 204} or network_error != QNetworkReply.NetworkError.NoError:
            message = f"CalDAV 完成状态回写失败（HTTP {status}）；本机状态已保留。" if status else "CalDAV 回写连接中断；本机状态已保留。"
            self._finish_caldav_task_sync_error(account_id, message)
            return
        try:
            etag = response_etag.decode("latin-1") if response_etag else ""
            confirmed = self._repository.record_caldav_task_writeback(
                account_id, pending["uid"], pending["done"], etag,
            )
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError):
            self._finish_caldav_task_sync_error(account_id, "远端已接受完成状态，但本机确认结果暂未保存；再次同步可核对。")
            return
        if not confirmed:
            self._finish_caldav_task_sync_error(
                account_id,
                "远端已接受完成状态，但对应的本机待办已被删除；请再次同步核对服务器状态。",
            )
            return
        job["writebackIndex"] = int(job.get("writebackIndex", 0) or 0) + 1
        self._start_next_caldav_writeback(account_id)

    @staticmethod
    def _current_caldav_writeback(job: dict[str, object]) -> dict[str, object] | None:
        writes = job.get("writebacks")
        index = job.get("writebackIndex")
        if not isinstance(writes, list) or isinstance(index, bool) or not isinstance(index, int):
            return None
        if not 0 <= index < len(writes) or not isinstance(writes[index], dict):
            return None
        return writes[index]

    def _cancel_caldav_writeback_for_deleted_task(self, record_id: str) -> None:
        for account_id, job in list(self._caldav_sync_jobs.items()):
            writes = job.get("writebacks")
            index = job.get("writebackIndex")
            if (
                not isinstance(writes, list)
                or isinstance(index, bool)
                or not isinstance(index, int)
                or not 0 <= index <= len(writes)
            ):
                continue
            pending = writes[index:]
            kept_pending = [
                item for item in pending
                if not isinstance(item, dict) or item.get("recordId") != record_id
            ]
            if len(kept_pending) == len(pending):
                continue
            current = self._current_caldav_writeback(job)
            current_deleted = isinstance(current, dict) and current.get("recordId") == record_id
            job["writebacks"] = [*writes[:index], *kept_pending]
            if current_deleted and job.get("phase") == "put":
                job["writebackCancelledDuringDelete"] = True
                reply = self._caldav_sync_replies.pop(account_id, None)
                self._caldav_sync_buffers.pop(account_id, None)
                if reply is not None:
                    reply.abort()
                QTimer.singleShot(
                    0,
                    lambda account_id=account_id: self._start_next_caldav_writeback(account_id),
                )

    def _start_next_caldav_writeback(self, account_id: str) -> None:
        job = self._caldav_sync_jobs.get(account_id)
        if job is None or self._repository is None:
            return
        pending = self._current_caldav_writeback(job)
        if pending is None:
            conflicts = int(job.get("conflicts", 0) or 0)
            self._repository.record_caldav_sync_result(account_id)
            count = int(job.get("resourceCount", 0) or 0)
            event_count = int(job.get("eventCount", 0) or 0)
            self._notice = f"CalDAV 已同步 {count} 个待办、{event_count} 个日程。"
            if job.get("writebackCancelledDuringDelete"):
                self._notice += " 同步期间删除了一项待办，已取消它的待处理回写；请再次同步核对服务器状态。"
            unsupported = int(job.get("unsupportedResourceCount", 0) or 0)
            if unsupported:
                self._notice += f" {unsupported} 项循环 VTODO 暂不支持，已跳过；其他日历内容已同步。"
            if conflicts:
                self._notice += f" {conflicts} 项完成状态有冲突，请在任务行中选择保留哪一侧。"
            self._notice_is_error = False
            self._caldav_sync_jobs.pop(account_id, None)
            self._refresh()
            return
        etag = pending.get("etag", "")
        if not is_strong_caldav_etag(etag):
            self._finish_caldav_task_sync_error(
                account_id, "服务器没有为任务提供强 ETag，已保留本机完成状态且未覆盖远端。",
            )
            return
        try:
            base_url = str(job["collectionUrl"])
            resource_url = resolve_caldav_resource_url(base_url, pending.get("href"))
            updated = update_vtodo_completion(
                pending.get("calendarData"),
                str(pending.get("uid", "")),
                bool(pending.get("done")),
            )
            request = QNetworkRequest(QUrl(resource_url))
            request.setTransferTimeout(15_000)
            request.setHeader(
                QNetworkRequest.KnownHeaders.ContentTypeHeader,
                "text/calendar; charset=utf-8",
            )
            request.setRawHeader(QByteArray(b"If-Match"), QByteArray(str(etag).encode("latin-1")))
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.ManualRedirectPolicy,
            )
            authorization = job.get("authorization")
            if authorization:
                request.setRawHeader(QByteArray(b"Authorization"), QByteArray(authorization))
            reply = self._calendar_network.put(request, QByteArray(updated.encode("utf-8")))
        except (CalDAVError, OSError, RuntimeError, TypeError, UnicodeError, ValueError) as exc:
            self._finish_caldav_task_sync_error(account_id, str(exc)[:300] or "无法准备 CalDAV 完成状态回写。")
            return
        job["phase"] = "put"
        self._caldav_sync_replies[account_id] = reply
        self._caldav_sync_buffers[account_id] = bytearray()
        self._connect_caldav_sync_reply(account_id, reply, _MAX_CALDAV_PUT_RESPONSE_BYTES)

    def _connect_caldav_sync_reply(self, account_id: str, reply: QNetworkReply, limit: int) -> None:
        def receive_data() -> None:
            if self._caldav_sync_replies.get(account_id) is not reply:
                return
            chunk = bytes(reply.readAll())
            buffer = self._caldav_sync_buffers.get(account_id)
            if buffer is None:
                return
            if len(buffer) + len(chunk) > limit:
                self._caldav_sync_buffers[account_id] = None
                reply.abort()
                return
            buffer.extend(chunk)

        reply.readyRead.connect(receive_data)
        reply.finished.connect(
            lambda account_id=account_id, reply=reply:
                self._finish_caldav_task_sync(account_id, reply)
        )

    def _finish_caldav_task_sync_error(self, account_id: str, message: str) -> None:
        reply = self._caldav_sync_replies.pop(account_id, None)
        self._caldav_sync_buffers.pop(account_id, None)
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        self._caldav_sync_jobs.pop(account_id, None)
        if self._repository is not None:
            try:
                self._repository.record_caldav_sync_result(account_id, message[:300])
            except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError):
                pass
        self._notice = message[:300]
        self._notice_is_error = True
        self._refresh()

    def _start_caldav_task_sync(self, account_id: str) -> bool:
        if self._repository is None or not isinstance(account_id, str) or not account_id:
            return False
        if account_id in self._caldav_sync_jobs:
            return False
        details = self._repository.caldav_account_details(account_id)
        if details is None:
            return False
        try:
            url = unprotect_subscription_url(details.get("urlProtected"))
            username, password = unprotect_caldav_credentials(
                details.get("credentialsProtected"), unprotect_subscription_url,
            )
            normalized_url, _host = validate_caldav_transport(
                url, bool(username and password),
            )
            authorization = basic_authorization_header(username, password)
            sync_token = details.get("syncToken", "")
            unsupported = details.get("syncCollectionUnsupported", False)
            if not isinstance(sync_token, str) or not isinstance(unsupported, bool):
                raise CalDAVError("CalDAV 同步状态无效，请重新检查账户。")
            if not unsupported:
                caldav_sync_collection_body(sync_token)
        except (CalDAVError, CalendarSubscriptionError, OSError, RuntimeError,
                TypeError, UnicodeError, ValueError) as exc:
            self._notice = str(exc)[:300] or "无法准备 CalDAV 待办同步。"
            self._notice_is_error = True
            self._refresh()
            return False
        self._caldav_sync_jobs[account_id] = {
            "collectionUrl": normalized_url,
            "authorization": authorization,
            "phase": "sync-report",
            "writebacks": [],
            "writebackIndex": 0,
            "conflicts": 0,
            "resourceCount": 0,
            "eventCount": 0,
            "fullSnapshot": not bool(sync_token),
            "requestSyncToken": sync_token,
            "nextSyncToken": sync_token,
            "syncCollectionUnsupported": False,
            "changes": {},
            "pageCount": 0,
        }
        if unsupported:
            self._fallback_caldav_full_report(account_id)
        else:
            self._send_caldav_sync_report(
                account_id,
                "sync-report",
                caldav_sync_collection_body(sync_token),
                "0",
            )
        self._refresh()
        return True

    @Slot(str, result="QVariant")
    def removeCalDAVAccount(self, account_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        reply = self._caldav_probe_replies.pop(account_id, None)
        self._caldav_probe_buffers.pop(account_id, None)
        if reply is not None:
            reply.abort()
        sync_reply = self._caldav_sync_replies.pop(account_id, None)
        self._caldav_sync_buffers.pop(account_id, None)
        self._caldav_sync_jobs.pop(account_id, None)
        if sync_reply is not None:
            sync_reply.abort()

        def remove() -> None:
            if not self._repository.remove_caldav_account(account_id):
                raise PlannerRepositoryError("该 CalDAV 账户已不存在，列表已刷新。")

        return self._run(remove)

    def reload_from_database(self) -> None:
        try:
            self._repository = PlannerRepository(self._database_path)
            self._notice = ""
            self._notice_is_error = False
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "日程数据暂时无法载入。"
            self._notice_is_error = True
        self._refresh()

    def _run(self, operation: object) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        try:
            operation()  # type: ignore[operator]
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "日程操作没有保存，请检查后重试。"
            self._notice_is_error = True
            self._refresh()
            return {"ok": False, "error": self._notice}
        self._notice = ""
        self._notice_is_error = False
        self._refresh()
        return {"ok": True}

    @Slot(str, result="QVariant")
    def setFilter(self, value: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(lambda: self._repository.set_filter(value))

    @Slot(str, str, result="QVariant")
    def setTaskFilters(self, project: str, tag: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(lambda: self._repository.set_task_filters(project, tag))

    @Slot(str, result="QVariant")
    def setViewMode(self, value: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(lambda: self._repository.set_view_mode(value))

    @Slot("QVariant", result="QVariant")
    def saveCustomBoard(self, value: object) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(lambda: self._repository.save_custom_board(self._variant(value)))

    @Slot(str, result="QVariant")
    def deleteCustomBoard(self, value: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(lambda: self._repository.delete_custom_board(value))

    @Slot(str, str, str, str, str, str, result="QVariant")
    def moveTaskToBoardColumn(
        self,
        record_id: str,
        status: str,
        tag: str,
        board_id: str = "",
        column_id: str = "",
        before_task_id: str = "",
    ) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}

        def move() -> None:
            if self._repository.move_task_to_custom_board_column(
                record_id, status, tag, board_id, column_id, before_task_id
            ) is None:
                raise PlannerRepositoryError("这项待办已不存在，列表已刷新。")

        return self._run(move)

    @Slot("QVariant")
    def saveDraft(self, value: object) -> None:
        if self._repository is None:
            return
        try:
            self._repository.save_draft(self._variant(value))
            self._notice = ""
            self._notice_is_error = False
            self._refresh()
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "日程草稿保存失败。"
            self._notice_is_error = True
            self._refresh()

    @Slot()
    def clearDraft(self) -> None:
        if self._repository is not None:
            self._run(self._repository.clear_draft)

    @Slot(str, result="QVariant")
    def setSelectedDay(self, value: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(lambda: self._repository.set_selected_day(value))

    @Slot(str, str, str, str, str, str, bool, int, str, result="QVariant")
    def addTask(
        self, title: str, day: str, time: str, priority: str,
        list_name: str, note: str, remind: bool, estimate_minutes: int = 30,
        repeat: str = "none",
    ) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(lambda: self._repository.add_task(
            title, day, time, priority, list_name, note, remind, estimate_minutes, repeat,
        ))

    @Slot(str, str, str, str, str, str, bool, int, str, str, str, result="QVariant")
    def addTaskWithOrganization(
        self, title: str, day: str, time: str, priority: str,
        list_name: str, note: str, remind: bool, estimate_minutes: int,
        repeat: str, project: str, tags_text: str,
    ) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        if not isinstance(tags_text, str):
            return {"ok": False, "error": "标签必须是文本。"}
        tags = [item.strip() for item in tags_text.split(",") if item.strip()]
        return self._run(lambda: self._repository.add_task(
            title, day, time, priority, list_name, note, remind, estimate_minutes,
            repeat, project, tags,
        ))

    @Slot(str, str, str, str, str, str, str, bool, int, str, str, str, result="QVariant")
    def updateTaskWithOrganization(
        self, record_id: str, title: str, day: str, time: str, priority: str,
        list_name: str, note: str, remind: bool, estimate_minutes: int,
        repeat: str, project: str, tags_text: str,
    ) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        if not isinstance(tags_text, str):
            return {"ok": False, "error": "标签必须是文本。"}
        tags = [item.strip() for item in tags_text.split(",") if item.strip()]

        def update() -> None:
            if self._repository.update_task(
                record_id, title, day, time, priority, list_name, note, remind,
                estimate_minutes, repeat, project, tags,
            ) is None:
                raise PlannerRepositoryError("这项待办已不存在，列表已刷新。")

        return self._run(update)

    @Slot(str, str, str, result="QVariant")
    def setTaskOrganization(
        self, record_id: str, project: str, tags_text: str,
    ) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        if not isinstance(tags_text, str):
            return {"ok": False, "error": "标签必须是文本。"}
        tags = [item.strip() for item in tags_text.split(",") if item.strip()]

        def update() -> None:
            if self._repository.set_task_organization(record_id, project, tags) is None:
                raise PlannerRepositoryError("这项待办已不存在，列表已刷新。")

        return self._run(update)

    @Slot(str, str, result="QVariant")
    def setTaskStatus(self, record_id: str, status: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}

        def update() -> None:
            if self._repository.set_task_status(record_id, status) is None:
                raise PlannerRepositoryError("这项待办已不存在，列表已刷新。")

        return self._run(update)

    @Slot(str, "QVariant", result="QVariant")
    def setBoardOrder(self, status: str, ordered_ids: object) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        order_value = self._variant(ordered_ids)
        return self._run(lambda: self._repository.set_board_order(status, order_value))

    @Slot(str, str, str, result="QVariant")
    def moveTaskOnStandardBoard(
        self, record_id: str, target_status: str, before_task_id: str = "",
    ) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}

        def move() -> None:
            moved = self._repository.move_task_on_standard_board(
                record_id, target_status, before_task_id,
            )
            if moved is None:
                raise PlannerRepositoryError("这项待办已不存在，列表已刷新。")

        return self._run(move)

    @Slot(str, str, result="QVariant")
    def addSubtask(self, parent_id: str, title: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}

        def add() -> None:
            if self._repository.add_subtask(parent_id, title) is None:
                raise PlannerRepositoryError("父任务已不存在，列表已刷新。")

        return self._run(add)

    @Slot(str, str, str, int, result="QVariant")
    def scheduleTask(self, record_id: str, day: str, start_time: str, duration_minutes: int) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}

        def schedule() -> None:
            if self._repository.schedule_task(record_id, day, start_time, duration_minutes) is None:
                raise PlannerRepositoryError("这项待办已不存在，列表已刷新。")

        return self._run(schedule)

    @Slot(str, result="QVariant")
    def unscheduleTask(self, record_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        def unschedule() -> None:
            if self._repository.unschedule_task(record_id) is None:
                raise PlannerRepositoryError("这项待办已不存在，列表已刷新。")
        return self._run(unschedule)

    @Slot(str, int, result="QVariant")
    def setEstimate(self, record_id: str, duration_minutes: int) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        def update() -> None:
            if self._repository.set_estimate(record_id, duration_minutes) is None:
                raise PlannerRepositoryError("这项待办已不存在，列表已刷新。")
        return self._run(update)

    @Slot(str, result="QVariant")
    def startTrackingTask(self, record_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}

        def start() -> None:
            if self._repository.start_tracking(record_id) is None:
                raise PlannerRepositoryError("这项待办已不存在，列表已刷新。")

        return self._run(start)

    @Slot(str, str, int, result="QVariant")
    def startFocusTask(self, record_id: str, mode: str, duration_minutes: int = 25) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}

        def start() -> None:
            if self._repository.start_focus_tracking(record_id, mode, duration_minutes) is None:
                raise PlannerRepositoryError("这项待办已不存在，列表已刷新。")

        return self._run(start)

    @Slot(result="QVariant")
    def pauseTrackingTask(self) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(self._repository.pause_tracking)

    @Slot(result="QVariant")
    def resumeTrackingTask(self) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(self._repository.resume_tracking)

    @Slot(str, str, result="QVariant")
    def getTimesheet(self, start_date: str, end_date: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        try:
            report = self._repository.timesheet(start_date, end_date)
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "工时复盘暂时无法生成。"
            self._notice_is_error = True
            self._refresh()
            return {"ok": False, "error": self._notice}
        self._notice = ""
        self._notice_is_error = False
        self._refresh()
        return {"ok": True, "data": report}

    @Slot(QUrl, str, str, result="QVariant")
    def exportTimesheetCsv(self, file_url: QUrl, start_date: str, end_date: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        if not file_url.isLocalFile():
            return {"ok": False, "error": "请选择本机 CSV 保存位置。"}
        try:
            saved_path = self._repository.export_timesheet_csv(
                Path(file_url.toLocalFile()), start_date, end_date,
            )
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "工时 CSV 导出失败。"
            self._notice_is_error = True
            self._refresh()
            return {"ok": False, "error": self._notice}
        self._notice = ""
        self._notice_is_error = False
        self._refresh()
        return {"ok": True, "path": str(saved_path)}

    @Slot(QUrl, result="QVariant")
    def importCalendarIcs(self, file_url: QUrl) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        if not file_url.isLocalFile():
            return {"ok": False, "error": "请选择本机 ICS 文件。"}
        try:
            source_path = Path(file_url.toLocalFile())
            if source_path.stat().st_size > 2_000_000:
                raise PlannerRepositoryError("ICS 文件不能超过 2 MB。")
            try:
                contents = source_path.read_bytes().decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise PlannerRepositoryError("ICS 文件须使用 UTF-8 编码。") from exc
            imported = self._repository.import_calendar(
                contents, source_path.name, str(source_path.resolve()),
            )
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "ICS 日历无法导入。"
            self._notice_is_error = True
            self._refresh()
            return {"ok": False, "error": self._notice}
        self._notice = ""
        self._notice_is_error = False
        self._refresh()
        return {"ok": True, "data": imported, "state": self.state}

    @Slot(QUrl, str, str, result="QVariant")
    def exportCalendarIcs(self, file_url: QUrl, start_date: str, end_date: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        if not file_url.isLocalFile():
            return {"ok": False, "error": "请选择本机 ICS 保存位置。"}
        try:
            saved_path = self._repository.export_calendar_ics(
                Path(file_url.toLocalFile()), start_date, end_date,
            )
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "ICS 日程导出失败。"
            self._notice_is_error = True
            self._refresh()
            return {"ok": False, "error": self._notice}
        self._notice = ""
        self._notice_is_error = False
        self._refresh()
        return {"ok": True, "path": str(saved_path)}

    @Slot(result="QVariant")
    def stopTrackingTask(self) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(self._repository.stop_tracking)

    @Slot(str, result="QVariant")
    def toggleTask(self, record_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}
        return self._run(lambda: self._repository.toggle_task(record_id))

    @Slot(str, result="QVariant")
    def deleteTask(self, record_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "日程功能暂不可用。"}

        def remove() -> None:
            if not self._repository.delete_task(record_id):
                raise PlannerRepositoryError("这项日程已不存在，列表已刷新。")
            self._cancel_caldav_writeback_for_deleted_task(record_id)

        return self._run(remove)

    @Slot()
    def checkReminders(self) -> None:
        if self._repository is None:
            return
        try:
            due = self._repository.check_due_reminders()
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "日程提醒暂时无法检查。"
            self._notice_is_error = True
            self._refresh()
            return
        if due:
            self._notice = ""
            self._notice_is_error = False
            self._refresh()
            self.remindersDue.emit(due)

    @Slot()
    def _clockTick(self) -> None:
        self.checkReminders()
        if self._repository is not None:
            try:
                active = self._repository.state().get("activeTracking")
                if active:
                    completed_mode = self._repository.complete_tracking_if_due()
                    if completed_mode:
                        self._notice = (
                            "番茄钟完成，实际用时已保存。建议休息 5 分钟。"
                            if completed_mode == "pomodoro"
                            else "倒计时结束，实际用时已保存。"
                        )
                        self._notice_is_error = False
                    elif not active.get("paused", False):
                        self._repository.checkpoint_tracking()
                    self._refresh()
            except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
                self._notice = str(exc) or "任务计时暂时无法更新。"
                self._notice_is_error = True
                self._refresh()

    @Slot()
    def close(self) -> None:
        self._reminder_clock.stop()
        if self._repository is None:
            return
        try:
            completed_mode = self._repository.complete_tracking_if_due()
            active = self._repository.state().get("activeTracking") or {}
            if active and active.get("mode", "stopwatch") != "stopwatch":
                self._repository.pause_tracking()
            else:
                self._repository.stop_tracking()
            if completed_mode == "pomodoro":
                self._notice = "番茄钟完成，实际用时已保存。建议休息 5 分钟。"
            elif completed_mode == "countdown":
                self._notice = "倒计时结束，实际用时已保存。"
            if completed_mode:
                self._notice_is_error = False
        except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "关闭日程前保存实际用时失败。"
            self._notice_is_error = True

    def has_pending_reminders(self) -> bool:
        if self._repository is None:
            raise RuntimeError(self._notice or "日程数据暂时无法检查。")
        return self._repository.has_pending_reminders()

    @Slot("QVariant", result="QVariant")
    def sendSystemNotifications(self, reminders: object) -> dict[str, object]:
        """Send best-effort tray notices after QML has opened the in-app popup."""
        if isinstance(reminders, QJSValue):
            reminders = reminders.toVariant()
        if not isinstance(reminders, list):
            return {"sent": 0, "failed": 0, "reasons": ["提醒列表无效。"]}
        sent = 0
        reasons: list[str] = []
        for reminder in reminders:
            if not isinstance(reminder, dict):
                continue
            title = reminder.get("title", "日程提醒")
            body = reminder.get("body", "该处理这件日程了。")
            if self._notifier is None:
                reasons.append("系统通知不可用，应用内提醒仍然有效。")
                continue
            result = self._notifier.notify(title, body)
            if result.sent:
                sent += 1
            else:
                reasons.append(result.reason)
        return {"sent": sent, "failed": len(reasons), "reasons": reasons}

    @Slot("QVariant")
    def adoptImportedData(self, migration_snapshot: object) -> None:
        if self._repository is None:
            try:
                self._repository = PlannerRepository(self._database_path, self._variant(migration_snapshot))
            except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
                self._notice = str(exc) or "已导入数据，但日程列表无法载入。"
                self._notice_is_error = True
                self._refresh()
                return
        else:
            try:
                self._repository.adopt_imported_data(self._variant(migration_snapshot))
            except (PlannerRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
                self._notice = str(exc) or "已导入数据，但日程列表无法更新。"
                self._notice_is_error = True
                self._refresh()
                return
        self._notice = ""
        self._notice_is_error = False
        self._refresh()

    def activity_records(self) -> list[dict[str, object]]:
        return self._repository.all_records() if self._repository is not None else []

    def activity_tombstones(self) -> list[dict[str, str]]:
        return self._repository.deleted_record_keys() if self._repository is not None else []


class ShoppingBridge(QObject):
    """QML adapter for the local shopping list and its persistent filter."""

    stateChanged = Signal()

    def __init__(self, database_path: Path, migration_snapshot: object = None) -> None:
        super().__init__()
        self._database_path = database_path
        self._repository: ShoppingRepository | None = None
        self._notice = ""
        self._state: dict[str, object] = {"records": [], "shoppingRecords": [], "settings": {}, "summary": {}, "notice": ""}
        try:
            self._repository = ShoppingRepository(database_path, migration_snapshot)
            self._refresh(emit=False)
        except (ShoppingRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "待买清单数据暂时无法载入。"
            self._state["notice"] = self._notice

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return deepcopy(self._state)

    @staticmethod
    def _variant(value: object) -> object:
        return value.toVariant() if isinstance(value, QJSValue) else value

    def _refresh(self, *, emit: bool = True) -> None:
        if self._repository is not None:
            self._state = self._repository.state()
            self._state["notice"] = self._notice
        if emit:
            QTimer.singleShot(0, self, self.stateChanged.emit)

    def reload_from_database(self) -> None:
        try:
            self._repository = ShoppingRepository(self._database_path)
            self._notice = ""
        except (ShoppingRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "待买数据暂时无法载入。"
        self._refresh()

    def _run(self, operation: object) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "待买清单暂不可用。"}
        try:
            operation()  # type: ignore[operator]
        except (ShoppingRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "待买清单操作没有保存，请检查后重试。"
            self._refresh()
            return {"ok": False, "error": self._notice}
        self._notice = ""
        self._refresh()
        return {"ok": True}

    @Slot(str, str, str, str, str, str, result="QVariant")
    def addItem(self, name: str, quantity: str, category: str, price: str,
                priority: str, note: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "待买清单暂不可用。"}
        return self._run(lambda: self._repository.add_item(name, quantity, category, price, priority, note))

    @Slot(str, result="QVariant")
    def setFilter(self, value: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "待买清单暂不可用。"}
        return self._run(lambda: self._repository.set_filter(value))

    @Slot(str, bool, result="QVariant")
    def toggleBought(self, record_id: str, bought: bool) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "待买清单暂不可用。"}
        return self._run(lambda: self._repository.toggle_bought(record_id, bought))

    @Slot(str, result="QVariant")
    def deleteItem(self, record_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "待买清单暂不可用。"}

        def remove() -> None:
            if not self._repository.delete_item(record_id):
                raise ShoppingRepositoryError("这件物品已不存在，列表已刷新。")

        return self._run(remove)

    @Slot("QVariant")
    def adoptImportedData(self, migration_snapshot: object) -> None:
        if self._repository is None:
            try:
                self._repository = ShoppingRepository(self._database_path, self._variant(migration_snapshot))
            except (ShoppingRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
                self._notice = str(exc) or "已导入数据，但待买清单无法载入。"
                self._refresh()
                return
        else:
            try:
                self._repository.adopt_imported_data(self._variant(migration_snapshot))
            except (ShoppingRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
                self._notice = str(exc) or "已导入数据，但待买清单无法更新。"
                self._refresh()
                return
        self._notice = ""
        self._refresh()

    def activity_records(self) -> list[dict[str, object]]:
        return self._repository.records() if self._repository is not None else []

    def activity_tombstones(self) -> list[dict[str, str]]:
        return self._repository.deleted_record_keys() if self._repository is not None else []


class MediaBridge(QObject):
    """QML adapter for the separate local bookshelf/media collection."""

    stateChanged = Signal()

    def __init__(self, database_path: Path, migration_snapshot: object = None) -> None:
        super().__init__()
        self._database_path = database_path
        self._repository: MediaRepository | None = None
        self._notice = ""
        self._state: dict[str, object] = {
            "items": [], "filteredItems": [], "settings": {}, "summary": {}, "draft": {}, "notice": ""
        }
        try:
            self._repository = MediaRepository(database_path, migration_snapshot)
            self._refresh(emit=False)
        except (MediaRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "书影音数据暂时无法载入。"
            self._state["notice"] = self._notice

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return deepcopy(self._state)

    @staticmethod
    def _variant(value: object) -> object:
        return value.toVariant() if isinstance(value, QJSValue) else value

    def _refresh(self, *, emit: bool = True) -> None:
        if self._repository is not None:
            self._state = self._repository.state()
            self._state["notice"] = self._notice
        if emit:
            QTimer.singleShot(0, self, self.stateChanged.emit)

    def reload_from_database(self) -> None:
        try:
            self._repository = MediaRepository(self._database_path)
            self._notice = ""
        except (MediaRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "书影音数据暂时无法载入。"
        self._refresh()

    def _run(self, operation: object, success: str = "") -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "书影音功能暂不可用。"}
        try:
            operation()  # type: ignore[operator]
        except (MediaRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "书影音操作没有保存，请检查本机数据后重试。"
            self._refresh()
            return {"ok": False, "error": self._notice}
        self._notice = ""
        self._refresh()
        return {"ok": True, "message": success}

    @Slot(str, str, str, "QVariant", str, str, str, result="QVariant")
    def addItem(self, name: str, kind: str, status: str, rating: object,
                review: str, day: str, cover: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "书影音功能暂不可用。"}
        return self._run(
            lambda: self._repository.add_item(name, kind, status, rating, review, day, cover),
            "作品已保存到本机。",
        )

    @Slot(str, result="QVariant")
    def deleteItem(self, item_id: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "书影音功能暂不可用。"}

        def remove() -> None:
            if not self._repository.delete_item(item_id):
                raise MediaRepositoryError("这条书影音记录已不存在，请刷新列表。")

        return self._run(remove, "作品已从本机清单移除。")

    @Slot(str, result="QVariant")
    def setView(self, value: str) -> dict[str, object]:
        return self._run(lambda: self._repository.set_view(value), "已切换视图。") if self._repository else {
            "ok": False, "error": self._notice or "书影音功能暂不可用。"
        }

    @Slot(str, result="QVariant")
    def setStatusFilter(self, value: str) -> dict[str, object]:
        return self._run(lambda: self._repository.set_status_filter(value), "已切换状态筛选。") if self._repository else {
            "ok": False, "error": self._notice or "书影音功能暂不可用。"
        }

    @Slot(int, result="QVariant")
    def setRatingFilter(self, value: int) -> dict[str, object]:
        return self._run(lambda: self._repository.set_rating_filter(value), "已切换评分筛选。") if self._repository else {
            "ok": False, "error": self._notice or "书影音功能暂不可用。"
        }

    @Slot("QVariant", result="QVariant")
    def saveDraft(self, fields: object) -> dict[str, object]:
        fields = self._variant(fields)
        if self._repository is None:
            return {"ok": False, "error": self._notice or "书影音功能暂不可用。"}
        return self._run(lambda: self._repository.save_draft(fields))

    @Slot(str, result="QVariant")
    def prepareCover(self, source: str) -> dict[str, object]:
        try:
            return {"ok": True, **prepare_cover_file(source)}
        except (MediaRepositoryError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "封面图片处理失败。"}

    @Slot("QVariant")
    def adoptImportedData(self, snapshot: object) -> None:
        value = self._variant(snapshot)
        try:
            if self._repository is None:
                self._repository = MediaRepository(self._database_path, value)
            else:
                self._repository.adopt_imported_data(value)
        except (MediaRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "已导入数据，但书影音列表无法更新。"
            self._refresh()
            return
        self._notice = ""
        self._refresh()

    def activity_items(self) -> list[dict[str, object]]:
        return self._repository.activity_items() if self._repository is not None else []


class ArchiveBridge(QObject):
    """Read-only archive projection over already merged effective records."""

    stateChanged = Signal()

    def __init__(self, database_path: Path, migration_snapshot: object = None) -> None:
        super().__init__()
        self._database_path = database_path
        self._repository: ArchiveRepository | None = None
        self._records: list[dict[str, object]] = []
        self._notice = ""
        try:
            self._repository = ArchiveRepository(database_path, migration_snapshot)
        except (ArchiveRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._notice = str(exc) or "时光档案暂时无法载入。"

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        if self._repository is None:
            return {"filter": "all", "recordCount": 0, "groups": [], "summary": {}, "notice": self._notice}
        try:
            result = self._repository.state(self._records)
            result["notice"] = self._notice
            return result
        except (ArchiveRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            return {"filter": "all", "recordCount": 0, "groups": [], "summary": {},
                    "notice": str(exc) or "时光档案暂时无法计算。"}

    def updateRecords(self, records: list[dict[str, object]]) -> None:
        self._records = deepcopy(records) if isinstance(records, list) else []
        QTimer.singleShot(0, self, self.stateChanged.emit)

    @Slot(str, result="QVariant")
    def setFilter(self, value: str) -> dict[str, object]:
        if self._repository is None:
            return {"ok": False, "error": self._notice or "时光档案暂不可用。"}
        try:
            self._repository.set_filter(value)
        except (ArchiveRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "档案筛选没有保存。"}
        QTimer.singleShot(0, self, self.stateChanged.emit)
        return {"ok": True}

    @Slot("QVariant")
    def adoptImportedData(self, snapshot: object) -> None:
        value = snapshot.toVariant() if isinstance(snapshot, QJSValue) else snapshot
        try:
            if self._repository is None:
                self._repository = ArchiveRepository(self._database_path, value)
            else:
                self._repository.adopt_imported_data(value)
            self._notice = ""
        except (ArchiveRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "已导入数据，但时光档案筛选无法更新。"
        QTimer.singleShot(0, self, self.stateChanged.emit)


class NewsBridge(QObject):
    """QML-facing state and commands for previewing and managing news issues."""

    stateChanged = Signal()

    def __init__(
        self,
        database_path: Path,
        migration_snapshot: dict[str, object] | None = None,
    ) -> None:
        super().__init__()
        self._database_path = database_path
        documents = (
            migration_snapshot.get("documents", {})
            if isinstance(migration_snapshot, dict)
            else {}
        )
        if not isinstance(documents, dict):
            documents = {}
        legacy_store = documents.get("wanxiang-daily-issues-v1")
        self._repository: IssueRepository | None = None
        self._initialization_error = ""
        self._preview_is_unsaved = False
        self._recommendation_repository: RecommendationRepository | None = None
        self._recommendation_error = ""
        self._state: dict[str, object] = {
            "active": None,
            "archive": [],
            "draft": None,
            "draftUnsaved": False,
            "linkInbox": [],
            "layout": {},
            "recommendationFeedback": {},
            "recommendationSuggestions": {},
        }
        try:
            self._recommendation_repository = RecommendationRepository(database_path)
            self._refresh_recommendation_state()
        except (RecommendationRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            # Recommendation storage is optional: the issue reader and editor
            # remain usable if this separate local schema cannot initialize.
            self._recommendation_error = str(exc)
        try:
            self._repository = IssueRepository(
                database_path,
                legacy_store=legacy_store,
            )
            self._state = self._repository.snapshot()
            self._state["draftUnsaved"] = False
            self._refresh_recommendation_state()
        except (IssueRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            # Keep the desktop shell available if old data is malformed; expose
            # the readable error through each command instead of printing data.
            self._initialization_error = str(exc)

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return deepcopy(self._state)

    def _result(
        self,
        ok: bool,
        error: str | None = None,
    ) -> dict[str, object]:
        result: dict[str, object] = {"ok": ok, "state": self.state}
        if error:
            result["error"] = error
        return result

    def _require_repository(self) -> IssueRepository:
        if self._repository is None:
            raise IssueRepositoryError(
                self._initialization_error or "新闻数据仓储尚未就绪。"
            )
        return self._repository

    def _localized_json_syntax_error(self, error: BaseException) -> str | None:
        """Format JSON syntax failures in English when the UI language is English.

        The parser remains the source of the detailed reason and position. Its
        canonical Chinese exception is preserved for Simplified Chinese and
        for validation failures other than malformed JSON syntax.
        """
        cause = error.__cause__
        if not isinstance(cause, json.JSONDecodeError):
            return None
        try:
            language = LocalizationRepository(self._database_path).language()
        except (OSError, TypeError, ValueError, RuntimeError, sqlite3.Error):
            return None
        if language != "en_US":
            return None
        return (
            f"Invalid JSON: {cause.msg} "
            f"(line {cause.lineno}, column {cause.colno})."
        )

    def _refresh_state(self, *, notify: bool = True) -> None:
        self._state = self._require_repository().snapshot()
        self._preview_is_unsaved = False
        self._state["draftUnsaved"] = False
        self._state["recommendationSuggestions"] = {}
        self._refresh_recommendation_state()
        if notify:
            self.stateChanged.emit()

    def reload_from_database(self) -> None:
        try:
            # Reopening from SQLite observes the committed empty store and draft
            # while preserving independent layout, inbox and preference keys.
            self._repository = IssueRepository(self._database_path)
            self._initialization_error = ""
            self._refresh_state()
        except (IssueRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            self._initialization_error = str(exc) or "新闻数据暂时无法载入。"
            self.stateChanged.emit()

    def _refresh_recommendation_state(self) -> None:
        feedback: dict[str, str] = {}
        if self._recommendation_repository is not None:
            try:
                feedback = {
                    f"{entry['date']}::{entry['articleId']}": entry["action"]
                    for entry in self._recommendation_repository.all_feedback()
                }
                self._recommendation_error = ""
            except RecommendationRepositoryError as exc:
                self._recommendation_error = str(exc)
        self._state["recommendationFeedback"] = feedback
        self._state["recommendationError"] = self._recommendation_error

    def _preview_issue(self, issue: dict[str, object]) -> dict[str, object]:
        self._state["draft"] = deepcopy(issue)
        self._preview_is_unsaved = True
        self._state["draftUnsaved"] = True
        self._state["recommendationSuggestions"] = {}
        self.stateChanged.emit()
        return self._result(True)

    @Slot(str, result="QVariant")
    def previewJson(self, source: str) -> dict[str, object]:
        try:
            if not isinstance(source, str):
                raise NewsImportError("新闻内容包必须是 JSON 文本。")
            if len(source.encode("utf-8")) > MAX_ISSUE_JSON_BYTES:
                raise NewsImportError("新闻内容包超过 500 KB，请压缩图片后再导入。")
            issue = parse_issue_json(source)
        except (NewsImportError, UnicodeEncodeError, TypeError, ValueError) as exc:
            return self._result(
                False,
                self._localized_json_syntax_error(exc) or str(exc),
            )
        return self._preview_issue(issue)

    @Slot(QUrl, result="QVariant")
    def previewFile(self, file_url: QUrl) -> dict[str, object]:
        if not isinstance(file_url, QUrl) or not file_url.isLocalFile():
            return self._result(False, "请选择本机 JSON 内容包。")
        file_path = Path(file_url.toLocalFile())
        try:
            if not file_path.is_file():
                return self._result(False, "所选内容包文件不存在。")
            if file_path.stat().st_size > MAX_ISSUE_JSON_BYTES:
                return self._result(False, "新闻内容包超过 500 KB，请压缩图片后再导入。")
            with file_path.open("rb") as stream:
                raw = stream.read(MAX_ISSUE_JSON_BYTES + 1)
            if len(raw) > MAX_ISSUE_JSON_BYTES:
                return self._result(False, "新闻内容包超过 500 KB，请压缩图片后再导入。")
            issue = parse_issue_json(raw)
        except (OSError, NewsImportError, TypeError, ValueError) as exc:
            localized_json_error = self._localized_json_syntax_error(exc)
            if localized_json_error is not None:
                return self._result(
                    False,
                    f"Could not preview the selected JSON file: {localized_json_error}",
                )
            return self._result(False, f"无法预览新闻内容包：{exc}")
        return self._preview_issue(issue)

    @Slot(str, result="QVariant")
    def addLink(self, url: str) -> dict[str, object]:
        try:
            repository = self._require_repository()
            added = repository.add_link(url)
            self._state["linkInbox"] = repository.snapshot()["linkInbox"]
            if added:
                self.stateChanged.emit()
            return self._result(True)
        except (IssueRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            return self._result(False, str(exc))

    @Slot(int, result="QVariant")
    def removeLink(self, index: int) -> dict[str, object]:
        try:
            repository = self._require_repository()
            repository.remove_link(index)
            self._state["linkInbox"] = repository.snapshot()["linkInbox"]
            self.stateChanged.emit()
            return self._result(True)
        except (IssueRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            return self._result(False, str(exc))

    @Slot(result="QVariant")
    def saveDraft(self) -> dict[str, object]:
        issue = self._state.get("draft")
        if issue is None:
            return self._result(False, "请先预览或载入一份有效的新闻刊期。")
        try:
            self._require_repository().save_draft(issue)
            self._refresh_state()
            return self._result(True)
        except (IssueRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            return self._result(False, str(exc))

    @Slot(result="QVariant")
    def restoreSavedDraft(self) -> dict[str, object]:
        try:
            self._refresh_state()
            if self._state.get("draft") is None:
                return self._result(False, "本机没有可恢复的已保存草稿。")
            return self._result(True)
        except (IssueRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            return self._result(False, str(exc))

    @Slot(result="QVariant")
    def publishDraft(self) -> dict[str, object]:
        issue = self._state.get("draft")
        if issue is None:
            return self._result(False, "请先预览或载入一份有效的新闻刊期。")
        try:
            repository = self._require_repository()
            if self._preview_is_unsaved:
                repository.publish_issue(issue)
            else:
                repository.publish_draft()
            self._refresh_state()
            return self._result(True)
        except (IssueRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            # A failed atomic publish leaves both the stored state and the
            # in-memory preview available for retry.
            return self._result(False, str(exc))

    @Slot(int, result="QVariant")
    def loadHistory(self, index: int) -> dict[str, object]:
        try:
            self._require_repository().load_history(index)
            self._refresh_state()
            return self._result(True)
        except (IssueRepositoryError, OSError, RuntimeError, sqlite3.Error) as exc:
            return self._result(False, str(exc))

    @Slot(str, int, int, result="QVariant")
    def moveDraftItem(
        self, group: str, index: int, delta: int
    ) -> dict[str, object]:
        if group not in {"focus", "highlights", "articles"}:
            return self._result(False, "只能调整 focus、highlights 或 articles 分组。")
        draft = self._state.get("draft")
        if not isinstance(draft, dict):
            return self._result(False, "当前没有可调整的草稿。")
        items = draft.get(group)
        if not isinstance(items, list) or not 0 <= index < len(items):
            return self._result(False, "所选草稿条目不存在。")
        next_index = index + delta
        if delta == 0 or not 0 <= next_index < len(items):
            return self._result(True)
        updated = deepcopy(draft)
        updated_items = updated[group]
        updated_items[index], updated_items[next_index] = (
            updated_items[next_index],
            updated_items[index],
        )
        self._state["draft"] = updated
        self._preview_is_unsaved = True
        self._state["draftUnsaved"] = True
        self._state["recommendationSuggestions"] = {}
        self.stateChanged.emit()
        return self._result(True)

    @Slot("QVariant", str, str, result="QVariant")
    def setArticleFeedback(
        self, article: object, issue_date: str, action: str
    ) -> dict[str, object]:
        if isinstance(article, QJSValue):
            article = article.toVariant()
        if self._recommendation_repository is None:
            return self._result(False, self._recommendation_error or "本机推荐反馈暂不可用。")
        try:
            self._recommendation_repository.set_feedback(issue_date, article, action)
            self._state["recommendationSuggestions"] = {}
            self._refresh_recommendation_state()
            self.stateChanged.emit()
            return self._result(True)
        except (RecommendationError, RecommendationRepositoryError) as exc:
            return self._result(False, str(exc))

    @Slot("QVariant", "QVariant", result="QVariant")
    def recommendDraft(
        self, preferences: object, clippings: object
    ) -> dict[str, object]:
        if isinstance(preferences, QJSValue):
            preferences = preferences.toVariant()
        if isinstance(clippings, QJSValue):
            clippings = clippings.toVariant()
        if self._recommendation_repository is None:
            return self._result(False, self._recommendation_error or "本机推荐功能暂不可用。")
        draft = self._state.get("draft")
        if not isinstance(draft, dict):
            return self._result(False, "请先预览或载入一份草稿，再生成推荐排序建议。")
        if not isinstance(clippings, list):
            clippings = []
        try:
            feedback = self._recommendation_repository.all_feedback()
            groups: dict[str, list[dict[str, object]]] = {}
            for group in ("focus", "highlights", "articles"):
                ranked = rank_group(
                    draft.get(group, []),
                    preferences=preferences,
                    feedback=feedback,
                    clippings=clippings,
                    issue_topic=str(draft.get("topic", "")),
                )
                groups[group] = [
                    {
                        "id": result["item"].get("id", ""),
                        "rank": result["rank"],
                        "score": result["score"],
                        "reason": result["reason"],
                    }
                    for result in ranked
                ]
            self._state["recommendationSuggestions"] = {"groups": groups, "applied": False}
            self._state["recommendationError"] = ""
            self.stateChanged.emit()
            return self._result(True)
        except (RecommendationError, RecommendationRepositoryError, TypeError, ValueError) as exc:
            return self._result(False, str(exc))

    @Slot(result="QVariant")
    def applyRecommendation(self) -> dict[str, object]:
        draft = self._state.get("draft")
        suggestions = self._state.get("recommendationSuggestions")
        if not isinstance(draft, dict) or not isinstance(suggestions, dict):
            return self._result(False, "请先生成推荐排序建议。")
        groups = suggestions.get("groups")
        if not isinstance(groups, dict):
            return self._result(False, "推荐排序建议已失效，请重新生成。")
        updated = deepcopy(draft)
        for group in ("focus", "highlights", "articles"):
            items = updated.get(group)
            proposed = groups.get(group)
            if not isinstance(items, list) or not isinstance(proposed, list):
                return self._result(False, "推荐排序建议与当前草稿不匹配，请重新生成。")
            by_id = {item.get("id"): item for item in items if isinstance(item, dict)}
            proposed_ids = [entry.get("id") for entry in proposed if isinstance(entry, dict)]
            if len(proposed_ids) != len(items) or set(proposed_ids) != set(by_id):
                return self._result(False, "推荐排序建议与当前草稿不匹配，请重新生成。")
            updated[group] = [by_id[item_id] for item_id in proposed_ids]
        self._state["draft"] = updated
        self._preview_is_unsaved = True
        self._state["draftUnsaved"] = True
        suggestions["applied"] = True
        self._state["recommendationSuggestions"] = suggestions
        self.stateChanged.emit()
        return self._result(True)

    @Slot(result="QVariant")
    def clearRecommendationFeedback(self) -> dict[str, object]:
        if self._recommendation_repository is None:
            return self._result(False, self._recommendation_error or "本机推荐反馈暂不可用。")
        try:
            self._recommendation_repository.clear()
            self._state["recommendationSuggestions"] = {}
            self._refresh_recommendation_state()
            self.stateChanged.emit()
            return self._result(True)
        except RecommendationRepositoryError as exc:
            return self._result(False, str(exc))

    @Slot(str, bool, result="QVariant")
    def setLayoutGroupVisible(self, group: str, visible: bool) -> dict[str, object]:
        layout = deepcopy(self._state.get("layout", {}))
        hidden = layout.get("hidden", [])
        hidden = list(hidden) if isinstance(hidden, list) else []
        if visible:
            hidden = [key for key in hidden if key != group]
        elif group not in hidden:
            hidden.append(group)
        layout["hidden"] = hidden
        return self.saveLayout(layout)

    @Slot(str, int, "QVariant", result="QVariant")
    def moveLayoutGroup(
        self, group: str, delta: int, known_group_keys: object
    ) -> dict[str, object]:
        return self.moveLayoutGroupTo(group, -1, known_group_keys, delta=delta)

    @Slot(str, int, "QVariant", result="QVariant")
    def moveLayoutGroupTo(
        self,
        group: str,
        target_index: int,
        known_group_keys: object,
        *,
        delta: int = 0,
    ) -> dict[str, object]:
        if isinstance(known_group_keys, QJSValue):
            known_group_keys = known_group_keys.toVariant()
        if not isinstance(known_group_keys, (list, tuple)) or any(
            not isinstance(key, str) for key in known_group_keys
        ):
            return self._result(False, "新闻分组顺序无效，请重新打开版面设置。")

        known_keys = list(dict.fromkeys(known_group_keys))
        if group not in known_keys:
            return self._result(False, "找不到要调整的新闻分组。")
        layout = deepcopy(self._state.get("layout", {}))
        saved_order = layout.get("order", [])
        saved_order = list(saved_order) if isinstance(saved_order, list) else []
        selected_order = [key for key in saved_order if key in known_keys]
        selected_order.extend(key for key in known_keys if key not in selected_order)
        old_index = selected_order.index(group)
        destination = old_index + delta if target_index < 0 else target_index
        if destination < 0 or destination >= len(selected_order):
            return self._result(True)
        if destination == old_index:
            return self._result(True)

        moving = selected_order.pop(old_index)
        selected_order.insert(destination, moving)
        updated_order: list[str] = []
        selected_index = 0
        for key in saved_order:
            if key in known_keys:
                if selected_index < len(selected_order):
                    updated_order.append(selected_order[selected_index])
                    selected_index += 1
            else:
                updated_order.append(key)
        updated_order.extend(selected_order[selected_index:])
        layout["order"] = updated_order
        return self.saveLayout(layout)

    @Slot("QVariant", result="QVariant")
    def saveLayout(self, layout: object) -> dict[str, object]:
        try:
            if isinstance(layout, QJSValue):
                layout = layout.toVariant()
            repository = self._require_repository()
            repository.save_layout(layout)
            self._state["layout"] = repository.snapshot()["layout"]
            self.stateChanged.emit()
            return self._result(True)
        except (IssueRepositoryError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            return self._result(False, str(exc))

    @Slot("QVariant", result="QVariant")
    @Slot("QVariant", "QVariant", result="QVariant")
    def copyIssuePrompt(
        self, preferences: object, clippings: object = None
    ) -> dict[str, object]:
        if isinstance(preferences, QJSValue):
            preferences = preferences.toVariant()
        if isinstance(clippings, QJSValue):
            clippings = clippings.toVariant()
        if not isinstance(preferences, dict):
            return self._result(False, "关注方向设置暂时无法读取。")
        nested = preferences.get("preferences")
        if isinstance(nested, dict):
            topics = preferences.get("topics", [])
            sources = nested.get("presetSources", [])
            custom_topics = nested.get("subtopics", "")
            custom_sources = nested.get("sources", "")
        else:
            # Keep the bridge tolerant of an older flattened preview shape.
            topics = preferences.get("topics", [])
            sources = preferences.get("sources", [])
            custom_topics = preferences.get("customTopics", "")
            custom_sources = preferences.get("customSources", "")
        try:
            feedback = (
                self._recommendation_repository.all_feedback()
                if self._recommendation_repository is not None
                else []
            )
            summary = personalized_summary(
                feedback,
                clippings if isinstance(clippings, list) else [],
            )
            prompt = build_issue_prompt(
                topics=topics,
                sources=sources,
                custom_topics=custom_topics,
                custom_sources=custom_sources,
                personalization_summary=summary,
            )
            clipboard = QApplication.clipboard()
            if clipboard is None:
                return self._result(False, "系统剪贴板暂不可用，请重试。")
            clipboard.setText(prompt)
        except (IssueToolError, RecommendationRepositoryError, RuntimeError, TypeError, ValueError) as exc:
            return self._result(False, str(exc) or "生成提示失败，请检查关注方向设置。")
        return self._result(True, "已复制新闻生成提示。")

    @Slot(QUrl, result="QVariant")
    def exportActiveIssue(self, file_url: QUrl) -> dict[str, object]:
        if not isinstance(file_url, QUrl) or not file_url.isLocalFile():
            return self._result(False, "请选择本机 JSON 文件位置。")
        issue = self._state.get("active")
        if not isinstance(issue, dict):
            return self._result(False, "还没有已发布的本期内容，请先发布后再导出。")
        path = Path(file_url.toLocalFile())
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            saved_path = save_issue_json(path, issue)
        except (IssueToolError, OSError, RuntimeError, TypeError, ValueError) as exc:
            return self._result(False, str(exc) or "导出失败，请检查所选本机位置。")
        return self._result(True, f"本期已导出到：{saved_path}")


class LocalDataCleanupBridge(QObject):
    """QML API for local-only data cleanup and cache refresh after commit."""

    stateChanged = Signal()

    def __init__(
        self,
        database_path: Path,
        *,
        finance_bridge: FinanceBridge,
        fitness_bridge: FitnessBridge,
        planner_bridge: PlannerBridge,
        shopping_bridge: ShoppingBridge,
        media_bridge: MediaBridge,
        habit_bridge: HabitBridge,
        news_bridge: NewsBridge,
        failure_injector: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self._repository = LocalDataCleanupRepository(database_path)
        self._finance_bridge = finance_bridge
        self._fitness_bridge = fitness_bridge
        self._planner_bridge = planner_bridge
        self._shopping_bridge = shopping_bridge
        self._media_bridge = media_bridge
        self._habit_bridge = habit_bridge
        self._news_bridge = news_bridge
        # Injectable only for isolated transaction-failure acceptance tests.
        self._failure_injector = failure_injector

    @Slot(result="QVariant")
    def previewSamples(self) -> dict[str, object]:
        try:
            return {"ok": True, **self._repository.preview_samples()}
        except (DataCleanupError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "无法预览示例数据。"}

    @Slot(result="QVariant")
    def previewAll(self) -> dict[str, object]:
        try:
            return {"ok": True, **self._repository.preview_all()}
        except (DataCleanupError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "无法预览本机数据。"}

    def _refresh_cached_modules(self) -> None:
        # Reload repositories before notifying QML; the existing application
        # activity signal chain then refreshes DailyBridge and ArchiveBridge.
        self._finance_bridge.reload_from_database()
        self._fitness_bridge.reload_from_database()
        self._planner_bridge.reload_from_database()
        self._shopping_bridge.reload_from_database()
        self._media_bridge.reload_from_database()
        self._habit_bridge.reload_from_database()
        self._news_bridge.reload_from_database()

    def _run(self, *, samples_only: bool) -> dict[str, object]:
        try:
            result = (
                self._repository.clear_samples(failure_injector=self._failure_injector)
                if samples_only
                else self._repository.clear_all(failure_injector=self._failure_injector)
            )
        except (DataCleanupError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc) or "本机清理失败，数据已回滚。"}
        self._refresh_cached_modules()
        self.stateChanged.emit()
        return {"ok": True, **result}

    @Slot(result="QVariant")
    def clearSamples(self) -> dict[str, object]:
        return self._run(samples_only=True)

    @Slot(result="QVariant")
    def clearAll(self) -> dict[str, object]:
        return self._run(samples_only=False)


class WeatherBridge(QObject):
    """异步天气网络层与一次性系统定位适配。"""

    weatherChanged = Signal()

    def __init__(
        self,
        database_path: Path,
        imported_data: dict[str, object],
        *,
        location_provider: object = None,
    ) -> None:
        super().__init__()
        self._database_path = database_path
        self._location_provider = location_provider or WindowsLocationProvider(self)
        self._location_provider.progress.connect(self._location_progress)
        self._location_provider.finished.connect(self._location_provider_finished)
        self._manager = QNetworkAccessManager(self)
        self._manager.setTransferTimeout(12_000)
        self._manager.finished.connect(self._reply_finished)
        self._query_id = 0
        self._requested_city = ""
        self._candidates: list[str] = []
        self._candidate_index = 0
        self._place: dict[str, object] | None = None
        settings = self._legacy_weather_settings(imported_data)
        self._saved_location = self._validated_location(
            get_app_setting(database_path, "dailyFlowLocation", settings.get("dailyFlowLocation"))
        )
        attempted = get_app_setting(
            database_path,
            "dailyFlowLocationAttempted",
            settings.get("dailyFlowLocationAttempted", False),
        )
        self._location_attempted = attempted is True
        self._location_request_id = 0
        self._location_timeout = QTimer(self)
        self._location_timeout.setSingleShot(True)
        self._location_timeout.timeout.connect(self._location_timed_out)
        self._location_busy = False
        self._weather: dict[str, object] = {
            "city": "当前位置" if self._saved_location else self._saved_city(database_path, imported_data),
            "busy": False,
            "status": "请输入城市名称并查询天气。",
            "condition": "",
            "conditionEnglish": "",
            "glyph": "",
            "temperature": None,
            "apparentTemperature": None,
            "highTemperature": None,
            "lowTemperature": None,
            "humidity": None,
            "windSpeed": None,
            "rainChance": None,
            "lastUpdated": "",
        }

    @staticmethod
    def _legacy_weather_settings(imported_data: dict[str, object]) -> dict[str, object]:
        documents = imported_data.get("documents", {})
        state = documents.get("richangji-state-v1", {}) if isinstance(documents, dict) else {}
        settings = state.get("settings", {}) if isinstance(state, dict) else {}
        return settings if isinstance(settings, dict) else {}

    @staticmethod
    def _validated_location(value: object) -> dict[str, float] | None:
        if not isinstance(value, dict):
            return None
        latitude, longitude = value.get("latitude"), value.get("longitude")
        if (isinstance(latitude, bool) or isinstance(longitude, bool)
                or not isinstance(latitude, (int, float))
                or not isinstance(longitude, (int, float))):
            return None
        latitude, longitude = float(latitude), float(longitude)
        if (not math.isfinite(latitude) or not math.isfinite(longitude)
                or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
            return None
        return {"latitude": round(latitude, 1), "longitude": round(longitude, 1)}

    @staticmethod
    def _saved_city(
        database_path: Path, imported_data: dict[str, object]
    ) -> str:
        saved = get_app_setting(
            database_path, "dailyFlowCity", ""
        )
        if isinstance(saved, str) and saved.strip():
            return saved.strip()[:32]
        documents = imported_data.get("documents", {})
        state = documents.get("richangji-state-v1", {}) if isinstance(documents, dict) else {}
        settings = state.get("settings", {}) if isinstance(state, dict) else {}
        city = settings.get("dailyFlowCity", "") if isinstance(settings, dict) else ""
        return city.strip()[:32] if isinstance(city, str) else ""

    @Property("QVariant", notify=weatherChanged)
    def weather(self) -> dict[str, object]:
        return dict(self._weather)

    @Property(str, notify=weatherChanged)
    def city(self) -> str:
        return str(self._weather.get("city") or "")

    @Property(bool, notify=weatherChanged)
    def busy(self) -> bool:
        return bool(self._weather.get("busy"))

    @Property(bool, notify=weatherChanged)
    def locationBusy(self) -> bool:
        return self._location_busy

    @Property(str, notify=weatherChanged)
    def status(self) -> str:
        return str(self._weather.get("status") or "")

    @Property(str, notify=weatherChanged)
    def condition(self) -> str:
        return str(self._weather.get("condition") or "")

    @Property(str, notify=weatherChanged)
    def conditionEnglish(self) -> str:
        return str(self._weather.get("conditionEnglish") or "")

    @Property(str, notify=weatherChanged)
    def glyph(self) -> str:
        return str(self._weather.get("glyph") or "")

    @Property("QVariant", notify=weatherChanged)
    def temperature(self) -> object:
        return self._weather.get("temperature")

    @Property("QVariant", notify=weatherChanged)
    def apparentTemperature(self) -> object:
        return self._weather.get("apparentTemperature")

    @Property("QVariant", notify=weatherChanged)
    def highTemperature(self) -> object:
        return self._weather.get("highTemperature")

    @Property("QVariant", notify=weatherChanged)
    def lowTemperature(self) -> object:
        return self._weather.get("lowTemperature")

    @Property("QVariant", notify=weatherChanged)
    def humidity(self) -> object:
        return self._weather.get("humidity")

    @Property("QVariant", notify=weatherChanged)
    def windSpeed(self) -> object:
        return self._weather.get("windSpeed")

    @Property("QVariant", notify=weatherChanged)
    def rainChance(self) -> object:
        return self._weather.get("rainChance")

    def _publish(self, **changes: object) -> None:
        self._weather.update(changes)
        self.weatherChanged.emit()

    def _start_request(self, url: str, step: str, query_id: int) -> None:
        request = QNetworkRequest(QUrl(url))
        reply = self._manager.get(request)
        reply.setProperty("wanxiangQueryId", query_id)
        reply.setProperty("wanxiangWeatherStep", step)

    def _request_geocoding(self, query_id: int) -> None:
        try:
            url = build_geocoding_url(self._candidates[self._candidate_index])
        except (IndexError, WeatherServiceError) as exc:
            self._fail(str(exc), query_id)
            return
        self._start_request(url, "geocoding", query_id)

    def _request_forecast(self, query_id: int) -> None:
        if self._place is None:
            self._fail("城市查询结果缺失，请重新查询。", query_id)
            return
        try:
            url = build_forecast_url(
                self._place["latitude"], self._place["longitude"]
            )
        except (KeyError, TypeError, WeatherServiceError) as exc:
            self._fail(str(exc), query_id)
            return
        self._start_request(url, "forecast", query_id)

    @Slot(str)
    def queryCity(self, city: str) -> None:
        requested = (city or "").strip()
        if not requested:
            self._publish(busy=False, status="请输入城市名称。")
            return
        if len(requested) > 32:
            self._publish(busy=False, status="城市名称最多 32 个字符。")
            return
        candidates = city_search_candidates(requested)
        if not candidates:
            self._publish(busy=False, status="请输入有效的城市名称。")
            return
        try:
            # A city is a user setting. Keep it even if either network request
            # fails, so the next launch can retry without losing the input.
            set_app_settings(self._database_path, {
                "dailyFlowCity": requested,
                "dailyFlowLocation": None,
                "dailyFlowLocationAttempted": True,
            })
        except (OSError, sqlite3.Error, TypeError, ValueError, RuntimeError):
            self._publish(
                city=requested,
                busy=False,
                status="无法保存城市设置，请检查本机存储后重试。",
            )
            return
        self._saved_location = None
        self._location_attempted = True
        self._cancel_location_request()
        self._location_request_id += 1
        self._location_busy = False
        self._query_id += 1
        query_id = self._query_id
        self._requested_city = requested
        self._candidates = candidates
        self._candidate_index = 0
        self._place = None
        self._publish(city=requested, busy=True, status="正在查询城市天气……")
        self._request_geocoding(query_id)

    @Slot()
    def querySavedCity(self) -> None:
        if self._saved_location is not None:
            self._request_forecast_for_location(self._saved_location)
            return
        city = self._weather.get("city")
        if isinstance(city, str) and city.strip():
            self.queryCity(city)
        elif not self._location_attempted:
            self.requestLocation()
        else:
            self._publish(
                busy=False,
                status="定位未完成，可重新定位或手动输入城市。",
            )

    @Slot()
    def requestLocation(self) -> None:
        self._cancel_location_request()
        self._location_request_id += 1
        request_id = self._location_request_id
        self._query_id += 1
        self._location_busy = True
        self._publish(
            city="当前位置" if self._saved_location else str(self._weather.get("city") or ""),
            busy=True,
            status="正在请求 Windows 系统位置……",
        )
        try:
            self._location_timeout.start(30_000)
            self._location_provider.request(request_id)
        except Exception as exc:
            self._location_failed(request_id, f"无法请求系统位置：{exc}")

    def _location_progress(self, request_id: int, message: str) -> None:
        if request_id != self._location_request_id:
            return
        self._location_timeout.start(13_000)
        self._publish(busy=True, status=message)

    def _location_provider_finished(self, request_id: int, result: object) -> None:
        if request_id != self._location_request_id:
            return
        if not isinstance(result, dict):
            self._location_failed(request_id, "Windows 定位服务没有返回有效结果，可手动输入城市。")
            return
        error = result.get("error")
        if isinstance(error, str) and error.strip():
            self._location_failed(request_id, error.strip())
            return
        self._location_received(request_id, result)

    def _location_timed_out(self) -> None:
        self._location_failed(self._location_request_id, "获取系统位置超时，可重试或手动输入城市。")

    def _location_received(self, request_id: int, result: dict[str, object]) -> None:
        if request_id != self._location_request_id:
            return
        try:
            location = self._validated_location({
                "latitude": result.get("latitude"),
                "longitude": result.get("longitude"),
            })
            if location is None:
                raise ValueError("系统返回的坐标超出有效范围。")
            set_app_settings(self._database_path, {
                "dailyFlowCity": "",
                "dailyFlowLocation": location,
                "dailyFlowLocationAttempted": True,
            })
        except (OSError, sqlite3.Error, RuntimeError, TypeError, ValueError) as exc:
            self._location_failed(request_id, f"位置有效，但本机无法保存位置设置：{exc}")
            return
        self._saved_location = location
        self._location_attempted = True
        self._location_busy = False
        self._cancel_location_request()
        self._location_request_id += 1
        self.weatherChanged.emit()
        self._request_forecast_for_location(location)

    def _request_forecast_for_location(self, location: dict[str, float]) -> None:
        self._query_id += 1
        query_id = self._query_id
        self._requested_city = "当前位置"
        self._candidates = []
        self._candidate_index = 0
        self._place = {"name": "当前位置", **location}
        self._publish(city="当前位置", busy=True, status="正在查询当前位置天气……")
        self._request_forecast(query_id)

    def _location_failed(self, request_id: int, message: str) -> None:
        if request_id != self._location_request_id:
            return
        self._location_busy = False
        self._cancel_location_request()
        self._location_request_id += 1
        try:
            set_app_setting(self._database_path, "dailyFlowLocationAttempted", True)
            self._location_attempted = True
        except (OSError, sqlite3.Error, RuntimeError, TypeError, ValueError):
            pass
        if self._saved_location is not None:
            self._request_forecast_for_location(self._saved_location)
            return
        city = self._weather.get("city")
        if isinstance(city, str) and city.strip():
            self.queryCity(city)
            return
        self._publish(city="", busy=False, status=message)

    def _cancel_location_request(self) -> None:
        self._location_timeout.stop()
        try:
            self._location_provider.cancel(self._location_request_id)
        except (AttributeError, RuntimeError, TypeError):
            pass

    @Slot(result=bool)
    def openLocationSettings(self) -> bool:
        return QDesktopServices.openUrl(QUrl("ms-settings:privacy-location"))

    def _fail(self, message: str, query_id: int) -> None:
        if query_id != self._query_id:
            return
        self._publish(busy=False, status=message)

    def _reply_finished(self, reply: QNetworkReply) -> None:
        query_id = reply.property("wanxiangQueryId")
        step = reply.property("wanxiangWeatherStep")
        if query_id != self._query_id:
            reply.deleteLater()
            return
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                message = (
                    "城市查询服务暂不可用，请检查网络后重试。"
                    if step == "geocoding"
                    else "天气服务暂不可用，请检查网络后重试。"
                )
                self._fail(message, query_id)
                return
            body = bytes(reply.readAll())
            if step == "geocoding":
                try:
                    payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise WeatherServiceError("城市查询服务返回的内容无法读取，请稍后重试。")
                results = payload.get("results") if isinstance(payload, dict) else None
                if results == [] and self._candidate_index + 1 < len(self._candidates):
                    self._candidate_index += 1
                    self._request_geocoding(query_id)
                    return
                self._place = parse_geocoding_response(
                    payload, requested_city=self._requested_city
                )
                self._request_forecast(query_id)
                return

            result = simplify_forecast_response(body)
            current = result["current"]
            daily = result["daily"]
            city_name = str(self._place.get("name", self._requested_city)) if self._place else self._requested_city
            self._publish(
                city=city_name,
                busy=False,
                status="天气已更新。",
                condition=result["description"],
                conditionEnglish=result["description_en"],
                glyph=result["glyph"],
                temperature=current["temperature_2m"],
                apparentTemperature=current["apparent_temperature"],
                highTemperature=daily["temperature_2m_max"],
                lowTemperature=daily["temperature_2m_min"],
                humidity=current["relative_humidity_2m"],
                windSpeed=current["wind_speed_10m"],
                rainChance=daily["precipitation_probability_max"],
                lastUpdated="刚刚更新",
            )
        except (WeatherServiceError, KeyError, TypeError, ValueError) as exc:
            self._fail(str(exc), query_id)
        finally:
            reply.deleteLater()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FLUKE PySide6 / Qt Quick 桌面应用")
    parser.add_argument(
        "--size",
        default="1480x960",
        help="窗口逻辑尺寸，格式为 WIDTHxHEIGHT。",
    )
    parser.add_argument(
        "--capture",
        type=Path,
        help="开发预览用：显示窗口后保存一张 QQuickWindow 截图并退出。",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="可选 SQLite 路径；用于开发时隔离数据，不指定时使用本机默认目录。",
    )
    return parser.parse_known_args()[0]


def main() -> int:
    args = parse_args()
    try:
        width_text, height_text = args.size.lower().split("x", maxsplit=1)
        width, height = int(width_text), int(height_text)
    except (AttributeError, ValueError):
        print("窗口尺寸格式应为 WIDTHxHEIGHT，例如 1480x960。", file=sys.stderr)
        return 2

    QQuickStyle.setStyle("Basic")

    app = QApplication(sys.argv[:1])
    app.setApplicationName("FLUKE")
    app.setApplicationDisplayName("FLUKE")
    app.setOrganizationName("FLUKE")
    database_path = args.database or default_database_path()
    try:
        instance_lock = PlannerDatabaseInstanceLock(database_path)
        if not instance_lock.acquire():
            QMessageBox.information(
                None,
                "工作台已在运行",
                "这个本机数据库已经由另一个工作台窗口打开。请切回已打开的窗口，避免同时修改同一份数据。",
            )
            return 0
    except OSError as exc:
        QMessageBox.critical(
            None,
            "无法安全打开工作台",
            f"无法建立本机数据写入保护，因此没有打开窗口。\n\n{exc}",
        )
        return 1
    app.aboutToQuit.connect(instance_lock.release)
    atexit.register(instance_lock.release)
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    )
    os.environ.setdefault(
        "QML_DISK_CACHE_PATH", str(local_app_data / "FLUKE" / "QMLCache")
    )
    font_path = ASSET_DIR / "fonts" / "NotoSansSC-VF.ttf"
    font_id = QFontDatabase.addApplicationFont(str(font_path))
    font_families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    app.setFont(QFont(font_families[0] if font_families else "Noto Sans SC", 10))

    engine = QQmlApplicationEngine()
    initialize_database(database_path)
    localization_bridge = LocalizationBridge(
        LocalizationRepository(database_path), engine, app
    )
    migration_bridge = MigrationBridge(database_path)
    home_layout_bridge = HomeLayoutBridge(database_path)
    weather_bridge = WeatherBridge(database_path, migration_bridge.data)
    news_bridge = NewsBridge(database_path, migration_bridge.data)
    habit_bridge = HabitBridge(database_path, migration_bridge.data)
    preferences_bridge = IssuePreferencesBridge(database_path, migration_bridge.data)
    reading_bridge = ReadingBridge(database_path, migration_bridge.data)
    daily_bridge = DailyBridge(database_path, migration_bridge.data)
    finance_bridge = FinanceBridge(database_path, migration_bridge.data)
    backup_bridge = BackupBridge(database_path, finance_bridge)
    fitness_bridge = FitnessBridge(database_path, migration_bridge.data)
    tray_icon = app.windowIcon()
    if tray_icon.isNull():
        tray_icon = app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
    system_notifier = create_qt_system_tray_notifier(icon=tray_icon)
    planner_bridge = PlannerBridge(database_path, migration_bridge.data, system_notifier)
    webdav_planner_bridge = (
        WebDavPlannerSyncBridge(
            database_path,
            planner_bridge._repository,
            planner_bridge._calendar_network,
            engine,
        )
        if planner_bridge._repository is not None else None
    )
    if webdav_planner_bridge is not None:
        def update_webdav_planner_repository() -> None:
            repository = planner_bridge._repository
            if repository is not None:
                webdav_planner_bridge.set_repository(repository)

        planner_bridge.stateChanged.connect(update_webdav_planner_repository)
        planner_bridge.stateChanged.connect(webdav_planner_bridge.observe_local_changes)
        webdav_planner_bridge.changed.connect(planner_bridge._refresh)
        app.aboutToQuit.connect(webdav_planner_bridge.close)
    tray_lifecycle = TrayLifecycleController(
        app,
        system_notifier.tray,
        planner_bridge.has_pending_reminders,
    )
    app.aboutToQuit.connect(planner_bridge.close)
    app.aboutToQuit.connect(daily_bridge.close)
    shopping_bridge = ShoppingBridge(database_path, migration_bridge.data)
    media_bridge = MediaBridge(database_path, migration_bridge.data)
    archive_bridge = ArchiveBridge(database_path, migration_bridge.data)
    converter_bridge = ConverterBridge(QSettings())
    converter_engine_bridge = ConverterEngineUpdateBridge(
        local_app_data / "FLUKE" / "EngineUpdates"
    )
    converter_engine_bridge.engineUpdated.connect(
        lambda _engine_id: converter_bridge.refreshEngineAvailability()
    )
    brand_bridge = BrandBridge(BrandRepository(database_path), engine)
    migration_bridge.dataChanged.connect(
        lambda: habit_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(
        lambda: preferences_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(
        lambda: daily_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(
        lambda: reading_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(
        lambda: finance_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(
        lambda: fitness_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(
        lambda: planner_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(
        lambda: shopping_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(
        lambda: media_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(
        lambda: archive_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(
        lambda: brand_bridge.adoptImportedData(migration_bridge.data)
    )
    migration_bridge.dataChanged.connect(home_layout_bridge.refreshFromDatabase)

    def refresh_daily_activity() -> None:
        # Finance is the read-only baseline for legacy envelope rows. Each
        # specialist then replaces only the record type it owns, so one
        # module's stale copy cannot overwrite another module's local overlay.
        effective_records = merge_effective_records(
            finance_bridge.activity_records(),
            (
                (fitness_bridge.activity_records(), "fitness"),
                (planner_bridge.activity_records(), "planner"),
                (shopping_bridge.activity_records(), "home"),
            ),
            (
                finance_bridge.activity_tombstones(),
                fitness_bridge.activity_tombstones(),
                planner_bridge.activity_tombstones(),
                shopping_bridge.activity_tombstones(),
            ),
        )
        habit_state = habit_bridge.state
        daily_bridge.updateActivity(
            records=effective_records,
            habits=habit_state.get("habits", []) if isinstance(habit_state, dict) else [],
            media_items=media_bridge.activity_items(),
        )
        archive_bridge.updateRecords(effective_records)

    cleanup_bridge = LocalDataCleanupBridge(
        database_path,
        finance_bridge=finance_bridge,
        fitness_bridge=fitness_bridge,
        planner_bridge=planner_bridge,
        shopping_bridge=shopping_bridge,
        media_bridge=media_bridge,
        habit_bridge=habit_bridge,
        news_bridge=news_bridge,
    )

    habit_bridge.stateChanged.connect(refresh_daily_activity)
    finance_bridge.stateChanged.connect(refresh_daily_activity)
    fitness_bridge.stateChanged.connect(refresh_daily_activity)
    planner_bridge.stateChanged.connect(refresh_daily_activity)
    shopping_bridge.stateChanged.connect(refresh_daily_activity)
    media_bridge.stateChanged.connect(refresh_daily_activity)
    migration_bridge.dataChanged.connect(refresh_daily_activity)
    engine.setInitialProperties({
        "sansFontUrl": QUrl.fromLocalFile(str(ASSET_DIR / "fonts" / "NotoSansSC-VF.ttf")),
        "serifFontUrl": QUrl.fromLocalFile(str(ASSET_DIR / "fonts" / "NotoSerifSC-VF.ttf")),
        "migrationController": migration_bridge,
        "homeLayoutController": home_layout_bridge,
        "weatherController": weather_bridge,
        "newsController": news_bridge,
        "habitController": habit_bridge,
        "preferencesController": preferences_bridge,
        "readingController": reading_bridge,
        "dailyController": daily_bridge,
        "financeController": finance_bridge,
        "backupController": backup_bridge,
        "fitnessController": fitness_bridge,
        "plannerController": planner_bridge,
        "webdavPlannerController": webdav_planner_bridge,
        "trayController": tray_lifecycle,
        "shoppingController": shopping_bridge,
        "mediaController": media_bridge,
        "archiveController": archive_bridge,
        "converterController": converter_bridge,
        "converterEngineController": converter_engine_bridge,
        "brandController": brand_bridge,
        "cleanupController": cleanup_bridge,
        "localeController": localization_bridge,
    })
    qml_warnings: list[str] = []

    def capture_qml_warnings(warnings: list[object]) -> None:
        qml_warnings.extend(warning.toString() for warning in warnings)

    engine.warnings.connect(capture_qml_warnings)
    engine.load(QUrl.fromLocalFile(str(QML_FILE)))
    if not engine.rootObjects():
        print(f"无法加载界面：{QML_FILE}", file=sys.stderr)
        for warning in qml_warnings:
            print(warning, file=sys.stderr)
        return 1

    window = engine.rootObjects()[0]
    tray_lifecycle.set_window(window)
    refresh_daily_activity()
    window.resize(width, height)
    window.show()
    QTimer.singleShot(0, weather_bridge.querySavedCity)

    if args.capture is not None:
        output_path = args.capture.resolve()

        def capture_and_exit() -> None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image = window.grabWindow()
            if image.isNull() or not image.save(str(output_path)):
                print(f"截图失败：{output_path}", file=sys.stderr)
                app.exit(3)
                return
            print(f"已保存界面截图：{output_path} ({image.width()}x{image.height()})")
            print(
                "字体加载："
                f"sans={window.property('bundledSansFontReady')} ({window.property('sansFamily')}), "
                f"serif={window.property('bundledSerifFontReady')} ({window.property('serifFamily')})"
            )
            font_report = output_path.with_name(f"{output_path.stem}.font-status.txt")
            font_report.write_text(
                "\n".join((
                    f"bundledSansFontReady={bool(window.property('bundledSansFontReady'))}",
                    f"sansFamily={window.property('sansFamily')}",
                    f"bundledSerifFontReady={bool(window.property('bundledSerifFontReady'))}",
                    f"serifFamily={window.property('serifFamily')}",
                )) + "\n",
                encoding="utf-8",
            )
            app.exit(0)

        QTimer.singleShot(1200, capture_and_exit)

    backup_bridge.restoreRequested.connect(app.quit)
    migration_bridge.restartRequested.connect(app.quit)
    result = app.exec()
    # QML bindings can still reference the context objects until the engine
    # destroys its root objects. Destroy the engine while the Python bridge
    # locals are still alive so bindings are not evaluated against wrappers
    # that Python is releasing during function teardown.
    del window
    localization_bridge.close()
    del engine
    if backup_bridge.restart_requested or migration_bridge.restart_requested:
        if getattr(sys, "frozen", False):
            program = sys.executable
            arguments = sys.argv[1:]
            working_directory = str(Path(sys.executable).resolve().parent)
        else:
            program = sys.executable
            arguments = [str(PROJECT_DIR / "main.py"), *sys.argv[1:]]
            working_directory = str(PROJECT_DIR)
        started, _process_id = QProcess.startDetached(
            program, arguments, working_directory
        )
        if not started:
            print("自动重启未启动，请重新打开 FLUKE。", file=sys.stderr)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
