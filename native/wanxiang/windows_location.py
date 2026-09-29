"""One-shot Windows location access with an injectable async boundary."""

from __future__ import annotations

from datetime import timedelta
import sys
import weakref

from PySide6.QtCore import QObject, Signal, Slot


class WindowsLocationProvider(QObject):
    """Request Windows consent, then return one location without blocking Qt."""

    progress = Signal(int, str)
    finished = Signal(int, "QVariant")

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        access_requester=None,
        geolocator_factory=None,
        allowed_status=None,
        completed_status=None,
    ) -> None:
        super().__init__(parent)
        self._access_requester = access_requester
        self._geolocator_factory = geolocator_factory
        self._allowed_status = allowed_status
        self._completed_status = completed_status
        self._pending: dict[int, object] = {}
        self._completion_handlers: dict[int, object] = {}

    @Slot(int)
    def request(self, request_id: int) -> None:
        self.cancel(request_id)
        try:
            self._prepare_backend()
            operation = self._access_requester()
            self._pending[request_id] = operation
            self._bind_completion(request_id, operation, "_access_completed")
        except Exception as exc:
            self._finish_error(request_id, self._readable_error(exc))

    @Slot(int)
    def cancel(self, request_id: int) -> None:
        operation = self._pending.pop(request_id, None)
        self._completion_handlers.pop(request_id, None)
        if operation is not None:
            try:
                operation.cancel()
            except Exception:
                pass

    def _prepare_backend(self) -> None:
        if self._access_requester is not None and self._geolocator_factory is not None:
            return
        if sys.platform != "win32":
            raise RuntimeError("Windows 系统定位只在 Windows 桌面版提供。")
        try:
            from winrt.windows.devices.geolocation import (
                Geolocator,
                GeolocationAccessStatus,
            )
            from winrt.windows.foundation import AsyncStatus
        except ImportError as exc:
            raise RuntimeError("Windows 定位组件未安装，请修复或重新安装桌面版。") from exc

        # Qt owns initialization of the Windows GUI thread's STA.
        if self._access_requester is None:
            self._access_requester = Geolocator.request_access_async
        if self._geolocator_factory is None:
            self._geolocator_factory = Geolocator
        if self._allowed_status is None:
            self._allowed_status = GeolocationAccessStatus.ALLOWED
        if self._completed_status is None:
            self._completed_status = AsyncStatus.COMPLETED

    def _bind_completion(self, request_id: int, operation: object, callback_name: str) -> None:
        owner_ref = weakref.ref(self)

        def completed(completed_operation, _status) -> None:
            owner = owner_ref()
            if owner is None or owner._pending.get(request_id) is not completed_operation:
                return
            owner._completion_handlers.pop(request_id, None)
            try:
                if owner._completed_status is not None and _status != owner._completed_status:
                    owner._pending.pop(request_id, None)
                    owner._finish_error(request_id, "Windows 定位请求未能完成，请手动输入城市。")
                    return
                callback = getattr(owner, callback_name)
                callback(request_id, completed_operation)
            except Exception as exc:
                owner._pending.pop(request_id, None)
                owner._finish_error(request_id, owner._readable_error(exc))

        self._completion_handlers[request_id] = completed
        operation.completed = completed

    def _access_completed(self, request_id: int, operation: object) -> None:
        self._pending.pop(request_id, None)
        try:
            access_status = operation.get_results()
        except Exception as exc:
            self._finish_error(request_id, self._readable_error(exc))
            return
        if access_status != self._allowed_status:
            if getattr(access_status, "name", "") == "DENIED":
                self._finish_error(
                    request_id,
                    "Windows 未允许此应用访问位置；可在系统位置设置中开启，或手动输入城市。",
                )
            else:
                self._finish_error(request_id, "Windows 暂未提供位置授权，请手动输入城市。")
            return

        self.progress.emit(request_id, "已允许访问，正在获取当前位置……")
        try:
            locator = self._geolocator_factory()
            operation = locator.get_geoposition_async_with_age_and_timeout(
                timedelta(minutes=10), timedelta(seconds=12)
            )
            self._pending[request_id] = operation
            self._bind_completion(request_id, operation, "_position_completed")
        except Exception as exc:
            self._finish_error(request_id, self._readable_error(exc))

    def _position_completed(self, request_id: int, operation: object) -> None:
        self._pending.pop(request_id, None)
        try:
            position = operation.get_results()
            coordinate = position.coordinate.point.position
            latitude = float(coordinate.latitude)
            longitude = float(coordinate.longitude)
            self.finished.emit(request_id, {
                "latitude": latitude,
                "longitude": longitude,
            })
        except Exception as exc:
            self._finish_error(request_id, self._readable_error(exc))

    def _finish_error(self, request_id: int, message: str) -> None:
        self.finished.emit(request_id, {"error": message})

    @staticmethod
    def _readable_error(error: Exception) -> str:
        message = str(error).strip()
        if "组件未安装" in message or "只在 Windows 桌面版" in message:
            return message
        if "location" in message.lower() or "position" in message.lower():
            return f"获取系统位置失败：{message}"
        return "Windows 定位服务暂不可用，可稍后重试或手动输入城市。"
