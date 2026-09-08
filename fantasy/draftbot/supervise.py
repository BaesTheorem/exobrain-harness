#!/usr/bin/env python3
"""Poll the armed autopilot and report progress while a draft runs.

MIST cannot sit in the pick loop (a round trip costs 20-60s against a 30s mock
clock), so the supervision she does between picks needs a single owner of the
cmd.json channel. Two pollers on that channel race on result.json, which is the
same reason arm.py and watch.py must not run together. This is that one owner:
it writes a line per poll to supervise.log, and drives a MIST Console progress
bar off roster count, so a ten-minute draft is not a silent wait.

Usage:
    python3 supervise.py [interval_seconds]     # runs until the roster hits 16
"""

import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
CMD = HERE / "cmd.json"
RESULT = HERE / "result.json"
STATE = HERE / "state.json"
LOG = HERE / "supervise.log"
PROGRESS = "/Users/alexhedtke/Documents/mist-console/bin/mist-progress"
NOTIFY = HERE.parent.parent / "mist-voice" / "bin" / "mist-notify"
BAR = "draftbot-mock"
ROSTER_SIZE = 16

# Ways the draft room dies, each seen for real. The recovery (reload, then
# re-arm) is proven and takes ~30s, so it is automated: two consecutive
# sightings trigger it. state.json is written by the driver on its own clock,
# so reading it races nothing.
#
#   "Loading your draft"  -- seat-9 room hung on this banner while the clock ran
#                            and ESPN autodrafted eight rounds (2026-08-24).
#   "Connection Failed"   -- the room drops its socket to the draft server and
#                            does NOT come back. Found 2026-09-07: the autopilot
#                            polled a dead page in silence for 23 minutes while
#                            the draft ran on without it. Retry does nothing;
#                            only a reload clears it.
HANG_MARKERS = (
    "Loading your draft",
    "Connection Failed",
    "Multiple attempts to connect",
    # A second session for the same team (Alex opening the room on his phone)
    # bumps this one; a reload makes THIS session the newest, which bumps the
    # other one back. Exact banner text unconfirmed, so both casings.
    "Duplicate Connection",
    "duplicate connection",
)

# A room that has gone blank renders no visible text at all -- the failure has
# no marker to match, so it needs its own test. Anything this short is not a
# draft room. (The wedged page measured 0 characters for 90s straight.)
MIN_ROOM_TEXT = 200


def send(js, wait=30):
    RESULT.unlink(missing_ok=True)
    cid = int(time.time() * 1000) % 100000
    CMD.write_text(json.dumps({"id": cid, "op": "eval", "arg": js}))
    deadline = time.time() + wait
    while time.time() < deadline:
        if RESULT.exists():
            try:
                r = json.loads(RESULT.read_text())
                if r.get("id") == cid:
                    return r
            except json.JSONDecodeError:
                pass
        time.sleep(0.4)
    return {"ok": False, "error": "timeout"}


def bar(action, **kw):
    args = [PROGRESS, action, "--id", BAR]
    for k, v in kw.items():
        args += [f"--{k}", str(v)]
    try:
        subprocess.run(args, check=False, capture_output=True, timeout=10)
    except Exception:
        pass


def note(line):
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} {line}\n")
        fh.flush()
    print(line, flush=True)


def hung():
    """Why the room looks dead, or None if it looks fine.

    Returns the reason so the log and the banner can name it: a silent
    auto-recovery that does not say what it recovered from is how a recurring
    failure stays invisible.
    """
    try:
        st = json.loads(STATE.read_text())
        txt = st.get("text", "")
    except Exception:
        return None
    # A swipe-back or a stray click can walk the window off the draft page;
    # the page it lands on is healthy text, so the markers never fire.
    if "/draft" not in (st.get("url") or "/draft"):
        return "wrong page"
    for marker in HANG_MARKERS:
        if marker in txt:
            return marker
    if len(txt.strip()) < MIN_ROOM_TEXT:
        return "blank page"
    return None


def recover(reason="unknown"):
    """Reload the room and re-arm the autopilot. ~30 seconds, picks resume."""
    note(f"HANG: '{reason}' persisted; reloading and re-arming")
    try:
        subprocess.run(
            [str(NOTIFY), f"Draft room died ({reason}); auto-recovering "
                          "(reload + re-arm)",
             "MIST draftbot", "default", "console"],
            check=False, capture_output=True, timeout=15,
        )
    except Exception:
        pass
    RESULT.unlink(missing_ok=True)
    if reason == "wrong page":
        url = (HERE / "url.txt").read_text().strip()
        CMD.write_text(json.dumps({"id": int(time.time() * 1000) % 100000,
                                   "op": "goto", "arg": url}))
    else:
        CMD.write_text(json.dumps({"id": int(time.time() * 1000) % 100000,
                                   "op": "reload", "arg": ""}))
    time.sleep(10)
    r = subprocess.run(
        [sys.executable, str(HERE / "arm.py"), "arm"],
        capture_output=True, text=True, timeout=120,
    )
    note(f"re-arm: {(r.stdout or r.stderr).strip()[:120]}")


def escalate(msg):
    """Loud, urgent notification. Used when auto-recovery is not working."""
    note(f"ESCALATE: {msg}")
    try:
        subprocess.run(
            [str(NOTIFY), msg, "MIST draftbot", "default", "console",
             "--urgency", "timeSensitive"],
            check=False, capture_output=True, timeout=15,
        )
    except Exception:
        pass


