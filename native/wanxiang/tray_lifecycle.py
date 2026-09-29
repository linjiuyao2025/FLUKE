"""Window and system-tray lifecycle for reminders that outlive the window."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Slot


class TrayLifecycleController(QObject):
    """Keep the application alive while reminders remain scheduled.

    The controller shares the notification adapter's tray icon, installs the
    legacy open/exit menu, and lets QML decide whether an intercepted close
    should hide the window or ask the user what to do when a tray is absent.
    """

    def __init__(
        self,
        app: object,
        tray: object | None,
        has_pending_reminders: Callable[[], bool],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._tray = tray
        self._has_pending_reminders = has_pending_reminders
        self._window: object | None = None
        self._menu: object | None = None

        if tray is not None:
            try:
                from PySide6.QtWidgets import QMenu

                menu = QMenu()
                menu.addAction("打开 FLUKE", self.show_window)
                menu.addSeparator()
                menu.addAction("退出 FLUKE", self.exit_application)
                tray.setContextMenu(menu)
                tray.activated.connect(self._tray_activated)
                self._menu = menu
            except Exception:
                # A missing tray menu must not crash startup. The caller will
                # still receive an explicit close disposition below.
                self._tray = None

    def set_window(self, window: object) -> None:
        self._window = window

    @staticmethod
    def _tray_available(tray: object | None) -> bool:
        if tray is None:
            return False
        probe = getattr(tray, "isSystemTrayAvailable", None)
        if probe is None:
            return True
        try:
            if not bool(probe() if callable(probe) else probe):
                return False
            supports_messages = getattr(tray, "supportsMessages", None)
            if supports_messages is None:
                return True
            return bool(
                supports_messages() if callable(supports_messages) else supports_messages
            )
        except Exception:
            return False

    @Slot(result=str)
    def closeDisposition(self) -> str:
        """Return ``close``, ``hide``, ``no_tray`` or ``error`` for QML."""
        try:
            pending = bool(self._has_pending_reminders())
        except Exception:
            return "error"
        if not pending:
            return "close"
        if not self._tray_available(self._tray):
            return "no_tray"
        return "hide"

    @Slot()
    def show_window(self) -> None:
        window = self._window
        if window is None:
            return
        show = getattr(window, "show", None)
        if callable(show):
            show()
        raise_window = getattr(window, "raise", None) or getattr(window, "raise_", None)
        if callable(raise_window):
            raise_window()
        activate = getattr(window, "requestActivate", None) or getattr(window, "activateWindow", None)
        if callable(activate):
            activate()

    @Slot()
    def exit_application(self) -> None:
        quit_app = getattr(self._app, "quit", None)
        if callable(quit_app):
            quit_app()

    @Slot()
    def exitAnyway(self) -> None:
        """Let the user explicitly quit when reminders cannot use a tray."""
        self.exit_application()

    def _tray_activated(self, reason: object) -> None:
        # Qt's Trigger and DoubleClick enum values are intentionally compared
        # by their names so this remains straightforward to fake in tests.
        if str(reason).lower().endswith(("trigger", "doubleclick")):
            self.show_window()
