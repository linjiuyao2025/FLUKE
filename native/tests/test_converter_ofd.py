from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from pypdf import PdfReader

from wanxiang.converter import (
    ConversionError,
    _validate_ofd_archive,
    convert_file,
    formats_for,
)


class OfdConverterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="fluke-ofd-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()

    def _package(self, name: str = "fixture.ofd", root_xml: bytes | None = None, extra: dict[str, bytes] | None = None) -> Path:
        source = self.root / name
        content = root_xml or b'<?xml version="1.0" encoding="UTF-8"?><ofd:OFD xmlns:ofd="http://www.ofdspec.org/2016"/>'
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("OFD.xml", content)
            for member, data in (extra or {}).items():
                archive.writestr(member, data)
        return source

    def test_ofd_targets_are_dynamic_and_corrupt_packages_are_hidden(self) -> None:
        source = self._package()
        corrupt = self.root / "broken.ofd"
        corrupt.write_bytes(b"not an OFD zip")

        with patch("wanxiang.converter.ofd_engine_available", return_value=False):
            self.assertEqual(formats_for(source), [])
        with patch("wanxiang.converter.ofd_engine_available", return_value=True):
            self.assertEqual(
                [item["value"] for item in formats_for(source)],
                ["pdf", "html", "txt", "ofd-png-zip"],
            )
            self.assertEqual(formats_for(corrupt), [])

    def test_ofd_archive_rejects_traversal_and_entity_declarations(self) -> None:
        traversal = self._package(extra={"../outside.txt": b"unsafe"})
        with self.assertRaisesRegex(ConversionError, "内部路径"):
            _validate_ofd_archive(traversal)

        dtd = self._package(
            "entity.ofd",
            b'<!DOCTYPE OFD [<!ENTITY xxe SYSTEM "file:///secret">]><OFD>&xxe;</OFD>',
        )
        with self.assertRaisesRegex(ConversionError, "实体声明"):
            _validate_ofd_archive(dtd)

        utf16_dtd = self._package(
            "utf16-entity.ofd",
            '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE OFD [<!ENTITY xxe SYSTEM "file:///secret">]><OFD/>'.encode("utf-16"),
        )
        with self.assertRaisesRegex(ConversionError, "实体声明"):
            _validate_ofd_archive(utf16_dtd)

    def test_ofd_pdf_and_png_zip_keep_page_order_and_source(self) -> None:
        source = self._package()
        original = hashlib.sha256(source.read_bytes()).hexdigest()

        def render_fixture(_source: Path, target: str, output: Path) -> None:
            self.assertEqual(target, "png")
            output.mkdir(parents=True, exist_ok=True)
            for index, (width, height, color) in enumerate(
                ((240, 120, "#e53935"), (120, 240, "#1565c0"))
            ):
                image = QImage(width, height, QImage.Format.Format_RGB32)
                image.fill(color)
                self.assertTrue(image.save(str(output / f"{index}.png"), "PNG"))

        with (
            patch("wanxiang.converter.ofd_engine_available", return_value=True),
            patch("wanxiang.converter._run_ofdrw_bridge", side_effect=render_fixture),
        ):
            pdf = convert_file(source, "pdf", self.output)
            with PdfReader(str(pdf), strict=False) as reader:
                self.assertEqual(len(reader.pages), 2)
                first_ratio = float(reader.pages[0].mediabox.width) / float(reader.pages[0].mediabox.height)
                second_ratio = float(reader.pages[1].mediabox.width) / float(reader.pages[1].mediabox.height)
                self.assertAlmostEqual(first_ratio, 2.0, delta=0.03)
                self.assertAlmostEqual(second_ratio, 0.5, delta=0.03)

            page_zip = convert_file(source, "ofd-png-zip", self.output)
            with zipfile.ZipFile(page_zip) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.namelist(), ["page-0001.png", "page-0002.png"])
                for name in archive.namelist():
                    self.assertFalse(QImage.fromData(archive.read(name)).isNull(), name)

        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original)


if __name__ == "__main__":
    unittest.main()
