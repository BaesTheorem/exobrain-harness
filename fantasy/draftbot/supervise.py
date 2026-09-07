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
)

# A room that has gone blank renders no visible text at all -- the failure has
# no marker to match, so it needs its own test. Anything this short is not a
# draft room. (The wedged page measured 0 characters for 90s straight.)
MIN_ROOM_TEXT = 200


def send(js, wait=30):
    RESULT.unlink(missing_ok=True)
    CMD.write_text(
        json.dumps({"id": int(time.time() * 1000) % 100000, "op": "eval", "arg": js})
    )
    deadline = time.time() + wait
    while time.time() < deadline:
        if RESULT.exists():
            try:
                return json.loads(RESULT.read_text())
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
        txt = json.loads(STATE.read_text()).get("text", "")
    except Exception:
        return None
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
    CMD.write_text(
        json.dumps({"id": int(time.time() * 1000) % 100000, "op": "reload", "arg": ""})
    )
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


def main():
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
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
            idle += 1
            if idle > 40:
                bar("fail", detail="autopilot went unreachable")
                return
            time.sleep(interval)
            continue

        total = d["total"]
        detail = f"round {d['round']}  {d['counts']}"
        bar("set", current=total, total=ROSTER_SIZE, detail=detail)
        if total != seen:
            note(f"roster {total}/{ROSTER_SIZE}  {detail}")
            for p in d["picks"][seen:]:
                note(f"    + {p['player']} [{p['pos']}]")
            seen = total
            idle = 0
        else:
            idle += 1

        if total >= ROSTER_SIZE:
            bar("done", detail=f"16/16 drafted  {d['counts']}")
            note("roster complete")
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
