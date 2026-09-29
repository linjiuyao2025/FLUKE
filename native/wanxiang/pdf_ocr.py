"""Optional local OCR support for turning scanned PDFs into searchable PDFs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import csv
import io
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Callable

from PySide6.QtCore import QSize
from PySide6.QtPdf import QPdfDocument

from .converter_engines import engine_data_directory, engine_executable


OCR_DPI = 300
MAX_OCR_PAGES = 100
MAX_OCR_PAGE_PIXELS = 40_000_000
MAX_OCR_TOTAL_PIXELS = 500_000_000
MAX_OCR_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_OCR_DOCUMENT_SECONDS = 900
MAX_OCR_PAGE_SECONDS = 120

_LANGUAGE_PART = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
_LANGUAGE_ID = re.compile(r"^[A-Za-z0-9_/-]{1,64}$")


@dataclass(frozen=True)
class TesseractEngine:
    executable: str
    languages: frozenset[str]
    language: str
    tessdata_dir: str = ""


def _hidden_process_options() -> dict[str, object]:
    options: dict[str, object] = {}
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        options["startupinfo"] = startupinfo
    return options


@lru_cache(maxsize=8)
def _probe_engine(
    executable: str,
    executable_mtime_ns: int,
    language_override: str,
    tessdata_dir: str,
) -> TesseractEngine | None:
    del executable_mtime_ns  # Included in the cache key so replaced binaries are reprobed.
    try:
        version_result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
            **_hidden_process_options(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    version_match = re.search(r"\btesseract\s+v?(\d+)\.(\d+)(?:\.(\d+))?", version_result.stdout, re.I)
    if version_result.returncode != 0 or version_match is None:
        return None
    version = tuple(int(version_match.group(index) or 0) for index in (1, 2, 3))
    if version < (3, 3, 0):
        return None

    command = [executable, "--list-langs"]
    if tessdata_dir:
        command.extend(["--tessdata-dir", tessdata_dir])
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "2"
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
            env=environment,
            **_hidden_process_options(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    languages = frozenset(
        line.strip()
        for line in result.stdout.splitlines()
        if _LANGUAGE_ID.fullmatch(line.strip()) and line.strip().lower() not in {"osd", "script/osd"}
    )
    if not languages:
        return None

    if language_override:
        if not all(_LANGUAGE_PART.fullmatch(part) or _LANGUAGE_ID.fullmatch(part)
                   for part in language_override.split("+")):
            return None
        if not all(part in languages for part in language_override.split("+")):
            return None
        language = language_override
    elif {"chi_sim", "eng"}.issubset(languages):
        language = "chi_sim+eng"
    elif "eng" in languages:
        language = "eng"
    else:
        language = sorted(languages)[0]
    return TesseractEngine(executable, languages, language, tessdata_dir)


def tesseract_engine() -> TesseractEngine | None:
    configured = os.environ.get("FLUKE_TESSERACT_PATH", "").strip()
    executable = (
        str(Path(configured).expanduser().resolve())
        if configured
        else engine_executable("tesseract") or shutil.which("tesseract") or ""
    )
    if not executable:
        return None
    try:
        executable_mtime_ns = Path(executable).stat().st_mtime_ns
    except OSError:
        return None
    tessdata_dir = os.environ.get("FLUKE_TESSDATA_DIR", "").strip()
    if tessdata_dir:
        tessdata_dir = str(Path(tessdata_dir).expanduser().resolve())
        if not Path(tessdata_dir).is_dir():
            return None
    else:
        tessdata_dir = engine_data_directory("tesseract", "tessdata") or ""
    language_override = os.environ.get("FLUKE_TESSERACT_LANG", "").strip()
    return _probe_engine(executable, executable_mtime_ns, language_override, tessdata_dir)


def searchable_pdf_ocr_available() -> bool:
    return tesseract_engine() is not None


def available_ocr_languages() -> list[dict[str, str]]:
    engine = tesseract_engine()
    if engine is None:
        return []
    languages = set(engine.languages)
    options = [{"label": language, "value": language} for language in sorted(languages)]
    if {"chi_sim", "eng"}.issubset(languages):
        options.insert(0, {"label": "简体中文 + English", "value": "chi_sim+eng"})
    return options


def _run_tesseract_page(
    engine: TesseractEngine,
    image_path: Path,
    output_base: Path,
    timeout: float,
) -> Path:
    command = [engine.executable, str(image_path), str(output_base), "-l", engine.language, "--oem", "1", "pdf"]
    if engine.tessdata_dir:
        command[1:1] = ["--tessdata-dir", engine.tessdata_dir]
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "2"
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=max(1.0, timeout),
            check=False,
            env=environment,
            **_hidden_process_options(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("OCR 处理超时，请缩小文件或分批处理。") from exc
    except OSError as exc:
        raise RuntimeError("无法启动可用的 Tesseract OCR 引擎。") from exc
    output_pdf = output_base.with_suffix(".pdf")
    if result.returncode != 0 or not output_pdf.is_file() or output_pdf.stat().st_size <= 0:
        raise RuntimeError("Tesseract OCR 失败，请检查可用的语言模型。")
    return output_pdf


def recognize_tesseract_tsv(
    engine: TesseractEngine,
    image_path: Path,
    timeout: float,
) -> list[dict[str, object]]:
    """Return OCR lines with word boxes and confidence from a rendered page image."""
    command = [
        engine.executable,
        str(image_path),
        "stdout",
        "-l",
        engine.language,
        "--oem",
        "1",
        "tsv",
    ]
    if engine.tessdata_dir:
        command[1:1] = ["--tessdata-dir", engine.tessdata_dir]
    environment = os.environ.copy()
    environment["OMP_THREAD_LIMIT"] = "2"
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=max(1.0, timeout),
            check=False,
            env=environment,
            **_hidden_process_options(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("OCR 处理超时，请缩小文件或分批处理。") from exc
    except OSError as exc:
        raise RuntimeError("无法启动可用的 Tesseract OCR 引擎。") from exc
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("Tesseract OCR 失败，请检查可用的语言模型。")

    try:
        rows = csv.DictReader(io.StringIO(result.stdout.decode("utf-8-sig", errors="replace")), delimiter="\t")
        grouped: dict[tuple[str, str, str, str], dict[str, object]] = {}
        for row in rows:
            if row.get("level") != "5" or not (text := (row.get("text") or "").strip()):
                continue
            key = tuple(row.get(name, "") for name in ("page_num", "block_num", "par_num", "line_num"))
            try:
                left = float(row["left"])
                top = float(row["top"])
                right = left + float(row["width"])
                bottom = top + float(row["height"])
                confidence = max(0.0, min(100.0, float(row.get("conf", "0"))))
            except (KeyError, TypeError, ValueError):
                continue
            line = grouped.get(key)
            word = {
                "text": text,
                "x0": left,
                "top": top,
                "x1": right,
                "bottom": bottom,
                "confidence": confidence,
            }
            if line is None:
                grouped[key] = {
                    "text": text,
                    "x0": left,
                    "top": top,
                    "x1": right,
                    "bottom": bottom,
                    "confidence_sum": confidence,
                    "word_count": 1,
                    "words": [word],
                }
            else:
                line["text"] = f"{line['text']} {text}"
                line["x0"] = min(float(line["x0"]), left)
                line["top"] = min(float(line["top"]), top)
                line["x1"] = max(float(line["x1"]), right)
                line["bottom"] = max(float(line["bottom"]), bottom)
                line["confidence_sum"] = float(line["confidence_sum"]) + confidence
                line["word_count"] = int(line["word_count"]) + 1
                words = line.get("words")
                if isinstance(words, list):
                    words.append(word)
        return [
            {
                "text": str(line["text"]),
                "x0": float(line["x0"]),
                "top": float(line["top"]),
                "x1": float(line["x1"]),
                "bottom": float(line["bottom"]),
                "confidence": float(line["confidence_sum"]) / max(1, int(line["word_count"])),
                "words": list(line.get("words", [])),
            }
            for line in grouped.values()
        ]
    except Exception as exc:
        raise RuntimeError("Tesseract OCR 结果无法解析。") from exc


def create_searchable_pdf(
    source: Path,
    destination: Path,
    progress_callback: Callable[[int], None] | None = None,
    language: str = "",
) -> None:
    from pypdf import PdfReader, PdfWriter

    engine = tesseract_engine()
    if engine is None:
        raise RuntimeError("未检测到可用的 Tesseract OCR 引擎或语言模型。")
    selected_language = language.strip() or engine.language
    language_parts = selected_language.split("+")
    if not all(part in engine.languages for part in language_parts):
        raise RuntimeError("所选 OCR 语言未随当前组件提供，请重新选择可用语言。")
    engine = replace(engine, language=selected_language)

    try:
        with PdfReader(str(source), strict=False) as source_reader:
            if source_reader.is_encrypted:
                raise RuntimeError("扫描件 OCR 暂不处理加密 PDF，请先用原密码解密。")
            page_count = len(source_reader.pages)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("PDF 文件损坏或页面结构不受支持，无法执行 OCR。") from exc
    if page_count < 1:
        raise RuntimeError("PDF 中没有可执行 OCR 的页面。")
    if page_count > MAX_OCR_PAGES:
        raise RuntimeError("PDF 页数超过本机 OCR 安全上限。")

    document = QPdfDocument()
    document.load(str(source))
    if document.status() != QPdfDocument.Status.Ready or page_count != document.pageCount():
        document.close()
        raise RuntimeError("Qt PDF 引擎无法读取这个文件。")

    dimensions: list[QSize] = []
    total_pixels = 0
    for page in range(page_count):
        point_size = document.pagePointSize(page)
        if point_size.width() <= 0 or point_size.height() <= 0:
            document.close()
            raise RuntimeError("PDF 页面尺寸无效，已停止 OCR。")
        width = max(1, math.ceil(point_size.width() * OCR_DPI / 72))
        height = max(1, math.ceil(point_size.height() * OCR_DPI / 72))
        pixels = width * height
        if pixels > MAX_OCR_PAGE_PIXELS or total_pixels + pixels > MAX_OCR_TOTAL_PIXELS:
            document.close()
            raise RuntimeError("PDF 页面总像素数超过本机 OCR 安全上限。")
        dimensions.append(QSize(width, height))
        total_pixels += pixels

    deadline = time.monotonic() + MAX_OCR_DOCUMENT_SECONDS
    writer = PdfWriter()
    with tempfile.TemporaryDirectory(prefix="fluke-pdf-ocr-") as temp_name:
        temp_dir = Path(temp_name)
        accumulated_bytes = 0
        try:
            for page in range(page_count):
                image = document.render(page, dimensions[page])
                if image.isNull():
                    raise RuntimeError("无法渲染 PDF 页面。")
                image.setDotsPerMeterX(round(OCR_DPI / 0.0254))
                image.setDotsPerMeterY(round(OCR_DPI / 0.0254))
                image_path = temp_dir / f"page-{page + 1:04d}.png"
                if not image.save(str(image_path), "PNG"):
                    raise RuntimeError("无法生成 OCR 临时页面。")
                output_base = temp_dir / f"ocr-{page + 1:04d}"
                timeout = min(MAX_OCR_PAGE_SECONDS, deadline - time.monotonic())
                if timeout <= 0:
                    raise RuntimeError("OCR 总处理时间超过本机上限。")
                page_pdf = _run_tesseract_page(engine, image_path, output_base, timeout)
                accumulated_bytes += page_pdf.stat().st_size
                if accumulated_bytes > MAX_OCR_OUTPUT_BYTES:
                    raise RuntimeError("OCR 输出超过本机 PDF 大小上限。")
                writer.append(str(page_pdf))
                if progress_callback is not None:
                    progress_callback(round((page + 1) * 100 / page_count))
            with destination.open("wb") as stream:
                writer.write(stream)
        finally:
            writer.close()
            document.close()

    if destination.stat().st_size <= 0 or destination.stat().st_size > MAX_OCR_OUTPUT_BYTES:
        raise RuntimeError("OCR PDF 输出为空或超过本机大小上限。")
    with PdfReader(str(destination), strict=False) as result_reader:
        if result_reader.is_encrypted or len(result_reader.pages) != page_count:
            raise RuntimeError("OCR PDF 输出校验失败。")
