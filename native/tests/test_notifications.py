from __future__ import annotations

import unittest

from wanxiang.notifications import (
    SystemTrayNotificationAdapter,
)


class FakeTray:
    def __init__(self, *, available: bool = True, supports_messages: bool = True) -> None:
        self.available = available
        self.supports_messages = supports_messages
        self.calls: list[tuple[object, ...]] = []

    def isSystemTrayAvailable(self) -> bool:
        return self.available

    def supportsMessages(self) -> bool:
        return self.supports_messages

    def showMessage(self, *args: object) -> None:
        self.calls.append(args)


class NotificationAdapterTests(unittest.TestCase):
    def test_available_tray_receives_limited_text_icon_and_timeout(self) -> None:
        tray = FakeTray()
        adapter = SystemTrayNotificationAdapter(
            tray,
            information_icon="information",
            duration_ms=4321,
            max_title_chars=8,
            max_message_chars=12,
        )

        result = adapter.notify(
            "  TitleLongerThanLimit  ", "  ReminderBodyLonger  "
        )

        self.assertTrue(result.sent)
        self.assertEqual(result.reason, "")
        self.assertEqual(
            tray.calls,
            [("TitleLo…", "ReminderBod…", "information", 4321)],
        )

    def test_unavailable_tray_returns_failure_without_sending(self) -> None:
        tray = FakeTray(available=False)
        adapter = SystemTrayNotificationAdapter(tray)

        result = adapter.notify("日程提醒", "该处理这件日程了。")

        self.assertFalse(result.sent)
        self.assertIn("没有可用的系统托盘", result.reason)
        self.assertEqual(tray.calls, [])

    def test_unsupported_messages_and_missing_qt_return_explicit_failure(self) -> None:
        tray = FakeTray(supports_messages=False)
        result = SystemTrayNotificationAdapter(tray).notify("日程提醒", "请处理日程。")
        self.assertFalse(result.sent)
        self.assertIn("不支持消息提示", result.reason)
        self.assertEqual(tray.calls, [])

        unavailable = SystemTrayNotificationAdapter(None)
        failure = unavailable.notify("日程提醒", "请处理日程。")
        self.assertFalse(failure.sent)
        self.assertIn("没有可用的系统托盘", failure.reason)


if __name__ == "__main__":
    unittest.main()
