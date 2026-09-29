"""FFmpeg adapter for local audio/video conversions."""

from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Callable

from .converter_engines import engine_executable


AUDIO_INPUT_EXTENSIONS = {
    "aac", "aiff", "alac", "amr", "ape", "caf", "flac", "m4a", "mp3",
    "oga", "ogg", "opus", "wav", "wma",
}
VIDEO_INPUT_EXTENSIONS = {
    "3gp", "asf", "avi", "flv", "m4v", "mkv", "mov", "mp4", "mpeg",
    "mpg", "mts", "m2ts", "ogv", "ts", "vob", "webm", "wmv",
}
MEDIA_INPUT_EXTENSIONS = AUDIO_INPUT_EXTENSIONS | VIDEO_INPUT_EXTENSIONS
AUDIO_TARGETS = ("mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "wma")
VIDEO_TARGETS = ("mp4", "mkv", "mov", "webm", "avi")
MAX_MEDIA_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEDIA_OUTPUT_BYTES = 4 * 1024 * 1024 * 1024
MAX_MEDIA_DURATION_SECONDS = 4 * 60 * 60
MEDIA_TIMEOUT_SECONDS = 4 * 60 * 60
PROBE_TIMEOUT_SECONDS = 20

_AUDIO_ENCODERS = {
    "mp3": {"libmp3lame", "mp3"},
    "wav": {"pcm_s16le"},
    "flac": {"flac"},
    "m4a": {"aac"},
    "aac": {"aac"},
    "ogg": {"libvorbis", "vorbis"},
    "opus": {"libopus", "opus"},
    "wma": {"wmav2"},
}
_VIDEO_CODEC_ENCODERS = {
    "h264": ("libx264", "h264_mf", "h264_nvenc", "h264_qsv", "h264_amf"),
    "h265": ("libx265", "hevc_mf", "hevc_nvenc", "hevc_qsv", "hevc_amf"),
    "av1": ("libsvtav1", "libaom-av1", "av1", "av1_nvenc", "av1_qsv", "av1_amf"),
    "vp9": ("libvpx-vp9",),
    "mpeg4": ("mpeg4",),
    "msmpeg4v3": ("msmpeg4v3",),
}
_VIDEO_TARGET_CODECS = {
    "mp4": ("h264", "h265", "av1", "mpeg4"),
    "mkv": ("h264", "h265", "av1", "mpeg4"),
    "mov": ("h264", "h265", "av1", "mpeg4"),
    "webm": ("av1", "vp9"),
    "avi": ("mpeg4", "msmpeg4v3"),
}
_VIDEO_ENCODERS = {
    target: {encoder for codec in codecs for encoder in _VIDEO_CODEC_ENCODERS[codec]}
    for target, codecs in _VIDEO_TARGET_CODECS.items()
}
_AUDIO_MUXERS = {
    "mp3": {"mp3"}, "wav": {"wav"}, "flac": {"flac"}, "m4a": {"ipod", "mp4"},
    "aac": {"adts"}, "ogg": {"ogg", "oga"}, "opus": {"opus"}, "wma": {"asf"},
}
_VIDEO_MUXERS = {
    "mp4": {"mp4"}, "mkv": {"matroska"}, "mov": {"mov"},
    "webm": {"webm"}, "avi": {"avi"},
}


def ffmpeg_path() -> str | None:
    configured = os.environ.get("FLUKE_FFMPEG_PATH", "").strip().strip('"')
    if configured:
        path = Path(configured).expanduser()
        return str(path.resolve()) if path.is_file() else None
    bundled = engine_executable("ffmpeg")
    if bundled:
        return bundled
    return shutil.which("ffmpeg")


def ffprobe_path(executable: str | None = None) -> str | None:
    configured = os.environ.get("FLUKE_FFPROBE_PATH", "").strip().strip('"')
    if configured:
        path = Path(configured).expanduser()
        return str(path.resolve()) if path.is_file() else None
    if executable:
        sibling = Path(executable).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if sibling.is_file():
            return str(sibling)
    return shutil.which("ffprobe")


def _hidden_startup() -> tuple[object | None, int]:
    if os.name != "nt":
        return None, 0
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return startup, subprocess.CREATE_NO_WINDOW


@lru_cache(maxsize=16)
def _encoder_names(executable: str, size: int, modified_ns: int) -> frozenset[str]:
    startup, creation_flags = _hidden_startup()
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-encoders"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
            startupinfo=startup,
            creationflags=creation_flags,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    if result.returncode != 0:
        return frozenset()
    names = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and re.fullmatch(r"[A-Z\.]{6}", fields[0]):
            names.add(fields[1])
    return frozenset(names)


@lru_cache(maxsize=16)
def _muxer_names(executable: str, size: int, modified_ns: int) -> frozenset[str]:
    startup, creation_flags = _hidden_startup()
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-muxers"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
            startupinfo=startup,
            creationflags=creation_flags,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    if result.returncode != 0:
        return frozenset()
    names = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and re.fullmatch(r"[DE]{1,2}", fields[0]):
            names.add(fields[1])
    return frozenset(names)


def available_targets(source_extension: str) -> list[str]:
    executable = ffmpeg_path()
    if not executable or source_extension not in MEDIA_INPUT_EXTENSIONS:
        return []
    try:
        stat_result = Path(executable).stat()
    except OSError:
        return []
    encoders = _encoder_names(executable, stat_result.st_size, stat_result.st_mtime_ns)
    muxers = _muxer_names(executable, stat_result.st_size, stat_result.st_mtime_ns)
    source_extension = source_extension.lower().lstrip(".")
    targets: list[str] = []
    source_is_video = source_extension in VIDEO_INPUT_EXTENSIONS
    for target, accepted in _AUDIO_ENCODERS.items():
        if target != source_extension and accepted.intersection(encoders) and _AUDIO_MUXERS[target].intersection(muxers):
            targets.append(target)
    if source_is_video:
        for target, accepted in _VIDEO_ENCODERS.items():
            if target != source_extension and accepted.intersection(encoders) and _VIDEO_MUXERS[target].intersection(muxers):
                targets.append(target)
    return targets


def media_target_label(target: str) -> str:
    labels = {
        "mp3": "MP3 audio", "wav": "WAV audio", "flac": "FLAC audio",
        "m4a": "M4A audio", "aac": "AAC audio", "ogg": "OGG audio",
        "opus": "Opus audio", "wma": "WMA audio", "mp4": "MP4 video",
        "mkv": "MKV video", "mov": "MOV video", "webm": "WebM video",
        "avi": "AVI video",
    }
    return labels[target]


def available_video_codecs(target: str) -> list[dict[str, str]]:
    """Return codecs this local FFmpeg can encode into the selected container."""
    target = str(target).lower().lstrip(".")
    codecs = _VIDEO_TARGET_CODECS.get(target)
    executable = ffmpeg_path()
    if not codecs or not executable:
        return []
    try:
        stat_result = Path(executable).stat()
    except OSError:
        return []
    encoders = _encoder_names(executable, stat_result.st_size, stat_result.st_mtime_ns)
    muxers = _muxer_names(executable, stat_result.st_size, stat_result.st_mtime_ns)
    if not _VIDEO_MUXERS[target].intersection(muxers):
        return []
    labels = {
        "h264": "H.264 / AVC",
        "h265": "H.265 / HEVC",
        "av1": "AV1",
        "vp9": "VP9",
        "mpeg4": "MPEG-4 Part 2",
        "msmpeg4v3": "MS MPEG-4 v3",
    }
    return [
        {"value": codec, "label": labels[codec]}
        for codec in codecs
        if any(encoder in encoders for encoder in _VIDEO_CODEC_ENCODERS[codec])
    ]


def _duration_seconds(source: Path, executable: str) -> float | None:
    probe = ffprobe_path(executable)
    startup, creation_flags = _hidden_startup()
    if probe:
        try:
            result = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=PROBE_TIMEOUT_SECONDS,
                startupinfo=startup,
                creationflags=creation_flags,
                check=False,
            )
            if result.returncode == 0:
                duration = float(json.loads(result.stdout).get("format", {}).get("duration", 0))
                return duration if duration > 0 else None
        except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.SubprocessError):
            return None
    # Some portable/system FFmpeg installs ship ffmpeg without ffprobe. Asking
    # for input metadata without an output reads headers only and exits quickly.
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-nostdin", "-i", str(source)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS,
            startupinfo=startup,
            creationflags=creation_flags,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _audio_arguments(target: str, encoders: frozenset[str]) -> list[str]:
    candidates = {
        "mp3": ("libmp3lame", "-q:a", "3"),
        "wav": ("pcm_s16le",),
        "flac": ("flac",),
        "m4a": ("aac", "-b:a", "192k"),
        "aac": ("aac", "-b:a", "192k"),
        "ogg": ("libvorbis", "-q:a", "5"),
        "opus": ("libopus", "-b:a", "128k"),
        "wma": ("wmav2", "-b:a", "192k"),
    }
    candidate = candidates[target]
    encoder = next((name for name in candidate[0:1] if name in encoders), None)
    if not encoder:
        aliases = {"mp3": ("mp3",), "ogg": ("vorbis",), "opus": ("opus",)}
        encoder = next((name for name in aliases.get(target, ()) if name in encoders), None)
    if not encoder:
        raise ValueError("所选音频编码器不可用。")
    return ["-c:a", encoder, *candidate[1:]]


