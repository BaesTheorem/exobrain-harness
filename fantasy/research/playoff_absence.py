#!/usr/bin/env python3
"""playoff_absence: how often a starter of today is missing in weeks 15-17,
and what that does to our lineup.

The playbook's *The strategic thesis* rule 4 said "about 8% of starters are
out in a given playoff week". That is the rate for a starter who is healthy
the week before the game. A roster decision in week 10 needs the rate from
week 10, and it is about twice as large (2026-11-11).

  rates   For each season 2021-2025 (18-week seasons, so week 17 is not the
          NFL's last week): the top 13 QB, 26 RB, 39 WR and 13 TE by league
          points a game through week 9, with 5 or more games and a game in
          week 8 or 9. The share with no stat line in each of weeks 15, 16
          and 17, with a bootstrap over player-seasons, plus the same share
          in weeks 11-14 (the control: it must be lower) and a split by the
          NFL team's record through week 9. Writes out/playoff_absence.json.

  tree    Our live roster against those rates. Each rostered skill player
          is missing in week 16 or 17 at his position's rate, independently.
          The best lineup is refilled from the bench and then from the best
          healthy free agent. Prints the expected lineup, each starter's
          failure mode in title points (`.cache/leverage.json`
          `playoff_per_point`), how often each bench place plays, and the
          value of one more point at each place in the chain.

A missing stat line counts an injury, a benching and a rest day alike: in
each case the fantasy slot needs another player. Absences are drawn
independently, which is wrong for two players on one NFL team; the error is
small against the rates' own intervals.

    python3 research/playoff_absence.py rates
    python3 research/playoff_absence.py tree [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FANTASY = HERE.parent
sys.path.insert(0, str(FANTASY))

OUT = HERE / "out" / "playoff_absence.json"
LEVERAGE = FANTASY / ".cache" / "leverage.json"
SEASONS = [2021, 2022, 2023, 2024, 2025]
TOP = {"QB": 13, "RB": 26, "WR": 39, "TE": 13}     # a 13-team league: 1 QB, 2 RB, 2 WR + the flex, 1 TE
DECISION_WEEK = 10
PLAYOFF_WEEKS = (15, 16, 17)
FINAL_WEEKS = (16, 17)                              # the two weeks we play with a bye
BOOT = 2000
SIMS = 120_000


# ---- rates ------------------------------------------------------------------

def starter_rows(seasons: list[int]) -> list[dict]:
    """One row per starter, season and later week: did he have a stat line?"""
    import polars as pl  # noqa: PLC0415

    from ffmodel import nflraw  # noqa: PLC0415

    pw = (nflraw.player_weeks(seasons).filter(pl.col("pos").is_in(list(TOP)))
          .select(["season", "week", "player_id", "pos", "team", "pts"])
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    games = nflraw.games(seasons).with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
    rows = []
    for s in seasons:
        p, gs = pw.filter(pl.col("season") == s), games.filter(pl.col("season") == s)
        record: dict[str, list[int]] = {}
        team_weeks: dict[str, set[int]] = {}
        for g in gs.iter_rows(named=True):
            team_weeks.setdefault(g["home"], set()).add(g["week"])
            team_weeks.setdefault(g["away"], set()).add(g["week"])
            if g["week"] >= DECISION_WEEK or g["home_score"] is None:
                continue
            home_won, tie = g["home_score"] > g["away_score"], g["home_score"] == g["away_score"]
            for team, won in ((g["home"], home_won), (g["away"], not home_won and not tie)):
                r = record.setdefault(team, [0, 0])
                r[0] += int(won)
                r[1] += 1
        played = {(r[0], r[1]) for r in p.select(["player_id", "week"]).iter_rows()}
        early = (p.filter(pl.col("week") < DECISION_WEEK).sort("week").group_by(["player_id", "pos"])
                 .agg(pl.col("pts").mean().alias("ppg"), pl.len().alias("gp"),
                      pl.col("week").max().alias("last"), pl.col("team").last().alias("team"))
                 .filter((pl.col("gp") >= 5) & (pl.col("last") >= DECISION_WEEK - 2)))
        for pos, n in TOP.items():
            top = early.filter(pl.col("pos") == pos).sort(["ppg", "player_id"], descending=[True, False]).head(n)
            for r in top.iter_rows(named=True):
                won, gms = record.get(r["team"], [0, 0])
                for wk in range(DECISION_WEEK + 1, 18):
                    if wk not in team_weeks.get(r["team"], set()):
                        continue                    # his team's bye
                    rows.append({"season": s, "pos": pos, "pid": r["player_id"], "week": wk,
                                 "missed": (r["player_id"], wk) not in played,
                                 "winpct": won / gms if gms else 0.5})
    return rows


def boot_rate(rows: list[dict], rng: np.random.Generator) -> dict:
    """Share missed, with a 95% interval from a bootstrap over player-seasons."""
    if not rows:
        return {"miss": None, "lo": None, "hi": None, "n": 0}
    keys = np.array([f"{r['season']}|{r['pid']}" for r in rows])
    miss = np.array([float(r["missed"]) for r in rows])
    uniq, inv = np.unique(keys, return_inverse=True)
    sums, cnt = np.bincount(inv, weights=miss, minlength=len(uniq)), np.bincount(inv, minlength=len(uniq))
    est = []
    for _ in range(BOOT):
        i = rng.integers(0, len(uniq), len(uniq))
        est.append(sums[i].sum() / cnt[i].sum())
    return {"miss": round(float(miss.mean()), 4), "lo": round(float(np.percentile(est, 2.5)), 4),
            "hi": round(float(np.percentile(est, 97.5)), 4), "n": len(uniq)}


def cmd_rates(args: argparse.Namespace) -> None:
    rows = starter_rows(SEASONS)
    rng = np.random.default_rng(7)
    out: dict = {"seasons": SEASONS, "top": TOP, "decision_week": DECISION_WEEK, "by_pos": {}, "all": {}, "by_record": {}}
    for pos in TOP:
        out["by_pos"][pos] = {str(w): boot_rate([r for r in rows if r["pos"] == pos and r["week"] == w], rng)
                              for w in PLAYOFF_WEEKS}
    for w in PLAYOFF_WEEKS:
        out["all"][str(w)] = boot_rate([r for r in rows if r["week"] == w], rng)
    out["all"]["11-14"] = boot_rate([r for r in rows if 11 <= r["week"] <= 14], rng)
    bands = {"losing": lambda x: x < 0.4, "middle": lambda x: 0.4 <= x < 0.6, "winning": lambda x: x >= 0.6}
    for w in PLAYOFF_WEEKS:
        out["by_record"][str(w)] = {k: boot_rate([r for r in rows if r["week"] == w and f(r["winpct"])], rng)
                                    for k, f in bands.items()}
        a = np.array([float(r["missed"]) for r in rows if r["week"] == w and r["winpct"] < 0.4])
        b = np.array([float(r["missed"]) for r in rows if r["week"] == w and r["winpct"] >= 0.6])
        d = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(BOOT)]
        out["by_record"][str(w)]["losing_minus_winning"] = {
            "diff": round(float(a.mean() - b.mean()), 4), "lo": round(float(np.percentile(d, 2.5)), 4),
            "hi": round(float(np.percentile(d, 97.5)), 4)}
    control = out["all"]["11-14"]["miss"] < min(out["all"][str(w)]["miss"] for w in FINAL_WEEKS)
    out["control_near_weeks_lower"] = bool(control)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"No stat line, top starters of week {DECISION_WEEK}, {SEASONS[0]}-{SEASONS[-1]}")
    for pos in TOP:
        print(f"  {pos:<3}" + "".join(f"  wk{w} {out['by_pos'][pos][str(w)]['miss']:.3f}" for w in PLAYOFF_WEEKS))
    for k, v in out["all"].items():
        print(f"  all  wk{k:<6} {v['miss']:.3f} [{v['lo']:.3f}, {v['hi']:.3f}] n={v['n']}")
    for w in PLAYOFF_WEEKS:
        d = out["by_record"][str(w)]["losing_minus_winning"]
        print(f"  wk{w} losing teams minus winning teams {d['diff']:+.3f} [{d['lo']:+.3f}, {d['hi']:+.3f}]")
    print("control (weeks 11-14 lower than weeks 16-17):", "ok" if control else "FAILED")
    print(f"wrote {OUT}")


# ---- tree -------------------------------------------------------------------

def best_lineup(avail: list[tuple[str, str, float]], wire: dict[str, float]) -> float:
    """Points of the best QB, 2 RB, 2 WR, TE and FLEX from the players available,
    with the wire's best player at each position as an unlimited fallback."""
    qb = max([r for _, p, r in avail if p == "QB"] + [wire["QB"]])
    te_all = sorted([r for _, p, r in avail if p == "TE"], reverse=True) + [wire["TE"]] * 2
    rbs = sorted([r for _, p, r in avail if p == "RB"], reverse=True) + [wire["RB"]] * 3
    wrs = sorted([r for _, p, r in avail if p == "WR"], reverse=True) + [wire["WR"]] * 3
    return qb + te_all[0] + rbs[0] + rbs[1] + wrs[0] + wrs[1] + max(rbs[2], wrs[2], te_all[1])


