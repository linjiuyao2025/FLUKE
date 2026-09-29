"""Brand appearance settings backed by the existing SQLite settings helper.

The old app stores this object in ``settings.brand`` within
``richangji-state-v1``.  The imported source remains immutable; this module
keeps a legacy base and explicit local overrides in one app_settings key.
"""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata
from typing import Any
from urllib.parse import unquote, urlsplit

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, Property, Qt, Signal, Slot
from PySide6.QtGui import QImage, QImageReader, QImageWriter
from PySide6.QtQml import QJSValue

from .database import get_app_setting, load_imported_data, set_app_setting
from .json_utils import copy_json
from .migration import MigrationPackage


BRAND_SETTING_KEY = "brandAppearance"
LEGACY_BRAND_DEFAULT_NAME = "万象来信"
BRAND_DEFAULT: dict[str, Any] = {
    "name": "FLUKE",
    "avatar": "F",
    "tagline": "把远方与日常，折进今天",
    "theme": "plum",
}
BRAND_THEMES = ("plum", "forest", "clay", "navy")
MAX_BRAND_NAME_LENGTH = 12
MAX_BRAND_TAGLINE_LENGTH = 20
MAX_AVATAR_SOURCE_BYTES = 12_000_000
AVATAR_OUTPUT_SIZE = 256
_BRAND_FIELDS = frozenset((*BRAND_DEFAULT, "avatarImage"))
_MISSING = object()
_DATA_IMAGE = re.compile(
    r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$", re.IGNORECASE
)
_ALLOWED_IMAGE_FORMATS = frozenset({"png", "jpeg", "jpg", "webp", "gif"})


class BrandRepositoryError(ValueError):
    """Readable input or persistence error for brand appearance."""


def _json_copy(value: Any, label: str) -> Any:
    return copy_json(
        value,
        label,
        BrandRepositoryError,
        compact=True,
        error_suffix=" 不是有效的 JSON 数据。",
    )


def _strict_json_loads(raw: str, label: str) -> Any:
    def reject_constant(value: str) -> None:
        raise BrandRepositoryError(f"{label} 含有无效数值。")

    try:
        return json.loads(raw, parse_constant=reject_constant)
    except (TypeError, json.JSONDecodeError, BrandRepositoryError) as exc:
        raise BrandRepositoryError(f"{label} 无法读取。") from exc


def _legacy_state(source: Any) -> tuple[dict[str, Any], bool]:
    """Return the legacy brand object and whether the main state was present."""
    state: Any = None
    present = False
    if isinstance(source, MigrationPackage):
        state = source.parsed_values.get("richangji-state-v1")
        present = state is not None
    elif isinstance(source, dict):
        for container_name in ("parsed_values", "documents"):
            container = source.get(container_name)
            if isinstance(container, dict) and "richangji-state-v1" in container:
                state = container["richangji-state-v1"]
                present = state is not None
                break
        if not present:
            raw_values = source.get("raw_values")
            if isinstance(raw_values, dict) and raw_values.get("richangji-state-v1") is not None:
                state = _strict_json_loads(raw_values["richangji-state-v1"], "旧版主状态")
                present = True
        if not present and "richangji-state-v1" in source:
            value = source["richangji-state-v1"]
            state = _strict_json_loads(value, "旧版主状态") if isinstance(value, str) else value
            present = state is not None
        if not present and ("settings" in source or "records" in source):
            state = source
            present = True

    if not present:
        return {}, False
    if not isinstance(state, dict):
        raise BrandRepositoryError("旧版主状态必须是对象。")
    settings = state.get("settings", {})
    if settings is None:
        settings = {}
    if not isinstance(settings, dict):
        raise BrandRepositoryError("旧版 settings 必须是对象。")
    brand = settings.get("brand", {})
    if brand is None:
        brand = {}
    if not isinstance(brand, dict):
        raise BrandRepositoryError("旧版 settings.brand 必须是对象。")
    return _json_copy(brand, "旧版品牌外观"), True


