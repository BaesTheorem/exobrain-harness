"""Tests for the booking guardrail and the barber ranking rule.

The confirm step spends real money, so verify_summary is the piece that has to
be right: it is the only thing standing between an automated click and buying
the wrong appointment.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BARBER = Path(__file__).resolve().parent.parent / "barber"


def _load(name: str, filename: str):
    # book.py imports its sibling browser.py, so the package dir must be importable.
    if str(BARBER) not in sys.path:
        sys.path.insert(0, str(BARBER))
    spec = importlib.util.spec_from_file_location(name, BARBER / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def book():
    return _load("barber_book", "book.py")


@pytest.fixture(scope="module")
def booksy():
    return _load("barber_booksy", "booksy.py")


DMILLY = {
    "name": "Dmilly Cutz",
    "price": "$40.00",
    "service_name": "Men's Haircut no facial hair",
    "duration_min": 45,
}
WHEN = datetime(2026, 8, 29, 11, 0)


GOOD = "Your booking details\nSat, Aug 29 • 11:00 AM\nDmilly Cutz\nMen's Haircut\n$40.00"


def test_matching_summary_passes(book):
    assert book.verify_summary(GOOD, DMILLY, WHEN) == []


def test_wrong_time_is_caught(book):
    """Booksy shifting us to another slot must abort, not confirm."""
    bad = "Your booking details\nSat, Aug 29 • 2:30 PM\n$40.00"
    assert any("time" in p for p in book.verify_summary(bad, DMILLY, WHEN))


def test_wrong_day_is_caught(book):
    bad = "Your booking details\nSun, Aug 30 • 11:00 AM\n$40.00"
    assert any("wanted" in p for p in book.verify_summary(bad, DMILLY, WHEN))


def test_reverted_date_is_caught(book):
    """The real regression: the flow silently fell back to the draft default.

    Aug 18 was the draft's default day, and the old check passed because the
    month-calendar grid contained a "29" somewhere on the page.
    """
    reverted = (
        "Select Date & Time\nAugust 2026\n"
        + " ".join(str(d) for d in range(1, 32))  # the calendar grid
        + "\n9:00 AM 10:00 AM 11:00 AM 12:00 PM\n"  # the slot list
        + "Your booking details\nTue, Aug 18 • 11:00 AM\n$40.00"
    )
    problems = book.verify_summary(reverted, DMILLY, WHEN)
    assert problems, "a reverted booking date must never verify"
    assert any("Aug 18" in p for p in problems)


def test_calendar_grid_alone_does_not_verify(book):
    """Day numbers and slot times on screen are not a booking."""
    grid_only = (
        "August 2026\n" + " ".join(str(d) for d in range(1, 32)) + "\n11:00 AM\n$40.00"
    )
    assert book.verify_summary(grid_only, DMILLY, WHEN)


def test_wrong_price_is_caught(book):
    """A silent service swap costs money and must abort."""
    bad = "Your booking details\nSat, Aug 29 • 11:00 AM\n$100.00"
    assert any("price" in p for p in book.verify_summary(bad, DMILLY, WHEN))


def test_empty_summary_is_caught(book):
    """A blank screen must never read as agreement."""
    assert len(book.verify_summary("", DMILLY, WHEN)) == 3


# --- ranking ------------------------------------------------------------


def _barber(booksy, name, stars, reviews, business_id=1, deposit: float | None = 0.0):
    return booksy.Barber(
        business_id=business_id,
        name=name,
        service_name="Haircut",
        service_variant_id=1,
        price="$40.00",
        duration_min=30,
        url="x",
        stars=stars,
        reviews=reviews,
        deposit=deposit,
    )


def test_best_slot_prefers_higher_rated_over_earlier(booksy):
    """Alex's rule: the better barber wins even if someone else is free sooner."""
    weak = _barber(booksy, "Rookie", 5.0, 1, 1)
    strong = _barber(booksy, "Veteran", 5.0, 82, 2)
    slots = [
        booksy.Slot(weak, datetime(2026, 8, 29, 9, 0)),
        booksy.Slot(strong, datetime(2026, 8, 29, 16, 0)),
    ]
    assert booksy.best_slot(slots).barber.name == "Veteran"


def test_best_slot_breaks_ties_by_earliest(booksy):
    strong = _barber(booksy, "Veteran", 5.0, 82, 2)
    slots = [
        booksy.Slot(strong, datetime(2026, 8, 29, 16, 0)),
        booksy.Slot(strong, datetime(2026, 8, 29, 9, 0)),
    ]
    assert booksy.best_slot(slots).start.hour == 9


def test_best_slot_respects_busy_blocks_with_travel(booksy):
    """A slot butting up against a commitment is not actually free."""
    strong = _barber(booksy, "Veteran", 5.0, 82, 2)
    weak = _barber(booksy, "Rookie", 5.0, 1, 1)
    busy = [(datetime(2026, 8, 29, 13, 0), datetime(2026, 8, 29, 17, 0))]
    slots = [
        booksy.Slot(strong, datetime(2026, 8, 29, 12, 45)),  # collides via travel
        booksy.Slot(weak, datetime(2026, 8, 29, 10, 0)),
    ]
    chosen = booksy.best_slot(slots, busy)
    assert chosen.barber.name == "Rookie"
    assert chosen.start.hour == 10


