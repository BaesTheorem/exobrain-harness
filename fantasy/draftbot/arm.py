#!/usr/bin/env python3
"""Deploy and supervise the in-page draft autopilot.

Usage:
    python3 arm.py arm          # inject autopilot.js and start it
    python3 arm.py queue [N]    # fill the ESPN queue N deep (default 30)
    python3 arm.py status       # roster counts, picks made, recent log
    python3 arm.py off          # stop the autopilot, leave the queue in place
    python3 arm.py board        # regenerate board_ranks.json from ringer_board

Talks to driver.py through cmd.json / result.json.
"""

import json
import pathlib
import re
import sys
import time
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
CMD = HERE / "cmd.json"
RESULT = HERE / "result.json"
RANKS = HERE / "board_ranks.json"
BOARD = HERE.parent / "ringer_board.json"

# Target shape for a 16-man roster in 13-team full PPR with one flex.
# Receiver-heavy on purpose: in full PPR, WR12 returns 71.7% of WR1 while RB12
# returns 56.4% and lands below WR24. The 2026-08-24 mock ended RB6/WR4, which
# is the inversion of what this format rewards.
CONFIG = {
    "rounds": 16,
    "maxQB": 1,          # stream the position; a QB2 is a wasted bench slot
    "maxTE": 2,
    "maxRB": 6,
    "maxWR": 8,
    "startRB": 2,       # required starting slots that must be filled
    "startTE": 1,
    "bpaRounds": 4,      # rounds 1-4 are pure best-player-available
    "wantWR": 6,         # bonus applies while under this
    "wantRB": 5,
    "wrBonus": 12,
    "rbBonus": 8,
    "dstRoundsLeft": 1,  # D/ST only when <=1 round remains after this pick
    "kRoundsLeft": 0,    # K only in the final round
    "unrankedPenalty": 70,
    "queueDepth": 30,
    "pollMs": 250,
    "confirmDelay": 400,
    "verifyDelay": 1200,
}


def norm(s):
    s = unicodedata.normalize("NFKD", s).replace("’", "").replace("'", "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def build_board():
    players = json.loads(BOARD.read_text())["players"]
    ranks = {norm(p["name"]): p["rank"] for p in players}
    RANKS.write_text(json.dumps(ranks))
    return ranks


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
        print("ranked players:", len(build_board()))
        return

    if cmd == "arm":
        ranks = json.loads(RANKS.read_text()) if RANKS.exists() else build_board()
        js = (HERE / "autopilot.js").read_text()
        js = js.replace("__RANKS__", json.dumps(ranks))
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
            print(f"queue {mark}: tried {len(data['tried'])}, actually added {data['added']}")
            for i, n in enumerate(data.get("queueNow", []), 1):
                print(f"  {i:>2}. {n}")
        else:
            print("queue ->", data)
        return

    if cmd == "clear":
        print("removed:", send("eval", "() => window.__mist.clearQueue()", wait=40).get("data"))
        return

    if cmd == "off":
        print(send("eval", "() => { window.__mist.enabled = false; return 'disabled'; }"))
        return

    res = send("eval", "() => window.__mist ? window.__mist.status() : 'NOT ARMED'")
    if not res.get("ok"):
        print("error:", res.get("error"))
        return
    d = res["data"]
    if not isinstance(d, dict):
        print(d)
        return
    print(f"round {d['round']}   roster {d['total']}   {d['counts']}   enabled={d['enabled']}")
    if d["picks"]:
        print("picks made by autopilot:")
        for p in d["picks"]:
            print(f"  {p['at']}  {p['player']} [{p['pos']}]")
    print("log:")
    for line in d["log"]:
        print("  " + line)


if __name__ == "__main__":
    main()
