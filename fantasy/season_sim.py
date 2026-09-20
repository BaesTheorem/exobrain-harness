#!/usr/bin/env python3
"""Season outlook for Roll for First Down: two draft scoreboards and a Monte
Carlo of the season from the real rosters and the real schedule.

Scoreboard 1 ("our system") is the draft board's value over replacement summed
over each team's picks, read from draftbot/draft_2026_record.json (ESPN's own
pick record) against draftbot/vor.json. Scoreboard 2 ("ESPN's system") is each
team's optimal starting lineup on ESPN's 2026 season projections, scored in
this league's settings, pulled live from the rosters. ESPN's letter grades are
not exposed by the API, so this is the closest thing to ESPN's own view.

The simulation draws every regular-season week from the schedule ESPN
generated (idle weeks included), seeds the playoffs by record then points for,
gives the top two a bye, and plays single-week rounds with no reseeding, which
is this league's format. Two noise terms, both stated rather than fitted:

  SIGMA_WEEK  points of week-to-week scatter in a team's score
  TAU_SEASON  points per week of roster-strength error (injuries, busts,
              breakouts) drawn once per simulated season

Run in season with actual standings folded in later; for now it is preseason.

    python3 season_sim.py [--sims 20000] [--sigma 22] [--tau 8] [--seed 1]
"""

import argparse
import collections
import json
import pathlib
import re
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from espncli.client import Espn, season_actual, season_proj, team_name, week_actual, week_proj  # noqa: E402
from espncli.value import games_played, ros_rate  # noqa: E402

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
LINEUP = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "D/ST": 1, "K": 1}
FLEX = ("RB", "WR", "TE")
NFL_WEEKS = 17
PLAYOFF_TEAMS, BYES = 6, 2


def norm(s):
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|iii|ii|iv)\b", "", s.lower()))


def optimal_lineup(players):
    """Best legal starting nine by season projection: fixed slots, then flex."""
    by_pos = collections.defaultdict(list)
    for p in players:
        by_pos[p["pos"]].append(p)
    for lst in by_pos.values():
        lst.sort(key=lambda p: -p["proj"])
    used, total = set(), 0.0
    for pos, n in LINEUP.items():
        for p in by_pos[pos][:n]:
            used.add(id(p))
            total += p["proj"]
    flex = max((p for pos in FLEX for p in by_pos[pos] if id(p) not in used),
               key=lambda p: p["proj"], default=None)
    return total + (flex["proj"] if flex else 0.0)


def load(season):
    """Every roster valued on the one in-season currency (espncli.value.ros_rate,
    scaled back to a 17-game season so the simulator's per-week division holds).
    Before 2026-09-20 this read ESPN's static preseason projection, which never
    moves on a role change or an injury; a trade scan or a bye-odds number on
    that input was pricing August."""
    cl = Espn()
    data = cl.league("mTeam", "mRoster", "mMatchup", "mSettings", "mStatus")
    week = Espn.current_week(data)
    teams = {}
    for t in data["teams"]:
        players = []
        for e in (t.get("roster") or {}).get("entries", []):
            p = e["playerPoolEntry"]["player"]
            games = games_played(cl.pro(p.get("proTeamId")).get("games", {}), week)
            rate = ros_rate(week, week_proj(p, season, week), season_proj(p, season), season_actual(p, season), games)
            players.append({"name": p["fullName"], "pos": POS.get(p.get("defaultPositionId"), "?"),
                            "proj": rate * NFL_WEEKS, "preseason": season_proj(p, season) or 0.0})
        teams[t["id"]] = {"name": team_name(t).strip(), "players": players,
                          "espn": optimal_lineup(players)}
    reg = data["settings"]["scheduleSettings"]["matchupPeriodCount"]
    games = [(m["matchupPeriodId"], m["home"]["teamId"], m["away"]["teamId"])
             for m in data["schedule"]
             if m["matchupPeriodId"] <= reg and "home" in m and "away" in m]
    return teams, games, reg


def board_scores(teams):
    """Scoreboard 1: the draft board's view of each team, from ESPN's pick record.

    Two numbers. 'starters' is the best legal starting nine by value over
    replacement, the same structure as the ESPN scoreboard; 'all16' sums every
    pick, which lets the bench rounds (negative by construction once the pool
    is below replacement) swamp the starters, so it is shown, not ranked on.
    """
    vor = json.load(open(HERE / "draftbot" / "vor.json"))["players"]
    board = {norm(p["name"]): p for p in vor.values()}
    rec = json.load(open(HERE / "draftbot" / "draft_2026_record.json"))
    picks = collections.defaultdict(list)
    for r in rec:
        b = board.get(norm(r["player"]))
        picks[r["team"]].append({"name": r["player"], "pos": r["pos"],
                                 "proj": b["vor"] if b else -60.0})
    return {team: {"starters": optimal_lineup(ps), "all16": sum(p["proj"] for p in ps)}
            for team, ps in picks.items()}


