#!/usr/bin/env python3
"""role_eval: does the role model (ffmodel.role) earn a vote?

Walk-forward test. Seasons 2022-2025, weeks 4-17, QB/RB/WR/TE player-games
that were played and have a Sleeper projection. For each test season S the
role model is fitted on 2019..S-1 (2018 feeds the carry-over into 2019) and
projects each week of S from earlier games only.

Sources
  sleeper   Sleeper's archived weekly projection on league scoring
  role      ffmodel.role, three variants: base (snap share, the live one),
            routes (pass-play participation, historical only), plain (no
            participation)
  market    ffmodel.market on 2024-2025 rows with lines, fitted on the other
            priced season (as market.evaluate does)
  blends    convex weights per position, fitted by MAE on the other test
            seasons (for market blends, the other priced season), and the
            equal-weight means

Uncertainty: paired differences of absolute error and of RMSE, with 95%
intervals from a bootstrap that resamples whole clusters. Two clusterings
(player, NFL week); `ci` is the union of the two intervals, so it is the
wider.

Controls
  positive  Sleeper against the season-to-date average; a planted source
            0.9 x Sleeper + 0.1 x actual against Sleeper; and two planted
            sources at the role model's MAE added to the Sleeper+market
            blend: actual + noise (strong) and 0.9 x Sleeper + 0.1 x actual
            + noise (weak)
  negative  a planted source with no new information (Sleeper + noise, at
            the role model's MAE) added to the same blend
  leakage   week_projection() on data cut at the week equals the vectorized
            projection used here, for sampled weeks; and changing every box
            score from the week on leaves that week's projections unchanged

Verdict rule, fixed before the run: the role model becomes a vote only if
adding it to the Sleeper+market blend lowers MAE with a 95% interval that
excludes zero.

    python3 research/role_eval.py           # writes research/out/role_eval.json

INVARIANTS
- Read-only on everything but research/out/role_eval.json.
- No fitted number sees its test season: role.fit trains on seasons before
  S; blend weights and the market model train on other seasons.
- Deterministic: one seeded generator, frames sorted before any draw.
- One Python process; one season of play-by-play or participation in
  memory at a time (role.load reads them one by one).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from itertools import combinations_with_replacement
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

FANTASY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FANTASY))

from ffmodel import market, nflraw, role  # noqa: E402

OUT = FANTASY / "research" / "out" / "role_eval.json"
TEST = (2022, 2023, 2024, 2025)
PRICED = (2024, 2025)
DATA = tuple(range(2018, 2026))
WEEKS = (4, 17)
BOOT = 2000
SEED = 20261015
RNG = np.random.default_rng(SEED)
POS = role.POS
RELEVANT = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}   # top-N by Sleeper's projection, per week


def r3(x: Any) -> Any:
    if x is None:
        return None
    x = float(x)
    return round(x, 3) if np.isfinite(x) else None


# ---- bootstrap ------------------------------------------------------------------

def _boot(stat_sums: list[np.ndarray], clusters: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cluster-level sums of each per-row array, and the bootstrap weight
    matrix (BOOT x clusters) from resampling whole clusters."""
    _, idx = np.unique(clusters, return_inverse=True)
    k = int(idx.max()) + 1
    w = RNG.multinomial(k, np.full(k, 1.0 / k), size=BOOT).astype(float)
    sums = np.vstack([np.bincount(idx, weights=s, minlength=k) for s in stat_sums])
    return sums, w


def paired(a: np.ndarray, b: np.ndarray, y: np.ndarray, groups: dict[str, np.ndarray]) -> dict:
    """a against b on the same rows: MAE and RMSE of each, the difference
    (a - b; negative = a better) and its 95% interval per clustering."""
    ea, eb = a - y, b - y
    d = np.abs(ea) - np.abs(eb)
    out: dict = {"n": int(y.size), "mae_a": r3(np.abs(ea).mean()), "mae_b": r3(np.abs(eb).mean()),
                 "rmse_a": r3(np.sqrt((ea ** 2).mean())), "rmse_b": r3(np.sqrt((eb ** 2).mean())),
                 "d_mae": r3(d.mean()), "d_rmse": r3(np.sqrt((ea ** 2).mean()) - np.sqrt((eb ** 2).mean()))}
    lo_m, hi_m, lo_r, hi_r = [], [], [], []
    for name, cl in groups.items():
        sums, w = _boot([d, ea ** 2, eb ** 2, np.ones(y.size)], cl)
        tot = w @ sums.T                       # BOOT x 4
        cnt = np.maximum(tot[:, 3], 1e-12)
        bm = tot[:, 0] / cnt
        br = np.sqrt(tot[:, 1] / cnt) - np.sqrt(tot[:, 2] / cnt)
        ci_m = (float(np.percentile(bm, 2.5)), float(np.percentile(bm, 97.5)))
        ci_r = (float(np.percentile(br, 2.5)), float(np.percentile(br, 97.5)))
        out[f"ci_mae_{name}"] = [r3(ci_m[0]), r3(ci_m[1])]
        out[f"ci_rmse_{name}"] = [r3(ci_r[0]), r3(ci_r[1])]
        lo_m.append(ci_m[0]); hi_m.append(ci_m[1]); lo_r.append(ci_r[0]); hi_r.append(ci_r[1])
    out["ci_mae"] = [r3(min(lo_m)), r3(max(hi_m))]
    out["ci_rmse"] = [r3(min(lo_r)), r3(max(hi_r))]
    out["mae_gain_excludes_zero"] = bool(max(hi_m) < 0)
    return out