def expected(roster: list[tuple[str, str, float]], wire: dict[str, float], miss: dict[str, float],
             rng: np.random.Generator, sims: int = SIMS) -> tuple[float, np.ndarray]:
    """(mean lineup points, the absence draws) with each player out at his position's rate."""
    p = np.array([miss[pos] for _, pos, _ in roster])
    out = rng.random((sims, len(roster))) < p
    cache: dict[bytes, float] = {}
    total = 0.0
    for row in out:
        key = row.tobytes()
        if key not in cache:
            cache[key] = best_lineup([x for x, gone in zip(roster, row, strict=True) if not gone], wire)
        total += cache[key]
    return total / sims, out


def tree(roster: list[tuple[str, str, float]], wire: dict[str, float], rates: dict[int, dict[str, float]],
         title_per_point: dict[int, float], seed: int = 11, sims: int = SIMS) -> dict:
    """Pure: the roster and the rates in, the fault tree out. Title numbers are in points of title odds."""
    full = best_lineup(roster, wire)

    def run(rs: list[tuple[str, str, float]]) -> dict[int, float]:
        rng = np.random.default_rng(seed)          # the same draws for every variant with the same roster size
        return {w: expected(rs, wire, rates[w], rng, sims)[0] for w in FINAL_WEEKS}

    def title(ev: dict[int, float], base: dict[int, float]) -> float:
        return sum((ev[w] - base[w]) * title_per_point[w] * 100 for w in FINAL_WEEKS)

    base = run(roster)
    starters, chain = lineup_names(roster, wire)
    modes = []
    for name, pos, rate in roster:
        if name not in starters:
            continue
        loss = full - best_lineup([x for x in roster if x[0] != name], wire)
        modes.append({"player": name, "pos": pos, "rate": rate, "lost_if_out": round(loss, 1),
                      "p_out": {w: rates[w][pos] for w in FINAL_WEEKS},
                      "title": round(sum(rates[w][pos] * loss * title_per_point[w] * 100 for w in FINAL_WEEKS), 2)})
    modes.sort(key=lambda m: -m["title"])
    plus_one = []
    for name in [*starters, *chain]:
        bumped = [(n, p, r + 1.0) if n == name else (n, p, r) for n, p, r in roster]
        plus_one.append({"player": name, "place": "starter" if name in starters else f"bench {chain.index(name) + 1}",
                         "title_per_point": round(title(run(bumped), base), 2)})
    return {"full_health": round(full, 1), "expected": {w: round(v, 1) for w, v in base.items()},
            "injury_tax_title": round(title(base, dict.fromkeys(FINAL_WEEKS, full)), 1),
            "failure_modes": modes, "one_more_point": plus_one, "wire": wire}


