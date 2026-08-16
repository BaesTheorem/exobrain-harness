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
import urllib.request
from datetime import datetime
from pathlib import Path

# playwright is imported inside book() on purpose: verify_summary is the
# safety-critical logic and must stay unit-testable without a browser (the
# test runner's interpreter has no playwright).

import session
from browser import PROFILE_DIR, launch_profile

HERE = Path(__file__).resolve().parent
STEPS_DIR = HERE / "steps"
CONFIG_PATH = HERE / "config.json"
BOOKINGS_URL = "https://us.booksy.com/core/v2/customer_api/me/bookings"


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


def normalise(text: str) -> str:
    """Reduce a service name to just its words, lowercased.

    Booksy's service names disagree with themselves on punctuation in ways
    that silently break matching and look like a missing button: a typographic
    apostrophe in "Men's Haircut", a stray space in "(BEARD NOT INCLUDED )".
    Comparing only the alphanumeric words sidesteps the whole category instead
    of patching each variant as it turns up.
    """
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.lower()).split())


def visited_before(barber_name: str) -> bool:
    """Has Alex had a cut from this barber before, per the recorded history?

    Booksy asks this on the review screen and the honest answer matters: some
    barbers price or gate returning clients differently.
    """
    state_path = HERE / "state.json"
    if not state_path.exists():
        return False
    history = json.loads(state_path.read_text()).get("history") or []
    return any(entry.get("barber") == barber_name for entry in history)


def list_bookings() -> list[dict]:
    """Every appointment on the account, straight from Booksy."""
    req = urllib.request.Request(BOOKINGS_URL, headers=session.api_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read()).get("bookings") or []
    except Exception as exc:  # noqa: BLE001 - caller treats this as "unverified"
        raise BookingError(f"could not read bookings: {type(exc).__name__}") from exc


def find_booking(business_id: int, when: datetime) -> str | None:
    """The booking matching this slot, if the server actually has one.

    This exists because page text is not evidence. An earlier version decided
    a booking had succeeded by looking for the word "booked"/"appointment" in
    the final screen -- and the deposit/payment screen contains both, so a
    flow that never completed reported success. Only the account's own
    booking list settles it.
    """
    for booking in list_bookings():
        appt = booking.get("appointment") or booking
        biz = (appt.get("business") or {}).get("id")
        start = appt.get("booked_from") or ""
        if biz == business_id and start.startswith(when.strftime("%Y-%m-%dT%H:%M")):
            return f"{start} at {(appt.get('business') or {}).get('name')} ({appt.get('total')})"
    return None


BOOKING_DATE_RE = re.compile(
    r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2})\b"
)


