from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage

from wanxiang.brand import (
    BRAND_DEFAULT,
    BRAND_SETTING_KEY,
    BrandBridge,
    BrandRepository,
    BrandRepositoryError,
    inspect_avatar_source,
    prepare_avatar_image,
)
from wanxiang.database import get_app_setting, import_package, load_imported_data, set_app_setting
from wanxiang.migration import (
    PACKAGE_FORMAT,
    PACKAGE_SCHEMA_VERSION,
    STORAGE_KEYS,
    calculate_checksum,
    validate_package,
)


def _package(brand: dict[str, object] | None = None, marker: str = "old"):
    state: dict[str, object] = {"records": [], "settings": {}}
    if brand is not None:
        state["settings"] = {"brand": brand}
    raw_values: dict[str, str | None] = {key: None for key in STORAGE_KEYS}
    raw_values["richangji-state-v1"] = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    return validate_package({
        "format": PACKAGE_FORMAT,
        "schemaVersion": PACKAGE_SCHEMA_VERSION,
        "sourceVersion": f"synthetic-brand-{marker}",
        "exportedAt": "2026-09-27T10:00:00Z",
        "keys": raw_values,
        "checksum": calculate_checksum(raw_values),
    })


def _png_bytes(width: int = 48, height: int = 24) -> bytes:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


