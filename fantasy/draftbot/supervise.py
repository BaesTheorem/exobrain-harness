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
LOG = HERE / "supervise.log"
PROGRESS = "/Users/alexhedtke/Documents/mist-console/bin/mist-progress"
BAR = "draftbot-mock"
ROSTER_SIZE = 16


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


def main():
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    LOG.write_text("")
    bar("start", label="Mock draft: Chaos Legion", total=ROSTER_SIZE, current=0,
        unit="picks", detail="waiting for the clock")

    seen = 0
    idle = 0
    while True:
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
