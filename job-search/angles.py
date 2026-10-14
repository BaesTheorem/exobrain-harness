#!/usr/bin/env python3
"""Keyword rotation for the daily /job-search scan.

Before 2026-10-13 the scan model chose its own search keywords ("angles") each
morning. Nothing guaranteed coverage: on 10/13 Indeed ran one angle, and GRC,
IT auditor and help desk titles did not appear in two days of runs. This
script makes the choice mechanical.

Two pools, in angles.json next to this file:
  titles   job titles; they work on every board
  phrases  duties from Alex's real work; they suit full-text boards
           (hiring.cafe, Dice, Indeed, Jooble, SimplyHired) and the X-ray

`next` takes the least recently used angles from each pool (3 titles,
2 phrases), records today's date on them, and prints the exact command line
for every keyword-driven lane. A second `next` on the same day reprints the
same set, so a retry of the scan does not advance the rotation. With 12 titles
and 9 phrases, every angle runs at least once every 5 days.

State (gitignored): state/angles-used.json, {angle: last date used}, plus the
set chosen for today.

Usage:
    python3 job-search/angles.py next      # today's angles + lane commands
    python3 job-search/angles.py status    # every angle with its last-used date
"""

import argparse
import datetime as dt
import json
import shlex
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
POOLS = HERE / "angles.json"
STATE = HERE / "state" / "angles-used.json"
PICK = {"titles": 3, "phrases": 2}


def load() -> tuple[dict, dict]:
    pools = json.loads(POOLS.read_text())
    state = json.loads(STATE.read_text()) if STATE.exists() else {"used": {}, "today": {}}
    return pools, state


def choose(pools: dict, state: dict, today: str) -> dict:
    if state.get("today", {}).get("date") == today:
        return state["today"]
    used = state.setdefault("used", {})
    pick: dict[str, Any] = {"date": today}
    for pool, n in PICK.items():
        # Oldest first; never-used angles sort as oldest; list order breaks ties.
        ranked = sorted(pools[pool], key=lambda a: (used.get(a, ""), pools[pool].index(a)))
        pick[pool] = ranked[:n]
        for a in pick[pool]:
            used[a] = today
    state["today"] = pick
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True))
    return pick


def q(*angles: str) -> str:
    return " ".join(shlex.quote(a) for a in angles)


def cmd_next() -> None:
    pools, state = load()
    p = choose(pools, state, dt.date.today().isoformat())
    t, ph = p["titles"], p["phrases"]
    print(f"ANGLES {p['date']}: titles {t} | phrases {ph}\n")
    print("Run each lane with exactly these arguments, and record the angles in the hub-log entry.\n")
    print(f"hiringcafe   python3 job-search/hiringcafe.py {q(t[0], ph[0], ph[1])} --days 3")
    print(f"dice         python3 job-search/dice.py {q(t[1], ph[0], t[2])} --days 3")
    print(f"nicheboards  python3 job-search/nicheboards.py {q(t[0], t[1])} --days 2")
    print(f"indeed       python3 job-search/indeed.py {q(*t)} --days 3")
    print(f"moreboards   python3 job-search/moreboards.py {q(*t)} --days 3")
    print(f"jobspy       python3 job-search/jobspy_lane.py {q(t[0], t[1])} --days 3")
    print(f"linkedin     search_jobs keywords: {t[0]!r}, {t[1]!r}, {t[2]!r} (remote, full_time, past_24_hours)")
    print(f"x-ray        WebSearch {ph[0]!r} remote analyst, allowed_domains Greenhouse; "
          f"{ph[1]!r} remote, allowed_domains jobs.lever.co")
    print("fixed        usajobs.py \"IT specialist\" \"security analyst\" --days 7 (unchanged)")


def cmd_status() -> None:
    pools, state = load()
    used = state.get("used", {})
    for pool in PICK:
        print(pool)
        for a in sorted(pools[pool], key=lambda a: used.get(a, "")):
            print(f"  {used.get(a, 'never'):10s}  {a}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["next", "status"])
    a = ap.parse_args()
    {"next": cmd_next, "status": cmd_status}[a.command]()


if __name__ == "__main__":
    main()
