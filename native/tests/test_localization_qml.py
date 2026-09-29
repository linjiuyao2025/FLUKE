from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMetaObject,
    QObject,
    Property,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtQuick import QQuickItem
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
from wanxiang.database import set_app_setting
from wanxiang.localization import (
    DictionaryTranslator,
    ENGLISH_CATALOG,
    LocalizationBridge,
    LocalizationRepository,
    QML_CONTEXT_CATALOGS,
    QML_DISAMBIGUATED_CATALOGS,
)
from wanxiang.migration import STORAGE_KEYS


class LocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_language_setting_defaults_validates_and_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "locale.sqlite3"
            repository = LocalizationRepository(database)

            self.assertEqual(repository.language(), "zh_CN")
            self.assertNotIn("uiLanguage", STORAGE_KEYS)
            with self.assertRaises(ValueError):
                repository.set_language("fr_FR")

            repository.set_language("en_US")
            self.assertEqual(LocalizationRepository(database).language(), "en_US")

            set_app_setting(database, "uiLanguage", {"unexpected": "shape"})
            self.assertEqual(LocalizationRepository(database).language(), "zh_CN")

    def test_module_catalogs_use_qml_context_and_disambiguation(self) -> None:
        translator = DictionaryTranslator()
        translator.set_language("en_US")

        self.assertEqual(translator.translate("Main", "待买"), "Shopping")
        self.assertEqual(translator.translate("Main", "备份与数据"), "Backup & data")
        self.assertEqual(translator.translate("Main", "导入旧版数据"), "Import legacy data")
        self.assertEqual(
            translator.translate("Main", "导入本期 JSON"),
            "Import this issue's JSON",
        )
        self.assertEqual(
            translator.translate("Main", "NEWS SCOPE · 本机刊期工作台"),
            "NEWS SCOPE · Local issue workspace",
        )
        self.assertEqual(
            translator.translate("Main", "存储键 %1/%2 · 记录 %3 · 习惯 %4 · 书影音 %5"),
            "Storage keys %1/%2 · %3 records · %4 habits · %5 books & media",
        )
        self.assertEqual(
            translator.translate("Main", "新闻刊期 %1 · 新闻文章 %2 · 问题簿 %3 · 关注主题 %4 · 剪报 %5"),
            "News issues %1 · %2 articles · question log %3 · followed topics %4 · clippings %5",
        )
        self.assertEqual(
            translator.translate("Main", "设置字段 %1 · 日历来源 %2 · 草稿项 %3 · 首页布局顺序/槽位/隐藏 %4/%5/%6"),
            "Setting fields %1 · calendar sources %2 · draft items %3 · home layout order/slots/hidden %4/%5/%6",
        )
        self.assertEqual(
            translator.translate("Main", "样例清理 %1 · 稍后读开关 %2 · 日程同步标识 %3"),
            "Sample cleanup %1 · saved knowledge %2 · planner sync ID %3",
        )
        self.assertEqual(
            translator.translate("Main", "将清空全部本机数据"),
            "将清空全部本机数据",
            "unreviewed text stays in the original language",
        )
        self.assertEqual(translator.translate("ShoppingPage", "待买"), "To buy")
        self.assertEqual(translator.translate("ShoppingPage", "食品"), "Food")
        self.assertEqual(translator.translate("ShoppingPage", "其他"), "Other")
        self.assertEqual(translator.translate("PlannerPage", "项目"), "Project")
        self.assertEqual(translator.translate("PlannerPage", "任务标签"), "Task tags")
        self.assertEqual(translator.translate("PlannerPage", "用逗号分隔"), "Separate with commas")
        self.assertEqual(translator.translate("PlannerPage", "刷新"), "Refresh")
        self.assertEqual(translator.translate("Main", "仍有待处理提醒"), "Pending reminders")
        self.assertEqual(translator.translate("Main", "日程提醒"), "Planner reminder")
        self.assertEqual(
            translator.translate("Main", "该处理这件日程了。"),
            "Time to take care of this task.",
        )
        self.assertEqual(translator.translate("ArchivePage", "待买"), "Shopping")
        self.assertEqual(
            translator.translate("ArchivePage", "待买", "purchase status"),
            "To buy",
        )
        self.assertEqual(
            translator.translate("DailyFlowPage", "计时已重置。"),
            "Focus timer reset.",
        )
        self.assertEqual(
            translator.translate("FinancePage", "今天尚无账目；本月统计仅包含已记录的数据。"),
            "No transactions recorded today; monthly totals include recorded entries only.",
        )
        self.assertEqual(
            translator.translate("ShoppingPage", "待买物品", "shopping item count"),
            "Shopping items",
        )
        self.assertEqual(
            translator.translate("ShoppingPage", "待买物品", "shopping item fallback"),
            "Shopping item",
        )

    def test_preferences_app_update_section_localizes_live_qml(self) -> None:
        class UpdateProbe(QObject):
            stateChanged = Signal()

            def __init__(self) -> None:
                super().__init__()
                self._state = {
                    "currentVersion": "0.1.2",
                    "availableVersion": "0.1.2",
                    "releaseTag": "native-v0.1.2-preview.1",
                    "updateAvailable": True,
                    "verifiedInstallerPath": "",
                    "busy": False,
                    "progress": 0,
                    "statusMessage": "等待检查",
                    "automaticInstallAvailable": False,
                    "cancellable": False,
                }

            @Property("QVariant", notify=stateChanged)
            def state(self) -> dict[str, object]:
                return self._state

        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            database = temporary / "preferences-locale.sqlite3"
            qml_directory = Path(__file__).resolve().parents[1] / "qml"
            import_url = QUrl.fromLocalFile(str(qml_directory) + os.sep).toString()
            qml_path = temporary / "PreferencesLocaleProbe.qml"
            qml_path.write_text(
                "import QtQuick\n"
                "import QtQuick.Controls\n"
                f'import "{import_url}" as Native\n'
                "ApplicationWindow {\n"
                "  visible: true; width: 900; height: 900\n"
                "  Native.PreferencesDialog {\n"
                '    objectName: "preferencesDialogUnderTest"\n'
                "    appUpdateController: updateProbe\n"
                "    initialState: ({ topics: [], preferences: { subtopics: \"\", sources: \"\", "
                "presetSources: [] } })\n"
                "  }\n"
                "}\n",
                encoding="utf-8",
            )

            engine = QQmlApplicationEngine()
            localization = LocalizationBridge(
                LocalizationRepository(database), engine, self.app
            )
            update_probe = UpdateProbe()
            engine.rootContext().setContextProperty("updateProbe", update_probe)
            try:
                engine.load(QUrl.fromLocalFile(str(qml_path)))
                self.assertTrue(engine.rootObjects(), "PreferencesDialog failed to load")
                window = engine.rootObjects()[0]
                window.show()
                dialog = window.findChild(QObject, "preferencesDialogUnderTest")
                self.assertIsNotNone(dialog)
                assert dialog is not None
                dialog.open()
                QTest.qWait(80)

                def text_control(expected: str) -> QObject:
                    match = next(
                        (
                            item
                            for item in window.findChildren(QObject)
                            if item.property("text") == expected
                        ),
                        None,
                    )
                    self.assertIsNotNone(match, f"missing QML text: {expected}")
                    assert match is not None
                    return match

                self.assertTrue(localization.setLanguage("en_US")["ok"])
                QTest.qWait(40)
                version_text = (
                    "Current version: 0.1.2. Check GitHub Releases for Windows installers "
                    "v0.1.2 and later."
                )
                available_text = "Available version: 0.1.2 · native-v0.1.2-preview.1"
                update_notice = (
                    "This installation is not a rollback-safe side-by-side layout; only download "
                    "and verification are available, and automatic installation is disabled."
                )
                for expected in (
                    "FLUKE app updates",
                    version_text,
                    available_text,
                    update_notice,
                ):
                    with self.subTest(text=expected):
                        self.assertEqual(text_control(expected).property("text"), expected)

                for object_name, expected in (
                    ("appUpdateCheckButton", "Check for app updates"),
                    ("appUpdateDownloadButton", "Download and verify"),
                    ("appUpdateInstallButton", "Install safely and restart"),
                    ("appUpdateCancelButton", "Cancel download"),
                ):
                    with self.subTest(button=object_name):
                        self.assertEqual(
                            window.findChild(QObject, object_name).property("text"), expected
                        )

                update_probe._state["busy"] = True
                update_probe.stateChanged.emit()
                QTest.qWait(40)
                self.assertEqual(
                    window.findChild(QObject, "appUpdateCheckButton").property("text"),
                    "Checking…",
                )
                self.assertEqual(
                    window.findChild(QObject, "appUpdateDownloadButton").property("text"),
                    "Downloading…",
                )

                update_probe._state.update(
                    busy=False, verifiedInstallerPath="C:/FLUKE-0.1.2-Setup.exe"
                )
                update_probe.stateChanged.emit()
                QTest.qWait(40)
                self.assertEqual(
                    window.findChild(QObject, "appUpdateOpenFolderButton").property("text"),
                    "Open installer folder",
                )
            finally:
                localization.close()
                for root_object in engine.rootObjects():
                    root_object.close()
                engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

    def test_daily_flow_localizes_fixed_hints_and_preserves_user_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            database = temporary / "daily-flow-locale.sqlite3"
            today = date.today().isoformat()
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            spotify_url = "https://open.spotify.com/playlist/0123456789?si=synthetic-locale"
            snapshot = {
                "documents": {
                    "richangji-state-v1": {
                        "settings": {
                            "dailyFlowNotes": {yesterday: "工作", today: "工作"},
                            "dailyFlowFocusTask": "工作",
                            "dailyFlowAudioUrl": spotify_url,
                        },
                        "records": [
                            {
                                "id": "locale-focus-task",
                                "type": "planner",
                                "date": today,
                                "data": {
                                    "title": "工作",
                                    "done": False,
                                    "list": "工作",
                                },
                            }
                        ],
                        "habits": [],
                        "mediaItems": [],
                    },
                    "wanxiang-issue-questions-v1": [
                        {"text": "工作", "createdDate": today, "createdAt": 10}
                    ],
                }
            }
            daily = DailyBridge(database, snapshot)
            planner = PlannerBridge(database, snapshot)
            qml_directory = Path(__file__).resolve().parents[1] / "qml"
            import_url = QUrl.fromLocalFile(str(qml_directory) + os.sep).toString()
            qml_path = temporary / "DailyFlowLocaleProbe.qml"
            qml_path.write_text(
                "import QtQuick\n"
                "import QtQuick.Controls\n"
                f'import "{import_url}" as Native\n'
                "ApplicationWindow {\n"
                "  visible: true; width: 1320; height: 1120\n"
                "  Native.DailyFlowPage {\n"
                '    objectName: "dailyFlowUnderTest"\n'
                "    anchors.fill: parent\n"
                "    controller: dailyController\n"
                "    plannerBridge: plannerController\n"
                "  }\n"
                "}\n",
                encoding="utf-8",
            )

            engine = QQmlApplicationEngine()
            localization = LocalizationBridge(
                LocalizationRepository(database), engine, self.app
            )
            engine.rootContext().setContextProperty("dailyController", daily)
            engine.rootContext().setContextProperty("plannerController", planner)
            try:
                engine.load(QUrl.fromLocalFile(str(qml_path)))
                self.assertTrue(engine.rootObjects(), "DailyFlowPage failed to load")
                window = engine.rootObjects()[0]
                window.show()
                QTest.qWait(100)
                page = window.findChild(QObject, "dailyFlowUnderTest")
                self.assertIsNotNone(page)

                def visual_item(object_name: str) -> QQuickItem | None:
                    pending = [page]
                    while pending:
                        item = pending.pop()
                        if item.objectName() == object_name:
                            return item
                        pending.extend(item.childItems())
                    return None

                def control(object_name: str) -> QObject:
                    item = window.findChild(QObject, object_name) or visual_item(object_name)
                    self.assertIsNotNone(item, f"missing QML object: {object_name}")
                    return item

                follow_up = control("dailyFollowUpInput")
                question = control("dailyQuestionInput")
                focus_name = control("dailyFocusTaskInput")
                spotify = control("dailySpotifyUrlInput")
                spotify_status = control("dailySpotifyDecisionStatus")
                focus_candidate = control("dailyFocusCandidateSelector")
                question_card_text = control("dailyQuestionText_0")
                reset_button = control("dailyFocusResetButton")
                add_question_button = control("dailyQuestionAddButton")
                status = control("dailyMailIntegrationStatus")
                notice = control("dailyFlowNoticeText")
                spotify_decision_note = next(
                    (
                        item
                        for item in window.findChildren(QObject)
                        if item.property("text") == daily.state["spotifyDecisionNote"]
                    ),
                    None,
                )
                self.assertIsNotNone(spotify_decision_note)
                spotify_player_hint_source = (
                    "链接保存在本机；播放器载入 Spotify 官方页面。登录状态、内容地区和网络连接可能影响播放。"
                )
                spotify_player_hint = next(
                    (
                        item
                        for item in window.findChildren(QObject)
                        if item.property("text") == spotify_player_hint_source
                    ),
                    None,
                )
                self.assertIsNotNone(spotify_player_hint)

                self.assertEqual(follow_up.property("text"), "工作")
                self.assertEqual(focus_name.property("text"), "工作")
                self.assertEqual(spotify.property("text"), spotify_url)
                self.assertEqual(focus_candidate.property("currentText"), "工作")
                self.assertEqual(question_card_text.property("text"), "工作")
                question.setProperty("text", "工作")
                page.setProperty("notice", "计时已重置。")
                QTest.qWait(40)

                result = localization.setLanguage("en_US")
                self.assertTrue(result["ok"], result)
                self.assertEqual(
                    follow_up.property("placeholderText"),
                    "For example: continue the item I didn't finish yesterday...",
                )
                self.assertEqual(
                    question.property("placeholderText"),
                    "Write down one thing you want to understand today",
                )
                self.assertEqual(
                    focus_name.property("placeholderText"),
                    "Enter a task for this focus session or the next step",
                )
                self.assertEqual(
                    spotify.property("placeholderText"),
                    "Spotify track, album, playlist, or podcast link",
                )
                self.assertEqual(spotify_status.property("text"), "Official Spotify player")
                self.assertEqual(
                    spotify_decision_note.property("text"),
                    "The current Native implementation keeps valid Spotify links and loads Spotify's official embedded player on the focus page. Sign-in status, regional availability, and network access can affect playback.",
                )
                self.assertEqual(
                    spotify_player_hint.property("text"),
                    "The link is saved on this device. The focus page loads Spotify's official player. Sign-in status, regional availability, and network access can affect playback.",
                )
                self.assertEqual(reset_button.property("text"), "Reset")
                self.assertEqual(
                    add_question_button.property("text"),
                    "Add to question book +",
                )
                self.assertEqual(status.property("text"), "Not connected")
                self.assertEqual(control("dailyFocusToggleButton").property("text"), "Start focus session")
                self.assertEqual(control("dailyYesterdayFollowUp").property("text"), "工作")
                self.assertEqual(follow_up.property("text"), "工作")
                self.assertEqual(question.property("text"), "工作")
                self.assertEqual(focus_name.property("text"), "工作")
                self.assertEqual(spotify.property("text"), spotify_url)
                self.assertEqual(focus_candidate.property("currentText"), "工作")
                self.assertEqual(question_card_text.property("text"), "工作")
                self.assertEqual(notice.property("text"), "Focus timer reset.")
                self.assertEqual(
                    daily.state["questions"][0]["text"],
                    "工作",
                    "the user-authored question remains unchanged",
                )

                result = localization.setLanguage("zh_CN")
                self.assertTrue(result["ok"], result)
                self.assertEqual(reset_button.property("text"), "重置")
                self.assertEqual(notice.property("text"), "计时已重置。")
                self.assertEqual(follow_up.property("text"), "工作")
                self.assertEqual(question.property("text"), "工作")
                self.assertEqual(focus_name.property("text"), "工作")
                self.assertEqual(spotify.property("text"), spotify_url)
            finally:
                localization.close()
                for root_object in engine.rootObjects():
                    root_object.close()
                engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
    def test_daily_flow_literal_sources_have_reviewed_translations(self) -> None:
        qml_path = Path(__file__).resolve().parents[1] / "qml" / "DailyFlowPage.qml"
        source = qml_path.read_text(encoding="utf-8")
        contextual = QML_CONTEXT_CATALOGS["DailyFlowPage"]
        literal_translation = re.compile(
            r'qsTr\(\s*"((?:\\.|[^"\\])*)"'
            r'(?:\s*,\s*"((?:\\.|[^"\\])*)")?'
        )
        missing: list[str] = []
        for match in literal_translation.finditer(source):
            source_text = json.loads('"' + match.group(1) + '"')
            disambiguation = (
                json.loads('"' + match.group(2) + '"') if match.group(2) else ""
            )
            if disambiguation and (
                "DailyFlowPage",
                source_text,
                disambiguation,
            ) in QML_DISAMBIGUATED_CATALOGS:
                continue
            if source_text not in contextual and source_text not in ENGLISH_CATALOG:
                line = source.count("\n", 0, match.start()) + 1
                missing.append(f"DailyFlowPage.qml:{line}: {source_text}")
        self.assertEqual(missing, [])

    def test_all_literal_qml_translation_sources_have_a_reviewed_translation(self) -> None:
        qml_directory = Path(__file__).resolve().parents[1] / "qml"
        literal_translation = re.compile(
            r'qsTr\(\s*"((?:\\.|[^"\\])*)"'
            r'(?:\s*,\s*"((?:\\.|[^"\\])*)")?'
        )
        missing: list[str] = []
        for qml_path in sorted(qml_directory.glob("*.qml")):
            context = qml_path.stem
            contextual = QML_CONTEXT_CATALOGS.get(context, {})
            source = qml_path.read_text(encoding="utf-8")
            for match in literal_translation.finditer(source):
                source_text = json.loads('"' + match.group(1) + '"')
                disambiguation = (
                    json.loads('"' + match.group(2) + '"')
                    if match.group(2)
                    else ""
                )
                if disambiguation and (
                    context,
                    source_text,
                    disambiguation,
                ) in QML_DISAMBIGUATED_CATALOGS:
                    continue
                if source_text not in contextual and source_text not in ENGLISH_CATALOG:
                    line = source.count("\n", 0, match.start()) + 1
                    missing.append(f"{qml_path.name}:{line}: {source_text}")
        self.assertEqual(missing, [])

    def test_production_weather_card_localizes_ui_and_preserves_dynamic_weather(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "weather-locale.sqlite3"
            native_directory = Path(__file__).resolve().parents[1]
            engine = QQmlApplicationEngine()
            qml_warnings: list[str] = []
            engine.warnings.connect(lambda errors: qml_warnings.extend(error.toString() for error in errors))
            localization = LocalizationBridge(
                LocalizationRepository(database), engine, self.app
            )

            cleanup_done = False

            def dispose_engine() -> None:
                nonlocal cleanup_done
                if cleanup_done:
                    return
                cleanup_done = True
                localization.close()
                for root_object in engine.rootObjects():
                    root_object.close()
                engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

            self.addCleanup(dispose_engine)
            migration = MigrationBridge(database)
            snapshot = migration.data
            finance = FinanceBridge(database, snapshot)
            controllers = {
                "migrationController": migration,
                "weatherController": WeatherBridge(database, snapshot),
                "newsController": NewsBridge(database, snapshot),
                "habitController": HabitBridge(database, snapshot),
                "preferencesController": IssuePreferencesBridge(database, snapshot),
                "readingController": ReadingBridge(database, snapshot),
                "dailyController": DailyBridge(database, snapshot),
                "financeController": finance,
                "backupController": BackupBridge(database, finance),
                "fitnessController": FitnessBridge(database, snapshot),
                "plannerController": PlannerBridge(database, snapshot),
                "shoppingController": ShoppingBridge(database, snapshot),
                "mediaController": MediaBridge(database, snapshot),
                "archiveController": ArchiveBridge(database, snapshot),
                "converterController": ConverterBridge(),
                "converterEngineController": ConverterEngineUpdateBridge(Path(directory) / "engine-updates"),
                "brandController": BrandBridge(BrandRepository(database), engine),
                "localeController": localization,
            }
            weather = controllers["weatherController"]
            engine.setInitialProperties(controllers)
            engine.load(QUrl.fromLocalFile(str(native_directory / "qml" / "Main.qml")))
            self.assertTrue(engine.rootObjects(), f"production Main.qml failed to load: {qml_warnings}")
            window = engine.rootObjects()[0]
            window.show()
            QTest.qWait(120)

            def control(object_name: str) -> QObject:
                item = window.findChild(QObject, object_name)
                self.assertIsNotNone(item, f"missing QML object: {object_name}")
                return item

            title = control("dailyOverviewTitle")
            subtitle = control("dailyOverviewSubtitle")
            issue_slogan = control("dailyIssueSlogan")
            issue_description = control("dailyIssueDescription")
            issue_counts = control("newsIssueCounts")
            city = control("weatherCityLabel")
            condition = control("weatherConditionText")
            weather_icon = control("weatherConditionIcon")
            temperature_value = control("weatherTemperatureText")
            status = control("weatherStatusLabel")
            details = control("weatherDetailsToggle")
            apparent = control("weatherApparentLabel")
            temperature_range = control("weatherRangeLabel")
            metrics = control("weatherMetricsLabel")
            city_input = control("weatherCityInput")
            query_button = control("queryWeatherButton")
            locate_button = control("weatherLocateButton")
            location_settings = control("weatherLocationSettingsButton")
            privacy_note = control("weatherLocationPrivacyNote")
            error_text = control("weatherErrorText")

            self.assertEqual(weather_icon.property("name"), "location")
            self.assertEqual(temperature_value.property("text"), "—")
            self.assertFalse(temperature_value.property("visible"))
            self.assertFalse(issue_counts.property("visible"))

            weather._publish(
                city="合成市",
                busy=False,
                status="天气已更新。",
                condition="局部多云",
                conditionEnglish="Partly cloudy",
                glyph="☁",
                temperature=21,
                apparentTemperature=20,
                lowTemperature=17,
                highTemperature=25,
                humidity=60,
                windSpeed=8,
                rainChance=10,
            )
            QTest.qWait(40)
            self.assertEqual(title.property("text"), "今日速览")
            self.assertEqual(subtitle.property("text"), "先了解天气与值得关注的变化")
            self.assertEqual(city.property("text"), "合成市")
            self.assertEqual(condition.property("text"), "局部多云")
            self.assertEqual(weather_icon.property("name"), "cloud")
            self.assertEqual(temperature_value.property("text"), "21°")
            self.assertTrue(temperature_value.property("visible"))
            self.assertEqual(status.property("text"), "天气已更新。")
            self.assertEqual(details.property("text"), "详情")
            self.assertEqual(apparent.property("text"), "体感 20°")
            self.assertEqual(temperature_range.property("text"), "今日 17° / 25°")
            self.assertEqual(metrics.property("text"), "湿度 60% · 风 8 km/h · 降水 10%")
            self.assertEqual(city_input.property("placeholderText"), "城市名或“城市, 省/国家”")
            self.assertEqual(query_button.property("text"), "查询天气")
            self.assertEqual(locate_button.property("text"), "使用当前位置")
            self.assertEqual(location_settings.property("text"), "系统位置设置")
            self.assertEqual(privacy_note.property("text"), "仅保存约 0.1° 精度的位置；也可手动输入城市。")
            self.assertFalse(error_text.property("visible"))

            result = localization.setLanguage("en_US")
            self.assertTrue(result["ok"], result)
            self.assertEqual(title.property("text"), "Today at a glance")
            self.assertEqual(subtitle.property("text"), "Start with the weather and noteworthy changes")
            self.assertEqual(issue_slogan.property("text"), "See the world, then take care of today.")
            self.assertEqual(
                issue_description.property("text"),
                "Bring weather, industry updates, yesterday's reflection, and today's work into one daily letter.",
            )
            self.assertEqual(city.property("text"), "合成市")
            self.assertEqual(condition.property("text"), "Partly cloudy")
            self.assertEqual(status.property("text"), "Weather updated.")
            self.assertEqual(details.property("text"), "Details")
            self.assertEqual(apparent.property("text"), "Feels like 20°")
            self.assertEqual(temperature_range.property("text"), "Today 17° / 25°")
            self.assertEqual(metrics.property("text"), "Humidity 60% · Wind 8 km/h · Precipitation 10%")
            self.assertEqual(city_input.property("placeholderText"), "City or “city, region/country”")
            self.assertEqual(query_button.property("text"), "Get weather")
            self.assertEqual(locate_button.property("text"), "Use current location")
            self.assertEqual(location_settings.property("text"), "Location settings")
            self.assertIn("0.1°", privacy_note.property("text"))
            self.assertEqual(error_text.property("visible"), False)

            weather._publish(
                busy=True,
                status="正在查询城市天气……",
                condition="",
                conditionEnglish="",
            )
            QTest.qWait(40)
            self.assertEqual(status.property("text"), "Searching")
            self.assertEqual(condition.property("text"), "Getting weather…")
            self.assertEqual(query_button.property("text"), "Searching…")

            weather._publish(
                busy=False,
                status="城市查询服务暂不可用，请检查网络后重试。",
                condition="合成天气描述",
                conditionEnglish="",
            )
            QTest.qWait(40)
            self.assertEqual(status.property("text"), "Lookup failed")
            self.assertEqual(
                error_text.property("text"),
                "The city search service is unavailable. Check the network and try again.",
            )
            self.assertEqual(city.property("text"), "合成市")
            self.assertEqual(condition.property("text"), "合成天气描述")

            weather._publish(
                busy=False,
                status="没有找到“合成市”，请检查城市名称或尝试输入拼音。",
                condition="",
                conditionEnglish="",
            )
            QTest.qWait(40)
            self.assertEqual(
                error_text.property("text"),
                "没有找到“合成市”，请检查城市名称或尝试输入拼音。",
                "dynamic city-specific error text is intentionally preserved",
            )

            window.setProperty("currentSectionIndex", 1)
            QTest.qWait(40)
            finance_alert = control("financeAlert")
            result = localization.setLanguage("zh_CN")
            self.assertTrue(result["ok"], result)
            self.assertEqual(
                finance_alert.property("text"),
                "今天尚无账目；本月统计仅包含已记录的数据。",
            )
            result = localization.setLanguage("en_US")
            self.assertTrue(result["ok"], result)
            self.assertEqual(
                finance_alert.property("text"),
                "No transactions recorded today; monthly totals include recorded entries only.",
            )
            self.assertEqual(control("financeBudgetLabel").property("text"), "Budget amount for this month")
            self.assertEqual(control("financeFlowLabel").property("text"), "Type")
            self.assertEqual(control("financeAmountLabel").property("text"), "Amount")
            self.assertEqual(control("financeCategoryLabel").property("text"), "Category")
            self.assertEqual(control("financeDateLabel").property("text"), "Date")
            self.assertEqual(control("financeNoteLabel").property("text"), "Note")
            added_expense = finance.addRecord("expense", "36", "吃饭", date.today().isoformat(), "合成支出")
            self.assertTrue(added_expense["ok"], added_expense)
            QTest.qWait(120)
            finance_page = control("financePage")
            self.assertTrue(control("financeSpendingStructure").property("visible"))
            self.assertIsNone(window.findChild(QObject, "financeSpendingPie"))
            category_rows = finance_page.property("categoryRows").toVariant()
            self.assertEqual(len(category_rows), 1)
            self.assertEqual(category_rows[0]["category"], "吃饭")
            self.assertEqual(category_rows[0]["share"], 1.0)
            self.assertEqual(category_rows[0]["amount"], 36)

            window.setProperty("currentSectionIndex", 5)
            QTest.qWait(40)
            self.assertFalse(control("shoppingInsightPanel").property("visible"))
            dispose_engine()

    def test_production_news_workbench_localizes_static_ui_and_preserves_user_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "news-locale.sqlite3"
            native_directory = Path(__file__).resolve().parents[1]
            engine = QQmlApplicationEngine()
            localization = LocalizationBridge(
                LocalizationRepository(database), engine, self.app
            )

            def dispose_engine() -> None:
                localization.close()
                for root_object in engine.rootObjects():
                    root_object.close()
                engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

            self.addCleanup(dispose_engine)
            migration = MigrationBridge(database)
            snapshot = migration.data
            finance = FinanceBridge(database, snapshot)
            news = NewsBridge(database, snapshot)
            user_topic = "用户主题原文"
            user_title = "用户标题原文"
            user_summary = "用户摘要原文"
            user_body = "用户正文原文"
            user_publisher = "用户来源原文"
            user_url = "https://news.example.org/locale-original"
            issue = {
                "version": 1,
                "date": "2026-09-28",
                "topic": user_topic,
                "focus": [
                    {
                        "id": "locale-user-article",
                        "label": "用户栏目原文",
                        "title": user_title,
                        "summary": user_summary,
                        "body": [user_body],
                        "publisher": user_publisher,
                        "publishedAt": "2026-09-28T08:00:00Z",
                        "sourceUrl": user_url,
                    }
                ],
                "highlights": [
                    {
                        "id": "locale-user-highlight",
                        "label": "用户快讯栏目原文",
                        "title": "用户快讯标题原文",
                        "summary": "用户快讯摘要原文",
                        "body": ["用户快讯正文原文"],
                        "publisher": "用户快讯来源原文",
                        "publishedAt": "2026-09-28T08:05:00Z",
                        "sourceUrl": "https://news.example.org/highlight-original",
                    }
                ],
                "articles": [],
            }
            preview_result = news.previewJson(json.dumps(issue, ensure_ascii=False))
            self.assertTrue(preview_result["ok"], preview_result)

            controllers = {
                "migrationController": migration,
                "weatherController": WeatherBridge(database, snapshot),
                "newsController": news,
                "habitController": HabitBridge(database, snapshot),
                "preferencesController": IssuePreferencesBridge(database, snapshot),
                "readingController": ReadingBridge(database, snapshot),
                "dailyController": DailyBridge(database, snapshot),
                "financeController": finance,
                "backupController": BackupBridge(database, finance),
                "fitnessController": FitnessBridge(database, snapshot),
                "plannerController": PlannerBridge(database, snapshot),
                "shoppingController": ShoppingBridge(database, snapshot),
                "mediaController": MediaBridge(database, snapshot),
                "archiveController": ArchiveBridge(database, snapshot),
                "converterController": ConverterBridge(),
                "converterEngineController": ConverterEngineUpdateBridge(Path(directory) / "engine-updates"),
                "brandController": BrandBridge(BrandRepository(database), engine),
                "localeController": localization,
            }
            engine.setInitialProperties(controllers)
            engine.load(QUrl.fromLocalFile(str(native_directory / "qml" / "Main.qml")))
            self.assertTrue(engine.rootObjects(), "production Main.qml failed to load")
            window = engine.rootObjects()[0]
            window.resize(1480, 1100)
            window.show()
            QTest.qWait(120)

            def control(object_name: str) -> QObject:
                item = window.findChild(QObject, object_name)
                self.assertIsNotNone(item, f"missing QML object: {object_name}")
                assert item is not None
                return item

            def click(object_name: str) -> QObject:
                button = control(object_name)
                self.assertTrue(
                    QMetaObject.invokeMethod(
                        button, "click", Qt.ConnectionType.DirectConnection
                    ),
                    f"QML button {object_name} did not expose click()",
                )
                QTest.qWait(80)
                return button

            news_card = control("newsCard")
            issue_counts = control("newsIssueCounts")
            self.assertTrue(issue_counts.property("visible"))
            self.assertFalse(news_card.property("workspaceExpanded"))
            click("newsWorkspaceExpandButton")
            self.assertTrue(news_card.property("workspaceExpanded"))
            workspace_header = control("newsWorkspaceHeader")
            drop_hint = control("newsWorkspaceDropHint")
            self.assertEqual(news.state["draft"]["topic"], user_topic)

            click("newsPasteButton")
            json_instruction = control("newsJsonInstruction")
            json_input = control("newsJsonInput")
            result = localization.setLanguage("en_US")
            self.assertTrue(result["ok"], result)
            self.assertEqual(
                workspace_header.property("text"),
                "NEWS SCOPE · Local issue workspace",
            )
            self.assertEqual(control("newsWorkspaceCollapseButton").property("text"), "Close workspace")
            self.assertEqual(
                drop_hint.property("text"),
                "Drop a .json file to preview it, or drop an HTTP(S) link into the local link inbox. Links are not fetched or published.",
            )
            self.assertEqual(control("newsPasteButton").property("text"), "Edit / paste JSON")
            self.assertEqual(
                json_instruction.property("text"),
                "The current draft is loaded in the text box. Preview your changes before saving or publishing.",
            )
            self.assertEqual(
                json_input.property("placeholderText"),
                "Paste a JSON package with version, date, topic, focus, and highlights.",
            )
            for user_value in (user_title, user_summary, user_body, user_publisher, user_url):
                self.assertIn(user_value, json_input.property("text"))

            click("newsPreviewButton")
            QTest.qWait(300)
            replace_dialog = control("newsPreviewReplaceDialog")
            self.assertTrue(
                replace_dialog.property("visible"),
                "previewing new JSON must ask before replacing an unsaved draft",
            )
            click("newsPreviewReplaceConfirmButton")
            QTest.qWait(300)
            preview_dialog = control("newsPreviewDialog")
            self.assertTrue(
                preview_dialog.property("visible"),
                f"news preview dialog did not open; state={news.state}",
            )
            news_card = control("newsCard")
            self.assertTrue(
                news_card.property("previewIssue"),
                f"preview issue is empty; state={news.state}",
            )
            safety_note = control("newsPreviewSafetyNote")
            self.assertEqual(
                safety_note.property("text"),
                "This is an unpublished preview. Closing this window will not save it. Choose Save draft or Publish to continue.",
            )
            preview_issue = news_card.property("previewIssue")
            self.assertEqual(preview_issue["topic"], user_topic)
            self.assertEqual(preview_issue["focus"][0]["title"], user_title)
            self.assertEqual(preview_issue["focus"][0]["summary"], user_summary)
            self.assertEqual(preview_issue["focus"][0]["body"], [user_body])
            self.assertEqual(preview_issue["focus"][0]["publisher"], user_publisher)
            self.assertEqual(preview_issue["focus"][0]["sourceUrl"], user_url)
            click("newsPreviewSaveDraftButton")
            notice = control("newsWorkspaceNotice")
            self.assertEqual(notice.property("text"), "Draft saved on this device.")

            result = localization.setLanguage("zh_CN")
            self.assertTrue(result["ok"], result)
            self.assertEqual(workspace_header.property("text"), "NEWS SCOPE · 本机刊期工作台")
            self.assertEqual(notice.property("text"), "草稿已保存到本机。")
            self.assertEqual(news.state["draft"]["topic"], user_topic)
            self.assertEqual(news.state["draft"]["focus"][0]["title"], user_title)
            self.assertEqual(news.state["draft"]["focus"][0]["summary"], user_summary)
            self.assertEqual(news.state["draft"]["focus"][0]["body"], [user_body])
            self.assertEqual(news.state["draft"]["focus"][0]["publisher"], user_publisher)
            self.assertEqual(news.state["draft"]["focus"][0]["sourceUrl"], user_url)

    def test_qml_retranslates_live_and_uses_persisted_language(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "locale.sqlite3"
            qml_path = Path(directory) / "LocaleProbe.qml"
            qml_path.write_text(
                'import QtQuick\nText { objectName: "localeLabel"; '
                'text: qsTr("工作台外观"); '
                'property string fallbackText: qsTr("尚未覆盖的词条") }\n',
                encoding="utf-8",
            )
            engine = QQmlApplicationEngine()
            bridge = LocalizationBridge(
                LocalizationRepository(database), engine, self.app
            )
            component = QQmlComponent(engine)
            component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
            root = component.create()
            if root is None:
                errors = "\n".join(error.toString() for error in component.errors())
                bridge.close()
                engine.deleteLater()
                self.fail(f"Could not create localization probe QML: {errors}")

            try:
                self.assertEqual(root.property("text"), "工作台外观")
                result = bridge.setLanguage("en_US")
                self.assertTrue(result["ok"], result)
                self.assertEqual(root.property("text"), "Workspace appearance")
                self.assertEqual(root.property("fallbackText"), "尚未覆盖的词条")
                self.assertEqual(LocalizationRepository(database).language(), "en_US")

                bridge.close()
                restored = LocalizationBridge(
                    LocalizationRepository(database), engine, self.app
                )
                try:
                    engine.retranslate()
                    self.assertEqual(root.property("text"), "Workspace appearance")
                    restored.setLanguage("zh_CN")
                    self.assertEqual(root.property("text"), "工作台外观")
                finally:
                    restored.close()
            finally:
                root.deleteLater()
                component.deleteLater()
                engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

    def test_appearance_dialog_changes_language_without_saving_brand_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            database = temporary / "locale.sqlite3"
            qml_directory = Path(__file__).resolve().parents[1] / "qml"
            qml_path = temporary / "AppearanceLocaleProbe.qml"
            import_url = QUrl.fromLocalFile(str(qml_directory) + os.sep).toString()
            qml_path.write_text(
                'import QtQuick\n'
                'import QtQuick.Controls\n'
                f'import "{import_url}" as Native\n'
                'ApplicationWindow {\n'
                '  visible: true; width: 640; height: 800\n'
                '  Native.BrandAppearanceDialog {\n'
                '    objectName: "appearanceDialog"\n'
                '    localeController: localeControllerRef\n'
                '    Component.onCompleted: open()\n'
                '  }\n'
                '}\n',
                encoding="utf-8",
            )
            engine = QQmlApplicationEngine()
            bridge = LocalizationBridge(
                LocalizationRepository(database), engine, self.app
            )
            engine.rootContext().setContextProperty("localeControllerRef", bridge)
            engine.load(QUrl.fromLocalFile(str(qml_path)))
            if not engine.rootObjects():
                bridge.close()
                engine.deleteLater()
                self.fail("Could not load appearance locale probe QML")
            window = engine.rootObjects()[0]
            language_label = window.findChild(QObject, "uiLanguageLabel")
            selector = window.findChild(QObject, "uiLanguageSelector")
            try:
                self.assertIsNotNone(language_label)
                self.assertIsNotNone(selector)
                QTest.qWait(80)
                self.assertEqual(language_label.property("text"), "界面语言")
                self.assertEqual(selector.property("displayText"), "简体中文 / Chinese")
                result = bridge.setLanguage("en_US")
                self.assertTrue(result["ok"], result)
                self.assertEqual(language_label.property("text"), "Interface language")
                self.assertEqual(
                    selector.property("displayText"),
                    "English",
                    "index=%r currentValue=%r language=%s"
                    % (
                        selector.property("currentIndex"),
                        selector.property("currentValue"),
                        bridge.language,
                    ),
                )
                self.assertEqual(LocalizationRepository(database).language(), "en_US")
                connection = sqlite3.connect(database)
                try:
                    saved_keys = connection.execute(
                        "SELECT key FROM app_settings ORDER BY key"
                    ).fetchall()
                finally:
                    connection.close()
                self.assertEqual(saved_keys, [("uiLanguage",)])
            finally:
                bridge.close()
                window.close()
                engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

    def test_article_reader_translates_ui_and_preserves_article_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            qml_directory = Path(__file__).resolve().parents[1] / "qml"
            qml_path = temporary / "ArticleLocaleProbe.qml"
            import_url = QUrl.fromLocalFile(str(qml_directory) + os.sep).toString()
            qml_path.write_text(
                'import QtQuick\n'
                'import QtQuick.Controls\n'
                f'import "{import_url}" as Native\n'
                'ApplicationWindow {\n'
                '  visible: true; width: 720; height: 900\n'
                '  Native.ArticleDialog {\n'
                '    objectName: "articleDialogLocaleProbe"\n'
                '    article: ({ id: "synthetic-locale-article", title: "合成文章标题", '
                'body: ["这段合成正文保持原文。"], sourceUrl: "https://example.com/article" })\n'
                '    Component.onCompleted: open()\n'
                '  }\n'
                '}\n',
                encoding="utf-8",
            )
            database = temporary / "locale.sqlite3"
            engine = QQmlApplicationEngine()
            bridge = LocalizationBridge(
                LocalizationRepository(database), engine, self.app
            )
            component = QQmlComponent(engine)
            component.loadUrl(QUrl.fromLocalFile(str(qml_path)))
            window = component.create()
            if window is None:
                errors = "\n".join(error.toString() for error in component.errors())
                bridge.close()
                engine.deleteLater()
                self.fail(f"Could not create article locale probe QML: {errors}")

            dialog = window.findChild(QObject, "articleDialogLocaleProbe")
            original_button = window.findChild(QObject, "articleDialogOriginalLinkButton")
            read_later_button = window.findChild(QObject, "articleDialogSavedKnowledgeButton")
            helpful_button = window.findChild(QObject, "articleFeedback_useful")
            try:
                self.assertIsNotNone(dialog)
                self.assertIsNotNone(original_button)
                self.assertIsNotNone(read_later_button)
                self.assertIsNotNone(helpful_button)
                QTest.qWait(80)
                self.assertEqual(dialog.property("title"), "文章阅读")
                self.assertEqual(original_button.property("text"), "打开原始报道 ↗")
                self.assertEqual(read_later_button.property("text"), "开启全局稍后读 +")
                self.assertEqual(dialog.property("headline"), "合成文章标题")

                result = bridge.setLanguage("en_US")
                self.assertTrue(result["ok"], result)
                self.assertEqual(dialog.property("title"), "Article reader")
                self.assertEqual(original_button.property("text"), "Open original article ↗")
                self.assertEqual(read_later_button.property("text"), "Save for later +")
                self.assertEqual(helpful_button.property("text"), "Helpful")
                self.assertEqual(dialog.property("headline"), "合成文章标题")
                self.assertEqual(
                    dialog.property("bodyParagraphs").toVariant(),
                    ["这段合成正文保持原文。"],
                )
            finally:
                bridge.close()
                window.close()
                window.deleteLater()
                component.deleteLater()
                engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
