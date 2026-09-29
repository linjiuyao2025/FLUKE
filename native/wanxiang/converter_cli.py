"""JSON command-line access to the converter's existing local operations."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


def _write_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _create_gui_application() -> Any:
    # The converter uses Qt image readers and QtPdf outside the window too.
    # Keep the CLI headless and avoid creating or touching the user's profile DB.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    application = QGuiApplication.instance()
    if application is None:
        application = QGuiApplication(["fluke-convert"])
    return application


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fluke-convert",
        description="在本机查询并执行 FLUKE 支持的格式转换。",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("capabilities", help="输出本机可处理的输入类型。")

    targets = commands.add_parser("targets", help="查询一个或多个文件的可用目标格式。")
    targets.add_argument("files", nargs="+", type=Path, help="要查询的本地文件。")

    convert = commands.add_parser("convert", help="转换一个或多个本地文件。")
    convert.add_argument("files", nargs="+", type=Path, help="要转换的本地文件。")
    convert.add_argument("--to", required=True, dest="target", help="统一使用的目标格式。")
    convert.add_argument("--output-dir", type=Path, help="输出目录；不指定时与源文件放在一起。")
    convert.add_argument("--video-codec", help="可选视频编码，例如 h264、h265、av1 或 vp9。")
    convert.add_argument("--progress", action="store_true", help="将阶段进度 JSON 写入标准错误流。")

    images = commands.add_parser("images-to-pdf", help="按参数顺序将多张图片合并成 PDF。")
    images.add_argument("files", nargs="+", type=Path, help="至少两张本地图片。")
    images.add_argument("--output-dir", type=Path, help="输出目录；不指定时与第一张图片放在一起。")
    images.add_argument("--progress", action="store_true", help="将阶段进度 JSON 写入标准错误流。")

    merge = commands.add_parser("merge-pdfs", help="按参数顺序合并多个未加密 PDF。")
    merge.add_argument("files", nargs="+", type=Path, help="至少两份本地 PDF。")
    merge.add_argument("--output-dir", type=Path, help="输出目录；不指定时与第一份 PDF 放在一起。")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    args = _parser().parse_args(argv)
    application = _create_gui_application()

    from .converter import (
        ConversionError,
        convert_file,
        formats_for,
        images_to_pdf,
        input_extensions,
        merge_pdf_files,
    )
    from .media_conversion import VIDEO_TARGETS, available_video_codecs

    if args.command == "capabilities":
        _write_json({
            "ok": True,
            "inputExtensions": sorted(input_extensions()),
            "operations": ["targets", "convert", "images-to-pdf", "merge-pdfs"],
            "localOnly": True,
        })
        return 0

    if args.command == "targets":
        items = []
        for source in args.files:
            resolved = source.expanduser()
            try:
                if not resolved.is_file():
                    raise ConversionError("找不到这个文件，或它不是普通文件。")
                options = formats_for(resolved)
                targets = []
                for option in options:
                    item = dict(option)
                    if item.get("value") in VIDEO_TARGETS:
                        item["videoCodecs"] = available_video_codecs(item["value"])
                    targets.append(item)
                items.append({
                    "source": str(resolved),
                    "supported": bool(targets),
                    "targets": targets,
                })
            except Exception as exc:
                items.append({
                    "source": str(resolved),
                    "supported": False,
                    "targets": [],
                    "error": str(exc),
                })
        _write_json({"ok": True, "items": items})
        return 0

    if args.command in {"images-to-pdf", "merge-pdfs"}:
        sources = [path.expanduser() for path in args.files]
        output_directory = str(args.output_dir.expanduser()) if args.output_dir else None
        try:
            if args.command == "images-to-pdf":
                last_progress = [-1]

                def report_merge_progress(progress: int) -> None:
                    if not args.progress or int(progress) == last_progress[0]:
                        return
                    last_progress[0] = int(progress)
                    print(json.dumps({
                        "event": "progress",
                        "operation": "images-to-pdf",
                        "progress": int(progress),
                    }, ensure_ascii=False, separators=(",", ":")), file=sys.stderr, flush=True)

                output = images_to_pdf(
                    sources, output_directory,
                    report_merge_progress if args.progress else None,
                )
            else:
                output = merge_pdf_files(sources, output_directory)
            _write_json({"ok": True, "operation": args.command, "output": str(output)})
            _ = application
            return 0
        except (ConversionError, OSError, ValueError) as exc:
            _write_json({"ok": False, "operation": args.command, "error": str(exc)})
            _ = application
            return 1

    output_directory = str(args.output_dir.expanduser()) if args.output_dir else None
    results: list[dict[str, Any]] = []
    requested_target = str(args.target).lower().lstrip(".")
    requested_codec = str(args.video_codec or "").lower()
    for source in args.files:
        resolved = source.expanduser()
        try:
            if not resolved.is_file():
                raise ConversionError("找不到这个文件，或它不是普通文件。")
            valid_targets = {item["value"] for item in formats_for(resolved)}
            if requested_target not in valid_targets:
                raise ConversionError("所选格式不适用于这个文件，或当前设备没有对应的转换组件。")
            if requested_codec:
                if requested_target not in VIDEO_TARGETS:
                    raise ConversionError("所选视频编码在这个输出格式中不可用。")
                valid_codecs = {item["value"] for item in available_video_codecs(requested_target)}
                if requested_codec not in valid_codecs:
                    raise ConversionError("所选视频编码器不可用。")
            last_progress = [-1]

            def report_progress(progress: int) -> None:
                if not args.progress or int(progress) == last_progress[0]:
                    return
                last_progress[0] = int(progress)
                print(json.dumps({
                    "event": "progress",
                    "source": str(resolved),
                    "target": requested_target,
                    "progress": int(progress),
                }, ensure_ascii=False, separators=(",", ":")), file=sys.stderr, flush=True)

            output = convert_file(
                resolved,
                requested_target,
                output_directory,
                progress_callback=report_progress if args.progress else None,
                video_codec=requested_codec,
            )
            results.append({
                "source": str(resolved),
                "target": requested_target,
                "status": "done",
                "output": str(output),
            })
        except (ConversionError, OSError, ValueError) as exc:
            results.append({
                "source": str(resolved),
                "target": requested_target,
                "status": "failed",
                "error": str(exc),
            })
        except Exception as exc:
            results.append({
                "source": str(resolved),
                "target": requested_target,
                "status": "failed",
                "error": f"转换失败：{exc}",
            })

    succeeded = sum(1 for item in results if item["status"] == "done")
    _write_json({
        "ok": succeeded == len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "items": results,
    })
    # Retain the Qt application until all converters and codecs have finished.
    _ = application
    return 0 if succeeded == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
