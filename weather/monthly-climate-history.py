#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.9", "numpy>=1.26"]
# ///
"""Chart the long-run history of one month's climate for a place, one variable at a time.

Two sources, because no single one covers everything:

  tavg      NOAA NCEI Climate at a Glance, nClimGrid county series. A 5km gridded
            analysis of the GHCN station network, area averaged over a county.
            Gap-free to 1895 and free of station-move discontinuities.
  dewpoint  ERA5 reanalysis via the Open-Meteo archive. Starts 1940. nClimGrid
  humidity  carries no moisture variables at all, so there is no county-grid
            equivalent and no way to push a humidity series back to the 1920s.

Defaults to Jackson County, Missouri (Kansas City).

    ./monthly-climate-history.py                                   # September temperature
    ./monthly-climate-history.py --variable humidity --month 8
    ./monthly-climate-history.py --county KS-209 --month 7 --start 1900

Writes a light PNG, a dark PNG, and the CSV the chart was drawn from.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import urllib.parse
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

# Stay in the system sans, per the house palette.
# clean bold weight; keep the stack short so rendering is reproducible.
plt.rcParams["font.family"] = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]

CAG = "https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance"
ERA5 = "https://archive-api.open-meteo.com/v1/archive"
ERA5_FIRST_YEAR = 1940
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

VARIABLES = {
    "tavg": {
        "source": "county",
        "noun": "temperature",
        "unit": "°F",
        "delta_unit": "°F",
        "spread": "between the warmest and the coolest",
        "first_year": 1895,
        "credit": "NOAA NCEI Climate at a Glance, nClimGrid county series (tavg)",
    },
    "dewpoint": {
        "source": "era5",
        "era5_field": "dew_point_2m_mean",
        "noun": "mean dew point",
        "unit": "°F",
        "delta_unit": "°F",
        "spread": "between the muggiest and the driest",
        "first_year": ERA5_FIRST_YEAR,
        "credit": "ERA5 reanalysis via the Open-Meteo archive (dew_point_2m_mean)",
    },
    "humidity": {
        "source": "era5",
        "era5_field": "relative_humidity_2m_mean",
        "noun": "mean relative humidity",
        "unit": "%",
        "delta_unit": " points",
        "spread": "between the muggiest and the driest",
        "first_year": ERA5_FIRST_YEAR,
        "credit": "ERA5 reanalysis via the Open-Meteo archive (relative_humidity_2m_mean)",
    },
}

# Palette roles, per the house dataviz palette. Dark mode is its own selected
# set of steps from the same ramps, not an inversion of the light one.
THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0b0b0b",
        "secondary": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "annual": "#2a78d6",   # categorical slot 1, blue
        "smooth": "#184f95",   # same ramp, step 600
        "trend": "#eb6834",    # categorical slot 2, orange
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#ffffff",
        "secondary": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        # On the dark surface the emphasis inverts: the brighter blue carries the
        # smoothed signal. Both steps validate in-band against #1a1a19.
        "annual": "#256abf",
        "smooth": "#3987e5",
        "trend": "#d95926",
    },
}


def _cached_json(url: str, cache: Path) -> dict:
    if cache.exists():
        return json.loads(cache.read_text())
    with urllib.request.urlopen(url, timeout=180) as resp:
        payload = json.loads(resp.read())
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload))
    return payload


def fetch_county(county: str, month: int, start: int, end: int, cache: Path) -> dict[int, float]:
    """The county's month-of-year average temperature, in degrees F."""
    url = f"{CAG}/county/time-series/{county}/tavg/1/{month}/{start}-{end}.json"
    payload = _cached_json(url, cache)
    if "data" not in payload:
        raise SystemExit(f"NOAA returned no data for {county}. Check the county code.\n{url}")
    return {int(k[:4]): float(v["value"]) for k, v in payload["data"].items()}


def fetch_era5(field: str, lat: float, lon: float, month: int,
               start: int, end: int, cache: Path) -> dict[int, float]:
    """Monthly mean of an ERA5 daily field, averaged over the month's days.

    Open-Meteo has no month-of-year endpoint, so this pulls the whole daily
    series once (cached) and aggregates locally.
    """
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "start_date": f"{start}-01-01", "end_date": f"{end}-12-31",
        "daily": field, "temperature_unit": "fahrenheit",
        "timezone": "America/Chicago",
    })
    payload = _cached_json(f"{ERA5}?{q}", cache)
    if "daily" not in payload:
        raise SystemExit(f"Open-Meteo returned no data: {payload.get('reason', payload)}")

    daily = payload["daily"]
    buckets: dict[int, list[float]] = {}
    for stamp, value in zip(daily["time"], daily[field], strict=True):
        if stamp[5:7] == f"{month:02d}" and value is not None:
            buckets.setdefault(int(stamp[:4]), []).append(float(value))

    # A month cut short by the end of the archive would sit on the chart as a
    # real value while being an average of a different thing. Drop it.
    expected = max(len(v) for v in buckets.values())
    partial = sorted(y for y, v in buckets.items() if len(v) < expected)
    if partial:
        print(f"note: dropping {partial} (incomplete month in the archive)")
    return {y: float(np.mean(v)) for y, v in buckets.items() if len(v) == expected}


