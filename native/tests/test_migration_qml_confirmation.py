from __future__ import annotations

import json
import gc
import os
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
import warnings

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
    merge_effective_records,
)
from wanxiang.brand import BrandBridge, BrandRepository
from wanxiang.converter import ConverterBridge
from wanxiang.converter_engines import ConverterEngineUpdateBridge
from wanxiang.database import load_imported_data
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    SOURCE_IDENTITY,
    STORAGE_KEYS,
    STORAGE_KEYS_V1,
    calculate_checksum,
)


def _package_payload(*, note: str = "合成数据：仅供迁移确认测试。") -> dict[str, object]:
    state = {
        "version": 2,
        "records": [
            {
                "id": "synthetic-confirmation-record",
                "type": "money",
                "date": "2026-09-28",
                "createdAt": 1727500000000,
                "sample": False,
                "data": {"amount": 12.5, "flow": "expense", "note": note},
            }
        ],
        "habits": [
            {"key": "synthetic-confirmation-habit", "name": "合成习惯", "entries": {}}
        ],
        "mediaItems": [{"name": "合成书目", "type": "book", "status": "reading"}],
        "settings": {"brand": {"name": "合成品牌"}},
    }
    # Keep the exact source strings, including the deliberately spaced JSON, so the
    # test exercises the legacy_storage preservation contract as well as parsing.
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    raw_values["richangji-state-v1"] = json.dumps(
        state, ensure_ascii=False, indent=2
    )
    raw_values["wanxiang-paper-layout-v2"] = '{ "order": ["home", "money"] }'
    raw_values["wanxiang-issue-questions-v1"] = '[ "合成问题" ]'
    payload: dict[str, object] = {
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-qml-confirmation-test",
        "exportedAt": "2026-09-28T09:00:00Z",
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    }
    return payload


def _cross_module_package_payload() -> dict[str, object]:
    today = date.today()
    yesterday = today - timedelta(days=1)
    today_key = today.isoformat()
    yesterday_key = yesterday.isoformat()
    state = {
        "version": 2,
        "records": [
            {
                "id": "synthetic-money",
                "type": "money",
                "date": yesterday_key,
                "createdAt": 10,
                "sample": False,
                "data": {
                    "flow": "expense", "amount": 32, "category": "吃饭",
                    "note": "合成记账",
                },
            },
            {
                "id": "synthetic-fitness",
                "type": "fitness",
                "date": yesterday_key,
                "createdAt": 20,
                "sample": False,
                "data": {"weight": 62.5, "duration": 25, "note": "合成健身"},
            },
            {
                "id": "synthetic-planner",
                "type": "planner",
                "date": today_key,
                "createdAt": 30,
                "sample": False,
                "data": {
                    "title": "合成今日计划", "time": "18:30", "priority": "normal",
                    "list": "生活", "note": "", "remind": False, "done": False,
                },
            },
            {
                "id": "synthetic-shopping",
                "type": "home",
                "date": yesterday_key,
                "createdAt": 40,
                "sample": False,
                "data": {
                    "name": "合成待买物品", "quantity": "2 件", "category": "家居",
                    "price": 45, "priority": "normal", "note": "", "bought": False,
                },
            },
        ],
        "habits": [
            {
                "id": "synthetic-habit", "key": "walk", "name": "合成散步",
                "entries": {yesterday_key: 1}, "target": 1, "unit": "次", "sample": False,
            }
        ],
        "mediaItems": [
            {
                "id": "synthetic-media", "name": "合成书目", "type": "书",
                "status": "想看", "rating": 4, "date": yesterday_key,
                "cover": "", "sample": False,
            }
        ],
        "settings": {
            "budget": 5000, "archiveFilter": "all",
            "dailyFlowNotes": {yesterday_key: "合成跟进"},
        },
    }
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    raw_values["richangji-state-v1"] = json.dumps(state, ensure_ascii=False, indent=2)
    raw_values["richangji-samples-cleared"] = "1"
    raw_values["wanxiang-paper-layout-v2"] = '{ "order": ["home", "money"], "slots": {}, "hidden": [] }'
    raw_values["wanxiang-daily-issues-v1"] = '{ "active": null, "archive": [] }'
    raw_values["wanxiang-issue-questions-v1"] = '[ { "text": "合成问题" } ]'
    raw_values["wanxiang-issue-topics-v1"] = '[ "technology" ]'
    raw_values["wanxiang-issue-preferences-v1"] = '{ "subtopics": "合成主题", "sources": "合成来源", "presetSources": ["Reuters"] }'
    raw_values["wanxiang-issue-clippings-v1"] = "[]"
    raw_values["wanxiang-saved-knowledge"] = "1"
    return {
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-cross-module-test",
        "exportedAt": "2026-09-28T09:00:00Z",
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    }


