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

Second brief (rule inventory, 2026-10-15):

  gate      bin/swap-scan GATE_PER_GAME (R74). Weeks 3-11 of 2022-2025:
            same-position pairs of a bench-band and a wire-band player
            (preseason ECR rank bands), the live ros_rate gap at week w
            against the realized rest-of-season PPG gap. Sign rate and mean
            realized gap by gap size, the 80% gate, and the gate that
            maximizes net realized gain at a move cost of 0, 0.5 and 1 a game,
            under a static, a moving and a mixed prior proxy.
  backup    bin/swap-scan BACKUP_INJURY_WEEKS (R77). Snap-defined starting
            QBs and TEs at weeks 6, 8, 10 and 12 of 2016-2025: the share of
            later team games they miss and the allowance in swap-scan's
            horizon units (playoff weeks weighted).
  role      bin/volume ROLE-UP and the playbook's two-week rule (R75, R90).
            2019-2025: how much of a one-week and a two-week change in snap
            share, target share and RB opportunities persists into the next
            three games, and flagged against matched unflagged players.
  ownratio  the playbook's own-ratio rule (R89). Tier medians from Sleeper
            2022-2023, scored on 2024-2025: next-week median error with the
            3-week own ratio blended in, for volume-confirmed streaks.
  alarms    the tuesday.md review alarms (R88). Exact binomial and simulated
            false-alarm rates for a calibrated forecaster, and replacements.

Every test states its expected result before it runs (EXPECT) and runs
positive and negative controls where one exists (a planted effect must be
recovered, shuffled labels must give about zero).

    rule_backtests.py ros [--ecr db_fpecr.parquet] | spread | dst | k | flags
    rule_backtests.py gate [--ecr db_fpecr.parquet] | backup | role | ownratio | alarms

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
  unsigned, and a negative rank gap wraps around. Frames that are compared
  in polars carry null, not NaN: polars orders NaN above every number, so
  `x - NaN >= threshold` is true.
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


# ---- R74: the waiver gate -------------------------------------------------------------

GATE_SEASONS = [2022, 2023, 2024, 2025]
GATE_WEEKS = list(range(3, 12))
# Draft-status bands by preseason FantasyPros positional rank, for a 13-team,
# 16-man league: about 20 QB, 55 RB, 65 WR and 20 TE are drafted, and the
# starters (with flex) are about QB 13, RB 33, WR 33, TE 13. "Bench" is the
# drafted players below the starters; "wire" is everyone below the drafted
# pool, unranked players included (the undrafted rookie who breaks out).
GATE_BENCH = {"QB": (14, 20), "RB": (34, 55), "WR": (34, 65), "TE": (14, 20)}
GATE_WIRE_FROM = {"QB": 21, "RB": 56, "WR": 66, "TE": 21}
GATE_BINS = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 99.0]
GATE_GRID = [round(0.25 * i, 2) for i in range(0, 33)]


def two_way_weights(a: np.ndarray, b: np.ndarray, n: int) -> np.ndarray:
    """n x pairs bootstrap weights: each unit of `a` and of `b` gets a Poisson(1)
    weight per replicate and a pair carries the product (two-way cluster
    bootstrap), because every player sits in many pairs."""
    _, ia = np.unique(a, return_inverse=True)
    _, ib = np.unique(b, return_inverse=True)
    wa = RNG.poisson(1.0, size=(n, int(ia.max()) + 1))
    wb = RNG.poisson(1.0, size=(n, int(ib.max()) + 1))
    return (wa[:, ia] * wb[:, ib]).astype(float)


