# Weather

Fallback weather script using the Open-Meteo API. The primary weather source is the Weather MCP server; this script exists for cases where the MCP is unavailable.

## Usage

```bash
python3 get-weather.py
```

Outputs JSON to stdout with current conditions and 7-day forecast. Coordinates default to Kansas City, MO — update `LAT, LON` in the script for your location.

## Dependencies

- `openmeteo-requests`
- `openmeteo-sdk`
- `numpy` (transitive, used by openmeteo SDK)
