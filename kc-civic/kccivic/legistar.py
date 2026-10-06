"""Kansas City, MO meetings from the public Legistar Web API (no key needed).

The API returns JSON with raw control characters inside agenda titles, so every
response is parsed with strict=False. A strict parse fails on roughly one body in
three.
"""

from __future__ import annotations

import json
import urllib.error
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from .model import TZ, Meeting

BASE = "https://webapi.legistar.com/v1/kansascity"
LINK_RE = re.compile(r"https?://[^\s<>\"']*(?:zoom\.us|teams\.microsoft\.com|teams\.live\.com)[^\s<>\"']*", re.I)


def _get(path: str, params: dict | None = None) -> list | dict:
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, safe="$'(),+ ")
    url = url.replace(" ", "+")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "kc-civic/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"), strict=False)


def events_between(start: date, end: date) -> list[dict]:
    flt = f"EventDate ge datetime'{start.isoformat()}' and EventDate lt datetime'{end.isoformat()}'"
    out = _get("/events", {"$filter": flt, "$orderby": "EventDate"})
    assert isinstance(out, list)
    return out


def event(event_id: int) -> dict | None:
    try:
        out = _get(f"/events/{event_id}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return out if isinstance(out, dict) else None


def event_items(event_id: int) -> list[dict]:
    out = _get(f"/events/{event_id}/eventitems", {"AgendaNote": "1", "Attachments": "1"})
    assert isinstance(out, list)
    return out


def parse_time(day: str, clock: str | None) -> tuple[datetime, bool]:
    """(start, time_known). Legistar gives the date and a separate '9:00 AM' string."""
    d = datetime.fromisoformat(day[:10])
    if clock:
        m = re.match(r"\s*(\d{1,2}):(\d{2})\s*([AaPp])", clock)
        if m:
            h, mi = int(m.group(1)) % 12, int(m.group(2))
            if m.group(3).lower() == "p":
                h += 12
            return d.replace(hour=h, minute=mi, tzinfo=TZ), True
    return d.replace(hour=9, tzinfo=TZ), False


def to_meeting(ev: dict, cfg: dict) -> Meeting:
    start, known = parse_time(ev["EventDate"], ev.get("EventTime"))
    loc = (ev.get("EventLocation") or "").replace("\r\n", " ").strip()
    comment = (ev.get("EventComment") or "").strip()
    blob = " ".join([loc, comment, ev.get("EventTime") or ""])
    link = LINK_RE.search(blob)
    agenda = ev.get("EventAgendaFile") or ""
    m = Meeting(
        key=f"legistar-{ev['EventId']}",
        source="legistar",
        body=ev["EventBodyName"].strip(),
        short=cfg["short"],
        tier=cfg["tier"],
        start=start,
        end=start + timedelta(minutes=int(cfg.get("minutes", 90))),
        location=loc,
        url=ev.get("EventInSiteURL") or "",
        agenda_url=agenda,
        agenda_fingerprint=(ev.get("EventAgendaLastPublishedUTC") or "") if agenda else "",
        join_link=link.group(0).rstrip(".,);") if link else "",
        cancelled="cancel" in blob.lower(),
        source_id=str(ev["EventId"]),
        extra={"comment": comment, "time_known": known, "pages": list(cfg.get("pages", []))},
    )
    return m


def meetings(bodies: list[dict], days: int, today: date | None = None) -> list[Meeting]:
    today = today or datetime.now(TZ).date()
    by_name = {b["name"].strip(): b for b in bodies}
    out = []
    for ev in events_between(today, today + timedelta(days=days)):
        cfg = by_name.get((ev.get("EventBodyName") or "").strip())
        if cfg:
            out.append(to_meeting(ev, cfg))
    return out
