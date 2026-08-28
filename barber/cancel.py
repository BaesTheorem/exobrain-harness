#!/usr/bin/env python3
"""Cancel a haircut on Booksy using the saved login session.

Drives the appointment page in the account area, which (unlike booking) lives
on the main frame with plain CANCEL/CHANGE buttons -- no widget iframe. The
flow is three screens deep: CANCEL opens a "Reason for cancellation" survey,
and submitting (or skipping) that opens a "Prefer to reschedule?" retention
modal whose "Cancel appointment" button is the only thing that actually
cancels. Stopping anywhere before that last click leaves the appointment
untouched (verified against a live booking).

INVARIANTS (an edit must not break these):
- Dry run is the default. Cancelling is destructive and some barbers charge
  late-cancellation fees, so the confirming path must always be opt-in via
  --confirm.
- Before clicking CANCEL, the on-page appointment is matched against the slot
  we were asked to cancel. Never cancel a screen we have not verified.
- Success is decided by the server (the booking's status in /me/bookings),
  never by page text.

Usage:
    python3 cancel.py --barber 1335772 --at "2026-08-29 11:00"            # dry run
    python3 cancel.py --barber 1335772 --at "2026-08-29 11:00" --confirm  # for real
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# playwright is imported inside cancel() on purpose, mirroring book.py: the
# matching logic stays unit-testable without a browser.

import session
from book import BookingError, list_bookings, load_barber
from browser import PROFILE_DIR, launch_profile

HERE = Path(__file__).resolve().parent
STEPS_DIR = HERE / "steps"

# Statuses Booksy uses for a live appointment; anything else is not cancellable
# and "already gone" must not be reported as a successful cancellation.
ACTIVE_STATUSES = {"A", "P"}  # accepted, pending


def find_active_booking(business_id: int, when: datetime) -> dict | None:
    """The live appointment matching this slot, or None."""
    for booking in list_bookings():
        appt = booking.get("appointment") or booking
        biz = (appt.get("business") or {}).get("id")
        start = appt.get("booked_from") or ""
        status = appt.get("status")
        if (
            biz == business_id
            and start.startswith(when.strftime("%Y-%m-%dT%H:%M"))
            and status in ACTIVE_STATUSES
        ):
            return appt
    return None


def _shot(page, name: str) -> None:
    STEPS_DIR.mkdir(exist_ok=True)
    page.screenshot(path=str(STEPS_DIR / f"{name}.png"), full_page=True)


def cancel(business_id: int, when: datetime, confirm: bool) -> int:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 - see module header

    barber = load_barber(business_id)
    if not PROFILE_DIR.exists():
        raise BookingError("no saved Booksy session; run: python3 login.py")

    print(f"barber : {barber['name']}")
    print(f"slot   : {when:%A, %B %d %Y at %-I:%M %p}")
    print(f"mode   : {'CONFIRM (real cancellation)' if confirm else 'dry run'}\n")

    appt = find_active_booking(business_id, when)
    if appt is None:
        raise BookingError(
            "no active booking matches that barber and time; nothing to cancel. "
            "Check: the appointment may already be cancelled, or the time is wrong."
        )
    uid = appt.get("appointment_uid") or appt.get("id")
    print(f"found booking {uid} ({appt.get('booked_from')}, status {appt.get('status')})")

    url = f"https://booksy.com/en-us/account/appointment/{uid}"

    with sync_playwright() as p:
        ctx = launch_profile(p, headless=True)
        # Same mechanism as book.py: the profile itself is never logged in;
        # inject the session Alex established by hand.
        ctx.add_cookies(session.playwright_cookies())
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)
            _shot(page, "cancel-1-appointment")

            body = page.evaluate("() => document.body.innerText") or ""
            if "Log In / Sign Up" in body:
                raise BookingError("session expired; re-run: python3 login.py")

            # Verify the page shows the appointment we mean to cancel before
            # touching anything. The date/time header reads "11:00 AM • Sat,
            # Aug 29"; require both halves.
            wanted_time = f"{when:%-I:%M %p}"
            wanted_date = f"{when:%a}, {when:%b} {when.day}"
            problems = [
                f"{label} {value!r} not on the appointment page"
                for label, value in (("time", wanted_time), ("date", wanted_date))
                if value not in body
            ]
            if problems:
                for problem in problems:
                    print(f"  MISMATCH: {problem}")
                raise BookingError("appointment page does not match the requested slot")
            print("appointment page matches the requested slot")

            cancel_button = page.locator('button:has-text("CANCEL")')
            if cancel_button.count() == 0:
                raise BookingError(
                    "no CANCEL button on the appointment page (past the "
                    "cancellation window, or Booksy changed the layout)"
                )

            if not confirm:
                print("\ndry run: verified, stopping before CANCEL. Use --confirm to cancel.")
                return 0

            cancel_button.first.click(timeout=10000)
            page.wait_for_timeout(4000)
            _shot(page, "cancel-2-reason-survey")

            # The reason survey is what actually executes the cancellation.
            # Answer honestly when the stock reason fits; SKIP works too and
            # is the fallback when the survey copy shifts.
            survey = page.evaluate("() => document.body.innerText") or ""
            if "Reason for cancellation" in survey:
                try:
                    page.get_by_text("I need to reschedule", exact=True).first.click(timeout=5000)
                    page.locator('button:has-text("SUBMIT")').first.click(timeout=5000)
                    print("submitted the cancellation survey (reason: reschedule)")
                except Exception:  # noqa: BLE001 - survey options vary
                    page.locator('button:has-text("SKIP")').first.click(timeout=5000)
                    print("skipped the cancellation survey")
            page.wait_for_timeout(4000)
            _shot(page, "cancel-3-retention-modal")

            # After the survey, a "Prefer to reschedule?" retention modal makes
            # the real ask: "Are you sure you want to cancel this appointment?"
            # with Reschedule/Cancel buttons. Nothing is cancelled until
            # "Cancel appointment" is clicked here. It restates the slot, so
            # re-verify before the final click.
            modal = page.evaluate("() => document.body.innerText") or ""
            if "Cancel appointment" in modal:
                restated = f"{when:%A}, {when:%b} {when.day}, {when:%Y}, {when:%-I:%M %p}"
                if restated not in modal:
                    raise BookingError(
                        f"the confirmation modal does not restate {restated!r}; "
                        "aborting rather than cancelling an unverified appointment"
                    )
                page.locator('button:has-text("Cancel appointment")').first.click(timeout=8000)
                print("confirmed on the retention modal")
            page.wait_for_timeout(6000)
            _shot(page, "cancel-4-done")

            print("\n--- verifying against the server ---")
            still_there = find_active_booking(business_id, when)
            if still_there is not None:
                raise BookingError(
                    "the booking is still active on the account; the cancellation "
                    "did not complete. See steps/cancel-4-done.png"
                )
            print(f"Cancelled: {when:%A, %B %d} at {when:%-I:%M %p} with {barber['name']}")
            return 0
        finally:
            ctx.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cancel a haircut on Booksy.")
    parser.add_argument("--barber", type=int, required=True, help="Booksy business_id")
    parser.add_argument("--at", required=True, help='"YYYY-MM-DD HH:MM"')
    parser.add_argument(
        "--confirm", action="store_true", help="actually cancel (default is a dry run)"
    )
    args = parser.parse_args(argv)
    try:
        return cancel(args.barber, datetime.strptime(args.at, "%Y-%m-%d %H:%M"), args.confirm)
    except BookingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
