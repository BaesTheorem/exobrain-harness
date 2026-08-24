#!/usr/bin/env python3
"""Offline draft simulator: test autopilot policies across all 13 seats at once.

A live practice draft costs eight minutes and gives one data point from one
seat. This gives all thirteen seats in under a second, so policy questions
("should the wheel take a QB?") get answered by measurement instead of by one
anecdote. Opponents are modeled as ESPN AUTO teams: they draft by ADP subject to
roster limits, which matches the observed rooms (picks 1-12 of the seat-13 room
were ADP order almost exactly, and their K/D/ST arrive on schedule because
kicker ADPs sit in the 150s-160s).

The bot policy here mirrors autopilot.js score() -- VONA with the survive-to-
next-turn floor, horizon skipping own back-to-back picks, caps, starter
reservation, bye tiebreaks. Keep them in sync when either changes.

Grading is the same optimal-starting-lineup metric as draftbot/grade.py, so
offline and live results are comparable.
"""

import argparse
import json
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
VOR = HERE / "draftbot" / "vor.json"

TEAMS = 13
ROUNDS = 16

# The autopilot's live config is the single source of truth. A hand-copied CFG
# here silently drifted (this file kept the old K/D/ST punt after arm.py was
# tuned), which made "default policy" sim runs measure a policy nobody ships.
sys.path.insert(0, str(HERE / "draftbot"))
import arm  # noqa: E402

CFG = {
    k: arm.CONFIG[k]
    for k in (
        "maxQB",
        "maxTE",
        "maxRB",
        "maxWR",
        "startRB",
        "startTE",
        "dstRoundsLeft",
        "kRoundsLeft",
        "freeBye",
        "freeByeBonus",
        "byeStackPenalty",
        "starters",
        "benchBalance",
    )
}
AUTO_CAPS = {"QB": 2, "RB": 8, "WR": 8, "TE": 3, "K": 1, "D/ST": 1}
FLEX = ("RB", "WR", "TE")


def load_players():
    data = json.loads(VOR.read_text())
    base = data["baseline"]
    out = []
    for k, v in data["players"].items():
        out.append(
            {
                "key": k,
                "name": v["name"],
                "pos": v["pos"],
                "vor": v["vor"],
                "adp": v["adp"],
                "bye": v["bye"],
                "proj": v["vor"] + base.get(v["pos"], 0.0),
                "espnRank": v.get("espnRank", 9999),
            }
        )

    return out


def snake_order():
    order = []
    for rd in range(ROUNDS):
        seats = range(1, TEAMS + 1) if rd % 2 == 0 else range(TEAMS, 0, -1)
        order.extend(seats)
    return order


def auto_pick(avail, roster, rd=1, rng=None):
    """ESPN AUTO model, calibrated against the real seat-13 room (2026-08-24).

    Skill picks follow ESPN's own PPR draft rank, not crowd ADP: replaying the
    room against an ADP model matched 18% of AUTO picks, and the first misses
    (Bijan 1.01 over Gibbs, Rice over London) are exactly ESPN-rank order. K and
    D/ST are forced by round instead of rank, because ESPN ranks defenses in the
    200s yet every AUTO team drafted its defense in rounds 12-13 and its kicker
    in round 14, a run the rank list cannot produce."""
    counts = {}
    for p in roster:
        counts[p["pos"]] = counts.get(p["pos"], 0) + 1

    def best(pos):
        c = [p for p in avail if p["pos"] == pos]
        return min(c, key=lambda x: x["espnRank"]) if c else None

    if rd >= 12 and counts.get("D/ST", 0) < 1:
        p = best("D/ST")
        if p:
            return p
    if rd >= 14 and counts.get("K", 0) < 1:
        p = best("K")
        if p:
            return p
    legal = [
        p
        for p in sorted(avail, key=lambda x: x["espnRank"])
        if p["pos"] not in ("K", "D/ST")
        and counts.get(p["pos"], 0) < AUTO_CAPS[p["pos"]]
    ]
    if not legal:
        return sorted(avail, key=lambda x: x["espnRank"])[0]
    # The real rooms scatter among the top few candidates (Bijan, CMC and Chase
    # all went before Gibbs, ESPN's #1); a deterministic best-rank drafter
    # matched only 50% of replayed picks. Top-3 choice reproduces the scatter.
    if rng is None:
        return legal[0]
    return rng.choice(legal[: min(3, len(legal))])


