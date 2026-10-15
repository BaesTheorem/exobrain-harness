"""market: fantasy points implied by the betting market's player props.

The rawest forecast available for one player in one game is the price a
sportsbook will take bets at: receiving yards 54.5, receptions 4.5, rushing
yards 38.5, the team's implied total from the spread and the total. This
turns those lines into points on this league's scoring with one linear model
per position, fitted on games whose results are known:

    pts ~ intercept + implied team points + the position's CORE lines

Lines are medians and yardage is right-skewed, so a line is not a mean; the
fit learns the conversion (2025: receiving yards came in 3.7 over the close
on average, while half the results still fell under it). Touchdowns have no
priced market in the 2026 feed, so the touchdown part comes from the
implied total and the yardage lines, which is what the fit can see.

Books post different menus: ESPN BET in 2024 posted no interception line and
a rushing line for 41% of quarterbacks, against 99% and 93% in 2025. A model
that reads "line missing" as information learns one book's habits and
breaks on the next (the first version, with a flag per missing line, scored
quarterbacks at 8.4 points of error on 2024 against Sleeper's 6.0). So the
model reads only CORE lines, and a missing one is first rebuilt from lines
that imply it (rushing = passing-plus-rushing minus passing) and then from a
linear fill learned on rows that have both.

Books void a prop when the player does not play, so a line is a forecast
conditional on playing, and so is this projection. Inactive risk stays with
the injury status, where every other tool already prices it.

    frame(seasons, when)     player-games with their lines and the result
    fit(df)                  fills and coefficients per position
    predict_rows(rows, m)    E[points | plays] per row
    evaluate()               out-of-sample against Sleeper and ESPN
    clv(recs)                closing line value of the filed forecasts
    week(season, week)       this week's projections from the current lines,
                             keyed by ESPN player id (ESPN's athlete id is
                             the fantasy player id)

INVARIANTS
- Never fitted and scored on the same season: evaluate() trains on the
  other seasons only.
- A player gets a projection only when the book posted a line on his core
  stat (ANCHOR). No line, no market opinion; the caller falls back to the
  other sources.
- Read-only against every source.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = HERE / "market_model.json"
ALL_STATS = ["carries", "completions", "fg_made", "ints", "kick_pts", "pass_att", "pass_rush_yds", "pass_td",
             "pass_yds", "pat_made", "rec_yds", "receptions", "rush_rec_yds", "rush_yds"]
CORE = {"QB": ("pass_yds", "pass_td", "rush_yds"), "RB": ("rush_yds", "rec_yds", "receptions"),
        "WR": ("rec_yds", "receptions"), "TE": ("rec_yds", "receptions"), "K": ("kick_pts",)}
FEATS = CORE
ANCHOR = {"QB": ("pass_yds", "pass_rush_yds"), "RB": ("rush_yds", "carries", "rec_yds", "receptions", "rush_rec_yds"),
          "WR": ("rec_yds", "receptions", "rush_rec_yds"), "TE": ("rec_yds", "receptions", "rush_rec_yds"),
          "K": ("kick_pts", "fg_made")}
# Learned fills, tried in order: (target, sources). An empty source list is
# the training mean of the target for the position.
FILLS = {
    "QB": [("rush_yds", ["carries"]), ("rush_yds", []), ("pass_td", ["pass_yds", "implied"])],
    "RB": [("rush_yds", ["carries"]), ("receptions", ["rec_yds"]), ("rec_yds", ["receptions"]),
           ("receptions", ["rush_yds"]), ("rec_yds", ["rush_yds"]), ("rush_yds", ["receptions"])],
    "WR": [("receptions", ["rec_yds"]), ("rec_yds", ["receptions"])],
    "TE": [("receptions", ["rec_yds"]), ("rec_yds", ["receptions"])],
    "K": [("kick_pts", ["fg_made", "implied"]), ("kick_pts", ["implied"])],
}
DEFAULT_IMPLIED = 22.0
RIDGE = 1.0


def anchored(r: dict) -> bool:
    return any(r.get(s) is not None for s in ANCHOR.get(r.get("pos") or "", ()))


def identities(r: dict) -> dict:
    """Rebuild a missing line from lines that imply it, exactly."""
    x = dict(r)
    if x.get("implied") is None:
        x["implied"] = DEFAULT_IMPLIED
    prr, py, ry = x.get("pass_rush_yds"), x.get("pass_yds"), x.get("rush_yds")
    if ry is None and prr is not None and py is not None:
        x["rush_yds"] = max(0.0, prr - py)
    if x.get("pass_yds") is None and prr is not None and x.get("rush_yds") is not None:
        x["pass_yds"] = max(0.0, prr - x["rush_yds"])
    rr, rec, ry = x.get("rush_rec_yds"), x.get("rec_yds"), x.get("rush_yds")
    if rec is None and rr is not None:
        x["rec_yds"] = max(0.0, rr - (ry or 0.0)) if x.get("pos") != "RB" or ry is not None else None
    if x.get("rush_yds") is None and rr is not None and x.get("rec_yds") is not None and x.get("pos") == "RB":
        x["rush_yds"] = max(0.0, rr - x["rec_yds"])
    return x


def _ols(xs, ys, ridge: float = 1e-6):
    import numpy as np  # noqa: PLC0415

    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    pen = ridge * np.eye(x.shape[1])
    pen[0, 0] = 0.0
    return [float(b) for b in np.linalg.solve(x.T @ x + pen, x.T @ y)]


def fit_fills(rows: list[dict]) -> dict:
    out: dict = {}
    for pos, rules in FILLS.items():
        rs = [identities(r) for r in rows if r.get("pos") == pos]
        out[pos] = []
        for target, srcs in rules:
            ok = [r for r in rs if r.get(target) is not None and all(r.get(s) is not None for s in srcs)]
            if len(ok) < 30:
                continue
            coef = _ols([[1.0, *[float(r[s]) for s in srcs]] for r in ok], [float(r[target]) for r in ok])
            out[pos].append({"target": target, "sources": srcs, "coef": [round(c, 5) for c in coef], "n": len(ok)})
    return out


def complete(r: dict, fills: dict) -> dict | None:
    """The row with every CORE line present, or None when it cannot be built."""
    x = identities(r)
    pos = x.get("pos") or ""
    for f in fills.get(pos, []):
        if x.get(f["target"]) is None and all(x.get(s) is not None for s in f["sources"]):
            x[f["target"]] = sum(c * v for c, v in zip(f["coef"], [1.0, *[float(x[s]) for s in f["sources"]]], strict=True))
    if any(x.get(s) is None for s in CORE.get(pos, ("?",))):
        return None
    return x


def _design(x: dict, pos: str) -> list[float]:
    return [1.0, float(x["implied"]), *[float(x[s]) for s in CORE[pos]]]


def frame(seasons: list[int], when: str = "close"):
    """One row per player-game with a line on his core stat: the lines (wide),
    his team's implied points, his position and his league points."""
    import polars as pl  # noqa: PLC0415

    sys.path.insert(0, str(HERE.parent))
    from ffmodel import nflraw, props  # noqa: PLC0415

    col = f"{when}_line"
    lines = props.lines(seasons).filter(pl.col("stat").is_in(ALL_STATS) & pl.col("athlete").is_not_null())
    wide = lines.pivot(on="stat", index=["season", "week", "game", "athlete"], values=col, aggregate_function="first")
    ids = nflraw.id_table().select(["espn_id", "gsis_id"]).filter(pl.col("espn_id").is_not_null()).unique("espn_id")
    wide = wide.join(ids, left_on="athlete", right_on="espn_id", how="inner")
    pw = nflraw.player_weeks(seasons).select(["season", "week", "player_id", "name", "pos", "team", "opp", "pts"])
    df = wide.join(pw, left_on=["season", "week", "gsis_id"], right_on=["season", "week", "player_id"], how="inner")
    g = nflraw.games(seasons)
    imp = pl.concat([g.select(["season", "week", pl.col("home").alias("team"), pl.col("implied_home").alias("implied")]),
                     g.select(["season", "week", pl.col("away").alias("team"), pl.col("implied_away").alias("implied")])])
    df = df.join(imp, on=["season", "week", "team"], how="left")
    for s in ALL_STATS:
        if s not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias(s))
    rows = [r for r in df.to_dicts() if r["pos"] in CORE and anchored(r)]
    return pl.DataFrame(rows, infer_schema_length=None)


