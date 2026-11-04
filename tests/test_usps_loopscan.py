"""loopscan: the text parser and the TSV parser must agree, and loops must count."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "usps" / "bin"))

import loopscan  # noqa: E402

MO = "KANSAS CITY MO DISTRIBUTION CENTER"
KS = "KANSAS CITY KS DISTRIBUTION CENTER"


def _synthetic() -> list[loopscan.Event]:
    t = datetime(2026, 8, 1, 9, 0)
    seq = [("USPS in possession of item", "KANSAS CITY, MO 64111")]
    for i in range(3):
        seq += [("Arrived at USPS Facility", MO), ("Departed USPS Facility", MO),
                ("Arrived at USPS Facility", KS), ("Departed USPS Facility", KS)]
        del i
    seq += [("Arrived at Post Office", "KANSAS CITY, MO 64111"), ("Out for Delivery", "KANSAS CITY, MO 64111"),
            ("Delivered, In/At Mailbox", "KANSAS CITY, MO 64111")]
    out = []
    for what, where in seq:
        t += timedelta(hours=7, minutes=13)
        out.append(loopscan.Event(t, what, where))
    return out


def _render_usps(events: list[loopscan.Event]) -> str:
    lines = ["Latest Update", "Your item was delivered at 2:10 pm on August 9, 2026 in KANSAS CITY, MO 64111.", ""]
    for e in reversed(events):
        lines += [e.what, e.where, e.ts.strftime("%B %-d, %Y, %-I:%M %p").replace("AM", "am").replace("PM", "pm"), ""]
    return "\n".join(lines)


def test_text_parser_matches_events_and_ignores_banner() -> None:
    events = _synthetic()
    parsed = loopscan.parse_usps_text(_render_usps(events))
    assert loopscan.metrics(parsed) == loopscan.metrics(events)


def test_loop_counts() -> None:
    m = loopscan.metrics(_synthetic())
    assert m["plant_visits"] == 6
    assert m["returns_to_a_plant"] == 4
    assert m["mo_ks_alternations"] == 5
    assert m["processing_scans_at_plants"] == 0
    assert m["delivered"] is True
