#!/usr/bin/env python3
"""Fetch friends' calendar feeds (ICS) and cache busy intervals only.

Part of the group-scheduler: friends who opt in share a read-only ICS URL
(Google "secret address", Apple public calendar, any .ics/webcal feed).
This script turns each feed into a list of [start, end] busy blocks so the
scheduler can rank candidate times without ever seeing what anyone is doing.

INVARIANTS (an edit must not break these):
- Only busy time intervals reach the cache file or stdout. Event titles,
  descriptions, locations, organizers, and attendees are discarded during
  parsing and must never be persisted, printed, or logged.
- feeds.json and freebusy-cache.json are gitignored; this file stays free
  of names, URLs, and any other personal data.
- Events marked TRANSP:TRANSPARENT or STATUS:CANCELLED never count as busy
  (this is how all-day birthdays etc. stay out of the way).

Usage:
    python3 ics_freebusy.py [--feeds feeds.json] [--out freebusy-cache.json]
                            [--days 60] [--person NAME]

feeds.json shape: see feeds.example.json next to this script.
Exit codes: 0 = all feeds OK, 1 = some failed, 2 = all failed / config error.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
DEFAULT_TZ = "America/Chicago"
FETCH_TIMEOUT = 30
# Backstop against pathological recurrences, far above any real calendar.
MAX_OCCURRENCES = 10_000

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

Interval = tuple[datetime, datetime]


@dataclass
class BusyEvent:
    """The scheduling-relevant skeleton of one VEVENT. No content fields."""

    start: datetime
    end: datetime
    rrule: dict[str, str] = field(default_factory=dict)
    exdates: set[datetime] = field(default_factory=set)
    all_day: bool = False


def unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with space/tab continues the previous."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def split_prop(line: str) -> tuple[str, dict[str, str], str]:
    """'DTSTART;TZID=X:2026...' -> ('DTSTART', {'TZID': 'X'}, '2026...')."""
    head, _, value = line.partition(":")
    parts = head.split(";")
    params: dict[str, str] = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v
    return parts[0].upper(), params, value


def parse_dt(value: str, params: dict[str, str], default_tz: ZoneInfo) -> tuple[datetime, bool]:
    """Parse an ICS date or datetime. Returns (aware datetime, is_all_day)."""
    if params.get("VALUE") == "DATE" or ("T" not in value and len(value) == 8):
        d = date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
        return datetime.combine(d, time.min, tzinfo=default_tz), True
    utc = value.endswith("Z")
    core = value.rstrip("Z")
    dt = datetime.strptime(core, "%Y%m%dT%H%M%S")
    if utc:
        return dt.replace(tzinfo=timezone.utc), False
    tzid = params.get("TZID")
    if tzid:
        try:
            return dt.replace(tzinfo=ZoneInfo(tzid)), False
        except (KeyError, ValueError):
            pass  # unknown TZID: fall through to the feed's default zone
    return dt.replace(tzinfo=default_tz), False


def parse_duration(value: str) -> timedelta:
    """Minimal ISO-8601/RFC-5545 duration: [+-]P[nW][nD][T[nH][nM][nS]]."""
    sign = -1 if value.startswith("-") else 1
    v = value.lstrip("+-").upper()
    if not v.startswith("P"):
        raise ValueError(f"bad duration {value!r}")
    v = v[1:]
    days_part, _, time_part = v.partition("T")
    td = timedelta()
    num = ""
    for ch in days_part:
        if ch.isdigit():
            num += ch
        elif ch == "W":
            td += timedelta(weeks=int(num)); num = ""
        elif ch == "D":
            td += timedelta(days=int(num)); num = ""
    for ch in time_part:
        if ch.isdigit():
            num += ch
        elif ch == "H":
            td += timedelta(hours=int(num)); num = ""
        elif ch == "M":
            td += timedelta(minutes=int(num)); num = ""
        elif ch == "S":
            td += timedelta(seconds=int(num)); num = ""
    return sign * td


def parse_events(ics_text: str, default_tz: ZoneInfo, warnings: list[str]) -> list[BusyEvent]:
    """Extract busy-relevant VEVENT skeletons. Content properties are never read."""
    events: list[BusyEvent] = []
    in_event = False
    props: dict[str, tuple[dict[str, str], str]] = {}
    exdates: set[datetime] = set()
    for line in unfold(ics_text):
        name, params, value = split_prop(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            in_event, props, exdates = True, {}, set()
        elif name == "END" and value.upper() == "VEVENT":
            in_event = False
            ev = build_event(props, exdates, default_tz, warnings)
            if ev:
                events.append(ev)
        elif in_event:
            if name == "EXDATE":
                for chunk in value.split(","):
                    if chunk:
                        dt, _ = parse_dt(chunk, params, default_tz)
                        exdates.add(dt)
            elif name in ("DTSTART", "DTEND", "DURATION", "RRULE", "TRANSP", "STATUS"):
                props[name] = (params, value)
    return events


def build_event(
    props: dict[str, tuple[dict[str, str], str]],
    exdates: set[datetime],
    default_tz: ZoneInfo,
    warnings: list[str],
) -> BusyEvent | None:
    if "DTSTART" not in props:
        return None
    if props.get("STATUS", ({}, ""))[1].upper() == "CANCELLED":
        return None
    transp = props.get("TRANSP", ({}, "OPAQUE"))[1].upper()
    if transp == "TRANSPARENT":
        return None
    start_params, start_val = props["DTSTART"]
    start, all_day = parse_dt(start_val, start_params, default_tz)
    if "DTEND" in props:
        end_params, end_val = props["DTEND"]
        end, _ = parse_dt(end_val, end_params, default_tz)
    elif "DURATION" in props:
        try:
            end = start + parse_duration(props["DURATION"][1])
        except ValueError:
            warnings.append("unparseable DURATION; event skipped")
            return None
    else:
        # RFC default: all-day events last one day, timed events are instants.
        end = start + timedelta(days=1) if all_day else start
    if end <= start:
        end = start + (timedelta(days=1) if all_day else timedelta(minutes=1))
    rrule: dict[str, str] = {}
    if "RRULE" in props:
        for part in props["RRULE"][1].split(";"):
            k, _, v = part.partition("=")
            if k:
                rrule[k.upper()] = v
    return BusyEvent(start=start, end=end, rrule=rrule, exdates=exdates, all_day=all_day)


def expand(
    ev: BusyEvent,
    win_start: datetime,
    win_end: datetime,
    warnings: list[str],
) -> list[Interval]:
    """Occurrences of one event that overlap the window.

    Stdlib RRULE expansion covering what real Google/Apple exports use:
    FREQ=DAILY/WEEKLY/MONTHLY/YEARLY with INTERVAL, COUNT, UNTIL, and
    BYDAY (weekly only). Anything richer is expanded as best-effort and a
    warning is recorded, so a silent gap never masquerades as free time.
    """
    duration = ev.end - ev.start
    if not ev.rrule:
        occ = [(ev.start, ev.end)]
        return [iv for iv in occ if iv[1] > win_start and iv[0] < win_end and ev.start not in ev.exdates]

    freq = ev.rrule.get("FREQ", "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        warnings.append(f"unsupported RRULE FREQ={freq or '?'}; series treated as single event")
        return [(ev.start, ev.end)] if ev.end > win_start and ev.start < win_end else []

    interval = max(1, int(ev.rrule.get("INTERVAL", "1") or 1))
    count = int(ev.rrule["COUNT"]) if "COUNT" in ev.rrule else None
    until: datetime | None = None
    if "UNTIL" in ev.rrule:
        until, _ = parse_dt(ev.rrule["UNTIL"], {}, timezone.utc)  # type: ignore[arg-type]

    unsupported = set(ev.rrule) - {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "WKST"}
    if unsupported or ("BYDAY" in ev.rrule and freq != "WEEKLY"):
        warnings.append(f"partially supported RRULE parts {sorted(unsupported) or ['BYDAY']}; expansion approximate")

    # Candidate start instants, generated in order from DTSTART.
    starts: list[datetime] = []
    if freq == "WEEKLY" and "BYDAY" in ev.rrule:
        bydays = sorted(
            WEEKDAYS[d] for d in ev.rrule["BYDAY"].split(",") if d in WEEKDAYS
        ) or [ev.start.weekday()]
        week_anchor = ev.start - timedelta(days=ev.start.weekday())
        produced = 0
        for week in range(MAX_OCCURRENCES):
            base = week_anchor + timedelta(weeks=week * interval)
            done = False
            for wd in bydays:
                occ_start = base + timedelta(days=wd)
                if occ_start < ev.start:
                    continue
                if until and occ_start > until:
                    done = True
                    break
                starts.append(occ_start)
                produced += 1
                if (count and produced >= count) or len(starts) >= MAX_OCCURRENCES:
                    done = True
                    break
            if done or base > win_end + timedelta(weeks=interval):
                break
    else:
        step_days = {"DAILY": 1, "WEEKLY": 7}.get(freq)
        occ_start = ev.start
        # Unbounded old series: jump straight to the window instead of
        # iterating years of history one occurrence at a time.
        if step_days and count is None and occ_start < win_start:
            period = timedelta(days=step_days * interval)
            behind = (win_start - occ_start) // period
            occ_start += behind * period
        n = 0
        months_step = {"MONTHLY": 1, "YEARLY": 12}.get(freq, 0) * interval
        while len(starts) < MAX_OCCURRENCES:
            if until and occ_start > until:
                break
            if count is not None and n >= count:
                break
            starts.append(occ_start)
            n += 1
            if occ_start > win_end:
                break
            if step_days:
                occ_start += timedelta(days=step_days * interval)
            else:
                total = occ_start.month - 1 + months_step
                year, month = occ_start.year + total // 12, total % 12 + 1
                day = min(occ_start.day, last_day_of_month(year, month))
                occ_start = occ_start.replace(year=year, month=month, day=day)

    out: list[Interval] = []
    for s in starts:
        if s in ev.exdates:
            continue
        e = s + duration
        if e > win_start and s < win_end:
            out.append((s, e))
    return out


def last_day_of_month(year: int, month: int) -> int:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return (nxt - timedelta(days=1)).day


def merge_intervals(intervals: list[Interval]) -> list[Interval]:
    if not intervals:
        return []
    ivs = sorted(intervals)
    merged = [ivs[0]]
    for s, e in ivs[1:]:
        ls, le = merged[-1]
        if s <= le:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def clip(intervals: list[Interval], win_start: datetime, win_end: datetime) -> list[Interval]:
    return [(max(s, win_start), min(e, win_end)) for s, e in intervals]


def fetch_ics(url: str) -> str:
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    req = urllib.request.Request(url, headers={"User-Agent": "exobrain-scheduler/1.0"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def process_feed(
    url: str, person_tz: ZoneInfo, win_start: datetime, win_end: datetime
) -> tuple[list[Interval], list[str]]:
    warnings: list[str] = []
    text = fetch_ics(url)
    busy: list[Interval] = []
    for ev in parse_events(text, person_tz, warnings):
        busy.extend(expand(ev, win_start, win_end, warnings))
    return merge_intervals(clip(busy, win_start, win_end)), warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch friends' calendar feeds (ICS) and cache busy intervals only."
    )
    ap.add_argument("--feeds", type=Path, default=HERE / "feeds.json")
    ap.add_argument("--out", type=Path, default=HERE / "freebusy-cache.json")
    ap.add_argument("--days", type=int, default=60, help="window length ahead of now")
    ap.add_argument("--person", help="refresh just this one person")
    args = ap.parse_args(argv)

    if not args.feeds.exists():
        print(f"no feeds config at {args.feeds} (copy feeds.example.json)", file=sys.stderr)
        return 2
    config = json.loads(args.feeds.read_text())
    tz_name = str(config.get("timezone", DEFAULT_TZ))
    default_tz = ZoneInfo(tz_name)
    people: dict[str, dict[str, str]] = config.get("people", {})
    if args.person:
        people = {k: v for k, v in people.items() if k.lower() == args.person.lower()}
        if not people:
            print(f"{args.person!r} not in feeds config", file=sys.stderr)
            return 2

    now = datetime.now(default_tz)
    win_start, win_end = now - timedelta(days=1), now + timedelta(days=args.days)

    # Preserve entries for people not being refreshed this run.
    cache: dict[str, object] = {}
    if args.out.exists():
        try:
            cache = json.loads(args.out.read_text())
        except json.JSONDecodeError:
            cache = {}
    results: dict[str, dict[str, object]] = dict(cache.get("people", {}))  # type: ignore[arg-type]

    failures = 0
    for name, feed in people.items():
        person_tz = ZoneInfo(feed.get("timezone") or tz_name)
        try:
            busy, warnings = process_feed(feed["url"], person_tz, win_start, win_end)
            results[name] = {
                "fetched_at": now.isoformat(),
                "error": None,
                "warnings": warnings,
                "busy": [[s.isoformat(), e.isoformat()] for s, e in busy],
            }
            print(f"{name}: {len(busy)} busy blocks" + (f", {len(warnings)} warnings" if warnings else ""))
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            failures += 1
            prev = results.get(name, {})
            results[name] = {
                "fetched_at": prev.get("fetched_at"),
                "error": f"{type(exc).__name__}: {exc}",
                "warnings": [],
                "busy": prev.get("busy", []),
            }
            print(f"{name}: FAILED ({type(exc).__name__}), kept previous cache", file=sys.stderr)

    args.out.write_text(
        json.dumps(
            {
                "generated_at": now.isoformat(),
                "window": {"start": win_start.isoformat(), "end": win_end.isoformat()},
                "people": results,
            },
            indent=2,
        )
        + "\n"
    )
    if failures and failures == len(people):
        return 2
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