def human_pick(avail, roster, rd, rng):
    """Median-human model for the real Labor Day room.

    Crowd ADP is not a guess at human behavior, it IS human behavior: the
    average slot real drafters take each player. So a human is modeled as
    lowest-ADP-available under noise. The jitter is multiplicative (a person is
    off by a round late, not by a fixed number of picks), and K/D/ST wait until
    the last quarter of the draft even when ADP says otherwise, because a human
    who queues a defense in round 7 of a 16-round draft is rare in a casual
    room and the playbook's herding data says the run comes late.
    """
    counts = {}
    for p in roster:
        counts[p["pos"]] = counts.get(p["pos"], 0) + 1
    legal = []
    for p in avail:
        if counts.get(p["pos"], 0) >= AUTO_CAPS[p["pos"]]:
            continue
        if p["pos"] in ("K", "D/ST") and rd < 12:
            continue
        legal.append(p)
    if not legal:
        return min(avail, key=lambda x: x["adp"])
    return min(legal, key=lambda x: x["adp"] * rng.uniform(0.82, 1.22))


def my_next_pick(order, i):
    """Next pick of mine after i with at least one other team's pick between,
    mirroring the autopilot's horizon rule: back-to-back own picks share one
    horizon because nobody drafts between them."""
    me = order[i]
    seen_other = False
    for j in range(i + 1, len(order)):
        if order[j] != me:
            seen_other = True
        elif seen_other:
            return j
    return None


def bot_pick(avail, roster, order, i, policy):
    cfg = dict(CFG)
    cfg.update({k: v for k, v in policy.items() if k in CFG})
    counts = {}
    byes = {}
    for p in roster:
        counts[p["pos"]] = counts.get(p["pos"], 0) + 1
        byes[p["bye"]] = byes.get(p["bye"], 0) + 1
    total = len(roster)
    rd = i // TEAMS + 1
    left = ROUNDS - rd
    nxt = my_next_pick(order, i)
    next_pick = (nxt + 1) if nxt is not None else 10**9

    # floors: best VOR at each position among players surviving past next pick
    floors = {}
    for p in avail:
        if p["adp"] > next_pick:
            if p["vor"] > floors.get(p["pos"], float("-inf")):
                floors[p["pos"]] = p["vor"]

    need = {
        "RB": max(0, cfg["startRB"] - counts.get("RB", 0)),
        "TE": max(0, cfg["startTE"] - counts.get("TE", 0)),
        "D/ST": max(0, 1 - counts.get("D/ST", 0)),
        "K": max(0, 1 - counts.get("K", 0)),
    }
    must = sum(need.values())

    best, best_s = None, None
    for p in avail:
        pos = p["pos"]
        if pos == "D/ST":
            if counts.get("D/ST", 0) >= 1 or left > cfg["dstRoundsLeft"]:
                continue
            s = -1000 - p["vor"]
        elif pos == "K":
            if counts.get("K", 0) >= 1 or left > cfg["kRoundsLeft"]:
                continue
            s = -900 - p["vor"]
        else:
            if left + 1 <= must and not need.get(pos):
                continue
            cap = {"QB": "maxQB", "RB": "maxRB", "WR": "maxWR", "TE": "maxTE"}[pos]
            if counts.get(pos, 0) >= cfg[cap]:
                continue
            if pos == "QB" and rd < policy.get("qbNotBefore", 0):
                continue
            # Unclamped: below replacement, the best survivor is still the true
            # cost of waiting. Clamping at zero hid how thin a drained position
            # had become (README "still open"; swept 2026-08-24, worst 6 -> 4).
            floor = floors.get(pos, 0.0)
            s = -(p["vor"] - floor) - p["vor"] * 0.001
            # Bench balance: once the starters exist, each additional player at
            # an already-deep position is worth less than the same value at a
            # thin one, because the bench's job is covering an absence.
            bb = policy.get("benchBalance", cfg["benchBalance"])
            if bb and total >= cfg["starters"] - 2 and pos in ("RB", "WR"):
                starts = {"RB": 2, "WR": 2}[pos]
                s += bb * max(0, counts.get(pos, 0) - starts)
            if total < cfg["starters"] and p["bye"]:
                if p["bye"] == cfg["freeBye"]:
                    s -= cfg["freeByeBonus"]
                else:
                    s += cfg["byeStackPenalty"] * byes.get(p["bye"], 0)
        if best_s is None or s < best_s:
            best, best_s = p, s
    return best or auto_pick(avail, roster)