# ---- blends -----------------------------------------------------------------------

def simplex(k: int, step: float = 0.05) -> np.ndarray:
    n = round(1 / step)
    pts = [np.bincount(np.array(c, dtype=int), minlength=k) / n for c in combinations_with_replacement(range(k), n)]
    return np.unique(np.array(pts), axis=0)


def fit_convex(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    grid = simplex(x.shape[1])
    m = np.abs(x @ grid.T - y[:, None]).mean(axis=0)
    return grid[int(np.argmin(m))]


def blend(df: pl.DataFrame, cols: list[str], seasons: tuple[int, ...]) -> tuple[np.ndarray, dict]:
    """Convex blend per position, weights fitted on the other seasons."""
    x = df.select(cols).to_numpy().astype(float)
    y = df["pts"].to_numpy()
    s = df["season"].to_numpy()
    pos = df["pos"].to_numpy()
    pred = np.full(df.height, np.nan)
    weights: dict = {}
    for test in seasons:
        tr_s = np.isin(s, [t for t in seasons if t != test])
        for p in POS:
            tr, te = tr_s & (pos == p), (s == test) & (pos == p)
            if not te.any() or tr.sum() < 50:
                continue
            w = fit_convex(x[tr], y[tr])
            pred[te] = x[te] @ w
            weights[f"{test}:{p}"] = [round(float(v), 2) for v in w]
    return pred, weights


# ---- data -------------------------------------------------------------------------

def role_rows(data: dict) -> tuple[pl.DataFrame, dict]:
    """Every test player-game with the three role variants, each from a fit
    on the seasons before its season."""
    frames, summary = [], {}
    for s in TEST:
        cols: dict = {}
        for v in role.VARIANTS:
            t0 = time.time()
            prm = role.fit(data, range(role.FIRST_FIT, s), v)
            out = role.project(data, prm)
            m = ((out["season"] == s) & (out["week"] >= WEEKS[0]) & (out["week"] <= WEEKS[1])
                 & ~out["query"].astype(bool))
            if not cols:
                cols = {k: out[k][m] for k in ("season", "week", "player_id", "pos", "team", "pts")}
                cols["snap_share"] = out["snap_share"][m]
            else:
                assert np.array_equal(cols["player_id"], out["player_id"][m]), "row order changed between variants"
            cols[f"role_{v}"] = out["role"][m]
            cols[f"raw_{v}"] = out["raw"][m]
            if v == "base":
                summary[str(s)] = summarize(prm)
            print(f"role_eval: fit+project {s} {v} {time.time() - t0:.1f}s", file=sys.stderr)
        frames.append(pl.DataFrame({k: (v.astype(str) if v.dtype == object else v) for k, v in cols.items()}))
    df = pl.concat(frames).with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))
    return df, summary


def summarize(prm: dict) -> dict:
    """The fitted numbers worth reading, rounded."""
    def rnd(d: Any) -> Any:
        if isinstance(d, dict):
            return {k: rnd(v) for k, v in d.items() if k != "ll"}
        if isinstance(d, list):
            return [rnd(v) for v in d]
        return round(d, 4) if isinstance(d, float) else d
    return rnd({k: prm[k] for k in ("train", "volume", "share", "eff", "phi", "calib")})


