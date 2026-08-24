#!/usr/bin/env python3
"""Outside examiner: audit the autopilot's drafting against FantasyPros ECR.

The bot and its simulator share assumptions (the same value board, the same
projections), so they cannot catch a board pathology by agreeing with each
other. This replays a simulated draft and, at every one of our picks, compares
the pick against the best player still available by FantasyPros expert
consensus (~100+ experts). It is an audit, not a target: a flagged pick is a
question to answer, and the answer is allowed to be "our board is right and
consensus is wrong here," said explicitly.

ECR comes embedded in the public PPR cheat-sheet page and is cached to
draftbot/ecr.json (gitignored). Refresh on draft morning with --refresh.

Usage:
    python3 examiner.py --seat 5 [--seed 0] [--model human] [--refresh]
"""

import argparse
import json
import pathlib
import re
import sys
import unicodedata
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
CACHE = HERE / "draftbot" / "ecr.json"
URL = "https://www.fantasypros.com/nfl/rankings/ppr-cheatsheets.php"

sys.path.insert(0, str(HERE))
import sim  # noqa: E402

# A pick this many ECR ranks worse than the best available gets flagged.
# 13 ranks is one full round of this league.
FLAG_AT = 13


def norm(s):
    s = unicodedata.normalize("NFKD", s).replace("’", "").replace("'", "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def load_ecr(refresh=False):
    if CACHE.exists() and not refresh:
        return json.loads(CACHE.read_text())
    req = urllib.request.Request(
        URL, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode()
    m = re.search(r"var ecrData\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        sys.exit("ecrData not found on the cheat-sheet page; layout changed")
    players = json.loads(m.group(1))["players"]
    out = {}
    for p in players:
        name = p["player_name"]
        if p.get("player_position_id") == "DST":
            name = name.split()[-1] + " D/ST"
        out[norm(name)] = {
            "name": p["player_name"],
            "ecr": p["rank_ecr"],
            "pos": p.get("player_position_id"),
            "lo": int(p.get("rank_min") or 0),
            "hi": int(p.get("rank_max") or 999),
        }
    CACHE.write_text(json.dumps(out))
    return out


def simulated_events(seat, seed, model):
    """Replay a simulated draft, capturing the board at each of our picks."""
    import random

    players = sim.load_players()
    rng = random.Random(seed)
    avail = list(players)
    rosters = {s: [] for s in range(1, sim.TEAMS + 1)}
    order = sim.snake_order()
    events = []
    for i, s in enumerate(order):
        rd = i // sim.TEAMS + 1
        if s == seat:
            p = sim.bot_pick(avail, rosters[s], order, i, {})
            events.append((i + 1, rd, p, list(avail)))
        elif model == "human":
            p = sim.human_pick(avail, rosters[s], rd, rng)
        else:
            p = sim.auto_pick(avail, rosters[s], rd, rng)
        rosters[s].append(p)
        avail.remove(p)
    return events


def live_events(ecr, team_needle="Chaos"):
    """Same audit, against the draft actually in the browser.

    The simulated audit can only check the policy against a modeled room. This
    checks the roster that really got drafted, which is the one Alex has to
    play, and it is the only way a live-room pathology (a stale board, a
    mis-clicked row) shows up as anything other than a plausible-looking team.

    The board at each of our picks is reconstructed from the pick order itself:
    every ECR player not yet taken when that pick came up.
    """
    sys.path.insert(0, str(HERE / "draftbot"))
    import grade  # noqa: PLC0415  -- optional dep: only the --live path needs the driver channel

    picks = grade.read_picks()
    taken = set()
    events = []
    for p in picks:
        if (p["team"] or "").startswith(team_needle):
            board = [
                {"name": v["name"], "pos": v["pos"]}
                for k, v in ecr.items()
                if k not in taken
            ]
            rd = (p["pick"] - 1) // sim.TEAMS + 1
            events.append((p["pick"], rd, {"name": p["name"], "pos": None}, board))
        taken.add(norm(p["name"]))
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default="human", choices=["auto", "human"])
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument(
        "--live",
        action="store_true",
        help="audit the draft open in driver.py instead of a simulated one",
    )
    args = ap.parse_args()

    ecr = load_ecr(args.refresh)

    if args.live:
        events = live_events(ecr)
        header = f"LIVE draft room, {len(events)} of our picks"
    else:
        events = simulated_events(args.seat, args.seed, args.model)
        header = f"seat {args.seat}, seed {args.seed}, {args.model} opponents"

    flags = 0
    print(header)
    print(
        f"{'pk':>3} {'rd':>2}  {'our pick':<24} {'ECR':>4}  best available by consensus"
    )
    for pick_no, rd, p, board in events:
        mine = ecr.get(norm(p["name"]))
        my_ecr = mine["ecr"] if mine else None
        # In --live mode the position comes off ECR, because the pick history
        # carries a name and nothing else.
        pos = p["pos"] or (mine["pos"] if mine else None)
        ranked = sorted(
            (ecr[norm(b["name"])] for b in board if norm(b["name"]) in ecr),
            key=lambda e: e["ecr"],
        )
        best = ranked[0] if ranked else None
        mark = ""
        if my_ecr is None:
            mark = " ?? not in ECR"
        elif best is not None and my_ecr - best["ecr"] > FLAG_AT:
            gap = my_ecr - best["ecr"]
            if pos in ("K", "DST", "D/ST"):
                mark = f"  [{gap} past consensus: deliberate K/D-ST timing]"
            else:
                mark = f" <<< {gap} ranks past consensus (they'd take {best['name']})"
                flags += 1
        print(
            f"{pick_no:>3} {rd:>2}  {p['name']:<24} {str(my_ecr or '--'):>4}"
            f"  {best['name'] if best else '--':<24}{mark}"
        )
    print(f"\nflags (non-K/D-ST picks >{FLAG_AT} ECR ranks past consensus): {flags}")


if __name__ == "__main__":
    main()
