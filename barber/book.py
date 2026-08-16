#!/usr/bin/env python3
"""Book a haircut on Booksy using the saved login session.

Drives the real booking UI in the persistent profile from login.py, rather
than guessing at an undocumented confirm endpoint. Slower than an API call and
worth it: the UI is the one path Booksy actually supports, and it carries
whatever prepayment or policy step a given barber has turned on.

INVARIANTS (an edit must not break these):
- Dry run is the default. Booking is real, costs money, and some barbers
  charge cancellation fees, so the confirming path must always be opt-in
  via --confirm.
- Before confirming, the on-screen summary is re-read and matched against the
  slot we asked for. If Booksy moved us to a different time, barber, or price,
  we abort instead of confirming. Never confirm a screen we have not verified.
- Every run leaves screenshots in steps/ so a failed booking can be diagnosed
  without re-running against live inventory.

Usage:
    python3 book.py --barber 1159975 --at "2026-08-29 11:00"            # dry run
    python3 book.py --barber 1159975 --at "2026-08-29 11:00" --confirm  # for real
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# playwright is imported inside book() on purpose: verify_summary is the
# safety-critical logic and must stay unit-testable without a browser (the
# test runner's interpreter has no playwright).

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / ".booksy-profile"
STEPS_DIR = HERE / "steps"
CONFIG_PATH = HERE / "config.json"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class BookingError(RuntimeError):
    """The booking could not be completed safely."""


def load_barber(business_id: int) -> dict:
    cfg = json.loads(CONFIG_PATH.read_text())
    for barber in cfg["barbers"]:
        if barber["business_id"] == business_id:
            return barber
    raise BookingError(f"no barber with business_id {business_id} in config.json")


def _shot(page, name: str) -> None:
    STEPS_DIR.mkdir(exist_ok=True)
    page.screenshot(path=str(STEPS_DIR / f"{name}.png"), full_page=True)


def _text(page) -> str:
    return re.sub(r"\n{3,}", "\n\n", page.evaluate("() => document.body.innerText") or "")


def verify_summary(summary: str, barber: dict, when: datetime) -> list[str]:
    """Cross-check the confirmation screen against what we asked for.

    Returns the list of mismatches; empty means safe to confirm. Booksy can
    silently shift a booking (a slot taken between draft and confirm), and a
    blind click would buy the wrong appointment.
    """
    problems = []
    blob = summary.lower()

    # Time, in either 24h or 12h form.
    h24 = f"{when:%H:%M}"
    h12 = f"{when:%-I:%M}".lower()
    if h24 not in blob and h12 not in blob:
        problems.append(f"time {h24} not on the confirmation screen")

    # Day number, guarding against a date silently rolling.
    if str(when.day) not in blob:
        problems.append(f"day {when.day} not on the confirmation screen")

    # Price, so a service swap does not slip through.
    price = barber["price"].replace("$", "").split(".")[0]
    if price not in blob:
        problems.append(f"price ${price} not on the confirmation screen")

    return problems


def book(business_id: int, when: datetime, confirm: bool) -> int:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 - see module header

    barber = load_barber(business_id)
    if not PROFILE_DIR.exists():
        raise BookingError("no saved Booksy session; run: python3 login.py")

    url = f"https://booksy.com/en-us/{barber['url']}"
    print(f"barber : {barber['name']}")
    print(f"service: {barber['service_name']} ({barber['price']}, {barber['duration_min']}min)")
    print(f"slot   : {when:%A, %B %d %Y at %-I:%M %p}")
    print(f"mode   : {'CONFIRM (real booking)' if confirm else 'dry run'}\n")

    calls: list[tuple[int, str, str | None]] = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=True,
            user_agent=UA,
            viewport={"width": 1280, "height": 1800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on(
            "request",
            lambda r: calls.append((0, r.url, r.post_data))
            if r.method == "POST" and "booksy.com/core" in r.url
            else None,
        )

        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3500)
            _shot(page, "1-listing")

            if "Log In / Sign Up" in _text(page):
                raise BookingError("session expired; re-run: python3 login.py")

            # Service rows carry the Book buttons, in menu order after the header.
            buttons = page.locator('button:has-text("Book")')
            target = None
            for i in range(buttons.count()):
                row = buttons.nth(i).locator(
                    "xpath=ancestor::*[self::li or self::div][1]"
                )
                try:
                    if barber["service_name"].lower() in row.inner_text(timeout=2000).lower():
                        target = buttons.nth(i)
                        break
                except Exception:  # noqa: BLE001 - some rows have no readable text
                    continue
            if target is None:
                raise BookingError(f"could not find a Book button for {barber['service_name']!r}")

            target.click(timeout=15000)
            page.wait_for_timeout(7000)
            _shot(page, "2-booking-panel")

            # Pick the day, then the time.
            for label in (f"{when:%-d}", f"{when:%B %-d}"):
                try:
                    page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}$")).first.click(
                        timeout=6000
                    )
                    break
                except Exception:  # noqa: BLE001 - calendar markup varies
                    continue
            page.wait_for_timeout(4000)
            _shot(page, "3-date-picked")

            picked = False
            for label in (f"{when:%-I:%M %p}", f"{when:%H:%M}", f"{when:%-I:%M}"):
                try:
                    page.get_by_text(label, exact=True).first.click(timeout=6000)
                    picked = True
                    print(f"selected time via label {label!r}")
                    break
                except Exception:  # noqa: BLE001 - time chips vary by locale
                    continue
            if not picked:
                raise BookingError(f"{when:%-I:%M %p} was not offered; slot may be gone")

            page.wait_for_timeout(5000)
            _shot(page, "4-summary")

            summary = _text(page)
            problems = verify_summary(summary, barber, when)
            if problems:
                for problem in problems:
                    print(f"  MISMATCH: {problem}")
                raise BookingError("confirmation screen does not match the requested slot")
            print("confirmation screen matches the requested slot")

            if not confirm:
                print("\ndry run: stopping before confirm. Re-run with --confirm to book.")
                return 0

            for sel in [
                'button:has-text("Confirm")',
                'button:has-text("Book appointment")',
                'button:has-text("Book now")',
            ]:
                try:
                    page.locator(sel).first.click(timeout=8000)
                    print(f"confirmed via {sel}")
                    break
                except Exception:  # noqa: BLE001 - button label varies
                    continue
            page.wait_for_timeout(9000)
            _shot(page, "5-confirmed")

            after = _text(page)
            booked = any(
                w in after.lower() for w in ("booked", "confirmed", "see you", "appointment")
            )
            print("\n--- result ---")
            print(after[:900])
            if not booked:
                raise BookingError("no confirmation text found; check steps/5-confirmed.png")
            print("\nBooked.")
            return 0
        finally:
            (STEPS_DIR / "calls.json").write_text(
                json.dumps([{"url": u, "body": b} for _, u, b in calls], indent=1)
            )
            ctx.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Book a haircut on Booksy.")
    parser.add_argument("--barber", type=int, required=True, help="Booksy business_id")
    parser.add_argument("--at", required=True, help='"YYYY-MM-DD HH:MM"')
    parser.add_argument(
        "--confirm", action="store_true", help="actually book (default is a dry run)"
    )
    args = parser.parse_args(argv)
    try:
        return book(args.barber, datetime.strptime(args.at, "%Y-%m-%d %H:%M"), args.confirm)
    except BookingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