class BrandRepositoryTests(unittest.TestCase):
    def test_defaults_use_existing_settings_helper_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brand.sqlite3"
            repository = BrandRepository(path)
            self.assertEqual(BRAND_DEFAULT["name"], "FLUKE")
            self.assertEqual(BRAND_DEFAULT["avatar"], "F")
            self.assertEqual(repository.brand()["name"], BRAND_DEFAULT["name"])
            self.assertEqual(repository.brand()["theme"], "plum")
            self.assertIsNone(get_app_setting(path, BRAND_SETTING_KEY))

            saved = repository.save({
                "name": "合成工作台",
                "tagline": "只用于自动测试",
                "theme": "forest",
                "avatarImage": "",
            })
            reopened = BrandRepository(path)
            self.assertEqual(reopened.brand(), saved)
            self.assertEqual(get_app_setting(path, BRAND_SETTING_KEY)["settingsOverrides"]["theme"], "forest")

    def test_legacy_default_brand_is_renamed_without_mutating_imported_data(self) -> None:
        old_brand = {
            "name": "万象来信",
            "avatar": "万",
            "tagline": "把远方与日常，折进今天",
            "theme": "plum",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-default-brand.sqlite3"
            import_package(_package(old_brand), path)

            repository = BrandRepository(path)
            self.assertEqual(repository.brand()["name"], "FLUKE")
            self.assertEqual(repository.brand()["avatar"], "F")
            self.assertEqual(BrandRepository(path).brand()["name"], "FLUKE")

            imported = load_imported_data(path)
            raw_state = json.loads(imported["raw_values"]["richangji-state-v1"])
            self.assertEqual(raw_state["settings"]["brand"], old_brand)

    def test_later_legacy_import_renames_only_the_local_default_projection(self) -> None:
        old_brand = {
            "name": "万象来信",
            "avatar": "万",
            "tagline": "把远方与日常，折进今天",
            "theme": "plum",
        }
        package = _package(old_brand, "later-default")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "later-import.sqlite3"
            repository = BrandRepository(path)
            import_package(package, path)
            result = repository.adopt_imported_data({
                "documents": {"richangji-state-v1": package.parsed_values["richangji-state-v1"]}
            })
            self.assertEqual(result["name"], "FLUKE")
            imported = load_imported_data(path)
            raw_state = json.loads(imported["raw_values"]["richangji-state-v1"])
            self.assertEqual(raw_state["settings"]["brand"], old_brand)

    def test_legacy_default_name_migration_preserves_other_custom_appearance(self) -> None:
        old_brand = {
            "name": "万象来信",
            "avatar": "万",
            "tagline": "我的工作台副标题",
            "theme": "forest",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "custom-appearance.sqlite3"
            import_package(_package(old_brand), path)

            brand = BrandRepository(path).brand()

            self.assertEqual(brand["name"], "FLUKE")
            self.assertEqual(brand["avatar"], "F")
            self.assertEqual(brand["tagline"], old_brand["tagline"])
            self.assertEqual(brand["theme"], "forest")

    def test_preexisting_explicit_legacy_name_override_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "explicit-legacy-override.sqlite3"
            set_app_setting(path, BRAND_SETTING_KEY, {
                "version": 1,
                "legacyBrand": {"name": "万象来信", "theme": "plum"},
                "settingsOverrides": {"name": "万象来信", "tagline": "自定义工作台"},
            })

            brand = BrandRepository(path).brand()

            self.assertEqual(brand["name"], "万象来信")
            self.assertEqual(brand["tagline"], "自定义工作台")

    def test_explicitly_saved_legacy_name_is_not_rewritten_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "explicit-name.sqlite3"
            repository = BrandRepository(path, {"settings": {"brand": {}}})
            saved = repository.save({
                "name": "万象来信",
                "tagline": "用户自定义名称",
                "theme": "plum",
            })
            reopened = BrandRepository(path)
            self.assertEqual(saved["name"], "万象来信")
            self.assertEqual(reopened.brand()["name"], "万象来信")

    def test_migrated_fields_and_unknown_values_survive_save_and_reset(self) -> None:
        old_brand = {
            "name": "旧品牌",
            "avatar": "旧",
            "tagline": "旧副标题",
            "theme": "navy",
            "avatarImage": "",
            "futureBadge": {"kind": "synthetic", "visible": True},
            "subtitle": "保留的未来字段",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            package = _package(old_brand)
            import_package(package, path)
            repository = BrandRepository(path)
            updated = repository.save({
                "name": "新名字",
                "tagline": "新的副标题",
                "theme": "clay",
                "avatarImage": "",
            })
            self.assertEqual(updated["name"], "新名字")
            self.assertEqual(updated["theme"], "clay")
            self.assertEqual(updated["futureBadge"], old_brand["futureBadge"])
            self.assertEqual(updated["subtitle"], old_brand["subtitle"])

            restored = BrandRepository(path).reset_defaults()
            self.assertEqual(restored["name"], BRAND_DEFAULT["name"])
            self.assertEqual(restored["theme"], "plum")
            self.assertEqual(restored["avatarImage"], "")
            self.assertEqual(restored["futureBadge"], old_brand["futureBadge"])
            self.assertEqual(restored["subtitle"], old_brand["subtitle"])

            imported = load_imported_data(path)
            raw_state = json.loads(imported["raw_values"]["richangji-state-v1"])
            self.assertEqual(raw_state["settings"]["brand"], old_brand)

    def test_later_import_rebases_base_without_replacing_local_edits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rebase.sqlite3"
            first = _package({"name": "旧名", "theme": "forest", "future": "keep-me"}, "first")
            import_package(first, path)
            repository = BrandRepository(path)
            repository.save({"name": "本机名称", "tagline": "本机副题", "theme": "clay"})

            later = _package({"name": "新版默认名", "tagline": "新版副题", "theme": "navy", "newFuture": 7}, "later")
            repository.adopt_imported_data({"documents": {"richangji-state-v1": later.parsed_values["richangji-state-v1"]}})
            reopened = BrandRepository(path, {"documents": {"richangji-state-v1": later.parsed_values["richangji-state-v1"]}})
            self.assertEqual(reopened.brand()["name"], "本机名称")
            self.assertEqual(reopened.brand()["theme"], "clay")
            self.assertEqual(reopened.brand()["future"], "keep-me")
            self.assertEqual(reopened.brand()["newFuture"], 7)

    def test_old_length_limits_utf16_count_and_theme_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = BrandRepository(Path(directory) / "limits.sqlite3")
            repository.save({"name": "名" * 12, "tagline": "副" * 20, "theme": "navy"})
            with self.assertRaisesRegex(BrandRepositoryError, "12"):
                repository.save({"name": "名" * 13, "tagline": "副", "theme": "plum"})
            with self.assertRaisesRegex(BrandRepositoryError, "12"):
                repository.save({"name": "😀" * 7, "tagline": "副", "theme": "plum"})
            with self.assertRaisesRegex(BrandRepositoryError, "20"):
                repository.save({"name": "名称", "tagline": "副" * 21, "theme": "plum"})
            with self.assertRaisesRegex(BrandRepositoryError, "主题"):
                repository.save({"name": "名称", "tagline": "副", "theme": "unknown"})

    def test_avatar_crop_format_size_and_square_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.png"
            path.write_bytes(_png_bytes())
            inspection = inspect_avatar_source(path.as_uri())
            self.assertTrue(inspection["ok"], inspection["error"])
            self.assertEqual(inspection["format"], "png")

            prepared = prepare_avatar_image(path.as_uri(), 0.5, 0.5, 2.0)
            self.assertTrue(prepared["ok"], prepared["error"])
            self.assertTrue(prepared["dataUrl"].startswith("data:image/png;base64,"))
            decoded = base64.b64decode(prepared["dataUrl"].split(",", 1)[1])
            output = QImage.fromData(decoded)
            self.assertEqual((output.width(), output.height()), (256, 256))

            appearance_path = Path(directory) / "appearance.sqlite3"
            appearance = BrandRepository(appearance_path)
            appearance.save({
                "name": "合成头像",
                "tagline": "图片保存检查",
                "theme": "plum",
                "avatarImage": prepared["dataUrl"],
            })
            self.assertEqual(BrandRepository(appearance_path).brand()["avatarImage"], prepared["dataUrl"])

            for extension, writer_format in (("jpg", "JPEG"), ("webp", "WEBP")):
                encoded_path = Path(directory) / f"synthetic.{extension}"
                image = QImage(32, 20, QImage.Format.Format_RGB32)
                image.fill(Qt.GlobalColor.green)
                self.assertTrue(image.save(str(encoded_path), writer_format))
                accepted = inspect_avatar_source(encoded_path.as_uri())
                self.assertTrue(accepted["ok"], accepted["error"])
            gif_path = Path(directory) / "synthetic.gif"
            gif_path.write_bytes(base64.b64decode(
                "R0lGODlhAQABAIAAAP8AAAAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="
            ))
            gif_result = inspect_avatar_source(gif_path.as_uri())
            self.assertTrue(gif_result["ok"], gif_result["error"])

            oversized = Path(directory) / "too-large.png"
            oversized.write_bytes(_png_bytes() + b"\0" * 12_000_001)
            rejected = inspect_avatar_source(oversized.as_uri())
            self.assertFalse(rejected["ok"])
            self.assertIn("12MB", rejected["error"])

            at_limit = Path(directory) / "at-limit.png"
            png = _png_bytes()
            at_limit.write_bytes(png + b"\0" * (12_000_000 - len(png)))
            boundary = inspect_avatar_source(at_limit.as_uri())
            self.assertTrue(boundary["ok"], boundary["error"])
            self.assertEqual(boundary["bytes"], 12_000_000)

            bmp = Path(directory) / "not-allowed.bmp"
            image = QImage(4, 4, QImage.Format.Format_RGB32)
            image.fill(Qt.GlobalColor.blue)
            self.assertTrue(image.save(str(bmp), "BMP"))
            unsupported = inspect_avatar_source(bmp.as_uri())
            self.assertFalse(unsupported["ok"])
            self.assertIn("PNG、JPG、WebP 或 GIF", unsupported["error"])

    def test_avatar_text_uses_first_grapheme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = BrandRepository(Path(directory) / "letters.sqlite3")
            bridge = BrandBridge(repository)
            self.assertEqual(bridge.firstLetter("万象"), "万")
            self.assertEqual(bridge.firstLetter(" 👩‍💻工作台"), "👩‍💻")

    def test_bridge_returns_readable_validation_and_saved_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = BrandRepository(Path(directory) / "bridge.sqlite3")
            bridge = BrandBridge(repository)
            before = bridge.brand
            failure = bridge.saveBrand({"name": "名" * 13, "tagline": "短", "theme": "plum"})
            self.assertFalse(failure["ok"])
            self.assertEqual(bridge.brand, before)
            success = bridge.saveBrand({"name": "桥接测试", "tagline": "只用于合成", "theme": "forest"})
            self.assertTrue(success["ok"])
            self.assertEqual(bridge.brand["name"], "桥接测试")
            self.assertEqual(bridge.resetBrand()["brand"]["theme"], "plum")


if __name__ == "__main__":
    unittest.main()
