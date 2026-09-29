from __future__ import annotations

from datetime import date, datetime, timedelta
import os
from pathlib import Path
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, QUrl, Slot
from PySide6.QtGui import QAccessible, QDesktopServices
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

from main import DailyBridge, PlannerBridge


class DailyFlowQmlIntegrationTests(unittest.TestCase):
    """Exercise the production daily-flow QML with isolated synthetic SQLite."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.qml_directory = Path(__file__).resolve().parents[1] / "qml"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-daily-qml-")
        self.addCleanup(self.temp_dir.cleanup)
        database_path = Path(self.temp_dir.name) / "synthetic.sqlite3"
        self.database_path = database_path
        self.clock = [datetime.now().astimezone()]
        today = date.today()
        yesterday = (today - timedelta(days=1)).isoformat()
        self.today = today.isoformat()
        snapshot = {
            "documents": {
                "richangji-state-v1": {
                    "settings": {
                        "dailyFlowNotes": {yesterday: "昨天留下的合成跟进"},
                            "dailyFlowFocusTask": "完成今日合成待办",
                    },
                    "records": [
                        {
                            "id": "synthetic-yesterday-record",
                            "type": "money",
                            "date": yesterday,
                            "data": {"category": "合成", "amount": 2, "note": "昨日合成记录"},
                            "createdAt": 20,
                        },
                        {
                            "id": "synthetic-today-task",
                            "type": "planner",
                            "date": self.today,
                            "data": {
                                "title": "完成今日合成待办",
                                "done": False,
                                "list": "工作",
                                "note": "仅用于 UI 集成测试",
                            },
                            "createdAt": 30,
                        },
                    ],
                    "habits": [],
                    "mediaItems": [],
                },
                "wanxiang-issue-questions-v1": [
                    {"text": "昨日合成问题", "createdDate": yesterday, "createdAt": 10}
                ],
            }
        }
        self.daily = DailyBridge(database_path, snapshot, clock=lambda: self.clock[0])
        self.planner = PlannerBridge(database_path, snapshot)
        self.planner._repository._clock = lambda: self.clock[0]
        self.assertEqual(self.daily.review["items"][0]["title"], "昨日合成记录")
        self.assertEqual(self.daily.todayWork["tasks"][0]["title"], "完成今日合成待办")

        self.engine = QQmlApplicationEngine()
        self.addCleanup(self._destroy_engine)
        self.engine.rootContext().setContextProperty("dailyController", self.daily)
        self.engine.rootContext().setContextProperty("plannerController", self.planner)
        qml_url = QUrl.fromLocalFile(str(self.qml_directory).replace("\\", "/") + "/")
        wrapper_url = QUrl.fromLocalFile(str(self.qml_directory / "DailyFlowIntegration.qml"))
        source = (
            "import QtQuick\n"
            "import QtQuick.Controls\n"
            f'import "{qml_url.toString()}" as Native\n'
            "ApplicationWindow {\n"
            "  visible: true; width: 1320; height: 1120\n"
            "  Native.DailyFlowPage {\n"
            "    objectName: \"dailyFlowUnderTest\"\n"
            "    anchors.fill: parent\n"
            "    controller: dailyController\n"
            "    plannerBridge: plannerController\n"
            "  }\n"
            "}\n"
        )
        component = QQmlComponent(self.engine)
        self.component = component
        component.setData(source.encode("utf-8"), wrapper_url)
        self.assertFalse(component.isError(), "\n".join(e.toString() for e in component.errors()))
        self.window = component.create()
        self.assertIsNotNone(self.window, "\n".join(e.toString() for e in component.errors()))
        self.page = self.window.findChild(QObject, "dailyFlowUnderTest")
        self.assertIsNotNone(self.page)
        self.window.show()
        QTest.qWait(100)

    def _destroy_engine(self) -> None:
        if getattr(self, "engine", None) is not None:
            self.engine.deleteLater()
            QTest.qWait(20)

    def _click(self, object_name: str) -> QObject:
        button = self.window.findChild(QObject, object_name) or self._visual_item(object_name)
        self.assertIsNotNone(button, f"QML control {object_name} was not found")
        self.assertTrue(
            QMetaObject.invokeMethod(button, "click", Qt.ConnectionType.DirectConnection),
            f"QML control {object_name} did not expose click()",
        )
        QTest.qWait(35)
        return button

    def _visual_item(self, object_name: str) -> QQuickItem | None:
        pending = [self.page]
        while pending:
            item = pending.pop()
            if item.objectName() == object_name:
                return item
            pending.extend(item.childItems())
        return None

    def _activate_focus_candidate(self, index: int) -> QQuickItem:
        selector = self._visual_item("dailyFocusCandidateSelector")
        self.assertIsNotNone(selector, "focus task selector was not found")
        invoked = QMetaObject.invokeMethod(
            selector,
            "activated",
            Qt.ConnectionType.DirectConnection,
            Q_ARG(int, index + 1),
        )
        self.assertTrue(invoked, "focus task selector did not expose activation")
        QTest.qWait(80)
        return selector

    def _activate_focus_mode(self, index: int) -> QQuickItem:
        selector = self._visual_item("dailyFocusModeSelector")
        self.assertIsNotNone(selector, "focus mode selector was not found")
        invoked = QMetaObject.invokeMethod(
            selector,
            "activated",
            Qt.ConnectionType.DirectConnection,
            Q_ARG(int, index),
        )
        self.assertTrue(invoked, "focus mode selector did not expose activation")
        QTest.qWait(80)
        return selector

    def test_daily_sections_follow_the_top_level_four_step_numbering(self) -> None:
        expected = {
            "dailySectionNumber_02": "02",
            "dailySectionNumber_03": "03",
            "dailySectionNumber_04": "04",
        }
        for object_name, number in expected.items():
            with self.subTest(section=object_name):
                item = self._visual_item(object_name)
                self.assertIsNotNone(item, f"section number {object_name} was not found")
                self.assertEqual(str(item.property("text")), number)

    def test_focus_candidate_selector_names_its_task_role(self) -> None:
        selector = self._visual_item("dailyFocusCandidateSelector")
        self.assertIsNotNone(selector)
        interface = QAccessible.queryAccessibleInterface(selector)
        self.assertIsNotNone(interface)
        self.assertEqual(str(interface.text(QAccessible.Text.Name)), "专注任务")

    def test_empty_yesterday_review_does_not_stretch_its_message_card(self) -> None:
        self.daily.updateActivity(records=[], habits=[], media_items=[])
        QTest.qWait(60)

        empty_card = self._visual_item("dailyReviewEmptyCard")
        self.assertIsNotNone(empty_card)
        self.assertTrue(empty_card.property("visible"))
        self.assertLessEqual(float(empty_card.property("height")), 100.0)

    def test_yesterday_review_questions_today_work_and_linked_focus_round_trip(self) -> None:
        self.assertEqual(self.window.findChild(QObject, "dailyReviewCount").property("text"), "1 条")
        self.assertIn(
            "昨天留下的合成跟进",
            self.window.findChild(QObject, "dailyYesterdayFollowUp").property("text"),
        )
        self.assertEqual(self.window.findChild(QObject, "dailyTaskCount").property("text"), "1 项")
        self.assertEqual(self.daily.state["questions"][0]["text"], "昨日合成问题")
        candidate_selector = self._visual_item("dailyFocusCandidateSelector")
        self.assertIsNotNone(
            candidate_selector,
            f"focus selector missing; planner={self.planner.state!r}; candidates={self.page.property('focusCandidates').toVariant()!r}; today={self.page.property('todayDateKey')!r}",
        )
        self.assertEqual(int(candidate_selector.property("count")), 2)
        self.assertEqual(int(candidate_selector.property("currentIndex")), 1)

        follow_up = self.window.findChild(QObject, "dailyFollowUpInput")
        follow_up.setProperty("text", "今日填写的合成跟进")
        self._click("dailyFollowUpSaveButton")
        self.assertEqual(self.daily.state["notes"][self.today], "今日填写的合成跟进")
        self.assertEqual(
            DailyBridge(self.database_path).state["notes"][self.today],
            "今日填写的合成跟进",
        )

        question_input = self.window.findChild(QObject, "dailyQuestionInput")
        question_button = self._click("dailyQuestionAddButton")
        self.assertFalse(bool(question_button.property("enabled")))
        limit_hint = self._visual_item("dailyQuestionLimitHint")
        self.assertIsNotNone(limit_hint)
        self.assertEqual(
            str(limit_hint.property("text")),
            "最多保留 12 条；新增会替换最早一条",
        )
        question_input.setProperty("text", "   ")
        self.assertFalse(bool(question_button.property("enabled")))
        self.assertTrue(
            QMetaObject.invokeMethod(
                self.page,
                "addQuestionDraft",
                Qt.ConnectionType.DirectConnection,
            )
        )
        QTest.qWait(35)
        self.assertEqual(len(self.daily.state["questions"]), 1)
        question_input.setProperty("text", "今天要确认的合成问题")
        self.assertTrue(bool(question_button.property("enabled")))
        self._click("dailyQuestionAddButton")
        self.assertEqual(self.daily.state["questions"][0]["text"], "今天要确认的合成问题")
        self.assertIsNotNone(self._visual_item("dailyQuestionRemove_0"))

        self.assertEqual(self.daily.state["focusTask"], "完成今日合成待办")
        self.assertEqual(self.window.findChild(QObject, "dailyFocusTaskInput").property("text"), "完成今日合成待办")

        self._click("dailyFocusToggleButton")
        self.assertTrue(self.daily.focusRunning)
        self.assertEqual(self.planner.state["activeTracking"]["taskId"], "synthetic-today-task")
        self.assertEqual(
            self.window.findChild(QObject, "dailyFocusToggleButton").property("text"),
            "暂停",
        )
        focus_task_input = self.window.findChild(QObject, "dailyFocusTaskInput")
        self.assertFalse(bool(focus_task_input.property("enabled")))
        candidate_selector = self._visual_item("dailyFocusCandidateSelector")
        self.assertIsNotNone(candidate_selector)
        self.assertFalse(bool(candidate_selector.property("enabled")))
        self.assertEqual(int(candidate_selector.property("currentIndex")), 1)

        self.clock[0] += timedelta(minutes=3, seconds=30)
        self._click("dailyFocusToggleButton")
        self.assertFalse(self.daily.focusRunning)
        self.assertEqual(self.planner.state["activeTracking"]["taskId"], "synthetic-today-task")
        self.assertTrue(self.planner.state["activeTracking"]["paused"])
        tracked_data = self.planner._repository._target("synthetic-today-task")["data"]
        self.assertEqual(tracked_data["trackedSeconds"], 210)
        self.assertEqual([session["seconds"] for session in tracked_data["sessions"]], [210])
        self.assertTrue(bool(focus_task_input.property("enabled")))
        candidate_selector = self._visual_item("dailyFocusCandidateSelector")
        self.assertTrue(bool(candidate_selector.property("enabled")))
        reopened_daily = DailyBridge(self.database_path, clock=lambda: self.clock[0])
        reopened_planner = PlannerBridge(self.database_path)
        self.assertEqual(reopened_daily.state["notes"][self.today], "今日填写的合成跟进")
        self.assertEqual(reopened_daily.state["questions"][0]["text"], "今天要确认的合成问题")
        self.assertEqual(reopened_daily.state["focusTask"], "完成今日合成待办")
        self.assertEqual(reopened_planner.state["activeTracking"]["taskId"], "synthetic-today-task")
        self.assertTrue(reopened_planner.state["activeTracking"]["paused"])

    def test_question_removal_requires_confirmation(self) -> None:
        remove_dialog = self.window.findChild(QObject, "dailyQuestionRemoveDialog")
        remove_message = self.window.findChild(QObject, "dailyQuestionRemoveMessage")
        self.assertIsNotNone(remove_dialog)
        self.assertIsNotNone(remove_message)
        self.assertEqual(len(self.daily.state["questions"]), 1)

        self._click("dailyQuestionRemove_0")
        self.assertTrue(remove_dialog.property("visible"))
        self.assertIn("昨日合成问题", str(remove_message.property("text")))
        self.assertEqual(len(self.daily.state["questions"]), 1)

        self._click("dailyQuestionRemoveCancelButton")
        self.assertFalse(remove_dialog.property("visible"))
        self.assertEqual(len(self.daily.state["questions"]), 1)

        self._click("dailyQuestionRemove_0")
        self._click("dailyQuestionRemoveConfirmButton")
        QTest.qWait(60)
        self.assertFalse(remove_dialog.property("visible"))
        self.assertEqual(self.daily.state["questions"], [])

    def test_email_and_spotify_links_dispatch_through_qt_without_launching_apps(self) -> None:
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
            probe = "https://handler-probe.example/safe"
            self.assertTrue(QDesktopServices.openUrl(QUrl(probe)))
            self.assertEqual(capture.urls, [probe])
            capture.urls.clear()

            for control_name, expected_url in (
                ("dailyOpenGmailButton", "https://mail.google.com/mail/u/0/#inbox"),
                ("dailyOpenOutlookButton", "https://outlook.office.com/mail/"),
            ):
                self._click(control_name)
                self.assertEqual(capture.urls, [expected_url], control_name)
                capture.urls.clear()

            spotify_url = "https://open.spotify.com/playlist/0123456789?si=synthetic"
            spotify_input = self.window.findChild(QObject, "dailySpotifyUrlInput")
            self.assertIsNotNone(spotify_input)
            spotify_remove = self.window.findChild(QObject, "dailySpotifyRemoveButton")
            self.assertIsNotNone(spotify_remove)
            self.assertFalse(bool(spotify_remove.property("enabled")))
            spotify_input.setProperty("text", spotify_url)
            self._click("dailySpotifySaveButton")
            self.assertEqual(self.daily.state["spotifyUrl"], spotify_url)
            self.assertTrue(bool(spotify_remove.property("enabled")))

            spotify_open = self.window.findChild(QObject, "dailySpotifyOpenButton")
            self.assertIsNotNone(spotify_open)
            self.assertTrue(bool(spotify_open.property("enabled")))
            self._click("dailySpotifyOpenButton")
            self.assertEqual(capture.urls, [spotify_url])
            capture.urls.clear()

            self._click("dailySpotifyRemoveButton")
            self.assertEqual(self.daily.state["spotifyUrl"], "")
            self.assertFalse(bool(spotify_remove.property("enabled")))

            spotify_input.setProperty("text", "http://open.spotify.com/playlist/0123456789")
            self._click("dailySpotifySaveButton")
            self.assertEqual(self.daily.state["spotifyUrl"], "")
            self.assertEqual(capture.urls, [], "an invalid draft must not be opened")

            legacy_state = dict(self.daily.state)
            legacy_state["spotifyUrl"] = "https://example.org/old-invalid-link"
            self.page.setProperty("stateSnapshot", legacy_state)
            QTest.qWait(30)
            self.assertFalse(bool(spotify_open.property("enabled")))
            self.assertTrue(bool(spotify_remove.property("enabled")))
            self._click("dailySpotifyRemoveButton")
            self.assertEqual(self.daily.state["spotifyUrl"], "")
        finally:
            QDesktopServices.unsetUrlHandler("https")

    def test_focus_mode_selector_and_custom_duration_control(self) -> None:
        mode_selector = self._visual_item("dailyFocusModeSelector")
        duration_input = self._visual_item("dailyFocusDurationInput")
        self.assertIsNotNone(mode_selector)
        self.assertIsNotNone(duration_input)
        self.assertEqual(int(mode_selector.property("count")), 3)
        self.assertFalse(bool(duration_input.property("visible")))

        self._activate_focus_mode(1)
        self.assertEqual(self.daily.state["focusTimer"]["mode"], "flowtime")
        self.assertEqual(self.daily.focusDisplay, "00:00")
        self.assertEqual(self.daily._timer.progress(), 0.0)

        self._activate_focus_mode(2)
        self.assertEqual(self.daily.state["focusTimer"]["mode"], "countdown")
        QTest.qWait(50)
        self.assertTrue(bool(duration_input.property("visible")))
        self.assertEqual(int(duration_input.property("value")), 25)

        self.assertTrue(self.daily.setFocusMode("countdown", 60)["ok"])
        QTest.qWait(60)
        self.assertEqual(self.daily.state["focusTimer"]["durationSeconds"], 3600)
        self.assertEqual(int(duration_input.property("value")), 60)
        self.assertEqual(self.daily.focusDisplay, "60:00")

    def test_focus_qml_countdown_uses_qt_timer_and_finishes_round(self) -> None:
        # Advance an injected clock through the production five-minute minimum.
        self.assertEqual(self.daily._timer.duration_seconds, 25 * 60)
        self.assertTrue(self.daily.setFocusMode("countdown", 5)["ok"])
        QTest.qWait(60)
        display = self.window.findChild(QObject, "dailyFocusDisplay")
        toggle_button = self.window.findChild(QObject, "dailyFocusToggleButton")
        reset_button = self.window.findChild(QObject, "dailyFocusResetButton")
        focus_task_input = self.window.findChild(QObject, "dailyFocusTaskInput")
        for label, control in (
            ("focus display", display),
            ("focus toggle button", toggle_button),
            ("focus reset button", reset_button),
            ("focus task input", focus_task_input),
        ):
            self.assertIsNotNone(control, f"production {label} was not found")

        self.assertEqual(str(display.property("text")), "05:00")
        self.assertEqual(str(toggle_button.property("text")), "开始专注")
        self.assertFalse(bool(reset_button.property("enabled")))
        # Leave this countdown standalone so the assertion isolates the timer
        # path from the separate planner-time tracking workflow.
        focus_task_input.setProperty("text", "")
        self._click("dailyFocusToggleButton")
        self.assertTrue(self.daily.focusRunning)
        self.assertTrue(self.daily._clock.isActive(), "starting focus must start the production Qt timer")
        self.assertTrue(bool(self.page.property("focusRunning")))
        self.assertEqual(str(toggle_button.property("text")), "暂停")
        self.assertTrue(bool(reset_button.property("enabled")))

        self.clock[0] += timedelta(minutes=5)
        self.daily.tickFocus()
        QTest.qWait(80)

        self.assertFalse(self.daily.focusRunning, "the running Qt timer did not finish the synthetic round")
        self.assertFalse(self.daily._clock.isActive(), "the production Qt timer must stop at zero")
        self.assertEqual(self.daily.focusDisplay, "00:00")
        self.assertEqual(str(display.property("text")), "00:00")
        self.assertFalse(bool(self.page.property("focusRunning")))
        self.assertEqual(float(self.page.property("focusProgress")), 1.0)
        self.assertEqual(str(toggle_button.property("text")), "再来一轮")

        self._click("dailyFocusToggleButton")
        self.assertTrue(self.daily.focusRunning)
        self.assertTrue(self.daily._clock.isActive())
        self.assertEqual(self.daily.focusDisplay, "05:00")
        self.assertEqual(str(display.property("text")), "05:00")
        self.assertEqual(float(self.page.property("focusProgress")), 0.0)
        self.assertEqual(str(toggle_button.property("text")), "暂停")

        self._click("dailyFocusResetButton")
        self.assertFalse(self.daily.focusRunning)
        self.assertFalse(self.daily._clock.isActive(), "reset must stop the production Qt timer")
        self.assertEqual(self.daily.focusDisplay, "05:00")
        self.assertEqual(str(display.property("text")), "05:00")
        self.assertEqual(float(self.page.property("focusProgress")), 0.0)
        self.assertEqual(str(toggle_button.property("text")), "开始专注")
        self.assertFalse(bool(reset_button.property("enabled")))

    def test_focus_task_selector_stays_compact_with_many_today_tasks(self) -> None:
        self.daily.saveFocusTask("没有匹配日程的专注任务")
        QTest.qWait(80)
        selector = self._visual_item("dailyFocusCandidateSelector")
        self.assertIsNotNone(selector)
        self.assertEqual(int(selector.property("currentIndex")), 0)

        for index in range(24):
            result = self.planner.addTask(
                f"合成今日任务 {index + 1}", self.today, "", "normal", "工作", "",
                False, 30, "none",
            )
            self.assertTrue(result["ok"], result)
        QTest.qWait(120)

        selector = self._visual_item("dailyFocusCandidateSelector")
        self.assertIsNotNone(selector)
        self.assertEqual(int(selector.property("count")), 26)
        self.assertLessEqual(
            float(selector.property("height")),
            48,
            "A long task list should not expand the focus panel into a stack of buttons.",
        )
        candidates = self.page.property("focusCandidates").toVariant()
        last_title = candidates[-1]["title"]
        self._activate_focus_candidate(len(candidates) - 1)
        self.assertEqual(self.daily.state["focusTask"], last_title)
        self.assertEqual(
            self.window.findChild(QObject, "dailyFocusTaskInput").property("text"),
            last_title,
        )

    def test_empty_yesterday_review_placeholder_stays_near_its_heading(self) -> None:
        self.page.setProperty(
            "reviewSnapshot",
            {"date": "2026-09-27", "count": 0, "items": [], "emptyMessage": "昨天还没有记录。"},
        )
        QTest.qWait(80)

        empty = self._visual_item("dailyReviewEmpty")
        empty_card = self._visual_item("dailyReviewEmptyCard")
        header = self._visual_item("dailyReviewListHeader")
        column = self._visual_item("dailyReviewRecordColumn")
        grid = self._visual_item("dailyReviewGrid")
        self.assertIsNotNone(empty)
        self.assertIsNotNone(empty_card)
        self.assertIsNotNone(header)
        self.assertIsNotNone(column)
        self.assertIsNotNone(grid)
        self.assertTrue(empty.isVisible())
        self.assertTrue(empty_card.isVisible())
        header_y = header.mapToItem(grid, 0, 0).y()
        self.assertLessEqual(
            header_y,
            20,
            "The review list should align with the top of the review grid.",
        )
        empty_card_y = empty_card.mapToItem(column, 0, 0).y()
        header_bottom = header.mapToItem(column, 0, header.height()).y()
        self.assertLessEqual(
            empty_card_y - header_bottom,
            24,
            "The empty review panel should begin directly below its heading.",
        )
        self.assertGreaterEqual(empty_card.height(), 92)
        self.assertLessEqual(
            empty_card.height(),
            110,
            "An empty review should not fill the height of the follow-up editor.",
        )


if __name__ == "__main__":
    unittest.main()
