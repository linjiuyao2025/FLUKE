from __future__ import annotations

from datetime import date, timedelta
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMetaObject, QObject, Qt, QUrl
from PySide6.QtGui import QAccessible, QColor, QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine

from main import HabitBridge
from wanxiang.habits import HabitRepository


class HabitHeatmapQmlIntegrationTests(unittest.TestCase):
    """Check the rendered heatmap colors against its visible legend."""

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
        cls.native_dir = Path(__file__).resolve().parents[1]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-habit-qml-")
        self.addCleanup(self.temp_dir.cleanup)
        today = date.today()
        habit = {
            "id": "heatmap-synthetic-water",
            "key": "heatmap-synthetic-water",
            "name": "合成饮水",
            "type": "counter",
            "target": 8,
            "unit": "杯",
            "tone": "sage",
            "entries": {
                today.isoformat(): 3,
                (today - timedelta(days=1)).isoformat(): 8,
            },
            "sample": False,
        }
        self.controller = HabitBridge(
            Path(self.temp_dir.name) / "synthetic.sqlite3",
            {"habits": [habit], "settings": {}},
        )
        self.habit_id = next(
            row["id"] for row in self.controller.state["habits"]
            if row["name"] == "合成饮水"
        )

        qml_dir_url = QUrl.fromLocalFile(str(self.native_dir / "qml")).toString()
        wrapper = Path(self.temp_dir.name) / "habit-host.qml"
        wrapper.write_text(
            "\n".join(
                [
                    "import QtQuick",
                    "import QtQuick.Window",
                    f'import "{qml_dir_url}" as Native',
                    "Window {",
                    '    objectName: "habitTestWindow"',
                    "    width: 1480",
                    "    height: 1100",
                    "    visible: true",
                    "    Native.HabitPage { anchors.fill: parent; controller: habitController }",
                    "}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.engine = QQmlApplicationEngine()
        self.addCleanup(self._destroy_engine)
        self.engine.rootContext().setContextProperty("habitController", self.controller)
        self.engine.load(QUrl.fromLocalFile(str(wrapper)))
        self.assertTrue(self.engine.rootObjects(), "production HabitPage.qml failed to load")
        self.window = self.engine.rootObjects()[0]
        self.window.show()
        QTest.qWait(180)

    def _destroy_engine(self) -> None:
        if getattr(self, "engine", None) is not None:
            self.engine.deleteLater()
            QTest.qWait(30)

    def _find_item(self, object_name: str):
        pending = [self.window.contentItem()]
        while pending:
            item = pending.pop()
            if item.objectName() == object_name:
                return item
            pending.extend(item.childItems())
        return None

    def test_heatmap_uses_neutral_partial_and_saturated_colors(self) -> None:
        no_record = self._find_item(f"habitHeatCell_{self.habit_id}_27")
        partial = self._find_item(f"habitHeatCell_{self.habit_id}_29")
        complete = self._find_item(f"habitHeatCell_{self.habit_id}_28")
        self.assertIsNotNone(no_record)
        self.assertIsNotNone(partial)
        self.assertIsNotNone(complete)
        legend = self._find_item("habitHeatmapLegend")
        self.assertIsNotNone(legend)
        self.assertEqual(
            legend.property("text"),
            "灰白为无记录，浅色为部分记录，深色为达成目标",
        )

        no_record_color = QColor(no_record.property("color"))
        partial_color = QColor(partial.property("color"))
        complete_color = QColor(complete.property("color"))
        self.assertGreater(partial_color.lightness(), complete_color.lightness())
        self.assertGreater(no_record_color.lightness(), partial_color.lightness())
        self.assertNotEqual(no_record_color, partial_color)

    def test_heatmap_tooltips_and_accessible_names_include_habit_date_and_units(self) -> None:
        cell = self._find_item(f"habitHeatCell_{self.habit_id}_29")
        self.assertIsNotNone(cell)
        today = self.controller.state["today"]
        description = str(cell.property("description"))
        self.assertEqual(description, f"合成饮水 · {today} · 3 / 8 杯")
        accessible = QAccessible.queryAccessibleInterface(cell)
        self.assertIsNotNone(accessible)
        self.assertEqual(accessible.role(), QAccessible.Role.Graphic)
        self.assertEqual(accessible.text(QAccessible.Text.Name), description)

    def test_heatmap_cells_use_wide_layout_without_collapsing_in_compact_layout(self) -> None:
        cell = self._find_item(f"habitHeatCell_{self.habit_id}_29")
        self.assertIsNotNone(cell)
        wide_width = float(cell.property("width"))
        self.assertGreater(wide_width, 18)

        self.window.setProperty("width", 760)
        QTest.qWait(80)
        compact_width = float(cell.property("width"))
        self.assertGreater(compact_width, 8)
        self.assertLess(compact_width, wide_width)

    def test_recent_week_chart_is_compact_and_has_a_visible_baseline(self) -> None:
        card = self._find_item("habitRecentWeekCard")
        baseline = self._find_item("habitWeeklyBaseline_0")
        self.assertIsNotNone(card)
        self.assertIsNotNone(baseline)
        self.assertLessEqual(float(card.property("height")), 180)
        self.assertEqual(float(baseline.property("height")), 1)

    def test_habit_rows_use_compact_separators_and_secondary_delete_action(self) -> None:
        habit_id = self.controller.state["habits"][0]["id"]
        row = self._find_item(f"habitRow_{habit_id}")
        more_button = self._find_item(f"habitMoreButton_{habit_id}")
        menu = more_button.findChild(QObject, f"habitActionsMenu_{habit_id}")
        self.assertIsNotNone(row)
        self.assertIsNotNone(more_button)
        self.assertIsNotNone(menu)
        self.assertLessEqual(float(row.property("height")), 70)
        accessible = QAccessible.queryAccessibleInterface(more_button)
        self.assertIsNotNone(accessible)
        self.assertEqual(
            accessible.text(QAccessible.Text.Name), "更多习惯操作"
        )
        self.assertIsNone(self._find_item(f"habitDeleteButton_{habit_id}"))

        self.window.setProperty("width", 760)
        QTest.qWait(80)
        self.assertGreater(float(more_button.property("x")) + float(more_button.property("width")), 0)
        self.assertLessEqual(
            float(more_button.property("x")) + float(more_button.property("width")),
            float(self.window.property("width")),
        )
        self.assertTrue(
            QMetaObject.invokeMethod(
                more_button, "click", Qt.ConnectionType.DirectConnection
            )
        )
        QTest.qWait(80)
        self.assertTrue(bool(menu.property("visible")))
        delete_item = menu.findChild(QObject, "deleteHabitMenuItem")
        self.assertIsNotNone(delete_item)
        self.assertTrue(
            QMetaObject.invokeMethod(
                delete_item, "click", Qt.ConnectionType.DirectConnection
            )
        )
        QTest.qWait(60)
        delete_dialog = self.window.findChild(QObject, "habitDeleteDialog")
        self.assertIsNotNone(delete_dialog)
        self.assertTrue(bool(delete_dialog.property("visible")))
        self.assertEqual(len(self.controller.state["habits"]), 5)
        QMetaObject.invokeMethod(menu, "dismiss", Qt.ConnectionType.DirectConnection)
        QMetaObject.invokeMethod(delete_dialog, "close", Qt.ConnectionType.DirectConnection)

    def test_new_habit_does_not_show_pre_creation_days_as_missed(self) -> None:
        for habit in list(self.controller.state["habits"]):
            self.assertTrue(self.controller.deleteHabit(habit["id"])["ok"])
        added = self.controller.addHabit({"name": "新建习惯", "type": "check"})
        self.assertTrue(added["ok"])
        new_habit = next(
            habit
            for habit in self.controller.state["habits"]
            if habit["name"] == "新建习惯"
        )
        QTest.qWait(100)

        prior_week = self.controller.state["metrics"]["week"][:-1]
        self.assertTrue(prior_week)
        self.assertTrue(all(item["total"] == 0 and item["rate"] == 0 for item in prior_week))
        yesterday = self._find_item(f"habitHeatCell_{new_habit['id']}_28")
        self.assertIsNotNone(yesterday)
        description = str(yesterday.property("description"))
        self.assertIn((date.today() - timedelta(days=1)).isoformat(), description)
        self.assertIn("\u5c1a\u672a\u5f00\u59cb", description)

    def test_weekday_schedule_can_be_created_and_hides_today_when_not_due(self) -> None:
        for habit in list(self.controller.state["habits"]):
            self.assertTrue(self.controller.deleteHabit(habit["id"])["ok"])
        add_button = self._find_item("habitAddButton")
        self.assertTrue(
            QMetaObject.invokeMethod(add_button, "click", Qt.ConnectionType.DirectConnection)
        )
        frequency = self._find_item("habitFrequencyBox")
        frequency.setProperty("currentIndex", 1)
        weekday = date.today().isoweekday() % 7 + 1
        weekday_button = self._find_item(f"habitWeekdayButton_{weekday}")
        self.assertIsNotNone(weekday_button)
        self.assertTrue(
            QMetaObject.invokeMethod(weekday_button, "click", Qt.ConnectionType.DirectConnection)
        )
        name_field = self._find_item("habitNameInput")
        name_field.setProperty("text", "每周习惯")
        confirm = self._find_item("habitAddConfirmButton")
        self.assertTrue(QMetaObject.invokeMethod(confirm, "click", Qt.ConnectionType.DirectConnection))
        QTest.qWait(100)

        habit = next(
            item for item in self.controller.state["habits"] if item["name"] == "每周习惯"
        )
        self.assertEqual(habit["schedule"], {"type": "weekdays", "days": [weekday]})
        self.assertEqual(self.controller.state["metrics"]["totalHabits"], 0)
        self.assertIsNone(self._find_item(f"habitRow_{habit['id']}"))
        today_cell = self._find_item(f"habitHeatCell_{habit['id']}_29")
        self.assertIsNotNone(today_cell)
        self.assertIn("\u975e\u8ba1\u5212\u65e5", str(today_cell.property("description")))

    def test_edit_habit_updates_schedule_from_today_without_rewriting_checkins(self) -> None:
        habit = next(
            item for item in self.controller.state["habits"] if item["name"] == "合成饮水"
        )
        original_entries = dict(habit["entries"])
        more_button = self._find_item(f"habitMoreButton_{habit['id']}")
        self.assertTrue(
            QMetaObject.invokeMethod(more_button, "click", Qt.ConnectionType.DirectConnection)
        )
        QTest.qWait(60)
        menu = more_button.findChild(QObject, f"habitActionsMenu_{habit['id']}")
        edit_item = menu.findChild(QObject, "editHabitMenuItem")
        self.assertIsNotNone(edit_item)
        self.assertTrue(
            QMetaObject.invokeMethod(edit_item, "click", Qt.ConnectionType.DirectConnection)
        )
        QTest.qWait(80)

        dialog = self.window.findChild(QObject, "habitAddDialog")
        self.assertTrue(bool(dialog.property("visible")))
        schedule_hint = self._find_item("habitEditScheduleHint")
        self.assertTrue(bool(schedule_hint.property("visible")))
        self.assertIn("之前的记录", str(schedule_hint.property("text")))
        self.assertEqual(self._find_item("habitNameInput").property("text"), "合成饮水")
        self.assertEqual(self._find_item("habitTypeBox").property("currentIndex"), 1)
        frequency = self._find_item("habitFrequencyBox")
        frequency.setProperty("currentIndex", 1)
        weekday = date.today().isoweekday()
        weekday_button = self._find_item(f"habitWeekdayButton_{weekday}")
        self.assertTrue(
            QMetaObject.invokeMethod(
                weekday_button, "click", Qt.ConnectionType.DirectConnection
            )
        )
        self.assertTrue(
            QMetaObject.invokeMethod(
                self._find_item("habitAddConfirmButton"),
                "click",
                Qt.ConnectionType.DirectConnection,
            )
        )
        QTest.qWait(80)

        updated = next(
            item for item in self.controller.state["habits"] if item["id"] == habit["id"]
        )
        self.assertEqual(updated["entries"], original_entries)
        self.assertEqual(updated["name"], "合成饮水")
        self.assertEqual(
            updated["schedule"], {"type": "weekdays", "days": [weekday]}
        )
        self.assertEqual(updated["scheduleHistory"][-1]["effectiveDate"], date.today().isoformat())
        self.assertFalse(bool(dialog.property("visible")))

    def test_unstarted_habit_history_is_not_shown_as_a_zero_streak_and_zero_rate(self) -> None:
        best_streak = self._find_item("habitSummaryValue_1")
        recent_rate = self._find_item("habitSummaryValue_2")
        self.assertIsNotNone(best_streak)
        self.assertIsNotNone(recent_rate)
        self.assertEqual(str(best_streak.property("text")), "1 次")
        self.assertNotEqual(str(recent_rate.property("text")), "—")

        self.assertTrue(self.controller.deleteHabit(self.habit_id)["ok"])
        added = self.controller.addHabit({
            "name": "新习惯",
            "type": "check",
            "target": 1,
            "unit": "次",
            "tone": "sage",
        })
        self.assertTrue(added["ok"])
        QTest.qWait(100)

        today = self._find_item("habitSummaryValue_0")
        today_hint = self._find_item("habitSummaryHint_0")
        best_streak = self._find_item("habitSummaryValue_1")
        best_hint = self._find_item("habitSummaryHint_1")
        recent_rate = self._find_item("habitSummaryValue_2")
        recent_hint = self._find_item("habitSummaryHint_2")
        total_habits = len(self.controller.state["habits"])
        self.assertEqual(str(today.property("text")), f"0 / {total_habits}")
        self.assertEqual(str(today_hint.property("text")), "完成目标的习惯")
        self.assertEqual(str(best_streak.property("text")), "—")
        self.assertEqual(str(best_hint.property("text")), "开始记录后显示")
        self.assertEqual(str(recent_rate.property("text")), "—")
        self.assertEqual(str(recent_hint.property("text")), "最近 30 天还没有记录")

    def test_number_habit_saves_once_editing_finishes(self) -> None:
        number_habit = next(
            row for row in self.controller.state["habits"] if row["type"] == "number"
        )
        field = self._find_item(f"habitNumberInput_{number_habit['id']}")
        self.assertIsNotNone(field)
        self.assertTrue(
            QMetaObject.invokeMethod(field, "forceActiveFocus", Qt.ConnectionType.DirectConnection)
        )
        QTest.qWait(30)
        self.assertTrue(field.property("activeFocus"))

        today = self.controller.state["today"]
        original_value = number_habit["entries"].get(today, 0)
        field.setProperty("editingValue", "6.5")
        self.assertTrue(
            QMetaObject.invokeMethod(field, "textEdited", Qt.ConnectionType.DirectConnection)
        )
        self.assertEqual(
            next(row for row in self.controller.state["habits"] if row["id"] == number_habit["id"])
            ["entries"].get(today, 0),
            original_value,
        )

        self.assertTrue(
            QMetaObject.invokeMethod(field, "editingFinished", Qt.ConnectionType.DirectConnection)
        )
        current = next(
            row for row in self.controller.state["habits"] if row["id"] == number_habit["id"]
        )
        self.assertEqual(current["entries"][today], 6.5)
        reopened = HabitRepository(Path(self.temp_dir.name) / "synthetic.sqlite3")
        reopened_habit = next(row for row in reopened.habits() if row["id"] == number_habit["id"])
        self.assertEqual(reopened_habit["entries"][today], 6.5)


if __name__ == "__main__":
    unittest.main()