def load_actuals(season, week):
    """Every team's real starter total for one completed week.

    Summed from the lineups rather than read from ESPN's own `totalPoints`,
    which sits at 0.0 until ESPN closes a week. The week that just finished is
    therefore invisible in the standings for the better part of a day, and a
    simulator that trusted that field would silently run preseason numbers
    while looking like it had folded results in.
    """
    cl = Espn(fresh=True)
    data = cl.league("mTeam", "mRoster", "mMatchup", period=week)
    out = {}
    for t in data["teams"]:
        total = 0.0
        for e in (t.get("roster") or {}).get("entries", []):
            if e.get("lineupSlotId") in (20, 21):  # bench, IR
                continue
            total += week_actual(e["playerPoolEntry"]["player"], season, week) or 0.0
        out[t["id"]] = round(total, 2)
    return out


def completed_weeks(season, games, reg, explicit=None):
    """Weeks whose results should be treated as fact, plus their scores.

    A week counts as complete only when EVERY team with a matchup in it has a
    nonzero total. Half a week of real scores mixed into a simulation is worse
    than none: it would fold in the early games and quietly zero out whoever
    plays Monday night.
    """
    if explicit == 0:
        return {}
    actuals = {}
    for w in range(1, reg + 1):
        playing = {t for wk, h, a in games if wk == w for t in (h, a)}
        if not playing:
            continue
        scores = load_actuals(season, w)
        if any(scores.get(t, 0.0) <= 0.0 for t in playing):
            break
        actuals[w] = scores
        if explicit is not None and w >= explicit:
            break
    return actuals


def simulate(teams, games, reg, sims, sigma, tau, seed, actuals=None) -> tuple:
    ids = sorted(teams)
    idx = {tid: i for i, tid in enumerate(ids)}
    n = len(ids)
    rng = np.random.default_rng(seed)
    mu = np.array([teams[t]["espn"] / NFL_WEEKS for t in ids])
    strength = mu[None, :] + rng.normal(0, tau, (sims, n))
    scores = strength[:, None, :] + rng.normal(0, sigma, (sims, reg, n))  # sims x weeks x teams
    wins = np.zeros((sims, n))
    losses = np.zeros((sims, n))
    pf = np.zeros((sims, n))
    actuals = actuals or {}
    for w, h, a in games:
        if w in actuals:
            # A played week is not a distribution. Overwrite the draws with the
            # real numbers so every simulated season starts from what happened,
            # and the remaining weeks are the only thing still uncertain.
            hs = np.full(sims, actuals[w][h])
            as_ = np.full(sims, actuals[w][a])
        else:
            hs, as_ = scores[:, w - 1, idx[h]], scores[:, w - 1, idx[a]]
        wins[:, idx[h]] += hs > as_
        wins[:, idx[a]] += as_ > hs
        losses[:, idx[h]] += hs < as_
        losses[:, idx[a]] += as_ < hs
        pf[:, idx[h]] += hs
        pf[:, idx[a]] += as_
    # Seeding: wins, then points for (the league's tiebreak).
    order = np.lexsort((-pf, -wins), axis=1)  # sims x n, best first
    seed_of = np.empty_like(order)
    rows = np.arange(sims)[:, None]
    seed_of[rows, order] = np.arange(n)[None, :]
    champ = np.zeros(n)
    top2 = np.zeros(n)
    playoffs = np.zeros(n)
    first = np.zeros(n)
    last = np.zeros(n)
    most_pf = np.zeros(n)
    # Playoffs: week 15 = 3v6, 4v5; week 16 = 1 v (4/5), 2 v (3/6); week 17 final.
    po = strength[:, None, :] + rng.normal(0, sigma, (sims, 3, n))
    s = order  # s[:, k] = team index of seed k+1
    def game(week, x, y):
        return np.where(po[rows[:, 0], week, x] >= po[rows[:, 0], week, y], x, y)
    w36 = game(0, s[:, 2], s[:, 5])
    w45 = game(0, s[:, 3], s[:, 4])
    f1 = game(1, s[:, 0], w45)
    f2 = game(1, s[:, 1], w36)
    winner = game(2, f1, f2)
    np.add.at(champ, winner, 1)
    np.add.at(first, s[:, 0], 1)
    np.add.at(last, s[:, -1], 1)
    np.add.at(most_pf, np.argmax(pf, axis=1), 1)
    for k in range(PLAYOFF_TEAMS):
        np.add.at(playoffs, s[:, k], 1)
        if k < BYES:
            np.add.at(top2, s[:, k], 1)
    # Final regular-season finishing place, 1..n, per simulated season. Kept
    # separate from the win count because rank is what the league table shows
    # and what the bye and the playoff cut are actually drawn on: a 7-win
    # season can finish 3rd or 9th depending on everyone else.
    ranks = seed_of + 1
    return ids, mu, wins, losses, pf, ranks, {
        "champ": champ / sims, "bye": top2 / sims, "playoffs": playoffs / sims,
        "seed1": first / sims, "last": last / sims, "most_pf": most_pf / sims}