def test_best_slot_returns_none_when_nothing_fits(booksy):
    strong = _barber(booksy, "Veteran", 5.0, 82, 2)
    busy = [(datetime(2026, 8, 29, 0, 0), datetime(2026, 8, 30, 0, 0))]
    slots = [booksy.Slot(strong, datetime(2026, 8, 29, 11, 0))]
    assert booksy.best_slot(slots, busy) is None


def test_slot_end_uses_service_duration(booksy):
    strong = _barber(booksy, "Veteran", 5.0, 82, 2)
    slot = booksy.Slot(strong, datetime(2026, 8, 29, 11, 0))
    assert slot.end - slot.start == timedelta(minutes=30)


# --- the deposit gate ---------------------------------------------------


def test_deposit_barber_never_wins_however_good(booksy):
    """The actual regression: 82 reviews kept beating a barber we can pay.

    Every cycle the routine picked Dmilly on review count, drove the whole
    booking flow, and hit her "Add card" screen. A better barber we cannot
    check out with is worth less than a worse barber we can.
    """
    deposit = _barber(booksy, "Dmilly", 5.0, 82, 1, deposit=20.0)
    free = _barber(booksy, "Troy", 5.0, 35, 2, deposit=0.0)
    slots = [
        booksy.Slot(deposit, datetime(2026, 8, 29, 9, 0)),
        booksy.Slot(free, datetime(2026, 8, 29, 16, 0)),
    ]
    assert booksy.best_slot(slots).barber.name == "Troy"


def test_unknown_deposit_fails_closed(booksy):
    """A barber we could not read is not a barber we may book.

    Xay's business 404s, so his deposit stores as null. Treating unknown as
    zero would send an unattended run at a possible card prompt.
    """
    unknown = _barber(booksy, "Xay", 5.0, 1, 1, deposit=None)
    assert not unknown.auto_bookable
    slots = [booksy.Slot(unknown, datetime(2026, 8, 29, 9, 0))]
    assert booksy.best_slot(slots) is None


def test_all_deposit_barbers_means_no_slot(booksy):
    """No eligible barber must read as "nothing bookable", not "book anyway"."""
    a = _barber(booksy, "Dmilly", 5.0, 82, 1, deposit=20.0)
    b = _barber(booksy, "Nick", 5.0, 14, 2, deposit=15.0)
    slots = [
        booksy.Slot(a, datetime(2026, 8, 29, 9, 0)),
        booksy.Slot(b, datetime(2026, 8, 29, 10, 0)),
    ]
    assert booksy.best_slot(slots) is None


def test_load_barbers_can_filter_to_auto_bookable(booksy, tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "barbers": [
                    {
                        "business_id": 1,
                        "name": "Dmilly",
                        "service_name": "Haircut",
                        "service_variant_id": 1,
                        "price": "$40.00",
                        "duration_min": 45,
                        "url": "x",
                        "stars": 5.0,
                        "reviews": 82,
                        "deposit": 20.0,
                    },
                    {
                        "business_id": 2,
                        "name": "Troy",
                        "service_name": "Haircut",
                        "service_variant_id": 2,
                        "price": "$40.00",
                        "duration_min": 45,
                        "url": "y",
                        "stars": 5.0,
                        "reviews": 35,
                        "deposit": 0.0,
                    },
                ]
            }
        )
    )
    everyone = booksy.load_barbers(config)
    assert [b.name for b in everyone] == ["Dmilly", "Troy"]
    assert [b.name for b in booksy.load_barbers(config, auto_bookable_only=True)] == ["Troy"]


def test_read_deposit_matches_the_configured_variant(booksy, monkeypatch):
    """Deposits are per service variant, so the wrong variant is the wrong answer.

    Dmilly charges $20 for a haircut and $85 for colour off the same menu.
    Reading the first variant on the page would call her deposit-free.
    """
    barber = _barber(booksy, "Dmilly", 5.0, 82, 1, deposit=None)
    payload = {
        "business": {
            "service_categories": [
                {
                    "services": [
                        {"name": "Colour", "variants": [{"id": 999, "prepayment": 0.0}]},
                        {"name": "Haircut", "variants": [{"id": 1, "prepayment": 20.0}]},
                    ]
                }
            ]
        }
    }
    monkeypatch.setattr(booksy, "_get", lambda path, headers: payload)
    assert booksy.read_deposit(barber) == 20.0


def test_read_deposit_raises_when_the_variant_is_gone(booksy, monkeypatch):
    """A missing variant must raise, not return 0.0 and authorise a booking."""
    barber = _barber(booksy, "Xay", 5.0, 1, 1, deposit=None)
    monkeypatch.setattr(booksy, "_get", lambda path, headers: {"business": {}})
    with pytest.raises(booksy.BooksyError):
        booksy.read_deposit(barber)
