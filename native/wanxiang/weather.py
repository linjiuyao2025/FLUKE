"""Open-Meteo URL construction and response parsing for the daily briefing.

This module deliberately performs no network I/O. Callers can use the URL
builders with Qt's asynchronous network APIs and pass the response body to the
parsers below.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode


GEOCODING_ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"

CURRENT_FIELDS = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "weather_code",
    "wind_speed_10m",
    "is_day",
)
DAILY_FIELDS = (
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_probability_max",
)


class WeatherServiceError(ValueError):
    """An invalid request or unusable Open-Meteo response."""


# Keep the legacy city aliases and candidate order so Chinese city names still
# get a romanized search first, with the original cleaned name as a fallback.
_CITY_ALIASES = {
    "北京": "Beijing",
    "上海": "Shanghai",
    "天津": "Tianjin",
    "重庆": "Chongqing",
    "厦门": "Xiamen",
    "福州": "Fuzhou",
    "泉州": "Quanzhou",
    "广州": "Guangzhou",
    "深圳": "Shenzhen",
    "珠海": "Zhuhai",
    "佛山": "Foshan",
    "东莞": "Dongguan",
    "杭州": "Hangzhou",
    "南京": "Nanjing",
    "苏州": "Suzhou",
    "无锡": "Wuxi",
    "宁波": "Ningbo",
    "温州": "Wenzhou",
    "成都": "Chengdu",
    "武汉": "Wuhan",
    "长沙": "Changsha",
    "西安": "Xi’an",
    "郑州": "Zhengzhou",
    "济南": "Jinan",
    "青岛": "Qingdao",
    "沈阳": "Shenyang",
    "大连": "Dalian",
    "哈尔滨": "Harbin",
    "长春": "Changchun",
    "昆明": "Kunming",
    "贵阳": "Guiyang",
    "南宁": "Nanning",
    "海口": "Haikou",
    "三亚": "Sanya",
    "兰州": "Lanzhou",
    "西宁": "Xining",
    "乌鲁木齐": "Urumqi",
    "呼和浩特": "Hohhot",
    "太原": "Taiyuan",
    "合肥": "Hefei",
    "南昌": "Nanchang",
    "石家庄": "Shijiazhuang",
    "烟台": "Yantai",
    "扬州": "Yangzhou",
    "常州": "Changzhou",
    "南通": "Nantong",
    "义乌": "Yiwu",
    "香港": "Hong Kong",
    "澳门": "Macau",
}

_WEATHER_DESCRIPTIONS = {
    0: ("晴", "☼"),
    1: ("大致晴朗", "☼"),
    2: ("局部多云", "☁"),
    3: ("阴", "☁"),
    45: ("有雾", "≋"),
    48: ("雾凇", "≋"),
    51: ("毛毛雨", "☂"),
    53: ("毛毛雨", "☂"),
    55: ("强毛毛雨", "☂"),
    56: ("冻毛毛雨", "❄"),
    57: ("冻毛毛雨", "❄"),
    61: ("小雨", "☂"),
    63: ("中雨", "☂"),
    65: ("大雨", "☂"),
    66: ("冻雨", "❄"),
    67: ("冻雨", "❄"),
    71: ("小雪", "❄"),
    73: ("中雪", "❄"),
    75: ("大雪", "❄"),
    77: ("雪粒", "❄"),
    80: ("阵雨", "☂"),
    81: ("阵雨", "☂"),
    82: ("强阵雨", "☂"),
    85: ("阵雪", "❄"),
    86: ("强阵雪", "❄"),
    95: ("雷雨", "⚡"),
    96: ("雷雨伴冰雹", "⚡"),
    99: ("强雷雨伴冰雹", "⚡"),
}

# English labels follow the WMO descriptions published by Open-Meteo. Keep this
# separate from the legacy Chinese descriptions so changing the UI language
# never changes the stored city, forecast values, or Chinese-mode wording.
_WEATHER_DESCRIPTIONS_EN = {
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


def city_search_candidates(query: str) -> list[str]:
    """Return legacy-compatible Open-Meteo search candidates for a city name."""
    raw_query = str(query or "").strip()
    cleaned = re.sub(r"^中国\s*", "", raw_query)
    parts = re.split(r"[，,、]", cleaned, maxsplit=1)
    city_part = parts[0].strip()
    qualifier = parts[1].strip() if len(parts) > 1 else ""
    normalized_city = re.sub(r"(?:市|地区|自治州|盟)$", "", city_part).strip()
    alias = _CITY_ALIASES.get(normalized_city) or _CITY_ALIASES.get(city_part)
    candidates: list[str] = []
    if qualifier:
        # Keep the user's region or country qualifier intact. Open-Meteo uses
        # it to narrow same-name places before applying the result limit.
        for candidate in (
            f"{city_part}, {qualifier}",
            f"{alias}, {qualifier}" if alias else "",
        ):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    for candidate in (alias, normalized_city):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def build_geocoding_url(city_name: str) -> str:
    """Build the same Chinese-language geocoding request used by the old UI."""
    name = str(city_name or "").strip()
    if not name:
        raise WeatherServiceError("请输入城市名称。")
    query = urlencode(
        {
            "name": name,
            "count": "10",
            "language": "zh",
            "format": "json",
        }
    )
    return f"{GEOCODING_ENDPOINT}?{query}"


def _coordinate(value: Any, *, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeatherServiceError(f"城市{field}无效，请重新查询城市。")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise WeatherServiceError(f"城市{field}超出有效范围，请重新查询城市。")
    return number


def build_forecast_url(latitude: float, longitude: float) -> str:
    """Build the legacy one-day Celsius/km/h forecast request URL."""
    lat = _coordinate(latitude, field="纬度", minimum=-90, maximum=90)
    lon = _coordinate(longitude, field="经度", minimum=-180, maximum=180)
    query = urlencode(
        {
            "latitude": str(lat),
            "longitude": str(lon),
            "current": ",".join(CURRENT_FIELDS),
            "daily": ",".join(DAILY_FIELDS),
            "forecast_days": "1",
            "timezone": "auto",
        }
    )
    return f"{FORECAST_ENDPOINT}?{query}"


def _response_object(response: Any, *, label: str) -> Mapping[str, Any]:
    if isinstance(response, (str, bytes, bytearray)):
        try:
            if isinstance(response, (bytes, bytearray)):
                response = bytes(response).decode("utf-8")
            response = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise WeatherServiceError(
                f"{label}返回的内容不是有效 JSON，请稍后重试。"
            ) from exc
    if not isinstance(response, Mapping):
        raise WeatherServiceError(f"{label}返回的数据格式无效，请稍后重试。")
    return response


def _required_text(data: Mapping[str, Any], key: str, *, label: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WeatherServiceError(f"{label}缺少有效的 {key} 字段，请重新查询城市。")
    return value.strip()


def parse_geocoding_response(
    response: Any, *, requested_city: str | None = None
) -> dict[str, Any]:
    """Validate geocoding JSON and return the preferred standard city record.

    A mainland-China result is preferred, matching the legacy UI; otherwise
    the first result is used. Returned coordinates are finite and range-checked.
    """
    data = _response_object(response, label="城市查询")
    if "results" not in data:
        raise WeatherServiceError("城市查询结果缺少 results 字段，请稍后重试。")
    results = data["results"]
    if not isinstance(results, list):
        raise WeatherServiceError("城市查询结果格式无效，请稍后重试。")
    if not results:
        city = (requested_city or "").strip()
        if city:
            raise WeatherServiceError(
                f"没有找到“{city}”，请检查城市名称或尝试输入拼音。"
            )
        raise WeatherServiceError("没有找到匹配的城市，请检查城市名称或尝试输入拼音。")

    places = [item for item in results if isinstance(item, Mapping)]
    if not places:
        raise WeatherServiceError("城市查询结果缺少有效地点，请稍后重试。")
    request_parts = re.split(r"[，,、]", str(requested_city or ""), maxsplit=1)
    qualifier = request_parts[1].strip().casefold() if len(request_parts) > 1 else ""
    if qualifier:
        qualified_places = [
            item
            for item in places
            if any(
                isinstance(item.get(field), str)
                and item[field].strip().casefold() == qualifier
                for field in ("admin1", "country", "country_code")
            )
        ]
        if qualified_places:
            places = qualified_places

    place = next(
        (
            item
            for item in places
            if isinstance(item.get("country_code"), str)
            and item["country_code"].upper() == "CN"
        ),
        places[0],
    )

    name = _required_text(place, "name", label="城市查询结果")
    latitude = _coordinate(
        place.get("latitude"), field="纬度", minimum=-90, maximum=90
    )
    longitude = _coordinate(
        place.get("longitude"), field="经度", minimum=-180, maximum=180
    )
    result: dict[str, Any] = {
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
    }
    for optional_field in ("admin1", "country", "country_code", "timezone"):
        value = place.get(optional_field)
        if isinstance(value, str) and value.strip():
            result[optional_field] = value.strip()
    return result


def _required_number(data: Mapping[str, Any], key: str, *, path: str) -> float:
    if key not in data:
        raise WeatherServiceError(f"天气数据缺少 {path}.{key}，请稍后重试。")
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WeatherServiceError(f"天气数据中的 {path}.{key} 无效，请稍后重试。")
    number = float(value)
    if not math.isfinite(number):
        raise WeatherServiceError(f"天气数据中的 {path}.{key} 无效，请稍后重试。")
    return number


def _optional_number(
    data: Mapping[str, Any], key: str, *, path: str, percentage: bool = False
) -> float | None:
    if key not in data or data[key] is None:
        return None
    number = _required_number(data, key, path=path)
    if percentage and not 0 <= number <= 100:
        raise WeatherServiceError(f"天气数据中的 {path}.{key} 超出有效范围。")
    return number


def _first_daily_number(data: Mapping[str, Any], key: str) -> float:
    if key not in data:
        raise WeatherServiceError(f"天气数据缺少 daily.{key}，请稍后重试。")
    values = data[key]
    if not isinstance(values, list) or not values:
        raise WeatherServiceError(f"天气数据中的 daily.{key} 不完整，请稍后重试。")
    return _required_number({key: values[0]}, key, path="daily")


def simplify_forecast_response(response: Any) -> dict[str, Any]:
    """Validate forecast JSON and keep only the fields used by the old UI.

    Humidity, wind, rain probability, and ``is_day`` remain optional just as
    the old UI omitted optional detail labels when the service did not return
    them. Core temperature, apparent temperature, weather code, and today's
    high/low are required so the view cannot render ``NaN`` placeholders.
    """
    data = _response_object(response, label="天气服务")
    current = data.get("current")
    daily = data.get("daily")
    if not isinstance(current, Mapping):
        raise WeatherServiceError("天气数据缺少 current 对象，请稍后重试。")
    if not isinstance(daily, Mapping):
        raise WeatherServiceError("天气数据缺少 daily 对象，请稍后重试。")

    temperature = _required_number(current, "temperature_2m", path="current")
    apparent = _required_number(current, "apparent_temperature", path="current")
    weather_code_value = _required_number(current, "weather_code", path="current")
    if not weather_code_value.is_integer():
        raise WeatherServiceError("天气代码无效，请稍后重试。")
    weather_code = int(weather_code_value)
    description, glyph = _WEATHER_DESCRIPTIONS.get(
        weather_code, ("天气已更新", "")
    )
    description_en = _WEATHER_DESCRIPTIONS_EN.get(weather_code, "Weather updated")

    humidity = _optional_number(
        current, "relative_humidity_2m", path="current", percentage=True
    )
    wind_speed = _optional_number(current, "wind_speed_10m", path="current")
    is_day = current.get("is_day")
    if is_day is not None and (
        isinstance(is_day, bool) or not isinstance(is_day, int) or is_day not in (0, 1)
    ):
        raise WeatherServiceError("天气数据中的 current.is_day 无效，请稍后重试。")

    max_temperature = _first_daily_number(daily, "temperature_2m_max")
    min_temperature = _first_daily_number(daily, "temperature_2m_min")
    rain_probability: float | None = None
    if (
        "precipitation_probability_max" in daily
        and daily["precipitation_probability_max"] is not None
    ):
        values = daily["precipitation_probability_max"]
        if not isinstance(values, list) or not values:
            raise WeatherServiceError(
                "天气数据中的 daily.precipitation_probability_max 不完整，请稍后重试。"
            )
        rain_probability = _required_number(
            {"precipitation_probability_max": values[0]},
            "precipitation_probability_max",
            path="daily",
        )
        if not 0 <= rain_probability <= 100:
            raise WeatherServiceError(
                "天气数据中的 daily.precipitation_probability_max 超出有效范围。"
            )

    return {
        "current": {
            "temperature_2m": temperature,
            "apparent_temperature": apparent,
            "relative_humidity_2m": humidity,
            "weather_code": weather_code,
            "wind_speed_10m": wind_speed,
            "is_day": is_day,
        },
        "daily": {
            "temperature_2m_max": max_temperature,
            "temperature_2m_min": min_temperature,
            "precipitation_probability_max": rain_probability,
        },
        "description": description,
        "description_en": description_en,
        "glyph": glyph,
    }
