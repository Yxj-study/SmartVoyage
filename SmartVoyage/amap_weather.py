from __future__ import annotations

import json
import os
import asyncio
import threading
import logging
from datetime import date
from decimal import Decimal
from typing import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from SmartVoyage.coordinator.schemas import TravelPlan, WeatherResult


class WeatherServiceError(RuntimeError):
    """Raised when AMap cannot return an auditable forecast."""


FetchJson = Callable[[str, dict[str, str]], dict]
CallTool = Callable[[str], str]


def _default_fetch_json(path: str, params: dict[str, str]) -> dict:
    url = f"https://restapi.amap.com{path}?{urlencode(params)}"
    request = Request(url, headers={"user-agent": "SmartVoyage/1.0"})
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


class AmapWeatherClient:
    def __init__(self, api_key: str, fetch_json: FetchJson | None = None):
        if not api_key:
            raise WeatherServiceError("高德天气密钥未配置")
        self._api_key = api_key
        self._fetch_json = fetch_json or _default_fetch_json

    @classmethod
    def from_environment(cls) -> "AmapWeatherClient":
        return cls(os.getenv("AMAP_MAPS_API_KEY", ""))

    def query(self, plan: TravelPlan) -> WeatherResult:
        city = plan.destination or plan.departure
        if not city:
            raise WeatherServiceError("天气查询缺少城市")

        geocode = self._fetch_json(
            "/v3/geocode/geo",
            {"key": self._api_key, "address": city, "city": city},
        )
        candidates = geocode.get("geocodes") or []
        if geocode.get("status") != "1" or not candidates:
            raise WeatherServiceError(f"高德未解析到城市：{city}")
        adcode = candidates[0].get("adcode")
        if not adcode:
            raise WeatherServiceError(f"高德未返回城市编码：{city}")

        forecast = self._fetch_json(
            "/v3/weather/weatherInfo",
            {"key": self._api_key, "city": str(adcode), "extensions": "all"},
        )
        forecasts = forecast.get("forecasts") or []
        casts = forecasts[0].get("casts") if forecasts else None
        if forecast.get("status") != "1" or not casts:
            raise WeatherServiceError(f"高德未返回天气预报：{city}")

        target = plan.date.isoformat() if plan.date else date.today().isoformat()
        if plan.weather_days > 1:
            return _weather_from_candidates(
                [(item, str(forecasts[0].get("city") or city)) for item in casts],
                city,
                plan.date,
                plan.weather_days,
            )
        selected = next((item for item in casts if item.get("date") == target), casts[0])
        weather = str(selected.get("dayweather") or selected.get("nightweather") or "未知")
        precipitation = Decimal("1") if any(term in weather for term in ("雨", "雪", "冰雹")) else Decimal("0")
        return WeatherResult(
            city=str(forecasts[0].get("city") or city),
            weather=weather,
            date=selected.get("date"),
            wind_scale=selected.get("daypower"),
            precipitation=precipitation,
            temperature_min=_integer(selected.get("nighttemp")),
            temperature_max=_integer(selected.get("daytemp")),
        )


