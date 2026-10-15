#!/usr/bin/env python3
"""rule_backtests: backtest five numeric rules the in-season tools apply.

Each subcommand measures one rule on past seasons and writes its section of
research/out/rule_backtests.json. The vault note "Fantasy Football Rule
Backtests 2026-10-15" reads the numbers from that file.

  ros     espncli/value.py ros_rate. At weeks 3, 5, 8 and 11 of 2022-2025,
          predict each player's points per game over weeks w-17 (games he
          played) from season-to-date PPG, Sleeper's week-w projection,
          expected fantasy points per game to date (ffopportunity, rescored
          on league points), a preseason prior (FantasyPros preseason ECR
          converted to PPG with the previous season's rank-to-PPG curve) and
          the in-season rest-of-season ECR on the same curve. Compares the
          current 50/50 rule with blends fitted leave-one-season-out.
  spread  bin/volume SD_SHRINK and value.py CV_TABLE. Residual = actual -
          Sleeper projection, 2022-2025. Measures whether a player's spread
          around his projection persists (split-half and season-to-season
          correlation of his residual RMS in table units), finds the
          shrinkage that minimizes next-season normal NLL and CRPS, and
          checks the 50% and 90% coverage of the table's normal intervals
          on 2024-2025.
  dst     stream-scan DST_OURS_MIN / DST_FA_MAX. D/ST points as a function of
          the opponent's implied total, the defense's quality and home field,
          2016-2025, and the realized gain of the swap the rule makes.
  k       stream-scan K_GAP_MIN. Kicker points against the kicker's own
          implied total, roof, wind and temperature, 2016-2025, and the
          realized gain of the swap the rule makes.
  flags   bin/volume RANK_GAP / TOP_N. Replicates the BUY and SELL flags at
          weeks 4-10 of 2019-2025 from season-to-date box scores and compares
          the flagged players' PPG over the next four weeks with unflagged
          players at the same position and points rank.

Every test states its expected result before it runs (EXPECT) and runs
positive and negative controls where one exists (a planted effect must be
recovered, shuffled labels must give about zero).

    rule_backtests.py ros [--ecr db_fpecr.parquet] | spread | dst | k | flags

`ros` downloads the FantasyPros ECR archive (about 40 MB) into a temporary
directory unless --ecr names a local copy. Each subcommand runs in seconds.

INVARIANTS
- Read-only on everything but research/out/rule_backtests.json. League
  scoring comes only from ffmodel.nflraw; the rule constants come from the
  tools themselves (imported from espncli.value, or parsed from the bin/
  scripts' source), so a changed constant changes the test, not a copy.
- Out-of-sample means out of season where anything is fitted (the ros
  blends, the variance-matched table, the K model rule): fitted on other
  seasons than the one it is scored on. The D/ST and K regressions that
  describe a slope are in-sample, and say so. Uncertainty is a bootstrap
  over the independent unit (player, or NFL week for slate tests).
- Deterministic: one seeded generator, and every frame is sorted before a
  random draw, so two runs write the same JSON (polars group_by and Python
  set order are not stable across processes).
- Rank columns are cast to Int64 before any subtraction: polars rank() is
  unsigned, and a negative rank gap wraps around.
- One season of play-by-play-sized data in memory at a time; everything else
  is a few columns of box scores.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

FANTASY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FANTASY))

from ffmodel import nflraw  # noqa: E402

OUT = FANTASY / "research" / "out" / "rule_backtests.json"
SKILL = ("QB", "RB", "WR", "TE")
LAST_WEEK = 17
RNG = np.random.default_rng(20261015)
BOOT = 2000
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
ECR_URL = "https://github.com/dynastyprocess/data/raw/master/files/db_fpecr.parquet"
ECR_PAGES = {"redraft-qb": "QB", "redraft-rb": "RB", "redraft-wr": "WR", "redraft-te": "TE"}


# ---- shared ------------------------------------------------------------------

def save(section: str, payload: dict) -> None:
    """Merge one test's results into the shared JSON."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    payload["run_at"] = time.strftime("%Y-%m-%dT%H:%M")
    data[section] = payload
    OUT.write_text(json.dumps(data, indent=1, default=_jsonable))


def _jsonable(x: Any) -> Any:
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, np.ndarray):
        return x.tolist()
    return str(x)


def fnum(x: Any) -> float:
    """A polars scalar (or None) as a float; None and NaN become nan."""
    return float("nan") if x is None else float(x)


def r3(x: float | None, nd: int = 3) -> float | None:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return round(float(x), nd)


def tool_constant(script: str, name: str) -> Any:
    """A constant as the bin/ script itself defines it (literal right-hand side)."""
    src = (FANTASY / "bin" / script).read_text()
    m = re.search(rf"^{name}\s*=\s*(.+?)(?:\s+#.*)?$", src, re.M)
    if not m:
        raise SystemExit(f"{name} not found in bin/{script}")
    rhs = m.group(1).strip()
    try:
        return json.loads(rhs.replace("(", "[").replace(")", "]").replace("'", '"'))
    except ValueError:
        return float(rhs)


def cluster_boot_mean(values: np.ndarray, clusters: np.ndarray, n: int = BOOT) -> tuple[float, float, float]:
    """Mean of `values` with a 95% interval from resampling whole clusters."""
    ok = np.isfinite(values)
    values, clusters = values[ok], clusters[ok]
    if values.size == 0:
        return float("nan"), float("nan"), float("nan")
    _, idx = np.unique(clusters, return_inverse=True)
    sums = np.bincount(idx, weights=values)
    cnts = np.bincount(idx).astype(float)
    k = sums.size
    draws = RNG.integers(0, k, size=(n, k))
    w = np.zeros((n, k))
    for i in range(n):
        w[i] = np.bincount(draws[i], minlength=k)
    boot = (w @ sums) / np.maximum(w @ cnts, 1e-12)
    return float(values.mean()), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def cluster_weights(clusters: np.ndarray, n: int = BOOT) -> np.ndarray:
    """n x rows matrix of bootstrap row weights, resampling whole clusters."""
    _, idx = np.unique(clusters, return_inverse=True)
    k = int(idx.max()) + 1
    out = np.zeros((n, clusters.size))
    for i in range(n):
        cw = np.bincount(RNG.integers(0, k, size=k), minlength=k)
        out[i] = cw[idx]
    return out


def mae(pred: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean(np.abs(pred - y)))


def r2(pred: np.ndarray, y: np.ndarray) -> float:
    return float(1.0 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2))


def first_gamedays(seasons: list[int]) -> dict[tuple[int, int], date]:
    g = nflraw.games(seasons).group_by(["season", "week"]).agg(pl.col("gameday").min())
    return {(int(s), int(w)): date.fromisoformat(d) for s, w, d in g.iter_rows()}


# ---- test 2: ros_rate ------------------------------------------------------------

ROS_SEASONS = [2022, 2023, 2024, 2025]
ROS_WEEKS = [3, 5, 8, 11]
RECOMMENDED_ROS = (0.45, 0.35, 0.20)   # weekly projection, prior, season PPG (from week 5)
CURVE_MIN_GAMES = 8


def load_ecr(path: str | None) -> pl.DataFrame:
    """FantasyPros redraft ECR history (DynastyProcess archive, the file behind
    nflreadpy.load_ff_rankings('all')), positional pages only, with gsis ids.
    Read lazily with a filter: the whole file is 3M+ rows."""
    def scan(p: Path | str) -> pl.DataFrame:
        return (pl.scan_parquet(p).filter(pl.col("page_type").is_in(list(ECR_PAGES)))
                .select("fp_page", "page_type", "id", "player", "ecr", "scrape_date").collect())

    if path:
        df = scan(path)
    else:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "db_fpecr.parquet"
            req = urllib.request.Request(ECR_URL, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r, dest.open("wb") as f:
                shutil.copyfileobj(r, f)
            df = scan(dest)
    import nflreadpy as nfl  # noqa: PLC0415 -- slow import, only this loader needs it

    ids = (nfl.load_ff_playerids().select(["fantasypros_id", "gsis_id"])
           .filter(pl.col("fantasypros_id").is_not_null() & pl.col("gsis_id").is_not_null())
           .with_columns(pl.col("fantasypros_id").cast(pl.Utf8)).unique("fantasypros_id"))
    df = df.with_columns(pl.col("page_type").replace_strict(ECR_PAGES).alias("pos"),
                         pl.when(pl.col("fp_page").str.contains("ros")).then(pl.lit("ros"))
                         .otherwise(pl.lit("pre")).alias("kind"))
    return df.join(ids, left_on="id", right_on="fantasypros_id", how="left")


def ppg_curves(pw: pl.DataFrame, seasons: list[int]) -> dict[tuple[int, str], np.ndarray]:
    """(season, pos) -> PPG of the k-th best player that season (>= 8 games)."""
    out = {}
    agg = (pw.filter(pl.col("week") <= LAST_WEEK).group_by(["season", "player_id", "pos"])
           .agg(pl.col("pts").mean().alias("ppg"), pl.len().alias("g")))
    for s in seasons:
        for pos in SKILL:
            v = agg.filter((pl.col("season") == s) & (pl.col("pos") == pos) & (pl.col("g") >= CURVE_MIN_GAMES))
            out[(s, pos)] = np.sort(v["ppg"].to_numpy())[::-1]
    return out


def ecr_snapshot(ecr: pl.DataFrame, kind: str, on_or_before: date, max_age_days: int) -> tuple[pl.DataFrame, str | None]:
    """The latest scrape of `kind` dated on or before a day, ranked ordinally
    within position. Empty when the newest one is older than max_age_days."""
    sub = ecr.filter((pl.col("kind") == kind) & (pl.col("scrape_date") <= on_or_before.isoformat()))
    if sub.is_empty():
        return sub, None
    d = sub["scrape_date"].max()
    assert isinstance(d, str)
    if (on_or_before - date.fromisoformat(d)).days > max_age_days:
        return sub.clear(), d
    snap = sub.filter(pl.col("scrape_date") == d).sort(["pos", "ecr"])
    snap = snap.with_columns(pl.col("ecr").rank("ordinal").over("pos").alias("rank"))
    return snap, d


def rank_ppg(snap: pl.DataFrame, curve: dict[str, np.ndarray], name: str) -> pl.DataFrame:
    """gsis_id -> PPG for its positional rank on the curve (deepest value past the end)."""
    rows = []
    for gsis, pos, rank in snap.select(["gsis_id", "pos", "rank"]).iter_rows():
        c = curve.get(pos)
        if gsis is None or c is None or c.size == 0:
            continue
        rows.append({"player_id": gsis, f"{name}_pos": pos, name: float(c[min(int(rank), c.size) - 1])})
    df = pl.DataFrame(rows, schema={"player_id": pl.Utf8, f"{name}_pos": pl.Utf8, name: pl.Float64})
    return df.sort(name, descending=True).unique("player_id", keep="first")


def xfp_weekly(seasons: list[int]) -> tuple[pl.DataFrame, dict]:
    """ffopportunity expected points per player-game, rescored on league
    points from the expected components (there is no expected fumble)."""
    import nflreadpy as nfl  # noqa: PLC0415

    comp = {"pass_yards_gained_exp": 0.04, "pass_touchdown_exp": 4.0, "pass_interception_exp": -2.0,
            "pass_two_point_conv_exp": 2.0, "rush_yards_gained_exp": 0.1, "rush_touchdown_exp": 6.0,
            "rush_two_point_conv_exp": 2.0, "receptions_exp": 1.0, "rec_yards_gained_exp": 0.1,
            "rec_touchdown_exp": 6.0, "rec_two_point_conv_exp": 2.0}
    parts, check = [], {}
    for s in seasons:
        o = nfl.load_ff_opportunity(seasons=[s], stat_type="weekly").select(
            ["season", "week", "player_id", "total_fantasy_points_exp", *comp])
        o = o.with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64),
                           sum((pl.col(c).fill_null(0) * v for c, v in comp.items()), pl.lit(0.0)).alias("xfp"))
        diff = (o["xfp"] - o["total_fantasy_points_exp"].fill_null(0)).abs()
        check[s] = {"rows": o.height, "max_abs_diff_vs_ppr_total": r3(fnum(diff.max())),
                    "mean_xfp": r3(fnum(o["xfp"].mean()))}
        parts.append(o.select(["season", "week", "player_id", "xfp"]))
        del o
    return pl.concat(parts), check