def _video_arguments(target: str, encoders: frozenset[str], codec: str = "") -> list[str]:
    codec_order = _VIDEO_TARGET_CODECS.get(target, ())
    selected_codec = str(codec).lower()
    if selected_codec and selected_codec not in codec_order:
        raise ValueError("所选视频编码在这个输出格式中不可用。")
    if not selected_codec:
        selected_codec = next(
            (candidate for candidate in codec_order
             if any(name in encoders for name in _VIDEO_CODEC_ENCODERS[candidate])),
            "",
        )
    video_encoder = next(
        (name for name in _VIDEO_CODEC_ENCODERS.get(selected_codec, ()) if name in encoders),
        "",
    )
    if not video_encoder:
        raise ValueError("所选视频编码器不可用。")

    if selected_codec == "h264" and video_encoder == "libx264":
        video_options = ["-preset", "medium", "-crf", "23"]
    elif selected_codec == "h265" and video_encoder == "libx265":
        video_options = ["-preset", "medium", "-crf", "28"]
    elif selected_codec == "av1" and video_encoder in {"libsvtav1", "libaom-av1"}:
        video_options = ["-b:v", "0", "-crf", "32"]
    elif selected_codec == "vp9":
        video_options = ["-deadline", "good", "-crf", "32", "-b:v", "0"]
    elif selected_codec in {"mpeg4", "msmpeg4v3"}:
        video_options = ["-q:v", "5"]
    else:
        video_options = ["-b:v", "4M"]

    if target == "webm":
        audio_encoder = next(
            (name for name in ("libopus", "opus", "libvorbis", "vorbis") if name in encoders),
            "",
        )
    else:
        audio_encoder = "aac" if "aac" in encoders else "libmp3lame" if "libmp3lame" in encoders else ""
    arguments = ["-c:v", video_encoder, *video_options]
    if audio_encoder:
        audio_bitrate = "128k" if target == "webm" else "192k" if audio_encoder == "aac" else "160k"
        arguments.extend(["-c:a", audio_encoder, "-b:a", audio_bitrate])
    else:
        arguments.append("-an")
    if target in {"mp4", "mov"}:
        arguments.extend(["-movflags", "+faststart"])
    return arguments