def _normalize_runtime(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BrandRepositoryError("本机品牌外观状态必须是对象。")
    if value.get("version", 1) != 1:
        raise BrandRepositoryError("本机品牌外观状态版本不受支持。")
    legacy = value.get("legacyBrand", {})
    overrides = value.get("settingsOverrides", {})
    if not isinstance(legacy, dict) or not isinstance(overrides, dict):
        raise BrandRepositoryError("本机品牌外观状态结构无效。")
    return {
        **value,
        "version": 1,
        "legacyBrand": _json_copy(legacy, "旧版品牌外观"),
        "settingsOverrides": _json_copy(overrides, "本机品牌设置覆盖"),
    }


def _migrate_legacy_default_name(runtime: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Rename an imported built-in name unless a local name was explicitly saved."""
    if runtime.get("brandNameMigrationVersion") == 1:
        return runtime, False
    overrides = runtime["settingsOverrides"]
    legacy = runtime["legacyBrand"]
    if "name" in overrides or legacy.get("name") != LEGACY_BRAND_DEFAULT_NAME:
        return runtime, False
    updated_overrides = deepcopy(overrides)
    updated_overrides["name"] = BRAND_DEFAULT["name"]
    return {
        **runtime,
        "settingsOverrides": updated_overrides,
        "brandNameMigrationVersion": 1,
    }, True


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _first_grapheme(value: str) -> str:
    """Small dependency-free equivalent for the name's first visible glyph."""
    if not value:
        return BRAND_DEFAULT["avatar"]
    result = value[0]
    regional_count = 1 if 0x1F1E6 <= ord(value[0]) <= 0x1F1FF else 0
    join_next = False
    for character in value[1:]:
        codepoint = ord(character)
        combining = unicodedata.combining(character) != 0
        extender = combining or codepoint in (0xFE0E, 0xFE0F) or 0x1F3FB <= codepoint <= 0x1F3FF
        regional = 0x1F1E6 <= codepoint <= 0x1F1FF
        if extender or join_next or character == "\u200d" or (regional and regional_count == 1):
            result += character
            if regional:
                regional_count += 1
            join_next = character == "\u200d"
        else:
            break
    return result


def _safe_saved_avatar(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    match = _DATA_IMAGE.fullmatch(value)
    if not match:
        return ""
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        return ""
    return value if len(decoded) <= MAX_AVATAR_SOURCE_BYTES else ""


def _local_path(source: str) -> Path:
    parsed = urlsplit(source)
    if parsed.scheme == "file":
        if parsed.netloc not in ("", "localhost"):
            raise BrandRepositoryError("请选择本机上的头像图片。")
        raw_path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", raw_path):
            raw_path = raw_path[1:]
        return Path(raw_path)
    if parsed.scheme:
        raise BrandRepositoryError("请选择本机上的头像图片。")
    return Path(source)


def _read_avatar_image(source: str) -> tuple[QImage, int, str]:
    if not isinstance(source, str) or not source.strip():
        raise BrandRepositoryError("请选择一张头像图片。")
    match = _DATA_IMAGE.fullmatch(source)
    if match:
        mime = match.group(1).lower()
        try:
            payload = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise BrandRepositoryError("头像图片数据无法读取。") from exc
        if len(payload) > MAX_AVATAR_SOURCE_BYTES:
            raise BrandRepositoryError("头像图片请控制在 12MB 以内。")
        payload_array = QByteArray(payload)
        buffer = QBuffer(payload_array)
        if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            raise BrandRepositoryError("头像图片数据无法读取。")
        reader = QImageReader(buffer)
        reader.setDecideFormatFromContent(True)
        image_format = bytes(reader.format()).decode("ascii", errors="ignore").lower()
        image = reader.read()
        buffer.close()
        if mime == "jpeg":
            expected = {"jpeg", "jpg"}
        else:
            expected = {mime}
        if image.isNull() or image_format not in expected:
            raise BrandRepositoryError("头像图片格式或内容不匹配，请重新选择。")
        return image, len(payload), image_format

    path = _local_path(source)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise BrandRepositoryError("头像图片无法读取，请重新选择。") from exc
    if size > MAX_AVATAR_SOURCE_BYTES:
        raise BrandRepositoryError("头像图片请控制在 12MB 以内。")
    reader = QImageReader(str(path))
    reader.setDecideFormatFromContent(True)
    image_format = bytes(reader.format()).decode("ascii", errors="ignore").lower()
    image = reader.read()
    if image.isNull():
        raise BrandRepositoryError("图片无法读取，请换一张图片。")
    if image_format not in _ALLOWED_IMAGE_FORMATS:
        raise BrandRepositoryError("请选择 PNG、JPG、WebP 或 GIF 图片。")
    return image, size, image_format


def inspect_avatar_source(source: str) -> dict[str, Any]:
    try:
        image, size, image_format = _read_avatar_image(source)
        return {
            "ok": True,
            "error": "",
            "bytes": size,
            "format": image_format,
            "width": image.width(),
            "height": image.height(),
        }
    except BrandRepositoryError as exc:
        return {"ok": False, "error": str(exc), "bytes": 0, "format": "", "width": 0, "height": 0}


def prepare_avatar_image(
    source: str,
    center_x: float = 0.5,
    center_y: float = 0.5,
    zoom: float = 1.0,
) -> dict[str, Any]:
    """Read an allowed source, crop it to a square, and return a PNG data URL."""
    try:
        image, size, image_format = _read_avatar_image(source)
        center_x, center_y, zoom = float(center_x), float(center_y), float(zoom)
        if not all(math.isfinite(item) for item in (center_x, center_y, zoom)):
            raise BrandRepositoryError("头像裁切参数无效。")
        if not 0.0 <= center_x <= 1.0 or not 0.0 <= center_y <= 1.0 or not 1.0 <= zoom <= 3.0:
            raise BrandRepositoryError("头像裁切范围无效。")
        source_side = min(image.width(), image.height()) / zoom
        if source_side < 1:
            raise BrandRepositoryError("图片尺寸太小，无法生成头像。")
        left = min(image.width() - source_side, max(0.0, center_x * image.width() - source_side / 2.0))
        top = min(image.height() - source_side, max(0.0, center_y * image.height() - source_side / 2.0))
        crop_size = max(1, int(round(source_side)))
        crop_left = min(max(0, image.width() - crop_size), int(round(left)))
        crop_top = min(max(0, image.height() - crop_size), int(round(top)))
        cropped = image.copy(crop_left, crop_top, crop_size, crop_size).scaled(
            AVATAR_OUTPUT_SIZE,
            AVATAR_OUTPUT_SIZE,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        payload_array = QByteArray()
        output_buffer = QBuffer(payload_array)
        if not output_buffer.open(QIODevice.OpenModeFlag.WriteOnly):
            raise BrandRepositoryError("裁切后的头像无法暂存。")
        writer = QImageWriter(output_buffer, b"PNG")
        if not writer.write(cropped):
            output_buffer.close()
            raise BrandRepositoryError("头像图片转换失败，请换一张图片。")
        output_buffer.close()
        output = bytes(payload_array)
        return {
            "ok": True,
            "error": "",
            "bytes": size,
            "format": image_format,
            "dataUrl": "data:image/png;base64," + base64.b64encode(output).decode("ascii"),
        }
    except (BrandRepositoryError, TypeError, ValueError, OverflowError) as exc:
        error = str(exc) if isinstance(exc, BrandRepositoryError) else "头像裁切参数无效。"
        return {"ok": False, "error": error, "bytes": 0, "format": "", "dataUrl": ""}


class BrandRepository:
    """Persist brand appearance through ``app_settings`` without mutating imports."""

    def __init__(self, database_path: str | Path, legacy_store: Any = None) -> None:
        self.database_path = Path(database_path).expanduser()
        source = legacy_store
        if source is None:
            imported = load_imported_data(self.database_path)
            if imported.get("status") == "unavailable":
                raise BrandRepositoryError(imported.get("error") or "无法读取旧版导入数据。")
            source = imported
        incoming_brand, has_main = _legacy_state(source)
        stored = get_app_setting(self.database_path, BRAND_SETTING_KEY, _MISSING)
        if stored is _MISSING:
            self._runtime = _normalize_runtime({"version": 1, "legacyBrand": incoming_brand, "settingsOverrides": {}})
            self._runtime, migrated_name = _migrate_legacy_default_name(self._runtime)
            if migrated_name:
                self._commit(self._runtime)
        else:
            self._runtime = _normalize_runtime(stored)
            changed = False
            if has_main:
                merged_legacy = {**self._runtime["legacyBrand"], **incoming_brand}
                if merged_legacy != self._runtime["legacyBrand"]:
                    self._runtime["legacyBrand"] = merged_legacy
                    changed = True
            self._runtime, migrated_name = _migrate_legacy_default_name(self._runtime)
            if changed or migrated_name:
                self._commit(self._runtime)
    def _commit(self, runtime: dict[str, Any]) -> None:
        normalized = _normalize_runtime(runtime)
        try:
            set_app_setting(self.database_path, BRAND_SETTING_KEY, normalized)
        except (OSError, TypeError, ValueError, RuntimeError, sqlite3.Error) as exc:
            raise BrandRepositoryError(f"保存外观失败：{exc}") from exc
        self._runtime = normalized

    def brand(self) -> dict[str, Any]:
        """Return the effective settings.brand view, retaining future fields."""
        base = {**BRAND_DEFAULT, **self._runtime["legacyBrand"], **self._runtime["settingsOverrides"]}
        name = base.get("name")
        if not isinstance(name, str) or not name:
            name = BRAND_DEFAULT["name"]
        tagline = base.get("tagline")
        if not isinstance(tagline, str) or not tagline:
            tagline = BRAND_DEFAULT["tagline"]
        theme = base.get("theme")
        if theme not in BRAND_THEMES:
            theme = BRAND_DEFAULT["theme"]
        return {
            **base,
            "name": name,
            "avatar": _first_grapheme(name),
            "avatarImage": _safe_saved_avatar(base.get("avatarImage")),
            "tagline": tagline,
            "theme": theme,
        }

    def save(self, draft: Any) -> dict[str, Any]:
        if not isinstance(draft, dict):
            raise BrandRepositoryError("外观内容必须是对象。")
        raw_name = draft.get("name", "")
        raw_tagline = draft.get("tagline", "")
        theme = draft.get("theme", BRAND_DEFAULT["theme"])
        avatar_image = draft.get("avatarImage", "")
        if not isinstance(raw_name, str) or not isinstance(raw_tagline, str):
            raise BrandRepositoryError("页面名称和副标题必须是文字。")
        name = raw_name.strip() or BRAND_DEFAULT["name"]
        tagline = raw_tagline.strip() or BRAND_DEFAULT["tagline"]
        if _utf16_length(name) > MAX_BRAND_NAME_LENGTH:
            raise BrandRepositoryError("页面名称最多 12 个字符。")
        if _utf16_length(tagline) > MAX_BRAND_TAGLINE_LENGTH:
            raise BrandRepositoryError("副标题最多 20 个字符。")
        if not isinstance(theme, str) or theme not in BRAND_THEMES:
            raise BrandRepositoryError("请选择暮色紫、森林绿、陶土棕或深海蓝主题。")
        if avatar_image:
            safe_image = _safe_saved_avatar(avatar_image)
            if not safe_image:
                raise BrandRepositoryError("头像图片格式或大小无效，请重新选择。")
            # Confirm that the data URL's claimed MIME matches a readable image.
            validation = inspect_avatar_source(safe_image)
            if not validation["ok"]:
                raise BrandRepositoryError(validation["error"])
        else:
            safe_image = ""

        overrides = deepcopy(self._runtime["settingsOverrides"])
        overrides.update({
            "name": name,
            "avatar": _first_grapheme(name),
            "avatarImage": safe_image,
            "tagline": tagline,
            "theme": theme,
        })
        runtime = {
            **self._runtime,
            "settingsOverrides": overrides,
            "brandNameMigrationVersion": 1,
        }
        self._commit(runtime)
        return self.brand()

    def reset_defaults(self) -> dict[str, Any]:
        """Immediately persist the old app's reset behavior, keeping unknown keys."""
        overrides = deepcopy(self._runtime["settingsOverrides"])
        overrides.update({
            **BRAND_DEFAULT,
            "avatarImage": "",
        })
        self._commit({
            **self._runtime,
            "settingsOverrides": overrides,
            "brandNameMigrationVersion": 1,
        })
        return self.brand()

    def adopt_imported_data(self, snapshot: Any) -> dict[str, Any]:
        """Rebase on a later legacy import while retaining existing values and edits."""
        incoming_brand, has_main = _legacy_state(snapshot)
        if not has_main:
            return self.brand()
        merged = {**self._runtime["legacyBrand"], **incoming_brand}
        runtime = {**self._runtime, "legacyBrand": merged}
        runtime, migrated_name = _migrate_legacy_default_name(runtime)
        if merged != self._runtime["legacyBrand"] or migrated_name:
            self._commit(runtime)
        return self.brand()


class BrandBridge(QObject):
    """Small QML adapter for BrandAppearanceDialog; it has no main-window policy."""

    changed = Signal()

    def __init__(self, repository: BrandRepository, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.repository = repository

    @Property("QVariant", notify=changed)
    def brand(self) -> dict[str, Any]:
        return self.repository.brand()

    @Slot(str, result=str)
    def firstLetter(self, text: str) -> str:
        return _first_grapheme(text.strip() if isinstance(text, str) else "")

    @Slot("QVariant", result="QVariant")
    def saveBrand(self, draft: Any) -> dict[str, Any]:
        if isinstance(draft, QJSValue):
            draft = draft.toVariant()
        try:
            result = self.repository.save(draft)
        except BrandRepositoryError as exc:
            return {"ok": False, "error": str(exc)}
        self.changed.emit()
        return {"ok": True, "error": "", "brand": result}

    @Slot(result="QVariant")
    def resetBrand(self) -> dict[str, Any]:
        try:
            result = self.repository.reset_defaults()
        except BrandRepositoryError as exc:
            return {"ok": False, "error": str(exc)}
        self.changed.emit()
        return {"ok": True, "error": "", "brand": result}

    @Slot(str, result="QVariant")
    def inspectAvatar(self, source: str) -> dict[str, Any]:
        return inspect_avatar_source(source)

    @Slot(str, float, float, float, result="QVariant")
    def prepareAvatarImage(
        self, source: str, center_x: float, center_y: float, zoom: float
    ) -> dict[str, Any]:
        return prepare_avatar_image(source, center_x, center_y, zoom)

    @Slot("QVariant", result="QVariant")
    def adoptImportedData(self, snapshot: Any) -> dict[str, Any]:
        if isinstance(snapshot, QJSValue):
            snapshot = snapshot.toVariant()
        try:
            result = self.repository.adopt_imported_data(snapshot)
        except BrandRepositoryError as exc:
            return {"ok": False, "error": str(exc)}
        self.changed.emit()
        return {"ok": True, "error": "", "brand": result}
