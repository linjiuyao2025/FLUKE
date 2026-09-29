from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, QUrl
from PySide6.QtGui import QAccessible, QImage
from PySide6.QtTest import QTest
from PySide6.QtQuick import QQuickItem
from PySide6.QtWidgets import QApplication
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
from wanxiang.database import import_package
from wanxiang.media import MediaRepository
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _media_rows() -> list[dict[str, object]]:
    return [
        {
            "id": "synthetic-want-5",
            "name": "合成待读五星",
            "type": "书",
            "status": "想看",
            "rating": 5,
            "review": "仅供界面测试",
            "date": "2026-09-20",
            "cover": "",
            "sample": False,
        },
        {
            "id": "synthetic-progress-4",
            "name": "合成在看四星",
            "type": "番",
            "status": "在看",
            "rating": 4,
            "review": "仅供界面测试",
            "date": "2026-09-21",
            "cover": "",
            "sample": False,
        },
        {
            "id": "synthetic-finished-3",
            "name": "合成看完三星",
            "type": "电影",
            "status": "看完",
            "rating": 3,
            "review": "仅供界面测试",
            "date": "2026-09-22",
            "cover": "",
            "sample": False,
        },
        {
            "id": "synthetic-finished-5",
            "name": "合成看完五星",
            "type": "剧",
            "status": "看完",
            "rating": 5,
            "review": "仅供界面测试",
            "date": "2026-09-23",
            "cover": "",
            "sample": False,
        },
        {
            "id": "synthetic-dropped-unrated",
            "name": "合成弃看未评分",
            "type": "电影",
            "status": "弃了",
            "rating": 0,
            "review": "仅供界面测试",
            "date": "2026-09-24",
            "cover": "",
            "sample": False,
        },
    ]


def _migration_package() -> object:
    state = {
        "version": 2,
        "records": [{
            "id": "synthetic-shopping-low",
            "type": "home",
            "date": "2026-09-27",
            "createdAt": 10,
            "sample": False,
            "data": {
                "name": "合成低优先级物品",
                "quantity": "1 件",
                "category": "家居",
                "price": 12,
                "priority": "low",
                "note": "仅供优先级显示测试",
                "bought": False,
            },
        }],
        "habits": [],
        "mediaItems": _media_rows(),
        "drafts": {},
        "settings": {},
    }
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    raw_values["richangji-state-v1"] = json.dumps(state, ensure_ascii=False)
    return validate_package({
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-media-qml-integration",
        "exportedAt": "2026-09-28T00:00:00Z",
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    })


