"""Expected-meeting holds for bodies with a fixed cadence, before the city posts them.

Legistar lists a meeting only days ahead, so the calendar would otherwise be empty
past this week. Cadences were measured from the 2026 Legistar history; see the
"holds" block in config.json.

INVARIANTS:
- A hold's key is hold-<slug(short)>-<YYYY-MM-DD>. When a published meeting of the
  same body lands on that date, the sync adopts the hold's calendar event (patches
  it in place) instead of creating a second one.
- Holds are generated only for slots more than HOLD_CUTOFF away. A hold still
  unconfirmed inside that window is deleted, and is not regenerated because its
  slot is no longer in range.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .model import TZ, Meeting

HOLD_CUTOFF = timedelta(hours=4)
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def hold_key(short: str, day: date) -> str:
    return f"hold-{slug(short)}-{day.isoformat()}"


def _nth(day: date) -> int:
    return (day.day - 1) // 7 + 1


def generate(holds: list[dict], days: int, skip: set[str], now: datetime | None = None) -> list[Meeting]:
    now = now or datetime.now(TZ)
    out = []
    for h in holds:
        wd = DAYS[h["weekday"].lower()[:3]]
        hh, mm = (int(x) for x in h["time"].split(":"))
        for i in range(days + 1):
            day = now.date() + timedelta(days=i)
            if day.weekday() != wd or day.isoformat() in skip:
                continue
            if h.get("nth") and _nth(day) not in h["nth"]:
                continue
            start = datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)
            if start - now <= HOLD_CUTOFF:
                continue
            out.append(Meeting(
                key=hold_key(h["short"], day), source="hold", body=h["body"], short=h["short"],
                tier=h["tier"], start=start, end=start + timedelta(minutes=int(h.get("minutes", 90))),
                location=h.get("location", ""), extra={"pattern": h["pattern"]},
            ))
    return out
