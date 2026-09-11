"""Tests for the Rosy availability engine and the booking guardrails.

The slot walk is the part that can quietly do damage: too loose and it books
over somebody else's appointment, too strict and it reports a booked-solid
salon that actually has openings. Every case here is a rule the site itself
applies, or a shape its live data actually returned.
"""

import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "salon-ramon"))

from rosy.booking import build_payload, cancel_window_closed  # noqa: E402
from rosy.slots import Slot, busy_intervals, day_window, find_slots, is_cancelled  # noqa: E402

# Salon: open 08:00-20:00 every day, 2h lead, books 180 days out.
SALON = {
    "hours": [["08:00", "20:00"]] * 7,
    "onlineHoursInAdvanceToSchedule": 2,
    "scheduleDaysOut": 180,
    "onlnCancelTimeframe": 1,
    "cancelChargePercent": 50.0,
    "phone": "(816)555-0100",
}
# Provider works Mon-Fri 09:00-17:00, off weekends.
EMPLOYEE = {
    "id": 10,
    "firstName": "Ramon",
    "lastName": "Walker",
    "schedule": [[None, None]] + [["09:00", "17:00"]] * 5 + [[None, None]],
}
SERVICE = {"id": 500, "name": "Men's Haircut", "defaultPrice": 40.0, "defaultDurationPrice": 60}
EMP_SERVICE = {"employeeId": 10, "serviceId": 500, "duration": 45, "processTime": 0, "price": 0.0}

WEDNESDAY = date(2026, 9, 16)
SATURDAY = date(2026, 9, 19)
EARLY = datetime(2026, 9, 16, 6, 0)  # before the window, so lead time never bites


def appt(start, end, employee_id=10, client_id=999, cancellation=None):
    return {
        "employeeId": employee_id,
        "clientId": client_id,
        "serviceId": 500,
        "startDate": f"2026-09-16 {start}:00",
        "endDate": f"2026-09-16 {end}:00",
        "cancellationId": cancellation,
    }


def timesheet(start, end, event_type=0, employee_id=10, day="2026-09-16"):
    return {
        "employeeId": employee_id,
        "status": "S",
        "eventType": event_type,
        "startDate": f"{day} {start}:00",
        "endDate": f"{day} {end}:00",
    }


def search(appointments=(), timesheets=(), day=WEDNESDAY, now=EARLY, customer_id=None):
    return find_slots(
        salon=SALON,
        employee=EMPLOYEE,
        service=SERVICE,
        employee_service=EMP_SERVICE,
        day=day,
        appointments=list(appointments),
        timesheets=list(timesheets),
        now=now,
        customer_id=customer_id,
    )


def starts(slots):
    return [s.start.strftime("%H:%M") for s in slots]


def test_day_window_is_the_intersection_of_salon_and_provider():
    assert day_window(SALON, EMPLOYEE, WEDNESDAY) == (
        datetime(2026, 9, 16, 9, 0),
        datetime(2026, 9, 16, 17, 0),
    )


def test_weekend_off_uses_javascript_day_indexing():
    """Rosy indexes schedules Sunday=0; Python's weekday() is Monday=0.

    Off-by-one here shifts every provider's week by a day and still looks
    entirely plausible in the output.
    """
    assert day_window(SALON, EMPLOYEE, SATURDAY) is None
    assert search(day=SATURDAY) == []


def test_last_slot_must_finish_inside_the_window():
    slots = search()
    assert starts(slots)[0] == "09:00"
    assert starts(slots)[-1] == "16:15"  # 16:15 + 45 min = 17:00 exactly


def test_appointment_blocks_its_own_span_and_search_resumes_after_it():
    slots = search([appt("09:00", "11:00")])
    assert "09:00" not in starts(slots)
    assert "10:15" not in starts(slots)
    assert starts(slots)[0] == "11:00"


def test_cancelled_appointment_does_not_block():
    """The site's isCancelled() is `cancellationId > 0`, not a status string.

    Filtering on status leaves cancelled appointments blocking forever; the
    live data has CANCELED rows sitting on otherwise open chairs.
    """
    blocking = {**appt("09:00", "11:00"), "status": "CANCELED", "cancellationId": 1234}
    assert is_cancelled(blocking)
    assert starts(search([blocking]))[0] == "09:00"


