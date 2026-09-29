from __future__ import annotations

import os
from pathlib import Path
import unittest

from PySide6.QtCore import QObject, QMetaObject, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtTest import QTest


class RecommendationFeedbackQmlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.qml_directory = Path(__file__).resolve().parents[1] / "qml"

    def setUp(self) -> None:
        self.engine = QQmlApplicationEngine()
        qml_url = QUrl.fromLocalFile(str(self.qml_directory).replace("\\", "/") + "/")
        wrapper_url = QUrl.fromLocalFile(str(self.qml_directory / "RecommendationFeedbackTest.qml"))
        wrapper = (
            "import QtQuick\n"
            "import QtQuick.Controls\n"
            f'import "{qml_url.toString()}" as Native\n'
            "ApplicationWindow {\n"
            "  id: testWindow\n"
            "  visible: true; width: 720; height: 900\n"
            "  property string lastAction: \"\"\n"
            "  property string lastDate: \"\"\n"
            "  property string lastArticleId: \"\"\n"
            "  property string lastExternalUrl: \"\"\n"
            "  Native.ArticleDialog {\n"
            "    id: articleDialog\n"
            "    objectName: \"articleDialogUnderTest\"\n"
            "    date: \"2026-09-27\"\n"
            "    article: ({ id: \"qml-health-1\", title: \"合成健康新闻\", category: \"健康\", publisher: \"测试来源\", body: [\"合成正文。\"], relatedCoverage: [{ publisher: \"其他来源\", title: \"相关报道\", publishedAt: \"2026-09-26\", summary: \"相关摘要\", sourceUrl: \"https://example.com/related\" }], updates: [{ date: \"2026-09-27\", summary: \"事件更新\", publisher: \"原始来源\", sourceUrl: \"https://example.com/update\" }] })\n"
            "    onOpenExternalLinkRequested: function(url) { testWindow.lastExternalUrl = url }\n"
            "    onFeedbackRequested: function(article, issueDate, action) {\n"
            "      testWindow.lastAction = action\n"
            "      testWindow.lastDate = issueDate\n"
            "      testWindow.lastArticleId = article.id\n"
            "    }\n"
            "    Component.onCompleted: open()\n"
            "  }\n"
            "}\n"
        )
        self.component = QQmlComponent(self.engine)
        self.component.setData(wrapper.encode("utf-8"), wrapper_url)
        if self.component.isError():
            self.fail("\n".join(error.toString() for error in self.component.errors()))
        self.window = self.component.create()
        if self.window is None:
            self.fail("\n".join(error.toString() for error in self.component.errors()))
        self.dialog = self.window.findChild(QObject, "articleDialogUnderTest")
        if self.dialog is None:
            self.fail("ArticleDialog did not load in the QML test window")
        QTest.qWait(80)

    def tearDown(self) -> None:
        self.window.deleteLater()
        self.engine.deleteLater()
        QTest.qWait(20)

    def test_each_feedback_button_emits_stable_article_context_and_can_undo(self) -> None:
        for action in ("useful", "not_interested", "more_topic", "less_source"):
            with self.subTest(action=action):
                button = self.window.findChild(
                    QObject, f"articleFeedback_{action}"
                )
                self.assertIsNotNone(button)
                self.assertTrue(button.property("enabled"))
                self.assertTrue(
                    QMetaObject.invokeMethod(
                        button, "click", Qt.ConnectionType.DirectConnection
                    )
                )
                QTest.qWait(10)
                self.assertEqual(self.window.property("lastAction"), action)
                self.assertEqual(self.window.property("lastDate"), "2026-09-27")
                self.assertEqual(self.window.property("lastArticleId"), "qml-health-1")

                self.dialog.setProperty("feedbackAction", action)
                QTest.qWait(10)
                self.assertIn("✓", button.property("text"))
                self.assertTrue(
                    QMetaObject.invokeMethod(
                        button, "click", Qt.ConnectionType.DirectConnection
                    )
                )
                QTest.qWait(10)
                self.assertEqual(self.window.property("lastAction"), "")

    def test_related_coverage_and_update_source_buttons_emit_https_urls(self) -> None:
        self.assertEqual(len(self.dialog.property("relatedItems").toVariant()), 1)
        self.assertEqual(len(self.dialog.property("updateItems").toVariant()), 1)
        self.assertEqual(self.window.findChild(QObject, "articleCoverageRepeater").property("count"), 1)
        self.assertEqual(self.window.findChild(QObject, "articleUpdatesRepeater").property("count"), 1)
        content_item = self.dialog.property("contentItem")
        self.assertIsInstance(content_item, QQuickItem)
        visual_items = []
        pending_items = [content_item]
        while pending_items:
            item = pending_items.pop()
            visual_items.append(item)
            pending_items.extend(item.childItems())
        visible_text = [
            child.property("text")
            for child in visual_items
            if child.metaObject().indexOfProperty("text") >= 0
        ]
        body_paragraphs = self.dialog.property("bodyParagraphs").toVariant()
        self.assertEqual(len(body_paragraphs), 1)
        self.assertIn(body_paragraphs[0], visible_text)
        for object_name, expected_url in (
            ("coverageSourceButton", "https://example.com/related"),
            ("updateSourceButton", "https://example.com/update"),
        ):
            with self.subTest(object_name=object_name):
                button = next((item for item in visual_items if item.objectName() == object_name), None)
                self.assertIsNotNone(button, [item.objectName() for item in visual_items if item.objectName()])
                self.assertTrue(button.property("enabled"))
                self.assertTrue(
                    QMetaObject.invokeMethod(
                        button, "click", Qt.ConnectionType.DirectConnection
                    )
                )
                QTest.qWait(10)
                self.assertEqual(self.window.property("lastExternalUrl"), expected_url)


if __name__ == "__main__":
    unittest.main()