def lineup_names(roster: list[tuple[str, str, float]], wire: dict[str, float]) -> tuple[list[str], list[str]]:
    """(the seven starters, the RB/WR bench in order of use) at full health."""
    by = {p: sorted([x for x in roster if x[1] == p], key=lambda x: -x[2]) for p in TOP}
    starters = [x[0] for x in by["QB"][:1] + by["RB"][:2] + by["WR"][:2] + by["TE"][:1]]
    rest = sorted(by["RB"][2:] + by["WR"][2:], key=lambda x: -x[2])
    if rest:
        starters.append(rest[0][0])
    chain = [x[0] for x in rest[1:] if x[2] > min(wire["RB"], wire["WR"])]
    return starters, chain


def live_inputs() -> tuple[list[tuple[str, str, float]], dict[str, float]]:
    """Our roster and the best healthy free agent at each position, on `ros_rate`."""
    from espncli.cli import pool_rows, roster_rows  # noqa: PLC0415
    from espncli.client import IR, Espn, norm  # noqa: PLC0415
    from espncli.value import games_appeared, games_played, load_volume_rows, ros_rate  # noqa: PLC0415

    api = Espn()
    data = api.league("mTeam", "mRoster", "mSettings", "mStatus")
    week = api.current_week(data)
    games = {pt["abbrev"]: games_played(pt["games"], week) for pt in api.pro_teams().values()}
    appeared = games_appeared(load_volume_rows(api.season), week)

    def rate(r: dict) -> float:
        return ros_rate(week, r.get("proj"), r.get("season_proj"), r.get("season_actual"),
                        games.get(r.get("team") or ""), appeared.get(f"{norm(r['name'])}|{r['pos']}"))

    mine = roster_rows(api, api.roster_entries(data, api.resolve_team(data, None)["id"]), week)
    roster = [(r["name"], r["pos"], round(rate(r), 2)) for r in mine if r["pos"] in TOP and r["slotId"] != IR]
    wire = {}
    for pos in TOP:
        rows = [r for r in pool_rows(api, week, pos, 60, ["FREEAGENT"]) if not r.get("status")]
        wire[pos] = round(max((rate(r) for r in rows), default=0.0), 2)
    return roster, wire