class AmapMcpWeatherClient:
    """Use the official AMap MCP weather tool configured by the original project."""

    def __init__(self, api_key: str, call_tool: CallTool | None = None):
        if not api_key:
            raise WeatherServiceError("高德 MCP 密钥未配置")
        self._api_key = api_key.strip()
        self._call_tool = call_tool or self._call_official_mcp

    @classmethod
    def from_environment(cls) -> "AmapMcpWeatherClient":
        return cls(os.getenv("AMAP_MAPS_API_KEY", ""))

    def query(self, plan: TravelPlan) -> WeatherResult:
        city = plan.destination or plan.departure
        if not city:
            raise WeatherServiceError("天气查询缺少城市")
        text = self._call_tool(city)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise WeatherServiceError("高德 MCP 返回了非 JSON 天气数据") from exc
        return _weather_from_payload(payload, city, plan.date, plan.weather_days)

    def _call_official_mcp(self, city: str) -> str:
        result: dict[str, object] = {}

        def runner() -> None:
            try:
                result["value"] = asyncio.run(self._call_official_mcp_async(city))
            except BaseException as exc:
                result["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(timeout=20)
        if thread.is_alive():
            raise WeatherServiceError("高德 MCP 天气查询超时")
        if "error" in result:
            raise WeatherServiceError("高德 MCP 天气查询失败") from result["error"]
        return str(result.get("value", ""))

    async def _call_official_mcp_async(self, city: str) -> str:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        # AMap places the credential in the query string, so URL-level INFO logs
        # must stay disabled in the public service.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("mcp.client.streamable_http").setLevel(logging.WARNING)
        url = f"https://mcp.amap.com/mcp?key={self._api_key}"
        async with streamable_http_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.call_tool("maps_weather", {"city": city})
                if response.isError or not response.content:
                    raise WeatherServiceError("高德 MCP maps_weather 调用失败")
                return str(response.content[0].text)


def _weather_from_payload(
    payload,
    requested_city: str,
    requested_date: date | None,
    requested_days: int = 1,
) -> WeatherResult:
    containers = payload if isinstance(payload, list) else [payload]
    candidates: list[tuple[dict, str]] = []

    def visit(value, inherited_city: str = "") -> None:
        if isinstance(value, dict):
            city = str(value.get("city") or inherited_city)
            if any(key in value for key in ("weather", "dayweather", "text_day")):
                candidates.append((value, city))
            for child in value.values():
                visit(child, city)
        elif isinstance(value, list):
            for child in value:
                visit(child, inherited_city)

    visit(containers)
    if not candidates:
        raise WeatherServiceError("高德 MCP 未返回可识别的天气记录")
    return _weather_from_candidates(
        candidates, requested_city, requested_date, requested_days
    )


def _weather_from_candidates(
    candidates: list[tuple[dict, str]],
    requested_city: str,
    requested_date: date | None,
    requested_days: int,
) -> WeatherResult:
    target = requested_date.isoformat() if requested_date else None
    if requested_days > 1:
        dated = [
            (item, city)
            for item, city in candidates
            if item.get("date") and (not target or str(item.get("date")) >= target)
        ]
        dated.sort(key=lambda pair: str(pair[0].get("date")))
        selected_days = dated[:requested_days]
        if not selected_days:
            raise WeatherServiceError("高德 MCP 未返回可识别的逐日天气预报")
        summaries = []
        temperatures_min: list[int] = []
        temperatures_max: list[int] = []
        wind_scales: list[int] = []
        adverse = False
        for item, _city in selected_days:
            weather = str(
                item.get("dayweather")
                or item.get("weather")
                or item.get("text_day")
                or "未知"
            )
            temp_min = _integer(item.get("nighttemp") or item.get("temp_min"))
            temp_max = _integer(item.get("daytemp") or item.get("temp_max"))
            wind_scale = _wind_integer(
                item.get("daypower")
                or item.get("windpower")
                or item.get("wind_scale_day")
            )
            temp_text = (
                f" {temp_min}–{temp_max}℃"
                if temp_min is not None and temp_max is not None
                else ""
            )
            summaries.append(f"{str(item['date'])[5:]} {weather}{temp_text}")
            if temp_min is not None:
                temperatures_min.append(temp_min)
            if temp_max is not None:
                temperatures_max.append(temp_max)
            if wind_scale is not None:
                wind_scales.append(wind_scale)
            adverse = adverse or any(term in weather for term in ("雨", "雪", "冰雹"))
        available = len(selected_days)
        limitation = (
            f"（请求{requested_days}天，当前接口返回{available}天）"
            if available < requested_days
            else ""
        )
        return WeatherResult(
            city=selected_days[0][1] or requested_city,
            weather="；".join(summaries) + limitation,
            date=selected_days[0][0].get("date") or requested_date,
            wind_scale=max(wind_scales) if wind_scales else None,
            precipitation=Decimal("1") if adverse else Decimal("0"),
            temperature_min=min(temperatures_min) if temperatures_min else None,
            temperature_max=max(temperatures_max) if temperatures_max else None,
        )

    selected, city = next(
        ((item, city) for item, city in candidates if target and str(item.get("date")) == target),
        candidates[0],
    )
    weather = str(selected.get("dayweather") or selected.get("weather") or selected.get("text_day") or "未知")
    current_temp = _integer(selected.get("temperature"))
    return WeatherResult(
        city=city or requested_city,
        weather=weather,
        date=selected.get("date") or requested_date,
        wind_scale=selected.get("daypower") or selected.get("windpower") or selected.get("wind_scale_day"),
        precipitation=Decimal("1") if any(term in weather for term in ("雨", "雪", "冰雹")) else Decimal("0"),
        temperature_min=_integer(selected.get("nighttemp") or selected.get("temp_min")) or current_temp,
        temperature_max=_integer(selected.get("daytemp") or selected.get("temp_max")) or current_temp,
    )


def _wind_integer(value) -> int | None:
    if value is None:
        return None
    values = [int(part) for part in __import__("re").findall(r"\d+", str(value))]
    return max(values) if values else None


def _integer(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def unavailable_weather(plan: TravelPlan) -> WeatherResult:
    city = plan.destination or plan.departure or "目的地"
    return WeatherResult(
        city=city,
        weather="实时天气服务暂不可用",
        date=plan.date,
        precipitation=Decimal("1"),
    )


def environment_weather_query(plan: TravelPlan) -> WeatherResult:
    try:
        return AmapMcpWeatherClient.from_environment().query(plan)
    except (WeatherServiceError, OSError, ValueError, json.JSONDecodeError):
        try:
            return AmapWeatherClient.from_environment().query(plan)
        except (WeatherServiceError, OSError, ValueError, json.JSONDecodeError):
            return unavailable_weather(plan)
