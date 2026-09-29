from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Q_ARG, Property, QMetaObject, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QJSValue, QQmlApplicationEngine

from main import (
    ArchiveBridge,
    BackupBridge,
    DailyBridge,
    FinanceBridge,
    FitnessBridge,
    HabitBridge,
    HomeLayoutBridge,
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
from wanxiang.finance import FinanceRepository
from wanxiang.localization import LocalizationBridge, LocalizationRepository
from wanxiang.news_import import parse_issue_json


def _issue() -> dict[str, object]:
    article = {
        "id": "synthetic-qml-article-1",
        "label": "合成栏目",
        "title": "仅用于 QML 集成验收的合成文章",
        "summary": "用于验证生产界面读者和本机保存操作。",
        "body": ["第一段合成正文。", "第二段合成正文。"],
        "publisher": "合成来源",
        "publishedAt": "2026-09-28",
        "sourceTitle": "合成原始标题",
        "sourceUrl": "https://news.example.com/synthetic-qml-article",
        "relatedCoverage": [
            {
                "publisher": "关联合成来源",
                "title": "合成关联报道",
                "publishedAt": "2026-09-27",
                "summary": "关联报道说明。",
                "sourceUrl": "https://news.example.com/related",
            }
        ],
        "updates": [
            {
                "date": "2026-09-28",
                "summary": "合成事件进展。",
                "publisher": "进展合成来源",
                "sourceUrl": "https://news.example.com/update",
            }
        ],
    }
    return {
        "version": 1,
        "date": "2026-09-28",
        "topic": "合成 UI 验收主题",
        "editorNote": "仅供本机测试。",
        "focus": [article],
        "highlights": [
            {
                "id": "synthetic-qml-highlight-1",
                "label": "合成快讯",
                "title": "仅用于刊期结构的快讯",
                "summary": "合成摘要。",
                "body": ["合成内容。"],
                "publisher": "合成来源",
                "publishedAt": "2026-09-28",
                "sourceUrl": "https://news.example.com/synthetic-highlight",
            }
        ],
        "articles": [],
    }


class FakeHomeLayoutBridge(QObject):
    """Small stateful bridge for production Main.qml layout integration."""

    stateChanged = Signal()

    def __init__(self, layout: dict[str, object] | None = None) -> None:
        super().__init__()
        self.fail_next_save = False
        self.saved_layout = json.loads(json.dumps(layout or {
            "order": [
                "question-desk", "habits", "quick", "lead", "briefs", "weekly", "recent",
                "retained-unknown",
            ],
            "slots": {
                "lead": "flow-briefing-slot",
                "briefs": "flow-briefing-slot",
                "weekly": "flow-review-slot",
                "recent": "flow-review-slot",
                "question-desk": "flow-review-slot",
                "habits": "flow-work-slot",
                "quick": "flow-work-slot",
                "retained-unknown": "legacy-slot-3",
            },
            "hidden": [],
            "unknownMetadata": {"keep": "through-toggle"},
        }))

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        return {"layout": json.loads(json.dumps(self.saved_layout))}

    @Slot("QVariant", result="QVariant")
    def saveLayout(self, layout: object) -> dict[str, object]:
        if self.fail_next_save:
            self.fail_next_save = False
            return {"ok": False, "error": "synthetic write failure"}
        if isinstance(layout, QJSValue):
            layout = layout.toVariant()
        self.saved_layout = json.loads(json.dumps(layout))
        self.stateChanged.emit()
        return {"ok": True, "layout": json.loads(json.dumps(self.saved_layout))}


class NewsWorkflowQmlIntegrationTests(unittest.TestCase):
    """Exercise production Main.qml news workflows using isolated local data."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.native_dir = Path(__file__).resolve().parents[1]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-news-workflow-qml-")
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)
        self.database_path = self.temp_path / "synthetic.sqlite3"
        self.engine = QQmlApplicationEngine()
        self.addCleanup(self._destroy_engine)

        migration = MigrationBridge(self.database_path)
        snapshot = migration.data
        self.news = NewsBridge(self.database_path, snapshot)
        preview = self.news.previewJson(json.dumps(_issue(), ensure_ascii=False))
        self.assertTrue(preview["ok"], preview)
        self.assertTrue(self.news.publishDraft()["ok"])
        finance = FinanceBridge(self.database_path, snapshot)
        self.preferences = IssuePreferencesBridge(self.database_path, snapshot)
        self.reading = ReadingBridge(self.database_path, snapshot)
        self.home_layout = FakeHomeLayoutBridge()
        self.controllers = {
            "migrationController": migration,
            "weatherController": WeatherBridge(self.database_path, snapshot),
            "newsController": self.news,
            "habitController": HabitBridge(self.database_path, snapshot),
            "preferencesController": self.preferences,
            "readingController": self.reading,
            "dailyController": DailyBridge(self.database_path, snapshot),
            "financeController": finance,
            "backupController": BackupBridge(self.database_path, finance),
            "fitnessController": FitnessBridge(self.database_path, snapshot),
            "plannerController": PlannerBridge(self.database_path, snapshot),
            "shoppingController": ShoppingBridge(self.database_path, snapshot),
            "mediaController": MediaBridge(self.database_path, snapshot),
            "archiveController": ArchiveBridge(self.database_path, snapshot),
            "converterController": ConverterBridge(),
            "converterEngineController": ConverterEngineUpdateBridge(self.temp_path / "engine-updates"),
            "brandController": BrandBridge(BrandRepository(self.database_path), self.engine),
            "homeLayoutController": self.home_layout,
        }
        self.engine.setInitialProperties(self.controllers)
        self.engine.load(QUrl.fromLocalFile(str(self.native_dir / "qml" / "Main.qml")))
        self.assertTrue(self.engine.rootObjects(), "production Main.qml failed to load")
        self.window = self.engine.rootObjects()[0]
        self.window.resize(1480, 960)
        self.window.show()
        QTest.qWait(160)
        self.news_card = self.window.findChild(QObject, "newsCard")
        self.assertIsNotNone(self.news_card)

    def _destroy_engine(self) -> None:
        if getattr(self, "engine", None) is not None:
            self.engine.deleteLater()
            QTest.qWait(30)

    def _visual_item(self, object_name: str) -> QQuickItem | None:
        root_item = self.window.property("contentItem")
        pending = [root_item] if isinstance(root_item, QQuickItem) else []
        for obj in self.window.findChildren(QObject):
            if isinstance(obj, QQuickItem):
                pending.append(obj)
            if obj.metaObject().indexOfProperty("contentItem") >= 0:
                content_item = obj.property("contentItem")
                if isinstance(content_item, QQuickItem):
                    pending.append(content_item)
        while pending:
            item = pending.pop()
            if item.objectName() == object_name:
                return item
            pending.extend(item.childItems())
        return None

    def _control(self, object_name: str) -> QObject:
        control = next(
            (
                item
                for item in self.window.findChildren(QObject)
                if item.objectName() == object_name
            ),
            None,
        )
        if control is None:
            control = self._visual_item(object_name)
        if control is None:
            # Popup footer/content items may be parented below the popup rather
            # than the application window in offscreen Qt Quick runs.
            for popup_name in ("newsPreviewDialog", "newsPublishConfirmDialog"):
                popup = self.window.findChild(QObject, popup_name)
                if popup is not None:
                    control = next(
                        (child for child in popup.findChildren(QObject)
                         if child.objectName() == object_name),
                        None,
                    )
                    if control is None:
                        footer = popup.property("footer")
                        if isinstance(footer, QObject):
                            control = next(
                                (child for child in footer.findChildren(QObject)
                                 if child.objectName() == object_name),
                                None,
                            )
                    if control is not None:
                        break
        self.assertIsNotNone(control, f"production QML control {object_name} was not found")
        assert control is not None
        return control

    def _click(self, object_name: str) -> QObject:
        control = self._control(object_name)
        self.assertTrue(
            QMetaObject.invokeMethod(control, "click", Qt.ConnectionType.DirectConnection),
            f"production QML control {object_name} did not expose click()",
        )
        QTest.qWait(40)
        return control

    def _home_layout_slot_children(self, slot_id: str) -> list[str]:
        flow = self._control("homeLayoutCards_" + slot_id)
        self.assertIsInstance(flow, QQuickItem)
        assert isinstance(flow, QQuickItem)
        return [child.objectName() for child in flow.childItems()]

    def _home_layout_slot_visual_order(self, slot_id: str) -> list[str]:
        flow = self._control("homeLayoutCards_" + slot_id)
        self.assertIsInstance(flow, QQuickItem)
        assert isinstance(flow, QQuickItem)
        visible_cards = [child for child in flow.childItems() if child.isVisible()]
        visible_cards.sort(key=lambda child: float(child.y()))
        return [child.objectName() for child in visible_cards]

    def test_preferences_prompt_copy_and_active_issue_export_handlers(self) -> None:
        legacy_result = self.preferences.save(
            ["future-topic"],
            {"subtopics": "", "sources": "", "presetSources": []},
        )
        self.assertTrue(legacy_result["ok"], legacy_result)
        self._click("newsWorkspaceMoreButton")
        self._click("newsPreferencesButton")
        preferences_dialog = self._control("preferencesDialog")
        self.assertTrue(preferences_dialog.property("opened"))
        legacy_hint = self._control("unlistedTopicsHint")
        self.assertTrue(legacy_hint.property("visible"))
        self.assertIn("不会删除新闻或历史内容", legacy_hint.property("text"))
        self._click("unlistedTopicRemove_0")
        self.assertFalse(legacy_hint.property("visible"))

        topic = self._control("topicCheckBox_ai")
        self.assertFalse(topic.property("checked"))
        self._click("topicCheckBox_ai")
        source = self._control("presetSourceCheckBox_4")  # Reuters
        self.assertEqual(source.property("text"), "Reuters")
        self._click("presetSourceCheckBox_4")

        subtopics = self._control("subtopicsField")
        subtopics.setProperty("text", "AI agents and independent games")
        self.assertTrue(
            QMetaObject.invokeMethod(subtopics, "textEdited", Qt.ConnectionType.DirectConnection)
        )
        custom_sources = self._control("customSourcesField")
        custom_sources.setProperty("text", "Science; Example Research")
        self.assertTrue(
            QMetaObject.invokeMethod(custom_sources, "textEdited", Qt.ConnectionType.DirectConnection)
        )
        self._click("preferencesSaveButton")

        state = self.preferences.state
        self.assertEqual(state["topics"], ["ai"])
        self.assertEqual(state["preferences"]["presetSources"], ["Reuters"])
        self.assertEqual(state["preferences"]["subtopics"], "AI agents and independent games")
        self.assertEqual(state["preferences"]["sources"], "Science、Example Research")
        self.assertFalse(preferences_dialog.property("opened"))

        class ClipboardCapture:
            text: str | None = None

            def setText(self, text: str) -> None:
                self.text = text

        clipboard = ClipboardCapture()
        with patch("main.QApplication") as application:
            application.clipboard.return_value = clipboard
            self._click("newsCopyPromptButtonWorkspace")

        self.assertIsNotNone(clipboard.text, "copy handler did not write prompt text")
        assert clipboard.text is not None
        self.assertIn("- ai：人工智能", clipboard.text)
        self.assertIn("- 自定义方向：AI agents and independent games", clipboard.text)
        self.assertIn("- Reuters", clipboard.text)
        self.assertIn("- 自定义候选媒体：Science、Example Research", clipboard.text)
        self.assertIn("新闻生成提示已复制", self.news_card.property("notice"))
        self.assertFalse(self.news_card.property("noticeIsError"))

        export_button = self._control("newsExportIssueButtonWorkspace")
        self.assertTrue(export_button.property("enabled"))
        export_dialog = self._control("newsExportDialog")
        destination = self.temp_path / "qml-export.json"
        export_dialog.setProperty("selectedFile", QUrl.fromLocalFile(str(destination)))
        self.assertTrue(
            QMetaObject.invokeMethod(export_dialog, "accepted", Qt.ConnectionType.DirectConnection),
            "production FileDialog accepted handler was not invokable",
        )
        self.assertTrue(destination.is_file())
        parsed = parse_issue_json(destination.read_bytes())
        self.assertEqual(parsed["topic"], "合成 UI 验收主题")
        self.assertEqual(parsed["focus"][0]["id"], "synthetic-qml-article-1")
        self.assertIn("本期 JSON 已导出", self.news_card.property("notice"))

    def test_english_invalid_news_json_error_keeps_position_and_draft(self) -> None:
        draft = json.loads(json.dumps(_issue()))
        draft["topic"] = "待保留的合成草稿"
        draft["focus"][0]["title"] = "不可被失败预览覆盖的合成标题"
        self.assertTrue(self.news.previewJson(json.dumps(draft, ensure_ascii=False))["ok"])
        self.assertTrue(self.news.saveDraft()["ok"])
        original_draft = self.news.state["draft"]
        self.assertEqual(NewsBridge(self.database_path).state["draft"], original_draft)

        localization = LocalizationBridge(
            LocalizationRepository(self.database_path), self.engine, self.app
        )
        try:
            self.window.setProperty("localeController", localization)
            self.assertTrue(localization.setLanguage("en_US")["ok"])
            self._click("newsWorkspaceExpandButton")
            self._click("newsPasteButton")

            malformed_json = '{\n  "version": }'
            editor = self._control("newsJsonInput")
            editor.setProperty("text", malformed_json)
            self._click("newsPreviewButton")

            english_error = str(self.news_card.property("notice"))
            self.assertEqual(
                english_error,
                "Invalid JSON: Expecting value (line 2, column 14).",
            )
            self.assertTrue(self.news_card.property("noticeIsError"))
            self.assertTrue(self._control("newsJsonDialog").property("visible"))
            self.assertFalse(self._control("newsPreviewDialog").property("visible"))
            self.assertEqual(editor.property("text"), malformed_json)
            self.assertEqual(self.news.state["draft"], original_draft)
            self.assertEqual(NewsBridge(self.database_path).state["draft"], original_draft)

            malformed_file = self.temp_path / "synthetic-invalid-news.json"
            malformed_file.write_text(malformed_json, encoding="utf-8")
            file_dialog = self._control("newsFileDialog")
            file_dialog.setProperty("selectedFile", QUrl.fromLocalFile(str(malformed_file)))
            self.assertTrue(
                QMetaObject.invokeMethod(file_dialog, "accepted", Qt.ConnectionType.DirectConnection),
                "production news FileDialog accepted handler was not invokable",
            )
            self.assertEqual(
                self.news_card.property("notice"),
                "Could not preview the selected JSON file: Invalid JSON: Expecting value (line 2, column 14).",
            )
            self.assertTrue(self.news_card.property("noticeIsError"))
            self.assertFalse(self._control("newsPreviewDialog").property("visible"))
            self.assertEqual(self.news.state["draft"], original_draft)
            self.assertEqual(NewsBridge(self.database_path).state["draft"], original_draft)

            self.assertTrue(localization.setLanguage("zh_CN")["ok"])
            self._click("newsPreviewButton")
            chinese_error = str(self.news_card.property("notice"))
            self.assertRegex(
                chinese_error,
                r"^JSON 格式无效：Expecting value（第 2 行，第 14 列）。$",
            )
            self.assertTrue(self.news_card.property("noticeIsError"))
            self.assertTrue(self._control("newsJsonDialog").property("visible"))
            self.assertFalse(self._control("newsPreviewDialog").property("visible"))
            self.assertEqual(self.news.state["draft"], original_draft)
            self.assertEqual(NewsBridge(self.database_path).state["draft"], original_draft)
        finally:
            localization.close()

    def test_news_preview_offers_publish_and_cancel_returns_to_preview(self) -> None:
        draft = json.loads(json.dumps(_issue()))
        draft["topic"] = "预览出口验收主题"
        preview = self.news.previewJson(json.dumps(draft, ensure_ascii=False))
        self.assertTrue(preview["ok"], preview)
        self.assertTrue(
            QMetaObject.invokeMethod(
                self.news_card,
                "previewIssueResult",
                Qt.ConnectionType.DirectConnection,
                Q_ARG("QVariant", preview),
            )
        )
        QTest.qWait(80)

        preview_dialog = self._control("newsPreviewDialog")
        publish_button = self._control("newsPreviewPublishButton")
        confirm_dialog = self._control("newsPublishConfirmDialog")
        self.assertTrue(preview_dialog.property("visible"))
        self.assertTrue(publish_button.property("enabled"))

        self._click("newsPreviewPublishButton")
        self.assertFalse(preview_dialog.property("visible"))
        self.assertTrue(confirm_dialog.property("visible"))
        QTest.qWait(100)

        self.assertTrue(
            QMetaObject.invokeMethod(
                self.news_card, "confirmPublish", Qt.ConnectionType.DirectConnection
            )
        )
        self.assertFalse(confirm_dialog.property("visible"))
        self.assertFalse(preview_dialog.property("visible"))
        self.assertIsNone(self.news.state["draft"])
        self.assertEqual(self.news.state["active"]["topic"], "预览出口验收主题")

        # A second draft proves the cancel route returns to the same preview
        # decision point instead of leaving the user in the long workbench.
        draft["topic"] = "取消发布后仍可预览"
        preview = self.news.previewJson(json.dumps(draft, ensure_ascii=False))
        self.assertTrue(
            QMetaObject.invokeMethod(
                self.news_card,
                "previewIssueResult",
                Qt.ConnectionType.DirectConnection,
                Q_ARG("QVariant", preview),
            )
        )
        QTest.qWait(50)
        self._click("newsPreviewPublishButton")
        QTest.qWait(100)
        self.assertTrue(
            QMetaObject.invokeMethod(
                self.news_card, "cancelPublishConfirmation", Qt.ConnectionType.DirectConnection
            )
        )
        self.assertTrue(preview_dialog.property("visible"))

    def test_news_workbench_exposes_preview_unsaved_and_saved_status(self) -> None:
        draft = json.loads(json.dumps(_issue()))
        draft["topic"] = "持续保存状态验收主题"
        preview = self.news.previewJson(json.dumps(draft, ensure_ascii=False))
        self.assertTrue(preview["ok"], preview)
        self.assertTrue(
            QMetaObject.invokeMethod(
                self.news_card,
                "previewIssueResult",
                Qt.ConnectionType.DirectConnection,
                Q_ARG("QVariant", preview),
            )
        )
        QTest.qWait(60)

        summary_status = self._control("newsIssueSummaryStatus")
        workspace_status = self._control("newsWorkspaceDraftSaveStatus")
        save_button = self._control("newsSaveDraftButton")
        self.assertEqual(summary_status.property("text"), "预览未保存")
        self.assertEqual(workspace_status.property("text"), "预览未保存 · 保存后才写入本机")
        self.assertTrue(save_button.property("enabled"))

        self._click("newsPreviewSaveDraftButton")
        QTest.qWait(80)
        self.assertFalse(self.news.state["draftUnsaved"])
        self.assertEqual(summary_status.property("text"), "草稿已保存")
        self.assertEqual(workspace_status.property("text"), "草稿已保存到本机")
        self.assertFalse(save_button.property("enabled"))

    def test_news_json_replacement_requires_confirmation_when_preview_is_unsaved(self) -> None:
        current = json.loads(json.dumps(_issue()))
        current["topic"] = "需要保留的未保存预览"
        preview = self.news.previewJson(json.dumps(current, ensure_ascii=False))
        self.assertTrue(
            QMetaObject.invokeMethod(
                self.news_card,
                "previewIssueResult",
                Qt.ConnectionType.DirectConnection,
                Q_ARG("QVariant", preview),
            )
        )
        self._click("newsPreviewReturnButton")
        self._click("newsWorkspaceExpandButton")
        self._click("newsPasteButton")

        replacement = json.loads(json.dumps(_issue()))
        replacement["topic"] = "需要确认的新预览"
        editor = self._control("newsJsonInput")
        editor.setProperty("text", json.dumps(replacement, ensure_ascii=False))
        self._click("newsPreviewButton")

        replace_dialog = self._control("newsPreviewReplaceDialog")
        self.assertTrue(replace_dialog.property("visible"))
        self.assertEqual(self.news.state["draft"]["topic"], "需要保留的未保存预览")
        self._click("newsPreviewReplaceCancelButton")
        self.assertFalse(replace_dialog.property("visible"))
        self.assertTrue(self._control("newsJsonDialog").property("visible"))
        self.assertEqual(self.news.state["draft"]["topic"], "需要保留的未保存预览")

        self._click("newsPreviewButton")
        self.assertTrue(replace_dialog.property("visible"))
        self._click("newsPreviewReplaceConfirmButton")
        QTest.qWait(80)
        self.assertTrue(self._control("newsPreviewDialog").property("visible"))
        self.assertEqual(self.news.state["draft"]["topic"], "需要确认的新预览")

    def test_window_close_offers_save_discard_or_return_for_unsaved_news(self) -> None:
        saved_draft = json.loads(json.dumps(_issue()))
        saved_draft["topic"] = "关闭前可恢复的已保存草稿"
        self.assertTrue(self.news.previewJson(json.dumps(saved_draft, ensure_ascii=False))["ok"])
        self.assertTrue(self.news.saveDraft()["ok"])

        draft = json.loads(json.dumps(_issue()))
        draft["topic"] = "关闭前需要处理的预览"
        preview = self.news.previewJson(json.dumps(draft, ensure_ascii=False))
        self.assertTrue(
            QMetaObject.invokeMethod(
                self.news_card,
                "previewIssueResult",
                Qt.ConnectionType.DirectConnection,
                Q_ARG("QVariant", preview),
            )
        )
        self._click("newsPreviewReturnButton")

        self.window.close()
        QTest.qWait(80)
        exit_dialog = self._control("newsUnsavedExitDialog")
        self.assertTrue(exit_dialog.property("visible"))
        self.assertTrue(self.window.isVisible())
        self.assertIn("关闭窗口会丢弃", self._control("newsUnsavedExitSummary").property("text"))

        self._click("newsUnsavedExitRestoreButton")
        self.assertFalse(exit_dialog.property("visible"))
        self.assertEqual(self.news.state["draft"]["topic"], "关闭前可恢复的已保存草稿")
        self.assertFalse(self.news.state["draftUnsaved"])

        self.assertTrue(self.news.previewJson(json.dumps(draft, ensure_ascii=False))["ok"])

        self.window.close()
        QTest.qWait(80)
        self.assertTrue(exit_dialog.property("visible"))
        self._click("newsUnsavedExitReturnButton")
        self.assertFalse(exit_dialog.property("visible"))
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.news.state["draftUnsaved"])

        self.window.close()
        QTest.qWait(80)
        self.assertTrue(exit_dialog.property("visible"))
        self._click("newsUnsavedExitSaveButton")
        QTest.qWait(120)
        self.assertFalse(self.news.state["draftUnsaved"])
        self.assertFalse(self.window.isVisible())

    def test_article_reader_read_later_clipping_and_clipping_library_round_trip(self) -> None:
        self._click("newsReadArticle_focus_0")
        article_dialog = self._control("articleDialog")
        self.assertTrue(article_dialog.property("opened"))
        self.assertAlmostEqual(
            float(article_dialog.property("x")),
            (float(self.window.width()) - float(article_dialog.property("width"))) / 2,
            delta=2,
        )
        self.window.resize(760, 620)
        QTest.qWait(60)
        self.assertAlmostEqual(
            float(article_dialog.property("x")),
            (float(self.window.width()) - float(article_dialog.property("width"))) / 2,
            delta=2,
        )
        self.window.resize(1480, 960)
        QTest.qWait(60)
        self.assertEqual(article_dialog.property("headline"), "仅用于 QML 集成验收的合成文章")
        self.assertEqual(len(article_dialog.property("bodyParagraphs").toVariant()), 2)
        self.assertEqual(article_dialog.property("sourceUrl"), "https://news.example.com/synthetic-qml-article")
        original_button = self._control("articleDialogOriginalLinkButton")
        self.assertTrue(original_button.property("enabled"))
        global_reading = self._control("articleDialogGlobalReadingSection")
        self.assertTrue(global_reading.property("visible"))
        self.assertEqual(self._control("articleDialogGlobalReadingLabel").property("text"), "全局阅读设置")
        self._control("articleDialogRecommendationToggleButton")
        recommendation_feedback = self._control("articleDialogRecommendationFeedback")
        self.assertFalse(recommendation_feedback.property("visible"))
        self._click("articleDialogRecommendationToggleButton")
        self.assertTrue(recommendation_feedback.property("visible"))
        self.assertIn("本机推荐", self._control("articleDialogRecommendationExplanation").property("text"))

        self._click("articleDialogSavedKnowledgeButton")
        self.assertTrue(self.reading.state["savedKnowledge"])
        self.assertIn("关闭全局稍后读", self._control("articleDialogSavedKnowledgeButton").property("text"))
        self.assertEqual(
            self.reading.state["clippings"],
            [],
            "the global read-later setting must not imply that this article was saved",
        )

        self._click("articleDialogClippingButton")
        self.assertEqual(len(self.reading.state["clippings"]), 1)
        self.assertTrue(self._control("articleDialogClippingButton").property("text").startswith("已收进剪报"))
        restarted = ReadingBridge(self.database_path)
        self.assertTrue(restarted.state["savedKnowledge"])
        self.assertEqual(restarted.state["clippings"][0]["item"]["id"], "synthetic-qml-article-1")

        self._click("articleDialogCloseButton")
        self._click("newsWorkspaceMoreButton")
        self._click("newsClippingsButton")
        clippings_dialog = self._control("clippingsDialog")
        self.assertTrue(clippings_dialog.property("opened"))
        QTest.qWait(100)
        self.assertEqual(self._control("clippingOpen_0").property("text"), "阅读全文")
        self._click("clippingOpen_0")
        self.assertTrue(article_dialog.property("opened"))
        self.assertEqual(article_dialog.property("headline"), "仅用于 QML 集成验收的合成文章")
        self.assertFalse(self._control("articleDialogRecommendationFeedback").property("visible"))
        self._click("articleDialogCloseButton")

        # Remove through the production clipping-list handler and verify disk state.
        self._click("clippingRemove_0")
        self.assertEqual(self.reading.state["clippings"], [])
        self.assertEqual(ReadingBridge(self.database_path).state["clippings"], [])
        self.assertTrue(self.reading.state["savedKnowledge"])

    def test_article_external_link_buttons_dispatch_only_safe_https_urls(self) -> None:
        class ExternalUrlCapture(QObject):
            def __init__(self) -> None:
                super().__init__()
                self.urls: list[str] = []

            @Slot(QUrl)
            def capture(self, url: QUrl) -> None:
                self.urls.append(url.toString())

        capture = ExternalUrlCapture()
        # Qt.openUrlExternally forwards to QDesktopServices.openUrl. A scoped
        # https handler captures that exact production route instead of
        # starting the system browser.
        QDesktopServices.setUrlHandler("https", capture, "capture")
        try:
            # Prove that the safety handler itself is active before clicking
            # a production control; this call is also intercepted.
            probe = "https://handler-probe.example/safe"
            self.assertTrue(QDesktopServices.openUrl(QUrl(probe)))
            self.assertEqual(capture.urls, [probe])
            capture.urls.clear()

            self._click("newsReadArticle_focus_0")
            article_dialog = self._control("articleDialog")
            self.assertTrue(article_dialog.property("opened"))

            expected_links = (
                ("articleDialogOriginalLinkButton", "https://news.example.com/synthetic-qml-article"),
                ("coverageSourceButton", "https://news.example.com/related"),
                ("updateSourceButton", "https://news.example.com/update"),
            )
            for control_name, expected_url in expected_links:
                button = self._control(control_name)
                self.assertTrue(button.property("enabled"), f"{control_name} should accept HTTPS")
                self._click(control_name)
                self.assertEqual(capture.urls, [expected_url], control_name)
                capture.urls.clear()

            unsafe_cases = (
                ("sourceUrl", "http://news.example.com/insecure", "articleDialogOriginalLinkButton"),
                ("relatedCoverage", "javascript:alert(1)", "coverageSourceButton"),
                ("updates", "not a URL", "updateSourceButton"),
            )
            for field, unsafe_url, control_name in unsafe_cases:
                article = json.loads(json.dumps(_issue()["focus"][0]))
                if field == "sourceUrl":
                    article[field] = unsafe_url
                else:
                    article[field][0]["sourceUrl"] = unsafe_url
                article_dialog.setProperty("article", article)
                QTest.qWait(30)

                button = self._control(control_name)
                self.assertFalse(button.property("enabled"), f"{control_name} must reject {unsafe_url!r}")
                self._click(control_name)
                self.assertEqual(capture.urls, [], f"{control_name} dispatched an unsafe URL")
        finally:
            QDesktopServices.unsetUrlHandler("https")
            if getattr(self, "window", None) is not None:
                article_dialog = self.window.findChild(QObject, "articleDialog")
                if article_dialog is not None and article_dialog.property("opened"):
                    QMetaObject.invokeMethod(
                        article_dialog, "close", Qt.ConnectionType.DirectConnection
                    )

    def test_finance_save_requires_a_valid_amount_and_persists(self) -> None:
        self.window.setProperty("currentSectionIndex", 1)
        QTest.qWait(80)

        amount = self._control("financeAmountInput")
        save = self._control("financeSaveButton")
        flow = self._control("financeFlowBox")
        category = self._control("financeCategoryBox")
        self.assertIsNotNone(flow.property("uiTheme"))
        self.assertIsNotNone(category.property("uiTheme"))
        self.assertIn("必填", str(amount.property("placeholderText")))
        self.assertEqual(self._control("financeFlowLabel").property("text"), "类型")
        self.assertEqual(self._control("financeAmountLabel").property("text"), "金额")
        self.assertEqual(self._control("financeCategoryLabel").property("text"), "分类")
        self.assertEqual(self._control("financeDateLabel").property("text"), "日期")
        self.assertEqual(self._control("financeNoteLabel").property("text"), "备注")
        self.assertEqual(
            self._control("financeStorageHint").property("text"),
            "本机保存 · 导入的旧版数据不会被改动",
        )
        self.assertFalse(bool(save.property("enabled")))

        finance_page = self._control("financePage")
        flow.setProperty("currentIndex", 1)
        QTest.qWait(30)
        self.assertEqual(category.property("count"), len(finance_page.property("incomeOptions").toVariant()))
        flow.setProperty("currentIndex", 0)
        QTest.qWait(30)

        amount.setProperty("text", "0")
        QTest.qWait(30)
        self.assertFalse(bool(save.property("enabled")))

        amount.setProperty("text", "12.50")
        QTest.qWait(30)
        self.assertTrue(bool(save.property("enabled")))
        self._click("financeSaveButton")

        controller = self.controllers["financeController"]
        record = controller.state["records"][0]
        self.assertEqual(record["data"]["amount"], 12.5)
        persisted = FinanceBridge(self.database_path)
        self.assertEqual(persisted.state["records"][0]["data"]["amount"], 12.5)
        self._click("financeRecordDeleteButton")
        delete_dialog = self._control("financeDeleteDialog")
        delete_message = self._control("financeDeleteMessage")
        self.assertTrue(delete_dialog.property("visible"))
        self.assertIn("当前本机账本", str(delete_message.property("text")))
        self.assertIn("旧版原始数据不会被改动", str(delete_message.property("text")))
        self._click("financeDeleteConfirmButton")
        self.assertFalse(delete_dialog.property("visible"))

    def test_production_shopping_page_uses_its_contextual_english_catalog(self) -> None:
        locale = LocalizationBridge(
            LocalizationRepository(self.database_path), self.engine, self.app
        )
        try:
            self.window.setProperty("localeController", locale)
            result = locale.setLanguage("en_US")
            self.assertTrue(result["ok"], result)
            self.window.setProperty("currentSectionIndex", 5)
            QTest.qWait(80)

            shopping_page = self._control("shoppingPage")
            self.assertTrue(shopping_page.property("visible"))
            self.assertEqual(self._control("shoppingFilter_pending").property("text"), "To buy")
            self.assertEqual(
                self._control("shoppingStorageHint").property("text"),
                "Saved locally · Imported legacy data will not be changed",
            )
            for object_name, expected_text in {
                "shoppingNameLabel": "Item name",
                "shoppingQuantityLabel": "Quantity",
                "shoppingCategoryLabel": "Item category",
                "shoppingPriceLabel": "Estimated unit price",
                "shoppingPriorityLabel": "Purchase priority",
                "shoppingNoteLabel": "Note",
            }.items():
                with self.subTest(label=object_name):
                    label = self._control(object_name)
                    self.assertTrue(label.property("visible"))
                    self.assertEqual(label.property("text"), expected_text)
            category = self._control("shoppingCategoryBox")
            self.assertEqual(category.property("displayText"), "Food")
            self.assertEqual(category.property("currentValue"), "食品")

            shopping_name = self._control("shoppingNameInput")
            shopping_add = self._control("shoppingAddButton")
            self.assertIn("Required", str(shopping_name.property("placeholderText")))
            self.assertFalse(bool(shopping_add.property("enabled")))
            shopping_name.setProperty("text", "合成物品")
            QTest.qWait(30)
            self.assertTrue(bool(shopping_add.property("enabled")))
            self._click("shoppingAddButton")
            state = self.controllers["shoppingController"].state
            self.assertEqual(state["shoppingRecords"][0]["data"]["category"], "食品")
            item_id = state["shoppingRecords"][0]["id"]
            self._click("shoppingDelete_" + item_id)
            delete_dialog = self._control("shoppingDeleteDialog")
            delete_message = self._control("shoppingDeleteMessage")
            self.assertTrue(delete_dialog.property("visible"))
            self.assertIn("current local shopping list", str(delete_message.property("text")))
            self.assertIn("legacy source data stays unchanged", str(delete_message.property("text")))
            self._click("shoppingDeleteConfirmButton")
            self.assertFalse(delete_dialog.property("visible"))
        finally:
            locale.close()

    def test_production_home_layout_toggles_are_independent_and_reopen_from_saved_state(self) -> None:
        habits = self._control("dailyHabitQuickChecks")
        question_desk = self._control("dailyQuestionDesk")
        quick = self._control("dailyQuickAddCard")
        lead = self._control("newsScopeCard")
        weekly = self._control("dailyWeeklyCard")
        recent = self._control("dailyRecentCard")
        yesterday = self._control("dailyReviewCard")
        recap_items = self._control("dailyReviewItems")
        work = self._control("dailyWorkCard")
        news = self._control("newsCard")

        self.assertTrue(bool(habits.property("visible")))
        self.assertTrue(bool(question_desk.property("visible")))
        self.assertTrue(bool(quick.property("visible")))
        self.assertTrue(bool(yesterday.property("visible")))
        self.assertTrue(bool(work.property("visible")))
        self.assertTrue(bool(news.property("visible")))
        self.assertTrue(bool(lead.property("visible")))
        self.assertTrue(bool(weekly.property("visible")))
        self.assertTrue(bool(recent.property("visible")))
        self.assertEqual(lead.parentItem().objectName(), "homeLayoutCards_flow-briefing-slot")
        self.assertEqual(news.parentItem().objectName(), "homeLayoutCards_flow-briefing-slot")
        self.assertEqual(question_desk.parentItem().objectName(), "homeLayoutCards_flow-review-slot")
        self.assertEqual(weekly.parentItem().objectName(), "homeLayoutCards_flow-review-slot")
        self.assertEqual(recent.parentItem().objectName(), "homeLayoutCards_flow-review-slot")
        self.assertEqual(habits.parentItem().objectName(), "homeLayoutCards_flow-work-slot")
        self.assertEqual(quick.parentItem().objectName(), "homeLayoutCards_flow-work-slot")
        self.assertEqual(
            self._home_layout_slot_children("flow-review-slot"),
            ["dailyQuestionDesk", "dailyWeeklyCard", "dailyRecentCard"],
        )
        self.assertEqual(
            self._home_layout_slot_visual_order("flow-review-slot"),
            ["dailyQuestionDesk", "dailyWeeklyCard", "dailyRecentCard"],
        )
        question_input = self._control("dailyQuestionInput")
        question_input.setProperty("text", "通过新布局保留的问题簿输入")
        self._click("dailyQuestionAddButton")
        self.assertEqual(
            self.controllers["dailyController"].state["questions"][0]["text"],
            "通过新布局保留的问题簿输入",
        )

        self._click("homeLayoutSettingsButton")
        dialog = self._control("homeLayoutDialog")
        self.assertTrue(bool(dialog.property("opened")))
        habits_switch = self._control("homeLayoutHabitsSwitch")
        question_switch = self._control("homeLayoutQuestionDeskSwitch")
        quick_switch = self._control("homeLayoutQuickSwitch")
        card_switches = {
            card_id: self._control("homeLayoutVisibleSwitch_" + card_id)
            for card_id in ("lead", "briefs", "weekly", "recent")
        }
        self.assertTrue(bool(habits_switch.property("checked")))
        self.assertTrue(bool(question_switch.property("checked")))
        self.assertTrue(bool(quick_switch.property("checked")))
        self.assertTrue(all(bool(control.property("checked")) for control in card_switches.values()))

        self._click("homeLayoutVisibleSwitch_lead")
        QTest.qWait(30)
        self.assertFalse(bool(lead.property("visible")))
        self.assertTrue(bool(news.property("visible")))
        self.assertEqual(self.home_layout.saved_layout["hidden"], ["lead"])
        self._click("homeLayoutVisibleSwitch_lead")
        self._click("homeLayoutVisibleSwitch_briefs")
        QTest.qWait(30)
        self.assertTrue(bool(lead.property("visible")))
        self.assertFalse(bool(news.property("visible")))
        self.assertFalse(bool(self._control("newsIssueContentHeader").property("visible")))
        self.assertEqual(self.home_layout.saved_layout["hidden"], ["briefs"])
        self._click("homeLayoutVisibleSwitch_briefs")
        QTest.qWait(30)
        self.assertEqual(self.home_layout.saved_layout["hidden"], [])
        self.assertTrue(bool(self._control("newsIssueContentHeader").property("visible")))

        order_combo = self._control("homeLayoutOrder_lead")
        self.assertEqual(int(order_combo.property("currentIndex")), 3)
        order_combo.setProperty("currentIndex", 0)
        self.assertTrue(QMetaObject.invokeMethod(
            order_combo, "activated", Qt.ConnectionType.DirectConnection, Q_ARG("int", 0)
        ))
        self.assertEqual(self.home_layout.saved_layout["order"][0], "lead")
        slot_combo = self._control("homeLayoutSlot_quick")
        slot_combo.setProperty("currentIndex", 0)
        self.assertTrue(QMetaObject.invokeMethod(
            slot_combo, "activated", Qt.ConnectionType.DirectConnection, Q_ARG("int", 0)
        ))
        self.assertEqual(
            self.home_layout.saved_layout["slots"]["quick"], "flow-briefing-slot"
        )
        QTest.qWait(60)
        self.assertEqual(quick.parentItem().objectName(), "homeLayoutCards_flow-briefing-slot")
        self.assertEqual(
            self._home_layout_slot_children("flow-briefing-slot"),
            ["newsScopeCard", "dailyQuickAddCard", "newsCard", "newsIssueContentHeader"],
        )

        self._click("homeLayoutHabitsSwitch")
        QTest.qWait(30)
        self.assertFalse(bool(habits.property("visible")))
        self.assertTrue(bool(question_desk.property("visible")))
        self.assertTrue(bool(yesterday.property("visible")))
        self.assertEqual(self.home_layout.saved_layout["hidden"], ["habits"])

        self._click("homeLayoutQuickSwitch")
        QTest.qWait(30)
        self.assertFalse(bool(quick.property("visible")))
        self.assertEqual(self.home_layout.saved_layout["hidden"], ["habits", "quick"])
        self._click("homeLayoutQuickSwitch")
        QTest.qWait(30)
        self.assertTrue(bool(quick.property("visible")))
        self.assertEqual(self.home_layout.saved_layout["hidden"], ["habits"])

        self._click("homeLayoutQuestionDeskSwitch")
        QTest.qWait(30)
        self.assertFalse(bool(question_desk.property("visible")))
        self.assertFalse(bool(habits.property("visible")))
        self.assertTrue(bool(yesterday.property("visible")))
        self.assertTrue(bool(recap_items.property("visible")))
        self.assertTrue(bool(work.property("visible")))
        self.assertTrue(bool(news.property("visible")))
        self.assertEqual(
            self._home_layout_slot_children("flow-briefing-slot"),
            ["newsScopeCard", "dailyQuickAddCard", "newsCard", "newsIssueContentHeader"],
        )
        self.assertEqual(
            self._home_layout_slot_children("flow-review-slot"),
            ["dailyQuestionDesk", "dailyWeeklyCard", "dailyRecentCard"],
        )
        self.assertEqual(
            self._home_layout_slot_children("flow-work-slot"),
            ["dailyHabitQuickChecks"],
        )
        self.assertEqual(
            self.home_layout.saved_layout["hidden"], ["habits", "question-desk"]
        )

        self._click("homeLayoutHabitsSwitch")
        QTest.qWait(30)
        self.assertTrue(bool(habits.property("visible")))
        self.assertFalse(bool(question_desk.property("visible")))
        self.assertTrue(bool(yesterday.property("visible")))

        self.assertEqual(self.home_layout.saved_layout["hidden"], ["question-desk"])

        saved_layout = json.loads(json.dumps(self.home_layout.saved_layout))
        self._click("homeLayoutCloseButton")
        self.assertFalse(bool(dialog.property("opened")))
        reopened_bridge = FakeHomeLayoutBridge(saved_layout)
        self.assertTrue(self.window.setProperty("homeLayoutController", reopened_bridge))
        self._click("homeLayoutSettingsButton")
        QTest.qWait(30)
        self.assertTrue(bool(self._control("homeLayoutHabitsSwitch").property("checked")))
        self.assertFalse(bool(self._control("homeLayoutQuestionDeskSwitch").property("checked")))
        self.assertTrue(bool(self._control("homeLayoutQuickSwitch").property("checked")))
        self.assertTrue(bool(habits.property("visible")))
        self.assertFalse(bool(question_desk.property("visible")))
        self.assertTrue(bool(yesterday.property("visible")))
        self.assertTrue(bool(work.property("visible")))
        self.assertTrue(bool(news.property("visible")))
        self.assertEqual(reopened_bridge.saved_layout["order"], saved_layout["order"])
        self.assertEqual(reopened_bridge.saved_layout["slots"], saved_layout["slots"])
        self.assertEqual(
            reopened_bridge.saved_layout["unknownMetadata"],
            {"keep": "through-toggle"},
        )
        QTest.qWait(60)
        self.assertEqual(
            self._home_layout_slot_children("flow-briefing-slot"),
            ["newsScopeCard", "dailyQuickAddCard", "newsCard", "newsIssueContentHeader"],
        )
        self.assertEqual(
            self._home_layout_slot_children("flow-review-slot"),
            ["dailyQuestionDesk", "dailyWeeklyCard", "dailyRecentCard"],
        )
        self.assertEqual(
            self._home_layout_slot_children("flow-work-slot"),
            ["dailyHabitQuickChecks"],
        )
        self.assertEqual(
            quick.parentItem().objectName(), "homeLayoutCards_flow-briefing-slot"
        )

        reopened_bridge.fail_next_save = True
        self._click("homeLayoutQuestionDeskSwitch")
        status = self._control("homeLayoutSaveStatus")
        self.assertTrue(bool(status.property("visible")))
        self.assertIn("synthetic write failure", str(status.property("text")))
        self.assertTrue(bool(self.window.property("homeLayoutSaveStatusIsError")))
        self.assertFalse(bool(question_desk.property("visible")))
        self.assertTrue(bool(yesterday.property("visible")))

    def test_production_home_layout_order_slots_and_visibility_persist_in_sqlite(self) -> None:
        bridge = HomeLayoutBridge(self.database_path)
        self.assertTrue(self.window.setProperty("homeLayoutController", bridge))

        order_combo = self._control("homeLayoutOrder_lead")
        order_combo.setProperty("currentIndex", 6)
        self.assertTrue(QMetaObject.invokeMethod(
            order_combo, "activated", Qt.ConnectionType.DirectConnection, Q_ARG("int", 6)
        ))
        slot_combo = self._control("homeLayoutSlot_quick")
        slot_combo.setProperty("currentIndex", 0)
        self.assertTrue(QMetaObject.invokeMethod(
            slot_combo, "activated", Qt.ConnectionType.DirectConnection, Q_ARG("int", 0)
        ))
        self._click("homeLayoutVisibleSwitch_weekly")

        saved_layout = bridge.state["layout"]
        self.assertEqual(saved_layout["order"][-1], "lead")
        self.assertEqual(saved_layout["slots"]["quick"], "flow-briefing-slot")
        self.assertEqual(saved_layout["hidden"], ["weekly"])
        QTest.qWait(60)
        self.assertEqual(
            self._home_layout_slot_children("flow-briefing-slot"),
            ["newsCard", "newsIssueContentHeader", "dailyQuickAddCard", "newsScopeCard"],
        )
        self.assertEqual(
            self._home_layout_slot_visual_order("flow-briefing-slot"),
            ["newsCard", "newsIssueContentHeader", "dailyQuickAddCard", "newsScopeCard"],
        )
        self.assertEqual(
            self._home_layout_slot_children("flow-review-slot"),
            ["dailyWeeklyCard", "dailyRecentCard", "dailyQuestionDesk"],
        )
        self.assertEqual(
            self._home_layout_slot_children("flow-work-slot"),
            ["dailyHabitQuickChecks"],
        )

        reopened = HomeLayoutBridge(self.database_path)
        self.assertEqual(reopened.state["layout"], saved_layout)
        self.assertTrue(self.window.setProperty("homeLayoutController", reopened))
        QTest.qWait(60)
        self.assertEqual(
            self._home_layout_slot_children("flow-briefing-slot"),
            ["newsCard", "newsIssueContentHeader", "dailyQuickAddCard", "newsScopeCard"],
        )
        self.assertEqual(
            self._home_layout_slot_visual_order("flow-briefing-slot"),
            ["newsCard", "newsIssueContentHeader", "dailyQuickAddCard", "newsScopeCard"],
        )
        self.assertEqual(
            self._home_layout_slot_children("flow-review-slot"),
            ["dailyWeeklyCard", "dailyRecentCard", "dailyQuestionDesk"],
        )
        self.assertEqual(
            self._home_layout_slot_children("flow-work-slot"),
            ["dailyHabitQuickChecks"],
        )
        self.assertEqual(
            self._control("dailyQuickAddCard").parentItem().objectName(),
            "homeLayoutCards_flow-briefing-slot",
        )
        self._click("homeLayoutSettingsButton")
        self.assertFalse(bool(self._control("homeLayoutVisibleSwitch_weekly").property("checked")))
        self.assertFalse(bool(self._control("dailyWeeklyCard").property("visible")))
        self.assertEqual(
            str(self._control("homeLayoutSlot_quick").property("currentValue")),
            "flow-briefing-slot",
        )

    def test_legacy_quick_entry_routes_to_module_and_focuses_first_input(self) -> None:
        cases = (
            ("dailyQuickMoneyButton", 1, "financeAmountInput"),
            ("dailyQuickFitnessButton", 3, "fitnessWeightInput"),
            ("dailyQuickShoppingButton", 5, "shoppingNameInput"),
        )
        for button_name, section_index, input_name in cases:
            self.window.setProperty("currentSectionIndex", 0)
            QTest.qWait(40)
            self._click(button_name)
            QTest.qWait(220)
            self.assertEqual(int(self.window.property("currentSectionIndex")), section_index)
            active = self.window.activeFocusItem()
            self.assertIsNotNone(active, f"{button_name} did not focus a field")
            self.assertEqual(active.objectName(), input_name)


if __name__ == "__main__":
    unittest.main()