def fit(df) -> dict:
    rows = df.to_dicts()
    fills = fit_fills(rows)
    model: dict = {"core": {k: list(v) for k, v in CORE.items()}, "fills": fills, "coef": {}, "n": {}}
    for pos in CORE:
        done = [x for r in rows if r["pos"] == pos and (x := complete(r, fills)) is not None]
        if len(done) < 50:
            continue
        model["coef"][pos] = [round(c, 5) for c in _ols([_design(x, pos) for x in done],
                                                         [float(x["pts"]) for x in done], RIDGE)]
        model["n"][pos] = len(done)
    return model


def predict_rows(rows: list[dict], model: dict) -> list[float | None]:
    out: list[float | None] = []
    for r in rows:
        pos = r.get("pos") or ""
        coef = model["coef"].get(pos)
        x = complete(r, model.get("fills") or {}) if coef and anchored(r) else None
        if x is None or coef is None:
            out.append(None)
            continue
        out.append(round(max(0.0, sum(c * v for c, v in zip(coef, _design(x, pos), strict=True))), 2))
    return out


def save(model: dict, path: Path = MODEL) -> None:
    path.write_text(json.dumps(model, indent=1) + "\n")


def load(path: Path = MODEL) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


# ---- evaluation ---------------------------------------------------------------

