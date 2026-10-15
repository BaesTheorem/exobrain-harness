#!/usr/bin/env python3
"""sleeper_validation: outside tests of the in-season models on real leagues.

The models under `espn check` and `season_sim.py` were fitted and checked on
nflverse box scores. This scores them on hundreds of real season-long leagues
that had nothing to do with fitting them, crawled from Sleeper's public API by
fantasy/research/sleeper_crawl.py into /tmp/ffvoi.

1. `winprob`: every regular-season matchup's pre-game P(win) from
   espncli.value.win_prob, with each starter's mean = Sleeper's archived
   projection scored on THAT league's own scoring settings, the spread from
   CV_TABLE, and the correlations from ffmodel/corr_table.json, against who
   won. Reliability by decile, Brier score and log score, for independent
   starters and for correlated ones.
2. `byes`: at week 5 of every league with a 6-team, 2-bye bracket, P(top two
   seed) from the team-level model season_sim.py uses (normal weekly scores
   with the within-team spread measured in that league, seeding by win
   percentage then points for), each team's strength drawn from its
   empirical-Bayes posterior given five weeks of scores, against who got the
   byes. Reliability and Brier, against the naive "the current top two keep
   them".

    sleeper_validation.py winprob|byes|all [--raw /tmp/ffvoi]

INVARIANTS
- Reads the raw crawl in place and writes aggregates only
  (research/out/sleeper_validation.json): no league ids, user ids or names.
- Only leagues scored like ours (4-point passing TD, full PPR) enter the
  win-probability test, because CV_TABLE was measured on that scoring.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
FANTASY = HERE.parent
sys.path.insert(0, str(FANTASY))
OUT = HERE / "out" / "sleeper_validation.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
POS = {"DEF": "D/ST"}


def leagues(raw: Path):
    for f in sorted(os.listdir(raw / "leagues")):
        try:
            yield json.load(gzip.open(raw / "leagues" / f))
        except (OSError, ValueError):
            continue


def projections(raw: Path, season: int, week: int) -> dict[str, dict]:
    """player_id -> {pos, team, opp, stats}: Sleeper's archived weekly
    projections, cached next to the raw crawl (outside the repo)."""
    d = raw / "proj"
    d.mkdir(exist_ok=True)
    f = d / f"{season}_{week:02d}.json.gz"
    if not f.exists():
        pos = "&".join(f"position[]={p}" for p in ("QB", "RB", "WR", "TE", "K", "DEF"))
        url = f"https://api.sleeper.app/projections/nfl/{season}/{week}?season_type=regular&{pos}"
        rows = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
        with gzip.open(f, "wt") as fh:
            json.dump(rows, fh)
    rows = json.load(gzip.open(f))
    out = {}
    for r in rows:
        p = (r.get("player") or {}).get("position") or ""
        out[str(r.get("player_id"))] = {"pos": POS.get(p, p), "team": r.get("team"), "opp": r.get("opponent"),
                                       "stats": r.get("stats") or {}}
    return out


def score(stats: dict, scoring: dict) -> float:
    return float(sum(float(v) * float(scoring[k]) for k, v in stats.items() if k in scoring and isinstance(v, (int, float))))


def like_ours(lg: dict) -> bool:
    sc = lg["league"]["scoring_settings"]
    return float(sc.get("rec", 0)) == 1.0 and float(sc.get("pass_td", 4)) == 4.0


def reliability(pairs: list[tuple[float, int]], bins: int = 10) -> list[dict]:
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(p, y) for p, y in pairs if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if sel:
            out.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(sel), "pred": round(sum(p for p, _ in sel) / len(sel), 3),
                        "obs": round(sum(y for _, y in sel) / len(sel), 3)})
    return out


def scores(pairs: list[tuple[float, int]]) -> dict:
    n = len(pairs)
    brier = sum((p - y) ** 2 for p, y in pairs) / n
    logs = sum(-math.log(max(1e-6, p if y else 1 - p)) for p, y in pairs) / n
    return {"n": n, "brier": round(brier, 4), "log_score": round(logs, 4)}


def winprob(raw: Path) -> dict:
    from espncli import value  # noqa: PLC0415

    corr = value.load_corr()
    proj_cache: dict[tuple[int, int], dict] = {}
    ind, cor = [], []
    n_leagues = 0
    for lg in leagues(raw):
        if not like_ours(lg):
            continue
        season = int(lg["league"]["season"])
        sc = lg["league"]["scoring_settings"]
        reg = int(lg["league"]["settings"].get("playoff_week_start") or 15) - 1
        n_leagues += 1
        for wk, rows in (lg.get("matchups") or {}).items():
            w = int(wk)
            if w > reg:
                continue
            key = (season, w)
            if key not in proj_cache:
                proj_cache[key] = projections(raw, season, w)
            proj = proj_cache[key]
            by_m: dict[int, list[dict]] = {}
            for r in rows:
                if r.get("matchup_id") is not None:
                    by_m.setdefault(r["matchup_id"], []).append(r)
            for pair in by_m.values():
                if len(pair) != 2 or pair[0].get("points") == pair[1].get("points"):
                    continue
                sides = []
                for r in pair:
                    lineup = []
                    for i, pid in enumerate(r.get("starters") or []):
                        pr = proj.get(str(pid))
                        if not pr or pid == "0":
                            continue
                        lineup.append({"id": f"{r['roster_id']}-{i}", "name": str(pid), "pos": pr["pos"],
                                       "proj": max(0.0, score(pr["stats"], sc)), "team": pr["team"],
                                       "opp": pr["opp"], "slotId": 0, "actual": None})
                    sides.append(lineup)
                won = int((pair[0].get("points") or 0) > (pair[1].get("points") or 0))
                ind.append((value.win_prob(sides[0], sides[1])["p"], won))
                cor.append((value.win_prob(sides[0], sides[1], corr=corr)["p"], won))
    return {"leagues": n_leagues, "independent": {**scores(ind), "reliability": reliability(ind)},
            "correlated": {**scores(cor), "reliability": reliability(cor)}}


def byes(raw: Path, at_week: int = 5, sims: int = 4000, seed: int = 7, drift: float = 0.0) -> dict:
    import numpy as np  # noqa: PLC0415

    rng = np.random.default_rng(seed)
    pairs, naive = [], []
    n_leagues = 0
    for lg in leagues(raw):
        st = lg["league"]["settings"]
        if int(st.get("playoff_teams") or 0) != 6:
            continue
        reg = int(st.get("playoff_week_start") or 15) - 1
        mt = lg.get("matchups") or {}
        weeks = [w for w in range(1, reg + 1) if str(w) in mt]
        if len(weeks) != reg or reg <= at_week:
            continue
        rids = sorted({r["roster_id"] for r in mt["1"]})
        idx = {r: i for i, r in enumerate(rids)}
        n = len(rids)
        pts = np.zeros((reg, n))
        games = []
        for w in weeks:
            by_m: dict[int, list[int]] = {}
            for r in mt[str(w)]:
                pts[w - 1, idx[r["roster_id"]]] = r.get("points") or 0.0
                if r.get("matchup_id") is not None:
                    by_m.setdefault(r["matchup_id"], []).append(idx[r["roster_id"]])
            games += [(w, a, b) for a, b in (v for v in by_m.values() if len(v) == 2)]

        def seeds(score_mat, n=n, games=games):
            wins = np.zeros((score_mat.shape[0], n))
            losses = np.zeros_like(wins)
            for w, a, b in games:
                sa, sb = score_mat[:, w - 1, a], score_mat[:, w - 1, b]
                wins[:, a] += sa > sb
                wins[:, b] += sb > sa
                losses[:, a] += sa < sb
                losses[:, b] += sb < sa
            pf = score_mat.sum(axis=1)
            pct = wins / np.maximum(wins + losses, 1)
            order = np.lexsort((-pf, -pct), axis=1)
            return order

        actual_order = seeds(pts[None, :, :])[0]
        top2 = set(actual_order[:2].tolist())
        played = pts[:at_week]
        means = played.mean(axis=0)
        resid = played - means
        sigma = float(np.sqrt((resid ** 2).sum() / max(1, played.size - n)))
        between = max(0.0, float(means.var(ddof=1)) - sigma ** 2 / at_week)
        post_var = 1.0 / (1.0 / max(between, 1e-6) + at_week / sigma ** 2)
        post_mean = post_var * (means.mean() / max(between, 1e-6) + at_week * means / sigma ** 2)
        strength = post_mean[None, :] + rng.normal(0, math.sqrt(post_var), (sims, n))
        # Strength that wanders week to week (injuries, trades, role changes):
        # a random walk from the week after the last one played.
        walk = np.zeros((sims, reg, n))
        if drift > 0:
            steps = rng.normal(0, drift, (sims, reg, n))
            steps[:, :at_week, :] = 0.0
            walk = np.cumsum(steps, axis=1)
        sim = strength[:, None, :] + walk + rng.normal(0, sigma, (sims, reg, n))
        sim[:, :at_week, :] = played[None, :, :]
        order = seeds(sim)
        p_top2 = np.zeros(n)
        for k in range(2):
            np.add.at(p_top2, order[:, k], 1)
        p_top2 /= sims
        now_order = seeds(np.concatenate([played, np.zeros((reg - at_week, n))])[None, :, :])[0]
        now_top2 = set(now_order[:2].tolist())
        for i in range(n):
            pairs.append((float(p_top2[i]), int(i in top2)))
            naive.append((1.0 if i in now_top2 else 0.0, int(i in top2)))
        n_leagues += 1
    return {"leagues": n_leagues, "at_week": at_week, "model": {**scores(pairs), "reliability": reliability(pairs)},
            "naive_current_top2": scores(naive)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("what", choices=("winprob", "byes", "all"))
    ap.add_argument("--raw", default="/tmp/ffvoi")
    a = ap.parse_args()
    raw = Path(a.raw)
    out = json.loads(OUT.read_text()) if OUT.exists() else {}
    if a.what in ("winprob", "all"):
        out["winprob"] = winprob(raw)
    if a.what in ("byes", "all"):
        out["byes"] = byes(raw)
        sweep = {}
        for d in (2.0, 4.0, 6.0, 8.0):
            r = byes(raw, drift=d)
            sweep[str(d)] = {"brier": r["model"]["brier"], "log_score": r["model"]["log_score"],
                             "reliability": r["model"]["reliability"]}
        out["byes"]["drift_sweep"] = sweep
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
