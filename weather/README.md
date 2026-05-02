# Weather

Weather script using the Open-Meteo API. Used by the daily-briefing skill to fetch current conditions and forecast. No API key required.

## Usage

```bash
python3 get-weather.py
```

Outputs JSON to stdout with current conditions and 7-day forecast. Coordinates default to Kansas City, MO — update `LAT, LON` in the script for your location.

## Dependencies

- `openmeteo-requests`
- `openmeteo-sdk`
- `numpy` (transitive, used by openmeteo SDK)
