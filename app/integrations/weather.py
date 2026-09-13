"""Live weather via Open-Meteo, with a local catalog fallback."""
from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..tools.catalog import WEATHER
from .http import client

_WMO = {
    0: "clear",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "fog",
    51: "drizzle",
    61: "rain",
    63: "rain",
    65: "heavy rain",
    71: "snow",
    80: "rain showers",
    95: "thunderstorm",
}


def get_weather(city: str) -> dict[str, Any]:
    settings = get_settings()
    provider = settings.weather_provider
    if provider == "catalog":
        return _catalog(city)
    if provider in {"auto", "live", "open-meteo"}:
        try:
            return _open_meteo(city)
        except Exception:
            if provider != "auto":
                raise
    return {**_catalog(city), "fallback": True}


def _catalog(city: str) -> dict[str, Any]:
    key = city.strip().lower()
    known = WEATHER.get(key)
    if known:
        return {"city": city, **known, "source": "catalog"}
    seed = sum(ord(c) for c in key) or 1
    return {
        "city": city,
        "temp_c": 10 + seed % 22,
        "condition": ("clear", "clouds", "wind", "haze")[seed % 4],
        "humidity": 40 + seed % 45,
        "source": "generated",
    }


def _open_meteo(city: str) -> dict[str, Any]:
    with client() as http:
        geo = http.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "en", "format": "json"},
        )
        geo.raise_for_status()
        results = (geo.json() or {}).get("results") or []
        if not results:
            raise RuntimeError(f"unknown city: {city}")
        place = results[0]
        forecast = http.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,relative_humidity_2m,weather_code",
            },
        )
        forecast.raise_for_status()
        current = (forecast.json() or {}).get("current") or {}
    code = current.get("weather_code")
    return {
        "city": place.get("name") or city,
        "temp_c": current.get("temperature_2m"),
        "condition": _WMO.get(code, f"code {code}"),
        "humidity": current.get("relative_humidity_2m"),
        "source": "open-meteo",
        "country": place.get("country"),
    }
