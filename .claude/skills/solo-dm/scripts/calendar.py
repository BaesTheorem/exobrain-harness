#!/usr/bin/env python3
"""Harptos calendar tracking for solo-dm.

The Forgotten Realms calendar: 12 months of 30 days (3 tendays each) + 5
festivals. Date is stored in world_state as a JSON blob under key
"in_game_date" so it's the canonical source of truth across sessions.
Crafting, travel, spell scribing all advance time through this file.

    calendar.py show     --slug <s>                  # prints current date
    calendar.py set      --slug <s> --date '1491 DR, 15 Flamerule, morning'
    calendar.py advance  --slug <s> --days N [--to morning|midday|afternoon|evening|night]
    calendar.py advance  --slug <s> --hours N
    calendar.py tendays  --slug <s>                  # prints current tenday
    calendar.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

HARNESS_ROOT = Path("/Users/alexhedtke/Documents/Exobrain harness")
DATA_ROOT = HARNESS_ROOT / "data/solo-dm"

MONTHS = [
    ("Hammer",    "Deepwinter"),
    ("Alturiak",  "Claw of Winter"),
    ("Ches",      "Claw of the Sunsets"),
    ("Tarsakh",   "Claw of the Storms"),
    ("Mirtul",    "The Melting"),
    ("Kythorn",   "Time of Flowers"),
    ("Flamerule", "Summertide"),
    ("Eleasis",   "Highsun"),
    ("Eleint",    "The Fading"),
    ("Marpenoth", "Leaffall"),
    ("Uktar",     "The Rotting"),
    ("Nightal",   "Drawing Down"),
]
MONTH_BY_NAME = {m.lower(): i for i, (m, _) in enumerate(MONTHS)}

# Festivals sit between specific months. Ordered by day_of_year position.
#  day_of_year 31  = Midwinter          (after Hammer)
#  day_of_year 122 = Greengrass         (after Tarsakh, before Mirtul)
#  day_of_year 213 = Midsummer          (after Flamerule)
#  day_of_year 274 = Highharvestide     (after Eleint)
#  day_of_year 335 = Feast of the Moon  (after Uktar)
FESTIVALS = [
    (31,  "Midwinter"),
    (122, "Greengrass"),
    (213, "Midsummer"),
    (274, "Highharvestide"),
    (335, "Feast of the Moon"),
]
FESTIVAL_DAYS = {d: n for d, n in FESTIVALS}

TIMES_OF_DAY = ["dawn", "morning", "midday", "afternoon", "evening", "night", "midnight"]


def day_of_year(month_idx: int, day: int) -> int:
    """1-indexed day of the year given a (0-indexed month, 1-indexed day-in-month).
    Accounts for festivals sitting between months."""
    total = 0
    for i in range(month_idx):
        total += 30
        # festival AFTER this month?
        if (total + 1) in FESTIVAL_DAYS:
            total += 1
    return total + day


def parse_date_str(s: str) -> dict:
    """Parse strings like '1491 DR, 15 Flamerule, morning' or 'Midsummer 1491 DR'."""
    year_match = re.search(r"(\d{3,4})\s*DR", s, re.I)
    year = int(year_match.group(1)) if year_match else 1491
    s = re.sub(r"\d{3,4}\s*DR\s*,?", "", s, flags=re.I).strip(" ,")

    time = "morning"
    for t in TIMES_OF_DAY:
        if re.search(rf"\b{t}\b", s, re.I):
            time = t
            s = re.sub(rf",?\s*\b{t}\b", "", s, flags=re.I).strip()
            break

    # festival?
    for fest_day, fest_name in FESTIVALS:
        if fest_name.lower() in s.lower():
            return {"year": year, "day_of_year": fest_day, "time": time,
                    "is_festival": True, "festival": fest_name}

    # month + day
    m = re.match(r"(\d{1,2})\s+(\w+)", s.strip(", "))
    if not m:
        m = re.match(r"(\w+)\s+(\d{1,2})", s.strip(", "))
        if not m:
            sys.exit(f"can't parse date: {s!r}")
        month_name, day = m.group(1), int(m.group(2))
    else:
        day, month_name = int(m.group(1)), m.group(2)
    if month_name.lower() not in MONTH_BY_NAME:
        sys.exit(f"unknown month: {month_name!r}")
    month_idx = MONTH_BY_NAME[month_name.lower()]
    return {"year": year, "day_of_year": day_of_year(month_idx, day), "time": time,
            "is_festival": False, "festival": None}


def format_date(state: dict) -> str:
    year = state["year"]
    doy = state["day_of_year"]
    time = state.get("time", "morning")
    if doy in FESTIVAL_DAYS:
        return f"{FESTIVAL_DAYS[doy]} {year} DR, {time}"
    # walk through months + festivals
    walk = 0
    for m_idx, (name, _) in enumerate(MONTHS):
        block_start = walk + 1
        block_end = walk + 30
        if block_start <= doy <= block_end:
            day_in_month = doy - walk
            tenday_no = (day_in_month - 1) // 10 + 1
            return f"{day_in_month} {name} {year} DR, {time} (tenday {tenday_no})"
        walk += 30
        # festival after this month?
        if (walk + 1) in FESTIVAL_DAYS:
            walk += 1
    return f"day {doy} of {year} DR (overflow)"


def days_in_year(year: int) -> int:
    return 366 if year % 4 == 0 else 365


def advance(state: dict, days: int = 0, hours: int = 0,
            to_time: str | None = None) -> dict:
    doy = state["day_of_year"]
    year = state["year"]
    time = state.get("time", "morning")
    # hour math: 6 time slots (dawn, morning, midday, afternoon, evening, night);
    # treat each as 4 hours. Rough but good enough for crafting bookkeeping.
    if hours:
        slot_hours = 4
        cur_slot = TIMES_OF_DAY.index(time)
        total_slots = cur_slot + (hours // slot_hours)
        days += total_slots // 6
        new_slot = total_slots % 6
        time = TIMES_OF_DAY[new_slot]
    doy += days
    while doy > days_in_year(year):
        doy -= days_in_year(year)
        year += 1
    if to_time:
        if to_time not in TIMES_OF_DAY:
            sys.exit(f"bad time: {to_time}. Use one of {TIMES_OF_DAY}")
        time = to_time
    return {"year": year, "day_of_year": doy, "time": time,
            "is_festival": doy in FESTIVAL_DAYS,
            "festival": FESTIVAL_DAYS.get(doy)}


def _conn(slug: str) -> sqlite3.Connection:
    db = DATA_ROOT / slug / "state.sqlite"
    if not db.exists():
        sys.exit(f"no db for {slug!r}")
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c


def _load(c: sqlite3.Connection) -> dict:
    row = c.execute(
        "SELECT value FROM world_state WHERE key='in_game_date' LIMIT 1"
    ).fetchone()
    if row is None:
        sys.exit("no in_game_date in world_state — run 'calendar.py set' first")
    return json.loads(row["value"])


def _save(c: sqlite3.Connection, state: dict) -> None:
    campaign = c.execute("SELECT id FROM campaigns LIMIT 1").fetchone()
    cid = campaign["id"]
    c.execute(
        "INSERT INTO world_state (campaign_id, key, value) VALUES (?,?,?) "
        "ON CONFLICT(campaign_id, key) DO UPDATE SET value=excluded.value, "
        "updated_at=datetime('now')",
        (cid, "in_game_date", json.dumps(state)),
    )
    # log as event
    session = c.execute(
        "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if session:
        c.execute(
            "INSERT INTO events (session_id, type, data_json) VALUES (?,?,?)",
            (session["id"], "note",
             json.dumps({"flag": "date_updated", "to": format_date(state)})),
        )
    c.commit()


def cmd_show(slug: str) -> None:
    state = _load(_conn(slug))
    print(format_date(state))


def cmd_set(slug: str, date_str: str) -> None:
    c = _conn(slug)
    state = parse_date_str(date_str)
    _save(c, state)
    print(format_date(state))


def cmd_advance(slug: str, days: int, hours: int, to_time: str | None) -> None:
    c = _conn(slug)
    state = _load(c)
    new = advance(state, days=days, hours=hours, to_time=to_time)
    _save(c, new)
    print(f"{format_date(state)}  ->  {format_date(new)}")


def cmd_tendays(slug: str) -> None:
    state = _load(_conn(slug))
    doy = state["day_of_year"]
    if doy in FESTIVAL_DAYS:
        print(f"Festival day ({FESTIVAL_DAYS[doy]}) — no tenday")
        return
    walk = 0
    for name, alt in MONTHS:
        if walk + 1 <= doy <= walk + 30:
            day_in_month = doy - walk
            tenday = (day_in_month - 1) // 10 + 1
            print(f"{name} ({alt}), tenday {tenday} of 3 — day {day_in_month} of 30")
            return
        walk += 30
        if (walk + 1) in FESTIVAL_DAYS:
            walk += 1


def selftest() -> None:
    # Parse and format round-trip.
    s1 = parse_date_str("1491 DR, 15 Flamerule, morning")
    assert s1["year"] == 1491 and s1["time"] == "morning"
    # Flamerule is month index 6; day_of_year = 6*30 + 2 festivals passed (Midwinter, Greengrass) + 15
    # = 180 + 2 + 15 = 197
    assert s1["day_of_year"] == 197, f"got {s1['day_of_year']}"
    # Format back
    out = format_date(s1)
    assert "15 Flamerule 1491 DR" in out, out

    # Advance 1 tenday
    s2 = advance(s1, days=10)
    assert s2["day_of_year"] == 207
    assert "25 Flamerule" in format_date(s2), format_date(s2)

    # Advance past Midsummer festival (day 213): 197 + 20 = 217 → 4 Eleasis
    s3 = advance(s1, days=20)
    assert format_date(s3).startswith("4 Eleasis"), format_date(s3)

    # Advance across year boundary
    s_end = {"year": 1491, "day_of_year": 365, "time": "night"}
    s_next = advance(s_end, days=1)
    assert s_next["year"] == 1492 and s_next["day_of_year"] == 1

    # Hour advance
    s_hours = advance({"year": 1491, "day_of_year": 100, "time": "morning"}, hours=24)
    # morning (slot 1) + 24/4 = 6 slots → next day's slot 1 = morning
    assert s_hours["day_of_year"] == 101 and s_hours["time"] == "morning"

    # Festival
    s_fest = parse_date_str("Midsummer 1491 DR")
    assert s_fest["day_of_year"] == 213 and s_fest["festival"] == "Midsummer"

    print("calendar.py selftest: OK")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("show"); s.add_argument("--slug", required=True)
    s = sub.add_parser("set"); s.add_argument("--slug", required=True); s.add_argument("--date", required=True)
    s = sub.add_parser("advance"); s.add_argument("--slug", required=True)
    s.add_argument("--days", type=int, default=0); s.add_argument("--hours", type=int, default=0)
    s.add_argument("--to", dest="to_time", choices=TIMES_OF_DAY)
    s = sub.add_parser("tendays"); s.add_argument("--slug", required=True)
    sub.add_parser("selftest")

    args = p.parse_args()
    if args.cmd == "show":
        cmd_show(args.slug)
    elif args.cmd == "set":
        cmd_set(args.slug, args.date)
    elif args.cmd == "advance":
        cmd_advance(args.slug, args.days, args.hours, args.to_time)
    elif args.cmd == "tendays":
        cmd_tendays(args.slug)
    elif args.cmd == "selftest":
        selftest()


if __name__ == "__main__":
    main()
