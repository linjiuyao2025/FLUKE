from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(os.environ.get("FLUKE_FFMPEG_CANDIDATE_ROOT", Path(__file__).resolve().parents[1]))
BIN = ROOT / "bin"
if not (BIN / "ffmpeg.exe").is_file():
    BIN = ROOT / "staging" / "bin"
OUT = Path(os.environ.get("FLUKE_FFMPEG_SMOKE_OUTPUT", ROOT / "synthetic-tests"))
FFMPEG = BIN / "ffmpeg.exe"
FFPROBE = BIN / "ffprobe.exe"
OUT.mkdir(parents=True, exist_ok=True)
os.environ["FLUKE_FFMPEG_PATH"] = str(FFMPEG)
os.environ["FLUKE_FFPROBE_PATH"] = str(FFPROBE)

from wanxiang.media_conversion import available_targets, available_video_codecs, convert_media


def run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)


def probe(path: Path) -> dict:
    result = run([
        str(FFPROBE), "-v", "error", "-show_entries", "stream=codec_type,codec_name",
        "-of", "json", str(path),
    ])
    return json.loads(result.stdout)


report: dict[str, object] = {"engine": str(FFMPEG), "outputs": {}, "targets": {}}

# Short synthetic audio source.
wav = OUT / "synthetic-tone.wav"
run([
    str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
    "sine=frequency=440:duration=1", "-c:a", "pcm_s16le", str(wav),
])

audio_targets = available_targets("wav")
report["targets"]["audio_from_wav"] = audio_targets
for target in ("mp3", "flac", "m4a", "aac", "ogg", "opus", "wma"):
    if target not in audio_targets:
        raise RuntimeError(f"FLUKE adapter did not expose audio target {target}: {audio_targets}")
    destination = OUT / f"tone.{target}"
    convert_media(wav, destination, target)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise RuntimeError(f"No output created for audio target {target}")
    streams = probe(destination).get("streams", [])
    if not any(item.get("codec_type") == "audio" for item in streams):
        raise RuntimeError(f"Output has no audio stream for target {target}")
    report["outputs"][target] = {
        "size": destination.stat().st_size,
        "streams": streams,
    }

mp3 = OUT / "tone-for-wav.mp3"
convert_media(wav, mp3, "mp3")
wav_roundtrip = OUT / "tone-roundtrip.wav"
convert_media(mp3, wav_roundtrip, "wav")
report["outputs"]["wav"] = {
    "size": wav_roundtrip.stat().st_size,
    "streams": probe(wav_roundtrip).get("streams", []),
}

# MPEG-4/MP3 AVI source exercises a different video container and audio track.
avi = OUT / "synthetic-source.avi"
run([
    str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
    "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=1",
    "-f", "lavfi", "-i", "sine=frequency=660:duration=1", "-shortest",
    "-c:v", "mpeg4", "-q:v", "5", "-c:a", "libmp3lame", "-b:a", "96k", str(avi),
])

video_codecs = available_video_codecs("webm")
report["targets"]["video_from_avi"] = available_targets("avi")
report["targets"]["webm_codecs"] = video_codecs
if not any(item.get("value") == "vp9" for item in video_codecs):
    raise RuntimeError(f"FLUKE adapter did not expose VP9 for WebM: {video_codecs}")

webm = OUT / "synthetic-vp9-opus.webm"
convert_media(avi, webm, "webm", video_codec="vp9")
webm_streams = probe(webm).get("streams", [])
codecs = {item.get("codec_type"): item.get("codec_name") for item in webm_streams}
if codecs.get("video") != "vp9" or codecs.get("audio") != "opus":
    raise RuntimeError(f"WebM stream codec mismatch: {codecs}")
report["outputs"]["webm_vp9_opus"] = {"size": webm.stat().st_size, "streams": webm_streams}

# Try the application's H.264 selection, which resolves to Media Foundation
# in this LGPL-only build. The host OS may or may not expose an MF encoder.
if any(item.get("value") == "h264" for item in available_video_codecs("mp4")):
    mp4 = OUT / "synthetic-h264-mf.mp4"
    try:
        convert_media(avi, mp4, "mp4", video_codec="h264")
        report["outputs"]["mp4_h264_mf"] = {
            "size": mp4.stat().st_size,
            "streams": probe(mp4).get("streams", []),
        }
    except Exception as exc:  # keep an environment-specific MF result explicit
        report["outputs"]["mp4_h264_mf"] = {"error": str(exc)}
else:
    report["outputs"]["mp4_h264_mf"] = {"unavailable": "h264 encoder not exposed"}

(OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
