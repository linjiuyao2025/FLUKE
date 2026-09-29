from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from typing import Any
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import QCoreApplication, QObject, Signal

from main import WeatherBridge
from wanxiang.database import get_app_setting, set_app_setting

from wanxiang.weather import (
    CURRENT_FIELDS,
    DAILY_FIELDS,
    WeatherServiceError,
    build_forecast_url,
    build_geocoding_url,
    city_search_candidates,
    parse_geocoding_response,
    simplify_forecast_response,
)


class FakeLocationProvider(QObject):
    progress = Signal(int, str)
    finished = Signal(int, "QVariant")

    def __init__(self) -> None:
        super().__init__()
        self.request_ids: list[int] = []
        self.cancelled_ids: list[int] = []

    def request(self, request_id: int) -> None:
        self.request_ids.append(request_id)

    def cancel(self, request_id: int) -> None:
        self.cancelled_ids.append(request_id)


def synthetic_geocoding_response() -> dict[str, Any]:
    return {
        "results": [
            {
                "name": "Synthetic City Abroad",
                "latitude": 7.25,
                "longitude": 13.5,
                "country_code": "JP",
            },
            {
                "name": "合成市",
                "admin1": "合成省",
                "country": "合成国",
                "country_code": "CN",
                "latitude": 12.345,
                "longitude": 67.89,
                "timezone": "Asia/Shanghai",
            },
        ]
    }


def synthetic_forecast_response() -> dict[str, Any]:
    return {
        "current": {
            "temperature_2m": 21.6,
            "apparent_temperature": 22.3,
            "relative_humidity_2m": 67,
            "weather_code": 2,
            "wind_speed_10m": 8.4,
            "is_day": 1,
        },
        "daily": {
            "temperature_2m_max": [25.1],
            "temperature_2m_min": [17.2],
            "precipitation_probability_max": [30],
        },
    }


class WeatherUrlTests(unittest.TestCase):
    def test_city_candidates_normalize_legacy_query_shape(self) -> None:
        self.assertEqual(city_search_candidates("中国 合成市"), ["合成"])
        self.assertEqual(
            city_search_candidates("洛杉矶, California"),
            ["洛杉矶, California"],
        )
        self.assertEqual(
            city_search_candidates("北京, 中国"),
            ["北京, 中国", "Beijing, 中国"],
        )
        self.assertEqual(city_search_candidates("   "), [])

    def test_geocoding_url_uses_legacy_parameters(self) -> None:
        url = build_geocoding_url("合成市")
        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "geocoding-api.open-meteo.com")
        self.assertEqual(
            parse_qs(parsed.query),
            {"name": ["合成市"], "count": ["10"], "language": ["zh"], "format": ["json"]},
        )
        self.assertEqual(
            parse_qs(urlsplit(build_geocoding_url("Springfield, Illinois")).query)["name"],
            ["Springfield, Illinois"],
        )

    def test_forecast_url_requests_legacy_weather_fields(self) -> None:
        parsed = urlsplit(build_forecast_url(12.345, 67.89))
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "api.open-meteo.com")
        self.assertEqual(query["latitude"], ["12.345"])
        self.assertEqual(query["longitude"], ["67.89"])
        self.assertEqual(query["current"], [",".join(CURRENT_FIELDS)])
        self.assertEqual(query["daily"], [",".join(DAILY_FIELDS)])
        self.assertEqual(query["forecast_days"], ["1"])
        self.assertEqual(query["timezone"], ["auto"])

    def test_empty_city_and_out_of_range_coordinates_are_rejected(self) -> None:
        with self.assertRaisesRegex(WeatherServiceError, "请输入城市名称"):
            build_geocoding_url("  ")
        with self.assertRaisesRegex(WeatherServiceError, "超出有效范围"):
            build_forecast_url(91, 0)
        with self.assertRaisesRegex(WeatherServiceError, "超出有效范围"):
            build_forecast_url(0, 181)