def cmd_tree(args: argparse.Namespace) -> None:
    saved = json.loads(OUT.read_text())
    rates = {w: {pos: saved["by_pos"][pos][str(w)]["miss"] for pos in TOP} for w in FINAL_WEEKS}
    per_point = {int(k): float(v) for k, v in json.loads(LEVERAGE.read_text())["playoff_per_point"].items()}
    roster, wire = live_inputs()
    out = tree(roster, wire, rates, per_point)
    if args.json:
        json.dump(out, sys.stdout, indent=1)
        return
    print(f"Skill lineup at full health {out['full_health']} a game; expected with absences "
          + ", ".join(f"week {w} {v}" for w, v in out["expected"].items())
          + f" ({out['injury_tax_title']} title points)")
    print("\nFailure modes (title points over weeks 16 and 17)")
    for m in out["failure_modes"]:
        odds = "/".join(f"{m['p_out'][w]:.0%}" for w in FINAL_WEEKS)
        print(f"  {m['player']:<22}{m['pos']:<3} out {odds}  costs {m['lost_if_out']:>5} a game  -> {m['title']:.2f}")
    print("\nOne more point of rate at each place")
    for r in out["one_more_point"]:
        print(f"  {r['player']:<22}{r['place']:<9} +{r['title_per_point']:.2f} title points")
    print(f"\nwire fallbacks: {out['wire']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rates", help="measure the absence rates on 2021-2025").set_defaults(fn=cmd_rates)
    t = sub.add_parser("tree", help="price our live roster against the rates")
    t.add_argument("--json", action="store_true")
    t.set_defaults(fn=cmd_tree)
    args = ap.parse_args()
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
