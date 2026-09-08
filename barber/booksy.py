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
- best_slot only ever returns a deposit-free barber. Alex's rule: automation
  may book a barber who takes no deposit and nobody else, because paying one
  means storing a card, which this package will not do. A barber whose deposit
  is unknown counts as requiring one -- unknown fails closed, never open.

Usage:
    python3 booksy.py calendar --days 30
    python3 booksy.py slots --date 2026-08-29
    python3 booksy.py slots --from 2026-08-28 --to 2026-09-02 --json
    python3 booksy.py deposits --update
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
    deposit: float | None = None

    @property
    def booking_url(self) -> str:
        return f"https://booksy.com/en-us/{self.url}"

    @property
    def auto_bookable(self) -> bool:
        """May the automation book this barber unattended?

        Only if they take no deposit. A deposit means Booksy swaps "Confirm &
        Book" for "Add card", which no unattended run can get past, so ranking
        one first does not produce a worse booking -- it produces no booking at
        all, six weeks in a row. `None` means we could not read the deposit
        (the barber 404s, or the sweep failed), and that has to count as
        requiring one: the failure mode of guessing wrong here is a card
        prompt, so unknown fails closed.
        """
        return self.deposit == 0

    @property
    def deposit_label(self) -> str:
        """How to describe why this barber is off the automated path."""
        if self.deposit is None:
            return "deposit unknown"
        return f"${self.deposit:.2f} deposit"

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
        deposit = "" if self.barber.auto_bookable else f" [{self.barber.deposit_label}]"
        return (
            f"{self.start:%a %b %d  %-I:%M %p}-{self.end:%-I:%M %p}  "
            f"{self.barber.name} ({self.barber.price}){deposit}"
        )


def load_barbers(path: Path = CONFIG_PATH, auto_bookable_only: bool = False) -> list[Barber]:
    """Barbers, best-rated first.

    Reading availability for a deposit barber is still useful -- Alex may want
    to book one by hand -- so the default returns everyone. Anything on the
    automated path passes auto_bookable_only=True.
    """
    cfg = json.loads(path.read_text())
    barbers = [Barber(**b) for b in cfg["barbers"]]
    if auto_bookable_only:
        barbers = [b for b in barbers if b.auto_bookable]
    return sorted(barbers, key=lambda b: b.rank_key, reverse=True)


def best_slot(slots: list[Slot], busy: list[tuple[datetime, datetime]] | None = None) -> Slot | None:
    """Pick the slot with the best-rated deposit-free barber; earliest wins ties.

    Alex's rule, in order: never a barber who takes a deposit, then the highest
    rated of whoever is left. Rank by barber before date -- the other way round
    and a marginally earlier slot keeps beating a better barber.

    The deposit filter comes first and is not a tiebreak. Ranking on reviews
    alone put an 82-review barber at the top of the list every cycle, and every
    cycle the run walked the whole booking flow and died on her card prompt.
    """
    free = [
        s for s in slots if s.barber.auto_bookable and not _conflicts(s, busy or [])
    ]
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


def _get(path: str, headers: dict[str, str]) -> dict:
    """GET from Booksy, with the same never-raise-bare contract as _post."""
    req = urllib.request.Request(API + path, headers=headers, method="GET")
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


def read_deposit(barber: Barber) -> float:
    """The deposit Booksy will demand for this barber's *configured* service.

    Deposits are set per service variant, not per business: Dmilly charges $20
    on a men's haircut and $85 on a colour, and every barber carries the same
    boilerplate cancellation-policy text at the business level. So the business
    flags cannot answer this -- only the variant we actually book can, which is
    why this matches on service_variant_id and raises rather than guessing when
    the variant is absent.
    """
    data = _get(
        f"/businesses/{barber.business_id}?reviews_page=1&reviews_per_page=1", _headers()
    )
    business = data.get("business") or {}
    categories = business.get("service_categories") or []
    for category in categories:
        for service in category.get("services") or []:
            for variant in service.get("variants") or []:
                if variant.get("id") == barber.service_variant_id:
                    prepayment = variant.get("prepayment")
                    if prepayment is None:
                        raise BooksyError(
                            f"{barber.name}: variant {barber.service_variant_id} "
                            "has no prepayment field"
                        )
                    return float(prepayment)
    raise BooksyError(
        f"{barber.name}: service variant {barber.service_variant_id} not on the menu"
    )


def refresh_deposits(path: Path = CONFIG_PATH) -> list[tuple[str, float | None, str]]:
    """Re-read every barber's deposit from Booksy and write it into config.

    Returns (name, deposit, note) per barber. A barber we cannot read is stored
    as null, which auto_bookable treats as "requires a deposit".
    """
    cfg = json.loads(path.read_text())
    results: list[tuple[str, float | None, str]] = []
    for entry in cfg["barbers"]:
        barber = Barber(**entry)
        try:
            deposit = read_deposit(barber)
            note = "no deposit" if deposit == 0 else f"${deposit:.2f} deposit"
        except BooksyError as exc:
            deposit, note = None, f"unreadable ({exc})"
        entry["deposit"] = deposit
        results.append((barber.name, deposit, note))
        time.sleep(REQUEST_PACING)
    path.write_text(json.dumps(cfg, indent=2) + "\n")
    return results


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
                            "deposit": s.barber.deposit,
                            "auto_bookable": s.barber.auto_bookable,
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


def _cmd_deposits(args: argparse.Namespace) -> int:
    if args.update:
        rows = refresh_deposits()
        print("config.json updated.\n")
    else:
        rows = [
            (b.name, b.deposit, "no deposit" if b.auto_bookable else b.deposit_label)
            for b in load_barbers()
        ]
    for name, deposit, note in rows:
        mark = "auto-bookable" if deposit == 0 else "MANUAL ONLY"
        print(f"  {name:38} {note:<24} {mark}")
    return 0


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

    dep = sub.add_parser("deposits", help="who takes a deposit (and so cannot be auto-booked)")
    dep.add_argument("--update", action="store_true", help="re-read from Booksy and save")
    dep.set_defaults(func=_cmd_deposits)

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