def simplex(k: int, step: float) -> np.ndarray:
    n = round(1 / step)
    pts = []
    for c in combinations_with_replacement(range(k), n):
        w = np.bincount(np.array(c, dtype=int), minlength=k) / n
        pts.append(w)
    return np.unique(np.array(pts), axis=0)


def fit_convex(X: np.ndarray, y: np.ndarray, step: float = 0.05) -> np.ndarray:
    """Non-negative weights summing to 1 that minimize MAE (grid search)."""
    grid = simplex(X.shape[1], step)
    best, best_w = float("inf"), grid[0]
    for chunk in np.array_split(grid, max(1, grid.shape[0] // 400)):
        m = np.abs(X @ chunk.T - y[:, None]).mean(axis=0)
        i = int(np.argmin(m))
        if m[i] < best:
            best, best_w = float(m[i]), chunk[i]
    return best_w


def fit_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones(len(y)), X])
    return np.linalg.lstsq(A, y, rcond=None)[0]


def ros_frame(w: int, pw: pl.DataFrame, sl: pl.DataFrame, xfp: pl.DataFrame,
              priors: dict[int, pl.DataFrame], ros: dict[tuple[int, int], pl.DataFrame],
              leak_teams: dict[tuple[int, int], set[str]]) -> pl.DataFrame:
    before = pw.filter(pl.col("week") < w)
    after = pw.filter((pl.col("week") >= w) & (pl.col("week") <= LAST_WEEK))
    b = (before.join(xfp, on=["season", "week", "player_id"], how="left")
         .group_by(["season", "player_id"]).agg(
             pl.len().alias("n_before"), pl.col("pts").mean().alias("ppg"),
             pl.col("xfp").fill_null(0.0).mean().alias("xfp"),
             pl.col("pos").last(), pl.col("name").last(), pl.col("team").last().alias("team_before")))
    a = after.group_by(["season", "player_id"]).agg(pl.len().alias("n_after"), pl.col("pts").mean().alias("y"),
                                                  pl.col("team").first().alias("team_after"))
    f = b.join(a, on=["season", "player_id"], how="inner").filter((pl.col("n_before") >= 2) & (pl.col("n_after") >= 3))
    # Sleeper: the week-w projection, or the latest earlier one when week w is a bye or he was out.
    p = (sl.filter((pl.col("week") <= w) & (pl.col("proj") > 0)).sort("week")
         .group_by(["season", "gsis_id"]).agg(pl.col("proj").last(), pl.col("week").last().alias("proj_week")))
    f = f.join(p, left_on=["season", "player_id"], right_on=["season", "gsis_id"], how="left")
    pr = pl.concat([d.with_columns(pl.lit(s).cast(pl.Int64).alias("season")) for s, d in priors.items()])
    f = f.join(pr.select(["season", "player_id", "prior"]), on=["season", "player_id"], how="left")
    rs = [d.with_columns(pl.lit(s).cast(pl.Int64).alias("season")) for (s, ww), d in ros.items() if ww == w and d.height]
    if rs:
        f = f.join(pl.concat(rs).select(["season", "player_id", "ros"]), on=["season", "player_id"], how="left")
    else:
        f = f.with_columns(pl.lit(None, dtype=pl.Float64).alias("ros"))
    leak = [(s, t) for (s, ww), ts in leak_teams.items() if ww == w for t in ts]
    lk = pl.DataFrame({"season": [s for s, _ in leak], "team_after": [t for _, t in leak]},
                      schema={"season": pl.Int64, "team_after": pl.Utf8}).with_columns(pl.lit(True).alias("leak"))
    f = f.join(lk, on=["season", "team_after"], how="left").with_columns(pl.col("leak").fill_null(False))
    return f.with_columns(pl.lit(w).alias("week"))