class GeocodingResponseTests(unittest.TestCase):
    def test_prefers_cn_and_returns_standard_name_and_coordinates(self) -> None:
        place = parse_geocoding_response(
            synthetic_geocoding_response(), requested_city="合成市"
        )
        self.assertEqual(place["name"], "合成市")
        self.assertEqual(place["latitude"], 12.345)
        self.assertEqual(place["longitude"], 67.89)
        self.assertEqual(place["admin1"], "合成省")
        self.assertEqual(place["country"], "合成国")

    def test_requested_admin_area_wins_over_other_same_name_places(self) -> None:
        payload = {
            "results": [
                {
                    "name": "Springfield",
                    "admin1": "Missouri",
                    "country": "United States",
                    "country_code": "US",
                    "latitude": 37.2,
                    "longitude": -93.3,
                },
                {
                    "name": "Springfield",
                    "admin1": "Illinois",
                    "country": "United States",
                    "country_code": "US",
                    "latitude": 39.8,
                    "longitude": -89.6,
                },
            ]
        }
        place = parse_geocoding_response(
            payload, requested_city="Springfield, Illinois"
        )
        self.assertEqual(place["admin1"], "Illinois")
        self.assertEqual(place["latitude"], 39.8)

    def test_no_results_has_a_readable_chinese_error(self) -> None:
        with self.assertRaisesRegex(WeatherServiceError, "没有找到“无结果城”"):
            parse_geocoding_response({"results": []}, requested_city="无结果城")

    def test_missing_or_malformed_results_are_rejected(self) -> None:
        with self.assertRaisesRegex(WeatherServiceError, "缺少 results"):
            parse_geocoding_response({})
        with self.assertRaisesRegex(WeatherServiceError, "格式无效"):
            parse_geocoding_response({"results": {}})

    def test_invalid_json_and_missing_place_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(WeatherServiceError, "不是有效 JSON"):
            parse_geocoding_response("{broken json")
        with self.assertRaisesRegex(WeatherServiceError, "缺少有效的 name"):
            parse_geocoding_response(
                {"results": [{"latitude": 1.0, "longitude": 2.0}]}
            )

    def test_illegal_coordinates_are_rejected(self) -> None:
        payload = {"results": [{"name": "合成市", "latitude": 91, "longitude": 0}]}
        with self.assertRaisesRegex(WeatherServiceError, "超出有效范围"):
            parse_geocoding_response(payload)


