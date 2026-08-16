#!/usr/bin/env python3
"""Track the 6-week haircut cadence and decide when to go looking for a slot.

The recurring job runs daily and is cheap; this module is the gate that keeps
it from doing anything (or nagging) until a cut is actually due. It owns
state.json so the shell runner stays dumb.

INVARIANTS (an edit must not break these):
- `due` is derived from the last *completed* haircut, never from the last
  notification. Otherwise a cycle where Alex ignores the nudge silently
  slides the whole schedule later and the 6 weeks stretches without anyone
  noticing.
- Exactly one nudge per cycle. `notified_cycle` is compared against the due
  date, so re-running the job the same week does not re-notify.
- An appointment already lined up (`pending`) suppresses the job until the
  day after it happens. Without this the daily job re-nudges every morning
  for a haircut that is already on the calendar.

Usage:
    python3 schedule.py status                  # human-readable
    python3 schedule.py check                   # exit 0 = act now, 1 = nothing to do
    python3 schedule.py window                  # the date range to search
    python3 schedule.py mark-notified
    python3 schedule.py pending --date 2026-08-29 [--barber "Razor Nick"]
    python3 schedule.py record --date 2026-08-29 [--barber "Razor Nick"]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_PATH = HERE / "config.json"
STATE_PATH = HERE / "state.json"

# Start hunting this many days before the cut is due, so there is room to pick
# a slot that suits the calendar instead of taking whatever is left.
LEAD_DAYS = 12
# How wide a net to cast around the due date when ranking slots.
WINDOW_BEFORE = 5
WINDOW_AFTER = 9


@dataclass(frozen=True)
class Status:
    last_haircut: date | None
    due: date | None
    days_until_due: int | None
    notified_cycle: date | None
    should_act: bool
    reason: str
    pending: date | None = None


def _load(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text())


def load_state() -> dict:
    return _load(
        STATE_PATH,
        {"last_haircut": None, "notified_cycle": None, "pending": None, "history": []},
    )


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def interval_weeks() -> int:
    return int(_load(CONFIG_PATH, {"interval_weeks": 6}).get("interval_weeks", 6))


def status(today: date | None = None) -> Status:
    today = today or date.today()
    state = load_state()

    last = date.fromisoformat(state["last_haircut"]) if state.get("last_haircut") else None
    notified = (
        date.fromisoformat(state["notified_cycle"]) if state.get("notified_cycle") else None
    )
    pending = date.fromisoformat(state["pending"]) if state.get("pending") else None

    # An appointment already lined up settles the question, whether or not
    # there is any history. Stay quiet until the day after it happens.
    if pending is not None and pending >= today:
        due = (last + timedelta(weeks=interval_weeks())) if last else None
        days = (due - today).days if due else None
        return Status(last, due, days, notified, False, f"appointment on {pending}", pending)

    if last is None:
        return Status(None, None, None, notified, True, "no haircut on record yet", pending)

    due = last + timedelta(weeks=interval_weeks())
    days_until = (due - today).days

    if days_until > LEAD_DAYS:
        return Status(
            last, due, days_until, notified, False, f"not due for {days_until} days", pending
        )
    if notified == due:
        return Status(
            last, due, days_until, notified, False, "already nudged for this cycle", pending
        )
    return Status(last, due, days_until, notified, True, f"due in {days_until} days", pending)


def search_window(today: date | None = None) -> tuple[date, date]:
    """The date range to search for slots.

    Clamped so it never starts in the past, and never ends before it starts --
    an overdue haircut pulls the target date behind us, and an unclamped end
    would hand Booksy a backwards range and silently find nothing.
    """
    today = today or date.today()
    st = status(today)
    target = st.due or (today + timedelta(days=14))
    start = max(today + timedelta(days=1), target - timedelta(days=WINDOW_BEFORE))
    end = max(target + timedelta(days=WINDOW_AFTER), start + timedelta(days=WINDOW_AFTER))
    return start, end


def _cmd_status(_: argparse.Namespace) -> int:
    st = status()
    print(f"last haircut : {st.last_haircut or '(none recorded)'}")
    if st.pending:
        print(f"appointment  : {st.pending}")
    print(f"interval     : {interval_weeks()} weeks")
    print(f"due          : {st.due or '(as soon as possible)'}")
    if st.days_until_due is not None:
        print(f"days until   : {st.days_until_due}")
    start, end = search_window()
    print(f"search window: {start} .. {end}")
    print(f"act now      : {st.should_act}  ({st.reason})")
    return 0


def _cmd_check(_: argparse.Namespace) -> int:
    st = status()
    print(st.reason)
    return 0 if st.should_act else 1


def _cmd_window(_: argparse.Namespace) -> int:
    start, end = search_window()
    print(f"{start} {end}")
    return 0


def _cmd_mark_notified(_: argparse.Namespace) -> int:
    state = load_state()
    st = status()
    if st.due is None:
        print("nothing to mark: no haircut on record")
        return 1
    state["notified_cycle"] = st.due.isoformat()
    save_state(state)
    print(f"marked notified for cycle due {st.due}")
    return 0


def _cmd_pending(args: argparse.Namespace) -> int:
    when = date.fromisoformat(args.date)
    state = load_state()
    state["pending"] = when.isoformat()
    if args.barber:
        state["pending_barber"] = args.barber
    save_state(state)
    print(f"appointment noted for {when}; the daily job stays quiet until then")
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    when = date.fromisoformat(args.date) if args.date else date.today()
    state = load_state()
    state["last_haircut"] = when.isoformat()
    # A fresh cycle deserves a fresh nudge, and the appointment is spent.
    state["notified_cycle"] = None
    state["pending"] = None
    state.pop("pending_barber", None)
    entry = {"date": when.isoformat()}
    if args.barber:
        entry["barber"] = args.barber
    state.setdefault("history", []).append(entry)
    save_state(state)
    print(f"recorded haircut on {when}; next due {when + timedelta(weeks=interval_weeks())}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Haircut cadence tracker.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show the cadence").set_defaults(func=_cmd_status)
    sub.add_parser("check", help="exit 0 if a slot hunt is due").set_defaults(func=_cmd_check)
    sub.add_parser("window", help="print the search window").set_defaults(func=_cmd_window)
    sub.add_parser("mark-notified", help="record that this cycle was nudged").set_defaults(
        func=_cmd_mark_notified
    )

    pend = sub.add_parser("pending", help="note an appointment that is lined up")
    pend.add_argument("--date", required=True, help="YYYY-MM-DD")
    pend.add_argument("--barber")
    pend.set_defaults(func=_cmd_pending)

    rec = sub.add_parser("record", help="record a completed haircut")
    rec.add_argument("--date", help="YYYY-MM-DD (default: today)")
    rec.add_argument("--barber")
    rec.set_defaults(func=_cmd_record)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