def _espn_projections(season: int, weeks: list[int]) -> dict[tuple[int, str], float]:
    """(week, espn id) -> ESPN's weekly projection, for every player rostered
    in the league that week. ESPN keeps past weeks' projections on the roster
    view of that period (checked 2026-10-15)."""
    sys.path.insert(0, str(HERE.parent))
    from espncli.client import Espn, week_proj  # noqa: PLC0415

    api = Espn()
    out = {}
    for w in weeks:
        data = api.league("mRoster", period=w)
        for t in data["teams"]:
            for e in (t.get("roster") or {}).get("entries", []):
                p = (e.get("playerPoolEntry") or {}).get("player") or {}
                v = week_proj(p, season, w)
                if v is not None and p.get("id") is not None:
                    out[(w, str(p["id"]))] = float(v)
    return out


def _score(pairs: list[tuple[float, float]]) -> dict:
    import numpy as np  # noqa: PLC0415

    if not pairs:
        return {"n": 0}
    a = np.asarray(pairs)
    err = a[:, 0] - a[:, 1]
    return {"n": len(a), "mae": round(float(np.mean(np.abs(err))), 3), "bias": round(float(np.mean(err)), 3),
            "rmse": round(float(np.sqrt(np.mean(err ** 2))), 3)}


def evaluate(seasons=(2024, 2025), live: int | None = 2026, live_weeks: list[int] | None = None,
             when: str = "close") -> dict:
    """Leave-one-season-out on the priced seasons, then the 2026 DraftKings
    weeks with a model fitted on every priced season. Each player-game is
    scored by every source that has him, and every comparison is on the rows
    both sources share."""
    import polars as pl  # noqa: PLC0415

    sys.path.insert(0, str(HERE.parent))
    from ffmodel import nflraw  # noqa: PLC0415

    report: dict = {"when": when, "folds": {}}
    frames = {s: frame([s], when) for s in seasons}
    test_sets = [(s, [t for t in seasons if t != s]) for s in seasons]
    if live:
        frames[live] = frame([live], when)
        test_sets.append((live, list(seasons)))
    for test, train in test_sets:
        model = fit(pl.concat([frames[t] for t in train], how="diagonal_relaxed"))
        df = frames[test]
        rows = df.to_dicts()
        mk = predict_rows(rows, model)
        sl = nflraw.sleeper_weeks([test]).filter(pl.col("gsis_id").is_not_null())
        sl_map = {(r["week"], r["gsis_id"]): r["proj"] for r in sl.select(["week", "gsis_id", "proj"]).to_dicts()}
        espn = _espn_projections(test, live_weeks or sorted({r["week"] for r in rows})) if test == live else {}
        fold: dict = {"train": train, "by_pos": {}}
        for pos in [*FEATS, "ALL"]:
            sel = [(r, m) for r, m in zip(rows, mk, strict=True) if m is not None and (pos == "ALL" or r["pos"] == pos)]
            res: dict = {}
            both = [(m, r["pts"], sl_map[(r["week"], r["gsis_id"])]) for r, m in sel if (r["week"], r["gsis_id"]) in sl_map]
            res["market_vs_sleeper_rows"] = len(both)
            res["market"] = _score([(m, a) for m, a, _ in both])
            res["sleeper"] = _score([(s, a) for _, a, s in both])
            res["blend50"] = _score([(0.5 * m + 0.5 * s, a) for m, a, s in both])
            if espn:
                tri: list[tuple[float, float, float, float]] = [
                    (m, r["pts"], sl_map[(r["week"], r["gsis_id"])], espn[(r["week"], str(r["athlete"]))])
                    for r, m in sel
                    if (r["week"], str(r["athlete"])) in espn and (r["week"], r["gsis_id"]) in sl_map]
                res["three_way_rows"] = len(tri)
                res["3w_market"] = _score([(m, a) for m, a, _, _ in tri])
                res["3w_espn"] = _score([(e, a) for _, a, _, e in tri])
                res["3w_sleeper"] = _score([(s, a) for _, a, s, _ in tri])
                res["3w_mean_espn_sleeper"] = _score([((e + s) / 2, a) for _, a, s, e in tri])
                res["3w_mean_all3"] = _score([((m + e + s) / 3, a) for m, a, s, e in tri])
            fold["by_pos"][pos] = res
        report["folds"][str(test)] = fold
    return report


