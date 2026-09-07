#!/usr/bin/env python3
"""Get into the draft room the moment it opens, then arm the autopilot.

Why this exists (2026-09-07). Every mock before today reached the room by
joining from the lobby, which lands you inside automatically, so the bot was
never asked to open a door. A live league draft is not like that: the room
announces itself with

    The draft room is now open!   [ Enter The Draft ]

and sits there. Nothing happens until something clicks it. During a rehearsal
this afternoon that button went unclicked for six minutes and ESPN autodrafted
four rounds before we got in -- the same failure that cost 73 picks in ~90
seconds on 2026-08-24, arriving by a different door.

Clicking it is therefore not something to leave to a human at a cookout, or to
an assistant whose round trip is 20-60 seconds. This polls fast and clicks the
instant the control appears, then hands off:

    python3 enter.py "<draft url>"     # then supervise.py takes over

It is deliberately separate from supervise.py, which owns the command channel
once the draft is running. Run this first, let it exit, then start that.
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

# Text ESPN puts on the way in. Matched case-insensitively against the button
# label; the room-open banner is the cue that one of these is now live.
ENTER_LABELS = ("Enter The Draft", "Enter Draft Room", "Join Draft", "Enter Draft")

# Proof we are actually inside: the round header only renders in the room.
# Checked instead of the click's return value, because a click reports intent
# and this reports arrival.
IN_ROOM_MARKERS = ("RND ", "ON THE CLOCK", "Roster Limits")


def send(op, arg, wait=30):
    RESULT.unlink(missing_ok=True)
    CMD.write_text(json.dumps({"id": int(time.time() * 1000) % 100000,
                               "op": op, "arg": arg}))
    deadline = time.time() + wait
    while time.time() < deadline:
        if RESULT.exists():
            try:
                return json.loads(RESULT.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(0.3)
    return {"ok": False, "error": f"timeout after {wait}s"}


def page_text():
    try:
        return json.loads(STATE.read_text()).get("text", "")
    except Exception:
        return ""


def in_room(txt=None):
    txt = page_text() if txt is None else txt
    return any(m in txt for m in IN_ROOM_MARKERS)


CLICK_JS = """(() => {
  const labels = %s;
  const els = [...document.querySelectorAll('button, a, [role=button]')];
  for (const want of labels) {
    const el = els.find(e => (e.textContent || '').trim().toLowerCase()
                              === want.toLowerCase());
    if (el && !el.disabled) { el.click(); return 'clicked: ' + want; }
  }
  // Fall back to a contains-match, since ESPN has renamed this control before.
  const el = els.find(e => /enter\\s+(the\\s+)?draft|join\\s+draft/i
                             .test((e.textContent || '').trim()));
  if (el && !el.disabled) { el.click(); return 'clicked (fuzzy): '
                                              + el.textContent.trim(); }
  return null;
})()""" % json.dumps(list(ENTER_LABELS))


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else (HERE / "url.txt").read_text().strip()
    deadline = time.time() + float(sys.argv[2]) if len(sys.argv) > 2 else time.time() + 3600

    print(f"navigating to {url}")
    send("goto", url, wait=90)

    clicked = False
    while time.time() < deadline:
        txt = page_text()
        if in_room(txt):
            print("IN THE ROOM")
            break
        res = send("eval", CLICK_JS, wait=20)
        got = res.get("data") if res.get("ok") else None
        if got:
            print(f"{time.strftime('%H:%M:%S')} {got}")
            clicked = True
            time.sleep(4)
            continue
        if not clicked:
            print(f"{time.strftime('%H:%M:%S')} waiting for the room to open...")
        time.sleep(3)
    else:
        sys.exit("never got into the draft room before the deadline")

    r = subprocess.run([sys.executable, str(HERE / "arm.py"), "arm"],
                       capture_output=True, text=True, timeout=120)
    print(f"arm: {(r.stdout or r.stderr).strip()[:200]}")
    print("now start the supervisor:  python3 supervise.py 12")


if __name__ == "__main__":
    main()
