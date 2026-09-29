"""PyInstaller console entry point for the packaged converter CLI."""

from wanxiang.converter_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
