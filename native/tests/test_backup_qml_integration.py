from __future__ import annotations

from datetime import date
import json
import gc
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import weakref
import zipfile

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
from wanxiang.backup import BACKUP_FORMAT, DATABASE_MEMBER, MANIFEST_MEMBER
from wanxiang.converter import ConverterBridge
from wanxiang.converter_engines import ConverterEngineUpdateBridge
from wanxiang.database import import_package, load_imported_data
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)
from wanxiang.webdav_planner import encrypt_snapshot


def _migration_package(
    *,
    records: list[dict[str, object]] | None = None,
    settings: dict[str, object] | None = None,
) -> object:
    legacy_settings: dict[str, object] = {"brand": {"name": "当前合成品牌"}}
    if settings:
        legacy_settings.update(settings)
    state = {
        "records": records if records is not None else [{
            "id": "current-before-restore",
            "type": "money",
            "date": "2026-09-27",
            "createdAt": 1,
            "sample": False,
            "data": {"amount": 31, "flow": "expense", "note": "synthetic current data"},
        }],
        "habits": [],
        "mediaItems": [],
        "settings": legacy_settings,
    }
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    raw_values["richangji-state-v1"] = json.dumps(state, ensure_ascii=False)
    return validate_package({
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": "synthetic-backup-ui",
        "exportedAt": "2026-09-27T10:00:00Z",
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    })