def test_customer_cannot_be_double_booked_with_a_different_provider():
    elsewhere = appt("09:00", "10:00", employee_id=77, client_id=42)
    assert starts(search([elsewhere], customer_id=42))[0] == "10:00"
    assert starts(search([elsewhere], customer_id=None))[0] == "09:00"


def test_time_off_timesheet_subtracts_from_the_window():
    assert starts(search(timesheets=[timesheet("09:00", "12:00")]))[0] == "12:00"


def test_time_on_timesheet_extends_the_window():
    slots = search(timesheets=[timesheet("08:00", "09:00", event_type=1)])
    assert starts(slots)[0] == "08:00"


def test_time_on_from_another_day_cannot_widen_this_day():
    """The regression that produced 53,800 phantom slots.

    A single 06:15-20:00 time-on row three weeks out was applied to every day
    in the search, stretching each day's window across the whole range so the
    grid walked days it had never checked for conflicts.
    """
    faraway = timesheet("06:15", "20:00", event_type=1, day="2026-10-07")
    slots = search(timesheets=[faraway])
    assert starts(slots)[0] == "09:00"
    assert all(s.start.date() == WEDNESDAY for s in slots)


def test_inverted_timesheet_row_blocks_nothing():
    """Live data really does carry rows that end before they start (18:00 -> 11:30).

    The site's overlap test never matches them, so neither may ours: "fixing"
    the row by swapping its ends would invent hours of unavailability.
    """
    busy = busy_intervals([], [timesheet("18:00", "11:30")], employee_id=10)
    assert busy == []
    assert starts(search(timesheets=[timesheet("18:00", "11:30")]))[0] == "09:00"


def test_lead_time_hides_slots_too_soon_from_now():
    now = datetime(2026, 9, 16, 10, 0)  # 2h lead -> nothing before 12:00
    assert starts(search(now=now))[0] == "12:00"


def test_process_time_holds_the_chair_past_the_end_of_the_service():
    with_process = {**EMP_SERVICE, "processTime": 30}
    slots = find_slots(
        salon=SALON,
        employee=EMPLOYEE,
        service=SERVICE,
        employee_service=with_process,
        day=WEDNESDAY,
        appointments=[appt("12:00", "13:00")],
        timesheets=[],
        now=EARLY,
        customer_id=None,
    )
    # 11:00 + 45 min service ends 11:45, but 30 min of processing runs to 12:15,
    # which lands inside the noon appointment.
    assert "11:00" not in starts(slots)
    assert "10:45" in starts(slots)
    assert starts(slots)[-1] == "15:45"  # 45 + 30 must fit before 17:00


def test_price_falls_back_to_the_menu_when_the_provider_sets_none():
    assert search()[0].price == 40.0


def test_booking_payload_matches_the_checkout_page():
    slot = Slot(
        start=datetime(2026, 9, 30, 15, 30),
        end=datetime(2026, 9, 30, 16, 15),
        end_blocking=datetime(2026, 9, 30, 16, 15),
        employee_id=10,
        employee_name="Ramon Walker",
        service_id=500,
        service_name="Men's Haircut",
        duration=45,
        price=40.0,
    )
    payload = build_payload(slot, customer_id=42, salon_id=41947, note="bit off the top")
    assert payload == [
        {
            "salonId": 41947,
            "customer": {"id": 42},
            "employee": {"id": 10},
            "service": {"id": 500},
            "startDate": "2026-09-30T15:30:00",
            "endDate": "2026-09-30T16:15:00",
            "note": "bit off the top",
            "createdByType": 1,  # OLB; the API rejects/miscredits other values
            "createdByClient": 1,
        }
    ]


@pytest.mark.parametrize(
    ("now", "closed"),
    [
        (datetime(2026, 9, 28, 12, 0), False),  # two days out, free to cancel
        (datetime(2026, 9, 29, 16, 0), True),  # inside 1 day, 50% charge risk
    ],
)
def test_cancel_window_guard(now, closed):
    appointment = {"id": 1, "startDate": "2026-09-30 15:30:00"}
    assert cancel_window_closed(SALON, appointment, now) is closed
