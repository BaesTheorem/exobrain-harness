"""nflraw: nflverse box scores scored the way this league scores them.

Every model in this package starts here, so there is one scoring function and
one team-abbreviation map. The source is nflverse through nflreadpy (player
and team box scores, schedules with closing lines, the cross-site id table);
nothing here reads another site's projection.

    player_weeks(seasons)  one row per player-game, QB/RB/WR/TE/K, with the
                           box-score components and `pts` on league scoring
    dst_weeks(seasons)     one row per team-game for the defense/special teams
    games(seasons)         regular-season games with the closing spread and
                           total, and each side's implied points
    id_table()             gsis id <-> ESPN id <-> Sleeper id, name, position
    sleeper_weeks(seasons) Sleeper's archived weekly projections (2022 on),
                           rescored from their stat components on league
                           scoring: the pre-game expectation the residual
                           models subtract. The one projection read here.

Team abbreviations come out in ESPN's spelling (LAR, WSH), because every
other tool here joins on ESPN's.

Checked against ESPN's own weekly actuals for every player rostered in the
league, 2026 weeks 1-5: QB/RB/WR/TE/K exact on 854 of 854 player-weeks, D/ST
exact on 66 of 72 (mean -0.15; nflverse misses an occasional sack or a
return touchdown that ESPN credits).

Parquet caches live in .cache/nflraw/. A finished season is cached for good;
the current season is refetched after CURRENT_TTL, since nflverse posts each
week a day after the games.

INVARIANTS
- League scoring lives in SCORING, K_POINTS, PA_BRACKETS and YA_BRACKETS and
  nowhere else. `espn settings` is the source; tests/test_fantasy_model.py
  plants a box score with a known ESPN total for each position group.
- Read-only. The only files written are under .cache/nflraw/.
"""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / ".cache" / "nflraw"
CURRENT_TTL = 12 * 3600
TEAM_ESPN = {"LA": "LAR", "WAS": "WSH", "STL": "LAR", "SD": "LAC", "OAK": "LV"}
POS_MAP = {"FB": "RB", "HB": "RB"}
SKILL = ("QB", "RB", "WR", "TE")

# Offense, per `espn settings` (2026-10-15). Full PPR, 4-point passing TD.
SCORING = {
    "passing_yards": 0.04, "passing_tds": 4.0, "passing_interceptions": -2.0,
    "passing_2pt_conversions": 2.0,
    "rushing_yards": 0.1, "rushing_tds": 6.0, "rushing_2pt_conversions": 2.0,
    "receiving_yards": 0.1, "receiving_tds": 6.0, "receiving_2pt_conversions": 2.0,
    "receptions": 1.0,
    "fumbles_lost": -2.0, "special_teams_tds": 6.0, "fumble_recovery_tds": 6.0,
}
# Kicking is scored by distance; a miss of any length is -1, a PAT is 1.
K_POINTS = {"fg_made_0_19": 3.0, "fg_made_20_29": 3.0, "fg_made_30_39": 3.0,
            "fg_made_40_49": 4.0, "fg_made_50_59": 5.0, "fg_made_60_": 6.0,
            "fg_missed_total": -1.0, "pat_made": 1.0}
# D/ST: (upper bound inclusive, points). Points allowed 18-27 and yards
# allowed 300-349 score nothing.
PA_BRACKETS = ((0, 5.0), (6, 4.0), (13, 3.0), (17, 1.0), (27, 0.0), (34, -1.0), (45, -3.0), (10**6, -5.0))
YA_BRACKETS = ((99, 5.0), (199, 3.0), (299, 2.0), (349, 0.0), (399, -1.0), (449, -3.0),
               (499, -5.0), (549, -6.0), (10**6, -7.0))
DST_EVENT = {"def_sacks": 1.0, "def_interceptions": 2.0, "fumble_recovery_opp": 2.0,
             "def_safeties": 2.0, "blocks": 2.0, "dst_tds": 6.0}


def current_season(today: date | None = None) -> int:
    t = today or date.today()
    return t.year if t.month >= 8 else t.year - 1