def _write_legacy_backup(path: Path) -> None:
    payload = {
        "format": "daily-atlas-backup",
        "version": 1,
        "exportedAt": "2026-09-27T10:30:00.000Z",
        "state": {
            "records": [{
                "id": "legacy-restored-row",
                "type": "money",
                "date": "2026-09-26",
                "createdAt": 2,
                "sample": False,
                "data": {"amount": 17, "flow": "expense", "note": "synthetic legacy backup"},
            }],
            "habits": [],
            "mediaItems": [],
            "settings": {"brand": {"name": "旧版合成品牌", "theme": "forest"}},
        },
        "issueContent": {"active": None, "archive": []},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class BackupQmlIntegrationTests(unittest.TestCase):
    """Exercise production QML backup export, cancellation, restore and readback."""

    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.native_dir = Path(__file__).resolve().parents[1]

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-backup-qml-")
        self.addCleanup(self._cleanup_temp_directory)
        self.temp_path = Path(self.temp_dir.name)
        self.database_path = self.temp_path / "synthetic.sqlite3"
        import_package(_migration_package(), self.database_path)
        self.engine = None
        self.controllers: dict[str, QObject] = {}
        self.addCleanup(self._destroy_engine)

        self._build_engine()

    def _build_engine(self) -> None:
        self.engine = QQmlApplicationEngine()
        migration = MigrationBridge(self.database_path)
        snapshot = migration.data
        finance = FinanceBridge(self.database_path, snapshot)
        self.backup = BackupBridge(self.database_path, finance)
        controllers = {
            "migrationController": migration,
            "weatherController": WeatherBridge(self.database_path, snapshot),
            "newsController": NewsBridge(self.database_path, snapshot),
            "habitController": HabitBridge(self.database_path, snapshot),
            "preferencesController": IssuePreferencesBridge(self.database_path, snapshot),
            "readingController": ReadingBridge(self.database_path, snapshot),
            "dailyController": DailyBridge(self.database_path, snapshot),
            "financeController": finance,
            "backupController": self.backup,
            "fitnessController": FitnessBridge(self.database_path, snapshot),
            "plannerController": PlannerBridge(self.database_path, snapshot),
            "shoppingController": ShoppingBridge(self.database_path, snapshot),
            "mediaController": MediaBridge(self.database_path, snapshot),
            "archiveController": ArchiveBridge(self.database_path, snapshot),
            "converterController": ConverterBridge(),
            "converterEngineController": ConverterEngineUpdateBridge(self.temp_path / "engine-updates"),
            "brandController": BrandBridge(BrandRepository(self.database_path), self.engine),
        }
        self.migration = migration
        self.finance = finance
        self.controllers = controllers
        self.engine.setInitialProperties(controllers)
        qml_path = self.native_dir / "qml" / "Main.qml"
        self.engine.load(QUrl.fromLocalFile(str(qml_path)))
        self.assertTrue(self.engine.rootObjects(), "production Main.qml failed to load")
        self.window = self.engine.rootObjects()[0]
        self.window.resize(1480, 960)
        self.window.show()
        QTest.qWait(120)

        self.file_picker = self.window.findChild(QObject, "fullBackupOpenDialog")
        self.save_picker = self.window.findChild(QObject, "fullBackupSaveDialog")
        self.preview_dialog = self.window.findChild(QObject, "fullBackupPreviewDialog")
        self.preview_summary = self.window.findChild(QObject, "fullBackupPreviewSummary")
        self.cancel_button = self.window.findChild(QObject, "backupPreviewCancelButton")
        self.confirm_button = self.window.findChild(QObject, "backupPreviewConfirmButton")
        self.encrypted_restore_dialog = self.window.findChild(
            QObject, "encryptedRestorePasswordDialog"
        )
        self.encrypted_restore_password_input = self.window.findChild(
            QObject, "encryptedRestorePasswordInput"
        )
        self.encrypted_restore_continue = self.window.findChild(
            QObject, "encryptedRestoreContinueButton"
        )
        self.encrypted_export_password_input = self.window.findChild(
            QObject, "encryptedExportPasswordInput"
        )
        self.encrypted_export_confirmation_input = self.window.findChild(
            QObject, "encryptedExportConfirmationInput"
        )
        for label, item in (
            ("backup file picker", self.file_picker),
            ("backup save picker", self.save_picker),
            ("backup preview dialog", self.preview_dialog),
            ("backup preview summary", self.preview_summary),
            ("backup cancel button", self.cancel_button),
            ("backup confirm button", self.confirm_button),
            ("encrypted restore dialog", self.encrypted_restore_dialog),
            ("encrypted restore password", self.encrypted_restore_password_input),
            ("encrypted restore continue", self.encrypted_restore_continue),
            ("encrypted export password", self.encrypted_export_password_input),
            ("encrypted export confirmation", self.encrypted_export_confirmation_input),
        ):
            self.assertIsNotNone(item, f"production {label} was not found")

    def _cleanup_temp_directory(self) -> None:
        path = self.temp_path
        self.temp_dir.cleanup()
        self.assertFalse(path.exists(), "the isolated backup directory must be removable")

    def _destroy_engine(self) -> None:
        engine = getattr(self, "engine", None)
        if engine is not None:
            window = getattr(self, "window", None)
            if window is not None:
                window.close()
            engine.deleteLater()
            QTest.qWait(30)
        self.engine = None
        self.window = None
        self.controllers = {}
        for name in (
            "migration", "finance", "backup", "file_picker", "save_picker",
            "preview_dialog", "preview_summary", "cancel_button", "confirm_button",
            "encrypted_restore_dialog", "encrypted_restore_password_input",
            "encrypted_restore_continue", "encrypted_export_password_input",
            "encrypted_export_confirmation_input",
        ):
            setattr(self, name, None)
        gc.collect()
        QTest.qWait(20)

    def _replace_database_with_package(self, package: object) -> None:
        """Re-seed only this test's temporary database, then load production QML."""
        self._destroy_engine()
        for suffix in ("-wal", "-shm", "-journal"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)
        self.database_path.unlink(missing_ok=True)
        import_package(package, self.database_path)
        self._build_engine()

    def _assert_database_can_be_released_and_reopened(self) -> None:
        probe_path = self.database_path.with_name("synthetic.release-probe")
        self.database_path.replace(probe_path)
        try:
            probe_path.replace(self.database_path)
        finally:
            if probe_path.exists() and not self.database_path.exists():
                probe_path.replace(self.database_path)

    def _show_preview_from_selected_file(self, backup_path: Path) -> None:
        invoked = QMetaObject.invokeMethod(
            self.window,
            "showFullBackupPreview",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", QUrl.fromLocalFile(str(backup_path))),
        )
        self.assertTrue(invoked, "the production backup file handler was not invokable")
        QTest.qWait(50)
        self.assertTrue(self.preview_dialog.property("visible"))

    def _show_encrypted_password_prompt(self, backup_path: Path) -> None:
        invoked = QMetaObject.invokeMethod(
            self.window,
            "showFullBackupPreview",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", QUrl.fromLocalFile(str(backup_path))),
        )
        self.assertTrue(invoked, "the encrypted backup handler was not invokable")
        QTest.qWait(50)
        self.assertTrue(self.encrypted_restore_dialog.property("visible"))

    def _click(self, button: QObject) -> None:
        self.assertTrue(
            QMetaObject.invokeMethod(button, "click", Qt.ConnectionType.DirectConnection)
        )
        QTest.qWait(50)

    def test_legacy_json_filter_preview_cancel_and_confirm_restore(self) -> None:
        filters = [str(value) for value in self.file_picker.property("nameFilters")]
        self.assertTrue(any("*.wxbak" in value for value in filters), filters)
        self.assertTrue(any("*.json" in value for value in filters), filters)
        save_filters = [str(value) for value in self.save_picker.property("nameFilters")]
        self.assertTrue(any("*.wxbak" in value for value in save_filters), save_filters)
        self.assertFalse(any("*.json" in value for value in save_filters), save_filters)

        backup_path = self.temp_path / "legacy-full-backup.json"
        _write_legacy_backup(backup_path)

        before = load_imported_data(self.database_path)
        self.assertEqual(before["entities"]["records"][0]["id"], "current-before-restore")
        database_before_legacy_restore = self.database_path.read_bytes()

        self._show_preview_from_selected_file(backup_path)
        report = self.window.property("backupReport")
        self.assertEqual(report["sourceFormat"], "daily-atlas-backup-v1")
        self.assertIn("旧版完整备份", str(self.preview_summary.property("text")))
        self.assertIn("记录 1", str(self.preview_summary.property("text")))
        QTest.keyClick(self.window, Qt.Key.Key_Escape)
        QTest.qWait(50)
        self.assertFalse(self.preview_dialog.property("visible"))
        self.assertFalse(self.preview_dialog.property("visible"))
        self.assertFalse(self.backup.applyPreview()["ok"], "cancel must clear the pending restore")
        after_cancel = load_imported_data(self.database_path)
        self.assertEqual(after_cancel["entities"]["records"][0]["id"], "current-before-restore")
        self.assertEqual(self.database_path.read_bytes(), database_before_legacy_restore)

        self._show_preview_from_selected_file(backup_path)
        self._click(self.confirm_button)
        self.assertFalse(self.preview_dialog.property("visible"))
        self.assertTrue(self.backup.restart_requested)
        restored = load_imported_data(self.database_path)
        self.assertEqual(restored["entities"]["records"][0]["id"], "legacy-restored-row")
        self.assertEqual(restored["summary"]["media_items"], 0)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

        # The production handler requests an app restart after replacing the DB.
        # Rebuild the startup graph in this test process to verify the next
        # launch reads the restored legacy record from disk.
        old_finance = weakref.ref(self.finance)
        self._destroy_engine()
        gc.collect()
        self.assertIsNone(old_finance(), "the old production bridge graph should be released")
        self._assert_database_can_be_released_and_reopened()

        self._build_engine()
        self.assertEqual(
            self.migration.data["entities"]["records"][0]["id"],
            "legacy-restored-row",
        )
        finance_records = self.finance.state["records"]
        self.assertTrue(
            any(row.get("id") == "legacy-restored-row" for row in finance_records)
        )

        self.window.setProperty("currentSectionIndex", 1)
        QTest.qWait(50)
        finance_page = self.window.findChild(QObject, "financePage")
        self.assertIsNotNone(finance_page, "fresh production Main.qml did not create FinancePage")
        qml_snapshot = finance_page.property("snapshot")
        self.assertTrue(
            any(row.get("id") == "legacy-restored-row" for row in qml_snapshot["records"]),
            "fresh production QML did not read the restored legacy backup state",
        )

    def test_full_backup_export_uses_production_qml_handler(self) -> None:
        target = self.temp_path / "production-export.wxbak"
        before = load_imported_data(self.database_path)
        self.assertEqual(before["entities"]["records"][0]["id"], "current-before-restore")

        invoked = QMetaObject.invokeMethod(
            self.window,
            "exportFullBackup",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", QUrl.fromLocalFile(str(target))),
        )
        self.assertTrue(invoked, "the production backup export handler was not invokable")
        QTest.qWait(50)

        self.assertTrue(target.is_file(), "the production handler did not create the backup")
        self.assertGreater(target.stat().st_size, 0)
        self.assertIn("完整备份已保存", str(self.window.property("backupNotice")))
        preview = self.backup.previewBackup(QUrl.fromLocalFile(str(target)))
        self.assertTrue(preview["ok"], preview)
        self.assertEqual(preview["summary"]["legacy"]["records"], 1)
        self.assertEqual(preview["summary"]["legacy"]["habits"], 0)
        self.backup.cancelPreview()

        after = load_imported_data(self.database_path)
        self.assertEqual(after["entities"]["records"][0]["id"], "current-before-restore")

    def test_encrypted_legacy_preview_cancel_clears_password_then_confirm_restores(self) -> None:
        payload_path = self.temp_path / "legacy.json"
        encrypted_path = self.temp_path / "legacy.wxbackup"
        password = "synthetic-legacy-password"
        _write_legacy_backup(payload_path)
        encrypted_path.write_text(
            encrypt_snapshot(json.loads(payload_path.read_text(encoding="utf-8")), password),
            encoding="utf-8",
        )
        before = self.database_path.read_bytes()

        self._show_encrypted_password_prompt(encrypted_path)
        self.encrypted_restore_password_input.setProperty("text", password)
        self._click(self.encrypted_restore_continue)
        self.assertFalse(self.encrypted_restore_dialog.property("visible"))
        self.assertEqual(self.encrypted_restore_password_input.property("text"), "")
        self.assertTrue(self.preview_dialog.property("visible"))
        self.assertEqual(
            self.window.property("backupReport")["sourceFormat"],
            "daily-atlas-backup-v1-encrypted",
        )
        self.assertEqual(self.backup._pending_encrypted_password, password)

        self._click(self.cancel_button)
        self.assertIsNone(self.backup._pending_backup)
        self.assertIsNone(self.backup._pending_encrypted_password)
        self.assertFalse(self.backup.applyPreview()["ok"])
        self.assertEqual(self.database_path.read_bytes(), before)

        self._show_encrypted_password_prompt(encrypted_path)
        self.encrypted_restore_password_input.setProperty("text", password)
        self._click(self.encrypted_restore_continue)
        self.assertTrue(self.preview_dialog.property("visible"))
        self._click(self.confirm_button)
        self.assertTrue(self.backup.restart_requested)
        self.assertIsNone(self.backup._pending_encrypted_password)
        restored = load_imported_data(self.database_path)
        self.assertEqual(restored["entities"]["records"][0]["id"], "legacy-restored-row")

    def test_encrypted_native_export_uses_qml_password_controls_and_v2_format(self) -> None:
        target = self.temp_path / "native-ui-export.wxbak2"
        password = "synthetic-native-password"
        self.window.setProperty("pendingEncryptedBackupUrl", QUrl.fromLocalFile(str(target)))
        self.encrypted_export_password_input.setProperty("text", password)
        self.encrypted_export_confirmation_input.setProperty("text", password)
        invoked = QMetaObject.invokeMethod(
            self.window,
            "exportEncryptedFullBackup",
            Qt.ConnectionType.DirectConnection,
        )
        self.assertTrue(invoked, "the encrypted backup QML handler was not invokable")
        QTest.qWait(50)
        self.assertTrue(target.is_file())
        envelope = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(envelope["version"], 2)
        self.assertEqual(envelope["payloadFormat"], BACKUP_FORMAT)
        self.assertEqual(self.encrypted_export_password_input.property("text"), "")
        self.assertEqual(self.encrypted_export_confirmation_input.property("text"), "")
        self.assertIn("密码保护 Native 备份已保存", str(self.window.property("backupNotice")))
        self._show_encrypted_password_prompt(target)
        self.encrypted_restore_password_input.setProperty("text", password)
        self._click(self.encrypted_restore_continue)
        self.assertTrue(self.preview_dialog.property("visible"))
        summary = str(self.preview_summary.property("text"))
        self.assertIn("Native 密码保护完整备份", summary)
        self.assertIn("完整本机数据库", summary)
        self.assertNotIn("旧记录 0", summary)
        self._click(self.cancel_button)

    def test_twentieth_money_record_reminds_until_full_backup_is_exported(self) -> None:
        today = date.today().isoformat()
        existing_records = [
            {
                "id": f"synthetic-before-reminder-{index:02d}",
                "type": "money",
                "date": today,
                "createdAt": index,
                "sample": False,
                "data": {
                    "amount": 1,
                    "flow": "income",
                    "category": "工资",
                    "note": "synthetic pre-existing ledger entry",
                },
            }
            for index in range(1, 20)
        ]
        self._replace_database_with_package(_migration_package(
            records=existing_records,
            settings={
                "budget": 100000,
                "recordsSinceExport": 19,
                "moneySinceExport": 19,
            },
        ))
        self.window.setProperty("currentSectionIndex", 1)
        QTest.qWait(80)

        finance_page = self.window.findChild(QObject, "financePage")
        self.assertIsNotNone(finance_page, "production FinancePage was not created")
        alert = self.window.findChild(QObject, "financeAlert")
        self.assertIsNotNone(alert, "production backup reminder label was not found")
        self.assertEqual(len(self.finance.activity_records()), 19)
        self.assertEqual(self.finance.state["summary"]["recordsSinceExport"], 19)
        self.assertEqual(self.finance.state["summary"]["moneySinceExport"], 19)
        self.assertFalse(alert.property("visible"), "19 entries must not trigger the reminder")

        amount_input = self.window.findChild(QObject, "financeAmountInput")
        category_box = self.window.findChild(QObject, "financeCategoryBox")
        date_input = self.window.findChild(QObject, "financeDateInput")
        note_input = self.window.findChild(QObject, "financeNoteInput")
        save_button = self.window.findChild(QObject, "financeSaveButton")
        for label, control in (
            ("amount input", amount_input),
            ("category selector", category_box),
            ("date input", date_input),
            ("note input", note_input),
            ("save button", save_button),
        ):
            self.assertIsNotNone(control, f"production {label} was not found")

        amount_input.setProperty("text", "1")
        category_box.setProperty("currentIndex", 0)
        date_input.setProperty("text", today)
        note_input.setProperty("text", "synthetic twentieth ledger entry")
        self._click(save_button)

        reminder = "已新增 20 笔账目，建议导出完整备份。"
        self.assertEqual(len(self.finance.activity_records()), 20)
        self.assertEqual(self.finance.state["summary"]["recordsSinceExport"], 20)
        self.assertEqual(self.finance.state["summary"]["moneySinceExport"], 20)
        self.assertEqual(self.finance.state["summary"]["alertReason"], "backup_reminder")
        self.assertTrue(alert.property("visible"))
        self.assertEqual(alert.property("text"), reminder)

        # The reminder is derived from SQLite counters and must survive a fresh
        # production bridge/QML graph, as it does after an application restart.
        self._destroy_engine()
        self._assert_database_can_be_released_and_reopened()
        self._build_engine()
        self.window.setProperty("currentSectionIndex", 1)
        QTest.qWait(80)
        finance_page = self.window.findChild(QObject, "financePage")
        alert = self.window.findChild(QObject, "financeAlert")
        self.assertIsNotNone(finance_page)
        self.assertIsNotNone(alert)
        self.assertEqual(self.finance.state["summary"]["recordsSinceExport"], 20)
        self.assertEqual(self.finance.state["summary"]["moneySinceExport"], 20)
        self.assertTrue(alert.property("visible"))
        self.assertEqual(alert.property("text"), reminder)

        excel_target = self.temp_path / "synthetic-ledger.xlsx"
        excel_result = self.finance.exportExcel(QUrl.fromLocalFile(str(excel_target)))
        self.assertTrue(excel_result["ok"], excel_result)
        self.assertTrue(excel_target.is_file())
        QTest.qWait(60)
        self.assertEqual(self.finance.state["summary"]["recordsSinceExport"], 20)
        self.assertEqual(self.finance.state["summary"]["moneySinceExport"], 20)
        self.assertTrue(alert.property("visible"), "Excel export must not clear backup counters")
        self.assertEqual(alert.property("text"), reminder)

        backup_target = self.temp_path / "twentieth-entry-backup.wxbak"
        invoked = QMetaObject.invokeMethod(
            self.window,
            "exportFullBackup",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", QUrl.fromLocalFile(str(backup_target))),
        )
        self.assertTrue(invoked, "the production QML full-backup handler was not invokable")
        QTest.qWait(80)
        self.assertTrue(backup_target.is_file())
        self.assertEqual(self.finance.state["summary"]["recordsSinceExport"], 0)
        self.assertEqual(self.finance.state["summary"]["moneySinceExport"], 0)
        self.assertFalse(alert.property("visible"))

        self._destroy_engine()
        self._assert_database_can_be_released_and_reopened()
        self._build_engine()
        self.window.setProperty("currentSectionIndex", 1)
        QTest.qWait(80)
        finance_page = self.window.findChild(QObject, "financePage")
        alert = self.window.findChild(QObject, "financeAlert")
        self.assertIsNotNone(finance_page)
        self.assertIsNotNone(alert)
        self.assertEqual(self.finance.state["summary"]["recordsSinceExport"], 0)
        self.assertEqual(self.finance.state["summary"]["moneySinceExport"], 0)
        self.assertFalse(alert.property("visible"), "a successful full backup must clear the reminder")

    def test_native_backup_restore_survives_engine_recreation(self) -> None:
        target = self.temp_path / "production-roundtrip.wxbak"
        exported_source = load_imported_data(self.database_path)
        self.assertEqual(exported_source["entities"]["records"][0]["id"], "current-before-restore")

        invoked = QMetaObject.invokeMethod(
            self.window,
            "exportFullBackup",
            Qt.ConnectionType.DirectConnection,
            Q_ARG("QVariant", QUrl.fromLocalFile(str(target))),
        )
        self.assertTrue(invoked, "the production QML backup export handler was not invokable")
        QTest.qWait(60)
        self.assertTrue(target.is_file(), "the production QML handler did not create a .wxbak")
        self.assertGreater(target.stat().st_size, 0)
        self.assertIn("完整备份已保存", str(self.window.property("backupNotice")))

        with zipfile.ZipFile(target, "r") as package:
            self.assertEqual(set(package.namelist()), {MANIFEST_MEMBER, DATABASE_MEMBER})
            manifest = json.loads(package.read(MANIFEST_MEMBER))
            exported_sqlite = package.read(DATABASE_MEMBER)
        exported_digest = hashlib.sha256(exported_sqlite).hexdigest()
        self.assertEqual(manifest["format"], BACKUP_FORMAT)
        self.assertEqual(manifest["databaseBytes"], len(exported_sqlite))
        self.assertEqual(manifest["sha256"], exported_digest)
        exported_database = self.temp_path / "exported-snapshot.sqlite3"
        exported_database.write_bytes(exported_sqlite)
        exported_state = load_imported_data(exported_database)
        self.assertEqual(
            exported_state["entities"]["records"][0]["id"],
            "current-before-restore",
        )

        # Make the target differ from the exported snapshot, using the production bridge.
        changed = self.finance.addRecord(
            "expense", "99", "吃饭", date.today().isoformat(), "synthetic-after-export"
        )
        self.assertTrue(changed["ok"], changed)
        self.assertTrue(
            any(
                (row.get("data") or {}).get("note") == "synthetic-after-export"
                for row in self.finance.activity_records()
            )
        )
        database_after_change = self.database_path.read_bytes()
        self.assertNotEqual(
            hashlib.sha256(database_after_change).hexdigest(),
            exported_digest,
            "the restore target must differ from the exported snapshot before preview",
        )

        # The production preview and Cancel button must leave the changed target byte-for-byte intact.
        self._show_preview_from_selected_file(target)
        report = self.window.property("backupReport")
        self.assertEqual(report["sourceFormat"], BACKUP_FORMAT)
        self.assertEqual(report["sha256"], exported_digest)
        self._click(self.cancel_button)
        self.assertFalse(self.preview_dialog.property("visible"))
        self.assertFalse(self.backup.applyPreview()["ok"], "cancel must clear the pending restore")
        self.assertEqual(self.database_path.read_bytes(), database_after_change)
        self.assertTrue(
            any(
                (row.get("data") or {}).get("note") == "synthetic-after-export"
                for row in self.finance.activity_records()
            )
        )

        # Confirm through production QML; this replaces SQLite but does not run the app's QProcess restart.
        self._show_preview_from_selected_file(target)
        self._click(self.confirm_button)
        self.assertFalse(self.preview_dialog.property("visible"))
        self.assertTrue(self.backup.restart_requested)
        restored = load_imported_data(self.database_path)
        self.assertEqual(restored["entities"]["records"][0]["id"], "current-before-restore")
        self.assertEqual(self.database_path.read_bytes(), exported_sqlite)
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

        # Release every reference held by the old engine and bridges, then make
        # sure Windows can move the database before creating a fresh startup graph.
        old_finance = weakref.ref(self.finance)
        self._destroy_engine()
        gc.collect()
        self.assertIsNone(old_finance(), "the old production bridge graph should be released")
        self._assert_database_can_be_released_and_reopened()

        self._build_engine()
        self.assertEqual(
            self.migration.data["entities"]["records"][0]["id"],
            "current-before-restore",
        )
        finance_records = self.finance.state["records"]
        self.assertTrue(
            any(row.get("id") == "current-before-restore" for row in finance_records)
        )
        self.assertFalse(
            any((row.get("data") or {}).get("note") == "synthetic-after-export"
                for row in finance_records)
        )

        self.window.setProperty("currentSectionIndex", 1)
        QTest.qWait(50)
        finance_page = self.window.findChild(QObject, "financePage")
        self.assertIsNotNone(finance_page, "fresh production Main.qml did not create FinancePage")
        qml_snapshot = finance_page.property("snapshot")
        self.assertTrue(
            any(row.get("id") == "current-before-restore" for row in qml_snapshot["records"]),
            "fresh production QML did not read the restored finance state",
        )


if __name__ == "__main__":
    unittest.main()
