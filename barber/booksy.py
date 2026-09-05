#!/usr/bin/env python3
"""Read live Booksy availability for the Rich Forever barbers.

Rich Forever Midtown is an umbrella venue (booth rental): the shop itself has
no calendar. Each barber is an independent Booksy business with their own
service menu and hours, so availability has to be read per barber and merged.

Booksy has no documented public API. This drives the same unauthenticated
endpoints the booking widget uses:

    POST /drafts/create              -> a draft appointment, returns its uuid
    POST /drafts/{uuid}/calendar     -> which days that barber is working
    POST /drafts/{uuid}/timeslots    -> open start times on a given day

Reading availability needs no account. *Booking* does (Booksy requires a
verified phone, and some barbers have prepayment enabled), which is why this
module deliberately stops at "here are the open slots" and hands off a deep
link instead of confirming anything.

INVARIANTS (an edit must not break these):
- This module is read-only against Booksy. It must never POST to a booking,
  confirmation, or cancellation endpoint -- creating a draft is a scratch
  object Booksy discards, and nothing here reserves a chair.
- config.json holds public business facts only (shop, barber, service ids).
  No customer name, phone, email, or card data belongs in this package.

Usage:
    python3 booksy.py calendar --days 30
    python3 booksy.py slots --date 2026-08-29
    python3 booksy.py slots --from 2026-08-28 --to 2026-09-02 --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"

API = "https://us.booksy.com/core/v2/customer_api"
# The public key the Booksy web widget ships with; not a secret or a credential.
WEB_API_KEY = "web-e3d812bf-d7a2-445d-ab38-55589ae6a121"
TIMEOUT = 30
# Booksy rate-limits a fast sweep; pace day requests and retry a stalled one.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 2.0
REQUEST_PACING = 0.4
# Booksy caps how far ahead a draft may look; keep requests inside it.
MAX_LEAD_DAYS = 90


class BooksyError(RuntimeError):
    """A Booksy request failed or returned something unusable."""


@dataclass(frozen=True)
class Barber:
    """One booth-renting barber and the service we want from them."""

    business_id: int
    name: str
    service_name: str
    service_variant_id: int
    price: str
    duration_min: int
    url: str
    stars: float = 0.0
    reviews: int = 0

    @property
    def booking_url(self) -> str:
        return f"https://booksy.com/en-us/{self.url}"

    @property
    def rank_key(self) -> tuple[float, int]:
        """Sort key for "best rated first".

        Every Midtown barber currently sits at a flat 5.0, so stars alone
        cannot separate them and review count is what actually decides. Sorting
        on stars alone would silently fall back to config order and look like
        it was ranking when it was not.
        """
        return (self.stars, self.reviews)


@dataclass(frozen=True)
class Slot:
    """A bookable start time with the barber who offers it."""

    barber: Barber
    start: datetime

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.barber.duration_min)

    def __str__(self) -> str:
        return (
            f"{self.start:%a %b %d  %-I:%M %p}-{self.end:%-I:%M %p}  "
            f"{self.barber.name} ({self.barber.price})"
        )


def load_barbers(path: Path = CONFIG_PATH) -> list[Barber]:
    """Barbers, best-rated first."""
    cfg = json.loads(path.read_text())
    barbers = [Barber(**b) for b in cfg["barbers"]]
    return sorted(barbers, key=lambda b: b.rank_key, reverse=True)


def best_slot(slots: list[Slot], busy: list[tuple[datetime, datetime]] | None = None) -> Slot | None:
    """Pick the slot with the best-rated barber, earliest date wins ties.

    Alex's rule: always take the highest-rated barber available in the window.
    So rank by barber first and date second -- not the other way round, or a
    marginally earlier slot would keep beating a better barber.
    """
    free = [s for s in slots if not _conflicts(s, busy or [])]
    if not free:
        return None
    return min(free, key=lambda s: (-s.barber.rank_key[0], -s.barber.rank_key[1], s.start))


def _conflicts(slot: Slot, busy: list[tuple[datetime, datetime]], travel_min: int = 30) -> bool:
    """Does this slot collide with a busy block, allowing travel either side?"""
    start = slot.start - timedelta(minutes=travel_min)
    end = slot.end + timedelta(minutes=travel_min)
    return any(start < b_end and b_start < end for b_start, b_end in busy)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "x-api-key": WEB_API_KEY,
        "x-fingerprint": str(uuid.uuid4()),
        "accept": "application/json",
        "accept-language": "en",
        "content-type": "application/json",
        "origin": "https://booksy.com",
        "referer": "https://booksy.com/",
    }


def _post(path: str, body: dict, headers: dict[str, str]) -> dict:
    """POST to Booksy, retrying a stalled request, and never raising a bare error.

    Every failure leaves here as a BooksyError. A read timeout arrives as a
    plain TimeoutError, which is not a URLError -- left uncaught it escapes the
    per-barber handler in slots_in_range and kills an entire sweep, instead of
    degrading into the one warning that call site is written to collect.
    """
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:200].decode("utf-8", "replace")
            raise BooksyError(f"{path} -> HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            reason = getattr(exc, "reason", exc)
            if attempt == RETRY_ATTEMPTS:
                raise BooksyError(f"{path} -> {reason}") from exc
            time.sleep(RETRY_BACKOFF * attempt)
    raise BooksyError(f"{path} -> gave up after {RETRY_ATTEMPTS} attempts")


def open_draft(barber: Barber) -> tuple[str, dict[str, str]]:
    """Create a scratch draft appointment; returns (draft_id, session headers).

    The draft is Booksy's handle for "someone is mid-booking". It reserves
    nothing and is never confirmed by this module.
    """
    headers = _headers()
    payload = {
        "staffer_id": -1,
        "business_id": barber.business_id,
        "service_variant_id": barber.service_variant_id,
        "meta": {
            "app_version": "3.0",
            "booking_source": "Undefined",
            "platform": "web",
            "device_type": "Desktop",
        },
    }
    data = _post("/drafts/create", payload, headers)
    draft_id = (data.get("appointment") or {}).get("id")
    if not draft_id:
        raise BooksyError(f"{barber.name}: no draft id in response")
    return draft_id, headers


def working_days(barber: Barber, start: date, end: date) -> dict[str, dict]:
    """Which days this barber is working, and roughly how full they are."""
    draft_id, headers = open_draft(barber)
    data = _post(
        f"/drafts/{draft_id}/calendar",
        {"start": start.isoformat(), "end": end.isoformat()},
        headers,
    )
    return data.get("calendar") or {}


def day_slots(barber: Barber, day: date) -> list[Slot]:
    """Open start times for this barber on one day."""
    draft_id, headers = open_draft(barber)
    data = _post(
        f"/drafts/{draft_id}/timeslots",
        {"start": day.isoformat(), "end": day.isoformat()},
        headers,
    )
    out: list[Slot] = []
    for iso_day, entries in (data.get("timeslots") or {}).items():
        for entry in entries:
            clock = entry.get("t")
            if not clock:
                continue
            out.append(Slot(barber, datetime.fromisoformat(f"{iso_day}T{clock}")))
    return sorted(out, key=lambda s: s.start)


def slots_in_range(
    barbers: list[Barber], start: date, end: date
) -> tuple[list[Slot], list[str]]:
    """Every open slot across every barber between start and end inclusive.

    Returns (slots, warnings) so a caller can tell "nobody is free" apart from
    "we could not reach Booksy" -- those must never be conflated, or the
    recurring job silently reports no availability when the API is down.
    """
    if (end - start).days > MAX_LEAD_DAYS:
        raise ValueError(f"range exceeds Booksy's {MAX_LEAD_DAYS}-day booking window")

    slots: list[Slot] = []
    warnings: list[str] = []
    for barber in barbers:
        try:
            calendar = working_days(barber, start, end)
        except BooksyError as exc:
            warnings.append(f"{barber.name}: calendar unavailable ({exc})")
            continue
        for iso_day, info in sorted(calendar.items()):
            if not info.get("working"):
                continue
            day = date.fromisoformat(iso_day)
            if not (start <= day <= end):
                continue
            try:
                slots.extend(day_slots(barber, day))
            except BooksyError as exc:
                warnings.append(f"{barber.name} {iso_day}: slots unavailable ({exc})")
            time.sleep(REQUEST_PACING)
    return sorted(slots, key=lambda s: (s.start, s.barber.name)), warnings


def _cmd_calendar(args: argparse.Namespace) -> int:
    barbers = load_barbers()
    start = date.today()
    end = start + timedelta(days=args.days)
    for barber in barbers:
        print(f"\n{barber.name}  ({barber.service_name} {barber.price}, {barber.duration_min}min)")
        try:
            calendar = working_days(barber, start, end)
        except BooksyError as exc:
            print(f"  !! {exc}")
            continue
        for iso_day, info in sorted(calendar.items()):
            if info.get("working"):
                parts = [k for k in ("morning", "afternoon", "evening") if info.get(k)]
                print(
                    f"  {date.fromisoformat(iso_day):%a %b %d}  "
                    f"{info.get('slots_marker', '?'):<7} {', '.join(parts)}"
                )
    return 0


def _cmd_slots(args: argparse.Namespace) -> int:
    barbers = load_barbers()
    start = date.fromisoformat(args.date or args.start)
    end = date.fromisoformat(args.date or args.end)
    slots, warnings = slots_in_range(barbers, start, end)

    if args.json:
        print(
            json.dumps(
                {
                    "slots": [
                        {
                            "start": s.start.isoformat(),
                            "end": s.end.isoformat(),
                            "barber": s.barber.name,
                            "price": s.barber.price,
                            "duration_min": s.barber.duration_min,
                            "url": s.barber.booking_url,
                        }
                        for s in slots
                    ],
                    "warnings": warnings,
                },
                indent=1,
            )
        )
        return 1 if warnings and not slots else 0

    current = None
    for slot in slots:
        if slot.start.date() != current:
            current = slot.start.date()
            print(f"\n=== {current:%A, %B %d} ===")
        print(f"  {slot}")
    if not slots:
        print("no open slots in range")
    for warning in warnings:
        print(f"!! {warning}", file=sys.stderr)
    return 1 if warnings and not slots else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read live Booksy availability.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    cal = sub.add_parser("calendar", help="which days each barber works")
    cal.add_argument("--days", type=int, default=30)
    cal.set_defaults(func=_cmd_calendar)

    slot = sub.add_parser("slots", help="open appointment times")
    slot.add_argument("--date", help="a single day (YYYY-MM-DD)")
    slot.add_argument("--from", dest="start", help="range start (YYYY-MM-DD)")
    slot.add_argument("--to", dest="end", help="range end (YYYY-MM-DD)")
    slot.add_argument("--json", action="store_true")
    slot.set_defaults(func=_cmd_slots)

    args = parser.parse_args(argv)
    if args.cmd == "slots" and not args.date and not (args.start and args.end):
        parser.error("slots needs --date, or both --from and --to")
    try:
        return args.func(args)
    except (BooksyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