def convert_media(
    source: Path,
    destination: Path,
    target: str,
    progress_callback: Callable[[int], None] | None = None,
    video_codec: str = "",
) -> None:
    executable = ffmpeg_path()
    if not executable:
        raise ValueError("本机没有可用的 FFmpeg 程序。")
    stat_result = Path(executable).stat()
    encoders = _encoder_names(executable, stat_result.st_size, stat_result.st_mtime_ns)
    targets = available_targets(source.suffix.lower().lstrip("."))
    if target not in targets:
        raise ValueError("所选音视频输出格式或编码器不可用。")
    source_size = source.stat().st_size
    if source_size > MAX_MEDIA_BYTES:
        raise ValueError("音视频源文件超过本机 2 GiB 处理上限。")
    duration = _duration_seconds(source, executable)
    if duration and duration > MAX_MEDIA_DURATION_SECONDS:
        raise ValueError("音视频时长超过本机 4 小时处理上限。")

    source_is_video = source.suffix.lower().lstrip(".") in VIDEO_INPUT_EXTENSIONS
    if target in AUDIO_TARGETS:
        args = ["-map", "0:a:0", "-vn", "-sn", "-dn", *_audio_arguments(target, encoders)]
    elif source_is_video and target in VIDEO_TARGETS:
        args = ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", *_video_arguments(target, encoders, video_codec)]
    else:
        raise ValueError("所选音视频转换方向不受支持。")
    command = [
        executable, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-i", str(source), *args, "-progress", "pipe:1", "-nostats", str(destination),
    ]
    startup, creation_flags = _hidden_startup()
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            startupinfo=startup,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise ValueError("无法启动本机 FFmpeg 程序。") from exc
    lines: queue.Queue[str | None] = queue.Queue()

    def capture_output() -> None:
        try:
            if process.stdout:
                for raw_line in process.stdout:
                    lines.put(raw_line.decode("utf-8", errors="replace").strip())
        finally:
            lines.put(None)

    reader_thread = threading.Thread(target=capture_output, name="fluke-ffmpeg-output", daemon=True)
    reader_thread.start()
    deadline = time.monotonic() + MEDIA_TIMEOUT_SECONDS
    values: dict[str, str] = {}
    timed_out = False
    oversized = False
    try:
        while True:
            if destination.is_file() and destination.stat().st_size > MAX_MEDIA_OUTPUT_BYTES:
                oversized = True
                try:
                    process.terminate()
                except OSError:
                    pass
                break
            if time.monotonic() >= deadline:
                timed_out = True
                try:
                    process.terminate()
                except OSError:
                    pass
                break
            try:
                line = lines.get(timeout=0.25)
            except queue.Empty:
                if process.poll() is not None and not reader_thread.is_alive():
                    break
                continue
            if line is None:
                break
            key, separator, value = line.partition("=")
            if not separator:
                continue
            values[key] = value
            if key == "progress":
                elapsed_us = int(values.get("out_time_us", values.get("out_time_ms", "0")) or 0)
                if duration and progress_callback:
                    progress_callback(min(99, max(0, int(elapsed_us * 100 / (duration * 1_000_000)))))
                values.clear()
        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            return_code = process.wait()
    finally:
        if process.stdout:
            process.stdout.close()
        reader_thread.join(timeout=1)

    if timed_out:
        raise ValueError("音视频转换超时，已停止处理。")
    if oversized:
        raise ValueError("音视频输出超过本机 4 GiB 上限，已提前停止转换。")
    if return_code != 0:
        raise ValueError("本机 FFmpeg 无法用当前编码器转换此文件。")
    if not destination.is_file() or destination.stat().st_size == 0:
        raise ValueError("FFmpeg 没有生成有效的音视频文件。")
    if destination.stat().st_size > MAX_MEDIA_OUTPUT_BYTES:
        raise ValueError("音视频输出超过本机 4 GiB 处理上限。")
    if progress_callback:
        progress_callback(100)