def _cached(name: str, season: int, build) -> Any:
    import polars as pl  # noqa: PLC0415 -- heavy import, only the data path needs it

    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}-{season}.parquet"
    fresh = path.exists() and (season < current_season() or time.time() - path.stat().st_mtime < CURRENT_TTL)
    if fresh:
        return pl.read_parquet(path)
    df = build(season)
    df.write_parquet(path)
    return df


def _team(col):
    import polars as pl  # noqa: PLC0415

    expr = pl.col(col)
    for a, b in TEAM_ESPN.items():
        expr = pl.when(pl.col(col) == a).then(pl.lit(b)).otherwise(expr)
    return expr


def bracket(value: float, table: tuple[tuple[int, float], ...]) -> float:
    for hi, pts in table:
        if value <= hi:
            return pts
    return table[-1][1]


def offense_points(row: dict) -> float:
    """League points for one box-score row (offense and kicking)."""
    pts = sum(float(row.get(k) or 0.0) * v for k, v in SCORING.items())
    pts += sum(float(row.get(k) or 0.0) * v for k, v in K_POINTS.items())
    return round(pts, 2)


def dst_points(row: dict) -> float:
    pts = bracket(float(row["pa"]), PA_BRACKETS) + bracket(float(row["ya"]), YA_BRACKETS)
    pts += sum(float(row.get(k) or 0.0) * v for k, v in DST_EVENT.items())
    return round(pts, 2)


def _build_players(season: int):
    import nflreadpy as nfl  # noqa: PLC0415
    import polars as pl  # noqa: PLC0415

    ps = nfl.load_player_stats(seasons=[season]).filter(pl.col("season_type") == "REG")
    ps = ps.with_columns(
        (pl.col("sack_fumbles_lost").fill_null(0) + pl.col("rushing_fumbles_lost").fill_null(0)
         + pl.col("receiving_fumbles_lost").fill_null(0)).alias("fumbles_lost"),
        (pl.col("fg_att").fill_null(0) - pl.col("fg_made").fill_null(0)).alias("fg_missed_total"),
        pl.col("position").replace(POS_MAP).alias("pos"),
    ).filter(pl.col("pos").is_in([*SKILL, "K"]))
    keep = ["season", "week", "game_id", "player_id", "player_display_name", "pos", "team", "opponent_team",
            "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
            "carries", "rushing_yards", "rushing_tds", "targets", "receptions", "receiving_yards",
            "receiving_tds", "target_share", "air_yards_share", "wopr", "receiving_air_yards",
            "fg_att", "fg_made", "pat_made", *SCORING.keys(), *K_POINTS.keys()]
    keep = list(dict.fromkeys(c for c in keep if c in ps.columns))
    ps = ps.select(keep)
    pts = [offense_points(r) for r in ps.to_dicts()]
    return ps.with_columns(pl.Series("pts", pts), _team("team").alias("team"),
                           _team("opponent_team").alias("opp")).rename(
        {"player_display_name": "name"}).drop("opponent_team")


def player_weeks(seasons: list[int]):
    import polars as pl  # noqa: PLC0415

    return pl.concat([_cached("players", s, _build_players) for s in seasons], how="diagonal_relaxed")


def _build_games(season: int):
    import nflreadpy as nfl  # noqa: PLC0415
    import polars as pl  # noqa: PLC0415

    g = nfl.load_schedules(seasons=[season]).filter(pl.col("game_type") == "REG")
    # nflverse spread_line is the home margin the market expects (positive =
    # home favored); result = home_score - away_score. Checked in the tests.
    g = g.with_columns(
        ((pl.col("total_line") + pl.col("spread_line")) / 2).alias("implied_home"),
        ((pl.col("total_line") - pl.col("spread_line")) / 2).alias("implied_away"),
        _team("home_team").alias("home"), _team("away_team").alias("away"),
    )
    return g.select(["game_id", "season", "week", "gameday", "home", "away", "home_score", "away_score",
                     "spread_line", "total_line", "implied_home", "implied_away", "roof", "temp", "wind",
                     "espn", "home_moneyline", "away_moneyline"])


