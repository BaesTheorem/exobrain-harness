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

## monthly-climate-history.py

Charts the long-run history of one month's climate for a place, one variable at a
time. Runs via `uv` off inline PEP 723 metadata, so there is no venv to manage.

```bash
./monthly-climate-history.py                                   # KC, September temperature
./monthly-climate-history.py --variable humidity --month 8
./monthly-climate-history.py --county KS-209 --month 7 --start 1900
```

Output lands in the gitignored `out/`: a light PNG, a dark PNG, the source CSV,
and the cached upstream JSON.

### Variables and why there are two sources

| `--variable` | Source | Starts | Unit |
|---|---|---|---|
| `tavg` | NOAA NCEI Climate at a Glance, nClimGrid county series | 1895 | °F |
| `dewpoint` | ERA5 reanalysis via the Open-Meteo archive | 1940 | °F |
| `humidity` | ERA5, relative humidity | 1940 | % |

nClimGrid carries temperature, precipitation, and drought indices only. It has no
moisture variables, so there is no county-grid humidity series and no way to push
humidity back past ERA5's 1940 start. The two sources are not interchangeable:
`tavg` is a county area average, ERA5 is a single grid point.

Why the county grid rather than a single station for temperature: the Kansas City
Downtown Airport record (GHCN `USW00013988`) starts in 1934 and is missing
1973-78 and 1994. The gridded series is gap-free back to 1895 and free of
station-move discontinuities. Over their 85 overlapping Septembers the two
correlate at r = 0.97, with the airport running 2.4 degrees F warmer, an urban
site effect rather than a disagreement about the climate.

ERA5 was checked the same way against MCI station dew point observations (GSOD,
1973-2024): r = 0.89, ERA5 running 0.8 degrees F low, and the two trends agreeing
to within 0.07 degrees F per decade.

### Reading the chart

The trend line carries a 95% confidence band, and the headline refuses to name a
direction when that interval straddles zero. Kansas City's August and September
temperatures both land there: the fitted slopes are around 0.07 degrees F per
decade in opposite directions, neither distinguishable from noise. August
humidity does not: +1.0 points per decade, comfortably clear of zero.