# ---- closing line value -----------------------------------------------------------

def clv(recs: list[dict], model: dict | None = None) -> dict:
    """Did a forecaster see what the market learned between forecast and kickoff?

    For each filed week: the market's projection at forecast time (the filed
    `market_at_forecast`, or the opening line for weeks filed before
    2026-10-15), the market's projection at the close, MIST's median, the
    source consensus and ESPN, and the result. A forecaster with information
    the market did not yet have leans the way the line later moves:
    corr(forecast - market then, market close - market then) > 0. Results
    converge slowly (one week is ~16 lines of noise); line moves converge
    fast, which is why bettors judge themselves on them."""
    model = model or load()
    if not model:
        return {"n": 0, "why": "no fitted market model"}
    seasons = sorted({r["season"] for r in recs if r.get("settled")})
    if not seasons:
        return {"n": 0}
    pred: dict[str, dict[tuple[int, str], float]] = {}
    for when in ("open", "close"):
        df = frame(seasons, when)
        rows = df.to_dicts()
        pr = predict_rows(rows, model)
        pred[when] = {(r["week"], str(r["athlete"])): v for r, v in zip(rows, pr, strict=True) if v is not None}
    out_rows = []
    for r in recs:
        s = r.get("settled")
        if not s:
            continue
        actual = {p["name"]: p["mist"]["actual"] for p in s["players"] if "mist" in p}
        at_fc = r.get("market_at_forecast") or {}
        for p in r["forecast"]["players"]:
            pid, w = str(p.get("id")), r["week"]
            if p["name"] not in actual:
                continue
            then = (at_fc.get(pid) or {}).get("market")
            src = "forecast-time" if then is not None else "open"
            then = then if then is not None else pred["open"].get((w, pid))
            close = pred["close"].get((w, pid))
            if then is None or close is None:
                continue
            out_rows.append({"week": w, "name": p["name"], "pos": p.get("pos"), "then_src": src,
                             "market_then": then, "market_close": close, "mist": p.get("median"),
                             "consensus": p.get("consensus"), "espn": p.get("espn"), "actual": actual[p["name"]]})
    return _clv_summary(out_rows)


def _clv_summary(rows: list[dict]) -> dict:
    import numpy as np  # noqa: PLC0415

    out: dict = {"n": len(rows), "rows": rows}
    if len(rows) < 5:
        return out
    move = np.asarray([r["market_close"] - r["market_then"] for r in rows])
    act = np.asarray([r["actual"] for r in rows])
    for who in ("mist", "consensus", "espn"):
        sel = [i for i, r in enumerate(rows) if r.get(who) is not None]
        if len(sel) < 5:
            continue
        f = np.asarray([rows[i][who] for i in sel], dtype=float)
        lean = f - np.asarray([rows[i]["market_then"] for i in sel])
        mv = move[sel]
        big = np.abs(mv) >= 0.5
        r_ = float(np.corrcoef(lean, mv)[0, 1]) if np.std(lean) > 0 and np.std(mv) > 0 else None
        out[who] = {"n": len(sel),
                    "corr_lean_vs_move": round(r_, 3) if r_ is not None else None,
                    "sign_agree_on_moves": round(float(np.mean(np.sign(lean[big]) == np.sign(mv[big]))), 3) if big.any() else None,
                    "moves": int(big.sum()),
                    "mae": round(float(np.mean(np.abs(f - act[sel]))), 3),
                    "mae_market_close_same_rows": round(float(np.mean(np.abs(np.asarray([rows[i]["market_close"] for i in sel]) - act[sel]))), 3),
                    "mae_market_then_same_rows": round(float(np.mean(np.abs(np.asarray([rows[i]["market_then"] for i in sel]) - act[sel]))), 3)}
    return out


