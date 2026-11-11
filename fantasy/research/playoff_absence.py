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

  tree    Our live roster against those rates (the model is
          `espncli/depth.py`). Each rostered skill player is missing in week
          16 or 17 at his position's rate, independently. The best lineup is
          refilled from the bench and then from the best healthy free agent.
          Prints the expected lineup, each starter's failure mode in title
          points (`.cache/leverage.json` `playoff_per_point`), and the value
          of one more point at each place in the chain.

A missing stat line counts an injury, a benching and a rest day alike: in
each case the fantasy slot needs another player. Absences are independent
in the model, which is wrong for two players on one NFL team; the error is
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
# The model is `espncli.depth` (best_lineup, expected, tree): `roster-watch`
# prices swaps with the same code, so it does not live in a research script.

def cmd_tree(args: argparse.Namespace) -> None:
    from espncli import depth  # noqa: PLC0415

    rates = depth.load_rates(OUT)
    per_point = {int(k): float(v) for k, v in json.loads(LEVERAGE.read_text())["playoff_per_point"].items()}
    roster, wire = depth.live_inputs()
    out = depth.tree(roster, wire, rates, per_point)
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