class MediaQmlIntegrationTests(unittest.TestCase):
    """Exercise production MediaPage QML with an isolated synthetic database."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.native_dir = Path(__file__).resolve().parents[1]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-media-qml-")
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)
        self.database_path = self.temp_path / "synthetic.sqlite3"
        import_package(_migration_package(), self.database_path)

        self.engine = QQmlApplicationEngine()
        self.addCleanup(self._destroy_engine)
        migration = MigrationBridge(self.database_path)
        snapshot = migration.data
        finance = FinanceBridge(self.database_path, snapshot)
        self.media = MediaBridge(self.database_path, snapshot)
        self.converter = ConverterBridge()
        self.converter_engine_controller = ConverterEngineUpdateBridge(self.temp_path / "engine-updates")
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
            "mediaController": self.media,
            "archiveController": ArchiveBridge(self.database_path, snapshot),
            "converterController": self.converter,
            "converterEngineController": self.converter_engine_controller,
            "brandController": BrandBridge(BrandRepository(self.database_path), self.engine),
        }
        self.shopping = controllers["shoppingController"]
        self.engine.setInitialProperties(controllers)
        self.engine.load(QUrl.fromLocalFile(str(self.native_dir / "qml" / "Main.qml")))
        self.assertTrue(self.engine.rootObjects(), "production Main.qml failed to load")
        self.window = self.engine.rootObjects()[0]
        self.window.setProperty("currentSectionIndex", 6)
        self.window.resize(1480, 960)
        self.window.show()
        QTest.qWait(160)

        self.page = self.window.findChild(QObject, "mediaPage")
        self.assertIsNotNone(self.page, "production MediaPage was not found")
        self.collection = self.window.findChild(QObject, "mediaCollection")
        self.assertIsNotNone(self.collection, "production media collection was not found")

    def _destroy_engine(self) -> None:
        if getattr(self, "engine", None) is not None:
            self.engine.deleteLater()
            QTest.qWait(40)

    def _click(self, item: QObject) -> None:
        self.assertTrue(QMetaObject.invokeMethod(item, "click", Qt.ConnectionType.DirectConnection))
        QTest.qWait(100)

    def _select_combo_option(self, object_name: str, index: int) -> QObject:
        combo = self.window.findChild(QObject, object_name)
        self.assertIsNotNone(combo, f"production {object_name} combo was not found")
        combo.setProperty("currentIndex", index)
        invoked = QMetaObject.invokeMethod(
            combo,
            "activated",
            Qt.ConnectionType.DirectConnection,
            Q_ARG(int, index),
        )
        self.assertTrue(invoked, f"could not activate production {object_name} option")
        QTest.qWait(140)
        return combo

    def _visual_items(self) -> list[QQuickItem]:
        if not isinstance(self.page, QQuickItem):
            return []
        result: list[QQuickItem] = []
        pending = [self.page]
        while pending:
            item = pending.pop()
            result.append(item)
            pending.extend(item.childItems())
        return result

    def test_add_action_has_clear_required_title_state(self) -> None:
        name = self.window.findChild(QObject, "mediaNameInput")
        add = self.window.findChild(QObject, "mediaAddButton")
        self.assertIsNotNone(name)
        self.assertIsNotNone(add)
        self.assertIn("必填", str(name.property("placeholderText")))
        self.assertFalse(bool(add.property("enabled")))

        name.setProperty("text", "有效作品名称")
        QTest.qWait(40)
        self.assertTrue(bool(add.property("enabled")))

        name.setProperty("text", "   ")
        QTest.qWait(40)
        self.assertFalse(bool(add.property("enabled")))

    def test_media_form_text_fields_expose_meaningful_accessible_names(self) -> None:
        for object_name, expected_text in {
            "mediaTypeLabel": "作品类型",
            "mediaStatusLabel": "观看状态",
            "mediaRatingLabel": "作品评分",
            "mediaDateLabel": "记录日期",
        }.items():
            with self.subTest(label=object_name):
                label = self.window.findChild(QObject, object_name)
                self.assertIsNotNone(label, f"production {object_name} label was not found")
                self.assertTrue(label.property("visible"))
                self.assertEqual(label.property("text"), expected_text)

        expected_names = {
            "mediaNameInput": "作品名称",
            "mediaDateInput": "记录日期",
            "mediaReviewInput": "一句话短评",
            "mediaTypeBox": "作品类型",
            "mediaStatusBox": "观看状态",
            "mediaRatingBox": "作品评分",
            "mediaStatusFilter": "按观看状态筛选",
            "mediaRatingFilter": "按评分筛选",
        }
        for object_name, expected_name in expected_names.items():
            with self.subTest(field=object_name):
                field = self.window.findChild(QObject, object_name)
                self.assertIsNotNone(field, f"production {object_name} field was not found")
                interface = QAccessible.queryAccessibleInterface(field)
                self.assertIsNotNone(interface, f"{object_name} has no accessible interface")
                self.assertEqual(
                    str(interface.text(QAccessible.Text.Name)), expected_name,
                    f"{object_name} has an unexpected accessible name",
                )

    def test_shopping_selectors_name_category_and_priority(self) -> None:
        self.window.setProperty("currentSectionIndex", 5)
        QTest.qWait(80)
        for object_name, expected_name in {
            "shoppingCategoryBox": "商品分类",
            "shoppingPriorityBox": "购买优先级",
        }.items():
            with self.subTest(control=object_name):
                control = self.window.findChild(QObject, object_name)
                self.assertIsNotNone(control, f"production {object_name} was not found")
                interface = QAccessible.queryAccessibleInterface(control)
                self.assertIsNotNone(interface)
                self.assertEqual(str(interface.text(QAccessible.Text.Name)), expected_name)

    def test_shopping_list_renders_low_priority_label(self) -> None:
        self.window.setProperty("currentSectionIndex", 5)
        QTest.qWait(100)
        shopping_page = self.window.findChild(QObject, "shoppingPage")
        self.assertIsNotNone(shopping_page, "production ShoppingPage was not found")
        rows = self.shopping.state["shoppingRecords"]
        self.assertEqual([row["id"] for row in rows], ["synthetic-shopping-low"])

        pending = [shopping_page]
        row = None
        while pending:
            item = pending.pop()
            if item.objectName() == "shoppingRow_synthetic-shopping-low":
                row = item
                break
            if isinstance(item, QQuickItem):
                pending.extend(item.childItems())
        self.assertIsNotNone(row, "production ShoppingPage did not create the imported shopping row")

        pending = [row]
        status = None
        while pending:
            item = pending.pop()
            if str(item.property("text") or "") == "等等再买":
                status = item
                break
            if isinstance(item, QQuickItem):
                pending.extend(item.childItems())
        self.assertIsNotNone(status, "the low-priority row did not render its priority label")

    def test_wall_list_status_and_rating_filters_use_qml_and_persist(self) -> None:
        wall = self.window.findChild(QObject, "mediaWallButton")
        listing = self.window.findChild(QObject, "mediaListButton")
        self.assertIsNotNone(wall)
        self.assertIsNotNone(listing)
        self.assertTrue(self.page.property("wallView"))
        self.assertTrue(wall.property("checked"))
        self.assertEqual(int(self.collection.property("columns")), 3)
        self.assertEqual(len(self.media.state["filteredItems"]), 5)

        self._click(listing)
        self.assertFalse(self.page.property("wallView"))
        self.assertTrue(listing.property("checked"))
        self.assertEqual(int(self.collection.property("columns")), 1)
        self.assertEqual(MediaRepository(self.database_path).settings()["mediaView"], "list")

        self._click(wall)
        self.assertTrue(self.page.property("wallView"))
        self.assertTrue(wall.property("checked"))
        self.assertEqual(MediaRepository(self.database_path).settings()["mediaView"], "wall")

        status = self._select_combo_option("mediaStatusFilter", 3)
        self.assertEqual(status.property("displayText"), "看完")
        self.assertEqual(self.media.state["settings"]["mediaStatusFilter"], "看完")
        self.assertEqual(
            {item["id"] for item in self.media.state["filteredItems"]},
            {"synthetic-finished-3", "synthetic-finished-5"},
        )
        reopened = MediaRepository(self.database_path)
        self.assertEqual(reopened.settings()["mediaStatusFilter"], "看完")
        self.assertEqual(
            {item["id"] for item in reopened.filtered_items()},
            {"synthetic-finished-3", "synthetic-finished-5"},
        )

        rating = self._select_combo_option("mediaRatingFilter", 2)
        self.assertEqual(rating.property("displayText"), "4 星以上")
        self.assertEqual(self.media.state["settings"]["mediaRatingFilter"], 4)
        self.assertEqual(
            [item["id"] for item in self.media.state["filteredItems"]],
            ["synthetic-finished-5"],
        )
        self.assertEqual(MediaRepository(self.database_path).filtered_items()[0]["id"], "synthetic-finished-5")

        self._select_combo_option("mediaStatusFilter", 0)
        self._select_combo_option("mediaRatingFilter", 1)
        self.assertEqual(self.media.state["settings"]["mediaStatusFilter"], "all")
        self.assertEqual(self.media.state["settings"]["mediaRatingFilter"], 5)
        self.assertEqual(
            {item["id"] for item in self.media.state["filteredItems"]},
            {"synthetic-want-5", "synthetic-finished-5"},
        )

    def test_cover_file_dialog_acceptance_processes_fixture_and_saves_local_jpeg(self) -> None:
        image_path = self.temp_path / "synthetic-cover.png"
        image = QImage(720, 960, QImage.Format.Format_RGB32)
        image.fill(0xFF5A8073)
        self.assertTrue(image.save(str(image_path), "PNG"))

        dialog = self.window.findChild(QObject, "mediaCoverDialog")
        choose = self.window.findChild(QObject, "mediaCoverChooseButton")
        self.assertIsNotNone(dialog, "production cover FileDialog was not found")
        self.assertIsNotNone(choose, "production cover chooser button was not found")
        self._click(choose)
        self.assertTrue(dialog.property("visible"), "cover chooser button did not open FileDialog")

        # Native OS picker interaction is not available in the offscreen test
        # runtime. Set its selectedFile to a generated local fixture and invoke
        # the real accepted signal, which runs MediaPage.onAccepted/chooseCover.
        dialog.setProperty("selectedFile", QUrl.fromLocalFile(str(image_path)))
        accepted = QMetaObject.invokeMethod(dialog, "accepted", Qt.ConnectionType.DirectConnection)
        self.assertTrue(accepted, "production FileDialog accepted handler was not invokable")
        QTest.qWait(100)

        data_uri = str(self.page.property("pendingCover"))
        self.assertTrue(data_uri.startswith("data:image/jpeg;base64,"), data_uri[:40])
        self.assertIn("封面已压缩", str(self.window.findChild(QObject, "mediaNotice").property("text")))
        preview = self.window.findChild(QObject, "mediaCoverPreview")
        self.assertIsNotNone(preview)
        self.assertTrue(preview.property("visible"))
        preview_source = preview.property("source")
        if isinstance(preview_source, QUrl):
            preview_source = preview_source.toString()
        self.assertEqual(str(preview_source), data_uri)
        clear_cover = self.window.findChild(QObject, "mediaCoverClearButton")
        self.assertIsNotNone(clear_cover)
        self.assertEqual(str(clear_cover.property("text")), "移除封面")

        name = self.window.findChild(QObject, "mediaNameInput")
        add = self.window.findChild(QObject, "mediaAddButton")
        self.assertIsNotNone(name)
        self.assertIsNotNone(add)
        name.setProperty("text", "合成封面保存作品")
        self._click(add)
        added = next(item for item in self.media.state["items"] if item["name"] == "合成封面保存作品")
        self.assertEqual(added["cover"], data_uri)
        self.assertEqual(added["cover"].split(",", 1)[0], "data:image/jpeg;base64")
        decoded = QImage.fromData(base64.b64decode(data_uri.split(",", 1)[1]), "JPEG")
        self.assertFalse(decoded.isNull())
        self.assertLessEqual(decoded.width(), 360)
        self.assertLessEqual(decoded.height(), 480)
        persisted = MediaRepository(self.database_path)
        persisted_item = next(item for item in persisted.items() if item["id"] == added["id"])
        self.assertEqual(persisted_item["cover"], data_uri)

    def test_delete_confirmation_cancel_and_confirm_through_production_qml(self) -> None:
        scroll = self.window.findChild(QObject, "mediaScrollView")
        self.assertIsNotNone(scroll)
        flickable = scroll.property("contentItem")
        self.assertIsNotNone(flickable)
        content_height = float(flickable.property("contentHeight") or 0)
        viewport_height = float(flickable.property("height") or scroll.property("height") or 0)
        flickable.setProperty("contentY", max(0.0, content_height - viewport_height))
        QTest.qWait(140)
        delete_buttons = [item for item in self._visual_items() if item.objectName() == "mediaDeleteButton"]
        self.assertEqual(len(delete_buttons), 5)
        dialog = self.window.findChild(QObject, "mediaDeleteDialog")
        confirm = self.window.findChild(QObject, "mediaDeleteConfirmButton")
        message = self.window.findChild(QObject, "mediaDeleteMessage")
        storage_hint = self.window.findChild(QObject, "mediaStorageHint")
        self.assertIsNotNone(dialog)
        self.assertIsNotNone(confirm)
        self.assertIsNotNone(message)
        self.assertIsNotNone(storage_hint)
        self.assertEqual(
            storage_hint.property("text"),
            "本机保存 · 封面只在本机处理 · 导入的旧版数据不会被改动",
        )

        original_ids = {item["id"] for item in self.media.state["items"]}
        legacy_before = MediaRepository(self.database_path).legacy_items()
        self._click(delete_buttons[0])
        self.assertTrue(dialog.property("visible"))
        self.assertIn("当前本机书影音清单", str(message.property("text")))
        self.assertIn("旧版原始数据不会被改动", str(message.property("text")))
        cancel = next(
            (
                child
                for child in dialog.findChildren(QObject)
                if str(child.property("text") or "") == "取消"
            ),
            None,
        )
        self.assertIsNotNone(cancel, "production delete dialog cancel button was not found")
        self._click(cancel)
        self.assertFalse(dialog.property("visible"))
        self.assertEqual({item["id"] for item in self.media.state["items"]}, original_ids)

        delete_buttons = [item for item in self._visual_items() if item.objectName() == "mediaDeleteButton"]
        self.assertEqual(len(delete_buttons), 5)
        self._click(delete_buttons[0])
        self.assertTrue(dialog.property("visible"))
        self._click(confirm)
        QTest.qWait(120)
        self.assertFalse(dialog.property("visible"))
        self.assertEqual(len(self.media.state["items"]), 4)
        self.assertEqual(len(self.media.state["filteredItems"]), 4)

        reopened = MediaRepository(self.database_path)
        self.assertEqual(len(reopened.items()), 4)
        self.assertEqual(len(reopened.legacy_items()), 5)
        self.assertEqual(legacy_before, reopened.legacy_items())
        self.assertEqual(len(reopened.deleted_item_ids()), 1)


if __name__ == "__main__":
    unittest.main()
