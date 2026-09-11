"""`ramon` -- read the salon's live calendar and book, from the terminal.

Read commands need only a signed-in Chrome session; `book` and `cancel` refuse
to do anything without --confirm.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config as cfg
from .api import Api, RosyError
from .booking import book as do_book
from .booking import cancel as do_cancel
from .slots import Slot, find_slots, is_cancelled, parse_dt, rank
from .session import NoSession, context, extract


def _norm(text: str) -> str:
    """Compare names on bare alphanumeric words.

    Salon menus disagree with themselves on punctuation ("Men's" vs "Mens",
    trailing spaces inside parentheses), so matching on the raw string drops
    services that are plainly there.
    """
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _pick(items: list[dict], wanted: str, field: str) -> dict | None:
    target = _norm(wanted)
    exact = [i for i in items if _norm(str(i.get(field, ""))) == target]
    if exact:
        return exact[0]
    partial = [i for i in items if target in _norm(str(i.get(field, "")))]
    return partial[0] if len(partial) == 1 else (partial[0] if partial else None)


def _resolve_at(value: str, slots: list[Slot]) -> Slot | None:
    """Turn --at into one of the slots we actually computed.

    A date alone means "the best slot that day". A date and time must match an
    open slot exactly: the point of routing through the computed list is that
    a hand-typed time can never become a booking the salon never offered.
    """
    text = value.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            wanted = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return next((s for s in slots if s.start == wanted), None)
    try:
        day = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(f"could not read {value!r} as a date or date and time") from None
    return next((s for s in slots if s.start.date() == day), None)


def _employee_label(emp: dict) -> str:
    return f"{emp.get('firstName', '')} {emp.get('lastName', '')}".strip()


class Session:
    """Everything a command needs: an API handle plus the salon's own rules."""

    def __init__(self):
        self.conf = cfg.load()
        self.ctx = context()
        self.api = Api(self.ctx, self.conf["salonId"])
        self.salon = self.api.salon()
        self.tz = ZoneInfo(self.salon.get("timeZone") or "US/Central")

    @property
    def now(self) -> datetime:
        """Naive 'now' in the salon's timezone -- the wire format's frame."""
        return datetime.now(self.tz).replace(tzinfo=None)

    def employee(self, name: str) -> dict:
        found = _pick(self.api.employees(), name, "firstName")
        if not found:
            found = _pick(self.api.employees(), name, "lastName")
        if not found:
            raise SystemExit(f"no provider matching {name!r}")
        return found

    def service(self, name: str) -> dict:
        found = _pick(self.api.services(), name, "name")
        if not found:
            raise SystemExit(f"no service matching {name!r}")
        # This salon's whole menu is resource-free and unchained, so the slot
        # walk models neither rooms nor primary/secondary service pairs. Say so
        # loudly rather than quietly offering times that need a room nobody
        # checked was free.
        if found.get("resourceGroupId") or found.get("requirement") not in (None, "none"):
            raise SystemExit(
                f"{found['name']} needs a room or a paired service, which this tool "
                "does not model. Book that one in the browser."
            )
        return found

    def search(self, service: dict, employees: list[dict], days: int) -> list[Slot]:
        emp_services = {es["employeeId"]: es for es in self.api.employee_services(service["id"])}
        today = self.now.date()
        last = today + timedelta(days=days)
        timesheets = self.api.timesheets(today.isoformat(), last.isoformat())

        out: list[Slot] = []
        for offset in range(days + 1):
            day = today + timedelta(days=offset)
            appts = None
            for emp in employees:
                es = emp_services.get(emp["id"])
                if not es or not es.get("online"):
                    continue
                if appts is None:  # one fetch per day, only if a provider is live
                    appts = self.api.appointments_on(day.isoformat())
                out.extend(
                    find_slots(
                        salon=self.salon,
                        employee=emp,
                        service=service,
                        employee_service=es,
                        day=day,
                        appointments=appts,
                        timesheets=timesheets,
                        now=self.now,
                        customer_id=self.ctx.customer_id,
                    )
                )
        return rank(out, self.conf.get("preferWeekdays", True), self.conf.get("preferredWindow"))


# -- commands --------------------------------------------------------------


def cmd_login(args) -> int:
    cookies = extract()
    print(f"lifted {len(cookies)} cookies from Chrome (JSESSIONID present)")
    ctx = context(cookies)
    print(f"signed in, customer {ctx.customer_id}; token {len(ctx.token)} chars")
    return 0


def cmd_whoami(args) -> int:
    s = Session()
    print(f"{s.salon['name']} -- {s.salon['address1']}, {s.salon['city']} {s.salon['state']}")
    print(f"customer id {s.ctx.customer_id}")
    print(f"lead time {s.salon.get('onlineHoursInAdvanceToSchedule')}h, "
          f"books out {s.salon.get('scheduleDaysOut')} days, "
          f"cancel window {s.salon.get('onlnCancelTimeframe')}d "
          f"({s.salon.get('cancelChargePercent'):.0f}% charge inside it)")
    return 0


def cmd_providers(args) -> int:
    s = Session()
    for emp in s.api.employees():
        schedule = emp.get("schedule") or []
        days = "".join(
            letter if (i < len(schedule) and schedule[i] and schedule[i][0]) else "-"
            for i, letter in enumerate("SMTWTFS")
        )
        print(f"{emp['id']:>7}  {_employee_label(emp):<18} {days}  "
              f"{emp.get('servicesCount', 0)} services  "
              f"{'online' if emp.get('availableOnline') else 'OFFLINE'}")
    return 0