def ci(x, lo, hi):
    a, b = np.percentile(x, [lo, hi])
    return a, b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--sigma", type=float, default=22.0, help="weekly team-score SD")
    ap.add_argument("--tau", type=float, default=8.0, help="per-week roster-strength SD, drawn per season")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--through-week", type=int, default=None, metavar="N",
                    help="treat weeks 1..N as played (default: auto-detect; 0 = preseason)")
    ap.add_argument("--json", action="store_true", help="also print a JSON summary (our odds first)")
    args = ap.parse_args()
    say = (lambda *a, **k: None) if args.json else print   # --json: the summary is the only stdout

    teams, games, reg = load(args.season)
    actuals = completed_weeks(args.season, games, reg, args.through_week)
    board = board_scores(teams)

    say("## Scoreboard 1: our system (value over replacement by our board, from ESPN's pick record)\n")
    say("| # | Team | Starters VOR | All 16 picks |")
    say("|---|---|---|---|")
    for i, (nm, v) in enumerate(sorted(board.items(), key=lambda kv: -kv[1]["starters"]), 1):
        say(f"| {i} | {nm} | {v['starters']:.0f} | {v['all16']:.0f} |")

    say("\n## Scoreboard 2: ESPN's system (optimal lineup on ESPN 2026 projections, league scoring)\n")
    say("| # | Team | Proj starters (season) | Per week |")
    say("|---|---|---|---|")
    for i, (_tid, t) in enumerate(sorted(teams.items(), key=lambda kv: -kv[1]["espn"]), 1):
        say(f"| {i} | {t['name']} | {t['espn']:.0f} | {t['espn'] / NFL_WEEKS:.1f} |")

    ids, mu, wins, losses, pf, ranks, probs = simulate(
        teams, games, reg, args.sims, args.sigma, args.tau, args.seed, actuals)
    played = f"weeks 1-{max(actuals)} played" if actuals else "preseason, nothing played"
    say(f"\n## Season simulation ({args.sims:,} seasons; {played}; "
          f"sigma_week={args.sigma}, tau_season={args.tau}; "
          f"{reg} weeks, {PLAYOFF_TEAMS} playoff teams, {BYES} byes, no reseeding)\n")
    say("| Team | Wins (50% CI) | Wins (90% CI) | Finish (50% CI) | Finish (90% CI) "
          "| Playoffs | Bye | Title |")
    say("|---|---|---|---|---|---|---|---|")
    rows = []
    for i, tid in enumerate(ids):
        w, r = wins[:, i], ranks[:, i]
        rows.append((teams[tid]["name"], w.mean(), ci(w, 25, 75), ci(w, 5, 95),
                     np.median(r), ci(r, 25, 75), ci(r, 5, 95),
                     probs["playoffs"][i], probs["bye"][i], probs["champ"][i]))
    for nm, wm, (a, b), (c, d), rmed, (ra, rb), (rc, rd), pp, pb, pc in sorted(rows, key=lambda x: -x[9]):
        say(f"| {nm} | {wm:.1f} ({a:.0f}-{b:.0f}) | {c:.0f}-{d:.0f} "
              f"| {rmed:.0f} ({ra:.0f}-{rb:.0f}) | {rc:.0f}-{rd:.0f} "
              f"| {pp:.0%} | {pb:.0%} | {pc:.0%} |")
    summary = {"names": [teams[t]["name"] for t in ids], "mu": mu.tolist(),
               "weeks_played": max(actuals) if actuals else 0,
               "probs": {k: v.tolist() for k, v in probs.items()}}
    json.dump(summary, open(HERE / "draftbot" / "season_sim_latest.json", "w"), indent=1)
    if args.json:
        me = int(Espn().creds.get("team_id", 0))
        i = ids.index(me) if me in ids else None
        mine = {k: round(float(v[i]), 4) for k, v in probs.items()} if i is not None else {}
        if i is not None:
            mine["wins_mean"] = round(float(wins[:, i].mean()), 2)
            mine["finish_median"] = float(np.median(ranks[:, i]))
        print(json.dumps({"weeks_played": summary["weeks_played"], "sims": args.sims, "mine": mine,
                          "teams": {teams[t]["name"]: {k: round(float(v[j]), 4) for k, v in probs.items()}
                                    for j, t in enumerate(ids)}}, indent=1))


if __name__ == "__main__":
    main()
