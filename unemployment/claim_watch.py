#!/usr/bin/env python3
"""
Watch Alex's Missouri unemployment claim and make sure a week never expires.

THE PROBLEM THIS SOLVES
-----------------------
Filing the weekly request is worth roughly $320 and takes about four minutes,
and it still went five consecutive days unfiled in late July. The failure is not
capability, it is that nothing was tracking the clock. So this tracks the clock.

WHERE THE DATA COMES FROM
-------------------------
DES texts shortcode 36553 on every meaningful claim event -- filings, logins,
and new correspondence. Those texts are already in Alex's own message database,
so the claim state can be reconstructed without ever logging into the portal.
That is strictly better than scraping: it costs nothing, it cannot trip anything
on the DES side, and it does not generate the account-accessed SMS that a login
check would.

Known message shapes from 36553:
  "Your Unemployment Insurance claim application has been processed."
  "Weekly Request for Payment week(s) have been filed and currently being processed."
  "Login Notice. Your account was accessed on MM/DD/YYYY HH:MM:SS AM/PM."

Anything else from that shortcode is treated as correspondence and surfaced
loudly, because DES notices carry deadlines that can suspend payment.

WHAT IT WILL NOT DO
-------------------
It does not file the weekly request. That form is a sworn statement under
RSMo 288.380 whose questions about self-employment, earnings timing, and
severance have answers only Alex has. This gets him to the form on time with the
evidence assembled; he answers and submits.

Subcommands:
  sync      Parse DES texts, update the ledger, print what changed.
  check     sync, then notify if a week needs attention. This is the launchd job.
  report    Print current claim state without notifying.
"""

import argparse
import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent
sys.path.insert(0, str(HERE))

from uinteract_mcp import (  # noqa: E402
    CLAIM_FILED, DATA, DEADLINE_DAYS, DES_PHONE, FILINGS, LOGIN_URL,
    MIN_ACTIVITIES, read_json, recent_weeks, week_ending_for, week_record,
    write_json, tool_work_search,
)