def cmd_services(args) -> int:
    s = Session()
    services = s.api.services()
    if args.provider:
        emp = s.employee(args.provider)
        print(f"{_employee_label(emp)}:")
        for svc in sorted(services, key=lambda x: (x.get("serviceGroupName") or "", x["name"])):
            es = next(
                (e for e in s.api.employee_services(svc["id"]) if e["employeeId"] == emp["id"]),
                None,
            )
            if not es or not es.get("online"):
                continue
            price = es.get("price") or svc.get("defaultPrice") or 0
            print(f"  {svc['id']:>7}  {svc['name']:<34} {es.get('duration')} min  ${price:.0f}")
        return 0
    for svc in sorted(services, key=lambda x: (x.get("serviceGroupName") or "", x["name"])):
        print(f"{svc['id']:>7}  {svc['name']:<34} {svc.get('serviceGroupName', '')}")
    return 0


def cmd_slots(args) -> int:
    s = Session()
    service = s.service(args.service or s.conf["defaultService"])
    employees = (
        s.api.employees() if args.any_provider else [s.employee(args.provider or s.conf["defaultProvider"])]
    )
    slots = s.search(service, employees, args.days)
    if not slots:
        print(f"no open {service['name']} slots in the next {args.days} days")
        return 1
    print(f"{service['name']} -- {len(slots)} open slots in the next {args.days} days:")
    for slot in slots[: args.limit]:
        print(f"  {slot.start:%Y-%m-%d %H:%M}  {slot.label()}  ${slot.price:.0f}")
    return 0


def cmd_book(args) -> int:
    s = Session()
    service = s.service(args.service or s.conf["defaultService"])
    employees = (
        s.api.employees() if args.any_provider else [s.employee(args.provider or s.conf["defaultProvider"])]
    )
    slots = s.search(service, employees, args.days)
    if not slots:
        print(f"no open {service['name']} slots in the next {args.days} days")
        return 1

    if args.at:
        chosen = _resolve_at(args.at, slots)
        if not chosen:
            print(f"{args.at} is not an open slot. Nearest options:")
            for slot in slots[:5]:
                print(f"  {slot.start:%Y-%m-%d %H:%M}  {slot.label()}")
            return 1
    else:
        chosen = slots[0]

    result = do_book(s.api, chosen, s.conf["salonId"], args.note, args.confirm)
    print(result.message)
    return 0 if result.ok or not args.confirm else 1


def cmd_appointments(args) -> int:
    s = Session()
    today = s.now.date()
    appts = s.api.my_appointments(today.isoformat(), (today + timedelta(days=365)).isoformat())
    upcoming = [a for a in appts if not is_cancelled(a)]
    if not upcoming:
        print("no upcoming appointments")
        return 0
    employees = {e["id"]: _employee_label(e) for e in s.api.employees()}
    services = {x["id"]: x["name"] for x in s.api.services()}
    for appt in sorted(upcoming, key=lambda a: a["startDate"]):
        start = parse_dt(appt["startDate"])
        print(f"{appt['id']:>10}  {start:%a %b %-d %Y, %-I:%M %p}  "
              f"{services.get(appt['serviceId'], appt['serviceId'])} with "
              f"{employees.get(appt['employeeId'], appt['employeeId'])}")
    return 0


def cmd_cancel(args) -> int:
    s = Session()
    today = s.now.date()
    appts = [
        a
        for a in s.api.my_appointments(today.isoformat(), (today + timedelta(days=365)).isoformat())
        if not is_cancelled(a)
    ]
    if args.id:
        appt = next((a for a in appts if a["id"] == args.id), None)
        if not appt:
            print(f"no upcoming appointment with id {args.id}")
            return 1
    else:
        if not appts:
            print("no upcoming appointments to cancel")
            return 1
        appt = sorted(appts, key=lambda a: a["startDate"])[0]

    result = do_cancel(s.api, s.salon, appt, s.now, args.confirm, args.force)
    print(result.message)
    return 0 if result.ok or not args.confirm else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ramon", description="Book at Salon Ramon (Rosy).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="lift the signed-in session out of Chrome").set_defaults(fn=cmd_login)
    sub.add_parser("whoami", help="who we are and what the salon allows").set_defaults(fn=cmd_whoami)
    sub.add_parser("providers", help="bookable staff and their weekly days").set_defaults(fn=cmd_providers)

    p = sub.add_parser("services", help="the bookable menu")
    p.add_argument("--provider", help="only what this provider performs, with their price")
    p.set_defaults(fn=cmd_services)

    p = sub.add_parser("slots", help="open appointment times")
    p.add_argument("--service")
    p.add_argument("--provider")
    p.add_argument("--any-provider", action="store_true", help="search every provider")
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(fn=cmd_slots)

    p = sub.add_parser("book", help="book a slot (dry run unless --confirm)")
    p.add_argument("--service")
    p.add_argument("--provider")
    p.add_argument("--any-provider", action="store_true")
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--at", help='exact start, "YYYY-MM-DD HH:MM"; default is the best-ranked slot')
    p.add_argument("--note", help="note for the salon")
    p.add_argument("--confirm", action="store_true", help="actually book it")
    p.set_defaults(fn=cmd_book)

    sub.add_parser("appointments", help="my upcoming appointments").set_defaults(fn=cmd_appointments)

    p = sub.add_parser("cancel", help="cancel an appointment (dry run unless --confirm)")
    p.add_argument("id", nargs="?", type=int, help="appointment id; default is the next one")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--force", action="store_true", help="cancel inside the salon's charge window")
    p.set_defaults(fn=cmd_cancel)

    args = parser.parse_args(argv)
    if getattr(args, "days", None) is None and hasattr(args, "days"):
        args.days = cfg.load()["searchDays"]

    try:
        return args.fn(args)
    except NoSession as exc:
        print(f"session: {exc}", file=sys.stderr)
        return 2
    except RosyError as exc:
        print(f"api: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
