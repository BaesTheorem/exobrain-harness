#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["matplotlib>=3.9", "numpy>=1.26"]
# ///
"""Chart the long-run history of one month's average temperature for a US county.

Data comes from NOAA NCEI's Climate at a Glance county time series, which is
built on nClimGrid: a 5km gridded analysis of the GHCN station network, area
averaged over the county. Unlike a single weather station it has no gaps and no
station-move discontinuities, so a 100-year line is actually comparable end to
end.

Defaults to Jackson County, Missouri (Kansas City) in September, 1926-2025.

    ./monthly-temp-history.py
    ./monthly-temp-history.py --county KS-209 --month 7 --start 1900 --end 2025

Writes a light PNG, a dark PNG, and the CSV the chart was drawn from.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
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
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

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


def fetch(county: str, month: int, start: int, end: int, cache: Path) -> dict[int, float]:
    """Pull the county's month-of-year average temperature series, in degrees F."""
    url = f"{CAG}/county/time-series/{county}/tavg/1/{month}/{start}-{end}.json"
    if cache.exists():
        payload = json.loads(cache.read_text())
    else:
        with urllib.request.urlopen(url, timeout=60) as resp:
            payload = json.loads(resp.read())
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(payload))

    if "data" not in payload:
        raise SystemExit(f"NOAA returned no data for {county}. Check the county code.\n{url}")
    series = {int(k[:4]): float(v["value"]) for k, v in payload["data"].items()}
    missing = sorted(set(range(start, end + 1)) - set(series))
    if missing:
        print(f"note: no value for {missing}")
    return dict(sorted(series.items()))


def fit_trend(x: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """OLS trend plus the 95% confidence band on the fitted line.

    A century of one month's temperature is mostly year-to-year noise, so a bare
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


def draw(years, temps, mode, title, subtitle, month_name, out_path):
    c = THEMES[mode]
    x = np.asarray(years, dtype=float)
    y = np.asarray(temps, dtype=float)

    slope, trend, band, slope_ci = fit_trend(x, y)
    mean = y.mean()
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
            label=(f"Linear trend  {slope * 10:+.2f} ± {slope_ci * 10:.2f}°F per decade"
                   "\n(dashed line, 95% band)"))
    ax.plot(x, smooth, color=c["smooth"], linewidth=2.6, zorder=4,
            label="11-year running mean")

    # Direct labels on the three points a reader will look for.
    hot_i, cold_i = int(np.argmax(y)), int(np.argmin(y))
    for i, va, dy in ((hot_i, "bottom", 11), (cold_i, "top", -11), (len(x) - 1, "bottom", 11)):
        ax.plot(x[i], y[i], "o", markersize=8, color=c["annual"],
                markeredgecolor=c["surface"], markeredgewidth=2, zorder=5)
        ax.annotate(
            f"{int(x[i])}  {y[i]:.1f}°F",
            xy=(x[i], y[i]), xytext=(0, dy), textcoords="offset points",
            ha="center", va=va, fontsize=10, color=c["ink"], fontweight="bold",
            zorder=6,
        )

    ax.set_xlim(x[0] - 2, x[-1] + 6)
    ax.set_xticks([yr for yr in range(int(x[0] // 10 * 10) + 10, int(x[-1]) + 1, 10)])
    ax.xaxis.set_major_formatter(lambda v, _: f"{int(v)}")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}°F")
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

    fig.text(
        0.008, 0.015,
        "Source: NOAA NCEI Climate at a Glance, nClimGrid county series (tavg)",
        color=c["muted"], fontsize=8.5,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out_path, facecolor=c["surface"])
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--county", default="MO-095", help="NOAA county code, e.g. MO-095 (Jackson County, MO)")
    p.add_argument("--place", default="Kansas City", help="Human-readable place name for the title")
    p.add_argument("--month", type=int, default=9)
    p.add_argument("--start", type=int, default=1926)
    p.add_argument("--end", type=int, default=2025)
    p.add_argument("--outdir", type=Path, default=Path(__file__).parent / "out")
    args = p.parse_args()

    month_name = MONTHS[args.month - 1]
    stem = f"{args.county}-{args.month:02d}-{args.start}-{args.end}"
    args.outdir.mkdir(parents=True, exist_ok=True)

    series = fetch(args.county, args.month, args.start, args.end,
                   args.outdir / f"{stem}.json")
    years, temps = list(series.keys()), list(series.values())

    csv_path = args.outdir / f"{stem}.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["year", f"{month_name.lower()}_avg_temp_f"])
        w.writerows(zip(years, temps, strict=True))

    # Headline states what the numbers actually show, so it stays honest when
    # the script is pointed at another county or month.
    xa, ya = np.asarray(years, dtype=float), np.asarray(temps, dtype=float)
    slope, _, _, slope_ci = fit_trend(xa, ya)
    spread = max(temps) - min(temps)
    # If the confidence interval straddles zero, the fitted slope is not evidence
    # of a direction and the headline must not imply one.
    finding = (f"{slope * len(years):+.1f}°F of trend" if abs(slope) > slope_ci
               else "no detectable trend")
    title = (f"{len(years)} {month_name}s in {args.place}: {spread:.0f}°F between the "
             f"warmest and the coolest, {finding}")
    subtitle = (f"Average {month_name} temperature, {years[0]}-{years[-1]} · period mean "
                f"{statistics.mean(temps):.1f}°F · NOAA nClimGrid, {args.county}")

    for mode in ("light", "dark"):
        out = args.outdir / f"{stem}-{mode}.png"
        draw(years, temps, mode, title, subtitle, month_name, out)
        print(f"wrote {out}")

    first30 = statistics.mean(temps[:30])
    last30 = statistics.mean(temps[-30:])
    print(f"\n{month_name} average, {years[0]}-{years[-1]}: {ya.mean():.2f}°F")
    verdict = "significant" if abs(slope) > slope_ci else "not distinguishable from zero"
    print(f"  trend           {slope * 10:+.2f} ± {slope_ci * 10:.2f}°F/decade  ({verdict})")
    print(f"  first 30 years  {first30:.2f}°F   last 30 years  {last30:.2f}°F   ({last30 - first30:+.2f})")
    print(f"  warmest         {years[temps.index(max(temps))]}  {max(temps):.1f}°F")
    print(f"  coolest         {years[temps.index(min(temps))]}  {min(temps):.1f}°F")
    print(f"  data            {csv_path}")


if __name__ == "__main__":
    main()
