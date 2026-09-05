# Weather

Weather script using the Open-Meteo API. Used by the daily-briefing skill to fetch current conditions and forecast. No API key required.

## Usage

```bash
python3 get-weather.py
```

Outputs JSON to stdout with current conditions and 7-day forecast. Coordinates default to Kansas City, MO -- update `LAT, LON` in the script for your location.

## Dependencies

- `openmeteo-requests`
- `openmeteo-sdk`
- `numpy` (transitive, used by openmeteo SDK)

## monthly-temp-history.py

Charts the long-run history of a single month's average temperature for any US
county, from NOAA NCEI Climate at a Glance (the nClimGrid county series). Runs
via `uv` off inline PEP 723 metadata, so there is no venv to manage.

```bash
./monthly-temp-history.py                                    # KC, September, 1926-2025
./monthly-temp-history.py --county KS-209 --month 7 --start 1900
```

County codes are `ST-FIPS3`. Output lands in the gitignored `out/`: a light PNG,
a dark PNG, the source CSV, and the cached NOAA JSON.

Why the county grid instead of a single station: the Kansas City Downtown Airport
record (GHCN `USW00013988`) starts in 1934 and is missing 1973-78 and 1994. The
gridded county series is gap-free back to 1895 and free of station-move
discontinuities. Over their 85 overlapping Septembers the two correlate at
r = 0.97, with the airport running 2.4 degrees F warmer -- an urban site effect,
not a disagreement about the climate.
