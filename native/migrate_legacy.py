from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from wanxiang.database import import_package
from wanxiang.migration import MigrationPackageError, read_package_file


def default_database_path() -> Path:
    roaming = Path(
        os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    )
    current = roaming / "FLUKE" / "fluke.sqlite3"
    previous = roaming / "Wanxiang Life Workspace Native" / "wanxiang.sqlite3"
    if current.exists() or not previous.is_file():
        return current

    # Move the existing native database forward without losing its SQLite WAL
    # state. Keep the old file as a recoverable copy; uninstall leaves it in place.
    current.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".fluke-migration-", suffix=".sqlite3", dir=current.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    source = destination = None
    try:
        source = sqlite3.connect(
            previous.resolve().as_uri() + "?mode=ro", uri=True, timeout=10
        )
        destination = sqlite3.connect(str(temporary), timeout=10)
        source.backup(destination)
        check = destination.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise sqlite3.DatabaseError("旧版数据库完整性检查失败")
        foreign_key_error = destination.execute("PRAGMA foreign_key_check").fetchone()
        if foreign_key_error:
            raise sqlite3.DatabaseError("旧版数据库关联检查失败")
        destination.close()
        destination = None
        source.close()
        source = None
        os.replace(temporary, current)
        return current
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise RuntimeError(
            "无法安全复制旧版原生数据库；旧数据库保持不变，请关闭其他窗口后重试。"
        ) from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _summary_payload(package: object) -> dict[str, object]:
    return {
        "sourceVersion": package.source_version,
        "exportedAt": package.exported_at,
        "checksum": package.checksum,
        "summary": package.summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="校验或一次性导入 FLUKE 兼容的旧版 localStorage 迁移包。"
    )
    parser.add_argument("--package", required=True, type=Path, help="旧版导出的 JSON 迁移包")
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite 数据库路径；默认使用新版独立的用户数据目录",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际写入 SQLite。省略时只校验文件并预览数量。",
    )
    args = parser.parse_args(argv)

    try:
        package = read_package_file(args.package)
        if not args.apply:
            print(
                json.dumps(
                    {"mode": "preview", **_summary_payload(package)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("预览未写入任何数据库。确认后添加 --apply 执行导入。")
            return 0

        database_path = args.database or default_database_path()
        result = import_package(package, database_path)
        print(
            json.dumps(
                {
                    "mode": result.status,
                    "database": result.database_path,
                    "checksum": result.checksum,
                    "summary": result.summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (MigrationPackageError, OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"迁移失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
