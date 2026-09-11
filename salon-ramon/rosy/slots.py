"""Availability math, ported from the booking widget's own finder.

Rosy has no "give me the open slots" endpoint. The browser downloads the salon
hours, each provider's weekly schedule, that day's timesheets and that day's
appointments, and walks a 15-minute grid itself (appointment-finder-svc.js).
This is that walk, in Python, deliberately no looser than the original: being
stricter than the site costs a slot it would have offered, being looser books
over somebody.

Rules the site applies, each of which silently changes the answer:
- A slot needs `start + duration + processTime` to fit inside the window; the
  process tail blocks the chair even though the appointment "ends" earlier.
- Busy means an ACTIVE appointment. An appointment is cancelled when
  `cancellationId > 0`, so filtering on a status string leaves cancelled
  appointments blocking slots forever.
- A customer cannot be double-booked with themselves anywhere in the salon,
  not just with the provider being searched.
- Time-off timesheets (eventType 0) subtract from the window; time-on
  timesheets (eventType 1) extend it, and can put a provider on the schedule on
  a day their weekly schedule says is off.
- Nothing may be booked inside the salon's lead time
  (`onlineHoursInAdvanceToSchedule`, 2 hours here) or past `scheduleDaysOut`.

INVARIANTS (an edit must not break these):
- `find_slots` never returns a slot that overlaps a busy interval. Every filter
  here is a guard against booking over a real person's appointment.
- Times are naive datetimes in the SALON's timezone, matching the wire format.
  Mixing in an aware datetime or a local-machine "now" breaks every comparison.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as Date
from datetime import datetime, time, timedelta

INTERVAL_MINUTES = 15
FALLBACK_LEAD_MINUTES = 15
TIMESHEET_SCHEDULED = "S"
EVENT_TIME_OFF = 0
EVENT_TIME_ON = 1


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    end_blocking: datetime  # end + process time; what actually holds the chair
    employee_id: int
    employee_name: str
    service_id: int
    service_name: str
    duration: int
    price: float

    @property
    def iso_start(self) -> str:
        return self.start.strftime("%Y-%m-%dT%H:%M:%S")

    @property
    def iso_end(self) -> str:
        return self.end.strftime("%Y-%m-%dT%H:%M:%S")

    def label(self) -> str:
        return f"{self.start:%a %b %-d, %-I:%M %p} with {self.employee_name} ({self.duration} min)"


def parse_dt(value: str) -> datetime:
    """Rosy writes 'YYYY-MM-DD HH:MM:SS' on reads and 'T'-separated on writes."""
    return datetime.strptime(value.replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")


def _parse_hhmm(day: Date, value: str) -> datetime:
    hour, minute = (int(part) for part in value.split(":")[:2])
    return datetime.combine(day, time(hour, minute))


def overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open overlap, matching the widget's isTimeInAppointmentRange."""
    return a_start < b_end and b_start < a_end


def is_cancelled(appointment: dict) -> bool:
    return (appointment.get("cancellationId") or 0) > 0 or bool(appointment.get("cancelledTmp"))


def day_window(salon: dict, employee: dict, day: Date) -> tuple[datetime, datetime] | None:
    """The provider's bookable window that day, or None if nothing is open.

    Python's weekday() is Monday=0; Rosy indexes both `hours` and `schedule` by
    JavaScript getDay(), which is Sunday=0. Getting this wrong shifts every
    provider's schedule by a day and still looks plausible.
    """
    dow = (day.weekday() + 1) % 7

    salon_hours = (salon.get("hours") or [])
    if dow >= len(salon_hours) or not salon_hours[dow] or not salon_hours[dow][0]:
        return None
    salon_start = _parse_hhmm(day, salon_hours[dow][0])
    salon_end = _parse_hhmm(day, salon_hours[dow][1])

    schedule = employee.get("schedule") or []
    if dow >= len(schedule) or not schedule[dow] or not schedule[dow][0]:
        return None
    emp_start = _parse_hhmm(day, schedule[dow][0])
    emp_end = _parse_hhmm(day, schedule[dow][1])

    start = max(salon_start, emp_start)
    end = min(salon_end, emp_end)
    return (start, end) if start < end else None


def _timesheets_for(
    timesheets: list[dict], employee_id: int, event_type: int, day: Date | None = None
) -> list[dict]:
    """One provider's timesheet rows of one kind, ON ONE DAY.

    The `day` filter is not optional in spirit. Callers hold a multi-day fetch,
    and a time-ON row belongs to its own date only: leaking one into another
    day's search stretches that day's window out to the other date and the grid
    walk then invents tens of thousands of slots across days it never checked
    for conflicts. That bug shipped once; the filter lives here, inside the
    module that owns the invariant, rather than in whichever caller remembers.
    """
    out = []
    for ts in timesheets:
        if ts.get("employeeId") != employee_id:
            continue
        if ts.get("status") != TIMESHEET_SCHEDULED or ts.get("eventType") != event_type:
            continue
        if day is not None and parse_dt(ts["startDate"]).date() != day:
            continue
        out.append(ts)
    return out


