from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from wanxiang.converter import ConversionError, convert_file, formats_for
from wanxiang.media_conversion import available_targets, ffmpeg_path


class MediaConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="wanxiang-media-converter-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "output"
        self.output.mkdir()

    def _engine(self) -> str:
        executable = ffmpeg_path()
        if not executable:
            self.skipTest("FFmpeg is not installed or configured for this test environment")
        return executable

    def _make_tone(self) -> Path:
        executable = self._engine()
        source = self.root / "tone.wav"
        result = subprocess.run(
            [executable, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=1", "-c:a", "pcm_s16le", str(source)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode:
            self.skipTest("The configured FFmpeg build does not include the lavfi test source")
        return source

    def test_engine_availability_filters_audio_targets(self) -> None:
        self._engine()
        source = self._make_tone()
        targets = {item["value"] for item in formats_for(source)}
        self.assertIn("mp3", targets)
        self.assertNotIn("wav", targets)
        self.assertNotIn("mp4", targets)

    def test_audio_conversion_reports_progress_and_decodes_output(self) -> None:
        executable = self._engine()
        source = self._make_tone()
        progress: list[int] = []
        output = convert_file(source, "mp3", self.output, progress_callback=progress.append)
        self.assertEqual(output.suffix, ".mp3")
        self.assertGreater(output.stat().st_size, 0)
        self.assertTrue(progress)
        self.assertEqual(progress[-1], 100)
        self.assertEqual(progress, sorted(progress))

        decoded = subprocess.run(
            [executable, "-hide_banner", "-loglevel", "error", "-i", str(output), "-f", "null", "-"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(decoded.returncode, 0, decoded.stderr.decode("utf-8", errors="replace"))

    def test_media_conversion_failure_leaves_no_partial_output(self) -> None:
        self._engine()
        source = self.root / "broken.wav"
        source.write_bytes(b"not a wave file")
        with self.assertRaisesRegex(ConversionError, "FFmpeg"):
            convert_file(source, "mp3", self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_video_conversion_and_audio_extraction(self) -> None:
        executable = self._engine()
        source = self.root / "color.mp4"
        result = subprocess.run(
            [executable, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=c=blue:s=160x120:d=1", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=1", "-shortest", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode:
            self.skipTest("The configured FFmpeg build does not include the video test codecs")

        targets = {item["value"] for item in formats_for(source)}
        video_target = next((target for target in ("mkv", "avi", "mov") if target in targets), None)
        self.assertIsNotNone(video_target)
        converted = convert_file(source, str(video_target), self.output)
        audio = convert_file(source, "mp3", self.output)
        for output in (converted, audio):
            decoded = subprocess.run(
                [executable, "-hide_banner", "-loglevel", "error", "-i", str(output), "-f", "null", "-"],
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(decoded.returncode, 0, decoded.stderr.decode("utf-8", errors="replace"))

    def test_media_targets_disappear_when_engine_is_unavailable(self) -> None:
        with patch("wanxiang.media_conversion.ffmpeg_path", return_value=None):
            self.assertEqual(available_targets("wav"), [])


if __name__ == "__main__":
    unittest.main()
