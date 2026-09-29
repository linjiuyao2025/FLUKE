"""Qt bridge for the native home layout repository."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtQml import QJSValue

from .home_layout import HomeLayoutError, HomeLayoutRepository


class HomeLayoutBridge(QObject):
    """QML adapter for the local home layout and its read-only legacy source."""

    stateChanged = Signal()

    def __init__(self, database_path: Path) -> None:
        super().__init__()
        self._database_path = database_path
        self._repository: HomeLayoutRepository | None = None
        self._notice = ""
        self._load_from_database()

    @Property("QVariant", notify=stateChanged)
    def state(self) -> dict[str, object]:
        if self._repository is None:
            return {"layout": {}, "legacy": {}, "notice": self._notice}
        result = self._repository.snapshot()
        result["notice"] = self._notice
        return result

    def _load_from_database(self) -> None:
        try:
            self._repository = HomeLayoutRepository(self._database_path)
            self._notice = ""
        except (HomeLayoutError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._repository = None
            self._notice = str(exc) or "首页布局暂时无法载入。"

    @Slot()
    def refreshFromDatabase(self) -> None:
        self._load_from_database()
        self.stateChanged.emit()

    @Slot("QVariant", result="QVariant")
    def saveLayout(self, layout: object) -> dict[str, object]:
        value = layout.toVariant() if isinstance(layout, QJSValue) else layout
        if self._repository is None:
            return {"ok": False, "error": self._notice or "首页布局暂不可用。"}
        try:
            normalized = self._repository.save_layout(value)
        except (HomeLayoutError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            self._notice = str(exc) or "首页布局没有保存。"
            self.stateChanged.emit()
            return {"ok": False, "error": self._notice}
        self._notice = ""
        self.stateChanged.emit()
        return {"ok": True, "layout": normalized}