def fit_trend(x: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray, np.ndarray, float]:
    """OLS trend plus the 95% confidence band on the fitted line.

    A century of one month's weather is mostly year-to-year noise, so a bare
    slope invites a reader to see a trend that the data cannot support. The band
    is what makes "this could be flat" visible.
    """
    (slope, intercept), cov = np.polyfit(x, y, 1, cov=True)
    line = slope * x + intercept
    resid = y - line
    s_err = np.sqrt((resid**2).sum() / (len(x) - 2))
    sxx = ((x - x.mean()) ** 2).sum()
    # t(0.975) at ~100 points; 1.98 rather than the normal 1.96
    band = 1.98 * s_err * np.sqrt(1 / len(x) + (x - x.mean()) ** 2 / sxx)
    return slope, line, band, 1.98 * np.sqrt(cov[0, 0])


def centered_rolling(values: np.ndarray, window: int) -> np.ndarray:
    """Centered rolling mean, NaN where the full window doesn't fit."""
    out = np.full(values.shape, np.nan)
    half = window // 2
    for i in range(half, len(values) - half):
        out[i] = values[i - half : i + half + 1].mean()
    return out


def draw(years, values, mode, title, subtitle, month_name, var, out_path):
    c = THEMES[mode]
    unit, delta = var["unit"], var["delta_unit"]
    x = np.asarray(years, dtype=float)
    y = np.asarray(values, dtype=float)

    slope, trend, band, slope_ci = fit_trend(x, y)
    smooth = centered_rolling(y, 11)

    fig, ax = plt.subplots(figsize=(11, 6.2), dpi=200)
    fig.patch.set_facecolor(c["surface"])
    ax.set_facecolor(c["surface"])

    # Recessive chrome: horizontal hairlines only, no box.
    ax.grid(axis="y", color=c["grid"], linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(c["axis"])
    ax.spines["bottom"].set_linewidth(1.0)
    ax.tick_params(colors=c["muted"], labelsize=10, length=0, pad=8)

    ax.plot(x, y, color=c["annual"], linewidth=1.3, alpha=0.75, zorder=2,
            label=f"{month_name} average, single year")
    ax.fill_between(x, trend - band, trend + band, color=c["trend"], alpha=0.16,
                    linewidth=0, zorder=1)
    ax.plot(x, trend, color=c["trend"], linewidth=1.8, linestyle=(0, (5, 3)), zorder=3,
            label=(f"Linear trend  {slope * 10:+.2f} ± {slope_ci * 10:.2f}{delta} per decade"
                   "\n(dashed line, 95% band)"))
    ax.plot(x, smooth, color=c["smooth"], linewidth=2.6, zorder=4,
            label="11-year running mean")

    # Direct labels on the three points a reader will look for.
    hi, lo = int(np.argmax(y)), int(np.argmin(y))
    for i, va, dy in ((hi, "bottom", 11), (lo, "top", -11), (len(x) - 1, "bottom", 11)):
        ax.plot(x[i], y[i], "o", markersize=8, color=c["annual"],
                markeredgecolor=c["surface"], markeredgewidth=2, zorder=5)
        ax.annotate(
            f"{int(x[i])}  {y[i]:.1f}{unit}",
            xy=(x[i], y[i]), xytext=(0, dy), textcoords="offset points",
            ha="center", va=va, fontsize=10, color=c["ink"], fontweight="bold",
            zorder=6,
        )

    ax.set_xlim(x[0] - 2, x[-1] + 6)
    ax.set_xticks([yr for yr in range(int(x[0] // 10 * 10) + 10, int(x[-1]) + 1, 10)])
    ax.xaxis.set_major_formatter(lambda v, _: f"{int(v)}")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}{unit}")
    ax.set_xlabel("")

    ax.set_title(title, color=c["ink"], fontsize=16 if len(title) <= 90 else 14,
                 fontweight="bold", loc="left", pad=26)
    ax.annotate(
        subtitle, xy=(0, 1), xycoords="axes fraction", xytext=(0, 12),
        textcoords="offset points", color=c["secondary"], fontsize=10.5, va="bottom",
    )

    legend = ax.legend(
        loc="lower right", frameon=False, fontsize=10, handlelength=2.4,
        labelcolor=c["secondary"], borderpad=0, labelspacing=0.6,
    )
    legend.set_zorder(7)

    fig.text(0.008, 0.015, f"Source: {var['credit']}", color=c["muted"], fontsize=8.5)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out_path, facecolor=c["surface"])
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--variable", default="tavg", choices=sorted(VARIABLES),
                   help="tavg (NOAA county grid) or dewpoint / humidity (ERA5)")
    p.add_argument("--county", default="MO-095", help="NOAA county code, e.g. MO-095 (Jackson County, MO)")
    p.add_argument("--lat", type=float, default=39.0997, help="ERA5 point latitude")
    p.add_argument("--lon", type=float, default=-94.5786, help="ERA5 point longitude")
    p.add_argument("--place", default="Kansas City", help="Human-readable place name for the title")
    p.add_argument("--month", type=int, default=9)
    p.add_argument("--start", type=int, help="defaults to 1926 for tavg, 1940 for ERA5 variables")
    p.add_argument("--end", type=int, default=2025)
    p.add_argument("--outdir", type=Path, default=Path(__file__).parent / "out")
    args = p.parse_args()

    var = VARIABLES[args.variable]
    start = args.start if args.start is not None else max(1926, var["first_year"])
    if start < var["first_year"]:
        raise SystemExit(f"{args.variable} data begins in {var['first_year']}; "
                         f"--start {start} is out of range.")

    month_name = MONTHS[args.month - 1]
    if var["source"] == "county":
        where = f"NOAA nClimGrid, {args.county}"
    else:
        ns, ew = "NS"[args.lat < 0], "EW"[args.lon < 0]
        where = f"ERA5 grid point {abs(args.lat):.2f}°{ns} {abs(args.lon):.2f}°{ew}"
    stem = f"{args.county}-{args.variable}-{args.month:02d}-{start}-{args.end}"
    args.outdir.mkdir(parents=True, exist_ok=True)

    if var["source"] == "county":
        series = fetch_county(args.county, args.month, start, args.end,
                              args.outdir / f"{stem}.json")
    else:
        series = fetch_era5(var["era5_field"], args.lat, args.lon, args.month,
                            start, args.end,
                            args.outdir / f"era5-{var['era5_field']}-{args.lat}-{args.lon}"
                                          f"-{start}-{args.end}.json")

    series = {y: v for y, v in sorted(series.items()) if start <= y <= args.end}
    gaps = sorted(set(range(start, args.end + 1)) - set(series))
    if gaps:
        print(f"note: no value for {gaps}")
    years, values = list(series.keys()), list(series.values())

    csv_path = args.outdir / f"{stem}.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["year", f"{month_name.lower()}_{args.variable}"])
        w.writerows(zip(years, values, strict=True))

    # Headline states what the numbers actually show, so it stays honest when
    # the script is pointed at another place, month, or variable.
    xa, ya = np.asarray(years, dtype=float), np.asarray(values, dtype=float)
    slope, _, _, slope_ci = fit_trend(xa, ya)
    unit, delta = var["unit"], var["delta_unit"]
    spread = max(values) - min(values)
    # If the confidence interval straddles zero, the fitted slope is not evidence
    # of a direction and the headline must not imply one.
    finding = (f"{slope * len(years):+.1f}{delta} of trend" if abs(slope) > slope_ci
               else "no detectable trend")
    title = (f"{len(years)} {month_name}s in {args.place}: {spread:.0f}{delta} "
             f"{var['spread']}, {finding}")
    subtitle = (f"{month_name} {var['noun']}, {years[0]}-{years[-1]} · period mean "
                f"{statistics.mean(values):.1f}{unit} · {where}")

    for mode in ("light", "dark"):
        out = args.outdir / f"{stem}-{mode}.png"
        draw(years, values, mode, title, subtitle, month_name, var, out)
        print(f"wrote {out}")

    n = min(30, len(values) // 2)
    verdict = "significant" if abs(slope) > slope_ci else "not distinguishable from zero"
    print(f"\n{month_name} {var['noun']}, {years[0]}-{years[-1]}: {ya.mean():.2f}{unit}")
    print(f"  trend           {slope * 10:+.2f} ± {slope_ci * 10:.2f}{delta}/decade  ({verdict})")
    print(f"  first {n} years  {statistics.mean(values[:n]):.2f}{unit}   "
          f"last {n} years  {statistics.mean(values[-n:]):.2f}{unit}   "
          f"({statistics.mean(values[-n:]) - statistics.mean(values[:n]):+.2f})")
    print(f"  highest         {years[values.index(max(values))]}  {max(values):.1f}{unit}")
    print(f"  lowest          {years[values.index(min(values))]}  {min(values):.1f}{unit}")
    print(f"  data            {csv_path}")


if __name__ == "__main__":
    main()