class MigrationQmlConfirmationTests(unittest.TestCase):
    """Exercise production Main.qml confirmation and database restart readback."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.native_dir = Path(__file__).resolve().parents[1]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-migration-confirm-qml-")
        self.addCleanup(self._cleanup_temp_directory)
        self.temp_path = Path(self.temp_dir.name)
        self.database_path = self.temp_path / "isolated-synthetic.sqlite3"
        self.package_path = self.temp_path / "synthetic-package.json"
        self.payload = _package_payload()
        self.package_path.write_text(
            json.dumps(self.payload, ensure_ascii=False), encoding="utf-8"
        )
        self.engine = None
        self.controllers = {}
        self.addCleanup(self._destroy_engine)
        self._build_engine()

    def _cleanup_temp_directory(self) -> None:
        self.temp_dir.cleanup()
        self.assertFalse(
            self.temp_path.exists(),
            "the isolated database directory must be releasable after bridge cleanup",
        )

    def _build_engine(self) -> None:
        self.engine = QQmlApplicationEngine()
        migration = MigrationBridge(self.database_path)
        snapshot = migration.data
        finance = FinanceBridge(self.database_path, snapshot)
        self.controllers = {
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
            "brandController": BrandBridge(
                BrandRepository(self.database_path), self.engine
            ),
        }
        migration = self.controllers["migrationController"]
        for key in (
            "habitController", "preferencesController", "dailyController",
            "readingController", "financeController", "fitnessController",
            "plannerController", "shoppingController", "mediaController",
            "archiveController", "brandController",
        ):
            controller = self.controllers[key]
            migration.dataChanged.connect(
                lambda controller=controller: controller.adoptImportedData(migration.data)
            )

        def refresh_daily_activity() -> None:
            finance = self.controllers["financeController"]
            fitness = self.controllers["fitnessController"]
            planner = self.controllers["plannerController"]
            shopping = self.controllers["shoppingController"]
            habit = self.controllers["habitController"]
            media = self.controllers["mediaController"]
            daily = self.controllers["dailyController"]
            archive = self.controllers["archiveController"]
            effective = merge_effective_records(
                finance.activity_records(),
                (
                    (fitness.activity_records(), "fitness"),
                    (planner.activity_records(), "planner"),
                    (shopping.activity_records(), "home"),
                ),
                (
                    finance.activity_tombstones(),
                    fitness.activity_tombstones(),
                    planner.activity_tombstones(),
                    shopping.activity_tombstones(),
                ),
            )
            daily.updateActivity(
                records=effective,
                habits=habit.state.get("habits", []),
                media_items=media.activity_items(),
            )
            archive.updateRecords(effective)

        for key in (
            "habitController", "financeController", "fitnessController",
            "plannerController", "shoppingController", "mediaController",
        ):
            self.controllers[key].stateChanged.connect(refresh_daily_activity)
        migration.dataChanged.connect(refresh_daily_activity)
        self.engine.setInitialProperties(self.controllers)
        self.engine.load(QUrl.fromLocalFile(str(self.native_dir / "qml" / "Main.qml")))
        self.assertTrue(self.engine.rootObjects(), "production Main.qml failed to load")
        self.window = self.engine.rootObjects()[0]
        self.window.resize(1480, 960)
        self.window.show()
        QTest.qWait(80)
        self.preview_dialog = self.window.findChild(QObject, "migrationPreviewDialog")
        self.cancel_button = self.window.findChild(
            QObject, "migrationPreviewCancelButton"
        )
        self.assertIsNotNone(self.preview_dialog)
        self.assertIsNotNone(self.cancel_button)
        self.confirm_button = self.window.findChild(
            QObject, "migrationPreviewConfirmButton"
        )
        self.assertIsNotNone(self.confirm_button)
        self.status_dialog = next(
            (
                item
                for item in self.window.findChildren(QObject)
                if str(item.property("title") or "") == "数据迁移"
            ),
            None,
        )
        self.assertIsNotNone(self.status_dialog)

    def _destroy_engine(self) -> None:
        engine = getattr(self, "engine", None)
        if engine is not None:
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always", ResourceWarning)
                window = getattr(self, "window", None)
                if window is not None:
                    window.close()
                engine.deleteLater()
                self.engine = None
                QTest.qWait(40)
                self.controllers = {}
                self.window = None
                self.preview_dialog = None
                self.cancel_button = None
                self.confirm_button = None
                self.status_dialog = None
                gc.collect()
            leaked_sqlite = [
                str(item.message)
                for item in captured
                if issubclass(item.category, ResourceWarning)
                and "unclosed database" in str(item.message)
            ]
            self.assertEqual(leaked_sqlite, [])

    def _assert_database_can_be_released_and_reopened(self) -> None:
        """Probe Windows file-handle release after a complete bridge teardown."""
        probe_path = self.database_path.with_name("isolated-synthetic.release-probe")
        self.database_path.replace(probe_path)
        try:
            probe_path.replace(self.database_path)
        finally:
            if probe_path.exists() and not self.database_path.exists():
                probe_path.replace(self.database_path)

    def _show_preview(self, package_path: Path) -> None:
        invoked = QMetaObject.invokeMethod(
            self.window,
            "showMigrationPreview",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", QUrl.fromLocalFile(str(package_path))),
        )
        self.assertTrue(invoked, "the production migration preview handler was not invokable")
        QTest.qWait(50)

    def _click(self, control: QObject) -> None:
        self.assertTrue(
            QMetaObject.invokeMethod(
                control, "click", Qt.ConnectionType.DirectConnection
            )
        )
        QTest.qWait(60)

    def _table_counts(self) -> dict[str, int]:
        if not self.database_path.is_file():
            return {}
        connection = sqlite3.connect(self.database_path)
        try:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            tables = (
                "migration_batches",
                "migration_sources",
                "legacy_storage",
                "json_documents",
                "records",
                "habits",
                "media_items",
            )
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
                if table in names
            }
        finally:
            connection.close()

    def _assert_status_contains(self, fragment: str) -> None:
        assert self.status_dialog is not None
        self.assertTrue(self.status_dialog.property("visible"))
        self.assertIn(fragment, str(self.window.property("migrationNotice")))

    def test_confirm_persists_package_and_new_bridge_reads_it_after_restart(self) -> None:
        baseline = load_imported_data(self.database_path)
        raw_values = self.payload["keys"]
        assert isinstance(raw_values, dict)
        expected_checksum = str(self.payload["checksum"])

        self._show_preview(self.package_path)
        self.assertTrue(self.preview_dialog.property("visible"))
        report = self.window.property("migrationReport")
        self.assertEqual(report["summary"]["keys_total"], len(STORAGE_KEYS))
        self.assertEqual(report["summary"]["records"], 1)
        self.assertEqual(report["summary"]["habits"], 1)
        self.assertEqual(report["summary"]["media_items"], 1)
        self.assertEqual(report["checksum"], expected_checksum)
        structure_summary = self.window.findChild(QObject, "migrationStructureSummary")
        self.assertIsNotNone(structure_summary)
        self.assertIn("设置字段 1", str(structure_summary.property("text")))
        self.assertIn("顺序/槽位/隐藏 2/0/0", str(structure_summary.property("text")))
        self.assertEqual(load_imported_data(self.database_path), baseline)

        assert self.confirm_button is not None
        self._click(self.confirm_button)
        self.assertFalse(self.preview_dialog.property("visible"))
        self._assert_status_contains("导入成功")

        imported = load_imported_data(self.database_path)
        self.assertEqual(imported["status"], "loaded")
        self.assertEqual(imported["raw_values"], raw_values)
        self.assertEqual(
            imported["documents"]["richangji-state-v1"],
            json.loads(raw_values["richangji-state-v1"]),
        )
        self.assertEqual(
            imported["documents"]["wanxiang-paper-layout-v2"],
            {"order": ["home", "money"]},
        )
        self.assertEqual(imported["entities"]["records"][0]["id"], "synthetic-confirmation-record")
        self.assertEqual(imported["summary"]["records"], 1)
        self.assertEqual(imported["summary"]["habits"], 1)
        self.assertEqual(imported["summary"]["media_items"], 1)

        connection = sqlite3.connect(self.database_path)
        try:
            metadata = connection.execute(
                "SELECT batch_id, source_identity, source_version, source_schema_version, "
                "exported_at, checksum_sha256 FROM migration_batches"
            ).fetchone()
            self.assertEqual(
                metadata,
                (
                    expected_checksum,
                    SOURCE_IDENTITY,
                    "synthetic-qml-confirmation-test",
                    PACKAGE_SCHEMA_VERSION,
                    "2026-09-28T09:00:00Z",
                    expected_checksum,
                ),
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM legacy_storage").fetchone()[0],
                len(STORAGE_KEYS),
            )
            exact_raw = dict(
                connection.execute(
                    "SELECT storage_key, raw_value FROM legacy_storage"
                ).fetchall()
            )
            self.assertEqual(exact_raw, raw_values)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM json_documents").fetchone()[0],
                3,
            )
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM records").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM habits").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM media_items").fetchone()[0],
                1,
            )
        finally:
            connection.close()

        # Destroy the first QML engine and construct fresh startup bridges, as on app restart.
        self._destroy_engine()
        self._assert_database_can_be_released_and_reopened()
        self._build_engine()
        restarted = self.controllers["migrationController"]
        self.assertEqual(restarted.data["raw_values"], raw_values)
        self.assertEqual(restarted.data["import_info"]["checksum_sha256"], expected_checksum)
        self.assertEqual(
            restarted.data["entities"]["records"][0]["id"],
            "synthetic-confirmation-record",
        )

        counts_before_repeat = self._table_counts()
        self._show_preview(self.package_path)
        assert self.confirm_button is not None
        self._click(self.confirm_button)
        self._assert_status_contains("没有重复写入")
        self.assertEqual(self._table_counts(), counts_before_repeat)
        self.assertEqual(load_imported_data(self.database_path)["raw_values"], raw_values)

    def test_qml_import_keeps_schema_v1_nine_key_compatibility(self) -> None:
        payload = _package_payload()
        raw_values = dict(payload["keys"])
        raw_values.pop("wanxiang-planner-sync-device-v1")
        payload["schemaVersion"] = 1
        payload["keys"] = raw_values
        payload["checksum"] = calculate_checksum(raw_values, schema_version=1)
        self.package_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

        self._show_preview(self.package_path)
        report = self.window.property("migrationReport")
        self.assertEqual(report["summary"]["keys_total"], len(STORAGE_KEYS_V1))
        assert self.confirm_button is not None
        self._click(self.confirm_button)

        loaded = load_imported_data(self.database_path)
        self.assertEqual(loaded["raw_values"], raw_values)
        self.assertEqual(loaded["summary"]["keys_total"], len(STORAGE_KEYS_V1))
        self.assertEqual(loaded["import_info"]["source_schema_version"], 1)

    def test_confirmed_migration_reaches_life_modules_daily_review_and_archive(self) -> None:
        payload = _cross_module_package_payload()
        raw_values = payload["keys"]
        assert isinstance(raw_values, dict)
        self.package_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        expected_checksum = str(payload["checksum"])
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        self._show_preview(self.package_path)
        self.assertTrue(self.preview_dialog.property("visible"))
        report = self.window.property("migrationReport")
        self.assertEqual(report["summary"]["keys_total"], len(STORAGE_KEYS))
        self.assertEqual(report["summary"]["records"], 4)
        self.assertEqual(report["summary"]["habits"], 1)
        self.assertEqual(report["summary"]["media_items"], 1)
        assert self.confirm_button is not None
        self._click(self.confirm_button)
        self._assert_status_contains("导入成功")

        imported = load_imported_data(self.database_path)
        self.assertEqual(imported["raw_values"], raw_values)
        self.assertEqual(imported["import_info"]["checksum_sha256"], expected_checksum)
        self.assertEqual(imported["summary"]["records"], 4)
        self.assertEqual(imported["summary"]["habits"], 1)
        self.assertEqual(imported["summary"]["media_items"], 1)
        for key, raw in raw_values.items():
            if raw is not None and key not in {"richangji-samples-cleared", "wanxiang-saved-knowledge"}:
                self.assertEqual(imported["documents"][key], json.loads(raw))

        self._destroy_engine()
        self._assert_database_can_be_released_and_reopened()
        self._build_engine()
        controllers = self.controllers
        migration = controllers["migrationController"]
        finance = controllers["financeController"]
        fitness = controllers["fitnessController"]
        planner = controllers["plannerController"]
        shopping = controllers["shoppingController"]
        media = controllers["mediaController"]
        habit = controllers["habitController"]
        daily = controllers["dailyController"]
        archive = controllers["archiveController"]

        self.assertEqual(migration.data["raw_values"], raw_values)
        self.assertEqual(migration.data["import_info"]["checksum_sha256"], expected_checksum)
        self.assertIn("synthetic-money", {row["id"] for row in finance.state["records"]})
        self.assertIn("synthetic-fitness", {row["id"] for row in fitness.state["records"]})
        self.assertIn("synthetic-planner", {row["id"] for row in planner.activity_records()})
        self.assertIn("synthetic-shopping", {row["id"] for row in shopping.state["shoppingRecords"]})
        self.assertIn("synthetic-media", {row["id"] for row in media.state["items"]})

        effective = merge_effective_records(
            finance.activity_records(),
            (
                (fitness.activity_records(), "fitness"),
                (planner.activity_records(), "planner"),
                (shopping.activity_records(), "home"),
            ),
            (
                finance.activity_tombstones(),
                fitness.activity_tombstones(),
                planner.activity_tombstones(),
                shopping.activity_tombstones(),
            ),
        )
        daily.updateActivity(
            records=effective,
            habits=habit.state["habits"],
            media_items=media.activity_items(),
        )
        archive.updateRecords(effective)
        self.assertEqual(daily.review["date"], yesterday)
        review_titles = {item["title"] for item in daily.review["items"]}
        self.assertTrue(
            {"合成记账", "合成健身", "合成待买物品", "合成散步", "合成书目"}.issubset(review_titles),
            review_titles,
        )
        self.assertEqual(daily.review["followUp"], "合成跟进")
        self.assertEqual(daily.todayWork["date"], today)
        self.assertIn("合成今日计划", {item["title"] for item in daily.todayWork["tasks"]})

        archive_state = archive.state
        self.assertEqual(archive_state["recordCount"], 4)
        archive_ids = {
            item["id"]
            for group in archive_state["groups"]
            for item in group["records"]
        }
        self.assertEqual(
            archive_ids,
            {"synthetic-money", "synthetic-fitness", "synthetic-planner", "synthetic-shopping"},
        )
        self.assertNotIn("synthetic-media", archive_ids)

        preserved = load_imported_data(self.database_path)
        self.assertEqual(preserved["raw_values"], raw_values)
        self.assertEqual(preserved["import_info"]["checksum_sha256"], expected_checksum)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

    def test_cancel_invalid_package_and_confirmation_failure_leave_import_unchanged(self) -> None:
        baseline = load_imported_data(self.database_path)

        self._show_preview(self.package_path)
        assert self.cancel_button is not None
        self._click(self.cancel_button)
        self.assertFalse(self.preview_dialog.property("visible"))
        self.assertEqual(load_imported_data(self.database_path), baseline)
        self.assertEqual(self._table_counts(), {})

        invalid_path = self.temp_path / "invalid-package.json"
        invalid_path.write_text('{"format":"not-a-migration-package"}', encoding="utf-8")
        self._show_preview(invalid_path)
        self._assert_status_contains("不是受支持的 FLUKE 旧版迁移包")
        self.assertEqual(load_imported_data(self.database_path), baseline)
        self.assertEqual(self._table_counts(), {})

        # Import the first package, then force the next snapshot transaction to fail.
        self._show_preview(self.package_path)
        assert self.confirm_button is not None
        self._click(self.confirm_button)
        self._assert_status_contains("导入成功")
        imported_before_failure = load_imported_data(self.database_path)
        counts_before_failure = self._table_counts()

        conflict_path = self.temp_path / "synthetic-conflicting-package.json"
        conflict = _package_payload(note="另一份合成迁移包")
        conflict_path.write_text(json.dumps(conflict, ensure_ascii=False), encoding="utf-8")
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                "CREATE TRIGGER reject_next_snapshot BEFORE INSERT ON json_documents "
                "BEGIN SELECT RAISE(ABORT,'synthetic confirmation failure'); END"
            )
            connection.commit()
        finally:
            connection.close()
        self._show_preview(conflict_path)
        self.assertTrue(self.preview_dialog.property("visible"))
        self._click(self.confirm_button)
        self._assert_status_contains("synthetic confirmation failure")
        self.assertEqual(load_imported_data(self.database_path), imported_before_failure)
        self.assertEqual(self._table_counts(), counts_before_failure)

    def test_new_snapshot_preview_shows_only_differences_then_requests_restart(self) -> None:
        first_payload = self.payload
        first_values = first_payload["keys"]
        assert isinstance(first_values, dict)
        first_checksum = str(first_payload["checksum"])

        self._show_preview(self.package_path)
        assert self.confirm_button is not None
        self._click(self.confirm_button)
        self.assertTrue(self.window.property("migrationRestartRequired"))

        self._destroy_engine()
        self._build_engine()

        first_import = load_imported_data(self.database_path)
        self.assertEqual(first_import["import_info"]["checksum_sha256"], first_checksum)
        second_payload = _package_payload(note="另一条合成备注；同一个迁移来源的新快照。")
        second_values = second_payload["keys"]
        assert isinstance(second_values, dict)
        second_checksum = str(second_payload["checksum"])
        second_path = self.temp_path / "synthetic-package-revision.json"
        second_path.write_text(json.dumps(second_payload, ensure_ascii=False), encoding="utf-8")

        self._show_preview(second_path)
        self.assertTrue(self.preview_dialog.property("visible"))
        report = self.window.property("migrationReport")
        self.assertEqual(report["status"], "new_snapshot")
        self.assertTrue(report["preview"]["willActivate"])
        revision_notice = self.window.findChild(QObject, "migrationRevisionNotice")
        diff_summary = self.window.findChild(QObject, "migrationDiffSummary")
        self.assertIsNotNone(revision_notice)
        self.assertIsNotNone(diff_summary)
        self.assertTrue(revision_notice.property("visible"))
        self.assertTrue(diff_summary.property("visible"))
        self.assertIn("存储键变化：新增 0", diff_summary.property("text"))
        self.assertIn("记录变化：新增 0 · 修改 1 · 移除 0", diff_summary.property("text"))
        self.assertEqual(load_imported_data(self.database_path), first_import)
        self.assertEqual(self._table_counts()["migration_batches"], 1)
        assert self.confirm_button is not None
        self.assertEqual(self.confirm_button.property("text"), "确认切换到新快照")

        self._click(self.confirm_button)
        self._assert_status_contains("新快照已设为当前数据")
        self.assertTrue(self.window.property("migrationRestartRequired"))
        second_import = load_imported_data(self.database_path)
        self.assertEqual(second_import["import_info"]["checksum_sha256"], second_checksum)
        self.assertEqual(second_import["raw_values"], second_values)
        self.assertEqual(self._table_counts()["migration_batches"], 2)
        self.assertEqual(self._table_counts()["legacy_storage"], 2 * len(STORAGE_KEYS))

        connection = sqlite3.connect(self.database_path)
        try:
            old_raw_values = dict(
                connection.execute(
                    "SELECT storage_key, raw_value FROM legacy_storage WHERE batch_id=?",
                    (first_checksum,),
                ).fetchall()
            )
            active_batch_id = connection.execute(
                "SELECT active_batch_id FROM migration_sources WHERE source_identity=?",
                (SOURCE_IDENTITY,),
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(old_raw_values, first_values)
        self.assertEqual(active_batch_id, second_checksum)

        restart_button = self.window.findChild(QObject, "migrationStatusConfirmButton")
        self.assertIsNotNone(restart_button)
        self.assertEqual(restart_button.property("text"), "重新打开软件")
        self._click(restart_button)
        self.assertTrue(self.controllers["migrationController"].restart_requested)


if __name__ == "__main__":
    unittest.main()
