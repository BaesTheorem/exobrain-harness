"""Turning "Meetups!" forum threads into calendar-ready events.

The board runs a calendar extension, which would be the better source, but a Tier 1
account renders the month grid with every event cell empty: the event records are
permission-gated like the rest of the board. So the thread itself is the source.

INVARIANTS:
- The TITLE is the authoritative date, not the first post. Hosts reschedule by editing
  the subject line ("Midweek Madness Gut & Grime 6/3" was proposed as 5/26 in the body
  and moved twice); the body keeps the stale date forever.
- A bare M/D gets its year from the thread's own start date: the meetup is on or after
  the announcement, and within a year of it. Never assume the current year -- most of
  these threads are read months later.
- Parsing is best-effort and says so. Every event carries `confidence`, and anything
  that did not yield a date is returned as unparsed rather than guessed onto a
  plausible-looking day.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .auth import Session
from . import forum as F

# "9/14/25", "6/3", "12/23". Bounded so it cannot swallow a coordinate or a time.
DATE_IN_TITLE = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")
# "7:30pm", "6:30 PM", "1PM"
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\b", re.I)
# A bare decimal lat/lon pair. KC sits near 39N 94W, so the ranges are tight on purpose:
# this must not match a price, a version number, or a phone number.
COORD_RE = re.compile(r"(3[5-9]\.\d{4,})\s*,\s*(-9[2-6]\.\d{4,})")
# "Meet at Kaw Point Park", "park at Bar K & walk over"
VENUE_RE = re.compile(r"\b(?:meet(?:ing)?\s+(?:up\s+)?at|meet\s+in|park\s+at|start(?:ing)?\s+at)\s+([^.\n;]{3,60})", re.I)


@dataclass
class Meetup:
    topic_id: int
    title: str
    host: str
    url: str
    announced: date | None
    starts: datetime | None
    all_day: bool
    venue: str = ""
    lat: float | None = None
    lon: float | None = None
    blurb: str = ""
    confidence: str = "parsed"
    images: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"kcurbex-meetup-{self.topic_id}"


def _year_group(m: re.Match[str]) -> int | None:
    """The optional 2- or 4-digit year in a M/D/Y match, or None if it was omitted."""
    raw = m.group(3)
    return int(raw) if raw else None


def _resolve_year(month: int, day: int, year: int | None, announced: date | None) -> date | None:
    """A M/D from a title, anchored to the year that puts it on/after the announcement."""
    if year is not None:
        year = year + 2000 if year < 100 else year
        try:
            return date(year, month, day)
        except ValueError:
            return None
    anchor = announced or date.today()
    for candidate in (anchor.year, anchor.year + 1):
        try:
            d = date(candidate, month, day)
        except ValueError:
            continue
        # Allow a few days of slack for a host who posts the morning after midnight.
        if d >= anchor - timedelta(days=3):
            return d
    return None


def parse_meetup(topic: F.Topic) -> Meetup:
    """Best-effort structured event from a meetup thread. Never invents a date."""
    announced = topic.started.date() if topic.started else None
    first = topic.posts[0].text if topic.posts else ""
    body = topic.body

    # -- date: title wins, body is the fallback
    event_date, confidence = None, "parsed"
    m = DATE_IN_TITLE.search(topic.title)
    if m:
        event_date = _resolve_year(int(m.group(1)), int(m.group(2)), _year_group(m), announced)
    if event_date is None:
        m = DATE_IN_TITLE.search(first)
        if m:
            event_date = _resolve_year(int(m.group(1)), int(m.group(2)), _year_group(m), announced)
            confidence = "from-body"
    if event_date is None:
        confidence = "no-date"

    # -- time. The HOST's post only. A reply saying "I'll be there around 9pm" is not
    # the start time, and silently adopting it puts a wrong hour on the calendar.
    start_dt, all_day = None, True
    if event_date:
        tm = TIME_RE.search(first)
        if tm:
            hour = int(tm.group(1)) % 12
            if tm.group(3).lower() == "p":
                hour += 12
            start_dt = datetime.combine(event_date, time(hour, int(tm.group(2) or 0))).astimezone()
            all_day = False
        else:
            start_dt = datetime.combine(event_date, time(0, 0)).astimezone()

    # -- place
    # Place, likewise from the announcement: a reply's coordinates may be some other
    # spot entirely (people post their own finds in meetup threads).
    lat = lon = None
    cm = COORD_RE.search(first)
    if cm:
        lat, lon = float(cm.group(1)), float(cm.group(2))
    vm = VENUE_RE.search(first)
    venue = " ".join(vm.group(1).split()).strip(" ,&") if vm else ""

    return Meetup(
        topic_id=topic.topic_id,
        title=topic.title,
        host=topic.author or (topic.posts[0].author if topic.posts else ""),
        url=topic.url,
        announced=announced,
        starts=start_dt,
        all_day=all_day,
        venue=venue,
        lat=lat,
        lon=lon,
        blurb=" ".join(first.split())[:500],
        confidence=confidence,
        images=topic.posts[0].images if topic.posts else [],
    )


def fetch_meetups(session: Session) -> list[Meetup]:
    """Every visible meetup thread, parsed, newest announcement first."""
    out = []
    for topic in F.list_topics(session, F.MEETUPS_FORUM):
        F.load_posts(session, topic, max_pages=2)
        out.append(parse_meetup(topic))
    out.sort(key=lambda m: m.starts or datetime.min.replace(tzinfo=None).astimezone(), reverse=True)
    return out


def upcoming(meetups: list[Meetup], today: date | None = None) -> list[Meetup]:
    today = today or date.today()
    return [m for m in meetups if m.starts and m.starts.date() >= today]
