#!/usr/bin/env python3
"""
Fetch weather data from Open-Meteo for Kansas City.
Outputs JSON to stdout for Claude to parse.

Usage: python3 get-weather.py
"""

import json
import openmeteo_requests

# Kansas City, MO
LAT, LON = 39.10, -94.58

# WMO weather code descriptions
WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers", 85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

om = openmeteo_requests.Client()
params = {
    "latitude": LAT,
    "longitude": LON,
    "current": [
        "temperature_2m", "relative_humidity_2m", "apparent_temperature",
        "precipitation", "weather_code", "wind_speed_10m",
        "wind_direction_10m", "uv_index",
    ],
    "daily": [
        "temperature_2m_max", "temperature_2m_min",
        "precipitation_probability_max", "sunrise", "sunset",
        "uv_index_max", "weather_code",
    ],
    "temperature_unit": "fahrenheit",
    "wind_speed_unit": "mph",
    "precipitation_unit": "inch",
    "timezone": "America/Chicago",
    "forecast_days": 7,
}

response = om.weather_api("https://api.open-meteo.com/v1/forecast", params=params)[0]
current = response.Current()
daily = response.Daily()

result = {
    "location": "Kansas City, MO",
    "current": {
        "temperature_f": round(current.Variables(0).Value()),
        "humidity_pct": round(current.Variables(1).Value()),
        "feels_like_f": round(current.Variables(2).Value()),
        "precipitation_in": round(current.Variables(3).Value(), 2),
        "conditions": WMO_CODES.get(int(current.Variables(4).Value()), "Unknown"),
        "wind_mph": round(current.Variables(5).Value()),
        "wind_direction_deg": round(current.Variables(6).Value()),
        "uv_index": round(current.Variables(7).Value(), 1),
    },
    "daily_forecast": [],
}

import numpy as np
from datetime import datetime, timedelta

base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
for i in range(min(7, len(daily.Variables(0).ValuesAsNumpy()))):
    day_date = base_date + timedelta(days=i)
    result["daily_forecast"].append({
        "date": day_date.strftime("%A, %B %d"),
        "high_f": round(float(daily.Variables(0).ValuesAsNumpy()[i])),
        "low_f": round(float(daily.Variables(1).ValuesAsNumpy()[i])),
        "rain_probability_pct": round(float(daily.Variables(2).ValuesAsNumpy()[i])),
        "uv_index_max": round(float(daily.Variables(5).ValuesAsNumpy()[i]), 1),
        "conditions": WMO_CODES.get(int(daily.Variables(6).ValuesAsNumpy()[i]), "Unknown"),
    })

print(json.dumps(result, indent=2))
