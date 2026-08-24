#!/usr/bin/env python3
"""Deploy and supervise the in-page draft autopilot.

Usage:
    python3 arm.py arm          # inject autopilot.js and start it
    python3 arm.py queue [N]    # fill the ESPN queue N deep (default 30)
    python3 arm.py status       # roster counts, picks made, recent log
    python3 arm.py off          # stop the autopilot, leave the queue in place
    python3 arm.py board        # rebuild vor.json (ESPN projections + Ringer ranks)

Talks to driver.py through cmd.json / result.json.
"""

import json
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
CMD = HERE / "cmd.json"
RESULT = HERE / "result.json"
VOR = HERE / "vor.json"
VOR_BUILDER = HERE.parent / "vor.py"

# Target shape for a 16-man roster in 13-team full PPR with one flex.
# The receiver lean is no longer a bonus constant: value over replacement gets it
# from the projection curve itself, because full PPR is the receiver-friendly
# extreme (WR12 returns 71.7% of WR1 while RB12 returns 56.4% and lands below
# WR24). What is left here is caps, required starters, and the bye tiebreak.
CONFIG = {
    "rounds": 16,
    "starters": 9,  # QB RB RB WR WR TE FLEX D/ST K
    "maxQB": 1,  # stream the position; a QB2 is a wasted bench slot
    "maxTE": 1,  # a 2nd TE simulated worse than the WR/RB taken instead, all seats
    "maxRB": 6,
    "maxWR": 8,
    "startRB": 2,  # required starting slots that must be filled
    "startTE": 1,
    # One round AHEAD of the room's late K/D/ST run, not the final rounds.
    # Every observed room (ESPN AUTO and the human-ADP model both) drains the
    # startable defenses in rounds 12-13 and kickers in round 14; waiting past
    # the run leaves a ~0-value defense, while the round-11 alternative pick is
    # a bench lottery ticket. Simulated across 13 seats x 10 rooms x both
    # opponent models (fantasy/sim.py): this pair took #1 finishes from ~75%
    # to ~90%. Streaming in-season stays the plan; this just stops donating
    # draft-day points.
    "dstRoundsLeft": 5,  # D/ST from round 11
    "kRoundsLeft": 3,  # K from round 13
    # A player whose ADP sits right at the next pick is a coin flip. 0 takes ADP
    # at face value; raising it assumes players go earlier than ADP says, which
    # makes every position look scarcer and pulls picks forward.
    "adpCushion": 0,
    "freeBye": 8,  # Alex's idle week in a 13-team league: a free bye
    "freeByeBonus": 5,
    "byeStackPenalty": 6,
    "queueDepth": 18,
    "pollMs": 250,
    # ESPN's player list is windowed to ~32 rows. Each pick sweeps the open
    # positions through the position filter, scrolling each to the top, so the
    # board it scores is complete at every position instead of being whatever
    # happened to be on screen.
    "filterDelay": 320,
    "scrollDelay": 130,
    "scrollSteps": 8,
    "confirmDelay": 400,
    "verifyDelay": 1200,
}


def build_board():
    """(Re)build the value-over-replacement table, then load it for injection."""
    subprocess.run([sys.executable, str(VOR_BUILDER)], check=True)
    data = json.loads(VOR.read_text())
    return {
        k: {
            "name": v["name"],
            "pos": v["pos"],
            "vor": v["vor"],
            "adp": v["adp"],
            "bye": v["bye"],
        }
        for k, v in data["players"].items()
    }


def load_board():
    if not VOR.exists():
        return build_board()
    data = json.loads(VOR.read_text())
    return {
        k: {
            "name": v["name"],
            "pos": v["pos"],
            "vor": v["vor"],
            "adp": v["adp"],
            "bye": v["bye"],
        }
        for k, v in data["players"].items()
    }


def send(op, arg, wait=25):
    RESULT.unlink(missing_ok=True)
    cid = int(time.time() * 1000) % 100000
    CMD.write_text(json.dumps({"id": cid, "op": op, "arg": arg}))
    deadline = time.time() + wait
    while time.time() < deadline:
        if RESULT.exists():
            try:
                return json.loads(RESULT.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(0.4)
    return {"ok": False, "error": f"timeout after {wait}s"}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "board":
        print("valued players:", len(build_board()))
        return

    if cmd == "arm":
        values = load_board()
        js = (HERE / "autopilot.js").read_text()
        js = js.replace("__VALUES__", json.dumps(values))
        js = js.replace("__CONFIG__", json.dumps(CONFIG))
        res = send("eval", js)
        print("arm ->", res.get("data") if res.get("ok") else res.get("error"))
        return

    if cmd == "queue":
        depth = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        res = send("eval", f"() => window.__mist.fillQueue({depth})", wait=60)
        data = res.get("data") if res.get("ok") else res.get("error")
        if isinstance(data, dict):
            mark = "OK" if data.get("ok") else "FAILED (ESPN ignored the clicks)"
            print(
                f"queue {mark}: tried {len(data['tried'])}, actually added {data['added']}"
            )
            for i, n in enumerate(data.get("queueNow", []), 1):
                print(f"  {i:>2}. {n}")
        else:
            print("queue ->", data)
        return

    if cmd == "clear":
        print(
            "removed:",
            send("eval", "() => window.__mist.clearQueue()", wait=40).get("data"),
        )
        return

    if cmd == "off":
        print(
            send("eval", "() => { window.__mist.enabled = false; return 'disabled'; }")
        )
        return

    res = send("eval", "() => window.__mist ? window.__mist.status() : 'NOT ARMED'")
    if not res.get("ok"):
        print("error:", res.get("error"))
        return
    d = res["data"]
    if not isinstance(d, dict):
        print(d)
        return
    print(
        f"round {d['round']}   roster {d['total']}   {d['counts']}   enabled={d['enabled']}"
    )
    if d["picks"]:
        print("picks made by autopilot:")
        for p in d["picks"]:
            print(f"  {p['at']}  {p['player']} [{p['pos']}]")
    print("log:")
    for line in d["log"]:
        print("  " + line)


if __name__ == "__main__":
    main()