def verify_summary(summary: str, barber: dict, when: datetime) -> list[str]:
    """Cross-check the confirmation screen against what we asked for.

    Returns the list of mismatches; empty means safe to confirm.

    This must read the *chosen* booking, not merely find the wanted values
    somewhere on screen. The first version searched the whole page for the day
    number and the time, which a month calendar grid (every day 1-31) and a
    slot list (every open time) satisfy trivially -- so it passed while the
    booking underneath had silently reverted to the draft's default date.
    Anchor on the summary's own "Weekday, Mon D" line and fail closed if that
    line is missing.
    """
    problems = []

    match = BOOKING_DATE_RE.search(summary)
    if not match:
        problems.append("no booking date line found on the confirmation screen")
    else:
        found = f"{match.group(1)}, {match.group(2)} {int(match.group(3))}"
        wanted = f"{when:%a}, {when:%b} {when.day}"
        if found != wanted:
            problems.append(f"booking shows {found!r}, wanted {wanted!r}")

    # The time must appear next to that date line, not merely in the slot list.
    tail = summary[match.end() : match.end() + 120] if match else ""
    h12 = f"{when:%-I:%M %p}"
    if h12.lower() not in tail.lower():
        problems.append(f"time {h12} not shown with the booking date")

    price = barber["price"].replace("$", "").split(".")[0]
    if price not in summary:
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
        ctx = launch_profile(p, headless=True)
        # The profile itself is never logged in -- hCaptcha blocks automated
        # login. Inject the session Alex established by hand instead.
        ctx.add_cookies(session.playwright_cookies())
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
            # Booksy renders a mobile and a desktop copy of the menu, so the
            # same service appears twice and only one copy is visible. Clicking
            # the hidden twin times out with a confusing "not visible" error.
            buttons = page.locator('button:has-text("Book")')
            wanted = normalise(barber["service_name"])
            target = None
            for i in range(buttons.count()):
                button = buttons.nth(i)
                if not button.is_visible():
                    continue
                # The service name and the Book button live in different
                # columns; only the enclosing <li> holds both. The nearest div
                # ancestor contains just price/duration/Book, so matching on it
                # never sees the name.
                row = button.locator("xpath=ancestor::li[1]")
                try:
                    if wanted in normalise(row.inner_text(timeout=2000)):
                        target = button
                        break
                except Exception:  # noqa: BLE001 - some rows have no readable text
                    continue
            if target is None:
                raise BookingError(f"could not find a Book button for {barber['service_name']!r}")

            target.scroll_into_view_if_needed(timeout=10000)
            target.click(timeout=15000)
            page.wait_for_timeout(8000)
            _shot(page, "2-booking-panel")

            # The whole booking UI lives in the widget-2024 iframe. Reading or
            # clicking on the main frame silently does nothing here.
            frame = None
            for _ in range(20):
                frame = next((f for f in page.frames if "widget-2024" in f.url), None)
                if frame:
                    break
                page.wait_for_timeout(1000)
            if frame is None:
                raise BookingError("booking widget iframe never appeared")

            # Booksy opens an add-ons upsell over the date picker. It intercepts
            # every click until dismissed, which looks like a dead calendar.
            if "Add-ons available" in (frame.evaluate("() => document.body.innerText") or ""):
                for sel in ['button:has-text("Continue")', 'button:has-text("Skip")']:
                    try:
                        frame.locator(sel).last.click(timeout=6000)
                        print("dismissed the add-ons step")
                        break
                    except Exception:  # noqa: BLE001 - label varies
                        continue
                page.wait_for_timeout(4000)

            # The date strip is a 7-day Swiper, so a target two weeks out needs
            # the month calendar. That grid also renders the adjacent months'
            # spill-over days with the SAME number, marked -inactive. Clicking
            # the first matching "29" hits July 29, does nothing, and leaves
            # the draft on its default date -- while the slot list still looks
            # right, because the default day has the same times free. Pick the
            # cell by availability class, not by text order.
            frame.locator('[data-testid="calendar-toggle"]').first.click(timeout=10000)
            page.wait_for_timeout(3500)
            clicked = frame.evaluate(
                """(day) => {
                    const cards = [...document.querySelectorAll('[data-testid="calendar-card"]')];
                    const live = cards.filter(c => {
                        const cls = (c.className || '').toString();
                        if (/-not-available|-inactive|-empty/.test(cls)) return false;
                        return c.textContent.trim() === String(day);
                    });
                    if (!live.length) return false;
                    live[0].click();
                    return true;
                }""",
                when.day,
            )
            if not clicked:
                raise BookingError(
                    f"{when:%B %-d} is not selectable in the calendar "
                    "(fully booked, closed, or outside the booking window)"
                )
            print(f"picked {when:%B %-d} from the month calendar")
            page.wait_for_timeout(5000)
            _shot(page, "3-date-picked")

            picked = False
            for label in (f"{when:%-I:%M %p}", f"{when:%H:%M}"):
                try:
                    frame.get_by_text(label, exact=True).first.click(timeout=8000)
                    picked = True
                    print(f"selected {label}")
                    break
                except Exception:  # noqa: BLE001 - chip format varies
                    continue
            if not picked:
                raise BookingError(f"{when:%-I:%M %p} was not offered; slot may be gone")

            page.wait_for_timeout(4000)
            _shot(page, "4-slot-selected")

            # Advance to the booking-details screen BEFORE verifying. The
            # picker screen has no "Weekday, Mon D" summary line -- it only
            # shows a calendar grid and a slot list, which is precisely why an
            # earlier version could "verify" a date the flow had already
            # reverted. The details screen is the first place the chosen
            # booking is stated, and the last place before money moves.
            for sel in ['button:has-text("Continue")', 'button:has-text("Next")']:
                try:
                    frame.locator(sel).last.click(timeout=8000)
                    print(f"advanced via {sel}")
                    break
                except Exception:  # noqa: BLE001 - button label varies
                    continue
            page.wait_for_timeout(8000)

            # Booksy asks first-time clients "Have you used the services of X
            # before?" on the review screen. The modal sits over Confirm & Book
            # and swallows the click, so the run looks like it confirmed and
            # nothing is booked. Answer it from the recorded history.
            answer = "Yes" if visited_before(barber["name"]) else "No"
            try:
                if "before?" in (frame.evaluate("() => document.body.innerText") or ""):
                    frame.get_by_role("button", name=answer, exact=True).first.click(timeout=6000)
                    print(f"answered the returning-client prompt: {answer}")
                    page.wait_for_timeout(4000)
            except Exception as exc:  # noqa: BLE001 - prompt is not always shown
                print(f"  (no returning-client prompt: {type(exc).__name__})")

            _shot(page, "5-booking-details")

            summary = frame.evaluate("() => document.body.innerText") or ""
            problems = verify_summary(summary, barber, when)
            if problems:
                for problem in problems:
                    print(f"  MISMATCH: {problem}")
                raise BookingError("booking details do not match the requested slot")
            print("booking details match the requested slot")

            deposit = "deposit" in summary.lower() or "add card" in summary.lower()
            if deposit:
                print("  note: this barber wants a deposit/card before confirming")

            if not confirm:
                print("\ndry run: verified, stopping before confirm. Use --confirm to book.")
                return 0

            # Match the real button exactly. A loose has-text("Confirm") also
            # matches copy in the cancellation-policy panel, and .last picked
            # that instead -- the run reported "confirmed" having clicked
            # nothing that books.
            confirmed = False
            for sel in [
                'button:has-text("Confirm & Book")',
                'button:has-text("Confirm and Book")',
                'button:has-text("Book appointment")',
            ]:
                button = frame.locator(sel)
                if button.count() == 0:
                    continue
                try:
                    button.first.click(timeout=8000)
                    print(f"clicked {sel}")
                    confirmed = True
                    break
                except Exception:  # noqa: BLE001 - try the next label
                    continue
            if not confirmed:
                raise BookingError("could not find the Confirm & Book button")

            page.wait_for_timeout(5000)

            # The returning-client prompt can appear after Confirm & Book and
            # blocks completion until answered.
            try:
                if "before?" in (frame.evaluate("() => document.body.innerText") or ""):
                    answer = "Yes" if visited_before(barber["name"]) else "No"
                    frame.get_by_role("button", name=answer, exact=True).first.click(timeout=6000)
                    print(f"answered the returning-client prompt: {answer}")
                    page.wait_for_timeout(8000)
            except Exception as exc:  # noqa: BLE001 - prompt is optional
                print(f"  (returning-client prompt: {type(exc).__name__})")

            page.wait_for_timeout(6000)
            _shot(page, "6-confirmed")

            print("\n--- verifying against the server ---")
            actual = find_booking(business_id, when)
            if actual is None:
                raise BookingError(
                    "no matching booking exists on the account. The flow did not "
                    "complete (a deposit/card step usually causes this). "
                    "See steps/6-confirmed.png"
                )
            print(f"Booked: {actual}")
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
