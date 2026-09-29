from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMetaObject, QObject, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine

from main import FitnessBridge
from wanxiang.fitness import FitnessRepository


class FitnessQmlIntegrationTests(unittest.TestCase):
    """Exercise production FitnessPage confirmation handlers on a temporary DB."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.native_dir = Path(__file__).resolve().parents[1]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-fitness-qml-")
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "synthetic.sqlite3"
        self.controller = FitnessBridge(
            self.database_path, {"records": [], "settings": {"weeklyPlan": []}}
        )
        self.assertEqual(self.controller.state["records"], [])

        record_result = self.controller.addRecord(
            "70", "25", date.today().isoformat(), "synthetic fitness record"
        )
        plan_result = self.controller.addPlan(
            "运动", "synthetic weekly plan", "synthetic plan note"
        )
        self.assertTrue(record_result["ok"], record_result)
        self.assertTrue(plan_result["ok"], plan_result)
        self.record_id = str(self.controller.state["records"][0]["id"])
        self.plan_id = str(
            next(
                row
                for row in self.controller.state["weeklyPlan"]
                if row["title"] == "synthetic weekly plan"
            )["id"]
        )

        # Keep the production QML source in place; this temporary wrapper only
        # supplies the isolated controller, bundled fonts, and a window for the standalone page.
        qml_dir_url = QUrl.fromLocalFile(str(self.native_dir / "qml")).toString()
        sans_font_url = QUrl.fromLocalFile(
            str(self.native_dir.parent / "assets" / "fonts" / "NotoSansSC-VF.ttf")
        ).toString()
        serif_font_url = QUrl.fromLocalFile(
            str(self.native_dir.parent / "assets" / "fonts" / "NotoSerifSC-VF.ttf")
        ).toString()
        wrapper = Path(self.temp_dir.name) / "fitness-host.qml"
        wrapper.write_text(
            "\n".join(
                [
                    "import QtQuick",
                    "import QtQuick.Window",
                    f'import "{qml_dir_url}" as Native',
                    "Window {",
                    '    objectName: "fitnessTestWindow"',
                    "    width: 1480",
                    "    height: 1600",
                    "    visible: true",
                    f'    FontLoader {{ source: "{sans_font_url}" }}',
                    f'    FontLoader {{ source: "{serif_font_url}" }}',
                    "    Native.FitnessPage {",
                    '        objectName: "fitnessTestPage"',
                    "        anchors.fill: parent",
                    "        controller: fitnessController",
                    "    }",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.engine = QQmlApplicationEngine()
        self.addCleanup(self._destroy_engine)
        self.engine.rootContext().setContextProperty("fitnessController", self.controller)
        self.engine.load(QUrl.fromLocalFile(str(wrapper)))
        self.assertTrue(self.engine.rootObjects(), "production FitnessPage.qml failed to load")
        self.window = self.engine.rootObjects()[0]
        self.window.show()
        QTest.qWait(150)
        self.page = self.window.findChild(QObject, "fitnessTestPage")
        self.assertIsNotNone(self.page, "production FitnessPage instance was not found")

    def _destroy_engine(self) -> None:
        if getattr(self, "engine", None) is not None:
            self.engine.deleteLater()
            QTest.qWait(30)

    def _click(self, object_name: str) -> QObject:
        control = self.window.findChild(QObject, object_name) or self._find_visual_item(
            object_name
        )
        self.assertIsNotNone(control, f"production QML control {object_name} was not found")
        invoked = QMetaObject.invokeMethod(
            control, "click", Qt.ConnectionType.DirectConnection
        )
        self.assertTrue(invoked, f"could not click production QML control {object_name}")
        QTest.qWait(100)
        return control

    def _find_visual_item(self, object_name: str) -> QQuickItem | None:
        pending = [self.page]
        while pending:
            item = pending.pop()
            if item.objectName() == object_name:
                return item
            pending.extend(item.childItems())
        return None

    def test_primary_actions_wait_for_required_valid_fields(self) -> None:
        weight = self.window.findChild(QObject, "fitnessWeightInput")
        save_record = self.window.findChild(QObject, "fitnessSaveRecordButton")
        self.assertIsNotNone(weight)
        self.assertIsNotNone(save_record)
        self.assertIn("必填", str(weight.property("placeholderText")))
        self.assertFalse(bool(save_record.property("enabled")))
        weight.setProperty("text", "0")
        QTest.qWait(30)
        self.assertFalse(bool(save_record.property("enabled")))
        weight.setProperty("text", "68.4")
        QTest.qWait(30)
        self.assertTrue(bool(save_record.property("enabled")))

        self._click("fitnessProfileButton")
        height = self.window.findChild(QObject, "fitnessHeightInput")
        starting_weight = self.window.findChild(QObject, "fitnessStartWeightInput")
        target_weight = self.window.findChild(QObject, "fitnessTargetInput")
        save_profile = self.window.findChild(QObject, "fitnessSaveProfileButton")
        self.assertIsNotNone(height)
        self.assertIsNotNone(starting_weight)
        self.assertIsNotNone(target_weight)
        self.assertIsNotNone(save_profile)
        self.assertFalse(bool(save_profile.property("enabled")))
        height.setProperty("text", "99")
        QTest.qWait(30)
        self.assertFalse(bool(save_profile.property("enabled")))
        height.setProperty("text", "170")
        starting_weight.setProperty("text", "72")
        target_weight.setProperty("text", "55")
        QTest.qWait(30)
        self.assertTrue(bool(save_profile.property("enabled")))

        profile_dialog = self.window.findChild(QObject, "fitnessProfileDialog")
        self.assertIsNotNone(profile_dialog)
        self.assertTrue(QMetaObject.invokeMethod(profile_dialog, "close", Qt.ConnectionType.DirectConnection))
        self._click("fitnessAddPlanOpenButton")
        plan_title = self.window.findChild(QObject, "fitnessPlanTitle")
        add_plan = self.window.findChild(QObject, "fitnessAddPlanButton")
        self.assertIsNotNone(plan_title)
        self.assertIsNotNone(add_plan)
        self.assertIn("必填", str(plan_title.property("placeholderText")))
        self.assertFalse(bool(add_plan.property("enabled")))
        plan_title.setProperty("text", "每周快走三次")
        QTest.qWait(30)
        self.assertTrue(bool(add_plan.property("enabled")))

    def test_record_delete_requires_confirmation_and_persists(self) -> None:
        delete_button = self._click(f"fitnessDeleteRecord_{self.record_id}")
        self.assertIsNotNone(delete_button)
        dialog = self.window.findChild(QObject, "fitnessDeleteRecordDialog")
        message = self.window.findChild(QObject, "fitnessDeleteRecordMessage")
        self.assertIsNotNone(dialog, "production record-delete confirmation was not found")
        self.assertIsNotNone(message)
        self.assertTrue(dialog.property("visible"), "record-delete confirmation did not open")
        self.assertIn("当前本机记录", str(message.property("text")))
        self.assertIn("旧版原始数据不会被改动", str(message.property("text")))
        self.assertEqual(str(self.page.property("deleteRecordId")), self.record_id)
        self.assertEqual(
            [row["id"] for row in self.controller.state["records"]], [self.record_id]
        )

        self._click("fitnessDeleteRecordConfirmButton")

        self.assertFalse(dialog.property("visible"), "confirmed record dialog stayed open")
        self.assertEqual(self.controller.state["records"], [])
        trend_description = self._find_visual_item("fitnessTrendDescription")
        trend_empty_state = self._find_visual_item("fitnessTrendEmptyState")
        trend_canvas = self._find_visual_item("fitnessTrendCanvas")
        trend_legend = self._find_visual_item("fitnessTrendLegend")
        self.assertEqual(trend_description.property("text"), "记录体重后查看变化")
        self.assertTrue(trend_empty_state.property("visible"))
        self.assertEqual(trend_empty_state.property("text"), "记录体重后即可查看趋势")
        self.assertFalse(trend_canvas.property("visible"))
        self.assertFalse(trend_legend.property("visible"))
        reopened = FitnessRepository(self.database_path)
        self.assertEqual(reopened.state()["records"], [])
        self.assertEqual(len(reopened.deleted_record_keys()), 0)

    def test_trend_labels_follow_the_number_of_valid_weight_records(self) -> None:
        description = self._find_visual_item("fitnessTrendDescription")
        legend = self._find_visual_item("fitnessTrendLegend")
        self.assertIsNotNone(description)
        self.assertIsNotNone(legend)
        self.assertEqual(description.property("text"), "已有 1 次有效体重记录")
        empty_state = self._find_visual_item("fitnessTrendEmptyState")
        canvas = self._find_visual_item("fitnessTrendCanvas")
        self.assertTrue(empty_state.property("visible"))
        self.assertEqual(empty_state.property("text"), "再记录一次体重，就能看到趋势")
        self.assertFalse(canvas.property("visible"))
        self.assertFalse(legend.property("visible"))

        result = self.controller.addRecord(
            "69.5", "", date.today().isoformat(), "second synthetic fitness record"
        )
        self.assertTrue(result["ok"], result)
        QTest.qWait(150)

        self.assertEqual(
            description.property("text"),
            "当前范围内 2 次测量 · 圆点为记录，虚线为最多 7 次均值",
        )
        self.assertFalse(empty_state.property("visible"))
        self.assertTrue(canvas.property("visible"))
        self.assertTrue(legend.property("visible"))

    def test_calendar_range_updates_qml_and_captures_chart(self) -> None:
        today = date.today()
        older_result = self.controller.addRecord(
            "73", "", (today - timedelta(days=60)).isoformat(), "older synthetic record"
        )
        self.assertTrue(older_result["ok"], older_result)
        combo = self._find_visual_item("fitnessTrendRangeCombo")
        description = self._find_visual_item("fitnessTrendDescription")
        canvas = self._find_visual_item("fitnessTrendCanvas")
        self.assertIsNotNone(combo)
        self.assertIsNotNone(description)
        self.assertIsNotNone(canvas)

        self.controller.setTrendRange("30")
        QTest.qWait(100)
        self.assertEqual(len(self.controller.state["trend"]), 1)
        self.assertEqual(combo.property("currentIndex"), 0)
        self.assertEqual(
            self._find_visual_item("fitnessTrendEmptyState").property("text"),
            "再记录一次体重，就能看到趋势",
        )
        self.assertFalse(canvas.property("visible"))

        self.controller.setTrendRange("90")
        QTest.qWait(150)
        self.assertEqual(len(self.controller.state["trend"]), 2)
        self.assertEqual(combo.property("currentIndex"), 1)
        self.assertEqual(combo.property("displayText"), "近 90 天")
        self.assertTrue(canvas.property("visible"))
        self.assertIn("2 次测量", description.property("text"))

        screenshot = self.window.grabWindow()
        self.assertFalse(screenshot.isNull(), "fitness trend review screenshot was empty")
        screenshot_dir = self.native_dir / "qa-release" / "ui-runtime-review"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        self.assertTrue(
            screenshot.save(
                str(screenshot_dir / f"fitness-trend-calendar-range-{today.isoformat()}.png"),
                "PNG",
            )
        )

    def test_start_weight_can_be_set_in_the_profile_dialog(self) -> None:
        self._click("fitnessProfileButton")
        dialog = self.window.findChild(QObject, "fitnessProfileDialog")
        start_weight = self.window.findChild(QObject, "fitnessStartWeightInput") or self._find_visual_item(
            "fitnessStartWeightInput"
        )
        self.assertTrue(dialog.property("visible"))
        self.assertIsNotNone(start_weight)
        height = self.window.findChild(QObject, "fitnessHeightInput") or self._find_visual_item("fitnessHeightInput")
        target = self.window.findChild(QObject, "fitnessTargetInput") or self._find_visual_item("fitnessTargetInput")
        self.assertEqual(start_weight.property("text"), "")

        height.setProperty("text", "170")
        start_weight.setProperty("text", "72.0")
        target.setProperty("text", "55")
        self._click("fitnessSaveProfileButton")

        self.assertFalse(dialog.property("visible"))
        self.assertEqual(self.controller.state["profile"]["startWeight"], 72)
        self.assertAlmostEqual(self.controller.state["summary"]["progress"], (2 / 17) * 100)
        reopened = FitnessRepository(self.database_path)
        self.assertEqual(reopened.profile()["startWeight"], 72)

    def test_unconfigured_body_metrics_do_not_show_default_personal_values(self) -> None:
        result = self.controller.deleteRecord(self.record_id)
        self.assertTrue(result["ok"], result)
        deleted_plan = self.controller.deletePlan(self.plan_id)
        self.assertTrue(deleted_plan["ok"], deleted_plan)
        QTest.qWait(150)

        summary = self.controller.state["summary"]
        self.assertIsNone(summary["current"])
        self.assertIsNone(summary["bmi"])
        self.assertIsNone(summary["progress"])
        self.assertEqual(self.controller.state["profileFields"], [])
        self.assertEqual(self._find_visual_item("fitnessStatValue_0").property("text"), "未记录")
        self.assertEqual(self._find_visual_item("fitnessStatValue_1").property("text"), "—")
        self.assertEqual(self._find_visual_item("fitnessStatValue_2").property("text"), "—")
        self.assertEqual(
            self._find_visual_item("fitnessGoalHint").property("text"),
            "请先记录体重，再设置身高和体重目标。",
        )
        self.assertEqual(self._find_visual_item("fitnessTrendDescription").property("visible"), False)
        self.assertEqual(self._find_visual_item("fitnessWeeklyPlanSummary").property("visible"), False)
        self.assertEqual(self._find_visual_item("fitnessTrendEmptyState").property("text"), "记录体重后即可查看趋势")
        self.assertEqual(self._find_visual_item("fitnessTrendCanvas").property("visible"), False)
        self.assertEqual(
            self._find_visual_item("fitnessNoRecordsText").property("text"),
            "保存后的记录会显示在这里。",
        )

    def test_weekly_plan_delete_requires_confirmation_and_persists(self) -> None:
        delete_button = self._click(f"fitnessDeletePlan_{self.plan_id}")
        self.assertIsNotNone(delete_button)
        dialog = self.window.findChild(QObject, "fitnessDeletePlanDialog")
        self.assertIsNotNone(dialog, "production plan-delete confirmation was not found")
        self.assertTrue(dialog.property("visible"), "plan-delete confirmation did not open")
        self.assertEqual(str(self.page.property("deletePlanId")), self.plan_id)
        self.assertEqual(
            [row["id"] for row in self.controller.state["weeklyPlan"]], [self.plan_id]
        )

        self._click("fitnessDeletePlanConfirmButton")

        self.assertFalse(dialog.property("visible"), "confirmed plan dialog stayed open")
        self.assertEqual(self.controller.state["weeklyPlan"], [])
        reopened = FitnessRepository(self.database_path)
        self.assertEqual(reopened.state()["weeklyPlan"], [])
        # The unrelated fitness record must survive deleting the weekly plan.
        self.assertEqual(
            [row["id"] for row in reopened.state()["records"]], [self.record_id]
        )


if __name__ == "__main__":
    unittest.main()
