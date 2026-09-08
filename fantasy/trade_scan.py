#!/usr/bin/env python3
"""Which trades would raise Chaos Legion's title odds, and which a rival could
plausibly accept? Enumerates every 1-for-1 and 2-for-1 with each team, scores
both sides' optimal starting lineups on ESPN season projections (the common
currency both managers see), keeps the ones the other side does not lose on
by that currency, ranks by our lineup gain, and runs the best through the
season simulator (paired seeds) for the change in playoff and title odds.

    python3 trade_scan.py [--top 12] [--sims 6000] [--min-gain 25]
"""
import argparse
import copy
import itertools
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import season_sim as ss  # noqa: E402
from espncli.client import Espn  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
SKIP_POS = {"K", "D/ST"}
SKIP_STATUS = {"OUT", "INJURY_RESERVE", "SUSPENSION", "DOUBTFUL"}


def norm(s):
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|iii|ii|iv)\b", "", s.lower()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--sims", type=int, default=6000)
    ap.add_argument("--min-gain", type=float, default=25.0, help="our lineup gain, season points")
    ap.add_argument("--their-floor", type=float, default=-12.0, help="worst lineup change we assume a rival accepts")
    ap.add_argument("--our-view", choices=["espn", "board"], default="espn",
                    help="value OUR side by ESPN projections, or by our draft board's value over replacement (vor.json)")
    args = ap.parse_args()

    teams, games, reg = ss.load(2026)
    api = Espn()
    me = int(api.creds["team_id"])
    status = {}
    for t in api.league("mRoster")["teams"]:
        for e in (t.get("roster") or {}).get("entries", []):
            p = e["playerPoolEntry"]["player"]
            status[(t["id"], p["fullName"])] = p.get("injuryStatus") or ""
    flags = {norm(v["name"]): v.get("flag") for v in json.load(open(HERE / "draftbot" / "opportunity.json")).values()}

    ours = teams[me]["players"]
    teams[me]["espn_players"] = {pl["name"]: pl["proj"] for pl in ours}
    if args.our_view == "board":
        # Two currencies: the rival sees ESPN's projections; we score our own
        # lineup by the board that drafted it (The Ringer's order on ESPN's
        # scale, minus replacement). A trade that is fair on their screen and
        # a gain on our board is the only kind of edge a projection scan finds.
        vor = {norm(v["name"]): v["vor"] for v in json.load(open(HERE / "draftbot" / "vor.json"))["players"].values()}
        for t in teams.values():
            for pl in t["players"]:
                pl["ours"] = vor.get(norm(pl["name"]), -60.0)
        ours = [dict(pl, proj=pl["ours"]) for pl in teams[me]["players"]]
        teams[me]["players"] = ours
        for t in teams.values():
            for pl in t["players"]:
                pl.setdefault("ours", -60.0)
    base_us = ss.optimal_lineup(ours)
    mine = [p for p in ours if p["pos"] not in SKIP_POS]
    cands = []
    for tid, t in teams.items():
        if tid == me:
            continue
        theirs = [p for p in t["players"] if p["pos"] not in SKIP_POS and status.get((tid, p["name"]), "") not in SKIP_STATUS]
        base_them = t["espn"]
        for b in theirs:
            for a in mine:
                if status.get((me, a["name"]), "") in SKIP_STATUS:
                    continue
                b_us = dict(b, proj=b["ours"]) if args.our_view == "board" else b
                a_them = dict(a, proj=teams[me]["espn_players"][a["name"]]) if args.our_view == "board" else a
                new_us = ss.optimal_lineup([p for p in ours if p is not a] + [b_us])
                new_them = ss.optimal_lineup([p for p in t["players"] if p is not b] + [a_them])
                cands.append({"team": t["name"], "tid": tid, "give": [a["name"]], "get": [b["name"]],
                              "d_us": new_us - base_us, "d_them": new_them - base_them,
                              "raw": b["proj"] - teams[me]["espn_players"][a["name"]], "b": b, "a": [a]})
            for a1, a2 in itertools.combinations(mine, 2):
                if any(status.get((me, x["name"]), "") in SKIP_STATUS for x in (a1, a2)):
                    continue
                b_us = dict(b, proj=b["ours"]) if args.our_view == "board" else b
                a_them = ([dict(x, proj=teams[me]["espn_players"][x["name"]]) for x in (a1, a2)]
                          if args.our_view == "board" else [a1, a2])
                new_us = ss.optimal_lineup([p for p in ours if p not in (a1, a2)] + [b_us])
                new_them = ss.optimal_lineup([p for p in t["players"] if p is not b] + a_them)
                cands.append({"team": t["name"], "tid": tid, "give": [a1["name"], a2["name"]], "get": [b["name"]],
                              "d_us": new_us - base_us, "d_them": new_them - base_them,
                              "raw": b["proj"] - teams[me]["espn_players"][a1["name"]] - teams[me]["espn_players"][a2["name"]], "b": b, "a": [a1, a2]})
    if args.our_view == "board":
        espn_ours = [dict(pl, proj=teams[me]["espn_players"][pl["name"]]) for pl in ours]
        base_espn = ss.optimal_lineup(espn_ours)
        for c in cands:
            keep = [p for p in espn_ours if p["name"] not in c["give"]]
            c["d_us_espn"] = ss.optimal_lineup(keep + [dict(c["b"])]) - base_espn
    plausible = [c for c in cands if c["d_us"] >= args.min_gain and c["d_them"] >= args.their_floor
                 and (c["raw"] <= 20 if len(c["give"]) == 1 else True)]
    plausible.sort(key=lambda c: -c["d_us"])
    print(f"candidates {len(cands):,}; plausible {len(plausible)} (our gain >= {args.min_gain}, their lineup change >= {args.their_floor}, raw balance)\n")

    # Paired simulation: same seed for baseline and every candidate.
    _, _, _, _, _, base = ss.simulate(teams, games, reg, args.sims, 22.0, 8.0, 7)
    i_me = sorted(teams).index(me)
    print("| # | With | We give | We get | Our lineup Δ (season) | Their lineup Δ | Raw proj Δ (them) | Δ title | Δ playoffs | Δ bye | Flags |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for n, c in enumerate(plausible[: args.top], 1):
        mod = copy.deepcopy(teams)
        mod[me]["espn"] = teams[me]["espn"] + (c["d_us"] if args.our_view == "espn" else c.get("d_us_espn", 0.0))
        mod[c["tid"]]["espn"] = teams[c["tid"]]["espn"] + c["d_them"]
        _, _, _, _, _, pr = ss.simulate(mod, games, reg, args.sims, 22.0, 8.0, 7)
        fl = [f"{x['name'].split()[-1]}:{flags.get(norm(x['name']))}" for x in c["a"] + [c["b"]] if flags.get(norm(x["name"]))]
        print(f"| {n} | {c['team']} | {' + '.join(c['give'])} | {', '.join(c['get'])} | {c['d_us']:+.0f} | {c['d_them']:+.0f} | {-c['raw']:+.0f} "
              f"| {100 * (pr['champ'][i_me] - base['champ'][i_me]):+.1f} pts | {100 * (pr['playoffs'][i_me] - base['playoffs'][i_me]):+.1f} pts "
              f"| {100 * (pr['bye'][i_me] - base['bye'][i_me]):+.1f} pts | {' '.join(fl) or '-'} |")
    print(f"\nbaseline: title {100 * base['champ'][i_me]:.1f}%, playoffs {100 * base['playoffs'][i_me]:.0f}%, bye {100 * base['bye'][i_me]:.0f}%")


if __name__ == "__main__":
    main()
