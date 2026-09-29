from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, QPoint, QPointF, Q_RETURN_ARG, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
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
)
from wanxiang.brand import BrandBridge, BrandRepository
from wanxiang.converter import ConverterBridge
from wanxiang.converter_engines import ConverterEngineUpdateBridge
from wanxiang.database import import_package
from wanxiang.localization import LocalizationBridge, LocalizationRepository
from wanxiang.notifications import SystemTrayNotificationAdapter
from wanxiang.tray_lifecycle import TrayLifecycleController
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


THEMES = {
    "plum": "#4d3045",
    "forest": "#365f53",
    "clay": "#8f4f3b",
    "navy": "#344b63",
}


class SyntheticLocationProvider(QObject):
    progress = Signal(int, str)
    finished = Signal(int, object)

    def __init__(self) -> None:
        super().__init__()
        self.request_ids: list[int] = []
        self.cancelled_ids: list[int] = []

    def request(self, request_id: int) -> None:
        self.request_ids.append(request_id)

    def cancel(self, request_id: int) -> None:
        self.cancelled_ids.append(request_id)


class FakeSystemTray(QObject):
    activated = Signal(object)

    def __init__(self, *, supports_messages: bool = True) -> None:
        super().__init__()
        self.supports_messages = supports_messages
        self.menu = None
        self.messages: list[tuple[object, ...]] = []

    def isSystemTrayAvailable(self) -> bool:
        return True

    def supportsMessages(self) -> bool:
        return self.supports_messages

    def showMessage(self, *args: object) -> None:
        self.messages.append(args)

    def setContextMenu(self, menu: object) -> None:
        self.menu = menu


class FakeApplication:
    def __init__(self) -> None:
        self.quit_calls = 0

    def quit(self) -> None:
        self.quit_calls += 1


def _synthetic_package() -> object:
    state = {
        "version": 2,
        "records": [],
        "habits": [],
        "mediaItems": [],
        "settings": {
            "brand": {
                "name": "合成主题验收",
                "avatar": "合",
                "tagline": "仅用于隔离验收",
                "theme": "plum",
            }
        },
        "drafts": {},
    }
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    raw_values["richangji-state-v1"] = json.dumps(state, ensure_ascii=False)
    return validate_package({
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-stage1-close-theme-check",
        "exportedAt": "2026-09-28T00:00:00Z",
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    })


