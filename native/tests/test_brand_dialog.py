from __future__ import annotations

import base64
import os
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QObject, QMetaObject, Qt, QUrl, Slot
from PySide6.QtGui import QAccessible, QGuiApplication, QImage
from PySide6.QtQml import QJSValue, QQmlApplicationEngine, QQmlComponent
from PySide6.QtTest import QTest

from wanxiang.brand import BRAND_DEFAULT, BrandBridge, BrandRepository


class _PreviewCapture(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.values: list[dict[str, object]] = []

    @Slot("QVariant")
    def capture(self, value: object) -> None:
        if isinstance(value, QJSValue):
            value = value.toVariant()
        self.values.append(dict(value))


class BrandAppearanceDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.qml_directory = Path(__file__).resolve().parents[1] / "qml"

    def _load_dialog(self, starting_brand: dict[str, object] | None = None):
        temporary = tempfile.TemporaryDirectory()
        repository = BrandRepository(
            Path(temporary.name) / "appearance.sqlite3",
            {"settings": {"brand": starting_brand or {}}},
        )
        bridge = BrandBridge(repository)
        preview_capture = _PreviewCapture()
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("brandStoreRef", bridge)
        engine.rootContext().setContextProperty("previewCapture", preview_capture)
        qml_url = QUrl.fromLocalFile(str(self.qml_directory).replace("\\", "/") + "/")
        wrapper_url = QUrl.fromLocalFile(str(self.qml_directory / "BrandAppearanceDialogTest.qml"))
        wrapper = (
            "import QtQuick\n"
            "import QtQuick.Controls\n"
            f'import "{qml_url.toString()}" as Native\n'
            "ApplicationWindow {\n"
            "  visible: true; width: 640; height: 800\n"
            "  Native.BrandAppearanceDialog {\n"
            "    objectName: \"testBrandDialog\"\n"
            "    brandStore: brandStoreRef\n"
            "    onPreviewChanged: previewCapture.capture(brand)\n"
            "    Component.onCompleted: open()\n"
            "  }\n"
            "}\n"
        )
        component = QQmlComponent(engine)
        component.setData(wrapper.encode("utf-8"), wrapper_url)
        if component.isError():
            errors = "\n".join(error.toString() for error in component.errors())
            engine.deleteLater()
            temporary.cleanup()
            self.fail(errors)
        window = component.create()
        if window is None:
            errors = "\n".join(error.toString() for error in component.errors())
            engine.deleteLater()
            temporary.cleanup()
            self.fail(errors)
        dialog = window.findChild(QObject, "testBrandDialog")
        if dialog is None:
            engine.deleteLater()
            temporary.cleanup()
            self.fail("BrandAppearanceDialog did not load in the test window")
        QTest.qWait(80)
        self.addCleanup(temporary.cleanup)
        self.addCleanup(engine.deleteLater)
        self.addCleanup(component.deleteLater)
        return window, dialog, repository, bridge, preview_capture, component

    def _invoke(self, target, name: str) -> None:
        self.assertTrue(
            QMetaObject.invokeMethod(target, name, Qt.ConnectionType.DirectConnection),
            f"QML method {name} was not invokable",
        )
        QTest.qWait(20)

    def test_preview_cancel_restores_saved_values_without_writing(self) -> None:
        window, dialog, repository, _bridge, preview_capture, _component = self._load_dialog({
            "name": "已保存",
            "tagline": "保存的副题",
            "theme": "forest",
        })
        original = repository.brand()
        dialog.setProperty("draftName", "未保存名称")
        dialog.setProperty("draftTagline", "未保存副题")
        dialog.setProperty("draftTheme", "clay")
        self._invoke(dialog, "publishPreview")
        self.assertEqual(preview_capture.values[-1]["name"], "未保存名称")
        self.assertEqual(preview_capture.values[-1]["theme"], "clay")

        self._invoke(dialog, "cancelDraft")
        self.assertEqual(repository.brand(), original)
        self.assertEqual(preview_capture.values[-1]["name"], "已保存")
        self.assertEqual(preview_capture.values[-1]["theme"], "forest")
        self.assertFalse(dialog.property("opened"))

    def test_reset_default_stays_draft_until_save(self) -> None:
        _window, dialog, repository, _bridge, _capture, _component = self._load_dialog({"name": "旧名", "theme": "navy"})
        dialog.setProperty("draftName", "保存名称")
        dialog.setProperty("draftTagline", "保存的副标题")
        dialog.setProperty("draftTheme", "clay")
        self._invoke(dialog, "finishSave")
        self.assertEqual(
            str(dialog.property("formError")).encode("unicode_escape"),
            b"",
        )
        actual = repository.brand()["name"]
        self.assertEqual(actual, "保存名称", f"stored={actual.encode('unicode_escape')!r}")
        self.assertEqual(repository.brand()["theme"], "clay")
        self.assertFalse(dialog.property("opened"))

        self._invoke(dialog, "open")
        self.assertEqual(dialog.property("draftName"), "保存名称")
        self.assertEqual(dialog.property("draftTagline"), "保存的副标题")
        self.assertEqual(dialog.property("draftTheme"), "clay")
        dialog.setProperty("draftName", "未提交")
        self._invoke(dialog, "resetAppearance")
        self.assertEqual(repository.brand()["name"], "保存名称")
        self.assertEqual(repository.brand()["theme"], "clay")
        self.assertTrue(dialog.property("opened"))
        self.assertEqual(dialog.property("draftName"), BRAND_DEFAULT["name"])
        self._invoke(dialog, "cancelDraft")
        self.assertEqual(repository.brand()["name"], "保存名称")
        self.assertEqual(repository.brand()["theme"], "clay")

        self._invoke(dialog, "open")
        self._invoke(dialog, "resetAppearance")
        self._invoke(dialog, "finishSave")
        self.assertEqual(repository.brand()["name"], BRAND_DEFAULT["name"])
        self.assertEqual(repository.brand()["theme"], "plum")

    def test_qml_exposes_old_input_limits_and_four_theme_options(self) -> None:
        window, dialog, _repository, _bridge, _capture, _component = self._load_dialog()
        name_input = window.findChild(QObject, "brandNameInput")
        tagline_input = window.findChild(QObject, "brandTaglineInput")
        self.assertIsNotNone(name_input)
        self.assertIsNotNone(tagline_input)
        self.assertEqual(name_input.property("maximumLength"), 12)
        self.assertEqual(tagline_input.property("maximumLength"), 20)
        name_accessible = QAccessible.queryAccessibleInterface(name_input)
        tagline_accessible = QAccessible.queryAccessibleInterface(tagline_input)
        self.assertEqual(name_accessible.text(QAccessible.Text.Name), "页面名称")
        self.assertEqual(tagline_accessible.text(QAccessible.Text.Name), "副标题")
        language_hint = window.findChild(QObject, "uiLanguageCommitHint")
        self.assertIsNotNone(language_hint)
        self.assertIn("立即保存", str(language_hint.property("text")))
        choices = dialog.property("themeChoices")
        if isinstance(choices, QJSValue):
            choices = choices.toVariant()
        self.assertEqual([item["key"] for item in choices], ["plum", "forest", "clay", "navy"])

    def test_selected_image_is_previewed_cropped_and_saved_as_square(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "synthetic-avatar.png"
            source_image = QImage(80, 40, QImage.Format.Format_RGB32)
            source_image.fill(Qt.GlobalColor.magenta)
            self.assertTrue(source_image.save(str(image_path), "PNG"))

            _window, dialog, repository, _bridge, _capture, _component = self._load_dialog()
            dialog.setProperty("selectedAvatarUrl", image_path.as_uri())
            dialog.setProperty("avatarMode", "image")
            dialog.setProperty("cropChanged", True)
            QTest.qWait(100)
            crop_image = dialog.findChild(QObject, "brandAvatarCropImage")
            crop_frame = dialog.findChild(QObject, "brandAvatarCropFrame")
            self.assertIsNotNone(crop_image)
            self.assertIsNotNone(crop_frame)
            self.assertGreater(crop_image.property("implicitWidth"), 0)
            self.assertGreater(crop_image.property("width"), crop_frame.property("width"))

            self._invoke(dialog, "finishSave")
            saved = repository.brand()["avatarImage"]
            self.assertTrue(saved.startswith("data:image/png;base64,"))
            cropped = QImage.fromData(base64.b64decode(saved.split(",", 1)[1]))
            self.assertEqual((cropped.width(), cropped.height()), (256, 256))


if __name__ == "__main__":
    unittest.main()
