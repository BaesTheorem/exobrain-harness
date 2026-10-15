#!/usr/bin/env python3
"""Track the 6-week haircut cadence and decide when to go looking for a slot.

The recurring job runs daily and is cheap; this module is the gate that keeps
it from doing anything (or nagging) until a cut is actually due. It owns
state.json so the shell runner stays dumb.

Venue-agnostic on purpose: it moved from Booksy (Rich Forever) to Rosy (Salon
Ramon) without a logic change, because none of the cadence depends on which
shop is on the other end. `history` carries the cuts from both.

INVARIANTS (an edit must not break these):
- `due` is derived from the last *completed* haircut, never from the last
  notification. Otherwise a cycle where Alex ignores the nudge silently
  slides the whole schedule later and the 6 weeks stretches without anyone
  noticing.
- Exactly one nudge per cycle. `notified_cycle` is compared against the due
  date, so re-running the job the same week does not re-notify.
- Appointments already lined up (`pending`) suppress the job until the day
  after the next one happens. Without this the daily job re-nudges every
  morning for a haircut that is already on the calendar.
- `pending` is a QUEUE, not one date. Booking several cycles ahead while the
  calendar is open is the whole point of booking early, and a single-slot
  field silently drops all but the newest: the job would then wake up after
  the first cut, see nothing lined up, and book a duplicate on top of an
  appointment that already exists.
- A `pending` appointment whose date has passed is closed out as a completed
  haircut, not discarded. It used to just expire, so the cut Alex actually got
  left no trace and the next run read "no haircut on record" and went hunting
  three weeks early. Booksy cannot settle this for us: it reported the Sep 1
  cut Alex sat through as status "C", so the only record of a *completed*
  haircut is this file.

Usage:
    python3 schedule.py status                  # human-readable
    python3 schedule.py check                   # exit 0 = act now, 1 = nothing to do
    python3 schedule.py window                  # the date range to search
    python3 schedule.py reconcile               # close out a lapsed appointment
    python3 schedule.py mark-notified
    python3 schedule.py pending --date YYYY-MM-DD [--time HH:MM] [--id N] [--swap-since D --swap-until D]
    python3 schedule.py plan                    # JSON: the hunt window and swap watches
    python3 schedule.py candidates --kind hunt|swap [--current D] < slots.json
    python3 schedule.py reject --at "YYYY-MM-DD HH:MM"   # a slot MIST found blocked
    python3 schedule.py swap --old-date D --date D --time HH:MM --id N
    python3 schedule.py nudge                   # exit 0 once per cycle when nothing is open
    python3 schedule.py record --date YYYY-MM-DD [--provider "[Stylist]"]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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
# With bookAhead > 1 the hunt runs as soon as the queue is short, limited only
# by how far out the salon takes bookings (Rosy's scheduleDaysOut).
HORIZON_DAYS = 180
# A swap must leave the old appointment cancellable for free: the salon charges
# 50% inside 1 day, so stop watching 2 days out.
SWAP_CUTOFF_DAYS = 2


@dataclass(frozen=True)
class Status:
    last_haircut: date | None
    due: date | None
    days_until_due: int | None
    notified_cycle: date | None
    should_act: bool
    reason: str
    pending: date | None = None  # the NEXT one; the rest live in state


def _load(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text())


def load_state() -> dict:
    state = _load(
        STATE_PATH,
        {"last_haircut": None, "notified_cycle": None, "pending": [], "history": []},
    )
    return _migrate(state)


def _migrate(state: dict) -> dict:
    """Bring a single-appointment state file up to the queue shape."""
    pending = state.get("pending")
    if isinstance(pending, str):
        entry = {"date": pending}
        if state.get("pending_provider"):
            entry["provider"] = state["pending_provider"]
        state["pending"] = [entry]
    elif pending is None:
        state["pending"] = []
    state.pop("pending_provider", None)
    return state


def pending_dates(state: dict) -> list[date]:
    return sorted(date.fromisoformat(e["date"]) for e in state.get("pending") or [])


def next_pending(state: dict, today: date) -> date | None:
    return next((d for d in pending_dates(state) if d >= today), None)


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def interval_weeks() -> int:
    return int(_load(CONFIG_PATH, {}).get("intervalWeeks", 6))


def book_ahead() -> int:
    """How many appointments to keep queued. 1 is the original behaviour."""
    return max(1, int(_load(CONFIG_PATH, {}).get("bookAhead", 1)))


def preferred(start: datetime) -> bool:
    """Weekday, inside the preferred hours: the bar a swap has to clear."""
    conf = _load(CONFIG_PATH, {})
    if conf.get("preferWeekdays", True) and start.weekday() >= 5:
        return False
    window = conf.get("preferredWindow")
    if not window:
        return True
    lo, hi = (time.fromisoformat(w) for w in window)
    return lo <= start.time() < hi


def status(today: date | None = None) -> Status:
    today = today or date.today()
    state = load_state()

    last = date.fromisoformat(state["last_haircut"]) if state.get("last_haircut") else None
    notified = (
        date.fromisoformat(state["notified_cycle"]) if state.get("notified_cycle") else None
    )
    pending = next_pending(state, today)
    queued = [d for d in pending_dates(state) if d >= today]
    ahead = book_ahead()

    # Enough appointments lined up settles the question, whether or not there
    # is any history. Stay quiet until the day after the next one happens.
    if len(queued) >= ahead:
        due = (last + timedelta(weeks=interval_weeks())) if last else None
        days = (due - today).days if due else None
        listed = ", ".join(d.isoformat() for d in queued)
        word = "appointment" if len(queued) == 1 else "appointments"
        return Status(last, due, days, notified, False, f"{word} on {listed}", pending)

    anchor = max([d for d in (last, queued[-1] if queued else None) if d], default=None)
    if anchor is None:
        return Status(None, None, None, notified, True, "no haircut on record yet", pending)

    due = anchor + timedelta(weeks=interval_weeks())
    days_until = (due - today).days
    lead = LEAD_DAYS if ahead == 1 else HORIZON_DAYS

    if days_until > lead:
        return Status(
            last, due, days_until, notified, False, f"not due for {days_until} days", pending
        )
    if ahead == 1 and notified == due:
        # Booking ahead keeps hunting daily (the precheck keeps that cheap);
        # the one-shot original stops after its single nudge.
        return Status(
            last, due, days_until, notified, False, "already nudged for this cycle", pending
        )
    return Status(last, due, days_until, notified, True, f"due in {days_until} days", pending)


def reconcile(today: date | None = None) -> date | None:
    """Close out an appointment whose date has passed. Returns the date, or None.

    A lapsed `pending` used to simply stop suppressing the job, which threw
    away the only evidence the haircut happened: the next run saw an empty
    history, concluded Alex had never had a cut, and hunted for a slot three
    weeks early. Booksy is no help here, since it files a sat-through
    appointment under the same status letter as a cancelled one.

    So a lapsed appointment records as completed, flagged `assumed` so the
    guess stays visible and Alex can correct it. Assuming he went is the
    cheaper error by a distance: guess "went" wrongly and the next nudge
    arrives late, which one sentence from him fixes; guess "did not go"
    wrongly and the job books a second appointment he is already booked for.
    """
    today = today or date.today()
    state = load_state()
    passed = [e for e in state.get("pending") or [] if date.fromisoformat(e["date"]) < today]
    if not passed:
        return None

    state["pending"] = [e for e in state["pending"] if e not in passed]
    last = date.fromisoformat(state["last_haircut"]) if state.get("last_haircut") else None
    latest: date | None = None

    for spent in sorted(passed, key=lambda e: e["date"]):
        when = date.fromisoformat(spent["date"])
        if last is not None and last >= when:
            continue  # already recorded by hand; just retire the spent appointment
        entry: dict[str, object] = {"date": when.isoformat(), "assumed": True}
        if spent.get("provider"):
            entry["provider"] = spent["provider"]
        state.setdefault("history", []).append(entry)
        latest = when

    if latest is None:
        save_state(state)
        return None

    state["last_haircut"] = latest.isoformat()
    state["notified_cycle"] = None
    save_state(state)
    return latest


def search_window(today: date | None = None) -> tuple[date, date]:
    """The date range to search for slots.

    Clamped so it never starts in the past, and never ends before it starts --
    an overdue haircut pulls the target date behind us, and an unclamped end
    would hand the booker a backwards range and silently find nothing.
    """
    today = today or date.today()
    st = status(today)
    target = st.due or (today + timedelta(days=14))
    start = max(today + timedelta(days=1), target - timedelta(days=WINDOW_BEFORE))
    end = max(target + timedelta(days=WINDOW_AFTER), start + timedelta(days=WINDOW_AFTER))
    return start, end


def _cmd_status(_: argparse.Namespace) -> int:
    st = status()
    last = st.last_haircut
    assumed = any(
        e.get("assumed") and e.get("date") == (last.isoformat() if last else None)
        for e in load_state().get("history") or []
    )
    print(f"last haircut : {last or '(none recorded)'}{' (assumed, unconfirmed)' if assumed else ''}")
    upcoming = pending_dates(load_state())
    stale = [d for d in upcoming if d < date.today()]
    if stale:
        print(f"appointment  : {stale[0]} (passed; run reconcile)")
    for when in [d for d in upcoming if d >= date.today()]:
        print(f"appointment  : {when}")
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


def _cmd_reconcile(_: argparse.Namespace) -> int:
    closed = reconcile()
    if closed is None:
        print("nothing to reconcile")
        return 1
    print(
        f"assumed the {closed} appointment happened and recorded it; "
        f"next due {closed + timedelta(weeks=interval_weeks())}. "
        f"If Alex did not go, run: schedule.py record --date <the real date>"
    )
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
    queue = [e for e in state["pending"] if e["date"] != when.isoformat()]
    entry: dict[str, object] = {"date": when.isoformat()}
    if args.provider:
        entry["provider"] = args.provider
    if args.time:
        entry["time"] = args.time
    if args.id:
        entry["id"] = args.id
    if args.swap_since and args.swap_until:
        entry["swap"] = {"since": args.swap_since, "until": args.swap_until}
    queue.append(entry)
    state["pending"] = sorted(queue, key=lambda e: e["date"])
    save_state(state)
    upcoming = pending_dates(state)
    print(
        f"appointment noted for {when}; the daily job stays quiet until then. "
        f"queue: {', '.join(d.isoformat() for d in upcoming)}"
    )
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    when = date.fromisoformat(args.date) if args.date else date.today()
    state = load_state()
    state["last_haircut"] = when.isoformat()
    # A fresh cycle deserves a fresh nudge, and the appointment is spent. Any
    # appointment already booked for a LATER cycle survives; that is the point
    # of the queue.
    state["notified_cycle"] = None
    state["pending"] = [e for e in state["pending"] if date.fromisoformat(e["date"]) > when]
    entry = {"date": when.isoformat()}
    if args.provider:
        entry["provider"] = args.provider
    state.setdefault("history", []).append(entry)
    save_state(state)
    print(f"recorded haircut on {when}; next due {when + timedelta(weeks=interval_weeks())}")
    return 0


def plan(today: date | None = None) -> dict:
    """What the daily run should look at: the hunt window and the swap watches."""
    today = today or date.today()
    st = status(today)
    hunt = None
    if st.should_act:
        start, end = search_window(today)
        hunt = {"since": start.isoformat(), "until": end.isoformat(),
                "target": st.due.isoformat() if st.due else None}
    swaps = [
        {"date": e["date"], "time": e.get("time"), "id": e.get("id"), **e["swap"]}
        for e in load_state().get("pending") or []
        if e.get("swap")
        and (date.fromisoformat(e["date"]) - today).days >= SWAP_CUTOFF_DAYS
    ]
    return {"hunt": hunt, "swaps": swaps}


def candidates(slots: list[dict], kind: str, current: str | None = None) -> list[dict]:
    """Drop slots MIST already ruled out; a swap also has to be a preferred time."""
    rejected = set(load_state().get("rejected") or [])
    out = []
    for slot in slots:
        start = datetime.fromisoformat(slot["start"])
        key = start.strftime("%Y-%m-%d %H:%M")
        if key in rejected:
            continue
        if kind == "swap" and (not preferred(start) or key == current):
            continue
        out.append({**slot, "preferred": preferred(start)})
    return out


def _cmd_plan(_: argparse.Namespace) -> int:
    print(json.dumps(plan()))
    return 0


def _cmd_candidates(args: argparse.Namespace) -> int:
    import sys

    print(json.dumps(candidates(json.load(sys.stdin), args.kind, args.current), indent=1))
    return 0


def _cmd_reject(args: argparse.Namespace) -> int:
    state = load_state()
    rejected = set(state.get("rejected") or [])
    rejected.add(args.at)
    # Past slots can never come back, so the list stays short.
    cutoff = date.today().isoformat()
    state["rejected"] = sorted(r for r in rejected if r[:10] >= cutoff)
    save_state(state)
    print(f"will not offer {args.at} again")
    return 0


def _cmd_swap(args: argparse.Namespace) -> int:
    state = load_state()
    old = next((e for e in state["pending"] if e["date"] == args.old_date), None)
    if old is None:
        print(f"no queued appointment on {args.old_date}")
        return 1
    new = {k: v for k, v in old.items() if k not in ("swap", "date", "time", "id")}
    new.update({"date": args.date, "time": args.time, "id": args.id})
    state["pending"] = sorted(
        [e for e in state["pending"] if e is not old] + [new], key=lambda e: e["date"]
    )
    save_state(state)
    print(f"swapped {args.old_date} for {args.date} {args.time}; watch closed")
    return 0


def _cmd_nudge(_: argparse.Namespace) -> int:
    """Exit 0 (and mark it) the first time a cycle runs short of openings near the date."""
    st = status()
    if st.due is None or st.days_until_due is None or st.days_until_due > LEAD_DAYS:
        return 1
    if st.notified_cycle == st.due:
        return 1
    state = load_state()
    state["notified_cycle"] = st.due.isoformat()
    save_state(state)
    print(f"no openings yet for the cut due {st.due}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Haircut cadence tracker.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="show the cadence").set_defaults(func=_cmd_status)
    sub.add_parser("check", help="exit 0 if a slot hunt is due").set_defaults(func=_cmd_check)
    sub.add_parser("window", help="print the search window").set_defaults(func=_cmd_window)
    sub.add_parser(
        "reconcile", help="close out an appointment whose date has passed"
    ).set_defaults(func=_cmd_reconcile)
    sub.add_parser("mark-notified", help="record that this cycle was nudged").set_defaults(
        func=_cmd_mark_notified
    )

    pend = sub.add_parser("pending", help="note an appointment that is lined up")
    pend.add_argument("--date", required=True, help="YYYY-MM-DD")
    pend.add_argument("--provider")
    pend.add_argument("--time", help="HH:MM")
    pend.add_argument("--id", type=int, help="the salon's appointment id")
    pend.add_argument("--swap-since", help="watch for a preferred time from this date")
    pend.add_argument("--swap-until", help="... to this date")
    pend.set_defaults(func=_cmd_pending)

    sub.add_parser("plan", help="JSON: hunt window and swap watches").set_defaults(func=_cmd_plan)
    cand = sub.add_parser("candidates", help="filter `ramon slots --json` from stdin")
    cand.add_argument("--kind", choices=["hunt", "swap"], required=True)
    cand.add_argument("--current", help='the booked slot, "YYYY-MM-DD HH:MM"')
    cand.set_defaults(func=_cmd_candidates)
    rej = sub.add_parser("reject", help="never offer this slot again")
    rej.add_argument("--at", required=True, help='"YYYY-MM-DD HH:MM"')
    rej.set_defaults(func=_cmd_reject)
    sw = sub.add_parser("swap", help="replace a watched appointment with the new booking")
    sw.add_argument("--old-date", required=True)
    sw.add_argument("--date", required=True)
    sw.add_argument("--time", required=True)
    sw.add_argument("--id", type=int, required=True)
    sw.set_defaults(func=_cmd_swap)
    sub.add_parser("nudge", help="once-per-cycle 'nothing open' gate").set_defaults(func=_cmd_nudge)

    rec = sub.add_parser("record", help="record a completed haircut")
    rec.add_argument("--date", help="YYYY-MM-DD (default: today)")
    rec.add_argument("--provider")
    rec.set_defaults(func=_cmd_record)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
