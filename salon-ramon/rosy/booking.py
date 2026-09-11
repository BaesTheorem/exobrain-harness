"""Create and cancel appointments, and prove to the server that it happened.

The hard-won rule from the Booksy tool applies verbatim here: never trust the
write's own response. A POST that returns 200 with an appointment body is a
claim, not a booking. Both `book` and `cancel` re-read the customer's
appointment list afterwards and report only what the server says is there.

The booking payload is exactly what the checkout page's appointment factory
builds (appointment-factory-svc.js): a LIST, even for one appointment, with
`createdByType: 1` (OLB, online booking) and `createdByClient: 1`.

INVARIANTS (an edit must not break these):
- Nothing writes without an explicit confirm. The dry run is the default and
  must stay the default; this spends an hour of a real person's day.
- Success is a server read, never the POST/DELETE response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .api import Api
from .slots import Slot, is_cancelled, overlaps, parse_dt

CREATED_BY_OLB = 1


@dataclass
class Result:
    ok: bool
    message: str
    appointment: dict | None = None


def build_payload(slot: Slot, customer_id: int, salon_id: int, note: str | None = None) -> list[dict]:
    return [
        {
            "salonId": salon_id,
            "customer": {"id": customer_id},
            "employee": {"id": slot.employee_id},
            "service": {"id": slot.service_id},
            "startDate": slot.iso_start,
            "endDate": slot.iso_end,
            "note": note,
            "createdByType": CREATED_BY_OLB,
            "createdByClient": 1,
        }
    ]


def slot_still_free(api: Api, slot: Slot) -> bool:
    """Re-read the day immediately before writing.

    Availability was computed from a snapshot that may be minutes old, and the
    API does not appear to reject a double-booking on its own.
    """
    day = slot.start.strftime("%Y-%m-%d")
    for appt in api.appointments_on(day):
        if is_cancelled(appt):
            continue
        if appt.get("employeeId") != slot.employee_id and appt.get("clientId") != api.ctx.customer_id:
            continue
        if overlaps(
            slot.start, slot.end_blocking, parse_dt(appt["startDate"]), parse_dt(appt["endDate"])
        ):
            return False
    return True


def find_booked(api: Api, slot: Slot) -> dict | None:
    """The server's own answer to 'did this appointment get created?'"""
    for appt in api.my_appointments_on(slot.start.date()):
        if is_cancelled(appt):
            continue
        if (
            appt.get("employeeId") == slot.employee_id
            and appt.get("serviceId") == slot.service_id
            and parse_dt(appt["startDate"]) == slot.start
        ):
            return appt
    return None


def book(api: Api, slot: Slot, salon_id: int, note: str | None, confirm: bool) -> Result:
    if not confirm:
        return Result(
            ok=False,
            message=f"DRY RUN -- would book {slot.label()} at ${slot.price:.0f}. Re-run with --confirm.",
        )

    existing = find_booked(api, slot)
    if existing:
        return Result(True, f"Already booked: {slot.label()} (id {existing['id']})", existing)

    if not slot_still_free(api, slot):
        return Result(False, f"Slot was taken while we worked: {slot.label()}")

    api.create_appointments(build_payload(slot, api.ctx.customer_id, salon_id, note))

    booked = find_booked(api, slot)
    if not booked:
        return Result(
            False,
            "POST returned without error but the server has no such appointment. Nothing booked.",
        )
    return Result(True, f"Booked: {slot.label()} (id {booked['id']})", booked)


def cancel_window_closed(salon: dict, appointment: dict, now: datetime) -> bool:
    """True when the salon's online cancel window has already shut.

    `onlnCancelTimeframe` is in days before the appointment; inside it the
    salon reserves the right to charge `cancelChargePercent` (50% here).
    """
    days = salon.get("onlnCancelTimeframe")
    if days in (None, -1):
        return False
    return now >= parse_dt(appointment["startDate"]) - timedelta(days=int(days))


def cancel(api: Api, salon: dict, appointment: dict, now: datetime, confirm: bool, force: bool = False) -> Result:
    start = parse_dt(appointment["startDate"])
    label = f"{start:%a %b %-d, %-I:%M %p} (id {appointment['id']})"

    if cancel_window_closed(salon, appointment, now) and not force:
        pct = salon.get("cancelChargePercent") or 0
        days = salon.get("onlnCancelTimeframe")
        return Result(
            False,
            f"Inside the salon's {days}-day cancellation window for {label}; "
            f"cancelling may incur a {pct:.0f}% charge. Call {salon.get('phone')} "
            f"or re-run with --force.",
        )

    if not confirm:
        return Result(False, f"DRY RUN -- would cancel {label}. Re-run with --confirm.")

    api.cancel_appointment(appointment["id"])

    still_there = next(
        (
            a
            for a in api.my_appointments_on(start.date())
            if a["id"] == appointment["id"] and not is_cancelled(a)
        ),
        None,
    )
    if still_there:
        return Result(False, f"DELETE returned OK but {label} is still active on the server.")
    return Result(True, f"Cancelled {label}")