def cmd_ros(args: argparse.Namespace) -> None:
    expect = ("Sleeper's week-w projection alone beats season PPG at every week; the best blend puts most "
              "weight on the projection and xFP; the 50/50 prior+PPG rule is 5-10% worse in MAE than the best blend.")
    print("EXPECT:", expect)
    seasons_all = [ROS_SEASONS[0] - 1, *ROS_SEASONS]
    pw = (nflraw.player_weeks(seasons_all).filter(pl.col("pos").is_in(SKILL) & (pl.col("week") <= LAST_WEEK))
          .select(["season", "week", "player_id", "name", "pos", "team", "pts"])
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    curves = ppg_curves(pw, seasons_all)
    sl = (nflraw.sleeper_weeks(ROS_SEASONS).filter(pl.col("pos").is_in(SKILL) & pl.col("gsis_id").is_not_null())
          .group_by(["season", "week", "gsis_id"]).agg(pl.col("proj").max())
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    xfp, xfp_check = xfp_weekly(ROS_SEASONS)
    ecr = load_ecr(args.ecr)
    days = first_gamedays(ROS_SEASONS)
    g = nflraw.games(ROS_SEASONS)
    priors, ros, leak_teams, snaps = {}, {}, {}, {}
    for s in ROS_SEASONS:
        prev_curve = {pos: curves[(s - 1, pos)] for pos in SKILL}
        opener = days[(s, 1)]
        snap, d = ecr_snapshot(ecr, "pre", opener - timedelta(days=1), 14)
        priors[s] = rank_ppg(snap, prev_curve, "prior")
        snaps[f"{s} preseason"] = d
        for w in ROS_WEEKS:
            if w < 5:
                continue
            first = days[(s, w)]
            # FantasyPros scrapes on Fridays; the Friday after week w's Thursday game
            # is the first one that has all of week w-1. Thursday teams are dropped.
            snap_w, dw = ecr_snapshot(ecr, "ros", first + timedelta(days=1), 8)
            ros[(s, w)] = rank_ppg(snap_w, prev_curve, "ros") if snap_w.height else pl.DataFrame()
            snaps[f"{s} week {w} ROS"] = dw if snap_w.height else f"stale ({dw})"
            if dw and snap_w.height:
                wk = g.filter((pl.col("season") == s) & (pl.col("week") == w) & (pl.col("gameday") < dw))
                leak_teams[(s, w)] = set(wk["home"].to_list()) | set(wk["away"].to_list())
    del ecr
    out: dict[str, Any] = {"expect": expect, "xfp_scoring_check": xfp_check, "ecr_snapshots": snaps,
                           "curve_note": "prior/ROS rank -> PPG of the k-th best player at the position in the PREVIOUS season (>= 8 games)",
                           "weeks": {}}
    # An unranked player gets the deepest value of his position's curve.
    floor = {(s, pos): float(curves[(s - 1, pos)][-1]) for s in ROS_SEASONS for pos in SKILL}

    def or_floor(col: str) -> pl.Expr:
        return pl.struct(["season", "pos", col]).map_elements(
            lambda r: r[col] if r[col] is not None else floor[(r["season"], r["pos"])], return_dtype=pl.Float64)

    frames = []
    for w in ROS_WEEKS:
        f = ros_frame(w, pw.filter(pl.col("season").is_in(ROS_SEASONS)), sl, xfp, priors, ros, leak_teams)
        f = f.sort(["season", "player_id"])      # set iteration upstream varies by process; draws must not
        n0 = f.height
        unranked = int(f["prior"].is_null().sum())
        f = f.with_columns(or_floor("prior").alias("prior"))
        has_ros = w >= 5
        if has_ros:
            f = f.filter(~pl.col("leak"))
            f = f.with_columns(or_floor("ros").alias("ros"))
        f = f.filter(pl.col("proj").is_not_null())
        y = f["y"].to_numpy()
        P = {k: f[k].to_numpy().astype(float) for k in ("ppg", "proj", "xfp", "prior", *(["ros"] if has_ros else []))}
        season = f["season"].to_numpy()
        live = P["ppg"] if w >= 5 else P["proj"]
        methods = {"current_rule": 0.5 * P["prior"] + 0.5 * live}
        if has_ros:
            methods["current_rule_ros_prior"] = 0.5 * P["ros"] + 0.5 * P["ppg"]
        for k in P:
            methods[f"only_{k}"] = P[k]
        sets = {"blend4": ["ppg", "proj", "xfp", "prior"], "live3_pre": ["proj", "prior", "ppg"]}
        if has_ros:
            sets["blend5"] = ["ppg", "proj", "xfp", "prior", "ros"]
            sets["live3_ros"] = ["proj", "ros", "ppg"]
        fitted_w = {}
        for name, cols in sets.items():
            X = np.column_stack([P[c] for c in cols])
            cv_convex, cv_ols = np.zeros_like(y), np.zeros_like(y)
            for s in ROS_SEASONS:
                tr, te = season != s, season == s
                cv_convex[te] = X[te] @ fit_convex(X[tr], y[tr])
                cv_ols[te] = np.column_stack([np.ones(te.sum()), X[te]]) @ fit_ols(X[tr], y[tr])
            methods[f"{name}_convex_cv"] = cv_convex
            methods[f"{name}_ols_cv"] = cv_ols
            wc = fit_convex(X, y)
            wo = fit_ols(X, y)
            fitted_w[name] = {"convex_all_seasons": dict(zip(cols, [r3(v, 2) for v in wc], strict=True)),
                              "ols_all_seasons": {"intercept": r3(wo[0], 2), **dict(zip(cols, [r3(v, 3) for v in wo[1:]], strict=True))}}
        # Two-input convex blends.
        pairs = {}
        for a_, b_ in (("prior", "ppg"), ("proj", "ppg"), ("ros", "ppg"), ("xfp", "ppg"), ("proj", "xfp"), ("proj", "prior")):
            if a_ not in P or b_ not in P:
                continue
            X = np.column_stack([P[a_], P[b_]])
            cv = np.zeros_like(y)
            for s in ROS_SEASONS:
                tr, te = season != s, season == s
                cv[te] = X[te] @ fit_convex(X[tr], y[tr], 0.05)
            methods[f"pair_{a_}_{b_}_cv"] = cv
            pairs[f"{a_}+{b_}"] = r3(float(fit_convex(X, y, 0.05)[0]), 2)
        # Controls: a planted predictor (truth plus noise) must take most of the
        # weight; a shuffled copy of the projection must take almost none.
        planted = y + RNG.normal(0.0, 2.0, y.size)
        shuffled = RNG.permutation(P["proj"])
        wp = fit_convex(np.column_stack([P["ppg"], P["proj"], P["prior"], planted]), y)
        ws = fit_convex(np.column_stack([P["ppg"], P["proj"], P["prior"], shuffled]), y)
        controls = {"planted_weight": r3(float(wp[3]), 2), "shuffled_proj_weight": r3(float(ws[3]), 2)}
        players = f["player_id"].to_numpy()
        rel = (np.maximum(P["ppg"], P["proj"]) >= 8.0)
        base = methods["current_rule"]
        res = {}
        for name, pred in methods.items():
            d = np.abs(pred - y) - np.abs(base - y)
            m, lo, hi = cluster_boot_mean(d, players)
            per_season = {int(s): r3(mae(pred[season == s], y[season == s]) - mae(base[season == s], y[season == s]))
                          for s in ROS_SEASONS}
            res[name] = {"mae": r3(mae(pred, y)), "r2": r3(r2(pred, y)), "bias": r3(float(np.mean(pred - y))),
                         "mae_relevant": r3(mae(pred[rel], y[rel])), "r2_relevant": r3(r2(pred[rel], y[rel])),
                         "mae_minus_current": r3(m), "ci95": [r3(lo), r3(hi)], "minus_current_by_season": per_season}
        by_pos = {}
        best_name = min((k for k in methods if k.endswith("_cv")), key=lambda k: mae(methods[k], y))
        pos_arr = f["pos"].to_numpy()
        for pos in SKILL:
            mk = pos_arr == pos
            if mk.sum() < 20:
                continue
            by_pos[pos] = {"n": int(mk.sum()), "current_rule": r3(mae(base[mk], y[mk])),
                           best_name: r3(mae(methods[best_name][mk], y[mk])),
                           "only_proj": r3(mae(P["proj"][mk], y[mk])), "only_ppg": r3(mae(P["ppg"][mk], y[mk]))}
        out["weeks"][str(w)] = {"n": int(f.height), "n_before_filters": n0, "unranked_preseason": unranked,
                                "n_relevant": int(rel.sum()), "mean_target_ppg": r3(float(y.mean())),
                                "proj_fallback_share": r3(fnum((f["proj_week"] < w).mean())),
                                "methods": res, "best_cv_method": best_name, "weights": fitted_w,
                                "pair_weight_on_first": pairs, "mae_by_pos": by_pos, "controls": controls}
        frames.append((w, f, y, P, season, players))
        print(f"week {w}: n={f.height}  current MAE {res['current_rule']['mae']}  best {best_name} "
              f"{res[best_name]['mae']} ({res[best_name]['mae_minus_current']} {res[best_name]['ci95']})  controls {controls}")
        for k_, v_ in res.items():
            print(f"   {k_:<28} MAE {v_['mae']:<6} R2 {v_['r2']:<6} bias {v_['bias']:<6} relMAE {v_['mae_relevant']:<6} "
                  f"d {v_['mae_minus_current']} {v_['ci95']} {v_['minus_current_by_season']}")
        print("   weights", json.dumps(fitted_w), "pairs", pairs)
    # One rule for every week from 5 on: the three inputs ros_rate can see
    # (weekly projection, prior, season PPG), fitted on weeks 5, 8 and 11 together.
    pooled: dict[str, Any] = {}
    late = [t for t in frames if t[0] >= 5]
    for prior_col in ("prior", "ros"):
        cols = ["proj", prior_col, "ppg"]
        X = np.vstack([np.column_stack([t[3][c] for c in cols]) for t in late])
        y = np.concatenate([t[2] for t in late])
        season = np.concatenate([t[4] for t in late])
        players = np.concatenate([t[5] for t in late])
        cur = 0.5 * X[:, 1] + 0.5 * X[:, 2]
        cv = np.zeros_like(y)
        fold_w = {}
        for s in ROS_SEASONS:
            tr, te = season != s, season == s
            wv = fit_convex(X[tr], y[tr], 0.05)
            fold_w[int(s)] = [r3(v, 2) for v in wv]
            cv[te] = X[te] @ wv
        wall = fit_convex(X, y, 0.05)
        m, lo, hi = cluster_boot_mean(np.abs(cv - y) - np.abs(cur - y), players)
        fixed = X @ np.array(RECOMMENDED_ROS)
        fm, flo, fhi = cluster_boot_mean(np.abs(fixed - y) - np.abs(cur - y), players)
        rel = np.maximum(X[:, 0], X[:, 2]) >= 8.0
        pooled[f"fixed_{'_'.join(str(v) for v in RECOMMENDED_ROS)}_with_{prior_col}"] = {
            "mae": r3(mae(fixed, y)), "r2": r3(r2(fixed, y)), "mae_minus_current": r3(fm), "ci95": [r3(flo), r3(fhi)],
            "mae_relevant": r3(mae(fixed[rel], y[rel])), "mae_relevant_current": r3(mae(cur[rel], y[rel]))}
        pooled[f"proj+{prior_col}+ppg"] = {
            "weights_all_seasons": dict(zip(cols, [r3(v, 2) for v in wall], strict=True)),
            "weights_by_held_out_season": fold_w, "n": int(y.size),
            "mae_current": r3(mae(cur, y)), "mae_cv": r3(mae(cv, y)), "r2_current": r3(r2(cur, y)), "r2_cv": r3(r2(cv, y)),
            "mae_minus_current": r3(m), "ci95": [r3(lo), r3(hi)]}
        print("pooled weeks 5-11", prior_col, json.dumps(pooled[f"proj+{prior_col}+ppg"]))
    out["pooled_weeks_5_11"] = pooled
    save("ros", out)


# ---- test 1: player spread and CV_TABLE ------------------------------------------------

SPREAD_SEASONS = [2022, 2023, 2024, 2025]
COVER_SEASONS = [2024, 2025]
SHRINK_GRID = [0.0, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 16.0, 24.0, 32.0, 48.0, 64.0, 128.0, float("inf")]
Z50, Z90 = 0.6744897501960817, 1.6448536269514722


def tool_sd(pos: np.ndarray, proj: np.ndarray, mult: np.ndarray | float = 1.0) -> np.ndarray:
    """value.player_sd, vectorized: max(SD_FLOOR, proj x CV_TABLE[pos][tier] x mult)."""
    from espncli.value import CV_TABLE, SD_FLOOR, TIERS  # noqa: PLC0415 -- the live numbers, not a copy

    tier = np.where(proj < TIERS[0][1], 0, np.where(proj < TIERS[1][1], 1, 2))
    cv = np.array([CV_TABLE[p][t] for p, t in zip(pos, tier, strict=True)], dtype=float)
    return np.maximum(SD_FLOOR, proj * cv * mult)


def tier_label(proj: np.ndarray) -> np.ndarray:
    from espncli.value import TIERS  # noqa: PLC0415

    return np.where(proj < TIERS[0][1], "0-7", np.where(proj < TIERS[1][1], "7-13", "13+"))


def residual_frame(seasons: list[int]) -> tuple[pl.DataFrame, dict]:
    """One row per player-game with a Sleeper projection above 0 that the player
    played, weeks 1-17. A player active on offense (snap counts) with no box-score
    line scored 0 and is kept. D/ST joins on team."""
    import nflreadpy as nfl  # noqa: PLC0415

    sl = (nflraw.sleeper_weeks(seasons).filter((pl.col("proj") > 0) & (pl.col("week") <= LAST_WEEK))
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    pw = (nflraw.player_weeks(seasons).filter(pl.col("pos").is_in([*SKILL, "K"]) & (pl.col("week") <= LAST_WEEK))
          .select(["season", "week", "player_id", "name", "pts"])
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    ids = nfl.load_ff_playerids().select(["pfr_id", "gsis_id"]).filter(pl.col("pfr_id").is_not_null() & pl.col("gsis_id").is_not_null()).unique("pfr_id")
    snaps = []
    for s in seasons:
        sc = (nfl.load_snap_counts(seasons=[s]).filter((pl.col("game_type") == "REG") & (pl.col("offense_snaps") > 0))
              .select(["season", "week", "pfr_player_id"]))
        snaps.append(sc.join(ids, left_on="pfr_player_id", right_on="pfr_id", how="inner")
                     .select(["season", "week", "gsis_id"]).with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    snaps_df = pl.concat(snaps).unique().with_columns(pl.lit(True).alias("active"))
    players = (sl.filter(pl.col("pos") != "D/ST").filter(pl.col("gsis_id").is_not_null())
               .group_by(["season", "week", "gsis_id"]).agg(pl.col("proj").max(), pl.col("pos").first())
               .join(pw, left_on=["season", "week", "gsis_id"], right_on=["season", "week", "player_id"], how="left")
               .join(snaps_df, on=["season", "week", "gsis_id"], how="left"))
    n_box = int(players["pts"].is_not_null().sum())
    zero_active = players.filter(pl.col("pts").is_null() & pl.col("active").fill_null(False) & (pl.col("pos") != "K"))
    players = pl.concat([players.filter(pl.col("pts").is_not_null()),
                         zero_active.with_columns(pl.lit(0.0).alias("pts"))], how="diagonal_relaxed")
    players = players.select(["season", "week", pl.col("gsis_id").alias("key"), "name", "pos", "proj", "pts"])
    dw = (nflraw.dst_weeks(seasons).select(["season", "week", "team", "pts"])
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    dst = (sl.filter(pl.col("pos") == "D/ST").select(["season", "week", "team", "proj"])
           .join(dw, on=["season", "week", "team"], how="inner")
           .select(["season", "week", pl.col("team").alias("key"), pl.col("team").alias("name"), pl.lit("D/ST").alias("pos"), "proj", "pts"]))
    df = (pl.concat([players, dst], how="diagonal_relaxed").filter(pl.col("pos").is_in([*SKILL, "K", "D/ST"]))
          .sort(["season", "week", "pos", "key"]))
    meta = {"rows": df.height, "box_score_rows": n_box, "active_no_statline_rows": zero_active.height}
    return df, meta


def normal_nll(r: np.ndarray, sd: np.ndarray) -> np.ndarray:
    return 0.5 * np.log(2 * np.pi * sd * sd) + 0.5 * (r / sd) ** 2


def normal_crps(r: np.ndarray, sd: np.ndarray) -> np.ndarray:
    from scipy.stats import norm  # noqa: PLC0415

    z = r / sd
    return sd * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))


def persistence(units: pl.DataFrame, a: str, b: str, players: np.ndarray) -> dict:
    """Pearson and Spearman correlation of log(a) and log(b), CI by player bootstrap."""
    from scipy.stats import spearmanr  # noqa: PLC0415

    x, y = np.log(units[a].to_numpy()), np.log(units[b].to_numpy())
    ok = np.isfinite(x) & np.isfinite(y)
    x, y, players = x[ok], y[ok], players[ok]
    r = float(np.corrcoef(x, y)[0, 1])
    rho = float(spearmanr(x, y).statistic)  # pyright: ignore[reportAttributeAccessIssue]
    _, idx = np.unique(players, return_inverse=True)
    k = int(idx.max()) + 1
    boots = []
    groups = [np.flatnonzero(idx == i) for i in range(k)]
    for _ in range(1000):
        pick = np.concatenate([groups[i] for i in RNG.integers(0, k, size=k)])
        boots.append(np.corrcoef(x[pick], y[pick])[0, 1])
    return {"n": int(x.size), "pearson_log": r3(r), "ci95": [r3(float(np.percentile(boots, 2.5))), r3(float(np.percentile(boots, 97.5)))],
            "spearman": r3(rho)}


def unit_rms(df: pl.DataFrame, by: list[str], zcol: str = "z") -> pl.DataFrame:
    return df.group_by(by).agg(pl.len().alias("g"), (pl.col(zcol) ** 2).mean().sqrt().alias("rms"))


def cmd_spread(args: argparse.Namespace) -> None:
    expect = ("Coverage: the IQR-based table gives about 50% at the 50% interval but well under 90% at the 90% "
              "interval (heavy right tail). Player trait: split-half correlation of the residual-SD ratio 0.1-0.3, "
              "season to season under 0.2; the NLL-best shrinkage is 20+ games, so SD_SHRINK = 6 is too light.")
    print("EXPECT:", expect)
    sd_shrink = tool_constant("volume", "SD_SHRINK")
    df, meta = residual_frame(SPREAD_SEASONS)
    pos = df["pos"].to_numpy()
    proj = df["proj"].to_numpy().astype(float)
    pts = df["pts"].to_numpy().astype(float)
    sd = tool_sd(pos, proj)
    df = df.with_columns(pl.Series("sd", sd), pl.Series("r", pts - proj), pl.Series("z", (pts - proj) / sd),
                         pl.Series("tier", tier_label(proj)))
    out: dict[str, Any] = {"expect": expect, "data": meta, "SD_SHRINK_in_tool": sd_shrink}

    # -- coverage of the table's normal intervals, 2024-2025 ------------------------
    cov = df.filter(pl.col("season").is_in(COVER_SEASONS))
    table = {}
    for (p_, t_), g in sorted(cov.group_by(["pos", "tier"]), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        z = g["z"].to_numpy()
        r = g["r"].to_numpy()
        pj = g["proj"].to_numpy()
        table[f"{p_} {t_}"] = {
            "n": int(z.size), "cov50": r3(float(np.mean(np.abs(z) <= Z50))), "cov90": r3(float(np.mean(np.abs(z) <= Z90))),
            "below90": r3(float(np.mean(z < -Z90))), "above90": r3(float(np.mean(z > Z90))),
            "median_z": r3(float(np.median(z))), "rms_z": r3(float(np.sqrt(np.mean(z * z)))),
            "mean_resid": r3(float(np.mean(r))), "sd_z": r3(float(np.std(z))),
            "scale_for_cov50": r3(float(np.percentile(np.abs(z), 50) / Z50)),
            "scale_for_cov90": r3(float(np.percentile(np.abs(z), 90) / Z90)),
            "cv_table": r3(float(np.median(g["sd"].to_numpy() / pj))),
            "cv_variance_matched": r3(float(np.sqrt(np.mean(r * r) / np.mean(pj * pj))))}
    z_all = cov["z"].to_numpy()
    out["coverage_2024_2025"] = {"overall": {"n": int(z_all.size), "cov50": r3(float(np.mean(np.abs(z_all) <= Z50))),
                                             "cov90": r3(float(np.mean(np.abs(z_all) <= Z90))),
                                             "rms_z": r3(float(np.sqrt(np.mean(z_all ** 2))))},
                                 "by_pos_tier": table}
    by_season = {}
    for s in SPREAD_SEASONS:
        zz = df.filter(pl.col("season") == s)["z"].to_numpy()
        by_season[int(s)] = {"cov50": r3(float(np.mean(np.abs(zz) <= Z50))), "cov90": r3(float(np.mean(np.abs(zz) <= Z90))),
                             "rms_z": r3(float(np.sqrt(np.mean(zz ** 2))))}
    out["coverage_by_season"] = by_season
    print("coverage", json.dumps(out["coverage_2024_2025"]["overall"]), json.dumps(by_season))
    for k_, v_ in table.items():
        print(f"   {k_:<10} {json.dumps(v_)}")

    # -- a variance-matched table: fit on 2022-2023, scored on 2024-2025 -----------
    def vm_table(frame: pl.DataFrame) -> dict[tuple[str, str], float]:
        agg = frame.group_by(["pos", "tier"]).agg(((pl.col("r") ** 2).mean() / (pl.col("proj") ** 2).mean()).sqrt().alias("cv"),
                                                  pl.len().alias("n"))
        return {(str(a), str(b)): float(c) for a, b, c, n_ in agg.iter_rows() if n_ >= 40}

    fit = vm_table(df.filter(~pl.col("season").is_in(COVER_SEASONS)))
    full = vm_table(df)
    cp, ct = cov["pos"].to_numpy(), cov["tier"].to_numpy()
    cpj, cr = cov["proj"].to_numpy().astype(float), cov["r"].to_numpy()
    old_sd = cov["sd"].to_numpy()
    new_sd = np.array([max(1.5, pj_ * fit.get((a, b), float(sd_) / pj_)) for a, b, pj_, sd_ in zip(cp, ct, cpj, old_sd, strict=True)])
    who_c = cov["key"].to_numpy()
    recal = {}
    for label, sdv in (("current_table", old_sd), ("variance_matched_2022_2023", new_sd)):
        zz = cr / sdv
        recal[label] = {"nll": r3(float(normal_nll(cr, sdv).mean()), 4), "crps": r3(float(normal_crps(cr, sdv).mean()), 4),
                        "cov50": r3(float(np.mean(np.abs(zz) <= Z50))), "cov90": r3(float(np.mean(np.abs(zz) <= Z90))),
                        "rms_z": r3(float(np.sqrt(np.mean(zz ** 2))))}
    dn, dlo, dhi = cluster_boot_mean(normal_nll(cr, new_sd) - normal_nll(cr, old_sd), who_c, 1000)
    dc, dclo, dchi = cluster_boot_mean(normal_crps(cr, new_sd) - normal_crps(cr, old_sd), who_c, 1000)
    recal["nll_new_minus_current"] = [r3(dn, 4), r3(dlo, 4), r3(dhi, 4)]
    recal["crps_new_minus_current"] = [r3(dc, 4), r3(dclo, 4), r3(dchi, 4)]
    by_cell = {}
    for (a, b) in sorted(full):
        mk = (cp == a) & (ct == b)
        if mk.sum() < 40:
            continue
        by_cell[f"{a} {b}"] = {"n_2024_25": int(mk.sum()),
                               "nll_new_minus_current": r3(float(np.mean(normal_nll(cr[mk], new_sd[mk]) - normal_nll(cr[mk], old_sd[mk]))), 4),
                               "crps_new_minus_current": r3(float(np.mean(normal_crps(cr[mk], new_sd[mk]) - normal_crps(cr[mk], old_sd[mk]))), 4),
                               "cov50_new": r3(float(np.mean(np.abs(cr[mk] / new_sd[mk]) <= Z50))),
                               "cov90_new": r3(float(np.mean(np.abs(cr[mk] / new_sd[mk]) <= Z90)))}
    recal["by_cell"] = by_cell
    recal["fit_2022_2023"] = {f"{a} {b}": r3(v) for (a, b), v in sorted(fit.items())}
    recal["fit_2022_2025_recommended"] = {f"{a} {b}": r3(v, 2) for (a, b), v in sorted(full.items())}
    out["recalibration"] = recal
    print("recalibration", json.dumps({k: v for k, v in recal.items() if k != "by_cell"}))
    for k_, v_ in by_cell.items():
        print(f"   {k_:<10} {json.dumps(v_)}")

    # -- is a player's spread a stable trait? (skill positions, fantasy-relevant) ----
    sk = df.filter(pl.col("pos").is_in(SKILL))
    rel_units = (sk.group_by(["season", "key"]).agg(pl.col("proj").mean().alias("mproj"))
                 .filter(pl.col("mproj") >= 5.0).select(["season", "key"]))
    sk = (sk.join(rel_units, on=["season", "key"], how="inner").with_columns((pl.col("week") % 2).alias("half"))
          .sort(["season", "week", "key"]))

    def trait_tests(frame: pl.DataFrame, zcol: str) -> dict:
        halves = unit_rms(frame, ["season", "key", "half"], zcol)
        wide = (halves.filter(pl.col("g") >= 4).pivot(on="half", index=["season", "key"], values="rms")
                .drop_nulls())
        wide = wide.rename({"0": "even", "1": "odd"})
        split = persistence(wide, "odd", "even", wide["key"].to_numpy())
        seas = unit_rms(frame, ["season", "key"], zcol).filter(pl.col("g") >= 8)
        nxt = seas.with_columns((pl.col("season") + 1).alias("season")).rename({"rms": "rms_prev", "g": "g_prev"})
        pair = seas.join(nxt, on=["season", "key"], how="inner")
        yoy = persistence(pair, "rms_prev", "rms", pair["key"].to_numpy())
        r = split["pearson_log"] or 0.0
        split["spearman_brown_full_season"] = r3(2 * r / (1 + r)) if r > -1 else None
        return {"split_half": split, "season_to_season": yoy}

    real = trait_tests(sk, "z")
    keys = sk["key"].to_numpy()
    uniq, inv = np.unique(keys, return_inverse=True)
    planted = {}
    for sig in (0.2, 0.5):
        m = np.exp(RNG.normal(0.0, sig, uniq.size))[inv]
        planted[f"sigma_log_{sig}"] = trait_tests(sk.with_columns(pl.Series("zp", sk["z"].to_numpy() * m)), "zp")
    shuffled = sk.with_columns(pl.Series("zs", RNG.permutation(sk["z"].to_numpy())))
    out["trait"] = {"units": "player-seasons with mean projection >= 5; residual RMS in table units",
                    "real": real, "planted": planted, "shuffled": trait_tests(shuffled, "zs")}
    print("trait real", json.dumps(real))
    print("trait planted", json.dumps(planted))
    print("trait shuffled", json.dumps(out["trait"]["shuffled"]))

    # -- shrinkage: next-season NLL and CRPS ------------------------------------------
    # History = the player's previous season (all his projected games), target =
    # every projected game of the next season (2023-2025).
    allsk = df.filter(pl.col("pos").is_in(SKILL))
    hist = unit_rms(allsk, ["season", "key"]).with_columns((pl.col("season") + 1).alias("season"))
    cell = (allsk.group_by(["season", "pos", "tier"]).agg((pl.col("z") ** 2).mean().sqrt().alias("cell_rms"))
            .with_columns((pl.col("season") + 1).alias("season")))
    tgt = (allsk.filter(pl.col("season") >= SPREAD_SEASONS[1])
           .join(hist, on=["season", "key"], how="left").join(cell, on=["season", "pos", "tier"], how="left"))
    n = tgt["g"].fill_null(0).to_numpy().astype(float)
    rms_prev = tgt["rms"].fill_null(1.0).to_numpy()
    c_cell = tgt["cell_rms"].fill_null(1.0).to_numpy()
    r_t = tgt["r"].to_numpy()
    p_t = tgt["pos"].to_numpy()
    pr_t = tgt["proj"].to_numpy().astype(float)
    who = tgt["key"].to_numpy()
    shrink = {}
    for label, scale in (("table_as_is", np.ones_like(c_cell)), ("table_rescaled_by_prev_season_cell", c_cell)):
        rows = {}
        for k in SHRINK_GRID:
            ratio = rms_prev / scale       # the player's history in units of the (rescaled) base
            if math.isinf(k):
                m = np.ones_like(n)
            else:
                m = np.where(n + k > 0, (n * ratio + k) / np.maximum(n + k, 1e-9), 1.0)
            sdk = np.maximum(1.5, tool_sd(p_t, pr_t, scale * m))
            nll = normal_nll(r_t, sdk)
            crps = normal_crps(r_t, sdk)
            rows["inf" if math.isinf(k) else str(int(k))] = {"nll": r3(float(nll.mean()), 4), "crps": r3(float(crps.mean()), 4),
                                                            "_nll": nll, "_crps": crps}
        inf = rows["inf"]
        for key_, v in rows.items():
            dm, lo, hi = cluster_boot_mean(v["_nll"] - inf["_nll"], who, 1000)
            v["nll_minus_no_multiplier"] = r3(dm, 4)
            v["ci95"] = [r3(lo, 4), r3(hi, 4)]
            dc, clo, chi = cluster_boot_mean(v["_crps"] - inf["_crps"], who, 1000)
            v["crps_minus_no_multiplier"] = r3(dc, 4)
            v["crps_ci95"] = [r3(clo, 4), r3(chi, 4)]
            del v["_nll"], v["_crps"]
            print(f"   {label:<36} k={key_:<4} {json.dumps(v)}")
        best_nll = min(rows, key=lambda q: rows[q]["nll"])
        best_crps = min(rows, key=lambda q: rows[q]["crps"])
        shrink[label] = {"by_k": rows, "best_k_nll": best_nll, "best_k_crps": best_crps}
    # The tool's own multiplier: raw weekly-points CV over the previous season's
    # logs (>= 6 games, >= 5 PPG), over the position mean, shrunk with SD_SHRINK
    # games and clipped to [0.6, 1.6]. Scored on the next season like the rest.
    pw = (nflraw.player_weeks(SPREAD_SEASONS).filter(pl.col("pos").is_in(SKILL) & (pl.col("week") <= 18))
          .select(["season", "player_id", "pos", "pts"]).with_columns(pl.col("season").cast(pl.Int64)))
    logs = pw.group_by(["season", "player_id", "pos"]).agg(pl.len().alias("n"), pl.col("pts").mean().alias("mu"),
                                                          pl.col("pts").std(ddof=0).alias("sdv"))
    logs = logs.filter((pl.col("n") >= 6) & (pl.col("mu") >= 5.0)).with_columns((pl.col("sdv") / pl.col("mu")).alias("cv"))
    logs = logs.join(logs.group_by(["season", "pos"]).agg(pl.col("cv").mean().alias("base")), on=["season", "pos"])
    tool_rows = {}
    for k in (0.0, 2.0, 6.0, 12.0, 24.0, 48.0, float("inf")):
        lk = logs.with_columns(
            (((pl.col("n") * pl.col("cv") + (0.0 if math.isinf(k) else k) * pl.col("base")) / (pl.col("n") + (0.0 if math.isinf(k) else k)))
             / pl.col("base")).clip(0.6, 1.6).alias("mult"))
        if math.isinf(k):
            lk = lk.with_columns(pl.lit(1.0).alias("mult"))
        lk = lk.select([(pl.col("season") + 1).alias("season"), pl.col("player_id").alias("key"), "mult"])
        t2 = allsk.filter(pl.col("season") >= SPREAD_SEASONS[1]).join(lk, on=["season", "key"], how="left")
        mult = t2["mult"].fill_null(1.0).to_numpy()
        sdk = tool_sd(t2["pos"].to_numpy(), t2["proj"].to_numpy().astype(float), mult)
        rr = t2["r"].to_numpy()
        tool_rows["inf" if math.isinf(k) else str(int(k))] = (normal_nll(rr, sdk), normal_crps(rr, sdk), t2["key"].to_numpy(), mult)
    ref = tool_rows["inf"]
    tool_out = {}
    for key_, (nll, crps, who2, mult) in tool_rows.items():
        dm, lo, hi = cluster_boot_mean(nll - ref[0], who2, 1000)
        dc, clo, chi = cluster_boot_mean(crps - ref[1], who2, 1000)
        tool_out[key_] = {"nll": r3(float(nll.mean()), 4), "crps": r3(float(crps.mean()), 4),
                          "nll_minus_no_multiplier": r3(dm, 4), "ci95": [r3(lo, 4), r3(hi, 4)],
                          "crps_minus_no_multiplier": r3(dc, 4), "crps_ci95": [r3(clo, 4), r3(chi, 4)],
                          "share_rows_with_multiplier": r3(float(np.mean(mult != 1.0)))}
        print(f"   tool raw-CV multiplier SD_SHRINK={key_:<4} {json.dumps(tool_out[key_])}")
    shrink["tool_raw_cv_multiplier"] = tool_out
    # The tool's raw CV against the next season's residual RMS: does it point the right way?
    lk6 = logs.with_columns(((pl.col("cv") / pl.col("base"))).alias("raw_ratio")).select(
        [(pl.col("season") + 1).alias("season"), pl.col("player_id").alias("key"), "raw_ratio"])
    nxt_rms = unit_rms(allsk.filter(pl.col("season") >= SPREAD_SEASONS[1]), ["season", "key"]).filter(pl.col("g") >= 8)
    jj = nxt_rms.join(lk6, on=["season", "key"], how="inner")
    shrink["tool_raw_cv_vs_next_season_residual_rms"] = persistence(jj, "raw_ratio", "rms", jj["key"].to_numpy())
    print("raw CV vs next residual RMS", json.dumps(shrink["tool_raw_cv_vs_next_season_residual_rms"]))
    out["shrinkage"] = shrink
    save("spread", out)


# ---- test 4: D/ST streaming ---------------------------------------------------------------

STREAM_SEASONS = list(range(2016, 2026))
LEAGUE_TEAMS = 13           # one starting D/ST (and one K) per team: the rest are free agents
QUALITY_K = 3.0             # games of prior weight on last season's PPG in the quality estimate


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(np.column_stack([np.ones(len(y)), X]), y, rcond=None)[0]


def ols_cluster_ci(X: np.ndarray, y: np.ndarray, clusters: np.ndarray, n: int = 1000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    beta = ols(X, y)
    _, idx = np.unique(clusters, return_inverse=True)
    k = int(idx.max()) + 1
    groups = [np.flatnonzero(idx == i) for i in range(k)]
    boots = []
    for _ in range(n):
        pick = np.concatenate([groups[i] for i in RNG.integers(0, k, size=k)])
        boots.append(ols(X[pick], y[pick]))
    b = np.array(boots)
    return beta, np.percentile(b, 2.5, axis=0), np.percentile(b, 97.5, axis=0)


def with_quality(df: pl.DataFrame, key: str, value: str) -> pl.DataFrame:
    """Add `q`: the unit's PPG over the earlier weeks of the season, shrunk
    toward its previous-season PPG (league mean when there is none) with
    QUALITY_K games of weight. Known before the week is played."""
    df = df.sort(["season", key, "week"])
    df = df.with_columns(
        (pl.col(value).cum_sum().over(["season", key]) - pl.col(value)).alias("_cs"),
        (pl.col(value).cum_count().over(["season", key]) - 1).alias("_cn"))
    prev = (df.group_by(["season", key]).agg(pl.col(value).mean().alias("_prev"))
            .with_columns((pl.col("season") + 1).alias("season")))
    lg = df.group_by("season").agg(pl.col(value).mean().alias("_lg")).with_columns((pl.col("season") + 1).alias("season"))
    df = df.join(prev, on=["season", key], how="left").join(lg, on="season", how="left")
    first_lg = float(df.filter(pl.col("season") == df["season"].min())[value].mean() or 0.0)  # pyright: ignore[reportArgumentType]
    df = df.with_columns(pl.coalesce(pl.col("_prev"), pl.col("_lg"), pl.lit(first_lg)).alias("_pr"))
    return df.with_columns(((pl.col("_cs") + QUALITY_K * pl.col("_pr")) / (pl.col("_cn") + QUALITY_K)).alias("q")).drop(
        ["_cs", "_cn", "_prev", "_lg", "_pr"])


def slate_moves(frame: pl.DataFrame, own_col: str, fa_col: str, fire, pick_col: str, pick_low: bool,
                noise: float = 0.0, reps: int = 1) -> dict:
    """Simulate one swap rule on every week's real slate.

    The top LEAGUE_TEAMS units by quality are 'rostered', the rest are the
    free-agent pool. A rostered unit swaps to the best free agent by
    `pick_col` when fire(own_value, fa_value) is true. Decisions can see the
    line with noise (the Tuesday opening line); outcomes are the real points."""
    gains, clusters = [], []
    n_slots = 0
    frame = frame.sort(["season", "week", "team"])
    for _ in range(reps):
        for (s, w), g in frame.group_by(["season", "week"], maintain_order=True):
            g = g.sort("q", descending=True)
            own_v = g[own_col].to_numpy().astype(float)
            fa_v = g[fa_col].to_numpy().astype(float)
            pick = g[pick_col].to_numpy().astype(float)
            pts = g["pts"].to_numpy().astype(float)
            if noise:
                e = RNG.normal(0.0, noise, own_v.size)
                own_v, fa_v = own_v + e, fa_v + e
                if pick_col in (own_col, fa_col):
                    pick = pick + e
            ok = np.isfinite(own_v)
            rost = np.flatnonzero(ok)[:LEAGUE_TEAMS]
            pool = np.flatnonzero(ok)[LEAGUE_TEAMS:]
            n_slots += rost.size
            for i in rost:
                cand = [j for j in pool if fire(own_v[i], fa_v[j])]
                if not cand:
                    continue
                j = min(cand, key=lambda c: pick[c]) if pick_low else max(cand, key=lambda c: pick[c])
                gains.append(pts[j] - pts[i])
                clusters.append(f"{s}-{w}")
    if not gains:
        return {"moves": 0}
    m, lo, hi = cluster_boot_mean(np.array(gains), np.array(clusters), 1000)
    seasons_n = frame["season"].n_unique()
    per_team_season = len(gains) / reps / (LEAGUE_TEAMS * seasons_n)
    return {"moves": int(len(gains) / reps), "gain_per_move": r3(m, 2), "ci95": [r3(lo, 2), r3(hi, 2)],
            "moves_per_team_season": r3(per_team_season, 2), "gain_per_team_season": r3(m * per_team_season, 2),
            "share_of_slots": r3(len(gains) / n_slots, 3)}


def cmd_dst(args: argparse.Namespace) -> None:
    expect = ("About -0.2 to -0.3 D/ST points per point of opponent implied total; quality adds little; the 24/19 "
              "rule gains about 1.5-2 points per move but fires rarely; a gap rule (ours minus FA >= 4-5) does as well "
              "per move and fires more often.")
    print("EXPECT:", expect)
    ours_min = tool_constant("stream-scan", "DST_OURS_MIN")
    fa_max = tool_constant("stream-scan", "DST_FA_MAX")
    d = (nflraw.dst_weeks(STREAM_SEASONS).filter(pl.col("week") <= LAST_WEEK)
         .select(["season", "week", "game_id", "team", "opp", "pts", "opp_implied"])
         .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    g = nflraw.games(STREAM_SEASONS).select(["game_id", "home", "total_line"])
    d = d.join(g, on="game_id", how="left").with_columns(
        (pl.col("team") == pl.col("home")).cast(pl.Float64).alias("is_home"),
        (pl.col("total_line") - pl.col("opp_implied")).alias("own_implied"))
    d = with_quality(d, "team", "pts").filter(pl.col("opp_implied").is_not_null()).sort(["season", "week", "team"])
    y = d["pts"].to_numpy().astype(float)
    imp = d["opp_implied"].to_numpy().astype(float)
    q = d["q"].to_numpy().astype(float)
    home = d["is_home"].to_numpy().astype(float)
    sw = (d["season"].cast(pl.Utf8) + "-" + d["week"].cast(pl.Utf8)).to_numpy()
    X = np.column_stack([imp, q, home])
    beta, lo, hi = ols_cluster_ci(X, y, sw)
    names = ["intercept", "opp_implied", "quality_ppg", "home"]
    model = {n_: {"coef": r3(b, 3), "ci95": [r3(a, 3), r3(c, 3)]} for n_, b, a, c in zip(names, beta, lo, hi, strict=True)}
    b_imp_only = ols(imp[:, None], y)
    seas = d["season"].to_numpy()
    by_period = {}
    for lo_s, hi_s in ((2016, 2020), (2021, 2025)):
        mk = (seas >= lo_s) & (seas <= hi_s)
        bp, bl, bh = ols_cluster_ci(X[mk], y[mk], sw[mk], 500)
        by_period[f"{lo_s}-{hi_s}"] = {"opp_implied": [r3(bp[1], 3), r3(bl[1], 3), r3(bh[1], 3)],
                                       "quality_ppg": [r3(bp[2], 3), r3(bl[2], 3), r3(bh[2], 3)], "n": int(mk.sum())}
    # Controls: a planted -0.3 per implied point must move the slope by -0.3;
    # implied totals shuffled within each week must give a slope near 0.
    planted = ols(X, y - 0.3 * (imp - imp.mean()))[1]
    shuf = d.with_columns(pl.col("opp_implied").shuffle(seed=7).over(["season", "week"]).alias("imp_s"))
    shuffled = ols(np.column_stack([shuf["imp_s"].to_numpy(), q, home]), y)[1]
    bins = [0, 17, 19, 21, 23, 25, 27, 99]
    by_bin = {}
    for a_, b_ in zip(bins[:-1], bins[1:], strict=True):
        mk = (imp > a_) & (imp <= b_) if a_ else imp <= b_
        if mk.sum() < 30:
            continue
        m_, l_, h_ = cluster_boot_mean(y[mk], sw[mk], 1000)
        by_bin[f"{a_}-{b_}" if a_ else f"<={b_}"] = {"n": int(mk.sum()), "mean_pts": r3(m_, 2), "ci95": [r3(l_, 2), r3(h_, 2)]}
    # Quality: does last weeks' D/ST PPG predict this week beyond the matchup?
    q_only = ols(q[:, None], y)
    out: dict[str, Any] = {
        "expect": expect, "rule_in_tool": {"DST_OURS_MIN": ours_min, "DST_FA_MAX": fa_max},
        "n_team_games": int(y.size), "mean_pts": r3(float(y.mean()), 2), "sd_pts": r3(float(y.std()), 2),
        "model": model, "by_period": by_period,
        "slope_implied_only": r3(float(b_imp_only[1]), 3), "slope_quality_only": r3(float(q_only[1]), 3),
        "controls": {"planted_slope_shift_expected": -0.3, "planted_slope_shift_measured": r3(float(planted - beta[1]), 3),
                     "shuffled_slope": r3(float(shuffled), 3)},
        "by_opp_implied": by_bin}
    print("model", json.dumps(model), "implied-only slope", out["slope_implied_only"], "controls", json.dumps(out["controls"]))
    for k_, v_ in by_bin.items():
        print("   bin", k_, json.dumps(v_))
    pred_col = (beta[0] + beta[1] * d["opp_implied"] + beta[2] * d["q"] + beta[3] * d["is_home"]).alias("pred")
    d = d.with_columns(pred_col)
    rules = {}
    rules["current_24_19"] = slate_moves(d, "opp_implied", "opp_implied", lambda o, f: o >= ours_min and f <= fa_max, "opp_implied", True)
    grid = {}
    for a_ in (20, 21, 22, 23, 24, 25, 26):
        for b_ in (17, 18, 19, 20, 21, 22):
            if b_ >= a_:
                continue
            grid[f"{a_}/{b_}"] = slate_moves(d, "opp_implied", "opp_implied", lambda o, f, a_=a_, b_=b_: o >= a_ and f <= b_, "opp_implied", True)
    gaps = {}
    for gap in (2, 3, 4, 5, 6, 7, 8):
        gaps[str(gap)] = slate_moves(d, "opp_implied", "opp_implied", lambda o, f, gap=gap: o - f >= gap, "opp_implied", True)
    model_rule = {}
    for c in (0.0, 0.5, 1.0, 1.5, 2.0, 3.0):
        model_rule[str(c)] = slate_moves(d, "pred", "pred", lambda o, f, c=c: f - o >= c, "pred", False)
    tuesday = {}
    for sd_ in (1.0, 2.0):
        tuesday[str(sd_)] = {"current_24_19": slate_moves(d, "opp_implied", "opp_implied", lambda o, f: o >= ours_min and f <= fa_max,
                                                          "opp_implied", True, noise=sd_, reps=10),
                             "gap_4": slate_moves(d, "opp_implied", "opp_implied", lambda o, f: o - f >= 4, "opp_implied", True, noise=sd_, reps=10)}
    shuffled_rule = slate_moves(shuf.with_columns(pl.col("imp_s").alias("opp_implied")), "opp_implied", "opp_implied",
                                lambda o, f: o >= ours_min and f <= fa_max, "opp_implied", True)
    rules["marginal_by_gap_best_fa"] = marginal_by_gap(d, "opp_implied", "opp_implied", True, [-99, 0, 2, 4, 6, 8, 10, 99])
    rules.update({"grid_ours_min/fa_max": grid, "gap_rule": gaps, "model_gain_rule": model_rule,
                  "tuesday_noise_sd": tuesday, "control_shuffled_lines_24_19": shuffled_rule})
    out["rules"] = rules
    print("current", json.dumps(rules["current_24_19"]))
    for k_, v_ in grid.items():
        print("   grid", k_, json.dumps(v_))
    for k_, v_ in gaps.items():
        print("   gap", k_, json.dumps(v_))
    for k_, v_ in model_rule.items():
        print("   model", k_, json.dumps(v_))
    print("tuesday", json.dumps(tuesday))
    print("shuffled-lines control", json.dumps(shuffled_rule))
    save("dst", out)


def marginal_by_gap(frame: pl.DataFrame, own_col: str, pick_col: str, pick_low: bool,
                    edges: list[float]) -> dict:
    """For every rostered unit and the best free agent by `pick_col` that week:
    realized gain by the size of the gap (pick value difference), so the value
    of a swap at each gap is visible, not only the average above a threshold."""
    gaps, gains, clusters = [], [], []
    frame = frame.sort(["season", "week", "team"])
    for (s, w), g in frame.group_by(["season", "week"], maintain_order=True):
        g = g.sort("q", descending=True)
        own_v = g[own_col].to_numpy().astype(float)
        pick = g[pick_col].to_numpy().astype(float)
        pts = g["pts"].to_numpy().astype(float)
        ok = np.isfinite(own_v)
        rost = np.flatnonzero(ok)[:LEAGUE_TEAMS]
        pool = [j for j in np.flatnonzero(ok)[LEAGUE_TEAMS:] if np.isfinite(pick[j])]
        if not pool:
            continue
        j = min(pool, key=lambda c: pick[c]) if pick_low else max(pool, key=lambda c: pick[c])
        for i in rost:
            gaps.append((own_v[i] - pick[j]) if pick_low else (pick[j] - own_v[i]))
            gains.append(pts[j] - pts[i])
            clusters.append(f"{s}-{w}")
    ga, gn, cl = np.array(gaps), np.array(gains), np.array(clusters)
    out = {}
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mk = (ga >= lo) & (ga < hi)
        if mk.sum() < 30:
            continue
        m, l_, h_ = cluster_boot_mean(gn[mk], cl[mk], 1000)
        out[f"{lo:g} to {hi:g}"] = {"n": int(mk.sum()), "mean_gap": r3(float(ga[mk].mean()), 2),
                                    "gain": r3(m, 2), "ci95": [r3(l_, 2), r3(h_, 2)]}
    return out


# ---- test 5: K streaming -------------------------------------------------------------------

K_WIND_FAIR = 15.0          # mph; at or above this an outdoor game is not "fair" (ESPN's string is not archived)


def cmd_k(args: argparse.Namespace) -> None:
    expect = ("About +0.15 to +0.25 K points per point of own implied total; dome +0.3-0.5; wind above 15 mph costs "
              "about 1 point; a 4-point gap is worth about 0.6-1.0 points per move, close to the noise floor.")
    print("EXPECT:", expect)
    gap_min = tool_constant("stream-scan", "K_GAP_MIN")
    g = nflraw.games(STREAM_SEASONS).filter(pl.col("week") <= LAST_WEEK).with_columns(
        pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
    sides = pl.concat([
        g.select(["season", "week", "game_id", pl.col("home").alias("team"), pl.col("implied_home").alias("own_implied"),
                  pl.col("implied_away").alias("opp_implied"), "roof", "temp", "wind", pl.lit(1.0).alias("is_home")]),
        g.select(["season", "week", "game_id", pl.col("away").alias("team"), pl.col("implied_away").alias("own_implied"),
                  pl.col("implied_home").alias("opp_implied"), "roof", "temp", "wind", pl.lit(0.0).alias("is_home")])])
    k = (nflraw.player_weeks(STREAM_SEASONS).filter((pl.col("pos") == "K") & (pl.col("week") <= LAST_WEEK))
         .group_by(["game_id", "team"]).agg(pl.col("pts").sum(), pl.col("fg_att").sum(), pl.col("pat_made").sum()))
    d = sides.join(k, on=["game_id", "team"], how="left")
    no_row = int(d["pts"].is_null().sum())
    d = d.with_columns(pl.col("pts").fill_null(0.0), pl.col("fg_att").fill_null(0), pl.col("pat_made").fill_null(0))
    d = d.filter(pl.col("own_implied").is_not_null())
    indoor = pl.col("roof").is_in(["dome", "closed"])
    d = d.with_columns(
        indoor.cast(pl.Float64).alias("indoor"),
        pl.when(indoor).then(0.0).otherwise(pl.col("wind").fill_null(7.0)).alias("wind_out"),
        (~indoor & pl.col("wind").is_null()).cast(pl.Float64).alias("wind_missing"),
        pl.when(indoor).then(0.0).otherwise((50.0 - pl.col("temp").fill_null(60.0)).clip(lower_bound=0.0)).alias("cold_out"),
        (indoor | pl.col("wind").is_null() | (pl.col("wind") < K_WIND_FAIR)).alias("fair"))
    d = with_quality(d, "team", "pts").sort(["season", "week", "team"])
    y = d["pts"].to_numpy().astype(float)
    cols = ["own_implied", "indoor", "wind_out", "wind_missing", "cold_out", "q"]
    seas = d["season"].to_numpy()
    # Season effects: K scoring rose (50+ yard makes doubled 2016-2024) while totals fell.
    fe = np.column_stack([(seas == s_).astype(float) for s_ in STREAM_SEASONS[1:]])
    X = np.column_stack([d[c].to_numpy().astype(float) for c in cols])
    sw = (d["season"].cast(pl.Utf8) + "-" + d["week"].cast(pl.Utf8)).to_numpy()
    beta_fe, lo_fe, hi_fe = ols_cluster_ci(np.column_stack([X, fe]), y, sw)
    beta, lo, hi = ols_cluster_ci(X, y, sw)
    model = {n_: {"coef": r3(b, 3), "ci95": [r3(a, 3), r3(c, 3)]}
             for n_, b, a, c in zip(["intercept", *cols], beta_fe[:len(cols) + 1], lo_fe[:len(cols) + 1],
                                    hi_fe[:len(cols) + 1], strict=True)}
    model_pooled = {n_: {"coef": r3(b, 3), "ci95": [r3(a, 3), r3(c, 3)]} for n_, b, a, c in zip(["intercept", *cols], beta, lo, hi, strict=True)}
    # Leave-one-season-out predictions for a model-based swap rule.
    pred = np.zeros_like(y)
    for s_ in STREAM_SEASONS:
        tr, te = seas != s_, seas == s_
        b_ = ols(X[tr], y[tr])
        pred[te] = b_[0] + X[te] @ b_[1:]
    imp = X[:, 0]
    planted = ols(X, y + 0.2 * (imp - imp.mean()))[1] - beta[1]
    shuf = d.with_columns(pl.col("own_implied").shuffle(seed=11).over(["season", "week"]).alias("imp_s"))
    Xs = X.copy()
    Xs[:, 0] = shuf["imp_s"].to_numpy()
    shuffled = ols(Xs, y)[1]
    by_bin = {}
    edges = [0, 17, 19, 21, 23, 25, 27, 29, 99]
    for a_, b_ in zip(edges[:-1], edges[1:], strict=True):
        mk = (imp > a_) & (imp <= b_)
        if mk.sum() < 30:
            continue
        m_, l_, h_ = cluster_boot_mean(y[mk], sw[mk], 1000)
        by_bin[f"{a_}-{b_}"] = {"n": int(mk.sum()), "mean_pts": r3(m_, 2), "ci95": [r3(l_, 2), r3(h_, 2)],
                                "fg_att": r3(float(d["fg_att"].to_numpy()[mk].mean()), 2),
                                "pat_made": r3(float(d["pat_made"].to_numpy()[mk].mean()), 2)}
    wind_bins = {}
    wo = d["wind_out"].to_numpy()
    ind = d["indoor"].to_numpy() > 0
    wm = d["wind_missing"].to_numpy() > 0
    for name, mk in (("indoor", ind), ("outdoor wind <10", ~ind & ~wm & (wo < 10)), ("outdoor 10-14", ~ind & ~wm & (wo >= 10) & (wo < 15)),
                     ("outdoor 15-19", ~ind & ~wm & (wo >= 15) & (wo < 20)), ("outdoor 20+", ~ind & ~wm & (wo >= 20))):
        # residual after the implied total, so wind is not confused with weak offenses
        res = y - (ols(imp[:, None], y)[0] + ols(imp[:, None], y)[1] * imp)
        m_, l_, h_ = cluster_boot_mean(res[mk], sw[mk], 1000)
        wind_bins[name] = {"n": int(mk.sum()), "resid_pts": r3(m_, 2), "ci95": [r3(l_, 2), r3(h_, 2)]}
    out: dict[str, Any] = {"expect": expect, "rule_in_tool": {"K_GAP_MIN": gap_min, "fair": f"dome or wind < {K_WIND_FAIR:g} mph (proxy)"},
                           "n_team_games": int(y.size), "team_games_without_k_row": no_row,
                           "mean_pts": r3(float(y.mean()), 2), "sd_pts": r3(float(y.std()), 2),
                           "model_season_effects": model, "model_pooled": model_pooled,
                           "controls": {"planted_slope_shift_expected": 0.2, "planted_slope_shift_measured": r3(float(planted), 3),
                                        "shuffled_slope": r3(float(shuffled), 3)},
                           "by_own_implied": by_bin, "weather_residual": wind_bins}
    print("model (season effects)", json.dumps(model))
    print("model (pooled)", json.dumps(model_pooled))
    print("controls", json.dumps(out["controls"]))
    for k_, v_ in by_bin.items():
        print("   bin", k_, json.dumps(v_))
    for k_, v_ in wind_bins.items():
        print("   weather", k_, json.dumps(v_))
    d = d.with_columns(pl.when(pl.col("fair")).then(pl.col("own_implied")).otherwise(None).alias("own_implied_fair"))
    rules = {}
    for gap in (1, 2, 3, 4, 5, 6, 8):
        rules[f"gap_{gap}_fair"] = slate_moves(d, "own_implied", "own_implied_fair", lambda o, f, gap=gap: np.isfinite(f) and f - o >= gap,
                                               "own_implied_fair", False)
    rules["gap_4_any_weather"] = slate_moves(d, "own_implied", "own_implied", lambda o, f: f - o >= 4, "own_implied", False)
    rules["tuesday_sd1_gap_4_fair"] = slate_moves(d, "own_implied", "own_implied_fair", lambda o, f: np.isfinite(f) and f - o >= 4,
                                                  "own_implied_fair", False, noise=1.0, reps=10)
    rules["control_shuffled_lines_gap_4"] = slate_moves(shuf.with_columns(pl.col("imp_s").alias("own_implied")).with_columns(
        pl.when(pl.col("fair")).then(pl.col("own_implied")).otherwise(None).alias("own_implied_fair")),
        "own_implied", "own_implied_fair", lambda o, f: np.isfinite(f) and f - o >= 4, "own_implied_fair", False)
    d = d.with_columns(pl.Series("pred", pred))
    for c in (0.0, 0.5, 1.0, 1.5):
        rules[f"model_gain_{c:g}"] = slate_moves(d, "pred", "pred", lambda o, f, c=c: f - o >= c, "pred", False)
    rules["marginal_by_pred_gap"] = marginal_by_gap(d, "pred", "pred", False, [-99, 0, 0.5, 1.0, 1.5, 2.0, 99])
    rules["marginal_by_gap_best_fair_fa"] = marginal_by_gap(d.with_columns(pl.col("own_implied_fair").fill_null(float("nan"))),
                                                            "own_implied", "own_implied_fair", False, [-99, 0, 2, 4, 6, 8, 99])
    out["rules"] = rules
    for k_, v_ in rules.items():
        print("   rule", k_, json.dumps(v_))
    save("k", out)


# ---- test 3: BUY / SELL flags ---------------------------------------------------------------

FLAG_SEASONS = list(range(2019, 2026))
FLAG_WEEKS = list(range(4, 11))
FLAG_HORIZON = 4            # weeks after the decision whose PPG is the outcome
MATCH_RANKS = 2             # control players within this many points-rank places


def flag_frame() -> pl.DataFrame:
    """bin/volume's season-to-date rows, ranks and outcome at every decision week.

    Volume metric as the tool has it: RB carries + 1.5 x targets per game; QB
    attempts + carries per game; WR/TE mean WOPR (mean target share when WOPR
    is missing). Points rank by PPG. Both ranks among every player at the
    position with a game so far. League points stand in for nflverse PPR (the
    two differ only on return and fumble-recovery touchdowns)."""
    pw = (nflraw.player_weeks(FLAG_SEASONS).filter(pl.col("pos").is_in(SKILL) & (pl.col("week") <= LAST_WEEK))
          .select(["season", "week", "player_id", "name", "pos", "pts", "carries", "targets", "attempts", "wopr", "target_share"])
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    frames = []
    for season in FLAG_SEASONS:
        ps = pw.filter(pl.col("season") == season)
        for w in FLAG_WEEKS:
            b = ps.filter(pl.col("week") < w).group_by(["player_id"]).agg(
                pl.col("pos").last(), pl.col("name").last(), pl.len().alias("g"),
                pl.col("pts").mean().alias("ppg"),
                ((pl.col("carries").fill_null(0) + 1.5 * pl.col("targets").fill_null(0)).mean()).alias("opps_pg"),
                ((pl.col("attempts").fill_null(0) + pl.col("carries").fill_null(0)).mean()).alias("qb_pg"),
                pl.col("wopr").mean().alias("wopr"), pl.col("target_share").mean().alias("tgt_share"))
            b = b.with_columns(
                pl.when(pl.col("pos") == "RB").then(pl.col("opps_pg"))
                .when(pl.col("pos") == "QB").then(pl.col("qb_pg"))
                .otherwise(pl.coalesce(pl.col("wopr"), pl.col("tgt_share"), pl.lit(0.0))).alias("vol"))
            b = b.sort(["pos", "player_id"]).with_columns(
                # rank() returns u32: cast, or pts_rank - vol_rank wraps around below zero
                pl.col("vol").rank("ordinal", descending=True).over("pos").cast(pl.Int64).alias("vol_rank"),
                pl.col("ppg").rank("ordinal", descending=True).over("pos").cast(pl.Int64).alias("pts_rank"))
            a = ps.filter((pl.col("week") >= w) & (pl.col("week") < w + FLAG_HORIZON)).group_by("player_id").agg(
                pl.len().alias("g_after"), pl.col("pts").mean().alias("y"))
            frames.append(b.join(a, on="player_id", how="left").with_columns(
                pl.lit(season).alias("season"), pl.lit(w).alias("week")))
    return pl.concat(frames).sort(["season", "week", "pos", "player_id"])


def flags_for(f: pl.DataFrame, gap: int, top_n: dict) -> tuple[np.ndarray, np.ndarray]:
    pos = f["pos"].to_numpy()
    vr, pr = f["vol_rank"].to_numpy().astype(np.int64), f["pts_rank"].to_numpy().astype(np.int64)
    top = np.array([top_n.get(p_, 0) for p_ in pos])
    d = pr - vr
    buy = (vr <= top) & (d >= gap) & (pos != "QB")
    sell = ~buy & (pr <= top) & (-d >= gap) & (pos != "QB")
    return buy, sell


def matched_effect(f: pl.DataFrame, flagged: np.ndarray, any_flag: np.ndarray, y: np.ndarray, min_after: int = 2) -> dict:
    """Mean of (flagged player's next-4-week PPG - mean of unflagged players at
    the same season, week, position and points rank +-MATCH_RANKS)."""
    keys = (f["season"].cast(pl.Utf8) + "|" + f["week"].cast(pl.Utf8) + "|" + f["pos"]).to_numpy()
    pr = f["pts_rank"].to_numpy().astype(np.int64)
    ppg = f["ppg"].to_numpy()
    ga = f["g_after"].fill_null(0).to_numpy()
    pid = f["player_id"].to_numpy()
    has_y = ga >= min_after
    idx_by_key: dict[str, np.ndarray] = {}
    for k in np.unique(keys):
        idx_by_key[k] = np.flatnonzero(keys == k)
    eff, eff_now, who = [], [], []
    n_flag, n_no_outcome = int(flagged.sum()), 0
    for i in np.flatnonzero(flagged):
        if not has_y[i]:
            n_no_outcome += 1
            continue
        grp = idx_by_key[keys[i]]
        ctrl = grp[(~any_flag[grp]) & has_y[grp] & (np.abs(pr[grp] - pr[i]) <= MATCH_RANKS)]
        if ctrl.size == 0:
            continue
        eff.append(y[i] - y[ctrl].mean())
        eff_now.append(ppg[i] - ppg[ctrl].mean())
        who.append(pid[i])
    if not eff:
        return {"n_flagged": n_flag, "n_matched": 0}
    e, en, wh = np.array(eff), np.array(eff_now), np.array(who)
    m, lo, hi = cluster_boot_mean(e, wh, 1000)
    return {"n_flagged": n_flag, "n_matched": int(e.size), "players": int(np.unique(wh).size),
            "share_no_outcome": r3(n_no_outcome / max(n_flag, 1), 3),
            "effect_ppg": r3(m, 2), "ci95": [r3(lo, 2), r3(hi, 2)], "balance_ppg_to_date": r3(float(en.mean()), 2)}


def cmd_flags(args: argparse.Namespace) -> None:
    expect = ("BUY players outscore points-rank peers by about +1 PPG over the next four weeks (CI touching 0 to +2); "
              "SELL players underperform by about -1; the effect grows with the gap and the gap of 8 is in the flat part.")
    print("EXPECT:", expect)
    gap0 = int(tool_constant("volume", "RANK_GAP"))
    top_n = tool_constant("volume", "TOP_N")
    assert isinstance(top_n, dict)
    f = flag_frame()
    y = f["y"].fill_null(float("nan")).to_numpy().astype(float)
    out: dict[str, Any] = {"expect": expect, "rule_in_tool": {"RANK_GAP": gap0, "TOP_N": top_n},
                           "decisions": int(f.height), "seasons": FLAG_SEASONS, "weeks": FLAG_WEEKS,
                           "outcome": f"PPG over weeks w to w+{FLAG_HORIZON - 1}, players with 2+ games in that window",
                           "by_gap": {}}
    for gap in (4, 6, 8, 10, 12, 16):
        buy, sell = flags_for(f, gap, top_n)
        any_flag = buy | sell
        res = {"BUY": matched_effect(f, buy, any_flag, y), "SELL": matched_effect(f, sell, any_flag, y)}
        out["by_gap"][str(gap)] = res
        print(f"gap {gap}: BUY {json.dumps(res['BUY'])}\n        SELL {json.dumps(res['SELL'])}")
    buy, sell = flags_for(f, gap0, top_n)
    any_flag = buy | sell
    by_pos = {}
    pos = f["pos"].to_numpy()
    for p_ in ("RB", "WR", "TE"):
        mk = pos == p_
        by_pos[p_] = {"BUY": matched_effect(f, buy & mk, any_flag, y), "SELL": matched_effect(f, sell & mk, any_flag, y)}
    out["by_pos_at_tool_gap"] = by_pos
    print("by pos", json.dumps(by_pos))
    # Controls: +2 PPG planted on the flagged players' outcomes must come back as
    # +2 more; flags shuffled within position-week must give about 0.
    planted = matched_effect(f, buy, any_flag, np.where(buy, y + 2.0, y))
    keys = (f["season"].cast(pl.Utf8) + "|" + f["week"].cast(pl.Utf8) + "|" + f["pos"]).to_numpy()
    sh = buy.copy()
    for k in np.unique(keys):
        ix = np.flatnonzero(keys == k)
        top_ix = ix[f["pts_rank"].to_numpy()[ix] <= 60]
        sh[top_ix] = RNG.permutation(buy[top_ix])
    shuffled = matched_effect(f, sh, sh | sell, y)
    out["controls"] = {"planted_plus_2": planted, "shuffled_buy_flags": shuffled}
    print("controls", json.dumps(out["controls"]))
    # Mechanism: does volume add to points-to-date? Regress next-4-week PPG on PPG
    # to date and the volume percentile within position-week (2+ games before).
    mech = {}
    vr = f["vol_rank"].to_numpy().astype(float)
    pr = f["pts_rank"].to_numpy().astype(float)
    ppg = f["ppg"].to_numpy().astype(float)
    g_before = f["g"].to_numpy()
    ga = f["g_after"].fill_null(0).to_numpy()
    for p_ in ("RB", "WR", "TE"):
        top = top_n.get(p_, 30)
        mk = (pos == p_) & (g_before >= 2) & (ga >= 2) & ((vr <= 2 * top) | (pr <= 2 * top))
        Xm = np.column_stack([ppg[mk], -vr[mk]])
        b, lo, hi = ols_cluster_ci(Xm, y[mk], f["player_id"].to_numpy()[mk], 500)
        mech[p_] = {"n": int(mk.sum()), "per_ppg": [r3(b[1], 3), r3(lo[1], 3), r3(hi[1], 3)],
                    "per_10_volume_rank_places": [r3(10 * b[2], 3), r3(10 * lo[2], 3), r3(10 * hi[2], 3)]}
    out["mechanism_regression"] = mech
    print("mechanism", json.dumps(mech))
    # Marginal value by gap band, against one fixed control set: players with
    # no flag even at a gap of 4.
    b4, s4 = flags_for(f, 4, top_n)
    none4 = ~(b4 | s4)
    vr_i = f["vol_rank"].to_numpy().astype(np.int64)
    pr_i = f["pts_rank"].to_numpy().astype(np.int64)
    top = np.array([top_n.get(p_, 0) for p_ in pos])
    dd = pr_i - vr_i
    bands = {}
    for lo_b, hi_b in ((4, 8), (8, 12), (12, 99)):
        bb = (vr_i <= top) & (dd >= lo_b) & (dd < hi_b) & (pos != "QB")
        ss = ~bb & (pr_i <= top) & (-dd >= lo_b) & (-dd < hi_b) & (pos != "QB")
        bands[f"{lo_b}-{hi_b - 1 if hi_b < 99 else 'up'}"] = {
            "BUY": matched_effect(f, bb, ~none4, y), "SELL": matched_effect(f, ss, ~none4, y)}
    out["by_gap_band_fixed_controls"] = bands
    print("bands", json.dumps(bands))
    # Does the flag know more than the projection? 2022-2025: match on Sleeper's
    # week-w projection (within 1 point) instead of the points rank.
    sl = (nflraw.sleeper_weeks([s_ for s_ in FLAG_SEASONS if s_ >= 2022]).filter(pl.col("pos").is_in(SKILL) & (pl.col("proj") > 0))
          .select(["season", "week", "gsis_id", "proj"]).with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    projs = []
    for w in FLAG_WEEKS:
        projs.append(sl.filter(pl.col("week") <= w).sort("week").group_by(["season", "gsis_id"]).agg(pl.col("proj").last())
                     .with_columns(pl.lit(w).cast(pl.Int64).alias("week")))
    fp = f.with_columns(pl.Series("buy8", buy), pl.Series("sell8", sell)).join(
        pl.concat(projs), left_on=["season", "week", "player_id"], right_on=["season", "week", "gsis_id"], how="inner")
    yp = fp["y"].fill_null(float("nan")).to_numpy().astype(float)
    proj = fp["proj"].to_numpy().astype(float)
    fp = fp.with_columns(pl.Series("proj_bin", np.round(proj).astype(np.int64)))
    keys = (fp["season"].cast(pl.Utf8) + "|" + fp["week"].cast(pl.Utf8) + "|" + fp["pos"]).to_numpy()
    ga = fp["g_after"].fill_null(0).to_numpy()
    pid = fp["player_id"].to_numpy()
    bflag, sflag = fp["buy8"].to_numpy(), fp["sell8"].to_numpy()
    anyf = bflag | sflag
    by_proj = {}
    for label, fl in (("BUY", bflag), ("SELL", sflag)):
        eff, resid_gap, who = [], [], []
        for i in np.flatnonzero(fl & (ga >= 2)):
            grp = np.flatnonzero(keys == keys[i])
            ctrl = grp[(~anyf[grp]) & (ga[grp] >= 2) & (np.abs(proj[grp] - proj[i]) <= 1.0)]
            if ctrl.size == 0:
                continue
            eff.append(yp[i] - yp[ctrl].mean())
            resid_gap.append((yp[i] - proj[i]) - (yp[ctrl] - proj[ctrl]).mean())
            who.append(pid[i])
        m, lo, hi = cluster_boot_mean(np.array(eff), np.array(who), 1000)
        by_proj[label] = {"n_matched": len(eff), "players": int(np.unique(np.array(who)).size),
                          "effect_ppg": r3(m, 2), "ci95": [r3(lo, 2), r3(hi, 2)]}
    # The same seasons matched on points rank, so the two numbers compare like for like.
    fr = f.filter(pl.col("season") >= 2022)
    b22, s22 = flags_for(fr, int(gap0), top_n)
    y22 = fr["y"].fill_null(float("nan")).to_numpy().astype(float)
    by_proj["rank_matched_same_seasons"] = {"BUY": matched_effect(fr, b22, b22 | s22, y22), "SELL": matched_effect(fr, s22, b22 | s22, y22)}
    out["projection_matched_2022_2025"] = by_proj
    print("projection-matched", json.dumps(by_proj))
    save("flags", out)


# ---- entry ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rule_backtests", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ros", help="test 2: ros_rate blend")
    p.add_argument("--ecr", help="local copy of db_fpecr.parquet (default: download to a temp dir)")
    sub.add_parser("spread", help="test 1: player spread multiplier and CV_TABLE coverage")
    sub.add_parser("dst", help="test 4: D/ST streaming thresholds")
    sub.add_parser("k", help="test 5: K streaming gap")
    sub.add_parser("flags", help="test 3: BUY/SELL rank-gap flags")
    args = ap.parse_args(argv)
    {"ros": cmd_ros, "spread": cmd_spread, "dst": cmd_dst, "k": cmd_k, "flags": cmd_flags}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
