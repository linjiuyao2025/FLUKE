from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMetaObject, QObject, Qt, QUrl
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from main import (
    ArchiveBridge,
    BackupBridge,
    DailyBridge,
    FinanceBridge,
    FitnessBridge,
    HabitBridge,
    IssuePreferencesBridge,
    LocalDataCleanupBridge,
    MediaBridge,
    MigrationBridge,
    NewsBridge,
    PlannerBridge,
    ReadingBridge,
    ShoppingBridge,
    WeatherBridge,
    merge_effective_records,
)
from wanxiang.brand import BrandBridge, BrandRepository
from wanxiang.converter import ConverterBridge
from wanxiang.converter_engines import ConverterEngineUpdateBridge
from wanxiang.database import get_app_setting, import_package, load_imported_data, set_app_settings
from wanxiang.issues import LAYOUT_SETTING
from wanxiang.data_cleanup import DataCleanupError, LocalDataCleanupRepository
from wanxiang.fitness import DEFAULT_WEEKLY_PLAN
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _article(article_id: str, title: str) -> dict[str, object]:
    return {
        "id": article_id,
        "label": "合成栏目",
        "title": title,
        "summary": "只用于本机清理专项验收的合成摘要。",
        "body": ["合成正文。"],
        "publisher": "合成来源",
        "publishedAt": "2026-09-27",
        "sourceUrl": f"https://example.com/{article_id}",
    }


def _issue(prefix: str) -> dict[str, object]:
    return {
        "version": 1,
        "date": "2026-09-27",
        "topic": f"合成刊期 {prefix}",
        "focus": [_article(f"{prefix}-focus", f"合成焦点 {prefix}")],
        "highlights": [_article(f"{prefix}-highlight", f"合成摘要 {prefix}")],
        "articles": [],
    }


def _record(record_id: str, record_type: str, sample: bool) -> dict[str, object]:
    return {
        "id": record_id,
        "type": record_type,
        "date": "2026-09-27",
        "createdAt": 10,
        "sample": sample,
        "data": {
            "flow": "expense",
            "amount": 18,
            "category": "其他",
            "note": f"合成 {'样本' if sample else '自建'} {record_type}",
            "title": f"合成 {'样本' if sample else '自建'} {record_type}",
            "list": "生活",
            "bought": False,
            "weight": 60,
            "durationMinutes": 20,
        },
    }


def _synthetic_package(*, include_samples: bool = True) -> object:
    state = {
        "version": 2,
        "records": [
            _record(f"sample-{kind}", kind, True)
            for kind in ("money", "fitness", "planner", "home")
        ] + [
            _record(f"custom-{kind}", kind, False)
            for kind in ("money", "fitness", "planner", "home")
        ],
        "habits": [
            {
                "id": "habit-water",
                "key": "water",
                "name": "喝水",
                "type": "counter",
                "target": 8,
                "unit": "杯",
                "tone": "sage",
                "entries": {"2026-09-27": 5},
                "remoteEntries": {"legacy-row": "remote-water"},
                "createdDate": "2026-09-01",
                "sample": True,
            },
            {
                "id": "custom-habit-1",
                "key": "custom-walk",
                "name": "合成散步",
                "type": "check",
                "target": 1,
                "unit": "次",
                "tone": "sand",
                "entries": {"2026-09-27": 1},
                "remoteEntries": {"custom-row": "remote-custom"},
                "createdDate": "2026-09-01",
                "sample": False,
            },
        ],
        "mediaItems": [
            {
                "id": "sample-media-1", "name": "合成样本电影", "type": "电影",
                "status": "想看", "rating": 0, "review": "", "date": "2026-09-27",
                "cover": "", "sample": True,
            },
            {
                "id": "custom-media-1", "name": "合成自建书籍", "type": "书",
                "status": "在看", "rating": 4, "review": "自建保留项", "date": "2026-09-27",
                "cover": "", "sample": False,
            },
        ],
        "settings": {
            "weeklyPlan": [{"id": "synthetic-plan", "title": "合成保留周计划"}],
            "brand": {"name": "合成品牌", "avatar": "合", "tagline": "合成短句", "theme": "forest"},
        },
        "drafts": {},
    }
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    if not include_samples:
        for record in state["records"]:
            record["sample"] = False
        for habit in state["habits"]:
            habit["sample"] = False
        for media_item in state["mediaItems"]:
            media_item["sample"] = False
    raw_values["richangji-state-v1"] = json.dumps(state, ensure_ascii=False)
    raw_values["wanxiang-daily-issues-v1"] = json.dumps(
        {"active": _issue("active"), "archive": [{"issue": _issue("archived"), "publishedAt": "2026-09-26"}]},
        ensure_ascii=False,
    )
    raw_values["wanxiang-paper-layout-v2"] = json.dumps(
        {"order": ["synthetic-keep"], "hidden": []}, ensure_ascii=False
    )
    raw_values["wanxiang-issue-questions-v1"] = json.dumps(["保留的问题簿"], ensure_ascii=False)
    raw_values["wanxiang-issue-topics-v1"] = json.dumps(["ai"], ensure_ascii=False)
    raw_values["wanxiang-issue-preferences-v1"] = json.dumps(
        {"sources": "合成来源", "subtopics": "合成细分"}, ensure_ascii=False
    )
    raw_values["wanxiang-issue-clippings-v1"] = json.dumps([{
        "key": "2026-09-27::keep-clip",
        "date": "2026-09-27",
        "topic": "合成主题",
        "item": _article("keep-clip", "保留剪报"),
        "savedAt": 10,
    }], ensure_ascii=False)
    raw_values["wanxiang-saved-knowledge"] = "1"
    return validate_package({
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-cleanup-acceptance",
        "exportedAt": "2026-09-27T10:00:00Z",
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    })


