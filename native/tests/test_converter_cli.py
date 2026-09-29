from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from pypdf import PdfReader, PdfWriter

from wanxiang.converter_cli import main


class ConverterCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="fluke-converter-cli-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "output"
        self.output.mkdir()

    def _invoke(self, args: list[str]) -> tuple[int, dict[str, object], str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_capabilities_and_per_file_target_query_are_json(self) -> None:
        csv_path = self.root / "sample.csv"
        csv_path.write_text("name,value\nexample,3\n", encoding="utf-8")

        code, capabilities, _stderr = self._invoke(["capabilities"])
        self.assertEqual(code, 0)
        self.assertTrue(capabilities["localOnly"])
        self.assertIn("images-to-pdf", capabilities["operations"])

        missing = self.root / "missing.csv"
        code, result, _stderr = self._invoke(["targets", str(csv_path), str(missing)])
        self.assertEqual(code, 0)
        items = result["items"]
        self.assertTrue(items[0]["supported"])
        self.assertIn("json", {item["value"] for item in items[0]["targets"]})
        self.assertFalse(items[1]["supported"])
        self.assertIn("error", items[1])

    def test_batch_conversion_isolates_bad_file_and_reports_json(self) -> None:
        first = self.root / "first.csv"
        second = self.root / "second.csv"
        first.write_text("name\nfirst\n", encoding="utf-8")
        second.write_text("name\nsecond\n", encoding="utf-8")
        missing = self.root / "missing.csv"

        code, result, _stderr = self._invoke([
            "convert", "--to", "json", str(first), str(missing), str(second),
            "--output-dir", str(self.output),
        ])

        self.assertEqual(code, 1)
        self.assertEqual((result["succeeded"], result["failed"]), (2, 1), repr(result))
        self.assertEqual([item["status"] for item in result["items"]], ["done", "failed", "done"])
        self.assertTrue(Path(result["items"][0]["output"]).is_file())
        self.assertTrue(Path(result["items"][2]["output"]).is_file())

    def test_images_to_pdf_reports_progress_on_stderr_and_writes_pages_in_order(self) -> None:
        sources = [self.root / "image-1.png", self.root / "image-2.png"]
        colors = (0xFF294A63, 0xFFB65D39)
        for source, color in zip(sources, colors):
            image = QImage(20, 12, QImage.Format.Format_RGB32)
            image.fill(color)
            self.assertTrue(image.save(str(source), "PNG"))

        code, result, stderr = self._invoke([
            "images-to-pdf", *(str(source) for source in sources),
            "--output-dir", str(self.output), "--progress",
        ])

        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        output = Path(result["output"])
        self.assertEqual(len(PdfReader(str(output)).pages), 2)
        events = [json.loads(line) for line in stderr.splitlines()]
        self.assertTrue(events)
        self.assertTrue(all(event["event"] == "progress" for event in events))
        self.assertEqual(events[-1]["progress"], 100)
        self.assertTrue(all(source.is_file() for source in sources))

    def test_merge_pdfs_preserves_input_order_and_original_files(self) -> None:
        sources = [self.root / "first.pdf", self.root / "second.pdf"]
        for source, size in zip(sources, (72, 144)):
            writer = PdfWriter()
            writer.add_blank_page(width=size, height=size)
            with source.open("wb") as stream:
                writer.write(stream)
        originals = [source.read_bytes() for source in sources]

        code, result, _stderr = self._invoke([
            "merge-pdfs", *(str(source) for source in sources),
            "--output-dir", str(self.output),
        ])

        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        merged = PdfReader(result["output"])
        self.assertEqual([float(page.mediabox.width) for page in merged.pages], [72, 144])
        self.assertEqual([source.read_bytes() for source in sources], originals)


if __name__ == "__main__":
    unittest.main()