def _load_imessage_reader():
    """The reader's filename has a hyphen, so it needs a manual import.

    Its extract_body_text() decodes the NSAttributedString typedstream that DES
    messages actually live in -- on this macOS the `text` column is NULL for all
    20 of them, so the decoder is not optional.
    """
    path = HARNESS / "imessage" / "imessage-reader.py"
    spec = importlib.util.spec_from_file_location("imessage_reader", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_READER = _load_imessage_reader()
extract_body_text = _READER.extract_body_text

DES_SHORTCODE = "36553"
APPLE_EPOCH = datetime(2001, 1, 1)
NOTIFY = HARNESS / "mist-voice" / "bin" / "mist-notify"

EVENTS = DATA / "des_events.json"
NOTIFIED = DATA / "notified.json"

CACHE_DB = HARNESS / "imessage" / "cache" / "chat.db"
LIVE_DB = Path.home() / "Library" / "Messages" / "chat.db"

RE_LOGIN = re.compile(
    r"account was accessed on\s+(\d{2}/\d{2}/\d{4})\s+([\d:]+\s*[AP]\.?M\.?)", re.I)
RE_FILED = re.compile(r"weekly request for payment.*have been filed", re.I | re.S)
RE_CLAIM = re.compile(r"claim application has been processed", re.I)
RE_CORRESPONDENCE = re.compile(r"(\d+)\s+new correspondence", re.I)
# Subscription and profile-change confirmations carry no deadline. They get their
# own bucket so they cannot drown out a notice that actually needs answering.
RE_INFORMATIONAL = re.compile(
    r"confirm subscribing|reply stop to unsubscribe\Z|profile was processed", re.I)


# ---------------------------------------------------------------- imessage

def db_path():
    if CACHE_DB.exists():
        return CACHE_DB
    return LIVE_DB


def apple_to_local(raw):
    """Apple CoreData timestamps: nanoseconds since 2001-01-01 UTC."""
    seconds = raw / 1_000_000_000 if raw > 1_000_000_000_000 else raw
    utc = APPLE_EPOCH.replace(tzinfo=timezone.utc) + timedelta(seconds=seconds)
    return utc.astimezone().replace(tzinfo=None)


def read_des_texts():
    path = db_path()
    if not path.exists():
        raise RuntimeError(
            f"No message database at {path}. Run the imessage sync, or grant "
            "Full Disk Access.")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT m.date, m.text, m.attributedBody
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE h.id LIKE ? AND m.is_from_me = 0
            ORDER BY m.date ASC
            """,
            (f"%{DES_SHORTCODE}%",),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for raw, text, blob in rows:
        body = text or extract_body_text(blob) or ""
        body = body.strip()
        if not body:
            continue
        try:
            when = apple_to_local(raw)
        except (ValueError, OverflowError, TypeError):
            continue
        out.append({"at": when.isoformat(timespec="seconds"), "text": body})
    return out


def classify(text):
    if RE_CLAIM.search(text):
        return "claim_processed"
    if RE_FILED.search(text):
        return "filing_confirmed"
    if RE_LOGIN.search(text):
        return "login_notice"
    if RE_CORRESPONDENCE.search(text):
        return "correspondence"
    if RE_INFORMATIONAL.search(text):
        return "informational"
    # Unrecognized shapes are treated as correspondence rather than ignored. A
    # missed deadline costs a week's payment; a false alarm costs a banner.
    return "correspondence"


def correspondence_count(text):
    m = RE_CORRESPONDENCE.search(text)
    return int(m.group(1)) if m else 1


# ---------------------------------------------------------------- ledger

def sync_events():
    """Parse DES texts into events and back-fill the filing ledger.

    A filing confirmation does not name the week it covered, so the weeks it
    closed out are INFERRED: every claimable week that had closed by then, was
    still inside its 14-day window, and was not already filed. Inferred entries
    are marked as such rather than passed off as confirmed, because the
    difference matters if a week is ever disputed.
    """
    texts = read_des_texts()
    events = []
    for t in texts:
        events.append({"at": t["at"], "kind": classify(t["text"]), "text": t["text"]})
    write_json(EVENTS, events)

    filings = read_json(FILINGS, {})
    inferred = []
    for ev in events:
        if ev["kind"] != "filing_confirmed":
            continue
        when = datetime.fromisoformat(ev["at"]).date()
        for we in recent_weeks(26, today=when):
            key = we.isoformat()
            if key < CLAIM_FILED:
                continue
            if filings.get(key, {}).get("filed"):
                continue
            if not (we < when <= we + timedelta(days=DEADLINE_DAYS)):
                continue
            filings[key] = {
                "filed": True,
                "filed_at": ev["at"],
                "confirmation": None,
                "certainty": "inferred from DES SMS -- confirm on the portal",
                "note": "Auto-seeded from the filing confirmation text. The SMS "
                        "does not name the week it covered.",
            }
            inferred.append(key)
    if inferred:
        write_json(FILINGS, filings)
    return events, inferred


# ---------------------------------------------------------------- assessment

def urgency(days_left):
    if days_left < 0:
        return "expired", "MIST URGENT", "Basso"
    if days_left <= 1:
        return "critical", "MIST URGENT", "Basso"
    if days_left <= 3:
        return "urgent", "MIST", "Purr"
    if days_left <= 7:
        return "nudge", "MIST", "Purr"
    return "quiet", None, None


def assess():
    filings = read_json(FILINGS, {})
    weeks = [week_record(we, filings) for we in recent_weeks(6)]
    open_weeks = []
    for w in weeks:
        if w["state"] != "OPEN":
            continue
        tier, _, _ = urgency(w["days_until_deadline"])
        ws = tool_work_search({"week_ending": w["week_ending"]})
        w["tier"] = tier
        w["work_search_confirmed"] = ws["confirmed_count"]
        w["work_search_short_by"] = max(0, MIN_ACTIVITIES - ws["confirmed_count"])
        open_weeks.append(w)
    expired = [w for w in weeks if w["state"].startswith("EXPIRED")]
    return weeks, open_weeks, expired


def notify(message, title, sound):
    if not NOTIFY.exists():
        print(f"[notify unavailable] {title}: {message}")
        return
    subprocess.run([str(NOTIFY), message, title, sound, LOGIN_URL], check=False)


def cmd_check(args):
    events, inferred = sync_events()
    weeks, open_weeks, expired = assess()

    if inferred:
        print(f"Ledger auto-seeded from DES texts: {', '.join(inferred)}")

    state = read_json(NOTIFIED, {})
    pending = [e for e in events
               if e["kind"] == "correspondence" and not state.get(f"corr:{e['at']}")]
    for e in pending:
        n = correspondence_count(e["text"])
        notify(f"{n} unread DES correspondence from {e['at'][:10]}, flagged "
               "time-sensitive. Viewing it is not answering it.",
               "MIST URGENT", "Basso")
        state[f"corr:{e['at']}"] = datetime.now().isoformat(timespec="seconds")
        print(f"[notified/correspondence] {e['at']} -- {n} item(s)")

    actionable = [w for w in open_weeks if w["tier"] != "quiet"]
    for w in sorted(actionable, key=lambda x: x["days_until_deadline"]):
        tier, title, sound = urgency(w["days_until_deadline"])
        key = f"{w['week_ending']}:{tier}"
        if state.get(key) and not args.force:
            continue
        days = w["days_until_deadline"]
        when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
        short = w["work_search_short_by"]
        msg = f"Week ending {w['week_ending']} expires {when}. A week's payment is at stake."
        if short:
            msg += (f" Work search is {short} short of {MIN_ACTIVITIES} -- those have "
                    "to be logged before you file.")
        notify(msg, title, sound)
        state[key] = datetime.now().isoformat(timespec="seconds")
        print(f"[notified/{tier}] {w['week_ending']} -- {days}d left")

    if not actionable and not pending:
        print("Nothing needs attention. Open weeks:",
              ", ".join(w["week_ending"] for w in open_weeks) or "none")
    write_json(NOTIFIED, state)

    for w in expired:
        key = f"{w['week_ending']}:expired"
        if not state.get(key):
            notify(f"Week ending {w['week_ending']} expired unfiled. That payment is "
                   "gone. Worth calling DES to check for an exception.",
                   "MIST URGENT", "Basso")
            state[key] = datetime.now().isoformat(timespec="seconds")
            write_json(NOTIFIED, state)


def cmd_sync(args):
    events, inferred = sync_events()
    kinds = {}
    for e in events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    print(f"{len(events)} DES messages parsed: "
          + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    if inferred:
        print("Ledger seeded (inferred, confirm on the portal):", ", ".join(inferred))
    else:
        print("Ledger unchanged.")
    for e in events:
        if e["kind"] == "correspondence":
            n = correspondence_count(e["text"])
            print(f"  ! {e['at'][:16]} -- {n} correspondence, flagged time-sensitive")


def cmd_report(args):
    events, _ = sync_events()
    weeks, open_weeks, expired = assess()
    print(f"UInteract claim -- {date.today().isoformat()}\n")
    print("Weeks")
    for w in weeks:
        line = f"  {w['week_ending']}  {w['state']}"
        if w["state"] == "OPEN":
            line += (f"  ({w['days_until_deadline']}d left, "
                     f"work search {w['work_search_confirmed']}/{MIN_ACTIVITIES})")
        elif w.get("certainty"):
            line += f"  [{w['certainty']}]"
        print(line)

    logins = [e for e in events if e["kind"] == "login_notice"]
    print(f"\nLogin notices from DES: {len(logins)}")
    for e in logins[-5:]:
        print(f"  {e['at']}")
    print(f"  Any login Alex cannot account for is a real security question: {DES_PHONE}")

    pending = [e for e in events if e["kind"] == "correspondence"]
    if pending:
        total = sum(correspondence_count(e["text"]) for e in pending)
        print(f"\nCorrespondence notices ({total} item(s), all flagged time-sensitive):")
        for e in pending:
            print(f"  {e['at'][:16]} -- {correspondence_count(e['text'])} item(s)")
        print("  Viewing is not responding. Each one needs a Things task with its "
              "real deadline.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync").set_defaults(func=cmd_sync)
    c = sub.add_parser("check")
    c.add_argument("--force", action="store_true", help="Re-notify even if already sent")
    c.set_defaults(func=cmd_check)
    sub.add_parser("report").set_defaults(func=cmd_report)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