def _database_rows(path: Path) -> dict[str, list[tuple[object, ...]]]:
    connection = sqlite3.connect(str(path))
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            table: list(connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid'))
            for table in tables
        }
    finally:
        connection.close()


def _shopping_overrides(path: Path) -> list[dict[str, object]]:
    connection = sqlite3.connect(str(path))
    try:
        row = connection.execute(
            "SELECT state_json FROM shopping_module_state WHERE singleton=1"
        ).fetchone()
        return json.loads(row[0])["recordOverrides"] if row else []
    finally:
        connection.close()


def _planner_overrides(path: Path) -> dict[str, object]:
    connection = sqlite3.connect(str(path))
    try:
        row = connection.execute(
            "SELECT state_json FROM planner_module_state WHERE singleton=1"
        ).fetchone()
        return json.loads(row[0])["recordOverrides"] if row else {}
    finally:
        connection.close()


class LocalDataCleanupQmlIntegrationTests(unittest.TestCase):
    """Run sample and all-local cleanup via production Main.qml and temp SQLite."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.native_dir = Path(__file__).resolve().parents[1]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-cleanup-qml-")
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)
        self.database_path = self.temp_path / "synthetic.sqlite3"
        import_package(_synthetic_package(), self.database_path)

        self.engine = QQmlApplicationEngine()
        self.addCleanup(self._destroy_engine)
        migration = MigrationBridge(self.database_path)
        snapshot = migration.data
        self.migration = migration
        self.weather = WeatherBridge(self.database_path, snapshot)
        self.news = NewsBridge(self.database_path, snapshot)
        self.habits = HabitBridge(self.database_path, snapshot)
        self.preferences = IssuePreferencesBridge(self.database_path, snapshot)
        self.reading = ReadingBridge(self.database_path, snapshot)
        self.daily = DailyBridge(self.database_path, snapshot)
        self.finance = FinanceBridge(self.database_path, snapshot)
        self.backup = BackupBridge(self.database_path, self.finance)
        self.fitness = FitnessBridge(self.database_path, snapshot)
        self.planner = PlannerBridge(self.database_path, snapshot)
        self.shopping = ShoppingBridge(self.database_path, snapshot)
        self.media = MediaBridge(self.database_path, snapshot)
        self.archive = ArchiveBridge(self.database_path, snapshot)
        self.converter = ConverterBridge()
        self.brand = BrandBridge(BrandRepository(self.database_path), self.engine)

        preserve = {
            LAYOUT_SETTING: {"order": ["focus", "highlights"], "hidden": ["highlights"]},
            "newsLinkInbox": [{"url": "https://example.com/keep", "addedAt": "2026-09-27T10:00:00Z"}],
            "dailyIssueStore": {"active": _issue("active"), "archive": [{"issue": _issue("archived"), "publishedAt": "2026-09-26"}]},
            "dailyIssueDraft": _issue("draft"),
        }
        set_app_settings(self.database_path, preserve)
        self.news.reload_from_database()

        self.cleanup = LocalDataCleanupBridge(
            self.database_path,
            finance_bridge=self.finance,
            fitness_bridge=self.fitness,
            planner_bridge=self.planner,
            shopping_bridge=self.shopping,
            media_bridge=self.media,
            habit_bridge=self.habits,
            news_bridge=self.news,
        )
        controllers = {
            "migrationController": migration,
            "weatherController": self.weather,
            "newsController": self.news,
            "habitController": self.habits,
            "preferencesController": self.preferences,
            "readingController": self.reading,
            "dailyController": self.daily,
            "financeController": self.finance,
            "backupController": self.backup,
            "fitnessController": self.fitness,
            "plannerController": self.planner,
            "shoppingController": self.shopping,
            "mediaController": self.media,
            "archiveController": self.archive,
            "converterController": self.converter,
            "converterEngineController": ConverterEngineUpdateBridge(self.temp_path / "engine-updates"),
            "brandController": self.brand,
            "cleanupController": self.cleanup,
        }
        self.controllers = controllers
        self.engine.setInitialProperties(controllers)
        self.engine.load(QUrl.fromLocalFile(str(self.native_dir / "qml" / "Main.qml")))
        self.assertTrue(self.engine.rootObjects(), "production Main.qml failed to load")
        self.window = self.engine.rootObjects()[0]
        self.window.resize(1480, 960)
        self.window.show()
        QTest.qWait(120)

        self.samples_button = self.window.findChild(QObject, "clearSamplesButton")
        self.all_button = self.window.findChild(QObject, "clearAllDataButton")
        self.data_tools_dialog = self.window.findChild(QObject, "dataToolsDialog")
        self.confirm_dialog = self.window.findChild(QObject, "cleanupConfirmDialog")
        self.confirm_text = self.window.findChild(QObject, "cleanupConfirmText")
        self.cancel_button = self.window.findChild(QObject, "cleanupCancelButton")
        self.confirm_button = self.window.findChild(QObject, "cleanupConfirmButton")
        self.status_dialog = self.window.findChild(QObject, "cleanupStatusDialog")
        self.status_text = self.window.findChild(QObject, "cleanupStatusText")
        for label, value in (
            ("sample cleanup button", self.samples_button),
            ("all cleanup button", self.all_button),
            ("data tools dialog", self.data_tools_dialog),
            ("cleanup confirmation", self.confirm_dialog),
            ("cleanup confirmation text", self.confirm_text),
            ("cleanup cancel button", self.cancel_button),
            ("cleanup confirm button", self.confirm_button),
            ("cleanup status dialog", self.status_dialog),
        ):
            self.assertIsNotNone(value, f"production {label} was not found")

    def _destroy_engine(self) -> None:
        if getattr(self, "engine", None) is not None:
            self.engine.deleteLater()
            try:
                QTest.qWait(30)
            except RuntimeError:
                pass

    def _click(self, button: QObject) -> None:
        self.assertTrue(QMetaObject.invokeMethod(button, "click", Qt.ConnectionType.DirectConnection))
        QTest.qWait(70)

    def _show_all_dialog(self) -> None:
        backup_button = self.window.findChild(QObject, "backupDataButton")
        self.assertIsNotNone(backup_button)
        self._click(backup_button)
        self._click(self.all_button)
        self.assertTrue(self.confirm_dialog.property("visible"))

    def _show_sample_dialog(self) -> None:
        backup_button = self.window.findChild(QObject, "backupDataButton")
        self.assertIsNotNone(backup_button)
        self._click(backup_button)
        self._click(self.samples_button)

    def _connect_activity_refresh(self) -> None:
        def refresh() -> None:
            records = merge_effective_records(
                self.finance.activity_records(),
                (
                    (self.fitness.activity_records(), "fitness"),
                    (self.planner.activity_records(), "planner"),
                    (self.shopping.activity_records(), "home"),
                ),
                (
                    self.finance.activity_tombstones(),
                    self.fitness.activity_tombstones(),
                    self.planner.activity_tombstones(),
                    self.shopping.activity_tombstones(),
                ),
            )
            self.daily.updateActivity(
                records=records,
                habits=self.habits.state.get("habits", []),
                media_items=self.media.activity_items(),
            )
            self.archive.updateRecords(records)

        for bridge in (self.finance, self.fitness, self.planner, self.shopping, self.media, self.habits):
            bridge.stateChanged.connect(refresh)
        refresh()

    def _assert_independent_local_data_preserved(
        self,
        *,
        daily: object | None = None,
        news: object | None = None,
        preferences: object | None = None,
        reading: object | None = None,
    ) -> None:
        daily = daily or self.daily
        news = news or self.news
        preferences = preferences or self.preferences
        reading = reading or self.reading
        self.assertEqual(daily.state["questions"], ["保留的问题簿"])
        self.assertEqual(preferences.state["topics"], ["ai"])
        self.assertEqual(preferences.state["preferences"]["subtopics"], "合成细分")
        self.assertEqual(preferences.state["preferences"]["sources"], "合成来源")
        self.assertTrue(reading.state["savedKnowledge"])
        self.assertEqual(reading.state["clippings"][0]["key"], "2026-09-27::keep-clip")
        self.assertEqual(news.state["layout"], {"order": ["focus", "highlights"], "hidden": ["highlights"]})
        self.assertEqual(news.state["linkInbox"], [{
            "url": "https://example.com/keep", "addedAt": "2026-09-27T10:00:00Z"
        }])
        self.assertEqual(self.brand.brand["name"], "合成品牌")
        self.assertEqual(self.brand.brand["theme"], "forest")

    def test_global_sample_cleanup_cancel_persist_and_reimport_suppression(self) -> None:
        self.assertTrue(self.shopping.setFilter("all")["ok"])
        self.assertTrue(self.shopping.toggleBought("sample-home", True)["ok"])
        self.assertTrue(self.shopping.toggleBought("custom-home", True)["ok"])
        self.assertTrue(self.planner.setEstimate("sample-planner", 45)["ok"])
        self.assertTrue(self.planner.setEstimate("custom-planner", 60)["ok"])
        before = _database_rows(self.database_path)
        source_before = load_imported_data(self.database_path)
        preview = self.cleanup.previewSamples()
        self.assertTrue(preview["ok"], preview)
        self.assertEqual((preview["records"], preview["media"], preview["habits"]), (4, 1, 1))

        self._show_sample_dialog()
        self.assertTrue(self.confirm_dialog.property("visible"))
        confirm_copy = str(self.confirm_text.property("text"))
        self.assertIn("4 条示例记录", confirm_copy)
        self.assertIn("周计划会保留", confirm_copy)
        self.assertIn("不影响云端账户数据", confirm_copy)
        self._click(self.cancel_button)
        self.assertFalse(self.confirm_dialog.property("visible"))
        self.assertEqual(_database_rows(self.database_path), before, "cancel must not write")

        self._connect_activity_refresh()
        self._show_sample_dialog()
        self._click(self.confirm_button)
        self.assertTrue(self.status_dialog.property("visible"))
        self.assertIn("已清理", str(self.status_text.property("text")))

        self.assertEqual({row["id"] for row in self.finance.state["records"]}, {"custom-money"})
        self.assertEqual({row["id"] for row in self.fitness.state["records"]}, {"custom-fitness"})
        self.assertEqual({row["id"] for row in self.planner.state["records"]}, {"custom-planner"})
        self.assertEqual({row["id"] for row in self.shopping.state["shoppingRecords"]}, {"custom-home"})
        self.assertTrue(next(row for row in self.shopping.state["shoppingRecords"] if row["id"] == "custom-home")["data"]["bought"])
        self.assertEqual(
            [(item["type"], item["id"]) for item in _shopping_overrides(self.database_path)],
            [("home", "custom-home")],
        )
        self.assertEqual(set(_planner_overrides(self.database_path)), {"custom-planner"})
        self.assertEqual([row["id"] for row in self.media.state["items"]], ["custom-media-1"])
        cleared_habits = self.habits.state["habits"]
        water = next(item for item in cleared_habits if item["id"] == "habit-water")
        walk = next(item for item in cleared_habits if item["id"] == "custom-habit-1")
        self.assertEqual(water["entries"], {})
        self.assertFalse(water["sample"])
        self.assertEqual(water["remoteEntries"], {"legacy-row": "remote-water"})
        self.assertEqual(walk["entries"], {"2026-09-27": 1})
        self.assertEqual(self.fitness.state["weeklyPlan"], [{"id": "synthetic-plan", "title": "合成保留周计划"}])
        self.assertTrue(self.finance.state["settings"].get("samplesCleared"))
        self.assertEqual(get_app_setting(self.database_path, "richangji-samples-cleared"), "1")
        self._assert_independent_local_data_preserved()

        reopened_finance = FinanceBridge(self.database_path)
        reopened_fitness = FitnessBridge(self.database_path)
        reopened_planner = PlannerBridge(self.database_path)
        reopened_shopping = ShoppingBridge(self.database_path)
        reopened_media = MediaBridge(self.database_path)
        reopened_habits = HabitBridge(self.database_path)
        reopened_daily = DailyBridge(self.database_path)
        reopened_preferences = IssuePreferencesBridge(self.database_path)
        reopened_reading = ReadingBridge(self.database_path)
        reopened_news = NewsBridge(self.database_path)
        for bridge in (reopened_finance, reopened_fitness, reopened_planner, reopened_shopping, reopened_media, reopened_habits):
            bridge.adoptImportedData(self.migration.data)
        self.assertEqual({row["id"] for row in reopened_finance.state["records"]}, {"custom-money"})
        self.assertEqual({row["id"] for row in reopened_fitness.state["records"]}, {"custom-fitness"})
        self.assertEqual({row["id"] for row in reopened_planner.state["records"]}, {"custom-planner"})
        self.assertEqual({row["id"] for row in reopened_shopping.state["shoppingRecords"]}, {"custom-home"})
        self.assertTrue(next(row for row in reopened_shopping.state["shoppingRecords"] if row["id"] == "custom-home")["data"]["bought"])
        self.assertEqual([row["id"] for row in reopened_media.state["items"]], ["custom-media-1"])
        self.assertEqual(next(item for item in reopened_habits.state["habits"] if item["id"] == "habit-water")["entries"], {})
        self._assert_independent_local_data_preserved(
            daily=reopened_daily,
            news=reopened_news,
            preferences=reopened_preferences,
            reading=reopened_reading,
        )

        source_after = load_imported_data(self.database_path)
        self.assertEqual(source_after["raw_values"], source_before["raw_values"])
        self.assertEqual(source_after["entities"], source_before["entities"])
        self.assertEqual(get_app_setting(self.database_path, LAYOUT_SETTING), {
            "order": ["focus", "highlights"], "hidden": ["highlights"]
        })
        self.assertEqual(get_app_setting(self.database_path, "newsLinkInbox"), [{
            "url": "https://example.com/keep", "addedAt": "2026-09-27T10:00:00Z"
        }])

    def test_clear_all_cancel_failure_rollback_and_local_only_commit(self) -> None:
        self.assertTrue(self.shopping.setFilter("all")["ok"])
        self.assertTrue(self.shopping.toggleBought("sample-home", True)["ok"])
        self.assertTrue(self.shopping.toggleBought("custom-home", True)["ok"])
        self.assertTrue(self.planner.setEstimate("sample-planner", 45)["ok"])
        self.assertTrue(self.planner.setEstimate("custom-planner", 60)["ok"])
        before = _database_rows(self.database_path)
        source_before = load_imported_data(self.database_path)
        self._show_all_dialog()
        prompt = str(self.confirm_text.property("text"))
        self.assertIn("只修改本机 SQLite", prompt)
        self.assertIn("不影响云端账户数据", prompt)
        self.assertIn("已存知识", prompt)
        self._click(self.cancel_button)
        self.assertEqual(_database_rows(self.database_path), before, "cancel must not write")

        fired = {"once": False}

        def fail_after_first_update(stage: str) -> None:
            if stage == "after-record-state" and not fired["once"]:
                fired["once"] = True
                raise sqlite3.OperationalError("synthetic injected failure")

        self.cleanup._failure_injector = fail_after_first_update
        self._show_all_dialog()
        self._click(self.confirm_button)
        self.assertTrue(fired["once"])
        self.assertEqual(_database_rows(self.database_path), before, "failed transaction must roll back every table")
        self.assertIn("已回滚", str(self.status_text.property("text")))
        self._click(self.window.findChild(QObject, "cleanupStatusCloseButton"))

        self.cleanup._failure_injector = None
        self._show_all_dialog()
        self._click(self.confirm_button)
        self.assertTrue(self.status_dialog.property("visible"))

        self.assertEqual(self.finance.state["records"], [])
        self.assertEqual(self.fitness.state["records"], [])
        self.assertEqual(self.planner.state["records"], [])
        self.assertEqual(self.shopping.state["shoppingRecords"], [])
        self.assertEqual(self.media.state["items"], [])
        self.assertEqual(self.fitness.state["weeklyPlan"], list(DEFAULT_WEEKLY_PLAN))
        for habit in self.habits.state["habits"]:
            self.assertEqual(habit["entries"], {})
            self.assertEqual(habit["remoteEntries"], {})
            self.assertFalse(habit["sample"])
        self.assertEqual(self.news.state["active"], None)
        self.assertEqual(self.news.state["archive"], [])
        self.assertEqual(self.news.state["draft"], None)
        self.assertEqual(get_app_setting(self.database_path, "dailyIssueStore"), {"active": None, "archive": []})
        self.assertIsNone(get_app_setting(self.database_path, "dailyIssueDraft"))
        self.assertEqual(self.finance.state["settings"].get("samplesCleared"), True)
        self.assertEqual(self.finance.state["settings"].get("userTouched"), True)
        self.assertEqual(get_app_setting(self.database_path, "richangji-samples-cleared"), "1")
        self.assertEqual(_shopping_overrides(self.database_path), [])
        self.assertEqual(_planner_overrides(self.database_path), {})

        self._assert_independent_local_data_preserved()
        self.assertEqual(get_app_setting(self.database_path, LAYOUT_SETTING), {
            "order": ["focus", "highlights"], "hidden": ["highlights"]
        })
        self.assertEqual(get_app_setting(self.database_path, "newsLinkInbox"), [{
            "url": "https://example.com/keep", "addedAt": "2026-09-27T10:00:00Z"
        }])
        source_after = load_imported_data(self.database_path)
        self.assertEqual(source_after["raw_values"], source_before["raw_values"])
        self.assertEqual(source_after["entities"], source_before["entities"])

        reopened_finance = FinanceBridge(self.database_path)
        reopened_fitness = FitnessBridge(self.database_path)
        reopened_planner = PlannerBridge(self.database_path)
        reopened_shopping = ShoppingBridge(self.database_path)
        reopened_media = MediaBridge(self.database_path)
        reopened_habits = HabitBridge(self.database_path)
        reopened_news = NewsBridge(self.database_path)
        reopened_daily = DailyBridge(self.database_path)
        reopened_preferences = IssuePreferencesBridge(self.database_path)
        reopened_reading = ReadingBridge(self.database_path)
        for bridge in (reopened_finance, reopened_fitness, reopened_planner, reopened_shopping, reopened_media, reopened_habits):
            bridge.adoptImportedData(self.migration.data)
        self.assertEqual(reopened_finance.state["records"], [])
        self.assertEqual(reopened_media.state["items"], [])
        self.assertEqual(reopened_habits.state["habits"][0]["entries"], {})
        self.assertEqual(reopened_news.state["active"], None)
        self.assertEqual(reopened_fitness.state["weeklyPlan"], list(DEFAULT_WEEKLY_PLAN))
        self.assertEqual(
            [row for row in reopened_planner.state["records"] if row.get("type") == "planner"],
            [],
        )
        self.assertEqual(reopened_shopping.state["shoppingRecords"], [])
        for habit in reopened_habits.state["habits"]:
            self.assertEqual(habit["entries"], {})
            self.assertEqual(habit["remoteEntries"], {})
        self._assert_independent_local_data_preserved(
            daily=reopened_daily,
            news=reopened_news,
            preferences=reopened_preferences,
            reading=reopened_reading,
        )

    def test_zero_sample_preview_is_a_no_op_in_repository_and_production_qml(self) -> None:
        empty_database = self.temp_path / "no-samples.sqlite3"
        import_package(_synthetic_package(include_samples=False), empty_database)
        migration = MigrationBridge(empty_database)
        snapshot = migration.data
        empty_bridges = {
            "finance": FinanceBridge(empty_database, snapshot),
            "fitness": FitnessBridge(empty_database, snapshot),
            "planner": PlannerBridge(empty_database, snapshot),
            "shopping": ShoppingBridge(empty_database, snapshot),
            "media": MediaBridge(empty_database, snapshot),
            "habits": HabitBridge(empty_database, snapshot),
            "news": NewsBridge(empty_database, snapshot),
        }
        cleanup = LocalDataCleanupBridge(
            empty_database,
            finance_bridge=empty_bridges["finance"],
            fitness_bridge=empty_bridges["fitness"],
            planner_bridge=empty_bridges["planner"],
            shopping_bridge=empty_bridges["shopping"],
            media_bridge=empty_bridges["media"],
            habit_bridge=empty_bridges["habits"],
            news_bridge=empty_bridges["news"],
        )
        before = _database_rows(empty_database)
        preview = cleanup.previewSamples()
        self.assertEqual((preview["records"], preview["media"], preview["habits"]), (0, 0, 0))
        result = cleanup.clearSamples()
        self.assertTrue(result["ok"], result)
        self.assertEqual(_database_rows(empty_database), before)
        self.assertIsNone(get_app_setting(empty_database, "richangji-samples-cleared"))
        self.assertTrue(self.window.setProperty("cleanupController", cleanup))
        self._show_sample_dialog()
        self.assertTrue(self.status_dialog.property("visible"))
        self.assertIn("当前没有可清理的示例", str(self.status_text.property("text")))
        self.assertFalse(self.confirm_dialog.property("visible"))
        self.assertEqual(_database_rows(empty_database), before)
        self.assertIsNone(get_app_setting(empty_database, "richangji-samples-cleared"))

    def test_incomplete_module_state_fails_closed_without_partial_cleanup(self) -> None:
        for case in ("missing-table", "missing-singleton"):
            broken_database = self.temp_path / f"{case}.sqlite3"
            import_package(_synthetic_package(), broken_database)
            snapshot = MigrationBridge(broken_database).data
            bridges = (
                FinanceBridge(broken_database, snapshot),
                FitnessBridge(broken_database, snapshot),
                PlannerBridge(broken_database, snapshot),
                ShoppingBridge(broken_database, snapshot),
                MediaBridge(broken_database, snapshot),
                HabitBridge(broken_database, snapshot),
            )
            connection = sqlite3.connect(str(broken_database))
            try:
                if case == "missing-table":
                    connection.execute("DROP TABLE media_module_state")
                else:
                    connection.execute("DELETE FROM habit_module_state WHERE singleton=1")
                connection.commit()
            finally:
                connection.close()
            before = _database_rows(broken_database)
            repository = LocalDataCleanupRepository(broken_database)
            for operation in (
                repository.preview_samples,
                repository.preview_all,
                repository.clear_samples,
                repository.clear_all,
            ):
                with self.assertRaises(DataCleanupError):
                    operation()
                self.assertEqual(_database_rows(broken_database), before, case)


if __name__ == "__main__":
    unittest.main()
