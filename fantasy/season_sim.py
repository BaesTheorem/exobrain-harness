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
    python3 season_sim.py --after-week 5    # the table after week 5, not the season
    python3 season_sim.py --live            # fold the week in progress in at ESPN's live projection
    python3 season_sim.py --live --force 6:Chefs   # the Chefs win their week 6 game

`--force` answers "what is someone else's game worth to us": run it once per
result and read the difference in our bye odds. A forced game keeps the two
simulated scores and only decides which side gets the higher one, so points
for stays on the same distribution.
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
from espncli.client import norm as cnorm  # noqa: E402
from espncli.value import games_appeared, games_played, load_volume_rows, ros_rate  # noqa: E402

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
    appeared = games_appeared(load_volume_rows(season), week)
    teams = {}
    for t in data["teams"]:
        players = []
        for e in (t.get("roster") or {}).get("entries", []):
            p = e["playerPoolEntry"]["player"]
            games = games_played(cl.pro(p.get("proTeamId")).get("games", {}), week)
            # `games` counts weeks before this one, so the points must too. ESPN's
            # season total is live, and mid-week it carries this week's partial
            # points over a count that excludes this week (2026-10-11: bye odds
            # 41% on a Sunday afternoon against 37% on the clean total).
            before = (season_actual(p, season) or 0.0) - (week_actual(p, season, week) or 0.0)
            pos = POS.get(p.get("defaultPositionId"), "?")
            rate = ros_rate(week, week_proj(p, season, week), season_proj(p, season), before, games,
                            appeared.get(f"{cnorm(p['fullName'])}|{pos}"))
            players.append({"name": p["fullName"], "pos": pos,
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

    The nonzero test alone is not enough: by Sunday afternoon every team has
    some points (Thursday's game, a D/ST, an early kicker), so the week in
    progress passed it and was simulated as already decided (2026-10-11, the
    week 5 bye odds came back conditioned on a win). So without an explicit
    N, a week also has to sit before the scoring period ESPN is on now.
    """
    if explicit == 0:
        return {}
    current = None if explicit is not None else Espn.current_week(Espn(fresh=True).league("mStatus"))
    actuals = {}
    for w in range(1, reg + 1):
        if current is not None and w >= current:
            break
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


def live_week(season):
    """The week in progress, every matchup at ESPN's live projected finish.

    Returns (week, {team_id: points}), or None when any side has no live
    projection yet (before the first kickoff of the week). The live figure
    is ESPN's: banked points plus the projection for players still to play.
    """
    cl = Espn(fresh=True)
    data = cl.league("mMatchup", "mMatchupScore", "mStatus")
    week = Espn.current_week(data)
    out = {}
    for m in data.get("schedule", []):
        if m.get("matchupPeriodId") != week or not (m.get("home") and m.get("away")):
            continue
        for side in (m["home"], m["away"]):
            live = side.get("totalProjectedPointsLive")
            if live is None:
                return None
            out[side["teamId"]] = float(live)
    return (week, out) if out else None


def parse_force(specs, teams, games):
    """`W:TEAM` strings to {(week, frozenset(pair)): winner_id}; TEAM is an id or a name fragment."""
    out = {}
    for spec in specs or []:
        wk, _, who = spec.partition(":")
        if not wk.isdigit() or not who:
            sys.exit(f"--force wants WEEK:TEAM, got {spec!r}")
        hits = [t for t in teams if who == str(t) or who.lower() in teams[t]["name"].lower()]
        if len(hits) != 1:
            sys.exit(f"--force {spec!r}: {len(hits)} teams match {who!r}")
        game = [(h, a) for w, h, a in games if w == int(wk) and hits[0] in (h, a)]
        if not game:
            sys.exit(f"--force {spec!r}: {teams[hits[0]]['name']} has no game in week {wk}")
        out[(int(wk), frozenset(game[0]))] = hits[0]
    return out


SIGMA_PRIOR = 22.0    # stated guess, used until enough weeks are played to measure it
SIGMA_MIN_WEEKS = 4


def measured_sigma(games, actuals):
    """Pooled within-team SD of the real weekly scores, or None before SIGMA_MIN_WEEKS.

    This is the simulator's SIGMA_WEEK read off the league instead of stated.
    First measurement (2026-10-14, weeks 1-5, 13 teams, 52 df): 29.3 against
    the 22 the model had assumed, so the prior understated how much a single
    week decides and overstated every bye number built on it.
    """
    if len(actuals) < SIGMA_MIN_WEEKS:
        return None
    resid, groups = [], 0
    for t in {t for _w, h, a in games for t in (h, a)}:
        xs = [actuals[w][t] for w in sorted(actuals) if any(wk == w and t in (h, a) for wk, h, a in games)]
        if len(xs) >= 2:
            resid.extend(np.asarray(xs) - np.mean(xs))
            groups += 1
    dof = len(resid) - groups
    return float(np.sqrt(np.sum(np.square(resid)) / dof)) if dof > 0 else None


def _season(teams, games, reg, sims, sigma, tau, seed, actuals=None, force=None, me=None, bump=None):
    """One batch of simulated seasons, returned raw for simulate() and leverage().

    `bump` shifts team `me` only and never touches the random draws, so two
    calls with the same seed differ by the intervention alone (common random
    numbers): {"week": {w: pts}} moves our score in an unplayed week before the
    game is decided, {"pf": pts} moves Points For without deciding anything,
    {"playoff": {round: pts}} moves our score in playoff round 0, 1 or 2.
    """
    ids = sorted(teams)
    idx = {tid: i for i, tid in enumerate(ids)}
    n = len(ids)
    rng = np.random.default_rng(seed)
    mu = np.array([teams[t]["espn"] / NFL_WEEKS for t in ids])
    strength = mu[None, :] + rng.normal(0, tau, (sims, n))
    scores = strength[:, None, :] + rng.normal(0, sigma, (sims, reg, n))  # sims x weeks x teams
    bump = bump or {}
    if me is not None:
        for w, d in bump.get("week", {}).items():
            if 1 <= w <= reg:
                scores[:, w - 1, idx[me]] += d
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
            winner = (force or {}).get((w, frozenset((h, a))))
            if winner is not None:
                hi, lo = np.maximum(hs, as_), np.minimum(hs, as_)
                hs, as_ = (hi, lo) if winner == h else (lo, hi)
        wins[:, idx[h]] += hs > as_
        wins[:, idx[a]] += as_ > hs
        losses[:, idx[h]] += hs < as_
        losses[:, idx[a]] += as_ < hs
        pf[:, idx[h]] += hs
        pf[:, idx[a]] += as_
    if me is not None and bump.get("pf"):
        pf[:, idx[me]] += bump["pf"]
    # Seeding: win percentage, then points for (the league's tiebreak), which
    # is ESPN's playoffSeed order. Not raw wins: idle weeks leave teams on
    # unequal games mid-season (a 3-0 idle team sits above a 3-1 team with
    # more points), and --after-week ranked those backwards until 2026-09-30.
    # At season end every team has played 13, so the two orders agree.
    pct = wins / np.maximum(wins + losses, 1)
    order = np.lexsort((-pf, -pct), axis=1)  # sims x n, best first
    seed_of = np.empty_like(order)
    rows = np.arange(sims)[:, None]
    seed_of[rows, order] = np.arange(n)[None, :]
    po = strength[:, None, :] + rng.normal(0, sigma, (sims, 3, n))
    if me is not None:
        for r, d in bump.get("playoff", {}).items():
            po[:, r, idx[me]] += d
    return {"ids": ids, "idx": idx, "mu": mu, "wins": wins, "losses": losses, "pf": pf,
            "pct": pct, "order": order, "seed_of": seed_of, "po": po}


def _bracket(po, s):
    """Champion per simulated season. Week 15 = 3v6, 4v5; week 16 = 1 v (4/5), 2 v (3/6); week 17 final."""
    rows = np.arange(len(s))

    def game(week, x, y):
        return np.where(po[rows, week, x] >= po[rows, week, y], x, y)
    w36 = game(0, s[:, 2], s[:, 5])
    w45 = game(0, s[:, 3], s[:, 4])
    return game(2, game(1, s[:, 0], w45), game(1, s[:, 1], w36))


def simulate(teams, games, reg, sims, sigma, tau, seed, actuals=None, force=None) -> tuple:
    raw = _season(teams, games, reg, sims, sigma, tau, seed, actuals, force)
    ids, mu, wins, losses, pf = raw["ids"], raw["mu"], raw["wins"], raw["losses"], raw["pf"]
    s, n = raw["order"], len(raw["ids"])
    champ = np.zeros(n)
    top2 = np.zeros(n)
    playoffs = np.zeros(n)
    first = np.zeros(n)
    last = np.zeros(n)
    most_pf = np.zeros(n)
    np.add.at(champ, _bracket(raw["po"], s), 1)
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
    ranks = raw["seed_of"] + 1
    return ids, mu, wins, losses, pf, ranks, {
        "champ": champ / sims, "bye": top2 / sims, "playoffs": playoffs / sims,
        "seed1": first / sims, "last": last / sims, "most_pf": most_pf / sims}


def leverage(teams, games, reg, actuals, me, sims, sigma, tau, seed, step=10.0):
    """What each remaining lever is worth to `me`, in bye and title odds.

    Every number is a difference between two batches on the same random
    draws, so it is the intervention alone. Built 2026-10-14 when Alex asked
    what else "play for the bye" implies; the playbook's *The strategic
    thesis* cites these numbers, so rerun this rather than quoting them.

    - placed[k]: P(title) with us moved to seed k and our strength unchanged.
      P(title | seed) read off a plain run is confounded (a team that earned
      the 1 seed is usually a stronger draw), which made the bye look like
      2.1x when the bracket itself is worth about 1.5x.
    - weeks[w]: a forced win against a forced loss in our game in week w, in
      bye and title points; title per point added to our week-w score; and
      the exchange rate: projected points worth 1 point of win probability.
    - pf_point: a point of Points For alone (the seeding tiebreak).
    - playoff_per_point: a point added to our score in week 15, 16, 17.
    - weight: title per point of each remaining week over the mean
      regular-season week. This is the per-week weight for valuing a player.
    """
    def batch(**kw):
        raw = _season(teams, games, reg, sims, sigma, tau, seed, actuals, me=me, **kw)
        return raw, _bracket(raw["po"], raw["order"])

    def odds(raw, champ):
        i = raw["idx"][me]
        sd = raw["seed_of"][:, i]
        return {"bye": float(np.mean(sd < BYES)), "title": float(np.mean(champ == i)),
                "playoffs": float(np.mean(sd < PLAYOFF_TEAMS)), "seed1": float(np.mean(sd == 0))}

    raw, champ = batch()
    base = odds(raw, champ)
    i, s, n = raw["idx"][me], raw["order"], len(raw["ids"])
    others = s[s != i].reshape(len(s), n - 1)
    placed = {}
    for k in range(PLAYOFF_TEAMS):
        sk = np.concatenate([others[:, :k], np.full((len(s), 1), i), others[:, k:]], axis=1)
        placed[k + 1] = float(np.mean(_bracket(raw["po"], sk) == i))
    sd = raw["seed_of"][:, i]
    pct = raw["pct"]
    rows = np.arange(len(s))
    base["tie_at_bye_line"] = float(np.mean((pct[rows, s[:, 1]] == pct[rows, s[:, 2]]) & ((sd == 1) | (sd == 2))))
    pfr = odds(*batch(bump={"pf": step}))
    pf_point = {"bye": (pfr["bye"] - base["bye"]) / step, "title": (pfr["title"] - base["title"]) / step}
    weeks = {}
    for w in sorted({w for w, h, a in games if me in (h, a) and w not in actuals}):
        h, a = next((h, a) for wk, h, a in games if wk == w and me in (h, a))
        opp = a if h == me else h
        pair = frozenset((h, a))
        won = odds(*batch(force={(w, pair): me}))
        lost = odds(*batch(force={(w, pair): opp}))
        moved = odds(*batch(bump={"week": {w: step}}))
        win_bye, win_title = won["bye"] - lost["bye"], won["title"] - lost["title"]
        weeks[w] = {"opp": teams[opp]["name"], "win_bye": win_bye, "win_title": win_title,
                    "title_per_point": (moved["title"] - base["title"]) / step,
                    "points_per_win_pct": (0.01 * win_title / pf_point["title"]) if pf_point["title"] > 0 else None}
    playoff = {}
    for r in range(3):
        playoff[reg + 1 + r] = (odds(*batch(bump={"playoff": {r: step}}))["title"] - base["title"]) / step
    regular = [v["title_per_point"] for v in weeks.values()]
    unit = float(np.mean(regular)) if regular else None
    weight = {w: (v["title_per_point"] / unit if unit else None) for w, v in weeks.items()}
    weight.update({w: (v / unit if unit else None) for w, v in playoff.items()})
    return {"sigma": sigma, "tau": tau, "sims": sims, "base": base, "placed": placed,
            "bye_worth_title": float(np.mean([placed[1], placed[2]]) - np.mean([placed[k] for k in range(3, 7)])),
            "pf_point": pf_point, "weeks": weeks, "playoff_per_point": playoff, "weight": weight}


def ci(x, lo, hi):
    a, b = np.percentile(x, [lo, hi])
    return a, b


def after_week(teams, games, reg, args, actuals, force=None):
    """The league table after week `reg`: finish distribution and top-two odds per team."""
    ids, _mu, wins, _losses, _pf, ranks, probs = simulate(
        teams, games, reg, args.sims, args.sigma, args.tau, args.seed, actuals, force)
    played = max(actuals) if actuals else 0
    me = int(Espn().creds.get("team_id", 0))
    rows = sorted(((teams[t]["name"], float(probs["seed1"][i]), float(probs["bye"][i]),
                    float(wins[:, i].mean()), ranks[:, i], t == me) for i, t in enumerate(ids)),
                  key=lambda r: -r[2])
    if args.json:
        print(json.dumps({"after_week": reg, "weeks_played": played, "sims": args.sims,
                          "teams": {nm: {"first": round(f, 4), "top2": round(b, 4), "wins_mean": round(w, 2),
                                         "rank_dist": {int(k): round(float((r == k).mean()), 4)
                                                       for k in np.unique(r)}, "mine": m}
                                    for nm, f, b, w, r, m in rows}}, indent=1))
        return
    print(f"## Standings after week {reg} ({args.sims:,} sims; weeks 1-{played} played; "
          f"sigma_week={args.sigma}, tau_season={args.tau})\n")
    print("| Team | Wins (mean) | First | Top two | Finish median (90% CI) |")
    print("|---|---|---|---|---|")
    for nm, f, b, w, r, m in rows:
        lo, hi = ci(r, 5, 95)
        print(f"| {'**' + nm + '**' if m else nm} | {w:.2f} | {f:.0%} | {b:.0%} | {np.median(r):.0f} ({lo:.0f}-{hi:.0f}) |")


def print_leverage(lev, as_json):
    if as_json:
        print(json.dumps(lev, indent=1, default=float))
        return
    b = lev["base"]
    print(f"## Leverage ({lev['sims']:,} seasons per batch; sigma_week={lev['sigma']}, tau_season={lev['tau']})\n")
    print(f"Now: bye {b['bye']:.0%}, seed 1 {b['seed1']:.0%}, playoffs {b['playoffs']:.0%}, title {b['title']:.0%}. "
          f"Our bye is decided on the Points For tiebreak in {b['tie_at_bye_line']:.0%} of seasons.\n")
    print("Title odds with us placed at each seed (same team, only the bracket changes): "
          + ", ".join(f"{k}: {v:.1%}" for k, v in lev["placed"].items())
          + f". The bye is worth {lev['bye_worth_title'] * 100:.1f} points of title odds.\n")
    print(f"A point of Points For alone: {lev['pf_point']['bye'] * 100:.3f} bye points, "
          f"{lev['pf_point']['title'] * 100:.4f} title points.\n")
    print("| Week | Opponent | A win is worth (bye) | (title) | Title per point | Points per 1% win | Weight |")
    print("|---|---|---|---|---|---|---|")
    for w, v in lev["weeks"].items():
        ppw = f"{v['points_per_win_pct']:.1f}" if v["points_per_win_pct"] else "-"
        print(f"| {w} | {v['opp']} | {v['win_bye'] * 100:.1f} | {v['win_title'] * 100:.1f} | "
              f"{v['title_per_point'] * 100:.3f}% | {ppw} | {lev['weight'][w]:.1f} |")
    for w, v in lev["playoff_per_point"].items():
        print(f"| {w} | playoffs | - | - | {v * 100:.3f}% | - | {lev['weight'][w]:.1f} |")
    print("\nWeight = title value of a point that week over the mean regular-season week: "
          "the per-week multiplier for valuing a player's rest of season.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--sigma", type=float, default=None,
                    help=f"weekly team-score SD (default: measured from the played weeks once there "
                         f"are {SIGMA_MIN_WEEKS}, else {SIGMA_PRIOR:g})")
    ap.add_argument("--tau", type=float, default=8.0, help="per-week roster-strength SD, drawn per season")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--through-week", type=int, default=None, metavar="N",
                    help="treat weeks 1..N as played (default: auto-detect; 0 = preseason)")
    ap.add_argument("--after-week", type=int, default=None, metavar="N",
                    help="stop the schedule after week N and report the standings then "
                         "(Bye column = P(top two after week N)); writes no summary file")
    ap.add_argument("--json", action="store_true", help="also print a JSON summary (our odds first)")
    ap.add_argument("--live", action="store_true",
                    help="treat the week in progress as played, at ESPN's live projected finish")
    ap.add_argument("--force", action="append", metavar="WEEK:TEAM",
                    help="TEAM (id or name fragment) wins its game in WEEK; repeatable")
    ap.add_argument("--leverage", action="store_true",
                    help="what each remaining lever is worth to us: seed value, a win per week, "
                         "a point per week (regular season and playoffs), Points For")
    args = ap.parse_args()
    say = (lambda *a, **k: None) if args.json else print   # --json: the summary is the only stdout

    teams, games, reg = load(args.season)
    actuals = completed_weeks(args.season, games, reg, args.through_week)
    if args.sigma is None:
        # Measured before --live folds in a projected week: a projection is not a score.
        measured = measured_sigma(games, actuals)
        args.sigma = round(measured, 1) if measured else SIGMA_PRIOR
        print(f"sigma_week {args.sigma} ({'measured on ' + str(len(actuals)) + ' played weeks' if measured else 'prior'})",
              file=sys.stderr)
    if args.live:
        live = live_week(args.season)
        if live is None:
            sys.exit("--live: ESPN has no live projection for every team yet")
        actuals[live[0]] = live[1]
    if args.leverage:
        lev = leverage(teams, games, reg, actuals, int(Espn().creds.get("team_id", 0)),
                       args.sims, args.sigma, args.tau, args.seed)
        if not (args.live or args.force):   # a scenario is not the outlook; swap-scan reads this file
            cache = HERE / ".cache" / "leverage.json"
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps({"weeks_played": max(actuals) if actuals else 0, **lev}, default=float))
        print_leverage(lev, args.json)
        return
    force = parse_force(args.force, teams, games)
    for (wk, pair), winner in sorted(force.items(), key=lambda kv: kv[0][0]):
        loser = next(iter(pair - {winner}))
        print(f"forced: week {wk}, {teams[winner]['name']} beat {teams[loser]['name']}", file=sys.stderr)
    if args.after_week:
        # Standings after week N are the same simulation on a shorter schedule:
        # the seeding step ranks by wins then points for, which is the table.
        reg = args.after_week
        games = [g for g in games if g[0] <= reg]
        actuals = {w: v for w, v in actuals.items() if w <= reg}
        after_week(teams, games, reg, args, actuals, force)
        return
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
        teams, games, reg, args.sims, args.sigma, args.tau, args.seed, actuals, force)
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
    if not (force or args.live):   # a scenario is not the outlook; keep the file to settled weeks
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