def gate_players(ecr: pl.DataFrame, prior_kind: str = "pre") -> pl.DataFrame:
    """One row per player, season and decision week: his ros_rate at week w
    (the live espncli.value.ros_rate, fed the same inputs it gets in season)
    and what he scored from week w to 17. The band rank is always the
    preseason rank (draft status). The prior inside the rate is the preseason
    ECR ("pre") or the rest-of-season ECR of the Friday of week w ("ros"),
    which moves in season the way ESPN's season_proj does; with "ros" the
    teams that played before that Friday's scrape are dropped that week."""
    from espncli.value import NFL_WEEKS, ros_rate  # noqa: PLC0415 -- the live blend, not a copy

    seasons_all = [GATE_SEASONS[0] - 1, *GATE_SEASONS]
    pw = (nflraw.player_weeks(seasons_all).filter(pl.col("pos").is_in(SKILL) & (pl.col("week") <= LAST_WEEK))
          .select(["season", "week", "player_id", "name", "pos", "team", "pts"])
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    curves = ppg_curves(pw, seasons_all)
    sl = (nflraw.sleeper_weeks(GATE_SEASONS).filter(pl.col("pos").is_in(SKILL) & pl.col("gsis_id").is_not_null())
          .group_by(["season", "week", "gsis_id"]).agg(pl.col("proj").max())
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    g = nflraw.games(GATE_SEASONS).filter(pl.col("week") <= LAST_WEEK).with_columns(
        pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
    sched = pl.concat([g.select(["season", "week", pl.col("home").alias("team")]),
                       g.select(["season", "week", pl.col("away").alias("team")])])
    days = first_gamedays(GATE_SEASONS)
    rows = []
    for s in GATE_SEASONS:
        prev_curve = {pos: curves[(s - 1, pos)] for pos in SKILL}
        snap, _ = ecr_snapshot(ecr, "pre", days[(s, 1)] - timedelta(days=1), 14)
        ranks: dict[str, tuple[str, int, float]] = {}
        for gsis, epos, rank in snap.select(["gsis_id", "pos", "rank"]).iter_rows():
            c = prev_curve.get(epos)
            if gsis is None or c is None or not c.size:
                continue
            prior = float(c[min(int(rank), c.size) - 1])
            if gsis not in ranks or int(rank) < ranks[gsis][1]:
                ranks[gsis] = (epos, int(rank), prior)
        ps = pw.filter(pl.col("season") == s)
        sch = sched.filter(pl.col("season") == s)
        for w in GATE_WEEKS:
            ros_prior: dict[str, float] = {}
            leak: set[str] = set()
            if prior_kind in ("ros", "mix"):
                snap_w, dw = ecr_snapshot(ecr, "ros", days[(s, w)] + timedelta(days=1), 8)
                rows_w = snap_w.select(["gsis_id", "pos", "rank"]).iter_rows() if snap_w.height else iter(())
                for gsis, epos, rank in rows_w:
                    c = prev_curve.get(epos)
                    if gsis is not None and c is not None and c.size:
                        v = float(c[min(int(rank), c.size) - 1])
                        ros_prior[gsis] = max(v, ros_prior.get(gsis, 0.0))
                if dw and snap_w.height:
                    wk = g.filter((pl.col("season") == s) & (pl.col("week") == w) & (pl.col("gameday") < dw))
                    leak = set(wk["home"].to_list()) | set(wk["away"].to_list())
            b = ps.filter(pl.col("week") < w).group_by("player_id").agg(
                pl.len().alias("played"), pl.col("pts").sum().alias("pts_sum"))
            a = ps.filter(pl.col("week") >= w).group_by("player_id").agg(
                pl.len().alias("n_after"), pl.col("pts").sum().alias("pts_after"))
            who = ps.filter(pl.col("week") < w).sort("week").group_by("player_id").agg(
                pl.col("name").last(), pl.col("pos").last(), pl.col("team").last())
            # Players with no game yet take their first team of the season.
            first = ps.sort("week").group_by("player_id").agg(pl.col("name").first(), pl.col("pos").first(),
                                                              pl.col("team").first())
            who = pl.concat([who, first.join(who.select("player_id"), on="player_id", how="anti")])
            tg_before = sch.filter(pl.col("week") < w).group_by("team").agg(pl.len().alias("team_games"))
            tg_after = sch.filter(pl.col("week") >= w).group_by("team").agg(pl.len().alias("team_games_after"))
            pr = sl.filter((pl.col("season") == s) & (pl.col("week") == w)).select(
                pl.col("gsis_id").alias("player_id"), "proj")
            f = (who.join(b, on="player_id", how="left").join(a, on="player_id", how="left")
                 .join(tg_before, on="team", how="left").join(tg_after, on="team", how="left")
                 .join(pr, on="player_id", how="left").sort("player_id"))
            for r in f.iter_rows(named=True):
                epos, rank, prior = ranks.get(r["player_id"], (None, None, None))
                if epos is not None and epos != r["pos"]:
                    rank, prior = None, None
                c = prev_curve[r["pos"]]
                floor = float(c[-1]) if c.size else 0.0
                if prior_kind in ("ros", "mix") and ros_prior:      # a stale or missing scrape keeps the preseason prior
                    if r["team"] in leak:
                        continue
                    live_prior = ros_prior.get(r["player_id"], floor)
                    prior = live_prior if prior_kind == "ros" else 0.5 * live_prior + 0.5 * (prior if prior is not None else floor)
                if prior is None:
                    prior = floor
                tgames = int(r["team_games"] or 0)
                played = int(r["played"] or 0)
                season_proj = prior * max(1, NFL_WEEKS - tgames)
                rate = ros_rate(w, r["proj"], season_proj, r["pts_sum"] or 0.0, tgames, played or None)
                rows.append({"season": s, "week": w, "player_id": r["player_id"], "name": r["name"], "pos": r["pos"],
                             "rank": rank, "rate": rate, "proj": r["proj"], "played": played,
                             "n_after": int(r["n_after"] or 0), "pts_after": float(r["pts_after"] or 0.0),
                             "team_games_after": int(r["team_games_after"] or 0)})
    df = pl.DataFrame(rows, infer_schema_length=None)
    return df.with_columns(
        pl.when(pl.col("n_after") > 0).then(pl.col("pts_after") / pl.col("n_after")).otherwise(None).alias("ppg_after"),
        pl.when(pl.col("team_games_after") > 0).then(pl.col("pts_after") / pl.col("team_games_after"))
        .otherwise(None).alias("ppg_avail"))


def gate_pairs(df: pl.DataFrame, min_after: int = 2, gmin: float = 0.0) -> dict[str, np.ndarray]:
    """Every same-position (bench, wire) pair in a season-week where the wire
    player's rate is above the bench player's. G = predicted gap, R = realized."""
    out: dict[str, list] = {k: [] for k in ("G", "R", "R_avail", "pos", "wire", "bench", "sw", "season")}
    for (s, w, pos), grp in df.sort(["season", "week", "pos", "player_id"]).group_by(
            ["season", "week", "pos"], maintain_order=True):
        lo, hi = GATE_BENCH[str(pos)]
        rank = grp["rank"].to_numpy()
        ranked = np.array([x is not None and not (isinstance(x, float) and math.isnan(x)) for x in rank])
        rk = np.where(ranked, np.nan_to_num(np.array([x if x is not None else np.nan for x in rank], dtype=float), nan=1e9), 1e9)
        rate = grp["rate"].to_numpy().astype(float)
        ok = (grp["n_after"].to_numpy() >= min_after) & (rate > 0)
        bench = np.flatnonzero(ok & (rk >= lo) & (rk <= hi))
        wire = np.flatnonzero(ok & (rk >= GATE_WIRE_FROM[str(pos)]))
        if not bench.size or not wire.size:
            continue
        fut = grp["ppg_after"].to_numpy().astype(float)
        fav = grp["ppg_avail"].to_numpy().astype(float)
        pid = grp["player_id"].to_numpy()
        G = rate[wire][:, None] - rate[bench][None, :]
        R = fut[wire][:, None] - fut[bench][None, :]
        RA = fav[wire][:, None] - fav[bench][None, :]
        keep = G > gmin
        wi, bi = np.nonzero(keep)
        out["G"].append(G[keep])
        out["R"].append(R[keep])
        out["R_avail"].append(RA[keep])
        out["pos"].append(np.full(wi.size, pos))
        out["wire"].append(np.array([f"{s}|{x}" for x in pid[wire][wi]]))
        out["bench"].append(np.array([f"{s}|{x}" for x in pid[bench][bi]]))
        out["sw"].append(np.full(wi.size, f"{s}-{w}"))
        out["season"].append(np.full(wi.size, s))
    return {k: np.concatenate(v) if v else np.array([]) for k, v in out.items()}


def gate_curves(P: dict[str, np.ndarray], rcol: str, n_boot: int = 400) -> dict:
    """Sign rate and mean realized gap by predicted-gap bin, the gate where the
    sign rate reaches 80% (logistic fit, and the first bin), and the gate that
    maximizes total realized gain net of a move cost, all with bootstrap CIs."""
    G, R = P["G"], P[rcol]
    ok = np.isfinite(R)
    G, R, wa, bb = G[ok], R[ok], P["wire"][ok], P["bench"][ok]
    W = two_way_weights(wa, bb, n_boot)
    hit = (R > 0).astype(float)
    bins = {}
    for lo, hi in zip(GATE_BINS[:-1], GATE_BINS[1:], strict=True):
        mk = (G >= lo) & (G < hi)
        if mk.sum() < 30:
            continue
        sw_ = W[:, mk]
        rate_b = (sw_ @ hit[mk]) / np.maximum(sw_.sum(1), 1e-9)
        mean_b = (sw_ @ R[mk]) / np.maximum(sw_.sum(1), 1e-9)
        bins[f"{lo:g}-{hi:g}"] = {"n": int(mk.sum()), "mean_pred": r3(float(G[mk].mean()), 2),
                                  "sign_rate": r3(float(hit[mk].mean())),
                                  "sign_ci95": [r3(float(np.percentile(rate_b, 2.5))), r3(float(np.percentile(rate_b, 97.5)))],
                                  "mean_realized": r3(float(R[mk].mean()), 2),
                                  "mean_ci95": [r3(float(np.percentile(mean_b, 2.5)), 2), r3(float(np.percentile(mean_b, 97.5)), 2)]}
    # Logistic P(R > 0) = 1 / (1 + exp(-(a + b G))), fitted by Newton steps;
    # the 80% gate is (logit(0.8) - a) / b.
    def logit_fit(x: np.ndarray, yb: np.ndarray, wts: np.ndarray) -> tuple[float, float]:
        beta = np.zeros(2)
        X = np.column_stack([np.ones_like(x), x])
        for _ in range(25):
            pr = 1 / (1 + np.exp(-(X @ beta)))
            grad = X.T @ (wts * (yb - pr))
            H = (X * (wts * pr * (1 - pr))[:, None]).T @ X
            step = np.linalg.solve(H + 1e-9 * np.eye(2), grad)
            beta += step
            if np.abs(step).max() < 1e-8:
                break
        return float(beta[0]), float(beta[1])

    a0, b0 = logit_fit(G, hit, np.ones_like(G))
    l80 = math.log(0.8 / 0.2)
    gate80 = (l80 - a0) / b0 if b0 > 0 else float("inf")
    boots80, lin_a, lin_b = [], [], []
    for i in range(min(n_boot, 200)):
        a_, b_ = logit_fit(G, hit, W[i])
        boots80.append((l80 - a_) / b_ if b_ > 0 else np.inf)
        A = np.column_stack([np.ones_like(G), G])
        sw_i = W[i]
        coef = np.linalg.lstsq(A * np.sqrt(sw_i)[:, None], R * np.sqrt(sw_i), rcond=None)[0]
        lin_a.append(coef[0])
        lin_b.append(coef[1])
    first_bin = next((k for k, v in bins.items() if (v["sign_rate"] or 0) >= 0.8), None)
    coef0 = np.linalg.lstsq(np.column_stack([np.ones_like(G), G]), R, rcond=None)[0]
    # Net realized gain of every pair at or above a gate, per season-week, at a cost per move.
    n_sw = len(np.unique(P["sw"][ok]))
    best = {}
    fixed = {}
    for cost in (0.0, 0.5, 1.0):
        fixed[f"cost_{cost:g}"] = {f"{g:g}": r3(float((R[G >= g] - cost).sum() / n_sw), 1) for g in (0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)}
    for cost in (0.0, 0.5, 1.0):
        tot = np.array([[((R[G >= g] - cost) * W[i, G >= g]).sum() / n_sw for g in GATE_GRID] for i in range(min(n_boot, 200))])
        point = np.array([((R[G >= g] - cost).sum() / n_sw) for g in GATE_GRID])
        arg = [GATE_GRID[int(j)] for j in np.argmax(tot, axis=1)]
        marginal = (cost - coef0[0]) / coef0[1] if coef0[1] > 0 else float("inf")
        best[f"cost_{cost:g}"] = {"best_gate": GATE_GRID[int(np.argmax(point))],
                                  "best_gate_ci95": [float(np.percentile(arg, 2.5)), float(np.percentile(arg, 97.5))],
                                  "net_gain_per_slate_at_best": r3(float(point.max()), 2),
                                  "net_gain_per_slate_at_2.5": r3(float(point[GATE_GRID.index(2.5)]), 2),
                                  "linear_marginal_gate": r3(max(0.0, marginal), 2)}
    return {"n_pairs": int(G.size), "bins": bins,
            "gate_80_logistic": r3(gate80, 2),
            "gate_80_ci95": [r3(float(np.percentile(boots80, 2.5)), 2), r3(float(np.percentile(boots80, 97.5)), 2)],
            "gate_80_first_bin": first_bin,
            "realized_on_predicted": {"intercept": r3(float(coef0[0]), 3), "slope": r3(float(coef0[1]), 3),
                                      "slope_ci95": [r3(float(np.percentile(lin_b, 2.5)), 3), r3(float(np.percentile(lin_b, 97.5)), 3)]},
            "best_gate_by_cost": best, "net_gain_per_slate_at_gate": fixed,
            "moves_per_slate_at_gate": {f"{g:g}": r3(float((G >= g).sum() / n_sw), 1) for g in (0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0)}}


def cmd_gate(args: argparse.Namespace) -> None:
    expect = ("A ros_rate gap keeps its sign about 60% of the time at 1 point a game and 80% near 3-4 points; "
              "realized gaps are about half the predicted ones; at a cost of 0 the best gate is under 1 point, so "
              "2.5 trades gain for certainty.")
    print("EXPECT:", expect)
    gate0 = tool_constant("swap-scan", "GATE_PER_GAME")
    ecr = load_ecr(args.ecr)
    out: dict[str, Any] = {"expect": expect, "rule_in_tool": {"GATE_PER_GAME": gate0},
                           "bands": {"bench_ranks": GATE_BENCH, "wire_from_rank": GATE_WIRE_FROM},
                           "realized": "PPG over games played in weeks w-17 (both players 2+ games); "
                                       "points_per_team_game counts a missed game as 0"}
    for kind in ("pre", "ros", "mix"):
        df = gate_players(ecr, kind)
        res: dict[str, Any] = {"player_weeks": int(df.height)}
        P = gate_pairs(df)
        res["pairs"] = int(P["G"].size)
        for rcol, label in (("R", "ppg_per_game_played"), ("R_avail", "points_per_team_game")):
            res[label] = gate_curves(P, rcol)
            print(kind, label, json.dumps({k: v for k, v in res[label].items() if k != "bins"}))
            for k_, v_ in res[label]["bins"].items():
                print(f"   {k_:<8} {json.dumps(v_)}")
        # Calibration around zero: the realized gap where the rate calls the pair even.
        Pc = gate_pairs(df, gmin=-2.0)
        cal = {}
        for lo in (-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5):
            mk = (Pc["G"] >= lo) & (Pc["G"] < lo + 0.5) & np.isfinite(Pc["R"])
            if mk.sum() < 30:
                continue
            Wc = two_way_weights(Pc["wire"][mk], Pc["bench"][mk], 200)
            mb = (Wc @ Pc["R"][mk]) / np.maximum(Wc.sum(1), 1e-9)
            cal[f"{lo:g} to {lo + 0.5:g}"] = {"n": int(mk.sum()), "mean_realized": r3(float(Pc["R"][mk].mean()), 2),
                                             "ci95": [r3(float(np.percentile(mb, 2.5)), 2), r3(float(np.percentile(mb, 97.5)), 2)],
                                             "sign_rate": r3(float((Pc["R"][mk] > 0).mean()))}
        res["calibration_around_zero"] = cal
        print(kind, "calibration", json.dumps(cal))
        pos_out = {}
        for pos in SKILL:
            mk = P["pos"] == pos
            if mk.sum() < 200:
                continue
            sub = {k: v[mk] for k, v in P.items()}
            rp = gate_curves(sub, "R", 200)
            pos_out[pos] = {"n_pairs": rp["n_pairs"], "gate_80_logistic": rp["gate_80_logistic"],
                            "gate_80_ci95": rp["gate_80_ci95"], "realized_on_predicted": rp["realized_on_predicted"],
                            "best_gate_cost_0.5": rp["best_gate_by_cost"]["cost_0.5"]["best_gate"]}
        res["by_pos"] = pos_out
        print(kind, "by pos", json.dumps(pos_out))
        # Realistic pairs only: the 10 lowest-rated bench players and the 10
        # highest-rated wire players at each position and week.
        keep_rows = []
        for (_s2, _w2, pos_), grp in df.sort(["season", "week", "pos", "player_id"]).group_by(["season", "week", "pos"], maintain_order=True):
            lo_, hi_ = GATE_BENCH[str(pos_)]
            grp = grp.with_columns(pl.col("rank").fill_null(1e9).cast(pl.Float64).alias("rk"))
            bench = grp.filter((pl.col("rk") >= lo_) & (pl.col("rk") <= hi_) & (pl.col("n_after") >= 2) & (pl.col("rate") > 0)).sort("rate").head(10)
            wire = grp.filter((pl.col("rk") >= GATE_WIRE_FROM[str(pos_)]) & (pl.col("n_after") >= 2) & (pl.col("rate") > 0)).sort("rate", descending=True).head(10)
            keep_rows.append(pl.concat([bench, wire]).drop("rk"))
        real = gate_curves(gate_pairs(pl.concat(keep_rows)), "R", 300)
        res["realistic_pairs"] = real
        print(kind, "realistic", json.dumps({k: v for k, v in real.items() if k != "bins"}))
        if kind == "pre":
            # Controls: realized gaps replaced by the predicted gap plus noise of
            # the real residual spread must put the logistic 80% gate where the
            # normal formula does; both players' futures shuffled within each
            # slate must leave the sign rate flat near 50%.
            okr = np.isfinite(P["R"])
            slope = res["ppg_per_game_played"]["realized_on_predicted"]["slope"] or 1.0
            resid_sd = float(np.std(P["R"][okr] - slope * P["G"][okr]))
            planted = dict(P)
            planted["R"] = P["G"] + RNG.normal(0.0, resid_sd, P["G"].size)
            pc = gate_curves(planted, "R", 100)
            from scipy.stats import norm as _norm  # noqa: PLC0415

            shuffled_df = []
            for _key, grp in df.sort(["season", "week", "pos", "player_id"]).group_by(["season", "week", "pos"], maintain_order=True):
                fut = grp["ppg_after"].to_numpy().astype(float)
                shuffled_df.append(grp.with_columns(pl.Series("ppg_after", fut[RNG.permutation(fut.size)])))
            sc = gate_curves(gate_pairs(pl.concat(shuffled_df)), "R", 100)
            res["controls"] = {"planted_noise_sd": r3(resid_sd, 2), "planted_gate80": pc["gate_80_logistic"],
                               "planted_gate80_theory": r3(float(_norm.ppf(0.8)) * resid_sd, 2),
                               "shuffled_sign_rate_by_bin": {k: v["sign_rate"] for k, v in sc["bins"].items()},
                               "shuffled_gate80": sc["gate_80_logistic"]}
            print("controls", json.dumps(res["controls"]))
        out[f"prior_{kind}"] = res
    save("gate_r74", out)


# ---- R77: the backup QB/TE allowance ---------------------------------------------------

BACKUP_SEASONS = list(range(2016, 2026))
BACKUP_WEEKS = [6, 8, 10, 12]
PLAYOFF_WEEK_UNITS = {15: 2.0, 16: 10.7, 17: 11.7}   # swap-scan PLAYOFF_UNITS = 24.4, split as its comment gives it


def starter_misses(seasons: list[int]) -> pl.DataFrame:
    """One row per team, season, position (QB, TE) and decision week W: the
    starter (most offensive snaps over the team's last two games before W,
    and at least half the snaps in the latest one) and, for every later team
    game through week 17, whether he took an offensive snap. A miss is a team
    game with no offensive snap for him, so a benching counts as well as an
    injury: either way the backup starts."""
    import nflreadpy as nfl  # noqa: PLC0415

    ids = (nfl.load_ff_playerids().select(["pfr_id", "gsis_id"])
           .filter(pl.col("pfr_id").is_not_null() & pl.col("gsis_id").is_not_null()).unique("pfr_id"))
    rows = []
    for s in seasons:
        sc = (nfl.load_snap_counts(seasons=[s]).filter((pl.col("game_type") == "REG") & (pl.col("week") <= LAST_WEEK)
                                                     & pl.col("position").is_in(["QB", "TE"]))
              .select(["week", "team", "position", "pfr_player_id", "player", "offense_snaps", "offense_pct"])
              .with_columns(pl.col("team").replace(nflraw.TEAM_ESPN)))
        g = nflraw.games([s]).filter(pl.col("week") <= LAST_WEEK)
        sched = pl.concat([g.select(["week", pl.col("home").alias("team")]), g.select(["week", pl.col("away").alias("team")])])
        team_weeks = {t: sorted(int(w) for w in grp["week"].to_list()) for (t,), grp in sched.group_by(["team"])}
        played = {(r[0], int(r[1])) for r in sc.filter(pl.col("offense_snaps") > 0).select(["pfr_player_id", "week"]).iter_rows()}
        have = {(str(r[0]), int(r[1])) for r in sc.select(["team", "week"]).unique().iter_rows()}
        for (team, pos), grp in sc.group_by(["team", "position"]):
            weeks = team_weeks.get(str(team), [])
            for W in BACKUP_WEEKS:
                before = [w for w in weeks if w < W][-2:]
                if len(before) < 2:
                    continue
                last2 = grp.filter(pl.col("week").is_in(before))
                if last2.is_empty():
                    continue
                tot = last2.group_by(["pfr_player_id", "player"]).agg(pl.col("offense_snaps").sum()).sort(
                    ["offense_snaps", "pfr_player_id"], descending=[True, False])
                pid, name = tot.row(0)[0], tot.row(0)[1]
                latest = last2.filter((pl.col("week") == before[-1]) & (pl.col("pfr_player_id") == pid))
                if latest.is_empty() or float(latest["offense_pct"][0] or 0) < 0.5:
                    continue
                for w in weeks:
                    # Through 2020 week 17 closed the NFL season and teams rested
                    # starters; fantasy week 17 is no longer that week. A game
                    # with no snap rows for the team is missing data, not a miss.
                    if w <= W or (s <= 2020 and w == 17) or (str(team), w) not in have:
                        continue
                    rows.append({"season": s, "team": team, "pos": pos, "W": W, "pfr_id": pid, "name": name,
                                 "week": w, "missed": (pid, w) not in played})
    df = pl.DataFrame(rows)
    return df.join(ids, left_on="pfr_id", right_on="pfr_id", how="left")


def cmd_backup(args: argparse.Namespace) -> None:
    expect = ("Starting QBs miss about 8% of their remaining games and starting TEs about 10%; from week 6 that is "
              "about 0.7-0.9 regular-season games, and with the playoff weights the allowance is about 2-3 units, "
              "so 1 is too low.")
    print("EXPECT:", expect)
    allowance0 = tool_constant("swap-scan", "BACKUP_INJURY_WEEKS")
    units = tool_constant("swap-scan", "PLAYOFF_UNITS")
    reg_end = int(tool_constant("swap-scan", "REG_SEASON_END"))
    df = starter_misses(BACKUP_SEASONS)
    # Fantasy-relevant starters: top 13 at the position by PPG before W.
    pw = (nflraw.player_weeks(BACKUP_SEASONS).filter(pl.col("pos").is_in(["QB", "TE"]) & (pl.col("week") <= LAST_WEEK))
          .select(["season", "week", "player_id", "pos", "pts"]).with_columns(pl.col("season").cast(pl.Int64)))
    top = []
    for W in BACKUP_WEEKS:
        r = (pw.filter(pl.col("week") < W).group_by(["season", "player_id", "pos"]).agg(pl.col("pts").mean().alias("ppg"))
             .with_columns(pl.col("ppg").rank("ordinal", descending=True).over(["season", "pos"]).cast(pl.Int64).alias("rk"))
             .filter(pl.col("rk") <= 13).select(["season", "player_id", pl.lit(W).alias("W")]))
        top.append(r)
    topdf = pl.concat(top).with_columns(pl.lit(True).alias("top13"), pl.col("W").cast(pl.Int64))
    df = df.with_columns(pl.col("season").cast(pl.Int64), pl.col("W").cast(pl.Int64)).join(
        topdf, left_on=["season", "gsis_id", "W"], right_on=["season", "player_id", "W"], how="left").with_columns(
        pl.col("top13").fill_null(False))
    out: dict[str, Any] = {"expect": expect, "rule_in_tool": {"BACKUP_INJURY_WEEKS": allowance0, "PLAYOFF_UNITS": units},
                           "playoff_week_units": PLAYOFF_WEEK_UNITS, "results": {}}
    for subset in ("all_starters", "top13_fantasy"):
        for pos in ("QB", "TE"):
            for W in BACKUP_WEEKS:
                d = df.filter((pl.col("pos") == pos) & (pl.col("W") == W))
                if subset == "top13_fantasy":
                    d = d.filter(pl.col("top13"))
                if d.is_empty():
                    continue
                key = (d["season"].cast(pl.Utf8) + "|" + d["team"]).to_numpy()
                miss = d["missed"].to_numpy().astype(float)
                wk = d["week"].to_numpy()
                m, lo, hi = cluster_boot_mean(miss, key, 1000)
                reg = wk <= reg_end
                po = ~reg
                # Expected misses per starter: regular weeks after W, and the playoff weeks in units.
                per = d.group_by(["season", "team"]).agg(
                    pl.col("missed").filter(pl.col("week") <= reg_end).sum().alias("reg_miss"),
                    (pl.col("week") <= reg_end).sum().alias("reg_games"),
                    pl.col("missed").filter(pl.col("week") > reg_end).sum().alias("po_miss"))
                p_week = {}
                for w_ in range(W + 1, LAST_WEEK + 1):
                    mk = wk == w_
                    if mk.sum():
                        p_week[w_] = float(miss[mk].mean())
                po_units = sum(p_week.get(w_, m) * u for w_, u in PLAYOFF_WEEK_UNITS.items())
                reg_exp = float(per["reg_miss"].mean() or 0.0)  # pyright: ignore[reportArgumentType]
                boot = []
                ukey, inv = np.unique(key, return_inverse=True)
                for _ in range(500):
                    wts = np.bincount(RNG.integers(0, ukey.size, ukey.size), minlength=ukey.size)[inv].astype(float)
                    pr_ = (wts[reg] @ miss[reg]) / max(wts[reg].sum(), 1e-9) * float(reg.sum()) / ukey.size
                    pp_ = sum(((wts[wk == w_] @ miss[wk == w_]) / max(wts[wk == w_].sum(), 1e-9)) * u for w_, u in PLAYOFF_WEEK_UNITS.items())
                    boot.append(pr_ + pp_)
                dist = per["reg_miss"].to_numpy() + per["po_miss"].to_numpy()
                out["results"][f"{subset}|{pos}|W{W}"] = {
                    "starters": int(ukey.size), "games_after_W": int(miss.size),
                    "miss_rate_per_game": r3(m), "ci95": [r3(lo), r3(hi)],
                    "miss_rate_regular": r3(float(miss[reg].mean()) if reg.any() else None),
                    "miss_rate_playoff_weeks": r3(float(miss[po].mean()) if po.any() else None),
                    "expected_regular_misses": r3(reg_exp, 2),
                    "expected_playoff_misses": r3(float(per["po_miss"].mean() or 0.0), 2),  # pyright: ignore[reportArgumentType]
                    "miss_rate_by_playoff_week": {str(k): r3(v) for k, v in p_week.items() if k > reg_end},
                    "allowance_games": r3(reg_exp + float(per["po_miss"].mean() or 0.0), 2),  # pyright: ignore[reportArgumentType]
                    "allowance_units": r3(reg_exp + po_units, 2),
                    "allowance_units_ci95": [r3(float(np.percentile(boot, 2.5)), 2), r3(float(np.percentile(boot, 97.5)), 2)],
                    "share_missing_0_1_2_3plus": [r3(float(np.mean(dist == k)), 3) for k in (0, 1, 2)] + [r3(float(np.mean(dist >= 3)), 3)]}
                print(subset, pos, W, json.dumps(out["results"][f"{subset}|{pos}|W{W}"]))
    save("backup_r77", out)


# ---- R75 / R90: one-week against two-week role reads ---------------------------------------

ROLE_SEASONS = list(range(2019, 2026))
ROLE_UP = {"snap": 0.15, "share": 0.08, "opps": 5.0}     # bin/volume ROLE-UP thresholds
ROLE_AHEAD = 3                                            # games after the read that are the outcome


def role_games() -> pl.DataFrame:
    """One row per player-game (RB, WR, TE), 2019-2025 weeks 1-17: offensive
    snap share (PFR snap counts), target share, and RB opportunities
    (carries + 1.5 x targets), the three inputs of bin/volume's ROLE flags."""
    import nflreadpy as nfl  # noqa: PLC0415

    ids = (nfl.load_ff_playerids().select(["pfr_id", "gsis_id"])
           .filter(pl.col("pfr_id").is_not_null() & pl.col("gsis_id").is_not_null()).unique("pfr_id"))
    snaps = []
    for s in ROLE_SEASONS:
        sc = (nfl.load_snap_counts(seasons=[s]).filter((pl.col("game_type") == "REG") & (pl.col("week") <= LAST_WEEK))
              .select(["season", "week", "pfr_player_id", "offense_pct"]))
        snaps.append(sc.join(ids, left_on="pfr_player_id", right_on="pfr_id", how="inner")
                     .select([pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64), "gsis_id",
                              pl.col("offense_pct").alias("snap")]))
    sn = pl.concat(snaps).group_by(["season", "week", "gsis_id"]).agg(pl.col("snap").max())
    pw = (nflraw.player_weeks(ROLE_SEASONS).filter(pl.col("pos").is_in(["RB", "WR", "TE"]) & (pl.col("week") <= LAST_WEEK))
          .select(["season", "week", "player_id", "pos", "targets", "carries", "target_share"])
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    return (pw.join(sn, left_on=["season", "week", "player_id"], right_on=["season", "week", "gsis_id"], how="left")
            .with_columns((pl.col("carries").fill_null(0) + 1.5 * pl.col("targets").fill_null(0)).alias("opps"),
                          pl.col("target_share").alias("share"))
            .sort(["season", "player_id", "week"]))


def role_reads(games: pl.DataFrame) -> pl.DataFrame:
    """Every decision point after a player's k-th game of a season (k >= 2):
    the one-week read (bin/volume: last game against the mean of all earlier
    games) and the two-week read (each of the last two games against the
    mean of the games before them), and the mean of the next ROLE_AHEAD games."""
    out = []
    for (season, pid), g in games.group_by(["season", "player_id"], maintain_order=True):
        pos = g["pos"][-1]
        wk = g["week"].to_numpy()
        X = {m: g[m].to_numpy().astype(float) for m in ("snap", "share", "opps")}
        n = wk.size
        for k in range(1, n - ROLE_AHEAD):
            nxt = slice(k + 1, k + 1 + ROLE_AHEAD)
            if wk[k + ROLE_AHEAD] - wk[k] > ROLE_AHEAD + 2:      # a long absence: not "the next three weeks"
                continue
            row = {"season": season, "player_id": pid, "pos": pos, "week": int(wk[k]), "k": k}
            for m, x in X.items():
                prior = x[:k]
                pm = np.nanmean(prior) if np.isfinite(prior).any() else np.nan
                row[f"{m}_prior"] = pm
                row[f"{m}_last"] = x[k]
                fut = x[nxt]
                row[f"{m}_next"] = np.nanmean(fut) if np.isfinite(fut).any() else np.nan
                if k >= 2:
                    base2 = x[:k - 1]
                    b2 = np.nanmean(base2) if np.isfinite(base2).any() else np.nan
                    row[f"{m}_base2"] = b2
                    row[f"{m}_prev"] = x[k - 1]
                else:
                    row[f"{m}_base2"] = np.nan
                    row[f"{m}_prev"] = np.nan
            out.append(row)
    # NaN -> null: polars orders NaN above every number, so `x - NaN >= 0.15`
    # is true and a read with no baseline would count as a role change.
    df = pl.DataFrame(out, infer_schema_length=None).fill_nan(None)

    def up1(m: str) -> pl.Expr:
        return (pl.col(f"{m}_last") - pl.col(f"{m}_prior")) >= ROLE_UP[m]

    def up2(m: str) -> pl.Expr:
        return (((pl.col(f"{m}_last") - pl.col(f"{m}_base2")) >= ROLE_UP[m])
                & ((pl.col(f"{m}_prev") - pl.col(f"{m}_base2")) >= ROLE_UP[m]))

    wrte = pl.col("pos").is_in(["WR", "TE"])
    rb = pl.col("pos") == "RB"
    return df.with_columns(
        (up1("snap").fill_null(False) | (wrte & up1("share").fill_null(False)) | (rb & up1("opps").fill_null(False))).alias("flag1"),
        (up2("snap").fill_null(False) | (wrte & up2("share").fill_null(False)) | (rb & up2("opps").fill_null(False))).alias("flag2"),
        up1("snap").fill_null(False).alias("flag1_snap"), up2("snap").fill_null(False).alias("flag2_snap"))


def persistence_slope(d_last: np.ndarray, d_next: np.ndarray, who: np.ndarray, n: int = 500) -> dict:
    """Share of a change that persists: OLS slope of (next - baseline) on (read - baseline), player bootstrap."""
    ok = np.isfinite(d_last) & np.isfinite(d_next)
    x, y, who = d_last[ok], d_next[ok], who[ok]
    b = np.polyfit(x, y, 1)[0] if x.size > 10 else float("nan")
    _, idx = np.unique(who, return_inverse=True)
    k = int(idx.max()) + 1
    groups = [np.flatnonzero(idx == i) for i in range(k)]
    boots = []
    for _ in range(n):
        pick = np.concatenate([groups[i] for i in RNG.integers(0, k, size=k)])
        boots.append(np.polyfit(x[pick], y[pick], 1)[0])
    return {"n": int(x.size), "slope": r3(float(b)), "ci95": [r3(float(np.percentile(boots, 2.5))), r3(float(np.percentile(boots, 97.5)))]}


def flag_vs_matched(df: pl.DataFrame, flag: str, metric: str, base: str, width: float) -> dict:
    """Next-3-game mean of `metric` for flagged reads minus matched unflagged
    reads (same season, week and position, baseline within +-width), and the
    share of the flagged jump that is still there."""
    keys = (df["season"].cast(pl.Utf8) + "|" + df["week"].cast(pl.Utf8) + "|" + df["pos"]).to_numpy()
    fl = df[flag].to_numpy()
    b = df[f"{metric}_{base}"].fill_null(float("nan")).to_numpy().astype(float)
    last = df[f"{metric}_last"].fill_null(float("nan")).to_numpy().astype(float)
    prev = df[f"{metric}_prev"].fill_null(float("nan")).to_numpy().astype(float)
    nxt = df[f"{metric}_next"].fill_null(float("nan")).to_numpy().astype(float)
    pid = df["player_id"].to_numpy()
    idx_by: dict[str, np.ndarray] = {}
    for k in np.unique(keys):
        idx_by[k] = np.flatnonzero(keys == k)
    eff, jump, kept, who = [], [], [], []
    for i in np.flatnonzero(fl & np.isfinite(b) & np.isfinite(nxt) & np.isfinite(last)):
        grp = idx_by[keys[i]]
        ctrl = grp[(~fl[grp]) & np.isfinite(nxt[grp]) & np.isfinite(b[grp]) & (np.abs(b[grp] - b[i]) <= width)]
        if ctrl.size == 0:
            continue
        read = last[i] if base == "prior" else np.nanmean([last[i], prev[i]])
        eff.append(nxt[i] - nxt[ctrl].mean())
        jump.append(read - b[i])
        kept.append(nxt[i] - b[i])
        who.append(pid[i])
    if not eff:
        return {"n": 0}
    e, j, kp, wh = np.array(eff), np.array(jump), np.array(kept), np.array(who)
    m, lo, hi = cluster_boot_mean(e, wh, 1000)
    return {"n": int(e.size), "players": int(np.unique(wh).size), "mean_jump": r3(float(j.mean())),
            "mean_next_minus_baseline": r3(float(kp.mean())),
            "next_vs_matched_unflagged": r3(m), "ci95": [r3(lo), r3(hi)],
            "share_of_jump_kept_vs_matched": r3(m / float(j.mean())) if j.mean() else None}


def cmd_role(args: argparse.Namespace) -> None:
    expect = ("About half of a one-week snap-share jump persists into the next three games (slope about 0.5) and "
              "about two thirds of a two-week one; the one-week flag carries signal, so 'one week is noise' is wrong, "
              "but the two-week read is the stronger one.")
    print("EXPECT:", expect)
    games = role_games()
    df = role_reads(games)
    out: dict[str, Any] = {"expect": expect, "thresholds": ROLE_UP, "reads": int(df.height), "seasons": ROLE_SEASONS,
                           "outcome": f"mean over the next {ROLE_AHEAD} games played"}
    who = df["player_id"].to_numpy()
    slopes = {}
    for metric, pos_set in (("snap", ("RB", "WR", "TE")), ("share", ("WR", "TE")), ("opps", ("RB",))):
        mk = df["pos"].is_in(list(pos_set)).to_numpy()
        prior = df[f"{metric}_prior"].fill_null(float("nan")).to_numpy().astype(float)
        last = df[f"{metric}_last"].fill_null(float("nan")).to_numpy().astype(float)
        nxt = df[f"{metric}_next"].fill_null(float("nan")).to_numpy().astype(float)
        b2 = df[f"{metric}_base2"].fill_null(float("nan")).to_numpy().astype(float)
        prev = df[f"{metric}_prev"].fill_null(float("nan")).to_numpy().astype(float)
        one = persistence_slope((last - prior)[mk], (nxt - prior)[mk], who[mk])
        two = persistence_slope((0.5 * (last + prev) - b2)[mk], (nxt - b2)[mk], who[mk])
        # Same reads, the last game alone against the older baseline, so the
        # two windows are compared on the same rows (k >= 2).
        one_same = persistence_slope((last - b2)[mk & np.isfinite(b2)], (nxt - b2)[mk & np.isfinite(b2)], who[mk & np.isfinite(b2)])
        # Controls: the read shuffled within position-week gives about 0; a planted
        # persistence of 0.5 comes back as about 0.5.
        sh = df.with_columns(pl.col(f"{metric}_last").shuffle(seed=5).over(["season", "week", "pos"]).alias("s_last"))
        s_last = sh["s_last"].fill_null(float("nan")).to_numpy().astype(float)
        ctrl_shuf = persistence_slope((s_last - prior)[mk], (nxt - prior)[mk], who[mk], 200)
        planted_next = prior + 0.5 * (last - prior) + RNG.normal(0, float(np.nanstd(nxt - prior)), prior.size)
        ctrl_plant = persistence_slope((last - prior)[mk], (planted_next - prior)[mk], who[mk], 200)
        slopes[metric] = {"one_week": one, "two_week_mean": two, "one_week_same_rows_vs_older_base": one_same,
                          "control_shuffled_read": ctrl_shuf, "control_planted_0.5": ctrl_plant}
        print(metric, json.dumps(slopes[metric]))
    out["persistence_slopes"] = slopes
    flags = {}
    for flag, base in (("flag1", "prior"), ("flag2", "base2"), ("flag1_snap", "prior"), ("flag2_snap", "base2")):
        res = {}
        for metric, pos_set, width in (("snap", ("RB", "WR", "TE"), 0.05), ("share", ("WR", "TE"), 0.03), ("opps", ("RB",), 1.5)):
            sub = df.filter(pl.col("pos").is_in(list(pos_set)))
            res[metric] = flag_vs_matched(sub, flag, metric, base, width)
        flags[flag] = {"n_flagged": int(df[flag].sum()), "share_of_reads": r3(float(df[flag].mean() or 0.0)), "vs_matched": res}  # pyright: ignore[reportArgumentType]
        print(flag, json.dumps(flags[flag]))
    out["flags"] = flags
    # Of the one-week flags, how many does the next game confirm (a two-week read one game later)?
    conf = {}
    for metric in ("snap", "share", "opps"):
        f1 = df.filter((pl.col(f"{metric}_last") - pl.col(f"{metric}_prior")) >= ROLE_UP[metric]).select(
            ["season", "player_id", "k", f"{metric}_prior"])
        nx = df.select(["season", "player_id", (pl.col("k") - 1).alias("k"), pl.col(f"{metric}_last").alias("x_next_game")])
        j = f1.join(nx, on=["season", "player_id", "k"], how="inner")
        ok = (j["x_next_game"] - j[f"{metric}_prior"]) >= ROLE_UP[metric]
        conf[metric] = {"one_week_reads": int(j.height), "confirmed_next_game": r3(float(ok.mean() or 0.0))}  # pyright: ignore[reportArgumentType]
    out["one_week_flags_confirmed_next_game"] = conf
    print("confirmed", json.dumps(conf))
    save("role_r75_r90", out)


# ---- R89: a population prior yields to the player's own ratio -------------------------------

OWN_FIT = [2022, 2023]
OWN_TEST = [2024, 2025]
OWN_WEIGHTS = [0.0, 0.25, 0.5, 0.75, 1.0]


def own_frame() -> pl.DataFrame:
    """Played player-weeks 2022-2025 (QB/RB/WR/TE) with Sleeper's projection on
    league points, the projected and actual opportunities (targets + carries,
    plus pass attempts for QB), and the projection tier."""
    sl = (nflraw.sleeper_weeks(OWN_FIT + OWN_TEST).filter(pl.col("pos").is_in(SKILL) & (pl.col("proj") > 0)
                                                        & pl.col("gsis_id").is_not_null() & (pl.col("week") <= LAST_WEEK))
          .group_by(["season", "week", "gsis_id"]).agg(pl.col("proj").max(), pl.col("proj_tgt").max(),
                                                       pl.col("proj_rush_att").max(), pl.col("proj_pass_att").max())
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    pw = (nflraw.player_weeks(OWN_FIT + OWN_TEST).filter(pl.col("pos").is_in(SKILL) & (pl.col("week") <= LAST_WEEK))
          .select(["season", "week", "player_id", "pos", "pts", "targets", "carries", "attempts"])
          .with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64)))
    f = pw.join(sl, left_on=["season", "week", "player_id"], right_on=["season", "week", "gsis_id"], how="inner")
    qb = pl.col("pos") == "QB"
    return f.with_columns(
        (pl.col("targets").fill_null(0) + pl.col("carries").fill_null(0)
         + pl.when(qb).then(pl.col("attempts").fill_null(0)).otherwise(0)).alias("opp"),
        (pl.col("proj_tgt").fill_null(0) + pl.col("proj_rush_att").fill_null(0)
         + pl.when(qb).then(pl.col("proj_pass_att").fill_null(0)).otherwise(0)).alias("opp_proj"),
        pl.when(pl.col("proj") < 7).then(pl.lit("0-7")).when(pl.col("proj") < 13).then(pl.lit("7-13"))
        .otherwise(pl.lit("13+")).alias("tier"),
    ).sort(["season", "player_id", "week"])


def cmd_ownratio(args: argparse.Namespace) -> None:
    expect = ("Blending the 3-week own ratio helps little: for volume-confirmed over-performers the next-week MAE "
              "falls by 0.1-0.3 at a weight of 0.25-0.5 and rises at 1.0; for TD-driven streaks it does not help.")
    print("EXPECT:", expect)
    f = own_frame()
    fit = f.filter(pl.col("season").is_in(OWN_FIT))
    tm = {(str(a), str(b)): float(c) for a, b, c in
          fit.group_by(["pos", "tier"]).agg((pl.col("pts") / pl.col("proj")).median().alias("m")).iter_rows()}
    rows = []
    for (season, pid), g in f.filter(pl.col("season").is_in(OWN_TEST)).group_by(["season", "player_id"], maintain_order=True):
        wk = g["week"].to_numpy()
        pts = g["pts"].to_numpy().astype(float)
        proj = g["proj"].to_numpy().astype(float)
        opp = g["opp"].to_numpy().astype(float)
        oppp = g["opp_proj"].to_numpy().astype(float)
        pos = g["pos"].to_numpy()
        tier = g["tier"].to_numpy()
        for t in range(3, wk.size):
            if wk[t] - wk[t - 3] > 5:                # three recent games, not a stale streak
                continue
            ref = np.array([tm[(str(pos[i]), str(tier[i]))] for i in range(t - 3, t)])
            r = pts[t - 3:t] / proj[t - 3:t]
            over, under = bool(np.all(r > ref)), bool(np.all(r < ref))
            vol_up = opp[t - 3:t].sum() > oppp[t - 3:t].sum()
            vol_dn = opp[t - 3:t].sum() < oppp[t - 3:t].sum()
            rows.append({"season": season, "player_id": pid, "pos": pos[t], "week": int(wk[t]), "proj": proj[t],
                         "actual": pts[t], "tm": tm[(str(pos[t]), str(tier[t]))],
                         "own": float(np.clip(pts[t - 3:t].sum() / proj[t - 3:t].sum(), 0.2, 3.0)),
                         "group": ("over_volume" if over and vol_up else "under_volume" if under and vol_dn
                                   else "over_no_volume" if over else "under_no_volume" if under else "mixed")})
    d = pl.DataFrame(rows)
    out: dict[str, Any] = {"expect": expect, "tier_medians_2022_2023": {f"{a} {b}": r3(v) for (a, b), v in sorted(tm.items())},
                           "rows_2024_2025": int(d.height), "groups": {}}
    for grp in ("over_volume", "under_volume", "over_no_volume", "under_no_volume", "mixed"):
        g = d.filter(pl.col("group") == grp)
        if g.height < 30:
            continue
        a = g["actual"].to_numpy()
        pj = g["proj"].to_numpy()
        tmv = g["tm"].to_numpy()
        own = g["own"].to_numpy()
        who = g["player_id"].to_numpy()
        base = pj * tmv
        res: dict[str, Any] = {"n": int(g.height), "players": int(np.unique(who).size),
                               "mean_own_ratio": r3(float(own.mean())), "mean_tier_median": r3(float(tmv.mean())),
                               "next_week_actual_over_proj": r3(float(a.sum() / pj.sum())), "by_weight": {}}
        for w in OWN_WEIGHTS:
            m = pj * ((1 - w) * tmv + w * own)
            dm, lo, hi = cluster_boot_mean(np.abs(a - m) - np.abs(a - base), who, 1000)
            res["by_weight"][str(w)] = {"mae": r3(float(np.mean(np.abs(a - m))), 2), "median_ae": r3(float(np.median(np.abs(a - m))), 2),
                                        "mean_error": r3(float(np.mean(a - m)), 2), "share_above_median": r3(float(np.mean(a > m))),
                                        "mae_minus_tier_median": r3(dm, 3), "ci95": [r3(lo, 3), r3(hi, 3)]}
        # The lean that would put half the outcomes above the median, and what
        # it is worth: fitted on 2024, scored on 2025 (one season each way).
        lean = a / (pj * tmv)
        res["median_lean_needed"] = r3(float(np.median(lean)))
        seas = g["season"].to_numpy()
        lean_oos = {}
        for fit_s, test_s in ((2024, 2025), (2025, 2024)):
            c = float(np.median(lean[seas == fit_s])) if (seas == fit_s).sum() >= 20 else 1.0
            mk = seas == test_s
            if mk.sum() < 20:
                continue
            dm2, lo2, hi2 = cluster_boot_mean(np.abs(a[mk] - c * base[mk]) - np.abs(a[mk] - base[mk]), who[mk], 500)
            lean_oos[f"fit {fit_s} test {test_s}"] = {"lean": r3(c), "mae_change": r3(dm2, 3), "ci95": [r3(lo2, 3), r3(hi2, 3)]}
        res["median_lean_out_of_season"] = lean_oos
        # Control: the own ratio shuffled across the group's rows must not help.
        sh = RNG.permutation(own)
        msh = pj * (0.5 * tmv + 0.5 * sh)
        dsh, slo, shi = cluster_boot_mean(np.abs(a - msh) - np.abs(a - base), who, 500)
        res["control_shuffled_own_w0.5"] = {"mae_minus_tier_median": r3(dsh, 3), "ci95": [r3(slo, 3), r3(shi, 3)]}
        out["groups"][grp] = res
        print(grp, json.dumps(res))
    save("ownratio_r89", out)


# ---- R88: the review alarms -----------------------------------------------------------------

ALARM_WEEKS = 16            # settled forecast weeks in a season (17 weeks, one idle week)
ALARM_SIMS = 60_000


def season_rate(fired: np.ndarray, first_check: int) -> float:
    """Share of simulated seasons where an alarm fires at any check from `first_check` (1-based week)."""
    return float(fired[:, first_check - 1:].any(axis=1).mean())


def cmd_alarms(args: argparse.Namespace) -> None:
    from scipy.stats import binom  # noqa: PLC0415

    expect = ("Per week, 50% coverage on 16 lines falls outside 0.35-0.65 about 21% of the time, so 'three weeks' fires "
              "often by chance unless the weeks must be consecutive and in one direction; a middle slice over 30% "
              "fires very often early in the season.")
    print("EXPECT:", expect)
    out: dict[str, Any] = {"expect": expect, "assumption": "calibrated forecaster, independent lines (binomial), "
                           f"{ALARM_WEEKS} settled weeks a season", "coverage": {}, "slices": {}}
    for n in (12, 14, 16, 18, 20):
        lo_k = math.ceil(0.35 * n) - 1          # count strictly under 0.35 of n
        hi_k = math.floor(0.65 * n) + 1         # count strictly over 0.65 of n
        p_lo = float(binom.cdf(lo_k, n, 0.5))
        p_hi = float(binom.sf(hi_k - 1, n, 0.5))
        X = RNG.binomial(n, 0.5, size=(ALARM_SIMS, ALARM_WEEKS))
        low, high = X <= lo_k, X >= hi_k
        out_ = low | high
        # (a) three consecutive weeks under, or three consecutive weeks over
        a = np.zeros_like(low)
        b = np.zeros_like(low)
        c = np.zeros_like(low)
        d = np.zeros_like(low)
        for t in range(2, ALARM_WEEKS):
            a[:, t] = (low[:, t - 2] & low[:, t - 1] & low[:, t]) | (high[:, t - 2] & high[:, t - 1] & high[:, t])
            b[:, t] = out_[:, t - 2] & out_[:, t - 1] & out_[:, t]
            pooled = X[:, t - 2:t + 1].sum(axis=1) / (3 * n)
            c[:, t] = (pooled < 0.35) | (pooled > 0.65)
        cum_low = np.cumsum(low, axis=1)
        cum_high = np.cumsum(high, axis=1)
        d = (cum_low >= 3) | (cum_high >= 3)
        out["coverage"][str(n)] = {
            "p_week_under_0.35": r3(p_lo, 4), "p_week_over_0.65": r3(p_hi, 4),
            "season_rate": {"3 consecutive weeks, same side": r3(season_rate(a, 3)),
                            "3 consecutive weeks, either side": r3(season_rate(b, 3)),
                            "trailing 3-week pooled coverage outside": r3(season_rate(c, 3)),
                            "any 3 weeks of the season on one side": r3(season_rate(d, 3))}}
        print("coverage", n, json.dumps(out["coverage"][str(n)]))
    # Replacements for the coverage rule at 16 lines: season-to-date coverage
    # outside 0.5 +- z x sqrt(0.25 / lines), checked weekly from week 3.
    n = 16
    X = RNG.binomial(n, 0.5, size=(ALARM_SIMS, ALARM_WEEKS))
    cum = np.cumsum(X, axis=1)
    lines = n * np.arange(1, ALARM_WEEKS + 1)
    z = (cum / lines - 0.5) / np.sqrt(0.25 / lines)
    repl = {}
    for zc in (2.0, 2.5, 2.8, 3.0):
        repl[f"season-to-date |z| > {zc}"] = r3(season_rate(np.abs(z) > zc, 3))
    trailing = {}
    for band in (0.30, 0.25):
        fired = np.zeros((ALARM_SIMS, ALARM_WEEKS), dtype=bool)
        for t in range(2, ALARM_WEEKS):
            pooled = X[:, t - 2:t + 1].sum(axis=1) / (3 * n)
            fired[:, t] = (pooled < band) | (pooled > 1 - band)
        trailing[f"trailing 3-week pooled coverage outside {band:g}-{1 - band:g}"] = r3(season_rate(fired, 3))
    out["coverage_replacements_16_lines"] = {**repl, **trailing}
    print("coverage replacements", json.dumps(out["coverage_replacements_16_lines"]))
    # Landing slices: forecast history prints the season-to-date histogram.
    from ffmodel.score import PIT_EXPECTED  # noqa: PLC0415 -- the live slice shares

    pexp = np.array(PIT_EXPECTED)
    for n in (16,):
        M = RNG.multinomial(n, pexp, size=(ALARM_SIMS, ALARM_WEEKS))      # sims x weeks x 6
        C = np.cumsum(M, axis=1)
        share = C / (n * np.arange(1, ALARM_WEEKS + 1))[None, :, None]
        week_share = M / n
        mid = share[:, :, 2:4].max(axis=2) > 0.30
        anyslice = share.max(axis=2) > 0.30
        week_mid = week_share[:, :, 2:4].max(axis=2) > 0.30
        rates = {"season-to-date, a middle slice over 30%, checked from week 1": r3(season_rate(mid, 1)),
                 "season-to-date, a middle slice over 30%, checked from week 3": r3(season_rate(mid, 3)),
                 "season-to-date, any slice over 30%, from week 1": r3(season_rate(anyslice, 1)),
                 "one week's 16 lines, a middle slice over 30%, per week": r3(float(week_mid.mean())),
                 "one week's 16 lines, a middle slice over 30%, any week of the season": r3(season_rate(week_mid, 1)),
                 "season-to-date, a middle slice over 30% at week 8": r3(float(mid[:, 7].mean())),
                 "season-to-date, a middle slice over 30% at week 16": r3(float(mid[:, 15].mean()))}
        # Replacement: a chi-square test of the season-to-date six-slice row.
        from scipy.stats import chi2  # noqa: PLC0415

        exp_counts = (n * np.arange(1, ALARM_WEEKS + 1))[None, :, None] * pexp[None, None, :]
        stat = ((C - exp_counts) ** 2 / exp_counts).sum(axis=2)
        for alpha in (0.01, 0.005, 0.002):
            crit = float(chi2.ppf(1 - alpha, 5))
            rates[f"chi-square of the six slices, weekly alpha {alpha:g} (stat > {crit:.1f}), from week 4"] = r3(season_rate(stat > crit, 4))
        for thr in (0.32, 0.35):
            for start in (4, 6):
                fired = share[:, :, 2:4].max(axis=2) > thr
                rates[f"season-to-date middle slice over {thr:.0%}, from week {start}"] = r3(season_rate(fired, start))
        out["slices"][str(n)] = rates
        print("slices", n, json.dumps(rates))
        del M, C, share
    save("alarms_r88", out)


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
    p = sub.add_parser("gate", help="R74: the swap-scan waiver gate")
    p.add_argument("--ecr", help="local copy of db_fpecr.parquet (default: download to a temp dir)")
    sub.add_parser("backup", help="R77: games a starting QB/TE misses (backup allowance)")
    sub.add_parser("role", help="R75/R90: one-week against two-week role reads")
    sub.add_parser("ownratio", help="R89: blend a 3-week own ratio into the tier median")
    sub.add_parser("alarms", help="R88: false-alarm rates of the review signals")
    args = ap.parse_args(argv)
    {"ros": cmd_ros, "spread": cmd_spread, "dst": cmd_dst, "k": cmd_k, "flags": cmd_flags,
     "gate": cmd_gate, "backup": cmd_backup, "role": cmd_role, "ownratio": cmd_ownratio,
     "alarms": cmd_alarms}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
