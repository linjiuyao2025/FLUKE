from __future__ import annotations

from enum import Enum
from types import SimpleNamespace
import unittest

from PySide6.QtCore import QCoreApplication

from wanxiang.windows_location import WindowsLocationProvider


class FakeAccessStatus(Enum):
    ALLOWED = 1
    DENIED = 2


class FakeAsyncStatus(Enum):
    COMPLETED = 1
    CANCELED = 2


class FakeAsyncOperation:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.handler = None
        self.cancelled = False

    @property
    def completed(self):
        return self.handler

    @completed.setter
    def completed(self, handler) -> None:
        self.handler = handler

    def get_results(self):
        if self.error is not None:
            raise self.error
        return self.result

    def cancel(self) -> None:
        self.cancelled = True

    def complete(self, status=FakeAsyncStatus.COMPLETED) -> None:
        if self.handler is not None:
            self.handler(self, status)


class FakeLocationProviderBackend:
    def __init__(self, access_status=FakeAccessStatus.ALLOWED) -> None:
        self.access_operation = FakeAsyncOperation(access_status)
        self.position_operation = FakeAsyncOperation()
        self.position_request = None
        self.geolocator_created = 0

    def request_access(self):
        return self.access_operation

    def make_geolocator(self):
        self.geolocator_created += 1
        return self

    def get_geoposition_async_with_age_and_timeout(self, maximum_age, timeout):
        self.position_request = (maximum_age, timeout)
        return self.position_operation


class WindowsLocationProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def make_provider(self, backend):
        provider = WindowsLocationProvider(
            access_requester=backend.request_access,
            geolocator_factory=backend.make_geolocator,
            allowed_status=FakeAccessStatus.ALLOWED,
            completed_status=FakeAsyncStatus.COMPLETED,
        )
        results: list[tuple[int, object]] = []
        progress: list[tuple[int, str]] = []
        provider.finished.connect(lambda request_id, result: results.append((request_id, result)))
        provider.progress.connect(lambda request_id, text: progress.append((request_id, text)))
        return provider, results, progress

    def test_allowed_access_reads_one_cached_or_current_position_asynchronously(self) -> None:
        backend = FakeLocationProviderBackend()
        provider, results, progress = self.make_provider(backend)

        provider.request(7)

        self.assertEqual(results, [])
        self.assertEqual(backend.geolocator_created, 0)
        backend.access_operation.complete()

        self.assertEqual(progress, [(7, "已允许访问，正在获取当前位置……")])
        self.assertEqual(backend.geolocator_created, 1)
        self.assertEqual(backend.position_request[0].total_seconds(), 600)
        self.assertEqual(backend.position_request[1].total_seconds(), 12)
        self.assertEqual(results, [])

        backend.position_operation.result = SimpleNamespace(
            coordinate=SimpleNamespace(
                point=SimpleNamespace(
                    position=SimpleNamespace(latitude=31.234, longitude=121.456)
                )
            )
        )
        backend.position_operation.complete()

        self.assertEqual(results, [(7, {"latitude": 31.234, "longitude": 121.456})])

    def test_denied_access_does_not_read_or_create_geolocator(self) -> None:
        backend = FakeLocationProviderBackend(FakeAccessStatus.DENIED)
        provider, results, _ = self.make_provider(backend)

        provider.request(8)
        backend.access_operation.complete()

        self.assertEqual(backend.geolocator_created, 0)
        self.assertEqual(len(results), 1)
        self.assertIn("未允许", results[0][1]["error"])

    def test_async_failure_is_reported_without_escaping_callback(self) -> None:
        backend = FakeLocationProviderBackend()
        backend.access_operation.error = OSError("synthetic failure")
        provider, results, _ = self.make_provider(backend)

        provider.request(9)
        backend.access_operation.complete()

        self.assertEqual(len(results), 1)
        self.assertIn("Windows 定位服务暂不可用", results[0][1]["error"])

    def test_cancel_ignores_late_completion(self) -> None:
        backend = FakeLocationProviderBackend()
        provider, results, _ = self.make_provider(backend)

        provider.request(10)
        provider.cancel(10)
        backend.access_operation.complete()

        self.assertTrue(backend.access_operation.cancelled)
        self.assertEqual(results, [])

    def test_non_completed_async_status_is_reported(self) -> None:
        backend = FakeLocationProviderBackend()
        provider, results, _ = self.make_provider(backend)

        provider.request(11)
        backend.access_operation.complete(FakeAsyncStatus.CANCELED)

        self.assertEqual(len(results), 1)
        self.assertIn("未能完成", results[0][1]["error"])


if __name__ == "__main__":
    unittest.main()