class Stage1MainWindowCloseAndThemeTests(unittest.TestCase):
    """Exercise production Main.qml against a temporary synthetic SQLite DB."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setApplicationName("FLUKE Stage 1 synthetic acceptance")
        cls.native_dir = Path(__file__).resolve().parents[1]
        cls.project_dir = cls.native_dir.parent

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-stage1-close-theme-")
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)
        self.database_path = self.temp_path / "synthetic.sqlite3"
        import_package(_synthetic_package(), self.database_path)

        self.engine = QQmlApplicationEngine()
        self.addCleanup(self._destroy_engine)
        self.migration = MigrationBridge(self.database_path)
        snapshot = self.migration.data
        self.weather_location_provider = SyntheticLocationProvider()
        self.weather = WeatherBridge(
            self.database_path, snapshot, location_provider=self.weather_location_provider
        )
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
        self.converter_engine = ConverterEngineUpdateBridge(self.temp_path / "engine-updates")
        self.brand = BrandBridge(BrandRepository(self.database_path), self.engine)
        self.locale = LocalizationBridge(
            LocalizationRepository(self.database_path), self.engine, self.app
        )
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

        self.engine.setInitialProperties({
            "migrationController": self.migration,
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
            "converterEngineController": self.converter_engine,
            "brandController": self.brand,
            "cleanupController": self.cleanup,
            "localeController": self.locale,
        })
        qml_path = self.native_dir / "qml" / "Main.qml"
        qml_warnings: list[str] = []
        self.engine.warnings.connect(lambda warnings: qml_warnings.extend(warning.toString() for warning in warnings))
        self.engine.load(QUrl.fromLocalFile(str(qml_path)))
        self.assertTrue(
            self.engine.rootObjects(),
            "production Main.qml failed to load: " + " | ".join(qml_warnings),
        )
        self.window = self.engine.rootObjects()[0]
        self.window.resize(1480, 960)
        self.window.show()
        QTest.qWait(350)

        self.dialog = self.window.findChild(QObject, "brandAppearanceDialog")
        self.assertIsNotNone(self.dialog, "production appearance dialog was not found")

    def _destroy_engine(self) -> None:
        if getattr(self, "engine", None) is not None:
            self.engine.deleteLater()
            try:
                QTest.qWait(30)
            except RuntimeError:
                pass

    def test_main_window_loads_bundled_sans_and_serif_fonts(self) -> None:
        font_directory = self.project_dir / "assets" / "fonts"
        self.assertTrue((font_directory / "NotoSansSC-VF.ttf").is_file())
        self.assertTrue((font_directory / "NotoSerifSC-VF.ttf").is_file())
        self.assertTrue(bool(self.window.property("bundledSansFontReady")))
        self.assertTrue(bool(self.window.property("bundledSerifFontReady")))
        self.assertEqual(str(self.window.property("sansFamily")), "Noto Sans SC")
        self.assertEqual(str(self.window.property("serifFamily")), "Noto Serif SC")

    def test_short_compact_window_keeps_daily_flow_steps_on_one_row(self) -> None:
        self.window.resize(760, 620)
        QTest.qWait(120)

        steps = [self._visual_item(f"flowStep_{index}") for index in range(4)]
        notes = [self._visual_item(f"flowStepNote_{index}") for index in range(4)]
        self.assertTrue(all(step is not None for step in steps))
        self.assertTrue(all(note is not None for note in notes))
        step_y = [float(step.property("y")) for step in steps if step is not None]
        self.assertLessEqual(max(step_y) - min(step_y), 1.0)
        self.assertTrue(all(not note.isVisible() for note in notes if note is not None))
        self.assertTrue(all(float(step.property("height")) == 42.0 for step in steps if step is not None))

    def test_daily_flow_step_navigation_tracks_the_visible_section(self) -> None:
        self.window.resize(1480, 960)
        QTest.qWait(120)

        scroll_view = self._visual_item("dailyPageScroll")
        scroll_content = self.window.property("flowScrollContent")
        review = self._visual_item("dailyReviewSection")
        work = self._visual_item("dailyWorkSection")
        focus = self._visual_item("dailyFocusSection")
        self.assertIsNotNone(scroll_view)
        self.assertIsNotNone(scroll_content)
        self.assertIsNotNone(review)
        self.assertIsNotNone(work)
        self.assertIsNotNone(focus)

        for step, target in ((1, review), (2, work), (3, focus)):
            with self.subTest(step=step):
                self._invoke(self._visual_item(f"flowStep_{step}"), "click")
                self.assertEqual(int(self.window.property("currentFlowStep")), step)
                target_y = target.mapToItem(scroll_view, 0, 0).y()
                self.assertGreaterEqual(
                    target_y,
                    -20,
                    f"step {step} landed above the scroll viewport ({target_y:.1f})",
                )
                self.assertLessEqual(
                    target_y,
                    48,
                    f"step {step} did not bring its section near the top ({target_y:.1f})",
                )

        review_y = review.mapToItem(scroll_view, 0, 0).y()
        self.assertLess(review_y, -20, "scrolling to focus should move the review section above the viewport")
        self.assertEqual(int(self.window.property("currentFlowStep")), 3)

        self.assertTrue(scroll_content.setProperty("contentY", 0.0))
        QTest.qWait(100)
        self.assertEqual(
            int(self.window.property("currentFlowStep")),
            0,
            "returning to the first section by scrolling should also update the step highlight",
        )

    def test_manual_weather_city_can_replace_a_pending_system_location_request(self) -> None:
        self.weather.requestLocation()
        self.assertTrue(self.weather.locationBusy)
        request_id = self.weather_location_provider.request_ids[-1]

        city_input = self._visual_item("weatherCityInput")
        query_button = self._visual_item("queryWeatherButton")
        self.assertIsNotNone(city_input)
        self.assertIsNotNone(query_button)
        city_input.setProperty("text", "合成市")
        QTest.qWait(50)
        self.assertTrue(bool(city_input.property("enabled")))
        self.assertTrue(bool(query_button.property("enabled")))
        self.assertEqual(str(query_button.property("text")), "改用此城市")

        requested: list[int] = []
        self.weather._request_geocoding = lambda query_id: requested.append(query_id)
        self._invoke(query_button, "click")

        self.assertFalse(self.weather.locationBusy)
        self.assertIn(request_id, self.weather_location_provider.cancelled_ids)
        self.assertEqual(self.weather.city, "合成市")
        self.assertEqual(requested, [self.weather._query_id])

        self.weather_location_provider.finished.emit(request_id, {
            "latitude": 31.2,
            "longitude": 121.5,
        })
        self.assertEqual(
            self.weather.city,
            "合成市",
            "a late location result must not overwrite the city chosen by the user",
        )

    def test_finance_page_identifies_the_legacy_default_budget_until_user_sets_one(self) -> None:
        self.window.setProperty("currentSectionIndex", 1)
        QTest.qWait(80)

        amount_label = self._visual_item("financeBudgetAmountLabel")
        budget_label = self._visual_item("financeBudgetLabel")
        default_hint = self._visual_item("financeBudgetDefaultHint")
        save_button = self._visual_item("financeBudgetSaveButton")
        self.assertIsNotNone(amount_label)
        self.assertIsNotNone(budget_label)
        self.assertIsNotNone(default_hint)
        self.assertIsNotNone(save_button)
        self.assertIn("默认值", amount_label.property("text"))
        self.assertEqual(budget_label.property("text"), "本月预算金额")
        self.assertTrue(default_hint.isVisible())
        self.assertEqual(save_button.property("text"), "设置预算")

        self.finance.setBudget("3200")
        QTest.qWait(80)
        self.assertNotIn("默认值", amount_label.property("text"))
        self.assertFalse(default_hint.isVisible())
        self.assertEqual(save_button.property("text"), "更新预算")

    def test_empty_archive_routes_to_the_module_that_creates_each_record(self) -> None:
        self.window.setProperty("currentSectionIndex", 7)
        QTest.qWait(100)
        archive_empty_state = self._visual_item("archiveEmptyState")
        self.assertIsNotNone(archive_empty_state)
        self.assertTrue(archive_empty_state.isVisible())
        recent_activity = self._visual_item("archiveRecentActivityPanel")
        self.assertIsNotNone(recent_activity)
        self.assertFalse(recent_activity.isVisible())
        self.assertEqual(float(recent_activity.property("height")), 0.0)

        for object_name, section_index in (
            ("archiveEmptyModule_finance", 1),
            ("archiveEmptyModule_fitness", 3),
            ("archiveEmptyModule_planner", 4),
            ("archiveEmptyModule_shopping", 5),
        ):
            with self.subTest(module=object_name):
                self.window.setProperty("currentSectionIndex", 7)
                QTest.qWait(50)
                button = self._visual_item(object_name)
                self.assertIsNotNone(button, f"{object_name} was not created")
                self.assertTrue(button.isVisible())
                self._invoke(button, "click")
                self.assertEqual(int(self.window.property("currentSectionIndex")), section_index)

    def test_compact_archive_shows_filters_and_records_before_activity_summary(self) -> None:
        self.window.resize(760, 620)
        result = self.fitness.addRecord("68", "", date.today().isoformat(), "synthetic archive row")
        self.assertTrue(result["ok"], result)
        self.archive.updateRecords(self.fitness.activity_records())
        QTest.qWait(100)
        self.window.setProperty("currentSectionIndex", 7)
        QTest.qWait(100)

        filters = self._visual_item("archiveFilters")
        groups = self._visual_item("archiveGroups")
        recent_activity = self._visual_item("archiveRecentActivityPanel")
        self.assertIsNotNone(filters)
        self.assertIsNotNone(groups)
        self.assertIsNotNone(recent_activity)
        self.assertLess(filters.y(), groups.y())
        self.assertLess(
            groups.y(),
            recent_activity.y(),
            f"archive panel placement: groupsY={groups.y()} activityY={recent_activity.y()} "
            f"activityVisible={recent_activity.isVisible()} activityHeight={recent_activity.height()} "
            f"summary={self.archive.state.get('summary')}",
        )

        screenshot = self.window.grabWindow()
        self.assertFalse(screenshot.isNull(), "compact archive screenshot was empty")
        screenshot_dir = self.native_dir / "qa-release" / "ui-runtime-review"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.assertTrue(
            screenshot.save(
                str(screenshot_dir / "archive-compact-records-first-2026-09-29.png"),
                "PNG",
            )
        )

    @staticmethod
    def _invoke(target: QObject, method: str) -> None:
        if not QMetaObject.invokeMethod(target, method, Qt.ConnectionType.DirectConnection):
            raise AssertionError(f"QML method {method} was not invokable")
        QTest.qWait(80)

    @staticmethod
    def _color_name(value: object) -> str:
        color = QColor(value)
        if not color.isValid():
            raise AssertionError(f"QML color property was invalid: {value!r}")
        return color.name().lower()

    def _visual_item(self, object_name: str):
        pending = [self.window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == object_name:
                return item
            pending.extend(item.childItems())
        return None

    def _click_theme_button(self, index: int) -> None:
        # The four production delegates are visually present but are not
        # exposed in the QObject child tree on this Qt version. Click their
        # centers through QTest against the real QQuickWindow instead.
        dialog_x = float(self.dialog.property("x"))
        dialog_y = float(self.dialog.property("y"))
        dialog_width = float(self.dialog.property("width"))
        dialog_height = float(self.dialog.property("height"))
        grid_width = dialog_width - 40.0
        gap = 8.0
        cell_width = (grid_width - 3 * gap) / 4.0
        center_x = dialog_x + 20.0 + index * (cell_width + gap) + cell_width / 2.0
        center_y = dialog_y + dialog_height - 72.0
        QTest.mouseClick(
            self.window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(center_x), round(center_y)),
        )
        QTest.qWait(80)

    def test_full_window_theme_preview_save_reopen_and_qwindow_close(self) -> None:
        evidence_dir = Path(os.environ.get(
            "WANXIANG_STAGE1_EVIDENCE_DIR",
            str(self.project_dir / "artifacts" / "stage-1-native" / "theme-captures"),
        ))
        evidence_dir.mkdir(parents=True, exist_ok=True)
        expected = {key: value for key, value in THEMES.items()}
        observed: dict[str, dict[str, object]] = {}
        pixel_data: dict[str, bytes] = {}

        # The production dialog's theme buttons emit previewChanged, which
        # updates Main.qml's shownBrand and the root UiTheme accent binding.
        current_saved_theme = "plum"
        for index, (theme, expected_accent) in enumerate(expected.items()):
            self._invoke(self.dialog, "open")
            self.assertTrue(bool(self.dialog.property("visible")))
            self.assertEqual(str(self.dialog.property("draftTheme")), current_saved_theme)
            self._click_theme_button(index)
            self.assertEqual(str(self.dialog.property("draftTheme")), theme)
            preview_accent = self._color_name(self.window.property("blue"))
            self.assertEqual(preview_accent, expected_accent)

            # Cancel the unsaved preview and prove that both the main window
            # and persisted setting return to the previously saved theme.
            self._invoke(self.dialog, "cancelDraft")
            self.assertFalse(bool(self.dialog.property("visible")))
            self.assertEqual(self._color_name(self.window.property("blue")), THEMES[current_saved_theme])
            self.assertEqual(BrandRepository(self.database_path).brand()["theme"], current_saved_theme)

            self._invoke(self.dialog, "open")
            self._click_theme_button(index)
            self.assertEqual(str(self.dialog.property("draftTheme")), theme)
            self.assertEqual(self._color_name(self.window.property("blue")), expected_accent)

            # Saving closes the modal editor; the resulting full-window PNG
            # shows the production main page under the selected theme.
            self._invoke(self.dialog, "finishSave")
            self.assertFalse(bool(self.dialog.property("visible")))
            saved = BrandRepository(self.database_path).brand()
            self.assertEqual(saved["theme"], theme)
            self.assertEqual(str(self.dialog.property("draftTheme")), theme)
            saved_accent = self._color_name(self.window.property("blue"))
            self.assertEqual(saved_accent, expected_accent)
            QTest.qWait(120)

            capture_path = evidence_dir / f"main-{theme}-1480x960.png"
            image = self.window.grabWindow()
            self.assertFalse(image.isNull(), f"QQuickWindow capture failed for {theme}")
            self.assertTrue(image.save(str(capture_path)), f"could not save {capture_path}")
            normalized = image.convertToFormat(QImage.Format.Format_RGBA8888)
            pixel_data[theme] = bytes(normalized.constBits()[: normalized.sizeInBytes()])
            observed[theme] = {
                "accent": saved_accent,
                "logicalSize": [int(self.window.width()), int(self.window.height())],
                "pixelSize": [image.width(), image.height()],
                "devicePixelRatio": float(image.devicePixelRatio()),
                "screenshot": str(capture_path.resolve()),
                "sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
            }

            # Reopen and cancel verifies that the saved selection comes back
            # into the production QML editor without changing persisted data.
            self._invoke(self.dialog, "open")
            self.assertEqual(str(self.dialog.property("draftTheme")), theme)
            self._invoke(self.dialog, "cancelDraft")
            self.assertEqual(BrandRepository(self.database_path).brand()["theme"], theme)
            current_saved_theme = theme

        for left in expected:
            for right in expected:
                if left < right:
                    self.assertNotEqual(pixel_data[left], pixel_data[right], f"theme screenshots did not differ: {left}, {right}")

        evidence_path = evidence_dir / "theme-capture-results.json"
        evidence_path.write_text(
            json.dumps({
                "verification": "synthetic production Main.qml / temporary SQLite",
                "manualTitleBarClickPerformed": False,
                "windowCloseMethod": "QQuickWindow.close() through Qt's close event",
                "themes": observed,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        child_environment = os.environ.copy()
        existing_pythonpath = child_environment.get("PYTHONPATH", "")
        child_environment["PYTHONPATH"] = os.pathsep.join(
            value for value in (str(self.native_dir), existing_pythonpath) if value
        )
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--stage1-close-child"],
            cwd=str(self.native_dir),
            env=child_environment,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        self.assertEqual(
            child.returncode,
            0,
            "isolated close child failed\n"
            f"stdout:\n{child.stdout}\nstderr:\n{child.stderr}",
        )
        result_lines = [
            line.removeprefix("STAGE1_CLOSE_RESULT=")
            for line in child.stdout.splitlines()
            if line.startswith("STAGE1_CLOSE_RESULT=")
        ]
        self.assertTrue(result_lines, f"close child emitted no result: {child.stdout!r}")
        close_result = json.loads(result_lines[-1])
        self.assertEqual(close_result.get("exitCode"), 0)
        self.assertTrue(close_result.get("lastWindowClosed"))
        self.assertTrue(close_result.get("aboutToQuit"))
        self.assertTrue(close_result.get("windowHiddenAfterClose"))
        self.assertFalse(close_result.get("manualTitleBarClickPerformed"))
        observed["close"] = close_result
        evidence_path.write_text(
            json.dumps({
                "verification": "synthetic production Main.qml / temporary SQLite",
                "manualTitleBarClickPerformed": False,
                "windowCloseMethod": "QQuickWindow.close() through Qt's close event",
                "themes": {key: value for key, value in observed.items() if key in expected},
                "close": observed["close"],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_pending_reminder_window_close_hides_and_tray_controller_restores_it(self) -> None:
        tray = FakeSystemTray()
        controller = TrayLifecycleController(self.app, tray, lambda: True)
        controller.set_window(self.window)
        self.window.setProperty("trayController", controller)

        self.window.close()
        QTest.qWait(80)
        self.assertFalse(self.window.isVisible(), "pending reminders should hide the window to tray")
        self.assertEqual(controller.closeDisposition(), "hide")

        controller.show_window()
        QTest.qWait(100)
        self.assertTrue(self.window.isVisible(), "tray open should restore the same window")
        self.assertIsNotNone(tray.menu)

        self.window.setProperty("trayController", None)

    def test_due_reminder_reaches_system_tray_while_main_window_is_hidden(self) -> None:
        tray = FakeSystemTray()
        now = datetime.now().astimezone().replace(second=0, microsecond=0)
        clock = {"now": now}
        assert self.planner._repository is not None
        self.planner._repository._clock = lambda: clock["now"]
        self.planner._notifier = SystemTrayNotificationAdapter(
            tray,
            system_tray_available=True,
            messages_supported=True,
        )
        due = now + timedelta(minutes=1)
        created = self.planner.addTaskWithOrganization(
            "隐藏窗口到期提醒",
            due.date().isoformat(),
            due.strftime("%H:%M"),
            "normal",
            "工作",
            "隔离托盘通知验证",
            True,
            30,
            "none",
            "",
            "",
        )
        self.assertTrue(created["ok"], created)
        self.assertTrue(self.planner.has_pending_reminders())

        controller = TrayLifecycleController(
            self.app, tray, self.planner.has_pending_reminders
        )
        controller.set_window(self.window)
        self.window.setProperty("trayController", controller)
        self.window.close()
        QTest.qWait(80)
        self.assertFalse(self.window.isVisible())

        clock["now"] = due + timedelta(seconds=1)
        self.planner.checkReminders()
        QTest.qWait(120)

        self.assertEqual(len(tray.messages), 1)
        self.assertEqual(tray.messages[0][:2], ("隐藏窗口到期提醒", "隔离托盘通知验证"))
        popup = self.window.findChild(QObject, "plannerReminderPopup")
        self.assertIsNotNone(popup)
        self.assertTrue(bool(popup.property("visible")))
        self.assertFalse(
            self.window.isVisible(),
            "the application window should remain hidden while its tray notification is dispatched",
        )

        self.planner.checkReminders()
        QTest.qWait(80)
        self.assertEqual(len(tray.messages), 1, "a reminder should only notify once")
        controller.show_window()
        QTest.qWait(80)
        self.assertTrue(self.window.isVisible())
        self.window.setProperty("trayController", None)

    def test_pending_reminders_without_a_tray_show_keep_open_or_exit_choices(self) -> None:
        app = FakeApplication()
        controller = TrayLifecycleController(app, None, lambda: True)
        self.window.setProperty("trayController", controller)

        self.window.close()
        QTest.qWait(80)
        dialog = self.window.findChild(QObject, "trayUnavailableCloseDialog")
        keep_open = self.window.findChild(QObject, "trayUnavailableKeepOpenButton")
        exit_button = self.window.findChild(QObject, "trayUnavailableExitButton")
        self.assertTrue(self.window.isVisible())
        self.assertIsNotNone(dialog)
        self.assertTrue(bool(dialog.property("visible")))
        self.assertIsNotNone(keep_open)
        self.assertIsNotNone(exit_button)

        self._invoke(keep_open, "click")
        self.assertFalse(bool(dialog.property("visible")))
        self.assertEqual(app.quit_calls, 0)

        self.window.close()
        QTest.qWait(80)
        self._invoke(exit_button, "click")
        self.assertEqual(app.quit_calls, 1)
        self.assertTrue(self.window.isVisible())
        self.window.setProperty("trayController", None)

    def test_tray_fallback_dialog_retranslates_in_the_production_window(self) -> None:
        app = FakeApplication()
        controller = TrayLifecycleController(app, None, lambda: True)
        self.window.setProperty("trayController", controller)

        self.window.close()
        QTest.qWait(80)
        dialog = self.window.findChild(QObject, "trayUnavailableCloseDialog")
        keep_open = self.window.findChild(QObject, "trayUnavailableKeepOpenButton")
        exit_button = self.window.findChild(QObject, "trayUnavailableExitButton")
        self.assertIsNotNone(dialog)
        self.assertIsNotNone(keep_open)
        self.assertIsNotNone(exit_button)
        self.assertEqual(dialog.property("title"), "仍有待处理提醒")
        self.assertEqual(keep_open.property("text"), "保持打开")
        self.assertEqual(exit_button.property("text"), "仍然退出")

        content = dialog.property("contentItem")
        self.assertIsNotNone(content)
        self.assertEqual(
            content.property("text"),
            "当前系统无法提供托盘提醒。为避免错过提醒，请保持窗口打开，或仍然退出软件。",
        )
        self.assertTrue(self.locale.setLanguage("en_US")["ok"])
        self.assertEqual(dialog.property("title"), "Pending reminders")
        self.assertEqual(keep_open.property("text"), "Keep window open")
        self.assertEqual(exit_button.property("text"), "Exit anyway")
        self.assertIn("tray reminders", content.property("text"))

        dialog.setProperty("storageError", True)
        QTest.qWait(50)
        self.assertEqual(dialog.property("title"), "Reminder status unavailable")
        self.assertIn("Planner data cannot be checked", content.property("text"))

        self.assertTrue(self.locale.setLanguage("zh_CN")["ok"])
        self.window.setProperty("trayController", None)

    def test_pending_reminders_with_tray_without_message_support_keep_window_open(self) -> None:
        tray = FakeSystemTray(supports_messages=False)
        controller = TrayLifecycleController(self.app, tray, lambda: True)
        controller.set_window(self.window)
        self.window.setProperty("trayController", controller)
        self.assertEqual(controller.closeDisposition(), "no_tray")
        self.assertIsNotNone(self.window.property("trayController"))

        self.window.close()
        QTest.qWait(80)

        dialog = self.window.findChild(QObject, "trayUnavailableCloseDialog")
        self.assertTrue(self.window.isVisible())
        self.assertIsNotNone(dialog)
        self.assertTrue(bool(dialog.property("visible")))
        self.assertEqual(controller.closeDisposition(), "no_tray")
        self.window.setProperty("trayController", None)

    def test_compact_appearance_dialog_signals_scrollable_options(self) -> None:
        self.window.resize(760, 620)
        QTest.qWait(100)
        self._invoke(self.dialog, "open")

        scroll = self.window.findChild(QObject, "appearanceScroll")
        hint = self.window.findChild(QObject, "appearanceScrollHint")
        scroll_bar = self.window.findChild(QObject, "appearanceVerticalScrollBar")
        self.assertIsNotNone(scroll)
        self.assertIsNotNone(hint)
        self.assertIsNotNone(scroll_bar)
        self.assertGreater(float(scroll.property("contentHeight")), float(scroll.property("height")))
        self.assertTrue(bool(hint.property("visible")))
        self.assertTrue(bool(scroll_bar.property("visible")))
        max_scroll = float(scroll.property("contentHeight")) - float(scroll.property("height"))
        scroll.setProperty("contentY", max_scroll)
        QTest.qWait(60)
        self.assertGreaterEqual(float(scroll.property("contentY")), max_scroll - 1)

    def test_compact_finance_actions_scroll_fully_above_bottom_navigation(self) -> None:
        self.window.resize(760, 620)
        self.window.setProperty("currentSectionIndex", 1)
        QTest.qWait(120)

        scroll = self._visual_item("financeScrollView")
        bottom_nav = self._visual_item("bottomNav_1")
        self.assertIsNotNone(scroll)
        self.assertIsNotNone(bottom_nav)
        self.assertTrue(bool(scroll.property("clip")))
        viewport_top = scroll.mapToScene(QPointF(0, 0)).y()
        viewport_bottom = viewport_top + float(scroll.property("height"))
        navigation_top = bottom_nav.mapToScene(QPointF(0, 0)).y()
        self.assertAlmostEqual(viewport_bottom, navigation_top, delta=1.0)

        summary_cards = [
            self._visual_item(f"financeSummaryCard_{index}")
            for index in range(4)
        ]
        self.assertTrue(all(card is not None for card in summary_cards))
        card_tops = [card.mapToScene(QPointF(0, 0)).y() for card in summary_cards]
        self.assertLessEqual(max(card_tops) - min(card_tops), 1.0)
        self.assertLess(float(summary_cards[0].height()), 90.0)

        pending = list(scroll.childItems())
        flickable = None
        while pending:
            item = pending.pop()
            if item.metaObject().className() == "QQuickFlickable":
                flickable = item
                break
            pending.extend(item.childItems())
        self.assertIsNotNone(flickable, "finance page has no scrollable content area")
        maximum_scroll = float(flickable.property("contentHeight")) - float(flickable.height())
        self.assertGreater(maximum_scroll, 0)

        # Scroll each workflow's primary action into view as a user would.
        for object_name in ("financeBudgetSaveButton", "financeSaveButton"):
            action = self._visual_item(object_name)
            self.assertIsNotNone(action, object_name)
            action_top = action.mapToScene(QPointF(0, 0)).y()
            current_y = float(flickable.property("contentY"))
            delta = action_top - viewport_top
            flickable.setProperty("contentY", min(maximum_scroll, max(0.0, current_y + delta)))
            QTest.qWait(60)
            action_top = action.mapToScene(QPointF(0, 0)).y()
            action_bottom = action_top + float(action.height())
            self.assertGreaterEqual(action_top, viewport_top - 1, object_name)
            self.assertLessEqual(action_bottom, navigation_top + 1, object_name)

    def test_compact_planner_shopping_and_media_primary_actions_are_reachable(self) -> None:
        self.window.resize(760, 620)
        pages = (
            (4, "plannerScroll", "plannerAddButton", None),
            (5, "shoppingScrollView", "shoppingAddButton", "shoppingNameInput"),
            (6, "mediaScrollView", "mediaAddButton", "mediaNameInput"),
        )

        for section_index, scroll_name, action_name, input_name in pages:
            with self.subTest(page=scroll_name):
                self.window.setProperty("currentSectionIndex", section_index)
                QTest.qWait(100)

                scroll = self._visual_item(scroll_name)
                bottom_nav = self._visual_item(f"bottomNav_{section_index}")
                action = self._visual_item(action_name)
                self.assertIsNotNone(scroll, scroll_name)
                self.assertIsNotNone(bottom_nav, f"bottomNav_{section_index}")
                self.assertIsNotNone(action, action_name)
                self.assertTrue(bool(scroll.property("clip")), scroll_name)

                viewport_top = scroll.mapToScene(QPointF(0, 0)).y()
                viewport_bottom = viewport_top + float(scroll.property("height"))
                navigation_top = bottom_nav.mapToScene(QPointF(0, 0)).y()
                self.assertAlmostEqual(viewport_bottom, navigation_top, delta=1.0)

                pending = list(scroll.childItems())
                flickable = scroll if scroll.metaObject().className() == "QQuickFlickable" else None
                while pending and flickable is None:
                    item = pending.pop()
                    if item.metaObject().className() == "QQuickFlickable":
                        flickable = item
                        break
                    pending.extend(item.childItems())
                self.assertIsNotNone(flickable, f"{scroll_name} has no scrollable content")

                if input_name is not None:
                    input_item = self._visual_item(input_name)
                    self.assertIsNotNone(input_item, input_name)
                    input_item.setProperty("text", "紧凑窗口验证")
                    QTest.qWait(30)

                target_top = action.mapToScene(QPointF(0, 0)).y()
                current_y = float(flickable.property("contentY"))
                delta = target_top - viewport_top
                max_y = max(
                    0.0,
                    float(flickable.property("contentHeight")) - float(flickable.height()),
                )
                flickable.setProperty("contentY", min(max_y, max(0.0, current_y + delta)))
                QTest.qWait(60)

                action_top = action.mapToScene(QPointF(0, 0)).y()
                action_bottom = action_top + float(action.height())
                self.assertGreaterEqual(action_top, viewport_top - 1, action_name)
                self.assertLessEqual(action_bottom, navigation_top + 1, action_name)
                if input_name == "shoppingNameInput":
                    self.assertTrue(bool(action.property("enabled")), action_name)
                    summary_cards = [
                        self._visual_item(f"shoppingSummaryCard_{index}")
                        for index in range(4)
                    ]
                    self.assertTrue(all(card is not None for card in summary_cards))
                    card_tops = [card.mapToScene(QPointF(0, 0)).y() for card in summary_cards]
                    self.assertLessEqual(max(card_tops) - min(card_tops), 1.0)
                    self.assertLess(float(summary_cards[0].height()), 90.0)

    def test_compact_empty_weather_state_exposes_location_setup_without_scrolling(self) -> None:
        self.window.resize(760, 620)
        self.window.setProperty("currentSectionIndex", 0)
        QTest.qWait(100)

        scroll = self._visual_item("dailyPageScroll")
        bottom_nav = self._visual_item("bottomNav_0")
        self.assertIsNotNone(scroll)
        self.assertIsNotNone(bottom_nav)
        viewport_top = scroll.mapToScene(QPointF(0, 0)).y()
        viewport_bottom = viewport_top + float(scroll.property("height"))
        navigation_top = bottom_nav.mapToScene(QPointF(0, 0)).y()
        self.assertAlmostEqual(viewport_bottom, navigation_top, delta=1.0)

        temperature = self._visual_item("weatherTemperatureText")
        self.assertIsNotNone(temperature)
        self.assertFalse(bool(temperature.property("visible")))
        empty_prompt = self._visual_item("weatherEmptyPrompt")
        self.assertIsNotNone(empty_prompt)
        self.assertTrue(bool(empty_prompt.property("visible")))

        for object_name in ("weatherCityInput", "queryWeatherButton", "weatherLocateButton"):
            control = self._visual_item(object_name)
            self.assertIsNotNone(control, object_name)
            control_top = control.mapToScene(QPointF(0, 0)).y()
            control_bottom = control_top + float(control.height())
            self.assertGreaterEqual(control_top, viewport_top - 1.0, object_name)
            self.assertLessEqual(control_bottom, navigation_top + 1.0, object_name)
        self.assertFalse(bool(self._visual_item("queryWeatherButton").property("enabled")))
        self.assertTrue(bool(self._visual_item("weatherLocateButton").property("enabled")))

    def test_daily_habit_quick_checks_reflow_and_keep_checkin_behavior(self) -> None:
        self.assertEqual(
            [habit["id"] for habit in self.habits.state["habits"][:3]],
            ["habit-water", "habit-sleep", "habit-exercise"],
        )

        today_weekday = date.fromisoformat(self.habits.state["today"]).isoweekday()

        def due_for(days: list[int]) -> bool:
            result = QMetaObject.invokeMethod(
                self.window,
                "dailyHabitDueToday",
                Qt.ConnectionType.DirectConnection,
                Q_RETURN_ARG("QVariant"),
                Q_ARG("QVariant", {
                    "schedule": {"type": "weekdays", "days": days},
                }),
            )
            return bool(result.toVariant() if hasattr(result, "toVariant") else result)

        self.assertTrue(due_for([today_weekday]))
        next_weekday = today_weekday % 7 + 1
        self.assertFalse(due_for([next_weekday]))

        for index in range(3):
            added = self.habits.addHabit({
                "name": f"额外习惯 {index + 1}",
                "type": "check",
                "target": 1,
                "unit": "次",
                "tone": "sage",
            })
            self.assertTrue(added["ok"])
        QTest.qWait(100)

        grid = self._visual_item("dailyHabitQuickGrid")
        card = self._visual_item("dailyHabitQuickCard_0")
        button = self._visual_item("dailyHabitQuickButton_0")
        overflow_hint = self._visual_item("dailyHabitQuickOverflowHint")
        self.assertIsNotNone(grid)
        self.assertIsNotNone(card, "daily habits from Python did not create quick cards")
        self.assertIsNotNone(button)
        self.assertIsNotNone(overflow_hint)
        self.assertTrue(bool(overflow_hint.property("visible")))
        overflow_count = len(self.habits.state["habits"]) - 5
        self.assertIn(f"还有 {overflow_count} 项", str(overflow_hint.property("text")))
        self.assertIsNone(self._visual_item("dailyHabitLegacyQuickButton_0"))
        grid = self._visual_item("dailyHabitQuickGrid")
        card = self._visual_item("dailyHabitQuickCard_0")
        button = self._visual_item("dailyHabitQuickButton_0")
        self.assertEqual(int(grid.property("columns")), 2)
        self.assertGreater(float(card.property("width")), 400)
        self.assertLess(
            float(card.property("width"))
            - float(button.property("x"))
            - float(button.property("width")),
            56,
            "The habit action should sit at the card's trailing edge.",
        )

        for expected_value in range(1, 9):
            self._invoke(button, "click")
            habit = next(
                row for row in self.habits.state["habits"]
                if row["id"] == "habit-water"
            )
            actual_value = habit["entries"].get(self.habits.state["today"], 0)
            self.assertEqual(actual_value, expected_value, f"water count was {actual_value}")
            button = self._visual_item("dailyHabitQuickButton_0")
            self.assertIsNotNone(button)

        self.assertEqual(button.property("text"), "已完成 · 重置")
        self.assertTrue(bool(button.property("highlighted")))
        self._invoke(button, "click")
        habit = next(row for row in self.habits.state["habits"] if row["id"] == "habit-water")
        self.assertEqual(habit["entries"][self.habits.state["today"]], 0)

        grid = self._visual_item("dailyHabitQuickGrid")
        card = self._visual_item("dailyHabitQuickCard_0")
        self.window.resize(760, 620)
        QTest.qWait(120)
        self.assertEqual(int(grid.property("columns")), 1)
        self.assertGreater(float(card.property("width")), 600)

        check_button = self._visual_item("dailyHabitQuickButton_2")
        self.assertEqual(check_button.property("text"), "快速打卡")
        self._invoke(check_button, "click")
        exercise = next(row for row in self.habits.state["habits"] if row["id"] == "habit-exercise")
        self.assertEqual(exercise["entries"][self.habits.state["today"]], 1)

        number_button = self._visual_item("dailyHabitQuickButton_1")
        self.assertIsNotNone(number_button)
        self.assertEqual(number_button.property("text"), "输入数值")
        self._invoke(number_button, "click")
        self.assertEqual(int(self.window.property("currentSectionIndex")), 2)
        sleep = next(row for row in self.habits.state["habits"] if row["id"] == "habit-sleep")
        self.assertNotIn(self.habits.state["today"], sleep["entries"])

        self.assertTrue(self.locale.setLanguage("en_US")["ok"])
        QTest.qWait(60)
        self.assertEqual(self._visual_item("dailyHabitQuickButton_0").property("text"), "Record +1")
        self.assertEqual(self._visual_item("dailyHabitQuickButton_1").property("text"), "Enter value")
        exercise_button = self._visual_item("dailyHabitQuickButton_2")
        self.assertEqual(
            exercise_button.property("text"),
            "Completed · reset" if bool(exercise_button.property("highlighted")) else "Quick check-in",
        )


if __name__ == "__main__":
    if "--stage1-close-child" in sys.argv:
        QQuickStyle.setStyle("Basic")
        Stage1MainWindowCloseAndThemeTests.setUpClass()
        close_test = Stage1MainWindowCloseAndThemeTests(
            "test_full_window_theme_preview_save_reopen_and_qwindow_close"
        )
        result: dict[str, object] = {}
        try:
            close_test.setUp()
            app = Stage1MainWindowCloseAndThemeTests.app
            last_window_closed: list[bool] = []
            about_to_quit: list[bool] = []
            app.setQuitOnLastWindowClosed(True)
            app.lastWindowClosed.connect(lambda: last_window_closed.append(True))
            app.aboutToQuit.connect(lambda: about_to_quit.append(True))
            app.aboutToQuit.connect(close_test.planner.close)
            QTimer.singleShot(160, close_test.window.close)
            exit_code = app.exec()
            result = {
                "method": "QQuickWindow.close() through Qt's close event",
                "lastWindowClosed": bool(last_window_closed),
                "aboutToQuit": bool(about_to_quit),
                "windowHiddenAfterClose": not bool(close_test.window.isVisible()),
                "exitCode": int(exit_code),
                "manualTitleBarClickPerformed": False,
                "platform": os.environ.get("QT_QPA_PLATFORM", "default"),
                "processId": os.getpid(),
            }
            if (
                exit_code != 0
                or not last_window_closed
                or not about_to_quit
                or close_test.window.isVisible()
            ):
                raise SystemExit(1)
            print("STAGE1_CLOSE_RESULT=" + json.dumps(result, ensure_ascii=False))
        finally:
            Stage1MainWindowCloseAndThemeTests.app.setQuitOnLastWindowClosed(False)
            close_test.doCleanups()
    else:
        unittest.main()
