#!/usr/bin/env python3
"""Measure routing loops in a USPS tracking history.

Input: the text of a tracking history as USPS.com shows it (pasted or OCR'd),
or the TSV format in raw/tracking-*.tsv. Output: one JSON record with the
facility sequence, the number of plant visits, MO<->KS alternations, dwell
per visit, and transit times between plants.

A "plant" is any location whose name ends in DISTRIBUTION CENTER (USPS shows
P&DCs, NDCs, RPDCs and RTHs with that one label since about 2023). A "loop"
is a return to a plant the item already left. This tool reads only text that
a person gave it; it never calls USPS.
"""
from __future__ import annotations

import json
import re
import sys
from itertools import pairwise
from dataclasses import dataclass
from datetime import datetime

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
TS_RE = re.compile(rf"({MONTHS}) (\d{{1,2}}), (\d{{4}})(?:,? (?:at )?(\d{{1,2}}):(\d{{2}}) ?([ap]\.?m\.?))?", re.I)
EVENT_WORDS = re.compile(
    r"(Delivered[^\n]*|Out for Delivery|Arrived at (?:USPS )?(?:Regional )?(?:Facility|Post Office|Hub)|"
    r"Departed (?:USPS )?(?:Regional )?(?:Facility|Post Office)|Processing at USPS Facility|"
    r"In Transit to Next Facility|USPS in possession of item|Accepted at USPS Origin Facility|"
    r"Pre-Shipment Info Sent to USPS[^\n]*|Shipping Label Created[^\n]*|Arrived at Hub|"
    r"Available for Pickup|Delivery Attempted[^\n]*|Moving Through Network|Missent|"
    r"Forwarded|Return to Sender|Delayed[^\n]*|Insufficient Address|Alert)", re.I)
LOC_RE = re.compile(r"([A-Z][A-Z .'-]+?,? (?:[A-Z]{2}) ?(?:\d{5})?(?: [A-Z ]*DISTRIBUTION CENTER| NETWORK DISTRIBUTION CENTER)?)")


@dataclass
class Event:
    ts: datetime
    what: str
    where: str

    @property
    def plant(self) -> str | None:
        w = self.where.upper()
        return w if "DISTRIBUTION CENTER" in w else None


def _ts(m: re.Match) -> datetime:
    mon, day, year, hh, mm, ap = m.groups()
    dt = datetime.strptime(f"{mon} {day} {year}", "%B %d %Y")
    if hh:
        h = int(hh) % 12 + (12 if ap.lower().startswith("p") else 0)
        dt = dt.replace(hour=h, minute=int(mm))
    return dt


def parse_tsv(text: str) -> list[Event]:
    out = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        ts, what, where = (line.split("\t") + ["", ""])[:3]
        fmt = "%Y-%m-%d %H:%M" if ":" in ts else "%Y-%m-%d"
        out.append(Event(datetime.strptime(ts.strip(), fmt), what.strip(), where.strip()))
    return out


def parse_usps_text(text: str) -> list[Event]:
    """Parse the block text of a USPS.com history (newest first, any line breaks)."""
    flat = re.sub(r"[ \t]+", " ", text.replace("\r", ""))
    # the "Latest Update" banner repeats the newest event as prose; drop it
    flat = re.sub(r"Your item (?:was|has|is)[^.]*\.", " ", flat, flags=re.I | re.S)
    events = []
    for m in EVENT_WORDS.finditer(flat):
        nxt = EVENT_WORDS.search(flat, m.end())
        chunk = flat[m.end(): nxt.start() if nxt else len(flat)]
        tsm = TS_RE.search(chunk)
        before_ts = chunk[: tsm.start()] if tsm else chunk
        loc = " ".join(before_ts.split()).strip(" ,")
        if tsm:  # an event with no date (for example "In Transit") cannot be placed
            events.append(Event(_ts(tsm), m.group(1).strip(), loc))
    # USPS lists newest first; return oldest first
    return sorted(events, key=lambda e: e.ts)


def metrics(events: list[Event]) -> dict:
    visits = []  # consecutive events at the same plant collapse into one visit
    for e in events:
        p = e.plant
        if not p:
            # "In Transit to Next Facility" has no place, so it does not end a visit
            if e.where.strip() and visits and visits[-1].get("open"):
                visits[-1]["open"] = False
            continue
        if visits and visits[-1]["plant"] == p and visits[-1].get("open"):
            visits[-1]["last"] = e.ts
            visits[-1]["events"].append(e.what)
        else:
            if visits:
                visits[-1]["open"] = False
            visits.append({"plant": p, "first": e.ts, "last": e.ts, "events": [e.what], "open": True})
    seen, loops = set(), 0
    for v in visits:
        if v["plant"] in seen:
            loops += 1
        seen.add(v["plant"])
    transits = []
    for a, b in pairwise(events):
        if a.plant and b.plant and a.plant != b.plant and a.what.lower().startswith("departed"):
            transits.append(round((b.ts - a.ts).total_seconds() / 60))
    # dwell = time from the first scan at a plant to the first scan anywhere else
    dwell_h = []
    for v in visits:
        nxt = next((e.ts for e in events
                    if e.ts > v["last"] and e.plant != v["plant"] and e.where.strip()), None)
        if nxt:
            dwell_h.append(round((nxt - v["first"]).total_seconds() / 3600, 1))
    first, last = events[0].ts, events[-1].ts
    delivered = next((e for e in events if e.what.lower().startswith("delivered")), None)
    plants_only = [v["plant"] for v in visits]
    return {
        "events": len(events),
        "plant_visits": len(visits),
        "distinct_plants": sorted(set(plants_only)),
        "returns_to_a_plant": loops,
        "mo_ks_alternations": sum(1 for a, b in pairwise(plants_only)
                                  if {a.split()[2] if len(a.split()) > 2 else a,
                                      b.split()[2] if len(b.split()) > 2 else b} == {"MO", "KS"}),
        "plant_sequence": [p.replace(" DISTRIBUTION CENTER", "") for p in plants_only],
        "processing_scans_at_plants": sum(1 for e in events if e.plant and "processing" in e.what.lower()),
        "arrivals_without_departure": sum(1 for v in visits if not any(w.lower().startswith("departed") for w in v["events"])),
        "plant_transit_min": transits,
        "dwell_hours_per_visit": dwell_h,
        "days_first_to_last_scan": round((last - first).total_seconds() / 86400, 1),
        "delivered": bool(delivered),
        "delivered_where": delivered.where if delivered else None,
    }


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "-"
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    events = parse_tsv(text) if "\t" in text else parse_usps_text(text)
    if not events:
        sys.exit("no timestamped events found")
    print(json.dumps(metrics(events), indent=1, default=str))


if __name__ == "__main__":
    main()