def games(seasons: list[int]):
    import polars as pl  # noqa: PLC0415

    return pl.concat([_cached("games", s, _build_games) for s in seasons], how="diagonal_relaxed")


def _build_dst(season: int):
    import nflreadpy as nfl  # noqa: PLC0415
    import polars as pl  # noqa: PLC0415

    ts = nfl.load_team_stats(seasons=[season]).filter(pl.col("season_type") == "REG")
    ts = ts.with_columns(_team("team").alias("team"), _team("opponent_team").alias("opp"))
    # ESPN's yards allowed is the opponent's net yards: passing less sack
    # yardage, plus rushing (BAL week 1 2026: 166 - 17 + 102 = 251, ESPN 251).
    # nflverse stores sack_yards_lost negative, so take its size explicitly.
    # ESPN's points allowed leaves out the opponent's defensive and return
    # touchdowns (SEA week 3 2026: 33 on the board, ESPN 27).
    off = ts.select(["game_id", "team",
                     (pl.col("passing_yards").fill_null(0) - pl.col("sack_yards_lost").fill_null(0).abs()
                      + pl.col("rushing_yards").fill_null(0)).alias("off_yards"),
                     (6 * (pl.col("def_tds").fill_null(0) + pl.col("special_teams_tds").fill_null(0))).alias("nonoff_pts")])
    d = ts.select(["season", "week", "game_id", "team", "opp", "def_sacks", "def_interceptions",
                   "fumble_recovery_opp", "def_safeties",
                   (pl.col("def_punt_blocks").fill_null(0) + pl.col("def_fg_blocks").fill_null(0)
                    + pl.col("def_pat_blocks").fill_null(0)).alias("blocks"),
                   (pl.col("def_tds").fill_null(0) + pl.col("special_teams_tds").fill_null(0)).alias("dst_tds")])
    d = d.join(off.rename({"team": "opp", "off_yards": "ya", "nonoff_pts": "opp_nonoff"}), on=["game_id", "opp"], how="left")
    g = _build_games(season)
    score = pl.concat([
        g.select(["game_id", pl.col("home").alias("team"), pl.col("away_score").alias("pa"),
                  pl.col("implied_away").alias("opp_implied")]),
        g.select(["game_id", pl.col("away").alias("team"), pl.col("home_score").alias("pa"),
                  pl.col("implied_home").alias("opp_implied")]),
    ])
    d = d.join(score, on=["game_id", "team"], how="left").filter(pl.col("pa").is_not_null())
    d = d.with_columns(pl.col("pa").alias("pa_board"),
                       (pl.col("pa") - pl.col("opp_nonoff").fill_null(0)).clip(lower_bound=0).alias("pa"))
    pts = [dst_points(r) for r in d.fill_null(0).to_dicts()]
    return d.with_columns(pl.Series("pts", pts), pl.lit("D/ST").alias("pos"))


def dst_weeks(seasons: list[int]):
    import polars as pl  # noqa: PLC0415

    return pl.concat([_cached("dst", s, _build_dst) for s in seasons], how="diagonal_relaxed")


def id_table():
    """gsis_id, espn_id, sleeper_id, name, position. One file, refreshed weekly."""
    import nflreadpy as nfl  # noqa: PLC0415
    import polars as pl  # noqa: PLC0415

    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "ids.parquet"
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        return pl.read_parquet(path)
    ids = nfl.load_ff_playerids().select(["gsis_id", "espn_id", "sleeper_id", "name", "position", "team"])
    ids = ids.with_columns(pl.col("espn_id").cast(pl.Utf8), pl.col("sleeper_id").cast(pl.Utf8))
    ids.write_parquet(path)
    return ids


