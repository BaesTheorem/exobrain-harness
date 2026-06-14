#!/usr/bin/env python3
"""
Rolls the air-log.csv time series (written by awair-co2-watcher.py) up into a
human-readable Air Quality Log note in the Obsidian vault, mirroring the
Energy Log pattern: an AUTO block between markers that MIST owns, leaving any
hand-written notes above/below untouched.

Tracks CO2 and humidity per day: average, peak, and how much of the day each
spent in an uncomfortable range. Run nightly via launchd (or on demand).
"""

import csv
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CSV_FILE = Path(__file__).resolve().parent / "air-log.csv"
NOTE = Path.home() / "Exobrain" / "Areas" / "Health & Fitness" / "Air Quality Log.md"
START = "<!-- AIR:AUTO START -->"
END = "<!-- AIR:AUTO END -->"

CO2_WARN = 1000          # ppm — stuffy/ventilate threshold (matches watcher)
HUMID_HIGH = 60.0        # % RH — mildew-risk threshold
DAYS = 14

NOTE_TEMPLATE = """# Air Quality Log

Awair Element readings (CO2, humidity, PM2.5), logged every 5 min and rolled \
up here daily. Write your own notes above or below the auto block; MIST only \
rewrites between the markers.

{start}
{body}
{end}
"""


def fnum(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def load_rows():
    if not CSV_FILE.exists():
        return []
    with CSV_FILE.open() as f:
        return list(csv.DictReader(f))


def summarize(rows):
    """Group readings by local date → per-day stats."""
    by_day = defaultdict(list)
    for r in rows:
        ts = r.get("timestamp", "")
        if not ts:
            continue
        by_day[ts[:10]].append(r)

    days = {}
    for day, recs in by_day.items():
        co2 = [v for v in (fnum(r.get("co2")) for r in recs) if v is not None]
        hum = [v for v in (fnum(r.get("humid")) for r in recs) if v is not None]
        if not co2:
            continue
        n = len(co2)
        days[day] = {
            "n": n,
            "co2_avg": round(sum(co2) / n),
            "co2_max": round(max(co2)),
            "co2_pct_high": round(100 * sum(c >= CO2_WARN for c in co2) / n),
            "hum_avg": round(sum(hum) / len(hum)) if hum else None,
            "hum_max": round(max(hum)) if hum else None,
            "hum_pct_high": round(100 * sum(h >= HUMID_HIGH for h in hum) / len(hum)) if hum else None,
        }
    return days


def build_body(rows, now_iso):
    days = summarize(rows)
    if not days:
        return "_No readings logged yet. The watcher records every 5 min during 7am-11pm._"

    latest = rows[-1]
    co2 = fnum(latest.get("co2"))
    hum = fnum(latest.get("humid"))
    pm25 = fnum(latest.get("pm25"))
    co2_flag = " ⚠️" if co2 and co2 >= CO2_WARN else ""
    hum_flag = " ⚠️" if hum and hum >= HUMID_HIGH else ""

    lines = ["### Latest reading", ""]
    lines.append(
        f"**CO2 {co2:.0f} ppm{co2_flag}** · **Humidity {hum:.0f}%{hum_flag}** · "
        f"PM2.5 {pm25:.0f} · _{latest.get('timestamp','')}_"
    )
    lines += ["", f"### Daily summary (last {DAYS} days)", ""]
    lines.append("| Date | CO2 avg | CO2 peak | % >1000 | Humid avg | Humid peak | % >60% | n |")
    lines.append("|------|---------|----------|---------|-----------|------------|--------|---|")
    for day in sorted(days, reverse=True)[:DAYS]:
        d = days[day]
        ha = f"{d['hum_avg']}%" if d["hum_avg"] is not None else "-"
        hm = f"{d['hum_max']}%" if d["hum_max"] is not None else "-"
        hp = f"{d['hum_pct_high']}%" if d["hum_pct_high"] is not None else "-"
        lines.append(
            f"| {day} | {d['co2_avg']} | {d['co2_max']} | {d['co2_pct_high']}% | "
            f"{ha} | {hm} | {hp} | {d['n']} |"
        )

    lines += ["", f"_Auto-updated by MIST {now_iso} from awair-rollup._"]
    return "\n".join(lines)


def write_note(body):
    NOTE.parent.mkdir(parents=True, exist_ok=True)
    if NOTE.exists():
        text = NOTE.read_text()
        if START in text and END in text:
            pre = text.split(START)[0]
            post = text.split(END, 1)[1]
            NOTE.write_text(f"{pre}{START}\n{body}\n{END}{post}")
            return
        # note exists but no markers — append a fresh auto block
        NOTE.write_text(f"{text.rstrip()}\n\n{START}\n{body}\n{END}\n")
        return
    NOTE.write_text(NOTE_TEMPLATE.format(start=START, body=body, end=END))


def main():
    rows = load_rows()
    now_iso = datetime.now().isoformat(timespec="minutes")
    write_note(build_body(rows, now_iso))


if __name__ == "__main__":
    main()