# ---- this week ----------------------------------------------------------------

def week(season: int, week_no: int, model: dict | None = None) -> dict[str, dict]:
    """ESPN player id -> {"market": points, "lines": {...}, "implied": x} for
    every player in an unplayed game of `week_no` with a line on his core stat.
    Reads the current (live pregame) lines; never a finished game's."""
    sys.path.insert(0, str(HERE.parent))
    from espncli.client import Espn  # noqa: PLC0415
    from ffmodel import props  # noqa: PLC0415

    model = model or load()
    if not model:
        raise SystemExit("market: no fitted model; run `python3 -m ffmodel.market fit`")
    api = Espn()
    index = {str(p["id"]): p for p in api.players_index()}
    out: dict[str, dict] = {}
    for ev in props.events(season, week_no):
        if ev["state"] != "pre":
            continue
        rows = props.game_props(ev["id"])
        by_ath: dict[str, list[dict]] = {}
        for r in rows:
            if r.get("a") and r["t"] in ALL_STATS:
                by_ath.setdefault(r["a"], []).append(r)
        implied = _implied(api, week_no, ev)
        for ath, items in by_ath.items():
            p = index.get(ath)
            if not p or p["pos"] not in FEATS:
                continue
            team = api.pro(p["team"]).get("abbrev") if p.get("team") else None
            rec: dict = {"pos": p["pos"], "implied": implied.get(team or "")}
            stats: dict[str, list[dict]] = {}
            for it in items:
                stats.setdefault(it["t"], []).append(it)
            lines = {}
            for st, its in stats.items():
                line, _p = props.main_line(its, "c")
                if line is not None:
                    lines[st] = line
            rec.update(lines)
            val = predict_rows([rec], model)[0]
            if val is not None:
                out[ath] = {"name": p["name"], "pos": p["pos"], "team": team, "market": val,
                            "lines": lines, "implied": rec["implied"], "game": ev["id"]}
    return out


def week_cached(season: int, week_no: int, ttl: float = 1800.0) -> dict[str, dict]:
    """week(), kept for `ttl` seconds in .cache/market-<season>-wNN.json, so a
    watcher that runs every 15 minutes reads the books twice an hour, not four
    times. Any failure returns {} and the caller falls back to ESPN alone."""
    import time  # noqa: PLC0415

    path = HERE.parent / ".cache" / f"market-{season}-w{week_no:02d}.json"
    try:
        if path.exists() and time.time() - path.stat().st_mtime < ttl:
            return json.loads(path.read_text())
        out = week(season, week_no)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out))
        return out
    except Exception as e:  # noqa: BLE001 - the lineup check must run without the market
        print(f"market: unavailable ({e})", file=sys.stderr)
        return {}


def _implied(api, week_no: int, ev: dict) -> dict[str, float]:
    sys.path.insert(0, str(HERE.parent))
    from espncli.cli import nfl_events  # noqa: PLC0415

    for g in nfl_events(api, week_no):
        if str(g.get("id")) == ev["id"]:
            out = {}
            if g.get("implied_home") is not None and g["home"]:
                out[g["home"]["abbrev"]] = g["implied_home"]
            if g.get("implied_away") is not None and g["away"]:
                out[g["away"]["abbrev"]] = g["implied_away"]
            return out
    return {}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="fantasy points from player prop lines")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("--seasons", default="2024,2025")
    e = sub.add_parser("evaluate")
    e.add_argument("--when", default="close", choices=("open", "close"))
    w = sub.add_parser("week")
    w.add_argument("week", type=int)
    w.add_argument("--season", type=int, default=2026)
    a = ap.parse_args()
    if a.cmd == "fit":
        ss = [int(s) for s in a.seasons.split(",")]
        m = fit(frame(ss))
        m["fit_seasons"] = ss
        save(m)
        print(json.dumps(m["n"]))
    elif a.cmd == "evaluate":
        print(json.dumps(evaluate(when=a.when), indent=1))
    else:
        res = week(a.season, a.week)
        for v in sorted(res.values(), key=lambda v: -v["market"])[:40]:
            print(f"{v['name'][:24]:24} {v['pos']:3} {v['team'] or '':4} {v['market']:6.1f}  implied {v['implied']}")
