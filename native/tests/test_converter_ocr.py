from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPageSize, QPdfWriter
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader

from wanxiang.converter import ConverterBridge, formats_for
from wanxiang.pdf_ocr import TesseractEngine, tesseract_engine


class ConverterOcrTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_searchable_pdf_target_tracks_local_engine_availability(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fluke-ocr-target-") as temp_name:
            source = Path(temp_name) / "source.pdf"
            writer = QPdfWriter(str(source))
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            painter = QPainter(writer)
            painter.drawText(100, 160, "OCR target probe")
            painter.end()

            with patch("wanxiang.converter.searchable_pdf_ocr_available", return_value=False):
                hidden_values = {item["value"] for item in formats_for(source)}
            with patch("wanxiang.converter.searchable_pdf_ocr_available", return_value=True):
                visible_values = {item["value"] for item in formats_for(source)}

        self.assertNotIn("pdf-ocr", hidden_values)
        self.assertIn("pdf-ocr", visible_values)

    def test_bridge_keeps_ocr_language_private_and_rejects_unavailable_choice(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fluke-ocr-bridge-") as temp_name:
            source = Path(temp_name) / "source.pdf"
            writer = QPdfWriter(str(source))
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            painter = QPainter(writer)
            painter.drawText(100, 160, "OCR language probe")
            painter.end()
            fake_engine = TesseractEngine("test-only", frozenset({"chi_sim", "eng"}), "chi_sim+eng")
            languages = [
                {"label": "简体中文 + English", "value": "chi_sim+eng"},
                {"label": "eng", "value": "eng"},
                {"label": "chi_sim", "value": "chi_sim"},
            ]
            bridge = ConverterBridge()
            with patch("wanxiang.converter.searchable_pdf_ocr_available", return_value=True), patch(
                "wanxiang.converter.available_ocr_languages", return_value=languages
            ), patch("wanxiang.converter.tesseract_engine", return_value=fake_engine):
                bridge.addFiles(str(source))
                job_id = str(bridge.jobs[0]["id"])
                bridge.setTargetFormat(job_id, "pdf-ocr")
                bridge.setJobOcrLanguage(job_id, "eng")
                self.assertEqual(bridge.ocrLanguageForJob(job_id), "eng")
                bridge.setJobOcrLanguage(job_id, "fra")
                self.assertEqual(bridge.ocrLanguageForJob(job_id), "eng")
                self.assertNotIn("eng", repr(bridge.jobs))
                bridge.setTargetFormat(job_id, "txt")
                self.assertEqual(bridge.ocrLanguageForJob(job_id), "chi_sim+eng")

    def test_pdf_render_merge_and_progress_with_a_local_engine_adapter(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fluke-ocr-pipeline-") as temp_name:
            root = Path(temp_name)
            source = root / "scanned.pdf"
            writer = QPdfWriter(str(source))
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            painter = QPainter(writer)
            painter.drawText(100, 160, "Raster page one")
            writer.newPage()
            painter.drawText(100, 160, "Raster page two")
            painter.end()

            def fake_tesseract_page(
                _engine: TesseractEngine,
                image_path: Path,
                output_base: Path,
                _timeout: float,
            ) -> Path:
                self.assertTrue(image_path.is_file())
                output = output_base.with_suffix(".pdf")
                from wanxiang.converter import _write_pdf

                _write_pdf(output, f"<p>mock OCR {image_path.stem}</p>")
                return output

            progress: list[int] = []
            fake_engine = TesseractEngine("test-only", frozenset({"eng"}), "eng")
            from wanxiang.converter import convert_file

            with patch("wanxiang.converter.searchable_pdf_ocr_available", return_value=True), patch(
                "wanxiang.pdf_ocr.tesseract_engine", return_value=fake_engine
            ), patch(
                "wanxiang.pdf_ocr._run_tesseract_page", side_effect=fake_tesseract_page
            ):
                converted = convert_file(source, "pdf-ocr", root, progress_callback=progress.append)

            result = PdfReader(str(converted))
            text = "\n".join(page.extract_text() or "" for page in result.pages)

        self.assertEqual(len(result.pages), 2)
        self.assertIn("mock\tOCR\tpage-0001", text)
        self.assertIn("mock\tOCR\tpage-0002", text)
        self.assertEqual(progress, [50, 100])

    def test_real_scanned_pdf_becomes_searchable_when_tesseract_is_installed(self) -> None:
        engine = tesseract_engine()
        if engine is None:
            self.skipTest("Optional Tesseract engine and language data are not installed")

        with tempfile.TemporaryDirectory(prefix="fluke-ocr-real-") as temp_name:
            root = Path(temp_name)
            source = root / "scanned.pdf"
            destination_dir = root / "converted"
            destination_dir.mkdir()

            page_image = QImage(QSize(1800, 2400), QImage.Format.Format_ARGB32)
            page_image.fill(QColor("white"))
            painter = QPainter(page_image)
            painter.setPen(QColor("black"))
            painter.setFont(QFont("Arial", 100, QFont.Weight.Bold))
            painter.drawText(130, 440, "FLUKE OCR TEST")
            painter.drawText(130, 650, "12345")
            painter.end()

            writer = QPdfWriter(str(source))
            writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            writer.setResolution(150)
            painter = QPainter(writer)
            rect = QRectF(80, 80, writer.width() - 160, writer.height() - 160)
            painter.drawImage(rect, page_image)
            writer.newPage()
            painter.drawImage(rect, page_image)
            painter.end()
            source_before = source.read_bytes()

            from wanxiang.converter import convert_file

            progress: list[int] = []
            converted = convert_file(source, "pdf-ocr", destination_dir, progress_callback=progress.append)
            reader = PdfReader(str(converted))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            self.assertEqual(converted.name, "scanned_converted.pdf")
            self.assertEqual(source.read_bytes(), source_before)
            self.assertEqual(
                {path.name for path in root.iterdir()},
                {"scanned.pdf", "converted"},
            )
            self.assertEqual(
                {path.name for path in destination_dir.iterdir()},
                {"scanned_converted.pdf"},
            )
            self.assertEqual(len(reader.pages), 2)
            self.assertIn("FLUKE", text.upper())
            self.assertIn("12345", text)
            self.assertEqual(progress, [50, 100])


if __name__ == "__main__":
    unittest.main()
