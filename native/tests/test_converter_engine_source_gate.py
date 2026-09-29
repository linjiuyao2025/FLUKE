from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from wanxiang.converter_engines import _extract_component


class ConverterEngineSourceGateTests(unittest.TestCase):
    def test_nested_source_archive_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fluke-engine-source-gate-") as temporary:
            root = Path(temporary)
            archive = root / "tesseract.zip"
            staging = root / "staging"
            with zipfile.ZipFile(archive, "w") as package:
                package.writestr("tesseract.exe", b"executable")
                package.writestr("THIRD-PARTY-NOTICES.md", "license notices")
                package.writestr("source/msys2/mingw-w64-tesseract.src.tar.zst", b"source")

            component = {
                "id": "tesseract",
                "version": "5.5.0",
                "sha256": "0" * 64,
                "releaseTag": "test",
            }
            with patch(
                "wanxiang.converter_engines.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=b"Tesseract"),
            ):
                result = _extract_component(archive, component, staging, lambda *_: None)

            self.assertEqual(result, staging)
            self.assertTrue((staging / "source/msys2/mingw-w64-tesseract.src.tar.zst").is_file())
            self.assertTrue((staging / "engine.json").is_file())


if __name__ == "__main__":
    unittest.main()