ROOM_LOG = HERE / "room_picks.log"
ROOM_REC = HERE / "room_picks.jsonl"
BOT_LOG = HERE / "bot_log.txt"

# The league API reports zero picks while a live draft runs (checked 19:04 on
# draft night, fifteen picks in), so the only live source for the OTHER twelve
# teams is the room's own Pick History panel, which ESPN keeps in the DOM even
# while the Players tab is showing. Read it, never click it: the autopilot
# drives the Players tab and a tab switch would blind it. Rows are found by
# shape (an element with 5+ cells whose text starts with the pick number and
# names a position), not by class, because ESPN's class names are hashed.
HIST_JS = """() => {
  const roots = [...document.querySelectorAll('[class*="pick-history"]')];
  if (!roots.length) return 'NOHIST';
  const root = roots.reduce((a, b) => (a.textContent.length >= b.textContent.length ? a : b));
  const isRow = (e) => e.children.length >= 5 && /^\\d+\\s*\\S/.test((e.textContent||'').trim())
                       && /(QB|RB|WR|TE|K|D\\/ST)/.test(e.textContent);
  const rows = [...root.querySelectorAll('*')].filter(e => isRow(e) && ![...e.children].some(isRow));
  return JSON.stringify(rows.map(r => [...r.children].map(c => (c.textContent||'').replace(/\\s+/g,' ').trim())));
}"""


def room_history(seen):
    """Append picks newer than `seen` to room_picks.log; return the new high."""
    res = send(HIST_JS, wait=15)
    d = res.get("data") if res.get("ok") else None
    if not isinstance(d, str) or not d.startswith("["):
        return seen
    try:
        rows = json.loads(d)
    except json.JSONDecodeError:
        return seen
    high = seen
    for cells in rows:
        try:
            n = int(cells[0])
        except (ValueError, IndexError):
            continue
        if n <= seen:
            continue
        line = f"{time.strftime('%H:%M:%S')} #{n:3d} " + " | ".join(cells[1:])
        with ROOM_LOG.open("a") as fh:
            fh.write(line + "\n")
        with ROOM_REC.open("a") as fh:
            fh.write(json.dumps({"pick": n, "cells": cells,
                                 "at": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n")
        high = max(high, n)
    return high


def main():
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    room_seen = 0
    bot_seen = set()
    try:
        bot_seen = set(BOT_LOG.read_text().splitlines())
    except OSError:
        pass
    try:
        for ln in ROOM_REC.read_text().splitlines():
            room_seen = max(room_seen, json.loads(ln).get("pick", 0))
    except (OSError, json.JSONDecodeError):
        pass
    LOG.write_text("")
    bar("start", label="Mock draft: Chaos Legion", total=ROSTER_SIZE, current=0,
        unit="picks", detail="waiting for the clock")

    seen = 0
    idle = 0
    hang_polls = 0
    recoveries = 0
    while True:
        reason = hung()
        if reason:
            hang_polls += 1
            if hang_polls >= 2:
                bar("set", detail=f"room died ({reason}); reloading + re-arming")
                recover(reason)
                recoveries += 1
                hang_polls = 0
                # A room that keeps dying is not recovering, and on a live
                # clock every failed round is ESPN autodrafting for us. Say so
                # loudly rather than looping quietly forever.
                if recoveries in (3, 6, 10):
                    escalate(f"draft room has died {recoveries}x "
                             f"(latest: {reason}) -- may need a human")
                continue
        else:
            hang_polls = 0
        res = send("() => window.__mist ? window.__mist.status() : null")
        d = res.get("data") if res.get("ok") else None
        if not isinstance(d, dict):
            note(f"status unavailable: {res.get('error') or d}")
            # A healthy page with no autopilot in it means the page was
            # reloaded under us: Alex refreshed the bot window 49 seconds
            # before the 2026 live draft, and the hang path never fires on a
            # healthy page, so nothing re-armed it. Re-arm here.
            if res.get("ok") and d is None and hung() is None:
                r = subprocess.run(
                    [sys.executable, str(HERE / "arm.py"), "arm"],
                    capture_output=True, text=True, timeout=120,
                )
                note(f"re-arm (autopilot missing): "
                     f"{(r.stdout or r.stderr).strip()[:120]}")
            idle += 1
            if idle > 40:
                bar("fail", detail="autopilot went unreachable")
                return
            time.sleep(interval)
            continue

        # idle counts consecutive FAILED polls only. It used to count
        # unchanged-roster polls too, so after eight quiet minutes a single
        # timeout tripped the exit and the supervisor died mid-wait (2026-09-07,
        # 18:58, two minutes before the live draft).
        idle = 0
        # Keep the autopilot's own log (CLICK/OK lines carry vor, vona, adp and
        # the board size scored) on disk: a reload or re-arm wipes it in-page,
        # and it is the only record of WHY each pick was made.
        for ln in d.get("log", []):
            if ln not in bot_seen:
                bot_seen.add(ln)
                with BOT_LOG.open("a") as fh:
                    fh.write(ln + "\n")
        total = d["total"]
        detail = f"round {d['round']}  {d['counts']}"
        bar("set", current=total, total=ROSTER_SIZE, detail=detail)
        if total != seen:
            note(f"roster {total}/{ROSTER_SIZE}  {detail}")
            for p in d["picks"][seen:]:
                note(f"    + {p['player']} [{p['pos']}]")
            seen = total

        room_seen = room_history(room_seen)
        if total >= ROSTER_SIZE:
            bar("done", detail=f"16/16 drafted  {d['counts']}")
            note("roster complete")
            room_history(room_seen)
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
