from __future__ import annotations

from datetime import date, datetime, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (
    QMetaObject,
    QObject,
    QPointF,
    Qt,
    QUrl,
    Q_ARG,
    Q_RETURN_ARG,
)
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from PySide6.QtGui import QAccessible, QFont, QFontDatabase

from main import PlannerBridge
from wanxiang.localization import LocalizationBridge, LocalizationRepository


class PlannerPageQmlIntegrationTests(unittest.TestCase):
    """Exercise the production planner form against isolated local storage."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        font_path = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "NotoSansSC-VF.ttf"
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        font_families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        if font_families:
            cls.app.setFont(QFont(font_families[0], 10))
        cls.qml_directory = Path(__file__).resolve().parents[1] / "qml"

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-planner-qml-")
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "synthetic.sqlite3"
        self.planner = PlannerBridge(self.database_path)
        self.engine = QQmlApplicationEngine()
        self.addCleanup(self._destroy_engine)
        self.engine.rootContext().setContextProperty("plannerController", self.planner)
        qml_url = QUrl.fromLocalFile(str(self.qml_directory).replace("\\", "/") + "/")
        wrapper_url = QUrl.fromLocalFile(str(self.qml_directory / "PlannerIntegration.qml"))
        source = (
            "import QtQuick\n"
            "import QtQuick.Controls\n"
            f'import "{qml_url.toString()}" as Native\n'
            "ApplicationWindow {\n"
            "  visible: true; width: 1280; height: 1000\n"
            "  Native.PlannerPage {\n"
            "    objectName: \"plannerUnderTest\"\n"
            "    anchors.fill: parent\n"
            "    controller: plannerController\n"
            "  }\n"
            "}\n"
        )
        component = QQmlComponent(self.engine)
        self.component = component
        component.setData(source.encode("utf-8"), wrapper_url)
        self.assertFalse(component.isError(), "\n".join(e.toString() for e in component.errors()))
        self.window = component.create()
        self.assertIsNotNone(self.window, "\n".join(e.toString() for e in component.errors()))
        self.page = self.window.findChild(QObject, "plannerUnderTest")
        self.assertIsNotNone(self.page)
        self.window.show()
        QTest.qWait(100)

    def _destroy_engine(self) -> None:
        if getattr(self, "engine", None) is not None:
            self.engine.deleteLater()
            QTest.qWait(20)

    def _visual_item(self, object_name: str) -> QQuickItem | None:
        pending = [self.window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == object_name:
                return item
            pending.extend(item.childItems())
        return None

    def _click(self, object_name: str) -> QQuickItem:
        item = self._visual_item(object_name)
        self.assertIsNotNone(item, f"QML control {object_name} was not found")
        self.assertTrue(
            QMetaObject.invokeMethod(item, "click", Qt.ConnectionType.DirectConnection),
            f"QML control {object_name} did not expose click()",
        )
        QTest.qWait(35)
        return item

    def test_task_form_and_filters_have_distinct_accessible_names(self) -> None:
        for object_name, expected_text in {
            "plannerDateLabel": "日期",
            "plannerTimeLabel": "时间",
            "plannerListLabel": "任务清单",
            "plannerPriorityLabel": "任务优先级",
        }.items():
            with self.subTest(label=object_name):
                label = self._visual_item(object_name)
                self.assertIsNotNone(label, f"{object_name} was not found")
                self.assertTrue(label.isVisible())
                self.assertEqual(label.property("text"), expected_text)

        expected = {
            "plannerDateInput": "任务日期",
            "plannerTimeInput": "任务时间",
            "plannerListCombo": "任务清单",
            "plannerPriorityCombo": "任务优先级",
            "plannerProjectInput": "所属项目",
            "plannerTagsInput": "任务标签",
            "plannerEstimateCombo": "预估时长",
            "plannerRepeatCombo": "重复周期",
            "plannerNoteInput": "待办备注",
            "plannerProjectFilter": "按项目筛选",
            "plannerTagFilter": "按标签筛选",
        }
        self.page.setProperty("advancedOptionsExpanded", True)
        QTest.qWait(80)
        for object_name, expected_name in expected.items():
            with self.subTest(control=object_name):
                control = self._visual_item(object_name)
                self.assertIsNotNone(control, f"{object_name} was not found")
                interface = QAccessible.queryAccessibleInterface(control)
                self.assertIsNotNone(interface, f"{object_name} has no accessible interface")
                self.assertEqual(str(interface.text(QAccessible.Text.Name)), expected_name)

    def test_compact_advanced_options_explain_hidden_values(self) -> None:
        self.window.resize(760, 620)
        self.page.setProperty("advancedOptionsExpanded", True)
        for object_name, expected_text in {
            "plannerProjectLabel": "项目",
            "plannerTagsLabel": "标签",
            "plannerEstimateLabel": "预估时长",
            "plannerRepeatLabel": "重复周期",
            "plannerNoteLabel": "备注",
        }.items():
            with self.subTest(label=object_name):
                label = self._visual_item(object_name)
                self.assertIsNotNone(label, f"{object_name} was not found")
                self.assertTrue(label.isVisible())
                self.assertEqual(label.property("text"), expected_text)
        self._visual_item("plannerProjectInput").setProperty("text", "FLUKE")
        self._visual_item("plannerTagsInput").setProperty("text", "研究, 开发")
        self._visual_item("plannerEstimateCombo").setProperty("currentIndex", 2)
        self._visual_item("plannerRepeatCombo").setProperty("currentIndex", 1)
        self.page.setProperty("advancedOptionsExpanded", False)
        QTest.qWait(80)

        compact_options = self._visual_item("plannerAdvancedOptionsCompactButton")
        summary = self._visual_item("plannerAdvancedOptionsSummary")
        self.assertTrue(compact_options.isVisible())
        self.assertIn("已设置 4 项", str(compact_options.property("text")))
        self.assertTrue(summary.isVisible())
        self.assertIn("项目、标签、预估、重复", str(summary.property("text")))

    def test_date_validation_and_task_submission_round_trip(self) -> None:
        self._visual_item("plannerTitleInput").setProperty("text", "检查日程表单")
        date_field = self._visual_item("plannerDateInput")
        date_field.setProperty("text", "2026-02-30")
        self.assertEqual(date_field.property("text"), "2026-02-30")
        self._visual_item("plannerTimeInput").setProperty("text", "14:30")
        self._click("plannerAddButton")

        notice = self._visual_item("plannerFormNotice")
        self.assertEqual(date_field.property("text"), "2026-02-30")
        self.assertTrue(notice.property("visible"))
        self.assertIn("YYYY-MM-DD", notice.property("text"))
        self.assertEqual(self.planner.state["records"], [])

        self._visual_item("plannerDateInput").setProperty("text", date.today().isoformat())
        self._visual_item("plannerRepeatCombo").setProperty("currentIndex", 3)
        self._visual_item("plannerProjectInput").setProperty("text", "FLUKE 日程升级")
        self._visual_item("plannerTagsInput").setProperty("text", "开发, 研究, 开发")
        self._click("plannerAddButton")

        rows = self.planner.state["records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["data"]["title"], "检查日程表单")
        self.assertEqual(rows[0]["data"]["plannedStart"], "14:30")
        self.assertEqual(rows[0]["data"]["repeat"], "weekly")
        self.assertEqual(rows[0]["data"]["project"], "FLUKE 日程升级")
        self.assertEqual(rows[0]["data"]["tags"], ["开发", "研究"])
        self.assertEqual(self._visual_item("plannerTitleInput").property("text"), "")

    def test_new_task_without_a_time_stays_in_unscheduled_backlog(self) -> None:
        time_input = self._visual_item("plannerTimeInput")
        self.assertEqual(str(time_input.property("text")), "")

        self._visual_item("plannerTitleInput").setProperty("text", "先记下，再安排时间")
        self.assertEqual(str(time_input.property("text")), "")
        self._click("plannerAddButton")

        rows = self.planner.state["records"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["data"]["plannedStart"], "")
        self.assertFalse(bool(rows[0]["data"].get("timeboxed", False)))
        QTest.qWait(60)
        backlog = self._visual_item("plannerUnscheduledPanel")
        self.assertIsNotNone(backlog)
        self.assertTrue(backlog.isVisible())
        self.assertIsNotNone(self._visual_item(f"plannerBacklogCard_{rows[0]['id']}"))
        self.assertTrue(self._visual_item("plannerTimebox").isVisible())
        self.assertFalse(self._visual_item("plannerTimelineEmptyState").isVisible())
        self.assertEqual(self._visual_item("plannerTimelineRangeLabel").property("text"), "07:00 – 23:00")
        self.assertEqual(self._visual_item("plannerActualTimeHint").property("text"), "开始计时后记录实际用时")
        post_create_action = self._visual_item("plannerPostCreateAction")
        self.assertIsNotNone(post_create_action)
        self.assertTrue(post_create_action.isVisible())
        self.assertIn("已保存到待安排", self._visual_item("plannerPostCreateMessage").property("text"))

        self._click("plannerPostCreateScheduleButton")
        QTest.qWait(80)
        scheduled = self.planner.state["records"][0]
        self.assertRegex(scheduled["data"]["plannedStart"], r"^(?:[01]\d|2[0-3]):(?:00|15|30|45)$")
        self.assertEqual(scheduled["data"]["plannedDate"], date.today().isoformat())
        self.assertFalse(self._visual_item("plannerPostCreateAction").isVisible())
        self.assertIsNone(self._visual_item(f"plannerBacklogCard_{scheduled['id']}"))

    def test_daily_timeboxing_precedes_supporting_week_overview(self) -> None:
        day_plan = self._visual_item("plannerDayPlan")
        week_overview = self._visual_item("plannerWeekOverview")
        timebox = self._visual_item("plannerTimebox")
        unscheduled_panel = self._visual_item("plannerUnscheduledPanel")
        empty_state = self._visual_item("plannerTimelineEmptyState")
        self.assertIsNotNone(day_plan)
        self.assertIsNotNone(week_overview)
        self.assertIsNotNone(timebox)
        self.assertIsNotNone(unscheduled_panel)
        self.assertIsNotNone(empty_state)
        self.assertFalse(unscheduled_panel.isVisible())
        self.assertFalse(timebox.isVisible())
        self.assertTrue(empty_state.isVisible())
        self.assertGreater(empty_state.width(), day_plan.width() * 0.8)
        empty_state_button = self._visual_item("plannerEmptyStateAddButton")
        self.assertIsNotNone(empty_state_button)
        self.assertTrue(empty_state_button.isEnabled())

        day_plan_position = day_plan.mapToItem(self.page, 0, 0)
        week_overview_position = week_overview.mapToItem(self.page, 0, 0)
        self.assertLess(day_plan_position.y(), week_overview_position.y())

        self.window.resize(760, 620)
        QTest.qWait(80)
        compact_metrics = self._visual_item("plannerCompactMetrics")
        metric_cards = self._visual_item("plannerMetricCards")
        compact_options = self._visual_item("plannerAdvancedOptionsCompactButton")
        full_options = self._visual_item("plannerAdvancedOptionsButton")
        self.assertTrue(compact_metrics.property("visible"))
        self.assertIn("今天 0 项", compact_metrics.property("text"))
        self.assertFalse(metric_cards.property("visible"))
        self.assertTrue(compact_options.property("visible"))
        self.assertFalse(full_options.property("visible"))
        self.assertTrue(empty_state.isVisible())
        day_plan_position = day_plan.mapToItem(self.page, 0, 0)
        week_overview_position = week_overview.mapToItem(self.page, 0, 0)
        self.assertLess(day_plan_position.y(), week_overview_position.y())
        self.assertLess(day_plan_position.y(), 620)
        self.assertFalse(unscheduled_panel.isVisible())
        self.assertFalse(timebox.isVisible())

        self._click("plannerEmptyStateAddButton")
        QTest.qWait(40)
        self.assertTrue(self._visual_item("plannerTitleInput").hasActiveFocus())

        self._click("plannerAdvancedOptionsCompactButton")
        self.assertTrue(bool(self.page.property("advancedOptionsExpanded")))

    def test_legacy_estimate_is_normalized_before_qml_drop_schedules_it(self) -> None:
        today = date.today().isoformat()
        snapshot = {
            "richangji-state-v1": {
                "records": [{
                    "id": "legacy-seven-minute",
                    "type": "planner",
                    "date": today,
                    "createdAt": 1,
                    "sample": False,
                    "data": {
                        "title": "旧数据估时任务",
                        "time": "",
                        "plannedDate": "",
                        "plannedStart": "",
                        "estimateMinutes": 7,
                        "done": False,
                        "status": "todo",
                        "priority": "normal",
                        "list": "工作",
                    },
                }],
                "settings": {},
                "drafts": {"plannerForm": {}},
            }
        }
        self.assertTrue(self.planner._repository.adopt_imported_data(snapshot))
        self.planner._refresh()
        QTest.qWait(80)

        record = self.planner.state["records"][0]
        self.assertEqual(record["data"]["estimateMinutes"], 10)
        card = self._visual_item("plannerBacklogCard_legacy-seven-minute")
        self.assertIsNotNone(card)
        self.assertEqual(card.property("dragEstimateMinutes"), 10)
        dropped = QMetaObject.invokeMethod(
            self.page,
            "dropTask",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", {
                "source": {
                    "dragTaskId": "legacy-seven-minute",
                    "dragEstimateMinutes": card.property("dragEstimateMinutes"),
                },
                "y": 160.0,
            }),
        )
        self.assertTrue(dropped)
        scheduled = next(
            item for item in self.planner.state["records"]
            if item["id"] == "legacy-seven-minute"
        )
        self.assertEqual(scheduled["data"]["estimateMinutes"], 10)
        self.assertRegex(scheduled["data"]["plannedStart"], r"^(?:[01]\d|2[0-3]):(?:00|15|30|45)$")
        blocks = [
            block for block in self.planner.state["timeline"]["blocks"]
            if block["id"] == "legacy-seven-minute"
        ]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["estimateMinutes"], 10)

    def test_calendar_busy_event_is_shown_and_avoided_by_qml_schedule_suggestion(self) -> None:
        today = date.today()
        day = today.strftime("%Y%m%d")
        calendar = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:busy-meeting@example.test\r\n"
            f"DTSTART:{day}T090000\r\nDTEND:{day}T100000\r\n"
            "SUMMARY:日历会议\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:short-meeting@example.test\r\n"
            f"DTSTART:{day}T120000\r\nDTEND:{day}T123000\r\n"
            "SUMMARY:半小时事项\r\nEND:VEVENT\r\n"
            "BEGIN:VEVENT\r\nUID:longer-meeting@example.test\r\n"
            f"DTSTART:{day}T130000\r\nDTEND:{day}T134500\r\n"
            "SUMMARY:四十五分钟事项\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        self.planner._repository.import_calendar(calendar, "工作日历")
        task = self.planner._repository.add_task("会后安排任务", today.isoformat())
        self.planner._refresh()
        QTest.qWait(60)

        card = self._visual_item("plannerBacklogCard_" + task["id"])
        self.assertIsNotNone(card)
        self.assertEqual(card.property("suggestedStartTime"), "10:00")
        event = self.planner.state["calendarEvents"][0]
        self.assertIsNotNone(self._visual_item("plannerCalendarTimeline_" + event["id"]))
        short_event = next(row for row in self.planner.state["calendarEvents"] if row["title"] == "半小时事项")
        short_block = self._visual_item("plannerCalendarTimeline_" + short_event["id"])
        short_time = self._visual_item("plannerCalendarTimelineTime_" + short_event["id"])
        self.assertAlmostEqual(float(short_block.property("height")), 24.0, delta=0.5)
        self.assertFalse(bool(short_time.property("visible")))
        longer_event = next(row for row in self.planner.state["calendarEvents"] if row["title"] == "四十五分钟事项")
        longer_time = self._visual_item("plannerCalendarTimelineTime_" + longer_event["id"])
        self.assertTrue(bool(longer_time.property("visible")))

        self.planner._repository.schedule_task(task["id"], today.isoformat(), "09:45", 30)
        self.planner._refresh()
        QTest.qWait(60)
        timeline = self.planner.state["timeline"]
        task_block = next(row for row in timeline["blocks"] if row["id"] == task["id"])
        self.assertTrue(task_block["conflict"])
        self.assertEqual(timeline["conflictCount"], 1)

    def test_submit_cancels_pending_autosave_of_the_cleared_form(self) -> None:
        self._visual_item("plannerTitleInput").setProperty("text", "快速加入后不应变成草稿")
        self.assertTrue(
            QMetaObject.invokeMethod(self.page, "queueDraftSave", Qt.ConnectionType.DirectConnection)
        )

        self._click("plannerAddButton")
        QTest.qWait(350)

        self.assertEqual(len(self.planner.state["records"]), 1)
        self.assertEqual(self.planner.state["draft"], {})

    def test_optional_fields_start_collapsed_and_expand_on_demand(self) -> None:
        advanced = self._visual_item("plannerAdvancedOptionsButton")
        project = self._visual_item("plannerProjectInput")
        repeat = self._visual_item("plannerRepeatCombo")
        note = self._visual_item("plannerNoteInput")
        reminder = self._visual_item("plannerRemindCheck")
        submit = self._visual_item("plannerAddButton")

        self.assertIsNotNone(advanced)
        self.assertFalse(project.property("visible"))
        self.assertFalse(repeat.property("visible"))
        self.assertFalse(note.property("visible"))
        self.assertFalse(reminder.property("visible"))
        self.assertTrue(submit.property("visible"))

        self._click("plannerAdvancedOptionsButton")
        self.assertTrue(project.property("visible"))
        self.assertTrue(repeat.property("visible"))
        self.assertTrue(note.property("visible"))
        self.assertTrue(reminder.property("visible"))

        self._click("plannerAdvancedOptionsButton")
        self.assertFalse(project.property("visible"))

    def test_weekday_labels_translate_as_complete_labels(self) -> None:
        locale = LocalizationBridge(
            LocalizationRepository(self.database_path), self.engine, self.app
        )
        try:
            result = locale.setLanguage("en_US")
            self.assertTrue(result["ok"], result)
            translated = QMetaObject.invokeMethod(
                self.page,
                "weekDayLabel",
                Qt.ConnectionType.DirectConnection,
                Q_RETURN_ARG("QVariant"),
                Q_ARG("QVariant", "一"),
            )
            self.assertEqual(translated, "Mon")
        finally:
            locale.close()

    def test_queued_draft_save_is_restored_by_a_new_page(self) -> None:
        title_input = self._visual_item("plannerTitleInput")
        title_input.setProperty("text", "Draft task")
        self._visual_item("plannerProjectInput").setProperty("text", "Draft project")
        self._visual_item("plannerTagsInput").setProperty("text", "draft, later")
        self.assertTrue(
            QMetaObject.invokeMethod(self.page, "queueDraftSave", Qt.ConnectionType.DirectConnection)
        )
        QTest.qWait(350)
        self.assertEqual(self.planner.state["draft"]["title"], "Draft task")
        self.assertEqual(self.planner.state["draft"]["project"], "Draft project")
        self.assertEqual(self.planner.state["draft"]["tags"], "draft, later")

        self._destroy_engine()
        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("plannerController", self.planner)
        qml_url = QUrl.fromLocalFile(str(self.qml_directory).replace("\\", "/") + "/")
        wrapper_url = QUrl.fromLocalFile(str(self.qml_directory / "PlannerRestoreIntegration.qml"))
        source = (
            "import QtQuick\n"
            "import QtQuick.Controls\n"
            f'import "{qml_url.toString()}" as Native\n'
            "ApplicationWindow {\n"
            "  visible: true; width: 1280; height: 1000\n"
            "  Native.PlannerPage { anchors.fill: parent; controller: plannerController }\n"
            "}\n"
        )
        component = QQmlComponent(self.engine)
        self.restore_component = component
        component.setData(source.encode("utf-8"), wrapper_url)
        restored_window = component.create()
        self.assertIsNotNone(restored_window, "\n".join(e.toString() for e in component.errors()))
        restored_window.show()
        QTest.qWait(80)
        restored_title = self._find_in(restored_window.contentItem(), "plannerTitleInput")
        self.assertEqual(restored_title.property("text"), "Draft task")
        self.assertEqual(
            self._find_in(restored_window.contentItem(), "plannerTimeInput").property("text"),
            "",
        )
        self.assertEqual(
            self._find_in(restored_window.contentItem(), "plannerProjectInput").property("text"),
            "Draft project",
        )
        self.assertEqual(
            self._find_in(restored_window.contentItem(), "plannerTagsInput").property("text"),
            "draft, later",
        )
        self.assertTrue(
            self._find_in(restored_window.contentItem(), "plannerProjectInput").property("visible")
        )

    def test_subtask_dialog_creates_a_child_from_the_task_list(self) -> None:
        result = self.planner.addTaskWithOrganization(
            "准备发布", date.today().isoformat(), "", "normal", "工作", "", False,
            30, "none", "FLUKE", "发布,验收",
        )
        self.assertTrue(result["ok"], result)
        parent = self.planner.state["records"][0]
        parent_id = parent["id"]
        QTest.qWait(60)
        create_button = self._visual_item(f"plannerSubtaskButton_{parent_id}")
        self.assertIsNotNone(create_button, "task row has no subtask action")
        self.assertTrue(
            QMetaObject.invokeMethod(create_button, "click", Qt.ConnectionType.DirectConnection)
        )
        QTest.qWait(35)

        dialog = self.window.findChild(QObject, "plannerSubtaskDialog")
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.property("visible"))
        title = dialog.findChild(QObject, "plannerSubtaskTitleInput")
        self.assertIsNotNone(title)
        label = self._visual_item("plannerSubtaskTitleLabel")
        self.assertIsNotNone(label)
        self.assertEqual(label.property("text"), "子任务内容")
        self.assertEqual(title.property("placeholderText"), "例如：检查安装包")
        title.setProperty("text", "检查安装包")
        confirm = dialog.findChild(QObject, "plannerSubtaskConfirmButton")
        self.assertIsNotNone(confirm)
        self.assertTrue(QMetaObject.invokeMethod(confirm, "click", Qt.ConnectionType.DirectConnection))
        QTest.qWait(50)

        child = next(
            row for row in self.planner.state["records"]
            if row["data"].get("parentTaskId") == parent_id
        )
        self.assertEqual(child["data"]["title"], "检查安装包")
        self.assertEqual(child["data"]["project"], "FLUKE")
        self.assertEqual(child["data"]["tags"], ["发布", "验收"])
        self.assertFalse(dialog.property("visible"))

    def test_saved_list_kanban_and_matrix_views_switch_in_the_page(self) -> None:
        created = self.planner.addTaskWithOrganization(
            "今天要完成", date.today().isoformat(), "", "high", "工作", "", False,
            45, "none", "日程升级", "看板,矩阵",
        )
        self.assertTrue(created["ok"], created)
        record_id = self.planner.state["records"][0]["id"]

        self._click("plannerView_kanban")
        self.assertEqual(self.planner.state["viewMode"], "kanban")
        self.assertTrue(self._visual_item("plannerKanbanBoard").property("visible"))
        status_button = self._visual_item(f"plannerKanbanStatus_{record_id}_todo")
        self.assertEqual(status_button.property("font").pixelSize(), 12)

        self.window.resize(760, 620)
        QTest.qWait(80)
        for flow_name, button_names in (
            ("plannerViewControlsFlow", ("plannerView_list", "plannerView_kanban", "plannerView_matrix")),
            ("plannerCalendarActionsFlow", (
                "plannerTimesheetButton", "plannerCalendarImportButton",
                "plannerCalendarSourcesButton",
                "plannerCalendarExportButton",
            )),
        ):
            flow = self._visual_item(flow_name)
            self.assertIsNotNone(flow, flow_name)
            for button_name in button_names:
                button = self._visual_item(button_name)
                self.assertIsNotNone(button, button_name)
                right_edge = button.mapToItem(flow, button.width(), 0).x()
                self.assertLessEqual(right_edge, flow.width() + 1, button_name)

        self.assertTrue(self.planner.setTaskStatus(record_id, "doing")["ok"])
        self.assertEqual(self.planner.state["records"][0]["data"]["status"], "doing")

        self._click("plannerView_matrix")
        self.assertEqual(self.planner.state["viewMode"], "matrix")
        self.assertTrue(self._visual_item("plannerMatrixBoard").property("visible"))
        matrix_status_button = self._visual_item(f"plannerMatrixStatus_{record_id}_doing")
        self.assertEqual(matrix_status_button.property("font").pixelSize(), 12)
        self._click("plannerView_list")
        self.assertEqual(self.planner.state["viewMode"], "list")

    def test_standard_kanban_uses_saved_order_and_atomic_cross_lane_move(self) -> None:
        task_ids: dict[str, str] = {}
        for title in ("标准待办 A", "标准待办 B", "标准待办 C", "标准进行中"):
            result = self.planner.addTaskWithOrganization(
                title, date.today().isoformat(), "", "normal", "生活", "", False,
                15, "none", "", "",
            )
            self.assertTrue(result["ok"], result)
            record = next(row for row in self.planner.state["records"] if row["data"]["title"] == title)
            task_ids[title] = record["id"]

        self.assertTrue(self.planner.setTaskStatus(task_ids["标准进行中"], "doing")["ok"])
        self._click("plannerView_kanban")
        self.assertIsNotNone(self._visual_item("plannerStandardBoardLane_todo"))
        self.assertIsNotNone(self._visual_item("plannerStandardBoardLane_doing"))
        self.assertIsNotNone(self._visual_item("plannerStandardBoardReorderHint"))
        self.assertIsNotNone(
            self._visual_item("plannerStandardBoardDrop_" + task_ids["标准待办 B"])
        )
        self.assertIsNotNone(self._visual_item("plannerStandardBoardTailDrop_todo"))

        todo_order = [task_ids["标准待办 B"], task_ids["标准待办 A"], task_ids["标准待办 C"]]
        self.assertTrue(self.planner.setBoardOrder("todo", todo_order)["ok"])
        QTest.qWait(80)
        todo_lane = self._visual_item("plannerStandardBoardLane_todo")
        b_card = self._visual_item("plannerStandardBoardTask_" + task_ids["标准待办 B"])
        a_card = self._visual_item("plannerStandardBoardTask_" + task_ids["标准待办 A"])
        c_card = self._visual_item("plannerStandardBoardTask_" + task_ids["标准待办 C"])
        self.assertIsNotNone(todo_lane)
        self.assertIsNotNone(b_card)
        self.assertIsNotNone(a_card)
        self.assertIsNotNone(c_card)
        positions = [
            card.mapToItem(todo_lane, 0, 0).y()
            for card in (b_card, a_card, c_card)
        ]
        self.assertEqual(positions, sorted(positions))

        source_card = self._visual_item("plannerStandardBoardTask_" + task_ids["标准待办 B"])
        scroll = self._visual_item("plannerScroll")
        self.assertIsNotNone(scroll)
        source_y = source_card.mapToItem(scroll, 0, 0).y()
        scroll.setProperty("contentY", max(0.0, source_y - 120.0))
        QTest.qWait(80)
        source_card = self._visual_item("plannerStandardBoardTask_" + task_ids["标准待办 B"])
        self.assertGreaterEqual(float(source_card.height()), 40.0)
        moved = self.planner.moveTaskOnStandardBoard(
            task_ids["标准待办 B"], "doing", task_ids["标准进行中"],
        )
        self.assertTrue(moved["ok"], moved)
        QTest.qWait(80)
        state = self.planner.state
        self.assertEqual(
            state["boardOrders"]["todo"],
            [task_ids["标准待办 A"], task_ids["标准待办 C"]],
        )
        self.assertEqual(
            state["boardOrders"]["doing"],
            [task_ids["标准待办 B"], task_ids["标准进行中"]],
        )
        moved_record = next(row for row in state["records"] if row["id"] == task_ids["标准待办 B"])
        self.assertEqual(moved_record["data"]["status"], "doing")
        doing_lane = self._visual_item("plannerStandardBoardLane_doing")
        moved_card = self._visual_item("plannerStandardBoardTask_" + task_ids["标准待办 B"])
        doing_card = self._visual_item("plannerStandardBoardTask_" + task_ids["标准进行中"])
        self.assertIsNotNone(doing_lane)
        self.assertIsNotNone(moved_card)
        self.assertIsNotNone(doing_card)
        self.assertLess(
            moved_card.mapToItem(doing_lane, 0, 0).y(),
            doing_card.mapToItem(doing_lane, 0, 0).y(),
        )
        reopened = PlannerBridge(self.database_path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.state["boardOrders"]["doing"], state["boardOrders"]["doing"])

    def test_existing_task_can_be_edited_through_the_production_form(self) -> None:
        original_day = date.today().isoformat()
        result = self.planner.addTaskWithOrganization(
            "需要编辑的待办", original_day, "09:15", "high", "工作", "原备注", True,
            45, "weekly", "原项目", "旧标签",
        )
        self.assertTrue(result["ok"], result)
        record = next(row for row in self.planner.state["records"] if row["data"]["title"] == "需要编辑的待办")
        record_id = record["id"]
        QTest.qWait(50)

        self._click(f"plannerEditButton_{record_id}")
        self.assertEqual(str(self.page.property("editingTaskId")), record_id)
        self.assertEqual(self._visual_item("plannerFormHeading").property("text"), "编辑待办")
        self.assertEqual(self._visual_item("plannerTitleInput").property("text"), "需要编辑的待办")
        self.assertTrue(self._visual_item("plannerRemindCheck").property("checked"))

        new_day = (date.today() + timedelta(days=1)).isoformat()
        self._visual_item("plannerTitleInput").setProperty("text", "已更新的待办")
        self._visual_item("plannerDateInput").setProperty("text", new_day)
        self._visual_item("plannerTimeInput").setProperty("text", "10:45")
        self._visual_item("plannerListCombo").setProperty("currentIndex", 3)
        self._visual_item("plannerPriorityCombo").setProperty("currentIndex", 2)
        self._visual_item("plannerProjectInput").setProperty("text", "新项目")
        self._visual_item("plannerTagsInput").setProperty("text", "新标签, 复核")
        self._visual_item("plannerNoteInput").setProperty("text", "更新后的备注")
        self._visual_item("plannerRemindCheck").setProperty("checked", False)
        self._visual_item("plannerEstimateCombo").setProperty("currentIndex", 4)
        self._visual_item("plannerRepeatCombo").setProperty("currentIndex", 4)
        self._click("plannerAddButton")

        updated = next(row for row in self.planner.state["records"] if row["id"] == record_id)
        self.assertEqual(updated["date"], new_day)
        self.assertEqual(updated["data"]["title"], "已更新的待办")
        self.assertEqual(updated["data"]["time"], "10:45")
        self.assertEqual(updated["data"]["list"], "个人")
        self.assertEqual(updated["data"]["priority"], "low")
        self.assertEqual(updated["data"]["project"], "新项目")
        self.assertEqual(updated["data"]["tags"], ["新标签", "复核"])
        self.assertEqual(updated["data"]["note"], "更新后的备注")
        self.assertFalse(updated["data"]["remind"])
        self.assertEqual(updated["data"]["estimateMinutes"], 90)
        self.assertEqual(updated["data"]["repeat"], "monthly")
        self.assertEqual(str(self.page.property("editingTaskId")), "")

    def test_task_organization_can_be_edited_and_filters_apply_to_the_list(self) -> None:
        edited = self.planner.addTaskWithOrganization(
            "准备发布", date.today().isoformat(), "", "normal", "工作", "", False,
            30, "none", "Alpha", "draft",
        )
        other = self.planner.addTaskWithOrganization(
            "阅读资料", date.today().isoformat(), "", "normal", "工作", "", False,
            30, "none", "Beta", "research",
        )
        self.assertTrue(edited["ok"], edited)
        self.assertTrue(other["ok"], other)
        edited_id = next(row["id"] for row in self.planner.state["records"] if row["data"]["title"] == "准备发布")
        other_id = next(row["id"] for row in self.planner.state["records"] if row["data"]["title"] == "阅读资料")
        QTest.qWait(60)

        self._click(f"plannerOrganizationButton_{edited_id}")
        dialog = self.window.findChild(QObject, "plannerOrganizationDialog")
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.property("visible"))
        for object_name, expected in (
            ("plannerOrganizationProjectLabel", "项目"),
            ("plannerOrganizationTagsLabel", "标签"),
        ):
            label = self._visual_item(object_name)
            self.assertIsNotNone(label, object_name)
            self.assertEqual(label.property("text"), expected)
        self.assertEqual(
            dialog.findChild(QObject, "plannerOrganizationProjectInput").property("placeholderText"),
            "可选",
        )
        self.assertEqual(
            dialog.findChild(QObject, "plannerOrganizationTagsInput").property("placeholderText"),
            "用逗号分隔；最多 12 个",
        )
        dialog.findChild(QObject, "plannerOrganizationProjectInput").setProperty("text", "Beta")
        dialog.findChild(QObject, "plannerOrganizationTagsInput").setProperty("text", "research, release")
        self._click("plannerOrganizationSaveButton")

        changed = next(row for row in self.planner.state["records"] if row["id"] == edited_id)
        self.assertEqual(changed["data"]["project"], "Beta")
        self.assertEqual(changed["data"]["tags"], ["research", "release"])
        self.assertIn("Beta", self.planner.state["projects"])
        self.assertIn("release", self.planner.state["tags"])

        result = QMetaObject.invokeMethod(
            self.page,
            "setTaskFilters",
            Qt.ConnectionType.DirectConnection,
            Q_RETURN_ARG("QVariant"),
            Q_ARG("QVariant", "Beta"),
            Q_ARG("QVariant", "research"),
        )
        self.assertTrue(result)
        QTest.qWait(60)
        self.assertEqual(self.planner.state["projectFilter"], "Beta")
        self.assertEqual(self.planner.state["tagFilter"], "research")
        self.assertEqual(self._visual_item("plannerProjectFilter").property("currentText"), "Beta")
        self.assertEqual(self._visual_item("plannerTagFilter").property("currentText"), "research")
        filtered_ids = {
            row["id"]
            for group in self.planner.state["groups"]
            for row in group["records"]
        }
        self.assertEqual(filtered_ids, {edited_id, other_id})

    def test_custom_board_dialog_saves_columns_and_filters_tasks(self) -> None:
        task = self.planner._repository.add_task(
            "检查自定义流程", date.today().isoformat(), project="FLUKE", tags=["复核"],
        )
        self.planner._repository.set_task_status(task["id"], "doing")
        later_task = self.planner._repository.add_task(
            "稍后加入的卡片", date.today().isoformat(), tags=["复核"],
        )
        self.planner._repository.set_task_status(later_task["id"], "doing")
        self.planner._refresh()
        QTest.qWait(40)

        self._click("plannerCustomBoardManageButton")
        dialog = self.window.findChild(QObject, "plannerCustomBoardDialog")
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.property("visible"))
        board_name = self._visual_item("plannerCustomBoardNameInput")
        board_label = self._visual_item("plannerCustomBoardNameLabel")
        self.assertIsNotNone(board_name)
        self.assertIsNotNone(board_label)
        self.assertEqual(board_label.property("text"), "看板名称")
        self.assertEqual(board_name.property("placeholderText"), "例如：发布流程")
        board_name.setProperty("text", "发布流程")
        self.page.setProperty("customBoardEditorColumns", [
            {"id": "", "title": "待复核", "status": "doing", "tag": "复核"},
            {"id": "", "title": "已完成", "status": "done", "tag": ""},
        ])
        for object_name, expected_name in (
            ("plannerBoardColumnStatus_0", "看板列状态"),
            ("plannerBoardColumnTag_0", "看板列标签"),
        ):
            control = self._visual_item(object_name)
            self.assertIsNotNone(control)
            interface = QAccessible.queryAccessibleInterface(control)
            self.assertIsNotNone(interface)
            self.assertEqual(str(interface.text(QAccessible.Text.Name)), expected_name)
        self._click("plannerSaveBoardButton")

        board = self.planner.state["customBoards"][0]
        self.assertEqual(board["name"], "发布流程")
        self.assertEqual(len(board["columns"]), 2)
        self.assertEqual(self.planner.state["viewMode"], "custom-board:" + board["id"])
        custom_view = self._visual_item("plannerCustomBoard")
        self.assertTrue(custom_view.property("visible"))
        reorder_hint = self._visual_item("plannerBoardReorderHint")
        self.assertEqual(reorder_hint.property("font").pixelSize(), 12)
        lane = self._visual_item("plannerCustomBoardLane_" + board["columns"][0]["id"])
        self.assertIsNotNone(lane)
        card = self._visual_item("plannerCustomBoardTask_" + task["id"])
        self.assertIsNotNone(card)
        later_card = self._visual_item("plannerCustomBoardTask_" + later_task["id"])
        self.assertIsNotNone(later_card)

        moved_to_bottom = self.planner.moveTaskToBoardColumn(
            task["id"], "doing", "复核", board["id"], board["columns"][0]["id"], ""
        )
        self.assertTrue(moved_to_bottom["ok"], moved_to_bottom)
        QTest.qWait(50)
        saved_order = self.planner.state["customBoardOrders"][board["id"]][board["columns"][0]["id"]]
        self.assertEqual(saved_order, [later_task["id"], task["id"]])
        card_after_move = self._visual_item("plannerCustomBoardTask_" + task["id"])
        later_card_after_move = self._visual_item("plannerCustomBoardTask_" + later_task["id"])
        self.assertGreater(float(card_after_move.property("y")), float(later_card_after_move.property("y")))

        moved_before_card = self.planner.moveTaskToBoardColumn(
            task["id"], "doing", "复核", board["id"], board["columns"][0]["id"], later_task["id"]
        )
        self.assertTrue(moved_before_card["ok"], moved_before_card)
        QTest.qWait(50)
        self.assertEqual(
            self.planner.state["customBoardOrders"][board["id"]][board["columns"][0]["id"]],
            [task["id"], later_task["id"]],
        )

        moved = self.planner.moveTaskToBoardColumn(task["id"], "done", "")
        self.assertTrue(moved["ok"], moved)
        QTest.qWait(50)
        self.assertEqual(self.planner._repository._target(task["id"])["data"]["status"], "done")
        self.assertIsNotNone(self._visual_item("plannerCustomBoardTask_" + task["id"]))

    def test_focus_dialog_starts_task_countdown_pauses_and_recovers_after_close(self) -> None:
        task = self.planner._repository.add_task(
            "整理发布清单", date.today().isoformat(), estimate_minutes=30,
        )
        self.planner._refresh()
        QTest.qWait(60)
        focus_button = self._visual_item(f"plannerFocusButton_{task['id']}")
        self.assertIsNotNone(focus_button)
        self.assertTrue(QMetaObject.invokeMethod(focus_button, "click", Qt.ConnectionType.DirectConnection))
        dialog = self.window.findChild(QObject, "plannerFocusDialog")
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.property("visible"))
        mode_selector = dialog.findChild(QObject, "plannerFocusModeCombo")
        self.assertIsNotNone(mode_selector)
        mode_accessible = QAccessible.queryAccessibleInterface(mode_selector)
        self.assertIsNotNone(mode_accessible)
        self.assertEqual(str(mode_accessible.text(QAccessible.Text.Name)), "计时方式")
        self._click("plannerFocusHelpButton")
        help_dialog = self.window.findChild(QObject, "plannerProcrastinationHelpDialog")
        self.assertIsNotNone(help_dialog)
        self.assertTrue(help_dialog.property("visible"))
        tip = self._visual_item("plannerProcrastinationTip")
        first_tip = tip.property("text")
        self._click("plannerNextProcrastinationTipButton")
        self.assertNotEqual(tip.property("text"), first_tip)
        self._click("plannerCloseProcrastinationHelpButton")
        self.assertFalse(help_dialog.property("visible"))
        self.assertTrue(dialog.property("visible"))
        dialog.findChild(QObject, "plannerFocusModeCombo").setProperty("currentIndex", 2)
        dialog.findChild(QObject, "plannerFocusDuration").setProperty("value", 15)
        self._click("plannerFocusStartButton")

        QTest.qWait(80)
        active = self.planner.state["activeTracking"]
        self.assertEqual(active["taskId"], task["id"])
        self.assertEqual(active["mode"], "countdown")
        self.assertEqual(active["targetSeconds"], 15 * 60)
        self.assertFalse(active["paused"])
        self.assertTrue(self._visual_item("plannerActiveTimer").property("visible"))
        self._click("plannerActiveTimerHelpButton")
        self.assertTrue(help_dialog.property("visible"))
        self._click("plannerCloseProcrastinationHelpButton")

        self._click(f"plannerTrackButton_{task['id']}")
        self.assertTrue(self.planner.state["activeTracking"]["paused"])
        self._click(f"plannerTrackButton_{task['id']}")
        self.assertFalse(self.planner.state["activeTracking"]["paused"])

        self.planner.close()
        reopened = PlannerBridge(self.database_path)
        self.reopened_planner = reopened
        self.addCleanup(reopened.close)
        recovered = reopened.state["activeTracking"]
        self.assertEqual(recovered["mode"], "countdown")
        self.assertTrue(recovered["paused"])
        self.assertGreaterEqual(recovered["remainingSeconds"], 15 * 60 - 1)
        self.assertLessEqual(recovered["remainingSeconds"], 15 * 60)
        self.assertTrue(reopened.stopTrackingTask()["ok"])

    def test_timesheet_dialog_shows_task_totals_and_exports_csv(self) -> None:
        now = [datetime.now().astimezone().replace(hour=9, minute=0, second=0, microsecond=0)]
        self.planner._repository._clock = lambda: now[0]
        task = self.planner._repository.add_task(
            "复盘集成验收", now[0].date().isoformat(), estimate_minutes=30,
            project="FLUKE", tags=["验收"],
        )
        self.planner._repository.start_tracking(task["id"])
        now[0] += timedelta(minutes=20)
        self.planner._repository.stop_tracking()
        self.planner._refresh()
        QTest.qWait(60)

        self._click("plannerTimesheetButton")
        dialog = self.window.findChild(QObject, "plannerTimesheetDialog")
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.property("visible"))
        start = dialog.findChild(QObject, "plannerTimesheetStartDate").property("text")
        end = dialog.findChild(QObject, "plannerTimesheetEndDate").property("text")
        self.assertEqual(end, now[0].date().isoformat())
        report = self.page.property("timesheetReport")
        self.assertEqual(report["totals"]["actualSeconds"], 20 * 60)
        self.assertEqual(report["tasks"][0]["estimatedSeconds"], 30 * 60)

        output = Path(self.temp_dir.name) / "review.csv"
        result = self.planner.exportTimesheetCsv(QUrl.fromLocalFile(str(output)), start, end)
        self.assertTrue(result["ok"], result)
        self.assertTrue(output.is_file())

    def test_pomodoro_completion_notifies_and_saves_capped_task_time(self) -> None:
        now = [datetime.now().astimezone().replace(hour=9, minute=0, second=0, microsecond=0)]
        self.planner._repository._clock = lambda: now[0]
        task = self.planner._repository.add_task("番茄钟自动结束", now[0].date().isoformat())
        self.assertTrue(self.planner.startFocusTask(task["id"], "pomodoro", 25)["ok"])
        now[0] += timedelta(minutes=26)
        self.planner._clockTick()

        QTest.qWait(30)
        self.assertEqual(self.planner.state["activeTracking"], {})
        self.assertEqual(self.planner.state["notice"], "番茄钟完成，实际用时已保存。建议休息 5 分钟。")
        self.assertFalse(self.planner.state["noticeIsError"])
        saved = self.planner._repository._target(task["id"])["data"]
        self.assertEqual(saved["trackedSeconds"], 25 * 60)
        self.assertEqual(saved["sessions"][0]["seconds"], 25 * 60)

    def test_external_ics_event_appears_separately_and_planner_tasks_export(self) -> None:
        today = date.today().isoformat()
        day_value = today.replace("-", "")
        next_day_value = (date.today() + timedelta(days=1)).strftime("%Y%m%d")
        calendar_file = Path(self.temp_dir.name) / "meeting.ics"
        calendar_file.write_text(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:客户日历\r\n"
            "BEGIN:VEVENT\r\nUID:client-review@example.test\r\n"
            f"DTSTART;VALUE=DATE:{day_value}\r\nDTEND;VALUE=DATE:{next_day_value}\r\n"
            "SUMMARY:客户评审\r\nLOCATION:线上\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n",
            encoding="utf-8",
        )
        imported = self.planner.importCalendarIcs(QUrl.fromLocalFile(str(calendar_file)))
        self.assertTrue(imported["ok"], imported)
        self.assertEqual(imported["data"]["added"], 1)
        self.planner.setSelectedDay(today)
        QTest.qWait(60)
        external = self._visual_item("plannerExternalCalendar")
        self.assertIsNotNone(external)
        self.assertTrue(external.property("visible"))
        self.assertEqual(self.planner.state["calendarEvents"][0]["title"], "客户评审")
        self.assertEqual(self.planner.state["records"], [])

        task = self.planner.addTaskWithOrganization(
            "写会议结论", today, "14:00", "normal", "工作", "本地任务",
            False, 30, "none", "FLUKE", "日历",
        )
        self.assertTrue(task["ok"], task)
        output = Path(self.temp_dir.name) / "planner.ics"
        exported = self.planner.exportCalendarIcs(
            QUrl.fromLocalFile(str(output)), today, today,
        )
        self.assertTrue(exported["ok"], exported)
        payload = output.read_text(encoding="utf-8")
        self.assertIn("SUMMARY:写会议结论", payload)
        self.assertNotIn("SUMMARY:客户评审", payload)

    def test_ical_vtodo_import_appears_as_a_planner_task(self) -> None:
        today = date.today().isoformat()
        day_value = today.replace("-", "")
        todo_file = Path(self.temp_dir.name) / "team-tasks.ics"
        todo_file.write_text(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:团队待办\r\n"
            "BEGIN:VTODO\r\nUID:prepare-review@example.test\r\n"
            f"DTSTART;VALUE=DATE:{day_value}\r\nDUE;VALUE=DATE:{day_value}\r\n"
            "SUMMARY:准备周会资料\r\nDESCRIPTION:整理议题\r\n"
            "STATUS:NEEDS-ACTION\r\nPRIORITY:2\r\nEND:VTODO\r\nEND:VCALENDAR\r\n",
            encoding="utf-8",
        )

        imported = self.planner.importCalendarIcs(QUrl.fromLocalFile(str(todo_file)))
        self.assertTrue(imported["ok"], imported)
        self.assertEqual(imported["data"]["tasks"]["added"], 1)
        self.assertEqual(imported["data"]["added"], 0)
        record = next(
            row for row in self.planner.state["records"]
            if row["data"]["title"] == "准备周会资料"
        )
        self.assertEqual(record["data"]["externalTodo"]["sourceName"], "团队待办")

        self.planner.setSelectedDay(today)
        QTest.qWait(80)
        toggle = self._visual_item("plannerToggle_" + record["id"])
        self.assertIsNotNone(toggle)
        self.assertTrue(toggle.property("visible"))
        visible_text = []
        pending = [self.window.contentItem()]
        while pending:
            item = pending.pop()
            text = item.property("text")
            if isinstance(text, str) and text:
                visible_text.append(text)
            pending.extend(item.childItems())
        self.assertTrue(any("准备周会资料" in text for text in visible_text))
        self.assertTrue(any("从 iCalendar 导入的任务" in text for text in visible_text))

    def test_cancelled_vtodo_status_controls_are_disabled_on_kanban(self) -> None:
        today = date.today().isoformat()
        todo_file = Path(self.temp_dir.name) / "cancelled-task.ics"
        todo_file.write_text(
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:团队待办\r\n"
            "BEGIN:VTODO\r\nUID:cancelled@example.test\r\n"
            "SUMMARY:已取消的待办\r\nSTATUS:NEEDS-ACTION\r\nEND:VTODO\r\nEND:VCALENDAR\r\n",
            encoding="utf-8",
        )
        imported = self.planner.importCalendarIcs(QUrl.fromLocalFile(str(todo_file)))
        self.assertTrue(imported["ok"], imported)
        todo_file.write_text(
            todo_file.read_text(encoding="utf-8").replace(
                "STATUS:NEEDS-ACTION", "STATUS:CANCELLED",
            ),
            encoding="utf-8",
        )
        cancelled = self.planner.importCalendarIcs(QUrl.fromLocalFile(str(todo_file)))
        self.assertTrue(cancelled["ok"], cancelled)
        record = next(
            row for row in self.planner.state["records"]
            if row["data"].get("externalTodo", {}).get("uid") == "cancelled@example.test"
        )
        self.planner._repository.set_view_mode("kanban")
        self.planner._refresh()
        QTest.qWait(80)

        for status in ("todo", "doing", "done"):
            button = self._visual_item(f"plannerKanbanStatus_{record['id']}_{status}")
            self.assertIsNotNone(button, status)
            self.assertFalse(button.property("enabled"), status)
        status_result = self.planner.setTaskStatus(record["id"], "done")
        self.assertFalse(status_result["ok"])
        self.assertFalse(next(
            row for row in self.planner.state["records"] if row["id"] == record["id"]
        )["data"]["done"])

    def test_caldav_completion_conflict_has_local_and_server_resolution_actions(self) -> None:
        account = self.planner._repository.add_caldav_account(
            "Work", "calendar.example.test", "protected-url", "protected-credentials",
        )
        calendar = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VTODO\r\nUID:conflict@example.test\r\n"
            "SUMMARY:同步状态冲突\r\nSTATUS:NEEDS-ACTION\r\nEND:VTODO\r\n"
            "END:VCALENDAR\r\n"
        )
        imported = self.planner._repository.import_calendar(
            calendar,
            "Work tasks",
            f"caldav:{account['id']}",
            todo_provider="caldav",
            todo_metadata_by_uid={"conflict@example.test": {
                "accountId": account["id"],
                "resourceHref": "https://calendar.example.test/dav/tasks/conflict.ics",
                "etag": '"v1"',
                "syncedDone": False,
                "remoteDone": False,
                "syncConflict": True,
                "conflictRemoteDone": True,
                "conflictRemoteCompletedAt": "2026-09-28T09:00:00+08:00",
            }},
        )
        self.assertEqual(imported["tasks"]["added"], 1)
        task_id = next(
            row["id"] for row in self.planner._repository.records()
            if row["data"].get("externalTodo", {}).get("uid") == "conflict@example.test"
        )
        self.planner._refresh()
        QTest.qWait(70)

        conflict = self._visual_item("plannerCalDAVConflict_" + task_id)
        remote_button = self._visual_item("plannerCalDAVConflictRemote_" + task_id)
        self.assertIsNotNone(conflict)
        self.assertTrue(conflict.property("visible"))
        self.assertIsNotNone(remote_button)
        self._click("plannerCalDAVConflictRemote_" + task_id)

        self.assertTrue(next(
            row for row in self.planner.state["records"] if row["id"] == task_id
        )["data"]["done"])
        self.assertFalse(next(
            row for row in self.planner.state["records"] if row["id"] == task_id
        )["data"]["externalTodo"].get("syncConflict", False))

    def test_calendar_subscription_manager_opens_with_private_url_form(self) -> None:
        self._click("plannerCalendarSourcesButton")
        self._click("plannerCalendarSubscriptionsMenuItem")
        dialog = self.window.findChild(QObject, "plannerCalendarSubscriptionsDialog")
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.property("visible"))
        self.assertLess(float(dialog.property("height")), 650)
        self.assertGreater(float(self._visual_item("plannerCalendarSubscriptionList").property("height")), 80)
        name = self.window.findChild(QObject, "plannerCalendarSubscriptionNameInput")
        url = self.window.findChild(QObject, "plannerCalendarSubscriptionUrlInput")
        add = self.window.findChild(QObject, "plannerCalendarSubscriptionAddButton")
        self.assertIsNotNone(name)
        self.assertIsNotNone(url)
        self.assertIsNotNone(add)
        for object_name, expected in (
            ("plannerCalendarSubscriptionNameLabel", "订阅名称"),
            ("plannerCalendarSubscriptionUrlLabel", "订阅地址"),
        ):
            label = self._visual_item(object_name)
            self.assertIsNotNone(label, object_name)
            self.assertEqual(label.property("text"), expected)
        self.assertFalse(add.property("enabled"))
        self.assertEqual(self.planner.state["calendarSubscriptions"], [])
        url.setProperty("text", "ftp://calendar.example.test/feed.ics")
        self.assertTrue(add.property("enabled"))
        self._click("plannerCalendarSubscriptionAddButton")
        self.assertIn("HTTP", str(self.page.property("notice")))
        self.assertEqual(self.planner.state["calendarSubscriptions"], [])
        self.window.setProperty("width", 760)
        self.window.setProperty("height", 620)
        QTest.qWait(60)
        self.assertLessEqual(float(dialog.property("height")), 596)
        self.assertTrue(add.property("visible"))

    def test_caldav_account_manager_opens_with_private_login_form(self) -> None:
        self._click("plannerCalendarSourcesButton")
        self._click("plannerCalDAVAccountsMenuItem")
        dialog = self.window.findChild(QObject, "plannerCalDAVAccountsDialog")
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.property("visible"))
        self.assertLess(float(dialog.property("height")), 600)
        self.assertGreater(float(self._visual_item("plannerCalDAVAccountList").property("height")), 80)
        self.assertNotEqual(self._visual_item("plannerCalDAVAddButton").property("text"), "□□□")
        for object_name in (
            "plannerCalDAVNameInput",
            "plannerCalDAVUrlInput",
            "plannerCalDAVUsernameInput",
            "plannerCalDAVPasswordInput",
            "plannerCalDAVAddButton",
        ):
            self.assertIsNotNone(self.window.findChild(QObject, object_name), object_name)
        for object_name, expected in (
            ("plannerCalDAVNameLabel", "账户名称"),
            ("plannerCalDAVUrlLabel", "CalDAV 日历集地址"),
            ("plannerCalDAVUsernameLabel", "账号"),
            ("plannerCalDAVPasswordLabel", "密码 / 应用专用密码"),
        ):
            label = self._visual_item(object_name)
            self.assertIsNotNone(label, object_name)
            self.assertEqual(label.property("text"), expected)
        self.assertEqual(self.planner.state["caldavAccounts"], [])

        account = self.planner._repository.add_caldav_account(
            "Work", "calendar.example.test", "protected-url", "protected-credentials",
        )
        self.planner._repository.record_caldav_probe_result(
            account["id"], [{"name": "Tasks", "components": ["VTODO"]}],
        )
        self.planner._refresh()
        QTest.qWait(50)
        sync = self._visual_item("plannerCalDAVSync_" + account["id"])
        self.assertIsNotNone(sync)
        self.assertTrue(sync.property("enabled"))
        account_status = self._visual_item("plannerCalDAVAccountStatus_" + account["id"])
        self.assertIsNotNone(account_status)
        self.assertIn("待办任务", account_status.property("text"))

        event_account = self.planner._repository.add_caldav_account(
            "只读日历", "events.example.test", "event-url", "event-credentials",
        )
        self.planner._repository.record_caldav_probe_result(
            event_account["id"], [{"name": "Events", "components": ["VEVENT"]}],
        )
        self.planner._refresh()
        QTest.qWait(50)
        event_sync = self._visual_item("plannerCalDAVSync_" + event_account["id"])
        self.assertIsNotNone(event_sync)
        self.assertTrue(event_sync.property("enabled"))
        self.assertEqual(event_sync.property("text"), "同步日历内容")
        event_status = self._visual_item("plannerCalDAVAccountStatus_" + event_account["id"])
        self.assertIn("日历事件", event_status.property("text"))

        self.window.setProperty("width", 760)
        self.window.setProperty("height", 620)
        QTest.qWait(60)
        self.assertLessEqual(float(dialog.property("height")), 596)
        self.assertTrue(self._visual_item("plannerCalDAVAddButton").property("visible"))

        remove_button = self._visual_item("plannerCalDAVRemove_" + account["id"])
        remove_dialog = self.window.findChild(QObject, "plannerCalDAVAccountRemoveDialog")
        remove_message = self.window.findChild(QObject, "plannerCalDAVAccountRemoveMessage")
        self.assertIsNotNone(remove_button)
        self.assertIsNotNone(remove_dialog)
        self.assertIsNotNone(remove_message)
        self._click("plannerCalDAVRemove_" + account["id"])
        self.assertTrue(remove_dialog.property("visible"))
        self.assertIn("本机保存的登录信息", str(remove_message.property("text")))
        self.assertIn("Work · calendar.example.test", str(remove_message.property("text")))
        self._click("plannerCalDAVAccountRemoveCancelButton")
        self.assertFalse(remove_dialog.property("visible"))
        self.assertTrue(any(row["id"] == account["id"] for row in self.planner.state["caldavAccounts"]))
        self._click("plannerCalDAVRemove_" + account["id"])
        self._click("plannerCalDAVAccountRemoveConfirmButton")
        QTest.qWait(60)
        self.assertFalse(remove_dialog.property("visible"))
        self.assertFalse(any(row["id"] == account["id"] for row in self.planner.state["caldavAccounts"]))

    def test_draft_save_failure_is_visible_and_recovers(self) -> None:
        self._visual_item("plannerTitleInput").setProperty("text", "Draft with disk error")
        with patch.object(
            self.planner._repository,
            "save_draft",
            side_effect=OSError("模拟磁盘写入失败"),
        ):
            self.assertTrue(
                QMetaObject.invokeMethod(self.page, "queueDraftSave", Qt.ConnectionType.DirectConnection)
            )
            QTest.qWait(350)
            status = self._visual_item("plannerDraftStatus")
            self.assertIn("保存异常", status.property("text"))
            form_notice = self._visual_item("plannerFormNotice")
            self.assertTrue(form_notice.property("visible"))
            self.assertIn("模拟磁盘写入失败", form_notice.property("text"))

        self.assertTrue(
            QMetaObject.invokeMethod(self.page, "queueDraftSave", Qt.ConnectionType.DirectConnection)
        )
        QTest.qWait(350)
        self.assertIn("草稿已保存", self._visual_item("plannerDraftStatus").property("text"))
        self.assertFalse(self._visual_item("plannerFormNotice").property("visible"))

    @staticmethod
    def _find_in(root: QQuickItem, object_name: str) -> QQuickItem | None:
        pending = [root]
        while pending:
            item = pending.pop()
            if item.objectName() == object_name:
                return item
            pending.extend(item.childItems())
        return None


if __name__ == "__main__":
    unittest.main()
