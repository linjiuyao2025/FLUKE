from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from wanxiang.tray_lifecycle import TrayLifecycleController


class FakeSignal:
    def __init__(self) -> None:
        self._slots = []

    def connect(self, callback) -> None:
        self._slots.append(callback)

    def emit(self, value) -> None:
        for callback in self._slots:
            callback(value)


class FakeApp:
    def __init__(self) -> None:
        self.quit_calls = 0

    def quit(self) -> None:
        self.quit_calls += 1


class FakeTray:
    def __init__(self, *, available: bool = True, supports_messages: bool = True) -> None:
        self.available = available
        self.supports_messages = supports_messages
        self.activated = FakeSignal()
        self.menu = None

    def isSystemTrayAvailable(self) -> bool:
        return self.available

    def supportsMessages(self) -> bool:
        return self.supports_messages

    def setContextMenu(self, menu) -> None:
        self.menu = menu


class FakeWindow:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def show(self) -> None:
        self.calls.append("show")

    def raise_(self) -> None:
        self.calls.append("raise")

    def requestActivate(self) -> None:
        self.calls.append("activate")


class TrayLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_close_hides_only_when_a_reminder_and_system_tray_are_available(self) -> None:
        app = FakeApp()
        tray = FakeTray()
        pending = [True]
        controller = TrayLifecycleController(app, tray, lambda: pending[0])

        self.assertEqual(controller.closeDisposition(), "hide")
        pending[0] = False
        self.assertEqual(controller.closeDisposition(), "close")
        pending[0] = True
        tray.available = False
        self.assertEqual(controller.closeDisposition(), "no_tray")

    def test_close_keeps_window_open_when_tray_cannot_show_notifications(self) -> None:
        controller = TrayLifecycleController(FakeApp(), FakeTray(supports_messages=False), lambda: True)
        self.assertEqual(controller.closeDisposition(), "no_tray")

    def test_query_failure_keeps_the_window_open_and_explicit_exit_still_works(self) -> None:
        app = FakeApp()

        def failed_query() -> bool:
            raise OSError("database unavailable")

        controller = TrayLifecycleController(app, None, failed_query)
        self.assertEqual(controller.closeDisposition(), "error")
        controller.exitAnyway()
        self.assertEqual(app.quit_calls, 1)

    def test_tray_menu_and_activation_reopen_the_same_window_and_offer_exit(self) -> None:
        app = FakeApp()
        tray = FakeTray()
        window = FakeWindow()
        controller = TrayLifecycleController(app, tray, lambda: True)
        controller.set_window(window)

        self.assertIsNotNone(tray.menu)
        actions = tray.menu.actions()
        self.assertEqual(actions[0].text(), "打开 FLUKE")
        self.assertEqual(actions[-1].text(), "退出 FLUKE")
        actions[0].trigger()
        self.assertEqual(window.calls, ["show", "raise", "activate"])
        tray.activated.emit(QSystemTrayIcon.ActivationReason.Trigger)
        self.assertEqual(window.calls[-3:], ["show", "raise", "activate"])
        actions[-1].trigger()
        self.assertEqual(app.quit_calls, 1)


if __name__ == "__main__":
    unittest.main()