def busy_intervals(
    appointments: list[dict],
    timesheets: list[dict],
    employee_id: int,
    customer_id: int | None = None,
    day: Date | None = None,
) -> list[tuple[datetime, datetime]]:
    """Everything that blocks this provider on this day."""
    busy: list[tuple[datetime, datetime]] = []

    for appt in appointments:
        if is_cancelled(appt):
            continue
        theirs = appt.get("employeeId") == employee_id
        mine = customer_id is not None and appt.get("clientId") == customer_id
        if theirs or mine:
            busy.append((parse_dt(appt["startDate"]), parse_dt(appt["endDate"])))

    for ts in _timesheets_for(timesheets, employee_id, EVENT_TIME_OFF, day):
        busy.append((parse_dt(ts["startDate"]), parse_dt(ts["endDate"])))

    # Live data carries rows that end before they start (seen: 18:00 -> 11:30).
    # The site's own overlap test never matches those, so they block nothing
    # there; dropping them keeps us identical instead of "helpfully" turning a
    # corrupt row into seven hours of fake unavailability.
    return [(start, end) for start, end in busy if end > start]


def find_slots(
    *,
    salon: dict,
    employee: dict,
    service: dict,
    employee_service: dict,
    day: Date,
    appointments: list[dict],
    timesheets: list[dict],
    now: datetime,
    customer_id: int | None = None,
) -> list[Slot]:
    """Open starts for one provider, one service, one day."""
    duration = int(employee_service.get("duration") or service.get("defaultDurationPrice") or 0)
    if duration <= 0:
        return []
    process = int(employee_service.get("processTime") or 0)
    price = employee_service.get("price")
    if not price:
        price = service.get("defaultPrice") or 0.0

    window = day_window(salon, employee, day)
    time_on = _timesheets_for(timesheets, employee["id"], EVENT_TIME_ON, day)
    if window is None and not time_on:
        return []

    if window is None:
        start, end = parse_dt(time_on[0]["startDate"]), parse_dt(time_on[0]["endDate"])
    else:
        start, end = window
    for ts in time_on:
        start = min(start, parse_dt(ts["startDate"]))
        end = max(end, parse_dt(ts["endDate"]))

    # Belt and braces: whatever the timesheets say, one day's search stays
    # inside one day.
    start = max(start, datetime.combine(day, time(0, 0)))
    end = min(end, datetime.combine(day, time(23, 59)))
    if start >= end:
        return []

    lead_hours = salon.get("onlineHoursInAdvanceToSchedule")
    lead = timedelta(hours=lead_hours) if lead_hours else timedelta(minutes=FALLBACK_LEAD_MINUTES)
    earliest = now + lead

    horizon = salon.get("scheduleDaysOut")
    if horizon and day > (now.date() + timedelta(days=int(horizon))):
        return []

    busy = busy_intervals(appointments, timesheets, employee["id"], customer_id, day)

    slots: list[Slot] = []
    cursor = start
    step = timedelta(minutes=INTERVAL_MINUTES)
    while cursor < end:
        slot_end = cursor + timedelta(minutes=duration)
        blocking_end = slot_end + timedelta(minutes=process)
        if blocking_end > end:
            break
        if cursor < earliest:
            cursor += step
            continue
        clash = next((b for b in busy if overlaps(cursor, blocking_end, b[0], b[1])), None)
        if clash:
            # Jump to the end of what we hit rather than crawling through it.
            cursor = max(clash[1], cursor + step)
            continue
        slots.append(
            Slot(
                start=cursor,
                end=slot_end,
                end_blocking=blocking_end,
                employee_id=employee["id"],
                employee_name=f"{employee.get('firstName', '')} {employee.get('lastName', '')}".strip(),
                service_id=service["id"],
                service_name=service.get("name", ""),
                duration=duration,
                price=float(price or 0.0),
            )
        )
        cursor += step
    return slots


def rank(slots: list[Slot], prefer_weekdays: bool, window: tuple[str, str] | None) -> list[Slot]:
    """Alex's preferences: weekdays first, then his preferred hours, then soonest."""
    lo, hi = (None, None)
    if window:
        lo = int(window[0].split(":")[0])
        hi = int(window[1].split(":")[0])

    def key(slot: Slot):
        weekend = slot.start.weekday() >= 5
        out_of_window = False
        if lo is not None and hi is not None:
            out_of_window = not (lo <= slot.start.hour < hi)
        return (
            int(weekend) if prefer_weekdays else 0,
            int(out_of_window),
            slot.start,
        )

    return sorted(slots, key=key)
