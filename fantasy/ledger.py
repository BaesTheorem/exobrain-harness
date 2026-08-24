#!/usr/bin/env python3
"""Disagreement ledger: make the board's contested calls pay rent.

Every time the drafting board and an independent source (FantasyPros ECR, the
CBS+FFToday consensus judge) disagree about two players, that call is either
resolved by fiat and forgotten, or registered here as a prediction and settled
with real season points. This file is the second half of the self-grading-loop
fix: the consensus judge detects disagreement before the season, the ledger
scores it after, and ONLY settled ledger results are allowed to flow back into
how the board is built (see the firewall note in consensus.py). It is also the
designated instrument for the elite-bias correction parked in vor.py: that
correction failed validation against other projections, because they share the
industry's elite optimism; actual points are the only judge that does not.

Entries are claims of the form "the board says A outscores B this season."
Settling pulls each player's actual season-to-date fantasy points from ESPN's
league API (read-only, same credentials as bin/ff).

Usage:
    python3 fantasy/ledger.py list
    python3 fantasy/ledger.py add --a "Player A" --b "Player B" \
        --claim "board ranks A over B at pick 117" [--basis "..."]
    python3 fantasy/ledger.py settle          # updates actuals, prints score
"""

import argparse
import json
import pathlib
import re
import unicodedata
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
LEDGER = HERE / "ledger.json"
CREDS = HERE / "espn-credentials.json"
BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"


def norm(s):
    s = unicodedata.normalize("NFKD", s).replace("’", "").replace("'", "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def load():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"entries": []}


def save(data):
    LEDGER.write_text(json.dumps(data, indent=1))


def actual_points(season=None):
    """Actual season-to-date fantasy points per player, from ESPN (read-only).

    kona_player_info carries, per player, one stat entry per (season, source,
    split); actuals are source 0, and the season-total split 0 exists from day
    one holding 0.0 until games are played. Validated against the live API on
    2026-08-24: Gibbs shows (2026,0,0)=0.0 pre-season and (2025,0,0)=366.9,
    which is also this function's positive control (pass season=2025 and Gibbs
    must come back 366.9, proving the parse reads real totals).

    Returns {} when every total is zero, i.e. the season has not started.
    """
    creds = json.loads(CREDS.read_text())
    season = season or creds["season"]
    url = (
        f"{BASE}/seasons/{creds['season']}/segments/0/leagues/"
        f"{creds['league_id']}?view=kona_player_info"
    )
    filt = {"players": {"limit": 2000, "sortPercOwned":
            {"sortAsc": False, "sortPriority": 1}}}
    req = urllib.request.Request(
        url,
        headers={
            "Cookie": f"espn_s2={creds['espn_s2']}; SWID={creds['SWID']}",
            "X-Fantasy-Filter": json.dumps(filt),
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    out = {}
    for entry in data.get("players", []):
        p = entry.get("player") or {}
        name = p.get("fullName")
        if not name:
            continue
        for st in p.get("stats", []):
            if (
                st.get("seasonId") == int(season)
                and st.get("statSourceId") == 0
                and st.get("statSplitTypeId") == 0
            ):
                out[norm(name)] = round(st.get("appliedTotal", 0.0), 1)
    if all(v == 0.0 for v in out.values()):
        return {}
    return out


def cmd_add(args):
    data = load()
    data["entries"].append(
        {
            "id": max((e["id"] for e in data["entries"]), default=0) + 1,
            "date": args.date,
            "a": args.a,
            "b": args.b,
            "claim": args.claim,
            "basis": args.basis,
            "status": "open",
        }
    )
    save(data)
    print(f"registered: {args.a} > {args.b}")


def cmd_list(_args):
    data = load()
    if not data["entries"]:
        print("ledger is empty")
        return
    for e in data["entries"]:
        line = f"#{e['id']} [{e['status']}] {e['a']} > {e['b']}  ({e['claim']})"
        if "a_pts" in e:
            mark = "RIGHT" if e["a_pts"] > e["b_pts"] else "WRONG"
            line += f"  actuals {e['a_pts']} vs {e['b_pts']} -> board {mark}"
        print(line)


def cmd_settle(_args):
    data = load()
    if not data["entries"]:
        print("ledger is empty")
        return
    pts = actual_points()
    if not pts:
        print("no actuals on ESPN yet (season not started); nothing to settle")
        return
    right = wrong = pending = 0
    for e in data["entries"]:
        a, b = pts.get(norm(e["a"])), pts.get(norm(e["b"]))
        if a is None or b is None:
            pending += 1
            continue
        e["a_pts"], e["b_pts"] = a, b
        e["status"] = "settling"
        if a > b:
            right += 1
        else:
            wrong += 1
    save(data)
    print(f"board right {right}, wrong {wrong}, pending {pending}")
    cmd_list(_args)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("--a", required=True, help="player the board prefers")
    add.add_argument("--b", required=True, help="player the other source prefers")
    add.add_argument("--claim", required=True)
    add.add_argument("--basis", default="")
    add.add_argument("--date", default="")
    sub.add_parser("list")
    sub.add_parser("settle")
    args = ap.parse_args()
    {"add": cmd_add, "list": cmd_list, "settle": cmd_settle}[args.cmd](args)


if __name__ == "__main__":
    main()
