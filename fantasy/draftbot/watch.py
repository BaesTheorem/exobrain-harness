#!/usr/bin/env python3
"""Stream new autopilot log lines, one per line of stdout, for Monitor.

Owns the cmd.json/result.json channel while it runs -- do not run arm.py at the
same time or the two will race on the same result file.
"""

import json
import pathlib
import time

HERE = pathlib.Path(__file__).resolve().parent
CMD = HERE / "cmd.json"
RESULT = HERE / "result.json"

STATUS_JS = "() => window.__mist ? window.__mist.status() : null"
INTERESTING = ("CLICK", "OK ", "FAIL", "auto-queue", "NO CANDIDATE", "ERR", "QUEUE")


def send(js, wait=20):
    RESULT.unlink(missing_ok=True)
    cid = int(time.time() * 1000) % 100000
    CMD.write_text(json.dumps({"id": cid, "op": "eval", "arg": js}))
    deadline = time.time() + wait
    while time.time() < deadline:
        if RESULT.exists():
            try:
                return json.loads(RESULT.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(0.3)
    return None


def main():
    seen = set()
    last_total = None
    quiet = 0
    while True:
        res = send(STATUS_JS)
        if res and res.get("ok") and isinstance(res.get("data"), dict):
            d = res["data"]
            for line in d.get("log", []):
                if line in seen:
                    continue
                seen.add(line)
                if any(k in line for k in INTERESTING):
                    print(f"{line}", flush=True)
            total = d.get("total")
            if total != last_total and last_total is not None:
                print(f"ROSTER {last_total} -> {total}   {d.get('counts')}   round {d.get('round')}", flush=True)
            if total != last_total:
                last_total = total
                quiet = 0
            else:
                quiet += 1
            if total and total >= 16:
                print(f"DRAFT COMPLETE  {d.get('counts')}", flush=True)
                return
        else:
            quiet += 1
        if quiet > 400:
            print("WATCHER IDLE 400 polls, exiting", flush=True)
            return
        time.sleep(3)


if __name__ == "__main__":
    main()