def season_average(data: dict) -> pl.DataFrame:
    """Season-to-date points per game before each game (the naive control)."""
    p = data["players"].sort(["player_id", "season", "week"])
    key = (p["player_id"] + "|" + p["season"].cast(pl.Utf8)).to_numpy()
    panel = role.Panel(key, p["season"].to_numpy())
    pts = p["pts"].fill_null(0).to_numpy().astype(float)
    tot, n = panel.state(pts, 1.0, 0.0), panel.state(np.ones(pts.size), 1.0, 0.0)
    avg = np.where(n > 0, tot / np.maximum(n, 1), np.nan)
    return p.select(["season", "week", "player_id"]).with_columns(pl.Series("naive", avg).fill_nan(None))


def sleeper_rows() -> pl.DataFrame:
    sl = nflraw.sleeper_weeks(list(TEST)).filter(pl.col("gsis_id").is_not_null() & pl.col("pos").is_in(POS))
    return sl.select([pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64),
                      pl.col("gsis_id").alias("player_id"), pl.col("proj").alias("sleeper")]).unique(
        ["season", "week", "player_id"], keep="first")


def market_rows() -> pl.DataFrame:
    frames = {s: market.frame([s], "close") for s in PRICED}
    out = []
    for s in PRICED:
        mdl = market.fit(pl.concat([frames[t] for t in PRICED if t != s], how="diagonal_relaxed"))
        rows = frames[s].to_dicts()
        for r, v in zip(rows, market.predict_rows(rows, mdl), strict=True):
            if v is not None:
                out.append({"season": s, "week": int(r["week"]), "player_id": r["gsis_id"], "market": float(v)})
    return pl.DataFrame(out).unique(["season", "week", "player_id"], keep="first")


# ---- leakage ------------------------------------------------------------------------

def leakage(data: dict, season: int, weeks: tuple[int, ...]) -> dict:
    """Two checks on the base variant fitted for `season`.
    cut:     week_projection() on data cut at the week, for the players who
             played that week, against the vectorized projection.
    corrupt: every player and team count, and every point total, from the
             week on multiplied by random factors; the week's vectorized
             projections must not move."""
    prm = role.fit(data, range(role.FIRST_FIT, season), "base")
    out = role.project(data, prm)
    res: dict = {"season": season, "weeks": list(weeks), "cut_max_abs_diff": 0.0, "corrupt_max_abs_diff": 0.0,
                 "rows": 0}
    pid = out["player_id"].astype(str)
    for w in weeks:
        sel = (out["season"] == season) & (out["week"] == w)
        vec = dict(zip(pid[sel], out["role"][sel], strict=True))
        uni = data["players"].filter((pl.col("season") == season) & (pl.col("week") == w)).select(
            [pl.col("player_id").alias("gsis_id"), "pos", "team"])
        cut = role.week_projection(season, w, "base", params=prm, data=data, universe=uni)
        diffs = [abs(cut[k] - round(float(v), 2)) for k, v in vec.items() if k in cut]
        res["cut_max_abs_diff"] = max(res["cut_max_abs_diff"], max(diffs) if diffs else float("nan"))
        res["rows"] += len(diffs)
        res[f"cut_missing_w{w}"] = len(vec) - len(diffs)

        fut = (pl.col("season") > season) | ((pl.col("season") == season) & (pl.col("week") >= w))
        num_p = [c for c in (*role.COUNTS, "rec_y", "rush_y", "pass_y", "pts") if c in data["players"].columns]
        bad_p = data["players"].with_columns(pl.Series("_f", RNG.uniform(0.0, 3.0, data["players"].height))).with_columns(
            *[pl.when(fut).then(pl.col(c) * pl.col("_f") + 1.0).otherwise(pl.col(c)).alias(c) for c in num_p]).drop("_f")
        bad_t = data["teams"].with_columns(pl.Series("_f", RNG.uniform(0.0, 3.0, data["teams"].height))).with_columns(
            *[pl.when(fut).then(pl.col(c) * pl.col("_f") + 1.0).otherwise(pl.col(c)).alias(c)
              for c in role.TEAM_COUNTS]).drop("_f")
        out2 = role.project({"players": bad_p, "teams": bad_t, "roster": data["roster"]}, prm)
        sel2 = (out2["season"] == season) & (out2["week"] == w)
        assert np.array_equal(out2["player_id"][sel2], out["player_id"][sel])
        changed_after = float(np.abs(out2["role"] - out["role"])[(out["season"] == season) & (out["week"] > w)].max())
        res["corrupt_max_abs_diff"] = max(res["corrupt_max_abs_diff"],
                                          float(np.abs(out2["role"][sel2] - out["role"][sel]).max()))
        # The positive control of this check: later weeks do move.
        res[f"corrupt_later_weeks_max_move_w{w}"] = r3(changed_after)
        if w == weeks[0]:
            # The fit reads only seasons before `season`: refit on the
            # corrupted data and compare every fitted number.
            prm2 = role.fit({"players": bad_p, "teams": bad_t, "roster": data["roster"]},
                            range(role.FIRST_FIT, season), "base")
            res["refit_on_corrupted_identical"] = json.dumps(prm2, sort_keys=True) == json.dumps(prm, sort_keys=True)
    res["cut_max_abs_diff"] = r3(res["cut_max_abs_diff"])
    res["corrupt_max_abs_diff"] = float(res["corrupt_max_abs_diff"])
    res["pass"] = bool(res["cut_max_abs_diff"] is not None and res["cut_max_abs_diff"] <= 0.01
                       and res["corrupt_max_abs_diff"] == 0.0 and res.get("refit_on_corrupted_identical"))
    return res


