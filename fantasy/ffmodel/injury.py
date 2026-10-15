"""injury: what an injury report says about Sunday, measured.

The lineup routine read a QUESTIONABLE tag through news text ("expected to
play", "game-time decision"). The raw material under that text is the
official report: a game status (Out, Doubtful, Questionable, or listed with
none) and the practice participation behind it (did not participate,
limited, full). nflverse keeps the final report of every week since 2009;
this joins ten seasons of them to snap counts (did he play) and to Sleeper's
pre-game projection (did he score what he was projected to when he played).

    build()            the table: P(plays) and the points-given-plays ratio
                       by position, game status and practice status, with
                       Wilson intervals; writes ffmodel/injury_table.json
    load()             read the table
    lookup(pos, status, practice)
                       the cell for one player, falling back to the
                       position-pooled cell and then to the status alone
    current(season, week)
                       this week's practice status by (name, team), from
                       nflverse's in-week report (Wednesday onward)

`plays` = at least one offensive snap (special-teams snap for a kicker).
Only regular contributors are counted: 40% or more of the offensive snaps in
one of the six weeks before (a kicker: any kick). The first build counted
the report's healthy backups, who never take a snap, as players who sat,
and put a listed-with-no-status QB at 0.82 to play.
`ratio` = mean actual / mean projection over the player-games where he
played, against the same ratio for players not on the report that week, so
it measures what the projection missed, not what injuries cost in general.

INVARIANTS
- The table is aggregate counts with no personal data; it is tracked so a
  fresh clone reads the same numbers.
- A cell with fewer than MIN_N player-games is never used on its own; the
  lookup falls back to a pooled cell instead.
- Read-only against every source.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE = HERE / "injury_table.json"
SEASONS = tuple(range(2016, 2026))
PROJ_SEASONS = (2022, 2023, 2024, 2025)
POSITIONS = ("QB", "RB", "WR", "TE", "K")
MIN_N = 40
REGULAR_PCT, REGULAR_LOOKBACK = 0.40, 6
PRACTICE = {"Did Not Participate In Practice": "DNP", "Limited Participation in Practice": "LP",
            "Full Participation in Practice": "FP"}
STATUS = {"Out": "O", "Doubtful": "D", "Questionable": "Q"}
ESPN_STATUS = {"OUT": "O", "O": "O", "D": "D", "DOUBTFUL": "D", "Q": "Q", "QUESTIONABLE": "Q"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def _frame():
    import nflreadpy as nfl  # noqa: PLC0415 -- heavy, build path only
    import polars as pl  # noqa: PLC0415

    sys.path.insert(0, str(HERE.parent))
    from ffmodel import nflraw  # noqa: PLC0415

    seasons = list(SEASONS)
    inj = nfl.load_injuries(seasons=seasons).filter(pl.col("game_type") == "REG")
    inj = inj.with_columns(
        pl.col("position").replace({"FB": "RB", "HB": "RB"}).alias("pos"),
        pl.col("report_status").replace_strict(STATUS, default="none").fill_null("none").alias("status"),
        pl.col("practice_status").replace_strict(PRACTICE, default="none").fill_null("none").alias("practice"),
    ).filter(pl.col("pos").is_in(list(POSITIONS)))
    inj = inj.select([pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64), "gsis_id", "pos", "status",
                      "practice"]).unique(["season", "week", "gsis_id"])
    snaps = nfl.load_snap_counts(seasons=seasons).filter(pl.col("game_type") == "REG")
    ids = nfl.load_ff_playerids().select(["gsis_id", "pfr_id"]).filter(
        pl.col("pfr_id").is_not_null() & pl.col("gsis_id").is_not_null()).unique("pfr_id")
    snaps = snaps.join(ids, left_on="pfr_player_id", right_on="pfr_id", how="inner").select(
        [pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64), "gsis_id", "offense_snaps", "st_snaps",
         "offense_pct"]
    ).group_by(["season", "week", "gsis_id"]).agg(pl.col("offense_snaps").sum(), pl.col("st_snaps").sum(),
                                                  pl.col("offense_pct").max())
    # Only regular contributors count: 40% of the offensive snaps (a kicker: any
    # kick) in one of the six weeks before. Without this the report's backups,
    # who never take a snap healthy or hurt, read as players who sat.
    prev = pl.concat([snaps.select(["season", (pl.col("week") + k).alias("week"), "gsis_id", "offense_pct", "st_snaps"])
                      for k in range(1, REGULAR_LOOKBACK + 1)]).group_by(["season", "week", "gsis_id"]).agg(
        pl.col("offense_pct").max().alias("prev_pct"), pl.col("st_snaps").max().alias("prev_st"))
    df = inj.join(snaps, on=["season", "week", "gsis_id"], how="left").join(
        prev, on=["season", "week", "gsis_id"], how="left").with_columns(
        pl.when(pl.col("pos") == "K").then(pl.col("st_snaps").fill_null(0) > 0)
        .otherwise(pl.col("offense_snaps").fill_null(0) > 0).alias("plays"),
        pl.when(pl.col("pos") == "K").then(pl.col("prev_st").fill_null(0) > 0)
        .otherwise(pl.col("prev_pct").fill_null(0) >= REGULAR_PCT).alias("regular"))
    df = df.filter(pl.col("regular"))
    proj = nflraw.sleeper_weeks(list(PROJ_SEASONS)).filter(pl.col("gsis_id").is_not_null()).select(
        [pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64), "gsis_id", "proj"])
    pts = nflraw.player_weeks(list(PROJ_SEASONS)).select(
        [pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64), "player_id", "pts"])
    base = proj.join(pts, left_on=["season", "week", "gsis_id"], right_on=["season", "week", "player_id"], how="inner")
    return df, base


def build(path: Path = TABLE) -> dict:
    import polars as pl  # noqa: PLC0415

    df, base = _frame()
    out: dict = {"built_from": f"nflverse injury reports and snap counts {SEASONS[0]}-{SEASONS[-1]}; "
                               f"Sleeper projections {PROJ_SEASONS[0]}-{PROJ_SEASONS[-1]} for the points ratio",
                 "cells": {}}
    listed = df.select(["season", "week", "gsis_id"]).with_columns(pl.lit(True).alias("listed"))
    joined = df.join(base, on=["season", "week", "gsis_id"], how="left")
    clean = base.join(listed, on=["season", "week", "gsis_id"], how="anti").filter(pl.col("proj") >= 3)
    clean_ratio = float(clean["pts"].sum()) / float(clean["proj"].sum())
    out["clean_ratio"] = round(clean_ratio, 3)
    for pos in (*POSITIONS, "ALL"):
        sub = joined if pos == "ALL" else joined.filter(pl.col("pos") == pos)
        for status in ("O", "D", "Q", "none", "*"):
            s1 = sub if status == "*" else sub.filter(pl.col("status") == status)
            for practice in ("DNP", "LP", "FP", "none", "*"):
                s2 = s1 if practice == "*" else s1.filter(pl.col("practice") == practice)
                n = s2.height
                if n == 0:
                    continue
                k = int(s2["plays"].sum())
                cell = {"n": n, "p_play": round(k / n, 3), "ci": wilson(k, n)}
                played = s2.filter(pl.col("plays") & pl.col("proj").is_not_null() & (pl.col("proj") >= 3))
                if played.height >= 20:
                    r = float(played["pts"].sum()) / float(played["proj"].sum())
                    cell["ratio"] = round(r / clean_ratio, 3)       # relative to players not on the report
                    cell["ratio_n"] = played.height
                out["cells"][f"{pos}|{status}|{practice}"] = cell
    path.write_text(json.dumps(out, indent=1) + "\n")
    return out


def load(path: Path = TABLE) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def lookup(table: dict, pos: str, status: str | None, practice: str | None) -> dict | None:
    """The best-supported cell for a player, or None when he is not on the report."""
    st = ESPN_STATUS.get((status or "").upper())
    pr = practice if practice in ("DNP", "LP", "FP") else "none"
    if st is None and pr == "none":
        return None
    st = st or "none"
    cells = table.get("cells") or {}
    for key in (f"{pos}|{st}|{pr}", f"ALL|{st}|{pr}", f"{pos}|{st}|*", f"ALL|{st}|*"):
        c = cells.get(key)
        if c and c["n"] >= MIN_N:
            return {"cell": key, **c}
    return None


def current_cached(season: int, week: int, ttl: float = 3600.0) -> dict[str, str]:
    """current(), kept an hour in .cache/practice-<season>-wNN.json, so a
    watcher that runs every 15 minutes does not refetch the report each time."""
    import time  # noqa: PLC0415

    path = HERE.parent / ".cache" / f"practice-{season}-w{week:02d}.json"
    try:
        if path.exists() and time.time() - path.stat().st_mtime < ttl:
            return json.loads(path.read_text())
        out = current(season, week)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out))
        return out
    except Exception as e:  # noqa: BLE001 - the lineup check runs without practice data
        print(f"injury: practice report unavailable ({e})", file=sys.stderr)
        return {}


def current(season: int, week: int) -> dict[str, str]:
    """ESPN player id -> practice code (DNP, LP, FP) from nflverse's in-week
    report, joined through the cross-site id table. Joined on ids, never
    names: "D.J. Moore" and "DJ Moore" are one player and two strings."""
    import nflreadpy as nfl  # noqa: PLC0415
    import polars as pl  # noqa: PLC0415

    sys.path.insert(0, str(HERE.parent))
    from ffmodel import nflraw  # noqa: PLC0415

    try:
        inj = nfl.load_injuries(seasons=[season]).filter(pl.col("week") == week)
    except Exception:  # noqa: BLE001 -- no report yet means no practice information
        return {}
    ids = nflraw.id_table().select(["gsis_id", "espn_id"]).filter(
        pl.col("gsis_id").is_not_null() & pl.col("espn_id").is_not_null()).unique("gsis_id")
    rows = inj.select(["gsis_id", "practice_status"]).join(ids, on="gsis_id", how="inner").to_dicts()
    return {str(r["espn_id"]): code for r in rows if (code := PRACTICE.get(r["practice_status"] or ""))}


if __name__ == "__main__":
    t = build()
    print(f"injury: clean ratio {t['clean_ratio']}; {len(t['cells'])} cells -> {TABLE}")
    for key in sorted(t["cells"]):
        if key.startswith("ALL|") or key.endswith("|*"):
            c = t["cells"][key]
            print(f"  {key:16} n {c['n']:6d}  P(play) {c['p_play']:.3f} {c['ci']}  ratio {c.get('ratio', '-')} (n {c.get('ratio_n', '-')})")