class ForecastResponseTests(unittest.TestCase):
    def test_simplifies_legacy_current_and_daily_fields(self) -> None:
        weather = simplify_forecast_response(synthetic_forecast_response())
        self.assertEqual(
            weather["current"],
            {
                "temperature_2m": 21.6,
                "apparent_temperature": 22.3,
                "relative_humidity_2m": 67.0,
                "weather_code": 2,
                "wind_speed_10m": 8.4,
                "is_day": 1,
            },
        )
        self.assertEqual(
            weather["daily"],
            {
                "temperature_2m_max": 25.1,
                "temperature_2m_min": 17.2,
                "precipitation_probability_max": 30.0,
            },
        )
        self.assertEqual(weather["description"], "局部多云")
        self.assertEqual(weather["description_en"], "Partly cloudy")
        self.assertEqual(weather["glyph"], "☁")

    def test_english_descriptions_cover_all_open_meteo_codes(self) -> None:
        expected_english = {
            0: "Clear sky",
            1: "Mainly clear",
            2: "Partly cloudy",
            3: "Overcast",
            45: "Fog",
            48: "Depositing rime fog",
            51: "Light drizzle",
            53: "Moderate drizzle",
            55: "Dense drizzle",
            56: "Light freezing drizzle",
            57: "Dense freezing drizzle",
            61: "Slight rain",
            63: "Moderate rain",
            65: "Heavy rain",
            66: "Light freezing rain",
            67: "Heavy freezing rain",
            71: "Slight snowfall",
            73: "Moderate snowfall",
            75: "Heavy snowfall",
            77: "Snow grains",
            80: "Slight rain showers",
            81: "Moderate rain showers",
            82: "Violent rain showers",
            85: "Slight snow showers",
            86: "Heavy snow showers",
            95: "Thunderstorm",
            96: "Thunderstorm with slight hail",
            97: "Heavy thunderstorm",
            99: "Thunderstorm with heavy hail",
        }
        for code, expected in expected_english.items():
            with self.subTest(code=code):
                payload = synthetic_forecast_response()
                payload["current"]["weather_code"] = code
                result = simplify_forecast_response(payload)
                self.assertEqual(result["description_en"], expected)

        # Code 97 was not in the legacy Chinese description table. Its English
        # label is supported while the Chinese-mode fallback remains unchanged.
        payload = synthetic_forecast_response()
        payload["current"]["weather_code"] = 97
        result = simplify_forecast_response(payload)
        self.assertEqual(result["description"], "天气已更新")
        self.assertEqual(result["description_en"], "Heavy thunderstorm")

        payload["current"]["weather_code"] = 12345
        result = simplify_forecast_response(payload)
        self.assertEqual(result["description"], "天气已更新")
        self.assertEqual(result["description_en"], "Weather updated")
        self.assertEqual(result["glyph"], "")

    def test_invalid_json_and_missing_core_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(WeatherServiceError, "不是有效 JSON"):
            simplify_forecast_response(b"not json")
        with self.assertRaisesRegex(WeatherServiceError, "缺少 current 对象"):
            simplify_forecast_response({"daily": {}})
        incomplete = synthetic_forecast_response()
        del incomplete["current"]["temperature_2m"]
        with self.assertRaisesRegex(WeatherServiceError, "current.temperature_2m"):
            simplify_forecast_response(incomplete)

    def test_missing_optional_details_are_returned_as_none(self) -> None:
        payload = synthetic_forecast_response()
        payload["current"].pop("relative_humidity_2m")
        payload["current"].pop("wind_speed_10m")
        payload["daily"].pop("precipitation_probability_max")
        result = simplify_forecast_response(payload)
        self.assertIsNone(result["current"]["relative_humidity_2m"])
        self.assertIsNone(result["current"]["wind_speed_10m"])
        self.assertIsNone(result["daily"]["precipitation_probability_max"])

    def test_missing_daily_extrema_and_invalid_values_are_rejected(self) -> None:
        payload = synthetic_forecast_response()
        del payload["daily"]["temperature_2m_min"]
        with self.assertRaisesRegex(WeatherServiceError, "daily.temperature_2m_min"):
            simplify_forecast_response(payload)
        with self.assertRaisesRegex(WeatherServiceError, "有效范围"):
            build_forecast_url(float("nan"), 0)


class WeatherBridgeStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def test_selected_city_is_saved_before_network_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "weather.sqlite3"
            bridge = WeatherBridge(database_path, {})
            # Keep this test offline: stop before issuing a geocoding request.
            bridge._request_geocoding = lambda _query_id: None

            bridge.queryCity("合成市")

            self.assertEqual(
                get_app_setting(database_path, "dailyFlowCity"), "合成市"
            )
            self.assertTrue(bridge.busy)
            self.assertEqual(bridge.city, "合成市")

    def test_failed_new_query_does_not_leave_stale_forecast_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "weather.sqlite3"
            bridge = WeatherBridge(database_path, {})
            bridge._publish(
                condition="晴",
                conditionEnglish="Clear sky",
                temperature=25.0,
                apparentTemperature=26.0,
                highTemperature=28.0,
                lowTemperature=19.0,
                humidity=60.0,
                windSpeed=8.0,
                rainChance=10.0,
                lastUpdated="刚刚更新",
            )
            bridge._request_geocoding = lambda query_id: bridge._fail("模拟城市查询失败。", query_id)

            bridge.queryCity("无结果城")

            self.assertFalse(bridge.busy)
            self.assertEqual(bridge.status, "模拟城市查询失败。")
            self.assertIsNone(bridge.temperature)
            self.assertEqual(bridge.condition, "")
            self.assertEqual(bridge.weather["lastUpdated"], "")

    def test_manual_city_is_reused_after_bridge_restart_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "weather.sqlite3"
            first = WeatherBridge(database_path, {})
            first_requests: list[int] = []
            first._request_geocoding = lambda query_id: first_requests.append(query_id)

            first.queryCity("合成市")

            self.assertEqual(first_requests, [first._query_id])
            self.assertEqual(
                get_app_setting(database_path, "dailyFlowCity"), "合成市"
            )

            restarted = WeatherBridge(database_path, {})
            self.assertEqual(restarted.city, "合成市")
            resumed_requests: list[int] = []
            restarted._request_geocoding = lambda query_id: resumed_requests.append(query_id)

            restarted.querySavedCity()

            self.assertEqual(resumed_requests, [restarted._query_id])
            self.assertEqual(restarted.city, "合成市")
            self.assertEqual(
                get_app_setting(database_path, "dailyFlowCity"), "合成市"
            )

    def test_synthetic_location_is_rounded_saved_and_reused_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "weather.sqlite3"
            provider = FakeLocationProvider()
            bridge = WeatherBridge(database_path, {}, location_provider=provider)
            requests = []
            bridge._request_forecast = lambda _query_id: requests.append(dict(bridge._place or {}))

            bridge.requestLocation()
            self.assertTrue(bridge.locationBusy)
            self.assertEqual(provider.request_ids[-1], bridge._location_request_id)
            provider.finished.emit(provider.request_ids[-1], {
                "latitude": 31.234,
                "longitude": 121.456,
            })

            expected_location = {"latitude": 31.2, "longitude": 121.5}
            self.assertEqual(get_app_setting(database_path, "dailyFlowLocation"), expected_location)
            self.assertEqual(get_app_setting(database_path, "dailyFlowCity"), "")
            self.assertIs(get_app_setting(database_path, "dailyFlowLocationAttempted"), True)
            self.assertFalse(bridge.locationBusy)
            self.assertEqual(requests[-1]["name"], "当前位置")

            restarted = WeatherBridge(database_path, {}, location_provider=FakeLocationProvider())
            restarted_requests = []
            restarted._request_forecast = lambda _query_id: restarted_requests.append(dict(restarted._place or {}))
            restarted.querySavedCity()
            self.assertEqual(restarted_requests[-1]["latitude"], 31.2)
            self.assertEqual(restarted_requests[-1]["longitude"], 121.5)

    def test_permission_failure_falls_back_to_saved_city(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "weather.sqlite3"
            set_app_setting(database_path, "dailyFlowCity", "合成市")
            provider = FakeLocationProvider()
            bridge = WeatherBridge(database_path, {}, location_provider=provider)
            bridge._request_geocoding = lambda _query_id: None

            bridge.requestLocation()
            provider.finished.emit(provider.request_ids[-1], {"error": "模拟权限拒绝。"})

            self.assertFalse(bridge.locationBusy)
            self.assertEqual(bridge.city, "合成市")
            self.assertTrue(bridge.busy)
            self.assertIs(get_app_setting(database_path, "dailyFlowLocationAttempted"), True)
            self.assertEqual(get_app_setting(database_path, "dailyFlowCity"), "合成市")

    def test_location_timeout_cancels_provider_and_keeps_manual_city_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "weather.sqlite3"
            provider = FakeLocationProvider()
            bridge = WeatherBridge(database_path, {}, location_provider=provider)

            bridge.requestLocation()
            request_id = provider.request_ids[-1]
            bridge._location_timed_out()

            self.assertIn(request_id, provider.cancelled_ids)
            self.assertFalse(bridge.locationBusy)
            self.assertIn("超时", bridge.status)
            self.assertIs(get_app_setting(database_path, "dailyFlowLocationAttempted"), True)

    def test_invalid_location_coordinates_are_rejected_before_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "weather.sqlite3"
            provider = FakeLocationProvider()
            bridge = WeatherBridge(database_path, {}, location_provider=provider)
            bridge._request_forecast = lambda _query_id: None

            bridge.requestLocation()
            provider.finished.emit(provider.request_ids[-1], {
                "latitude": 91,
                "longitude": 0,
            })

            self.assertIsNone(get_app_setting(database_path, "dailyFlowLocation"))
            self.assertIn("有效范围", bridge.status)
            self.assertFalse(bridge.locationBusy)


if __name__ == "__main__":
    unittest.main()