# ---- the run ------------------------------------------------------------------------

def table(df: pl.DataFrame, pairs: list[tuple[str, str]], label: str) -> dict:
    """paired() for each (a, b) by position and for all positions."""
    out: dict = {"rows": df.height, "label": label}
    groups_all = {"player": df["player_id"].to_numpy(),
                  "week": (df["season"] * 100 + df["week"]).to_numpy()}
    y_all = df["pts"].to_numpy()
    pos = df["pos"].to_numpy()
    for p in (*POS, "ALL"):
        m = np.ones(df.height, dtype=bool) if p == "ALL" else pos == p
        g = {k: v[m] for k, v in groups_all.items()}
        res = {}
        for a, b in pairs:
            res[f"{a} vs {b}"] = paired(df[a].to_numpy()[m], df[b].to_numpy()[m], y_all[m], g)
        out[p] = res
    return out


def mae_table(df: pl.DataFrame, cols: list[str]) -> dict:
    out: dict = {}
    y = df["pts"].to_numpy()
    for p in (*POS, "ALL"):
        m = np.ones(df.height, dtype=bool) if p == "ALL" else df["pos"].to_numpy() == p
        out[p] = {"n": int(m.sum())}
        for c in cols:
            e = df[c].to_numpy()[m] - y[m]
            out[p][c] = {"mae": r3(np.abs(e).mean()), "rmse": r3(np.sqrt((e ** 2).mean())), "bias": r3(e.mean())}
    return out


