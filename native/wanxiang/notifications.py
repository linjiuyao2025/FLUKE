"""Optional Qt system-tray notifications for the native application.

This adapter is deliberately independent of the planner bridge. Callers should
show their in-app reminder first, then use :meth:`notify` as a best-effort
system notification. A failed result is an explicit signal to keep the in-app
reminder as the fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


MAX_TITLE_CHARS = 64
MAX_MESSAGE_CHARS = 240
DEFAULT_DURATION_MS = 10_000

@dataclass(frozen=True)
class NotificationResult:
    """Outcome of dispatching one system-tray notification."""

    sent: bool
    reason: str = ""


Capability = bool | Callable[[], bool] | None


class SystemTrayNotificationAdapter:
    """Send short notifications through an injected Qt tray icon.

    ``tray`` can be a ``QSystemTrayIcon`` or a compatible fake. Capability
    checks are injectable so callers can report unavailable desktops without
    touching the UI. When omitted, Qt's static tray capability methods are
    queried through the injected object when available. Text is capped at 64
    title characters and 240 message characters by default; these are adapter
    limits, not guaranteed operating-system limits.
    """

    def __init__(
        self,
        tray: object | None,
        *,
        information_icon: object | None = None,
        duration_ms: int = DEFAULT_DURATION_MS,
        system_tray_available: Capability = None,
        messages_supported: Capability = None,
        max_title_chars: int = MAX_TITLE_CHARS,
        max_message_chars: int = MAX_MESSAGE_CHARS,
        unavailable_reason: str = "当前桌面没有可用的系统托盘，继续使用应用内提醒。",
    ) -> None:
        self._tray = tray
        self._information_icon = information_icon
        self._duration_ms = max(0, int(duration_ms))
        self._system_tray_available = system_tray_available
        self._messages_supported = messages_supported
        self._max_title_chars = max(1, int(max_title_chars))
        self._max_message_chars = max(1, int(max_message_chars))
        self._unavailable_reason = unavailable_reason

    @property
    def tray(self) -> object | None:
        """Return the owned Qt tray icon for shared lifecycle/menu wiring."""
        return self._tray

    @staticmethod
    def _trim(value: str, limit: int) -> str:
        value = value.strip()
        if len(value) <= limit:
            return value
        if limit == 1:
            return "…"
        return value[: limit - 1].rstrip() + "…"

    @staticmethod
    def _capability_value(
        configured: Capability,
        tray: object,
        method_name: str,
    ) -> tuple[bool, str]:
        candidate = configured
        if candidate is None:
            candidate = getattr(tray, method_name, None)
        if candidate is None:
            # A non-Qt compatible tray (including a test fake) may not expose
            # Qt's static capability methods. Its presence is sufficient.
            return True, ""
        try:
            available = bool(candidate() if callable(candidate) else candidate)
        except Exception as exc:
            return False, f"无法确认系统托盘能力：{exc}"
        return available, ""

    def notify(self, title: str, message: str) -> NotificationResult:
        """Attempt one notification and return a failure reason if unavailable."""
        if self._tray is None:
            return NotificationResult(False, self._unavailable_reason)
        if not isinstance(title, str) or not title.strip():
            return NotificationResult(False, "系统通知标题不能为空。")
        if not isinstance(message, str) or not message.strip():
            return NotificationResult(False, "系统通知内容不能为空。")

        has_tray, error = self._capability_value(
            self._system_tray_available, self._tray, "isSystemTrayAvailable"
        )
        if error:
            return NotificationResult(False, error)
        if not has_tray:
            return NotificationResult(False, "当前桌面没有可用的系统托盘，继续使用应用内提醒。")

        supports_messages, error = self._capability_value(
            self._messages_supported, self._tray, "supportsMessages"
        )
        if error:
            return NotificationResult(False, error)
        if not supports_messages:
            return NotificationResult(False, "当前系统托盘不支持消息提示，继续使用应用内提醒。")

        safe_title = self._trim(title, self._max_title_chars)
        safe_message = self._trim(message, self._max_message_chars)
        show_message = getattr(self._tray, "showMessage", None)
        if not callable(show_message):
            return NotificationResult(False, "系统托盘没有提供消息提示接口。")
        try:
            if self._information_icon is None:
                show_message(safe_title, safe_message)
            else:
                show_message(
                    safe_title,
                    safe_message,
                    self._information_icon,
                    self._duration_ms,
                )
        except Exception as exc:
            return NotificationResult(False, f"系统托盘通知发送失败：{exc}")
        return NotificationResult(True)


def create_qt_system_tray_notifier(
    *,
    icon: object | None = None,
    tooltip: str = "FLUKE",
    duration_ms: int = DEFAULT_DURATION_MS,
) -> SystemTrayNotificationAdapter:
    """Create an adapter backed by ``PySide6.QtWidgets.QSystemTrayIcon``.

    The import is lazy, so the reminder and its synthetic tests still work on
    systems where Qt Widgets or a system tray is unavailable. The returned
    adapter owns the tray object for its lifetime. It does not show a dialog or
    test whether Windows actually displays the notification.
    """
    try:
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    except Exception:
        return SystemTrayNotificationAdapter(
            None,
            duration_ms=duration_ms,
            unavailable_reason="PySide6 Qt Widgets 不可用，继续使用应用内提醒。",
        )

    app = QApplication.instance()
    if app is None:
        return SystemTrayNotificationAdapter(
            None,
            duration_ms=duration_ms,
            unavailable_reason="Qt 图形应用尚未初始化，继续使用应用内提醒。",
        )

    try:
        tray_icon = icon if icon is not None else app.windowIcon()
        tray = QSystemTrayIcon(tray_icon)
        tray.setToolTip(tooltip)
        tray.show()
        return SystemTrayNotificationAdapter(
            tray,
            information_icon=QSystemTrayIcon.MessageIcon.Information,
            duration_ms=duration_ms,
            system_tray_available=QSystemTrayIcon.isSystemTrayAvailable,
            messages_supported=QSystemTrayIcon.supportsMessages,
        )
    except Exception as exc:
        return SystemTrayNotificationAdapter(
            None,
            duration_ms=duration_ms,
            unavailable_reason=f"系统托盘通知初始化失败：{exc}",
        )
