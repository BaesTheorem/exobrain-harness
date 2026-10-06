"""TIF, PIEA and LCRA board meetings from the EDC of Kansas City events calendar.

edckc.com is Cloudflare-walled, so the feed is read through walled.py. Its wp-json
REST route rate-limits (429) quickly; use the iCal feed only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .model import TZ, Meeting


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse_ics(text: str) -> list[dict]:
    """VEVENTs as {PROP: value}, with TZID-local times parsed to aware datetimes."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    events, cur = [], None
    for ln in lines:
        if ln == "BEGIN:VEVENT":
            cur = {}
        elif ln == "END:VEVENT" and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None and ":" in ln:
            name_params, value = ln.split(":", 1)
            name = name_params.split(";", 1)[0].upper()
            if name in ("DTSTART", "DTEND"):
                v = value.strip()
                if len(v) == 8:
                    cur[name] = datetime.strptime(v, "%Y%m%d").replace(tzinfo=TZ)
                elif v.endswith("Z"):
                    cur[name] = datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(TZ)
                else:
                    cur[name] = datetime.strptime(v, "%Y%m%dT%H%M%S").replace(tzinfo=TZ)
            else:
                cur[name] = _unescape(value)
    return events


def to_meetings(events: list[dict], bodies: list[dict], days: int, now: datetime | None = None) -> list[Meeting]:
    now = now or datetime.now(TZ)
    horizon = now + timedelta(days=days)
    out = []
    for ev in events:
        summary = ev.get("SUMMARY", "").strip()
        cfg = next((b for b in bodies if b["match"].lower() == summary.lower()), None)
        start = ev.get("DTSTART")
        if not cfg or not isinstance(start, datetime) or not (now - timedelta(hours=6) <= start <= horizon):
            continue
        dtend = ev.get("DTEND")
        end = dtend if isinstance(dtend, datetime) else start + timedelta(hours=2)
        desc = ev.get("DESCRIPTION", "").strip()
        out.append(Meeting(
            key=f"edc-{ev.get('UID', summary + start.isoformat())}",
            source="edc", body=summary, short=cfg["short"], tier=cfg["tier"],
            start=start, end=end, location=ev.get("LOCATION", "").strip(),
            url=ev.get("URL", "").strip(), agenda_url="",
            # The feed carries no agenda link; LAST-MODIFIED moves when staff attach one.
            agenda_fingerprint=ev.get("LAST-MODIFIED", ""),
            cancelled="cancel" in (summary + desc).lower(),
            source_id=ev.get("UID", ""),
            extra={"description": desc, "pages": [ev.get("URL", "").strip()] if ev.get("URL") else []},
        ))
    return out