SLEEPER_KEYS = {
    "pass_yd": "passing_yards", "pass_td": "passing_tds", "pass_int": "passing_interceptions",
    "pass_2pt": "passing_2pt_conversions", "rush_yd": "rushing_yards", "rush_td": "rushing_tds",
    "rush_2pt": "rushing_2pt_conversions", "rec_yd": "receiving_yards", "rec_td": "receiving_tds",
    "rec_2pt": "receiving_2pt_conversions", "rec": "receptions", "fum_lost": "fumbles_lost",
    "st_td": "special_teams_tds", "fgm_0_19": "fg_made_0_19", "fgm_20_29": "fg_made_20_29",
    "fgm_30_39": "fg_made_30_39", "fgm_40_49": "fg_made_40_49", "fgm_50p": "fg_made_50_59",
    "xpm": "pat_made",
}
SLEEPER_POS = ("QB", "RB", "WR", "TE", "K", "DEF")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def sleeper_points(pos: str, st: dict) -> float:
    """League points from one Sleeper projection's stat components.

    Sleeper's own pts_ppr is on Sleeper's default scoring (a different
    interception and bonus table), so it is never used. A D/ST projection is
    a mean points-allowed and yards-allowed, so the bracket is applied to the
    mean: close enough for a residual, and labelled as such where it is used."""
    if pos == "DEF":
        return dst_points({"pa": st.get("pts_allow") or 0.0, "ya": st.get("yds_allow") or 0.0,
                           "def_sacks": st.get("sack"), "def_interceptions": st.get("int"),
                           "fumble_recovery_opp": st.get("fum_rec"), "def_safeties": st.get("safe"),
                           "blocks": st.get("blk_kick"),
                           "dst_tds": float(st.get("def_td") or 0) + float(st.get("def_kr_td") or 0)
                           + float(st.get("def_pr_td") or 0)})
    row = {v: st.get(k) for k, v in SLEEPER_KEYS.items()}
    if pos == "K":
        row["fg_missed_total"] = max(0.0, float(st.get("fga") or 0) - float(st.get("fgm") or 0))
    return offense_points(row)


def _build_sleeper(season: int, weeks: range = range(1, 19)):
    import json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    import polars as pl  # noqa: PLC0415

    pos = "&".join(f"position[]={p}" for p in SLEEPER_POS)
    out = []
    for w in weeks:
        url = f"https://api.sleeper.app/projections/nfl/{season}/{w}?season_type=regular&{pos}"
        try:
            rows = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40))
        except Exception as exc:  # noqa: BLE001 -- a missing week is recorded as missing, not fatal
            print(f"nflraw: sleeper {season} week {w}: {exc}", file=sys.stderr)
            continue
        for r in rows:
            st = r.get("stats") or {}
            p = r.get("player") or {}
            ppos = p.get("position") or ""
            if ppos not in SLEEPER_POS or not st:
                continue
            if not (st.get("gp") or st.get("pass_att") or st.get("rec_tgt") or st.get("rush_att")
                    or st.get("fga") or st.get("pts_allow")):
                continue
            team = str(r.get("team") or p.get("team") or "")
            out.append({"season": season, "week": w, "sleeper_id": str(r.get("player_id")),
                        "pos": "D/ST" if ppos == "DEF" else ppos,
                        "team": TEAM_ESPN.get(team, team) or None, "proj": sleeper_points(ppos, st),
                        "proj_rec": st.get("rec"), "proj_tgt": st.get("rec_tgt"),
                        "proj_rush_att": st.get("rush_att"), "proj_pass_att": st.get("pass_att")})
    return pl.DataFrame(out, infer_schema_length=None)


def sleeper_weeks(seasons: list[int]):
    """Sleeper weekly projections on league scoring, with gsis_id joined where
    the id table knows the player (D/ST rows keep their team instead)."""
    import polars as pl  # noqa: PLC0415

    df = pl.concat([_cached("sleeperproj", s, _build_sleeper) for s in seasons], how="diagonal_relaxed")
    ids = id_table().select(["sleeper_id", "gsis_id"]).filter(pl.col("sleeper_id").is_not_null()).unique("sleeper_id")
    return df.join(ids, on="sleeper_id", how="left")


if __name__ == "__main__":
    seasons = [int(s) for s in sys.argv[1:]] or [current_season()]
    p, d, g = player_weeks(seasons), dst_weeks(seasons), games(seasons)
    print(f"players {p.shape}  dst {d.shape}  games {g.shape}")
