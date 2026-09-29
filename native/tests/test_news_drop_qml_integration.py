from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (
    QCoreApplication,
    Q_ARG,
    QMetaObject,
    QObject,
    QPoint,
    QPointF,
    QMimeData,
    Qt,
    QUrl,
    Slot,
)
from PySide6.QtGui import (
    QAccessible,
    QDesktopServices,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QWheelEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine

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
from wanxiang.issues import DRAFT_SETTING, ISSUE_SETTING, LAYOUT_SETTING
from wanxiang.database import get_app_setting


def _synthetic_issue() -> dict[str, object]:
    article = {
        "id": "synthetic-focus-1",
        "label": "合成栏目",
        "title": "仅供拖放集成测试的合成标题",
        "summary": "合成摘要，不含个人或真实新闻数据。",
        "body": ["仅供测试的合成正文。"],
        "publisher": "合成来源",
        "publishedAt": "2026-09-27T08:00:00Z",
        "sourceUrl": "https://news.example.org/synthetic-story",
    }
    return {
        "version": 1,
        "date": "2026-09-27",
        "topic": "合成拖放测试刊期",
        "focus": [article],
        "highlights": [{**article, "id": "synthetic-highlight-1", "label": "合成快讯"}],
        "articles": [],
    }


class NewsDropQmlIntegrationTests(unittest.TestCase):
    """Exercise the production DropArea handlers through Qt Quick window events."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.native_dir = Path(__file__).resolve().parents[1]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-news-drop-")
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)
        self.database_path = self.temp_path / "synthetic.sqlite3"
        self.engine = QQmlApplicationEngine()
        self.addCleanup(self._destroy_engine)
        self.qml_warnings: list[str] = []
        self.engine.warnings.connect(
            lambda warnings: self.qml_warnings.extend(warning.toString() for warning in warnings)
        )

        # Recreate the production context using only an isolated temporary DB.
        migration = MigrationBridge(self.database_path)
        snapshot = migration.data
        finance = FinanceBridge(self.database_path, snapshot)
        controllers = {
            "migrationController": migration,
            "weatherController": WeatherBridge(self.database_path, snapshot),
            "newsController": NewsBridge(self.database_path, snapshot),
            "habitController": HabitBridge(self.database_path, snapshot),
            "preferencesController": IssuePreferencesBridge(self.database_path, snapshot),
            "readingController": ReadingBridge(self.database_path, snapshot),
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
        }
        self.controllers = controllers
        self.engine.setInitialProperties(controllers)

        qml_path = self.native_dir / "qml" / "Main.qml"
        self.engine.load(QUrl.fromLocalFile(str(qml_path)))
        self.assertTrue(
            self.engine.rootObjects(),
            "production Main.qml failed to load:\n" + "\n".join(self.qml_warnings),
        )
        self.window = self.engine.rootObjects()[0]
        self.assertEqual(self.window.title(), "万象来信")
        self.window.resize(1480, 960)
        self.window.show()
        QTest.qWait(150)

        self.drop_area = self.window.findChild(QObject, "newsDropArea")
        self.assertIsNotNone(self.drop_area, "production newsDropArea was not found")
        self.scroll = self.window.findChild(QObject, "dailyPageScroll")
        self.assertIsNotNone(self.scroll, "daily page scroll container was not found")
        self.news_card = self.window.findChild(QObject, "newsCard")
        self.assertIsNotNone(self.news_card, "production news card was not found")
        self.assertFalse(self.news_card.property("workspaceExpanded"))
        self._click("newsWorkspaceExpandButton")
        self.assertTrue(self.news_card.property("workspaceExpanded"))
        self.assertFalse(self.news_card.property("secondaryActionsExpanded"))
        self._click("newsWorkspaceMoreButton")
        self.assertTrue(self.news_card.property("secondaryActionsExpanded"))
        self._click("newsWorkspaceCollapseButton")
        self.assertFalse(self.news_card.property("workspaceExpanded"))
        self._click("newsWorkspaceExpandButton")
        self.assertTrue(self.news_card.property("workspaceExpanded"))

    def _destroy_engine(self) -> None:
        if getattr(self, "engine", None) is not None:
            self.engine.deleteLater()
            QTest.qWait(30)

    def _visible_drop_point(self) -> QPointF:
        """Scroll the real drop target into the production ScrollView viewport."""
        center = QPointF(self.drop_area.width() / 2, self.drop_area.height() / 2)
        scene_point = self.drop_area.mapToScene(center)
        flickable = self.scroll.property("contentItem")
        self.assertIsNotNone(flickable, "daily page ScrollView has no flickable viewport")
        viewport_top = self.scroll.mapToScene(QPointF(0, 0)).y()
        viewport_bottom = viewport_top + self.scroll.height()
        if scene_point.y() < viewport_top or scene_point.y() >= viewport_bottom:
            current_y = float(flickable.property("contentY") or 0)
            viewport_center = (viewport_top + viewport_bottom) / 2
            requested_y = current_y + scene_point.y() - viewport_center
            max_y = max(
                0.0,
                float(flickable.property("contentHeight") or 0)
                - float(flickable.property("height") or self.scroll.height()),
            )
            flickable.setProperty("contentY", min(max(requested_y, 0.0), max_y))
            QTest.qWait(100)
            scene_point = self.drop_area.mapToScene(center)
        self.assertGreaterEqual(scene_point.x(), 0)
        self.assertLess(scene_point.x(), self.window.width())
        self.assertGreaterEqual(scene_point.y(), 0)
        self.assertLess(scene_point.y(), self.window.height())
        viewport_top = self.scroll.mapToScene(QPointF(0, 0)).y()
        viewport_bottom = viewport_top + self.scroll.height()
        self.assertGreaterEqual(scene_point.y(), viewport_top)
        self.assertLess(scene_point.y(), viewport_bottom)
        return scene_point

    def _drop_urls(self, urls: list[QUrl]) -> None:
        point = self._visible_drop_point()
        mime = QMimeData()
        mime.setUrls(urls)
        position = point.toPoint()
        enter = QDragEnterEvent(
            position,
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QCoreApplication.sendEvent(self.window, enter)
        self.assertTrue(enter.isAccepted(), "the QQuickWindow rejected drag enter")
        drop = QDropEvent(
            point,
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QCoreApplication.sendEvent(self.window, drop)
        self.assertTrue(drop.isAccepted(), "the production DropArea did not accept the drop")
        QTest.qWait(50)

    def _open_layout_dialog(self) -> QObject:
        more_button = self.window.findChild(QObject, "newsWorkspaceMoreButton")
        self.assertIsNotNone(more_button, "production news more button was not found")
        if not bool(self.news_card.property("secondaryActionsExpanded")):
            self.assertTrue(
                QMetaObject.invokeMethod(
                    more_button, "click", Qt.ConnectionType.DirectConnection
                )
            )
            QTest.qWait(40)
        button = self.window.findChild(QObject, "newsLayoutButton")
        self.assertIsNotNone(button, "production news layout button was not found")
        self.assertTrue(
            QMetaObject.invokeMethod(
                button, "click", Qt.ConnectionType.DirectConnection
            )
        )
        QTest.qWait(100)
        dialogs = [
            child
            for child in self.window.findChildren(QObject)
            if child.property("title") == "调整新闻版面"
        ]
        self.assertTrue(dialogs, "production layout dialog was not created")
        dialog = next((item for item in dialogs if item.property("visible")), None)
        self.assertIsNotNone(dialog, "news layout button did not open its dialog")
        return dialog

    def _click(self, object_name: str) -> QObject:
        control = self.window.findChild(QObject, object_name)
        if control is None:
            control = next(
                (
                    item
                    for item in self._window_visual_items()
                    if item.objectName() == object_name
                ),
                None,
            )
        self.assertIsNotNone(control, f"production QML control {object_name} was not found")
        assert control is not None
        self.assertTrue(
            QMetaObject.invokeMethod(
                control, "click", Qt.ConnectionType.DirectConnection
            ),
            f"production QML control {object_name} did not expose click()",
        )
        QTest.qWait(80)
        return control

    def _window_visual_items(self) -> list[QQuickItem]:
        content = self.window.contentItem()
        if not isinstance(content, QQuickItem):
            return []
        result: list[QQuickItem] = []
        pending = [content]
        while pending:
            item = pending.pop()
            result.append(item)
            pending.extend(item.childItems())
        return result

    def _dialog(self, title: str) -> QObject:
        dialogs = [
            child
            for child in self.window.findChildren(QObject)
            if child.property("title") == title
        ]
        self.assertTrue(dialogs, f"production dialog {title!r} was not created")
        visible = next((dialog for dialog in dialogs if dialog.property("visible")), None)
        self.assertIsNotNone(visible, f"production dialog {title!r} is not visible")
        assert visible is not None
        return visible

    def _layout_row_order(self) -> list[str]:
        items = self._layout_visual_items()
        handles = [
            item
            for item in items
            if str(item.objectName()).startswith("newsLayoutDrag_")
        ]
        centers = []
        for handle in handles:
            key = str(handle.objectName()).removeprefix("newsLayoutDrag_")
            position = handle.mapToScene(
                QPointF(handle.width() / 2, handle.height() / 2)
            )
            centers.append((position.y(), key))
        return [key for _, key in sorted(centers)]

    def _layout_handle(self, key: str) -> QQuickItem:
        return self._layout_control(f"newsLayoutDrag_{key}")

    def _layout_control(self, object_name: str) -> QQuickItem:
        item = next(
            (item for item in self._layout_visual_items() if item.objectName() == object_name),
            None,
        )
        self.assertIsNotNone(item, f"layout control {object_name} was not found")
        return item

    def _layout_visual_items(self) -> list[QQuickItem]:
        content = self.layout_dialog.property("contentItem")
        if not isinstance(content, QQuickItem):
            return []
        result: list[QQuickItem] = []
        pending = [content]
        while pending:
            item = pending.pop()
            result.append(item)
            pending.extend(item.childItems())
        return result

    def _layout_drop_areas(self) -> list[QQuickItem]:
        return [
            item
            for item in self._layout_visual_items()
            if item.metaObject().className().endswith("DropArea")
        ]

    def _drop_layout_group(self, group: str, target: QQuickItem) -> None:
        point = target.mapToScene(QPointF(target.width() / 2, target.height() / 2))
        mime = QMimeData()
        mime.setText(group)
        position = point.toPoint()
        enter = QDragEnterEvent(
            position,
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QCoreApplication.sendEvent(self.window, enter)
        self.assertTrue(enter.isAccepted(), "QML layout DropArea rejected text/plain drag enter")
        move = QDragMoveEvent(
            position,
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QCoreApplication.sendEvent(self.window, move)
        drop = QDropEvent(
            point,
            Qt.DropAction.MoveAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QCoreApplication.sendEvent(self.window, drop)
        self.assertTrue(drop.isAccepted(), "QML layout DropArea did not accept the group drop")
        QTest.qWait(50)

    def _assert_layout_order_persisted(self, expected: list[str]) -> None:
        QTest.qWait(80)
        bridge: NewsBridge = self.controllers["newsController"]
        self.assertEqual(
            bridge.state["layout"].get("order"),
            expected,
            f"bridge state={bridge.state['layout']!r}; notice={self.news_card.property('notice')!r}",
        )
        stored = get_app_setting(self.database_path, LAYOUT_SETTING)
        self.assertEqual(stored["order"], expected)
        self.assertEqual(self._layout_row_order(), expected)

    def test_empty_issue_summary_does_not_claim_an_issue_is_published(self) -> None:
        status = self.window.findChild(QObject, "newsIssueSummaryStatus")
        description = self.window.findChild(QObject, "newsIssueSummaryDescription")
        counts = self.window.findChild(QObject, "newsIssueCounts")
        content_header = self.window.findChild(QObject, "newsIssueContentHeader")

        self.assertIsNotNone(status)
        self.assertIsNotNone(description)
        self.assertIsNotNone(counts)
        self.assertIsNotNone(content_header)
        self.assertEqual(status.property("text"), "尚未发布刊期")
        self.assertEqual(
            description.property("text"),
            "导入并发布本期 JSON 后，这里会显示刊期摘要。",
        )
        self.assertFalse(counts.property("visible"))
        self.assertFalse(
            content_header.property("visible"),
            "the empty issue should not repeat its state in the content header",
        )

    def test_expanded_news_workspace_remains_scrollable_at_minimum_window_size(self) -> None:
        issue = _synthetic_issue()
        issue["topic"] = "窄窗工作台合成刊期"
        article = issue["focus"][0]
        issue["articles"] = [
            {
                **article,
                "id": f"synthetic-compact-article-{index}",
                "title": f"窄窗工作台测试文章 {index}",
                "summary": "用于检查窄窗滚动范围的合成摘要。" * 3,
                "body": ["用于界面集成测试的合成正文。" * 5 for _ in range(3)],
            }
            for index in range(12)
        ]
        bridge: NewsBridge = self.controllers["newsController"]
        preview = bridge.previewJson(json.dumps(issue, ensure_ascii=False))
        self.assertTrue(preview["ok"], preview)
        saved = bridge.saveDraft()
        self.assertTrue(saved["ok"], saved)

        self.window.resize(760, 620)
        QTest.qWait(120)

        scroll = self.window.findChild(QObject, "newsWorkspaceScroll")
        self.assertIsNotNone(scroll)
        inner_flickable = scroll.property("contentItem")
        self.assertIsNotNone(inner_flickable)
        viewport_height = float(inner_flickable.property("height"))
        content_height = float(inner_flickable.property("contentHeight"))
        self.assertGreater(viewport_height, 120.0)
        self.assertGreater(
            content_height,
            viewport_height,
            "a long issue should use the editor's inner scroll area instead of overflowing the card",
        )

        controls = [
            "newsWorkspaceHeader",
            "newsWorkspaceMoreButton",
            "newsWorkspaceCollapseButton",
            "newsPreferencesButton",
            "newsClippingsButton",
            "newsSavedKnowledgeButton",
            "newsPasteButton",
            "newsOpenFileButton",
        ]
        for object_name in controls:
            with self.subTest(control=object_name):
                control = self.window.findChild(QObject, object_name)
                self.assertIsNotNone(control, f"{object_name} was not created")
                self.assertTrue(control.isVisible(), f"{object_name} is hidden in the expanded workspace")
                x = float(control.mapToItem(self.news_card, 0, 0).x())
                self.assertGreaterEqual(x, -1.0, f"{object_name} extends past the left side of the card")
                self.assertLessEqual(
                    x + float(control.property("width")),
                    float(self.news_card.property("width")) + 1.0,
                    f"{object_name} extends past the right side of the card",
                )

        max_scroll = content_height - viewport_height
        self.assertTrue(inner_flickable.setProperty("contentY", max_scroll))
        QTest.qWait(80)
        self.assertGreater(float(inner_flickable.property("contentY")), 0.0)
        self.assertTrue(inner_flickable.setProperty("contentY", 0.0))
        self._visible_drop_point()
        image = self.window.grabWindow()
        self.assertFalse(image.isNull(), "minimum-size workspace screenshot failed")
        evidence_path = (
            self.native_dir
            / "qa-release"
            / "ui-runtime-review"
            / "news-workspace-compact-760x620-2026-09-28.png"
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        self.assertTrue(image.save(str(evidence_path)), f"could not save {evidence_path}")

    def test_mouse_wheel_moves_editor_then_continues_outer_page_at_inner_edge(self) -> None:
        issue = _synthetic_issue()
        article = issue["focus"][0]
        issue["articles"] = [
            {
                **article,
                "id": f"synthetic-wheel-article-{index}",
                "title": f"滚轮交接测试文章 {index}",
                "body": ["用于滚轮事件测试的合成正文。" * 6 for _ in range(4)],
            }
            for index in range(12)
        ]
        bridge: NewsBridge = self.controllers["newsController"]
        preview = bridge.previewJson(json.dumps(issue, ensure_ascii=False))
        self.assertTrue(preview["ok"], preview)
        saved = bridge.saveDraft()
        self.assertTrue(saved["ok"], saved)
        self.window.resize(760, 620)
        QTest.qWait(120)

        scroll = self.window.findChild(QObject, "newsWorkspaceScroll")
        inner = scroll.property("contentItem")
        outer = self.scroll.property("contentItem")
        self.assertIsNotNone(scroll)
        self.assertIsNotNone(inner)
        self.assertIsNotNone(outer)
        self.assertGreater(
            float(inner.property("contentHeight")), float(inner.property("height"))
        )

        scroll_view_top = self.scroll.mapToScene(QPointF(0, 0)).y()
        scroll_view_bottom = scroll_view_top + float(self.scroll.property("height"))
        inner_center = inner.mapToScene(QPointF(
            float(inner.property("width")) / 2,
            float(inner.property("height")) / 2,
        )).y()
        desired_center = (scroll_view_top + scroll_view_bottom) / 2
        outer_max = max(
            0.0,
            float(outer.property("contentHeight")) - float(outer.property("height")),
        )
        outer_y = float(outer.property("contentY"))
        outer.setProperty("contentY", min(max(outer_y + inner_center - desired_center, 0.0), outer_max))
        QTest.qWait(80)

        def send_wheel(vertical_delta: int) -> None:
            center = inner.mapToScene(QPointF(
                float(inner.property("width")) / 2,
                float(inner.property("height")) / 2,
            ))
            local = QPointF(center.x(), center.y())
            global_pos = self.window.mapToGlobal(center.toPoint())
            event = QWheelEvent(
                local,
                QPointF(global_pos),
                QPoint(0, 0),
                QPoint(0, vertical_delta),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            )
            self.assertTrue(QCoreApplication.sendEvent(self.window, event))
            QTest.qWait(60)

        outer_before_inner_scroll = float(outer.property("contentY"))
        send_wheel(-120)
        self.assertGreater(float(inner.property("contentY")), 0.0)
        self.assertEqual(float(outer.property("contentY")), outer_before_inner_scroll)

        inner_max = max(
            0.0,
            float(inner.property("contentHeight")) - float(inner.property("height")),
        )
        inner.setProperty("contentY", max(0.0, inner_max - 12.0))
        outer_before_handoff = float(outer.property("contentY"))
        send_wheel(-120)
        self.assertAlmostEqual(float(inner.property("contentY")), inner_max, delta=1.0)
        self.assertAlmostEqual(
            float(outer.property("contentY")) - outer_before_handoff,
            36.0,
            delta=2.0,
            msg="only the part of the wheel delta past the editor's lower edge should reach the page",
        )

        inner.setProperty("contentY", 0.0)
        outer_before_top_handoff = float(outer.property("contentY"))
        send_wheel(120)
        self.assertEqual(float(inner.property("contentY")), 0.0)
        self.assertAlmostEqual(
            float(outer.property("contentY")) - outer_before_top_handoff,
            -48.0,
            delta=2.0,
            msg="wheel-up at the editor's top edge should continue the daily page upward",
        )

    def test_weather_query_saves_manual_city_and_restart_reuses_it_without_network(self) -> None:
        weather: WeatherBridge = self.controllers["weatherController"]
        requested_ids: list[int] = []
        # Stub the geocoding boundary so this production-QML test stays offline.
        weather._request_geocoding = lambda query_id: requested_ids.append(query_id)

        city_input = self.window.findChild(QObject, "weatherCityInput")
        self.assertIsNotNone(city_input)
        city_input.setProperty("text", "合成天气城")
        self._click("queryWeatherButton")

        self.assertEqual(requested_ids, [weather._query_id])
        self.assertEqual(weather.city, "合成天气城")
        self.assertEqual(
            get_app_setting(self.database_path, "dailyFlowCity"), "合成天气城"
        )
        weather._fail("天气服务暂不可用，请检查网络后重试。", weather._query_id)
        error_text = self.window.findChild(QObject, "weatherErrorText")
        self.assertIsNotNone(error_text)
        self.assertTrue(error_text.property("visible"))
        self.assertIn("检查网络后重试", error_text.property("text"))
        self.assertEqual(
            get_app_setting(self.database_path, "dailyFlowCity"), "合成天气城"
        )

        restarted = WeatherBridge(self.database_path, {})
        self.assertEqual(restarted.city, "合成天气城")
        resumed_ids: list[int] = []
        restarted._request_geocoding = lambda query_id: resumed_ids.append(query_id)
        restarted.querySavedCity()
        self.assertEqual(resumed_ids, [restarted._query_id])
        self.assertEqual(
            get_app_setting(self.database_path, "dailyFlowCity"), "合成天气城"
        )

    def test_https_link_enters_inbox_without_changing_issue_state(self) -> None:
        bridge: NewsBridge = self.controllers["newsController"]
        link = QUrl("https://news.example.org/synthetic-drop")
        self._drop_urls([link])

        inbox = bridge.state["linkInbox"]
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["url"], link.toString())
        self.assertIsNone(bridge.state["draft"])
        self.assertIsNone(bridge.state["active"])
        self.assertEqual(get_app_setting(self.database_path, DRAFT_SETTING), None)
        self.assertEqual(get_app_setting(self.database_path, ISSUE_SETTING), None)
        self.assertIn("本地素材箱", self.news_card.property("notice"))

    def test_saved_link_has_a_direct_open_action(self) -> None:
        bridge: NewsBridge = self.controllers["newsController"]
        link = "https://news.example.org/saved-link"
        self.assertTrue(bridge.addLink(link)["ok"])

        class ExternalUrlCapture(QObject):
            def __init__(self) -> None:
                super().__init__()
                self.urls: list[str] = []

            @Slot(QUrl)
            def capture(self, url: QUrl) -> None:
                self.urls.append(url.toString())

        capture = ExternalUrlCapture()
        QDesktopServices.setUrlHandler("https", capture, "capture")
        try:
            button = self._click("newsLinkOpen_0")
            interface = QAccessible.queryAccessibleInterface(button)
            self.assertIsNotNone(interface)
            self.assertEqual(interface.text(QAccessible.Text.Name), "打开素材链接")
            self.assertEqual(capture.urls, [link])
            self.assertEqual(bridge.state["linkInbox"][0]["url"], link)
        finally:
            QDesktopServices.unsetUrlHandler("https")

    def test_unsupported_dropped_link_has_clear_next_step(self) -> None:
        bridge: NewsBridge = self.controllers["newsController"]
        self._drop_urls([QUrl("ftp://news.example.org/synthetic-drop")])

        self.assertTrue(self.news_card.property("noticeIsError"))
        self.assertIn(".json 文件", self.news_card.property("notice"))
        self.assertIn("https://", self.news_card.property("notice"))
        self.assertEqual(bridge.state["linkInbox"], [])
        self.assertIsNone(bridge.state["draft"])
        self.assertIsNone(bridge.state["active"])

    def test_json_file_drop_opens_unsaved_preview_without_using_link_inbox(self) -> None:
        bridge: NewsBridge = self.controllers["newsController"]

        json_path = self.temp_path / "synthetic-issue.json"
        json_path.write_text(
            json.dumps(_synthetic_issue(), ensure_ascii=False), encoding="utf-8"
        )
        self._drop_urls([QUrl.fromLocalFile(str(json_path))])

        state = bridge.state
        preview = self.news_card.property("previewIssue")
        self.assertTrue(state["draftUnsaved"])
        self.assertEqual(state["draft"]["topic"], "合成拖放测试刊期")
        self.assertEqual(preview["topic"], "合成拖放测试刊期")
        preview_dialogs = [
            child
            for child in self.window.findChildren(QObject)
            if child.property("title") == "新闻刊期预览"
        ]
        self.assertTrue(preview_dialogs, "QML preview dialog was not created")
        self.assertTrue(
            any(dialog.property("visible") for dialog in preview_dialogs),
            "JSON drop did not open the production preview dialog",
        )
        self.assertIsNone(state["active"], "drop preview must not publish the issue")
        self.assertIsNone(
            get_app_setting(self.database_path, DRAFT_SETTING),
            "drop preview must not save a draft before explicit confirmation",
        )
        self.assertIsNone(
            get_app_setting(self.database_path, ISSUE_SETTING),
            "drop preview must not persist or publish an issue",
        )
        self.assertEqual(bridge.state["linkInbox"], [])

    def test_news_item_reordering_through_production_qml_persists_after_save(self) -> None:
        bridge: NewsBridge = self.controllers["newsController"]
        issue = _synthetic_issue()
        first = issue["focus"][0]
        second = {
            **first,
            "id": "synthetic-focus-2",
            "title": "第二条仅用于排版验收的合成标题",
        }
        issue["focus"].append(second)
        self.assertTrue(bridge.previewJson(json.dumps(issue, ensure_ascii=False))["ok"])
        self.assertTrue(bridge.saveDraft()["ok"])

        original_order = [item["id"] for item in bridge.state["draft"]["focus"]]
        self.assertEqual(original_order, [first["id"], second["id"]])
        self._click("newsMoveUp_focus_1")
        moved_order = [item["id"] for item in bridge.state["draft"]["focus"]]
        self.assertEqual(moved_order, [second["id"], first["id"]])
        self.assertTrue(bridge.state["draftUnsaved"])
        self.assertEqual(
            [item["id"] for item in get_app_setting(self.database_path, DRAFT_SETTING)["focus"]],
            original_order,
            "reordering should remain an explicit unsaved change until Save Draft is clicked",
        )

        self._click("newsSaveDraftButton")
        self.assertEqual(
            [item["id"] for item in get_app_setting(self.database_path, DRAFT_SETTING)["focus"]],
            moved_order,
        )
        self.assertEqual(
            [item["id"] for item in NewsBridge(self.database_path).state["draft"]["focus"]],
            moved_order,
        )

        self._click("newsMoveDown_focus_0")
        restored_order = [item["id"] for item in bridge.state["draft"]["focus"]]
        self.assertEqual(restored_order, original_order)
        self._click("newsSaveDraftButton")
        self.assertEqual(
            [item["id"] for item in NewsBridge(self.database_path).state["draft"]["focus"]],
            original_order,
        )

    def test_invalid_json_message_stays_readable_in_edit_dialog(self) -> None:
        bridge: NewsBridge = self.controllers["newsController"]
        self._click("newsPasteButton")
        edit_dialog = self._dialog("粘贴或编辑新闻 JSON")
        editor = self.window.findChild(QObject, "newsJsonInput")
        self.assertIsNotNone(editor)
        editor.setProperty("text", "{ invalid json")

        self._click("newsPreviewButton")

        self.assertTrue(edit_dialog.property("visible"))
        self.assertTrue(self.news_card.property("noticeIsError"))
        message = str(self.news_card.property("notice"))
        self.assertIn("JSON", message)
        self.assertIn("第 1 行", message)
        self.assertIn("列", message)
        self.assertIsNone(get_app_setting(self.database_path, DRAFT_SETTING))
        self.assertIsNone(get_app_setting(self.database_path, ISSUE_SETTING))
        self.assertEqual(bridge.state["linkInbox"], [])

    def test_preview_save_publish_history_load_and_database_round_trip(self) -> None:
        bridge: NewsBridge = self.controllers["newsController"]

        first_path = self.temp_path / "first-issue.json"
        first_issue = _synthetic_issue()
        first_issue["topic"] = "合成第一期"
        first_path.write_text(json.dumps(first_issue, ensure_ascii=False), encoding="utf-8")
        self._drop_urls([QUrl.fromLocalFile(str(first_path))])
        self.assertTrue(self._dialog("新闻刊期预览").property("visible"))
        self.assertIsNone(get_app_setting(self.database_path, DRAFT_SETTING))
        self.assertIsNone(get_app_setting(self.database_path, ISSUE_SETTING))

        self._click("newsPreviewSaveDraftButton")
        preview_dialog = self.window.findChild(QObject, "newsPreviewDialog")
        self.assertIsNotNone(preview_dialog)
        self.assertFalse(preview_dialog.property("visible"))
        self.assertEqual(bridge.state["draft"]["topic"], "合成第一期")
        content_header = self.window.findChild(QObject, "newsIssueContentHeader")
        self.assertIsNotNone(content_header)
        self.assertTrue(content_header.property("visible"))
        self.assertIsNone(bridge.state["active"])
        persisted_draft = get_app_setting(self.database_path, DRAFT_SETTING)
        self.assertEqual(persisted_draft["topic"], "合成第一期")
        self.assertEqual(
            NewsBridge(self.database_path).state["draft"]["topic"], "合成第一期"
        )

        self._click("newsPublishButton")
        self._dialog("确认发布本期新闻")
        self._click("newsConfirmPublishButton")
        self.assertEqual(bridge.state["active"]["topic"], "合成第一期")
        self.assertIsNone(bridge.state["draft"])
        self.assertEqual(
            get_app_setting(self.database_path, ISSUE_SETTING)["active"]["topic"],
            "合成第一期",
        )

        second_path = self.temp_path / "second-issue.json"
        second_issue = _synthetic_issue()
        second_issue["topic"] = "合成第二期"
        second_path.write_text(json.dumps(second_issue, ensure_ascii=False), encoding="utf-8")
        self._drop_urls([QUrl.fromLocalFile(str(second_path))])
        self._dialog("新闻刊期预览")
        self._click("newsPreviewSaveDraftButton")
        self._click("newsPublishButton")
        self._dialog("确认发布本期新闻")
        self._click("newsConfirmPublishButton")

        state = bridge.state
        self.assertEqual(state["active"]["topic"], "合成第二期")
        self.assertEqual(state["archive"][0]["issue"]["topic"], "合成第一期")
        selector = self.window.findChild(QObject, "newsHistorySelector")
        self.assertIsNotNone(selector)
        self.assertIn("合成第一期", str(selector.property("model")))
        selector.setProperty("currentIndex", 1)
        self.assertTrue(
            QMetaObject.invokeMethod(
                selector,
                "activated",
                Qt.ConnectionType.DirectConnection,
                Q_ARG(int, 1),
            ),
            "history selector did not expose its production activation signal",
        )
        preview_dialog = self._dialog("预览历史刊期")
        self.assertTrue(preview_dialog.property("visible"))
        self.assertIsNone(bridge.state["draft"])
        self._click("newsHistoryPreviewLoadButton")
        self.assertEqual(bridge.state["draft"]["topic"], "合成第一期")
        self.assertEqual(bridge.state["active"]["topic"], "合成第二期")
        reopened = NewsBridge(self.database_path)
        self.assertEqual(reopened.state["draft"]["topic"], "合成第一期")
        self.assertEqual(reopened.state["active"]["topic"], "合成第二期")

    def test_history_load_requires_confirmation_when_a_draft_exists(self) -> None:
        bridge: NewsBridge = self.controllers["newsController"]

        for topic in ("需要保留的已发布刊期", "当前已发布刊期"):
            issue = _synthetic_issue()
            issue["topic"] = topic
            self.assertTrue(bridge.previewJson(json.dumps(issue, ensure_ascii=False))["ok"])
            self.assertTrue(bridge.saveDraft()["ok"])
            self.assertTrue(bridge.publishDraft()["ok"])

        unsaved = _synthetic_issue()
        unsaved["topic"] = "尚未保存的当前预览"
        self.assertTrue(bridge.previewJson(json.dumps(unsaved, ensure_ascii=False))["ok"])
        QTest.qWait(80)

        selector = self.window.findChild(QObject, "newsHistorySelector")
        self.assertIsNotNone(selector)
        selector.setProperty("currentIndex", 1)
        self.assertTrue(
            QMetaObject.invokeMethod(
                selector,
                "activated",
                Qt.ConnectionType.DirectConnection,
                Q_ARG(int, 1),
            )
        )
        preview_dialog = self._dialog("预览历史刊期")
        self.assertTrue(preview_dialog.property("visible"))
        self.assertEqual(bridge.state["draft"]["topic"], "尚未保存的当前预览")
        self._click("newsHistoryPreviewLoadButton")
        replace_dialog = self._dialog("载入历史刊期？")
        self.assertTrue(replace_dialog.property("visible"))
        self.assertEqual(str(self.news_card.property("pendingHistoryTopic")), "需要保留的已发布刊期")
        self.assertTrue(str(self.window.findChild(QObject, "newsHistoryReplaceSummary").property("text")))
        self.assertEqual(bridge.state["draft"]["topic"], "尚未保存的当前预览")

        self._click("newsHistoryReplaceCancelButton")
        self.assertFalse(replace_dialog.property("visible"))
        self.assertEqual(int(selector.property("currentIndex")), 0)
        self.assertEqual(bridge.state["draft"]["topic"], "尚未保存的当前预览")

        selector.setProperty("currentIndex", 1)
        self.assertTrue(
            QMetaObject.invokeMethod(
                selector,
                "activated",
                Qt.ConnectionType.DirectConnection,
                Q_ARG(int, 1),
            )
        )
        self.assertTrue(preview_dialog.property("visible"))
        self._click("newsHistoryPreviewLoadButton")
        self.assertTrue(replace_dialog.property("visible"))
        self._click("newsHistoryReplaceConfirmButton")
        self.assertFalse(replace_dialog.property("visible"))
        self.assertEqual(bridge.state["draft"]["topic"], "需要保留的已发布刊期")
        self.assertEqual(int(selector.property("currentIndex")), 0)

    def test_layout_drop_target_and_up_down_buttons_persist_and_refresh(self) -> None:
        self.layout_dialog = self._open_layout_dialog()
        initial = ["focus", "highlights", "articles"]
        self.assertEqual(
            self._layout_row_order(),
            initial,
        )

        for group in initial:
            self.assertIsNotNone(self._layout_handle(group))
        drop_areas = sorted(
            self._layout_drop_areas(),
            key=lambda area: area.mapToScene(
                QPointF(area.width() / 2, area.height() / 2)
            ).y(),
        )
        self.assertEqual(len(drop_areas), 3, "expected one QML DropArea per group row")
        for area in drop_areas:
            self.assertEqual(list(area.property("keys")), ["text/plain"])
        self._drop_layout_group("focus", drop_areas[2])
        self._assert_layout_order_persisted(["highlights", "articles", "focus"])

        up = self._layout_control("newsLayoutUp_focus")
        self.assertTrue(up.property("enabled"))
        self.assertTrue(
            QMetaObject.invokeMethod(up, "click", Qt.ConnectionType.DirectConnection)
        )
        self._assert_layout_order_persisted(["highlights", "focus", "articles"])

        down = self._layout_control("newsLayoutDown_highlights")
        self.assertTrue(down.property("enabled"))
        self.assertTrue(
            QMetaObject.invokeMethod(
                down, "click", Qt.ConnectionType.DirectConnection
            )
        )
        self._assert_layout_order_persisted(initial)

    def test_layout_drag_handle_tracks_pointer_and_persists_drop(self) -> None:
        self.layout_dialog = self._open_layout_dialog()
        handle = self._layout_handle("focus")
        areas = sorted(
            self._layout_drop_areas(),
            key=lambda area: area.mapToScene(
                QPointF(area.width() / 2, area.height() / 2)
            ).y(),
        )
        start = handle.mapToScene(QPointF(handle.width() / 2, handle.height() / 2)).toPoint()
        end = areas[2].mapToScene(
            QPointF(areas[2].width() / 2, areas[2].height() / 2)
        ).toPoint()
        drag_window = handle.window()
        QTest.mousePress(drag_window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(drag_window, end, 100)
        QTest.qWait(50)
        self.assertTrue(handle.property("layoutDragActive"))
        self.assertTrue(self.layout_dialog.property("layoutDragging"))
        self.assertEqual(self.layout_dialog.property("layoutDropTargetIndex"), 2)
        QTest.mouseRelease(drag_window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        self._assert_layout_order_persisted(["highlights", "articles", "focus"])

if __name__ == "__main__":
    unittest.main()
