from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, QUrl
from PySide6.QtTest import QTest
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
from wanxiang.database import load_imported_data
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
)


def _write_migration_package(path: Path) -> None:
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    raw_values["richangji-state-v1"] = json.dumps({
        "version": 2,
        "records": [{
            "id": "synthetic-migration-preview-row",
            "type": "money",
            "date": "2026-09-27",
            "createdAt": 1,
            "sample": False,
            "data": {"amount": 9, "flow": "expense", "note": "synthetic preview only"},
        }],
        "habits": [],
        "mediaItems": [],
        "settings": {"brand": {"name": "合成预览品牌"}},
    }, ensure_ascii=False)
    payload = {
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-migration-ui",
        "exportedAt": "2026-09-27T11:00:00Z",
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class MigrationQmlIntegrationTests(unittest.TestCase):
    """Exercise the production migration picker handler without applying data."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.native_dir = Path(__file__).resolve().parents[1]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-migration-qml-")
        self.addCleanup(self.temp_dir.cleanup)
        self.temp_path = Path(self.temp_dir.name)
        self.database_path = self.temp_path / "synthetic.sqlite3"
        self.engine = QQmlApplicationEngine()
        self.addCleanup(self._destroy_engine)

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
        self.engine.load(QUrl.fromLocalFile(str(self.native_dir / "qml" / "Main.qml")))
        self.assertTrue(self.engine.rootObjects(), "production Main.qml failed to load")
        self.window = self.engine.rootObjects()[0]
        self.window.resize(1480, 960)
        self.window.show()
        QTest.qWait(100)

        self.file_picker = self.window.findChild(QObject, "migrationFileDialog")
        self.preview_dialog = self.window.findChild(QObject, "migrationPreviewDialog")
        self.cancel_button = self.window.findChild(QObject, "migrationPreviewCancelButton")
        self.assertIsNotNone(self.file_picker)
        self.assertIsNotNone(self.preview_dialog)
        self.assertIsNotNone(self.cancel_button)

    def _destroy_engine(self) -> None:
        if getattr(self, "engine", None) is not None:
            self.engine.deleteLater()
            QTest.qWait(30)

    def test_migration_json_picker_previews_and_cancel_keeps_database_unmodified(self) -> None:
        filters = [str(value) for value in self.file_picker.property("nameFilters")]
        self.assertTrue(any("*.json" in value for value in filters), filters)
        package_path = self.temp_path / "synthetic-legacy-package.json"
        _write_migration_package(package_path)
        before = load_imported_data(self.database_path)

        invoked = QMetaObject.invokeMethod(
            self.window,
            "showMigrationPreview",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", QUrl.fromLocalFile(str(package_path))),
        )
        self.assertTrue(invoked, "the production migration file handler was not invokable")
        QTest.qWait(50)
        self.assertTrue(self.preview_dialog.property("visible"))
        report = self.window.property("migrationReport")
        self.assertEqual(report["summary"]["keys_total"], len(STORAGE_KEYS))
        self.assertEqual(report["summary"]["records"], 1)
        self.assertTrue(report["checksum"])
        self.assertFalse(self.window.property("backupController").property("restart_requested"))

        self.assertTrue(QMetaObject.invokeMethod(
            self.cancel_button, "click", Qt.ConnectionType.DirectConnection
        ))
        QTest.qWait(50)
        self.assertFalse(self.preview_dialog.property("visible"))
        self.assertFalse(self.controllers["migrationController"].applyPreview()["ok"])
        after = load_imported_data(self.database_path)
        self.assertEqual(after, before, "preview and cancel must not import migration data")


if __name__ == "__main__":
    unittest.main()