def relevant(df: pl.DataFrame) -> pl.DataFrame:
    rk = pl.col("sleeper").rank("ordinal", descending=True).over(["season", "week", "pos"])
    lim = pl.col("pos").replace_strict(RELEVANT, return_dtype=pl.Int64)
    return df.filter(rk <= lim)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="does the role model earn a vote? (writes research/out/role_eval.json)")
    ap.parse_args(argv)
    t0 = time.time()
    report: dict = {"run_at": time.strftime("%Y-%m-%dT%H:%M"), "test_seasons": list(TEST), "weeks": list(WEEKS),
                    "boot": BOOT, "seed": SEED}

    data = role.load(DATA, routes=True)
    print(f"role_eval: loaded {DATA[0]}-{DATA[-1]} in {time.time() - t0:.0f}s "
          f"({data['players'].height} player-games)", file=sys.stderr)
    rr, report["fitted_base"] = role_rows(data)
    naive = season_average(data)
    df = rr.join(sleeper_rows(), on=["season", "week", "player_id"], how="inner")
    df = df.join(naive, on=["season", "week", "player_id"], how="left")
    df = df.join(market_rows(), on=["season", "week", "player_id"], how="left")
    df = df.sort(["season", "week", "player_id"])
    report["rows"] = {"role_rows": rr.height, "with_sleeper": df.height,
                      "with_market": int(df["market"].is_not_null().sum())}

    # Blends of Sleeper and the role model, all test seasons.
    for v in role.VARIANTS:
        pred, w = blend(df, ["sleeper", f"role_{v}"], TEST)
        df = df.with_columns(pl.Series(f"S+role_{v}", pred))
        report.setdefault("weights", {})[f"S+role_{v}"] = w
    df = df.with_columns(((pl.col("sleeper") + pl.col("role_base")) / 2).alias("S+role_base eq"))

    # Main table: Sleeper and role, all rows with a Sleeper projection.
    cols = ["sleeper", "role_base", "role_routes", "role_plain", "raw_base", "S+role_base", "S+role_routes",
            "S+role_base eq"]
    report["mae_all"] = mae_table(df, cols)
    report["diff_all"] = table(df, [("role_base", "sleeper"), ("role_routes", "sleeper"),
                                    ("S+role_base", "sleeper"), ("S+role_routes", "sleeper"),
                                    ("S+role_base eq", "sleeper"),
                                    ("role_routes", "role_base"), ("role_base", "role_plain"),
                                    ("S+role_routes", "S+role_base")], "all rows with a Sleeper projection")
    rel = relevant(df)
    report["mae_relevant"] = mae_table(rel, cols)
    report["diff_relevant"] = table(rel, [("role_base", "sleeper"), ("S+role_base", "sleeper"),
                                          ("role_routes", "role_base")],
                                    f"top {RELEVANT} per week by Sleeper's projection")
    per_season = {}
    for s in TEST:
        d_s = df.filter(pl.col("season") == s)
        per_season[str(s)] = table(d_s, [("role_base", "sleeper"), ("S+role_base", "sleeper")], str(s))["ALL"]
    report["per_season"] = per_season

    # Market rows: the verdict.
    mk = df.filter(pl.col("market").is_not_null() & pl.col("season").is_in(list(PRICED)))
    for name, cs in (("S+M", ["sleeper", "market"]), ("S+M+role_base", ["sleeper", "market", "role_base"]),
                     ("S+M+role_routes", ["sleeper", "market", "role_routes"])):
        pred, w = blend(mk, cs, PRICED)
        mk = mk.with_columns(pl.Series(name, pred))
        report.setdefault("weights", {})[name] = w
    for v in ("base", "routes"):
        pred, w = blend(mk, ["sleeper", f"role_{v}"], PRICED)
        mk = mk.with_columns(pl.Series(f"S+role_{v} (priced fit)", pred))
    mk = mk.with_columns(((pl.col("sleeper") + pl.col("market")) / 2).alias("S+M eq"),
                         ((pl.col("sleeper") + pl.col("market") + pl.col("role_base")) / 3).alias("S+M+role_base eq"))

    # Planted controls on the same rows.
    y = mk["pts"].to_numpy()
    s_ = mk["sleeper"].to_numpy()
    role_mae = float(np.abs(mk["role_base"].to_numpy() - y).mean())
    indep = y + RNG.normal(0.0, role_mae * np.sqrt(np.pi / 2), y.size)
    sig = np.linspace(0.5, 12.0, 116)
    noise = RNG.normal(0.0, 1.0, y.size)
    best_sig = float(sig[int(np.argmin([abs(np.abs(s_ + q * noise - y).mean() - role_mae) for q in sig]))])
    # A weak planted source: Sleeper moved 10% toward the result, plus noise
    # up to the role model's MAE. It carries a little information that
    # Sleeper and the market lack, at the size of gain the verdict cares about.
    nudge = s_ + 0.1 * (y - s_)
    noise_w = RNG.normal(0.0, 1.0, y.size)
    weak_sig = float(sig[int(np.argmin([abs(np.abs(nudge + q * noise_w - y).mean() - role_mae) for q in sig]))])
    mk = mk.with_columns(pl.Series("planted_indep", indep), pl.Series("planted_noinfo", s_ + best_sig * noise),
                         pl.Series("planted_weak", nudge + weak_sig * noise_w),
                         pl.Series("oracle10", 0.9 * s_ + 0.1 * y), pl.Series("oracle03", 0.97 * s_ + 0.03 * y))
    for name, cs in (("S+M+planted_indep", ["sleeper", "market", "planted_indep"]),
                     ("S+M+planted_noinfo", ["sleeper", "market", "planted_noinfo"]),
                     ("S+M+planted_weak", ["sleeper", "market", "planted_weak"])):
        pred, w = blend(mk, cs, PRICED)
        mk = mk.with_columns(pl.Series(name, pred))
        report.setdefault("weights", {})[name] = w
    mcols = ["sleeper", "market", "role_base", "role_routes", "S+role_base (priced fit)", "S+M", "S+M+role_base",
             "S+M+role_routes", "S+M eq", "S+M+role_base eq", "planted_indep", "planted_noinfo", "planted_weak"]
    report["mae_market_rows"] = mae_table(mk, mcols)
    report["diff_market_rows"] = table(mk, [
        ("market", "sleeper"), ("role_base", "sleeper"), ("S+M", "sleeper"),
        ("S+role_base (priced fit)", "sleeper"),
        ("S+M+role_base", "S+M"), ("S+M+role_routes", "S+M"), ("S+M+role_base eq", "S+M eq"),
        ("S+M+planted_indep", "S+M"), ("S+M+planted_noinfo", "S+M"), ("S+M+planted_weak", "S+M")],
        "2024-2025 rows with market lines")
    report["planted"] = {"role_mae_on_rows": r3(role_mae), "indep_noise_sd": r3(role_mae * np.sqrt(np.pi / 2)),
                         "noinfo_noise_sd": r3(best_sig), "weak_noise_sd": r3(weak_sig)}

    # Upper bound, NOT out of sample: blend weights chosen on the test rows
    # themselves. If even these find no gain, no weighting will.
    pos_mk = mk["pos"].to_numpy()
    x2 = mk.select(["sleeper", "market"]).to_numpy().astype(float)
    x3 = mk.select(["sleeper", "market", "role_base"]).to_numpy().astype(float)
    p2, p3 = np.zeros(y.size), np.zeros(y.size)
    ub_w = {}
    for p in POS:
        m = pos_mk == p
        w2, w3 = fit_convex(x2[m], y[m]), fit_convex(x3[m], y[m])
        p2[m], p3[m] = x2[m] @ w2, x3[m] @ w3
        ub_w[p] = {"S+M": [round(float(v), 2) for v in w2], "S+M+role_base": [round(float(v), 2) for v in w3]}
    groups = {"player": mk["player_id"].to_numpy(), "week": (mk["season"] * 100 + mk["week"]).to_numpy()}
    report["in_sample_bound"] = {"weights": ub_w, "ALL": paired(p3, p2, y, groups)}

    # How much of the role model's error does Sleeper's error already contain?
    ecorr: dict = {}
    for p in (*POS, "ALL"):
        m = np.ones(y.size, dtype=bool) if p == "ALL" else pos_mk == p
        e = {c: mk[c].to_numpy()[m] - y[m] for c in ("sleeper", "market", "role_base")}
        ecorr[p] = {"role~sleeper": r3(np.corrcoef(e["role_base"], e["sleeper"])[0, 1]),
                    "market~sleeper": r3(np.corrcoef(e["market"], e["sleeper"])[0, 1]),
                    "role~market": r3(np.corrcoef(e["role_base"], e["market"])[0, 1])}
    report["error_corr_market_rows"] = ecorr

    # Positive controls on all rows.
    nv = df.filter(pl.col("naive").is_not_null())
    report["control_naive"] = table(nv, [("sleeper", "naive"), ("role_base", "naive")],
                                    "rows with at least one earlier game this season")
    y2 = df["pts"].to_numpy()
    df = df.with_columns(pl.Series("oracle10", 0.9 * df["sleeper"].to_numpy() + 0.1 * y2),
                         pl.Series("oracle03", 0.97 * df["sleeper"].to_numpy() + 0.03 * y2))
    report["control_oracle"] = table(df, [("oracle10", "sleeper"), ("oracle03", "sleeper")], "all rows")

    v = report["diff_market_rows"]["ALL"]["S+M+role_base vs S+M"]
    report["verdict"] = {
        "rule": "role becomes a vote only if adding it to the Sleeper+market blend lowers MAE with a 95% CI "
                "that excludes zero (base variant, the one that runs live)",
        "d_mae": v["d_mae"], "ci": v["ci_mae"], "vote": v["mae_gain_excludes_zero"],
        "positive_control_detected": report["diff_market_rows"]["ALL"]["S+M+planted_indep vs S+M"][
            "mae_gain_excludes_zero"],
        "negative_control_detected": report["diff_market_rows"]["ALL"]["S+M+planted_noinfo vs S+M"][
            "mae_gain_excludes_zero"],
        "weak_positive_control_detected": report["diff_market_rows"]["ALL"]["S+M+planted_weak vs S+M"][
            "mae_gain_excludes_zero"]}
    r = report["diff_all"]["ALL"]["role_routes vs role_base"]
    report["routes_verdict"] = {"d_mae": r["d_mae"], "ci": r["ci_mae"], "routes_better": r["mae_gain_excludes_zero"]}

    report["leakage"] = [leakage(data, 2024, (6, 12)), leakage(data, 2022, (4,))]
    report["seconds"] = round(time.time() - t0)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1, default=str) + "\n")
    print(json.dumps({"verdict": report["verdict"], "routes": report["routes_verdict"],
                      "leakage": [{k: x[k] for k in ("cut_max_abs_diff", "corrupt_max_abs_diff", "pass")}
                                  for x in report["leakage"]]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