def lineup_points(roster, depth_weight=0.0):
    """Optimal starters, plus optionally a depth term.

    The starter total is what the league's points-for tiebreak rewards. The
    depth term prices the bench the way it actually gets used: the best
    remaining RB/WR/TE is the player who steps into the lineup when a starter
    sits, so his projection, discounted, is the insurance value the pure
    starter metric cannot see. ESPN's report card graded two same-policy
    rosters A and D apart almost entirely on this: the D roster's RB room was
    Kyren Williams and then Tony Pollard.
    """
    pool = sorted(roster, key=lambda p: -p["proj"])
    used, total = set(), 0.0
    for pos, n in {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "D/ST": 1, "K": 1}.items():
        got = 0
        for ix, p in enumerate(pool):
            if ix in used or p["pos"] != pos:
                continue
            used.add(ix)
            total += p["proj"]
            got += 1
            if got == n:
                break
    for ix, p in enumerate(pool):
        if ix not in used and p["pos"] in FLEX:
            used.add(ix)
            total += p["proj"]
            break
    if depth_weight:
        # best bench RB and best bench WR/TE: the two actual injury outs
        for want in (("RB",), ("WR", "TE")):
            for ix, p in enumerate(pool):
                if ix not in used and p["pos"] in want:
                    total += depth_weight * p["proj"]
                    used.add(ix)
                    break
    return total


def run(seat, policy, seed=0, model="auto"):
    players = load_players()
    rng = random.Random(seed)
    avail = list(players)
    rosters = {s: [] for s in range(1, TEAMS + 1)}
    order = snake_order()
    for i, s in enumerate(order):
        rd = i // TEAMS + 1
        if s == seat:
            p = bot_pick(avail, rosters[s], order, i, policy)
        elif model == "human":
            p = human_pick(avail, rosters[s], rd, rng)
        else:
            p = auto_pick(avail, rosters[s], rd, rng)
        rosters[s].append(p)
        avail.remove(p)
    dw = policy.get("depthWeight", 0.0)
    scores = {s: lineup_points(r, dw) for s, r in rosters.items()}
    rank = sorted(scores, key=lambda s: -scores[s]).index(seat) + 1
    return rank, scores[seat], rosters[seat]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="{}", help="JSON policy overrides")
    ap.add_argument("--seat", type=int, help="single seat; default all 13")
    ap.add_argument("--roster", action="store_true", help="print the bot roster")
    ap.add_argument("--seeds", type=int, default=0, help="N noisy rooms per seat")
    ap.add_argument(
        "--model",
        default="auto",
        choices=["auto", "human"],
        help="opponents: ESPN AUTO bots (practice rooms) or ADP-noise humans",
    )
    args = ap.parse_args()
    policy = json.loads(args.policy)

    seats = [args.seat] if args.seat else list(range(1, TEAMS + 1))
    ranks = []
    for seat in seats:
        if args.seeds:
            rs = [
                run(seat, policy, seed=sd, model=args.model)[0]
                for sd in range(args.seeds)
            ]
            ranks.extend(rs)
            n1 = sum(1 for r in rs if r == 1)
            print(
                f"seat {seat:>2}: #1 in {n1:>2}/{args.seeds}"
                f"  avg {sum(rs) / len(rs):.2f}  worst {max(rs)}"
            )
        else:
            rank, pts, roster = run(seat, policy, model=args.model)
            ranks.append(rank)
            line = f"seat {seat:>2}: rank {rank:>2}  {pts:7.1f}"
            if args.roster:
                names = ", ".join(f"{p['name']}({p['pos']})" for p in roster[:9])
                line += "  " + names
            print(line)
    n1 = sum(1 for r in ranks if r == 1)
    print(
        f"\n#1 in {n1}/{len(ranks)} rooms"
        f"   avg rank: {sum(ranks) / len(ranks):.2f}"
        f"   worst: {max(ranks)}"
    )


if __name__ == "__main__":
    main()
