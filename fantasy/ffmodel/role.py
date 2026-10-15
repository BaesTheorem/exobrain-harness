"""role: a weekly projection built from a player's opportunity, not from another site's number.

What it answers: how many league points does this player's role give him
this week? The model has three parts, and each part reads only box scores,
snap counts, play-by-play and the closing line:

1. Team volume. Targets, carries, pass attempts and offensive touchdowns
   for the team in this game, from the closing spread and total (linear,
   fitted on other seasons), plus the team's own tendency, filtered with a
   discount and shrunk toward zero.
2. Shares. The player's share of each volume: targets, carries, pass
   attempts, red-zone targets (inside the 20) and goal-line carries (inside
   the 10). Each share is a Beta-Binomial whose past games are discounted
   (a state-space filter in closed form). The prior mean is the position's
   rate per unit of participation times the player's filtered participation
   (snap share; in the historical variant, routes, counted as pass plays
   with the player on the field). Thus a player who plays 90% of the snaps
   starts at a starter's share, and a player who plays 20% starts at a
   reserve's share. The prior strength, the discount and the carry-over
   from last season are fitted by the held-out Beta-Binomial predictive
   likelihood. Red-zone and goal-line shares are centered on the player's
   own target and carry shares.
3. Points per opportunity. Non-touchdown points per target, per carry and
   per pass attempt, shrunk toward the position mean with a prior weight
   fitted on other seasons (efficiency is mostly noise).

    E[pts] = volume x share x points per opportunity, summed over
             targets, carries and pass attempts, + touchdown expectation;
             then one linear calibration per position, fitted on other
             seasons.

Variants (the prior of the target share): "plain" (the position mean, no
participation), "base" (snap share, available in-season) and "routes"
(pass-play participation from nflverse participation data, 2016-2025 only).

    load(seasons, routes, through)      player-game and team-game frames
    fit(data, train, variant)           every fitted number, from `train`
    project(data, params)               E[points] for every player-game row
    week_projection(season, week)       gsis_id -> points, from data before
                                        that week
    live(season, week)                  the same for the current season

Measured in research/role_eval.py (2022-2025, weeks 4-17, walk-forward;
numbers in the vault note "Fantasy Football Role Model 2026-10-15"). MAE
4.51 against Sleeper's 4.35 (equal to Sleeper for quarterbacks). Added to
the Sleeper+market blend it changes MAE by +0.002 (95% CI -0.009 to
+0.014), thus it is a research artifact and not a vote. Routes beat snap
share by 0.004, all of it at tight end.

INVARIANTS
- No leakage. A row's projection reads only earlier games: every filter is
  a causal recursion over games played, and week_projection() cuts every
  input at week - 1 before it estimates. The only same-week inputs are
  the closing line and the weekly roster, both public before kickoff.
  tests/test_fantasy_role.py changes future box scores and checks that the
  projection does not move.
- fit() learns only from the seasons in `train`. role_eval passes seasons
  before the projected one (walk-forward).
- League point values come from nflraw.SCORING, never a copy.
- This module writes nothing to disk (nflraw keeps its own caches). One
  season of play-by-play or participation is in memory at a time, and only
  the columns used.
"""

from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download/"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
POS = ("QB", "RB", "WR", "TE")
FIRST_FIT = 2019                 # earliest season fit() learns from
RZ_YARDS, GL_YARDS = 20, 10      # red zone (targets), goal line (carries)
FIT_WEEKS = (4, 17)              # the weeks each fit scores, as in the evaluation
DEFAULT_IMPLIED = 22.0
# Grids for the share filters. The first grid stopped at lambda 0.5 and
# strength 1, and the snap share, the running back's carry share and the
# quarterback's pass-attempt share chose that corner. On this grid they
# choose lambda 0.2, the edge again: last game's role is the best guide to
# this game's. Moving the edge from 0.5 to 0.2 changed the evaluation MAE by
# 0.002, thus the grid stops here.
LAMS = (0.2, 0.35, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0)   # discount per game played
DELTAS = (0.0, 0.25, 0.5, 1.0)                      # carry-over per season boundary
STRENGTHS = (0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024)
EFF_K = (5.0, 20.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0, 1e9)
TEAM_K = (1.0, 2.0, 4.0, 8.0, 16.0, 1e9)
VARIANTS = ("plain", "base", "routes")
VOLUME = ("T_tgt", "T_car", "T_att", "T_ptd", "T_rtd")
COUNTS = ("targets", "carries", "attempts", "rz_tgt", "gl_car", "snaps", "routes")
TEAM_COUNTS = ("T_tgt", "T_car", "T_att", "T_db", "T_rz", "T_gl", "T_ptd", "T_rtd", "T_ptd_rz", "T_rtd_gl",
               "T_snaps", "T_db_part")
PBP_COLS = ["play_id", "game_id", "season_type", "week", "posteam", "yardline_100", "two_point_attempt",
            "qb_dropback", "rush_attempt", "pass_attempt", "sack", "receiver_player_id", "rusher_player_id",
            "pass_touchdown", "rush_touchdown"]


# ---- data -----------------------------------------------------------------------

def _nflraw():
    sys.path.insert(0, str(HERE.parent))
    from ffmodel import nflraw  # noqa: PLC0415

    return nflraw


def _parquet(path: str, columns: list[str]):
    """One nflverse release file, only `columns` decoded. Not cached."""
    import io  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    import polars as pl  # noqa: PLC0415

    req = urllib.request.Request(NFLVERSE + path, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        raw = r.read()
    return pl.read_parquet(io.BytesIO(raw), columns=columns)


def _espn(col: str):
    import polars as pl  # noqa: PLC0415

    return pl.col(col).replace(_nflraw().TEAM_ESPN)


def _pbp(season: int, last: int):
    import polars as pl  # noqa: PLC0415

    p = _parquet(f"pbp/play_by_play_{season}.parquet", PBP_COLS)
    p = p.filter((pl.col("season_type") == "REG") & pl.col("posteam").is_not_null()
                 & (pl.col("two_point_attempt").fill_null(0) == 0) & (pl.col("week") <= last))
    return p.with_columns(_espn("posteam").alias("team"), pl.col("play_id").cast(pl.Int64),
                          pl.col("week").cast(pl.Int64)).drop(["season_type", "posteam", "two_point_attempt"])


def _from_pbp(p):
    """Team totals per team-game, and red-zone targets and goal-line carries
    per player-game."""
    import polars as pl  # noqa: PLC0415

    tgt = pl.col("receiver_player_id").is_not_null()
    car = (pl.col("rush_attempt") == 1) & pl.col("rusher_player_id").is_not_null()
    rz = pl.col("yardline_100") <= RZ_YARDS
    gl = pl.col("yardline_100") <= GL_YARDS
    ptd = pl.col("pass_touchdown").fill_null(0)
    rtd = pl.col("rush_touchdown").fill_null(0)
    team = p.group_by(["week", "team"]).agg(
        tgt.sum().alias("T_tgt"), car.sum().alias("T_car"),
        ((pl.col("pass_attempt") == 1) & (pl.col("sack").fill_null(0) == 0)).sum().alias("T_att"),
        (pl.col("qb_dropback") == 1).sum().alias("T_db"),
        (tgt & rz).sum().alias("T_rz"), (car & gl).sum().alias("T_gl"),
        ptd.sum().alias("T_ptd"), rtd.sum().alias("T_rtd"),
        pl.when(rz).then(ptd).otherwise(0).sum().alias("T_ptd_rz"),
        pl.when(gl).then(rtd).otherwise(0).sum().alias("T_rtd_gl"))
    rzt = p.filter(tgt & rz).group_by(["week", "receiver_player_id"]).len("rz_tgt").rename(
        {"receiver_player_id": "player_id"})
    glc = p.filter(car & gl).group_by(["week", "rusher_player_id"]).len("gl_car").rename(
        {"rusher_player_id": "player_id"})
    return team, rzt, glc


def _roster(season: int):
    import polars as pl  # noqa: PLC0415

    r = _parquet(f"weekly_rosters/roster_weekly_{season}.parquet",
                 ["season", "week", "team", "position", "status", "gsis_id", "pfr_id", "game_type"])
    return r.filter(pl.col("gsis_id").is_not_null()).with_columns(
        _espn("team").alias("team"), pl.col("week").cast(pl.Int64), pl.col("season").cast(pl.Int64),
        pl.col("position").replace(_nflraw().POS_MAP).alias("pos"))


@functools.cache
def _pfr_ids():
    """pfr id -> gsis id from the ffverse id table. The weekly roster alone
    leaves 4% of skill-player games without snaps; the two together, 0.1%."""
    import nflreadpy as nfl  # noqa: PLC0415
    import polars as pl  # noqa: PLC0415

    ids = nfl.load_ff_playerids().select(["pfr_id", "gsis_id"]).drop_nulls().unique("pfr_id")
    nfl.clear_cache()
    return ids.with_columns(pl.col("pfr_id").cast(pl.Utf8), pl.col("gsis_id").cast(pl.Utf8))


def _snaps(season: int, last: int, roster):
    """Offensive snaps per player-game (gsis id) and per team-game."""
    import polars as pl  # noqa: PLC0415

    s = _parquet(f"snap_counts/snap_counts_{season}.parquet",
                 ["game_type", "week", "pfr_player_id", "team", "offense_snaps"])
    s = s.filter((pl.col("game_type") == "REG") & (pl.col("week") <= last)).with_columns(
        _espn("team").alias("team"), pl.col("week").cast(pl.Int64))
    team = s.group_by(["week", "team"]).agg(pl.col("offense_snaps").max().alias("T_snaps"))
    ids = pl.concat([roster.select(["pfr_id", "gsis_id"]).drop_nulls(), _pfr_ids()]).unique("pfr_id")
    player = s.join(ids, left_on="pfr_player_id", right_on="pfr_id", how="inner").group_by(
        ["week", "gsis_id"]).agg(pl.col("offense_snaps").sum().alias("snaps")).rename({"gsis_id": "player_id"})
    return player, team


def _routes(season: int, p):
    """Routes run per player-game, counted as dropbacks with the player on the
    field, and the team dropbacks that have participation data."""
    import polars as pl  # noqa: PLC0415

    part = _parquet(f"pbp_participation/pbp_participation_{season}.parquet",
                    ["nflverse_game_id", "play_id", "offense_players"])
    part = part.with_columns(pl.col("play_id").cast(pl.Int64)).rename({"nflverse_game_id": "game_id"})
    db = p.filter(pl.col("qb_dropback") == 1).select(["game_id", "play_id", "week", "team"])
    j = db.join(part, on=["game_id", "play_id"], how="inner").filter(
        pl.col("offense_players").is_not_null() & (pl.col("offense_players").str.len_chars() > 0))
    team = j.group_by(["week", "team"]).len("T_db_part")
    player = j.select(["week", pl.col("offense_players").str.split(";").alias("player_id")]).explode(
        "player_id").group_by(["week", "player_id"]).len("routes")
    return player, team


def _lines(season: int):
    """One row per team-game of the regular season with the closing line
    from the team's side: implied points and expected margin."""
    import polars as pl  # noqa: PLC0415

    g = _nflraw().games([season])
    cols = ["season", "week"]
    home = g.select([*cols, pl.col("home").alias("team"), pl.col("implied_home").alias("implied"),
                     pl.col("spread_line").alias("spread")])
    away = g.select([*cols, pl.col("away").alias("team"), pl.col("implied_away").alias("implied"),
                     (-pl.col("spread_line")).alias("spread")])
    return pl.concat([home, away]).with_columns(pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64))


def load_season(season: int, routes: bool = False, through: int | None = None) -> dict:
    """One season: `players` (one row per player-game, QB/RB/WR/TE, with the
    box score, red-zone and goal-line counts, snaps and routes), `teams` (one
    row per team-game of the schedule, with the closing line and, for games
    played through `through`, the team totals) and the weekly `roster`."""
    import polars as pl  # noqa: PLC0415

    nflraw = _nflraw()
    last = 99 if through is None else through
    sc = nflraw.SCORING
    pw = nflraw.player_weeks([season]).filter(pl.col("pos").is_in(POS) & (pl.col("week") <= last))
    pw = pw.select([
        pl.col("season").cast(pl.Int64), pl.col("week").cast(pl.Int64), "player_id", "name", "pos", "team",
        *[pl.col(c).fill_null(0).cast(pl.Float64) for c in ("targets", "carries", "attempts")],
        (pl.col("receptions").fill_null(0) * sc["receptions"]
         + pl.col("receiving_yards").fill_null(0) * sc["receiving_yards"]).alias("rec_y"),
        (pl.col("rushing_yards").fill_null(0) * sc["rushing_yards"]).alias("rush_y"),
        (pl.col("passing_yards").fill_null(0) * sc["passing_yards"]
         + pl.col("passing_interceptions").fill_null(0) * sc["passing_interceptions"]).alias("pass_y"),
        "pts"])
    pbp = _pbp(season, last)
    team, rzt, glc = _from_pbp(pbp)
    roster = _roster(season)
    snap_p, snap_t = _snaps(season, last, roster)
    route_p = route_t = None
    if routes:
        route_p, route_t = _routes(season, pbp)
    del pbp
    players = pw.join(rzt, on=["week", "player_id"], how="left").join(glc, on=["week", "player_id"], how="left")
    players = players.join(snap_p, on=["week", "player_id"], how="left")
    team = team.join(snap_t, on=["week", "team"], how="left")
    if route_p is not None and route_t is not None:
        players = players.join(route_p, on=["week", "player_id"], how="left")
        team = team.join(route_t, on=["week", "team"], how="left")
    else:
        players = players.with_columns(pl.lit(None, dtype=pl.Float64).alias("routes"))
        team = team.with_columns(pl.lit(None, dtype=pl.Float64).alias("T_db_part"))
    teams = _lines(season).join(team, on=["week", "team"], how="left")
    teams = teams.with_columns(pl.col("T_tgt").is_not_null().alias("played"),
                               *[pl.col(c).cast(pl.Float64) for c in TEAM_COUNTS])
    players = players.with_columns(*[pl.col(c).cast(pl.Float64) for c in ("rz_tgt", "gl_car", "snaps", "routes")],
                                   pl.lit(False).alias("query"))
    return {"players": players, "teams": teams, "roster": roster}


def load(seasons, routes: bool = False, through: tuple[int, int] | None = None) -> dict:
    """load_season for each season, one at a time, concatenated. through =
    (season, week): the last game week kept in that season."""
    import polars as pl  # noqa: PLC0415

    parts = []
    for s in seasons:
        last = through[1] if through and s == through[0] else None
        if through and s > through[0]:
            continue
        parts.append(load_season(s, routes, last))
    return {k: pl.concat([p[k] for p in parts], how="diagonal_relaxed") for k in ("players", "teams", "roster")}


def truncate(data: dict, season: int, week: int) -> dict:
    """The data as it stood before `week` of `season`: later box scores,
    snaps and team totals removed; the closing lines of that week kept."""
    import polars as pl  # noqa: PLC0415

    before = (pl.col("season") < season) | ((pl.col("season") == season) & (pl.col("week") < week))
    now = (pl.col("season") == season) & (pl.col("week") == week)
    teams = data["teams"].filter(before | now).with_columns(
        *[pl.when(now).then(None).otherwise(pl.col(c)).alias(c) for c in TEAM_COUNTS],
        pl.when(now).then(False).otherwise(pl.col("played")).alias("played"))
    return {"players": data["players"].filter(before & ~pl.col("query")), "teams": teams,
            "roster": data["roster"]}


# ---- the filter -------------------------------------------------------------------

class Panel:
    """Rows sorted by (key, season, week). state(v) is, for each row, the
    discounted sum of v over the same key's EARLIER rows: weight lam per
    game, times delta per season boundary. The recursion never reads the
    row itself or a later row."""

    def __init__(self, keys, seasons) -> None:
        import numpy as np  # noqa: PLC0415

        k = np.asarray(keys)
        s = np.asarray(seasons, dtype=float)
        first = np.r_[True, k[1:] != k[:-1]] if k.size else np.zeros(0, dtype=bool)
        self.pidx = np.cumsum(first) - 1
        start = np.flatnonzero(first)
        self.slot = np.arange(k.size) - start[self.pidx] if k.size else np.zeros(0, dtype=int)
        gap = np.r_[0.0, s[1:] - s[:-1]] if k.size else np.zeros(0)
        gap[first] = 0.0
        self.first, self.gap = first, gap
        self.shape = (int(self.pidx.max()) + 1 if k.size else 0, int(self.slot.max()) + 1 if k.size else 0)

    def state(self, values, lam: float, delta: float):
        import numpy as np  # noqa: PLC0415

        v = np.zeros(self.shape)
        v[self.pidx, self.slot] = values
        m = np.zeros(self.shape)
        m[self.pidx, self.slot] = np.where(self.first, 0.0, lam * np.power(delta, self.gap))
        out = np.zeros(self.shape)
        for j in range(1, self.shape[1]):
            out[:, j] = m[:, j] * (out[:, j - 1] + v[:, j - 1])
        return out[self.pidx, self.slot]


def bb_loglik(n, big_n, a, b):
    """Beta-Binomial log pmf of n successes in big_n trials."""
    from scipy.special import betaln, gammaln  # noqa: PLC0415

    return (gammaln(big_n + 1) - gammaln(n + 1) - gammaln(big_n - n + 1)
            + betaln(n + a, big_n - n + b) - betaln(a, b))


def _ols(x, y, ridge: float = 1e-6):
    import numpy as np  # noqa: PLC0415

    pen = ridge * np.eye(x.shape[1])
    pen[0, 0] = 0.0
    return np.linalg.solve(x.T @ x + pen, x.T @ y)


# ---- the model ------------------------------------------------------------------------

def _arrays(data: dict) -> tuple[dict, dict, Any, Any]:
    """Sorted numpy views of the frames, the player and team panels, and the
    player row -> team row index."""
    import numpy as np  # noqa: PLC0415
    import polars as pl  # noqa: PLC0415

    teams = data["teams"].sort(["team", "season", "week"]).with_row_index("trow")
    players = data["players"].sort(["player_id", "season", "week"])
    players = players.join(teams.select(["season", "week", "team", "trow"]), on=["season", "week", "team"],
                           how="left").sort(["player_id", "season", "week"])
    players = players.filter(pl.col("trow").is_not_null())
    t: dict = {c: teams[c].fill_null(0).to_numpy().astype(float) for c in TEAM_COUNTS}
    t["implied"] = teams["implied"].fill_null(DEFAULT_IMPLIED).to_numpy().astype(float)
    t["spread"] = teams["spread"].fill_null(0.0).to_numpy().astype(float)
    t["played"] = teams["played"].fill_null(False).to_numpy().astype(bool)
    t["season"] = teams["season"].to_numpy()
    t["week"] = teams["week"].to_numpy()
    p: dict = {c: players[c].fill_null(0).to_numpy().astype(float)
               for c in (*COUNTS, "rec_y", "rush_y", "pass_y", "pts")}
    p["has_snaps"] = players["snaps"].is_not_null().to_numpy()
    p["has_routes"] = np.zeros(len(players), dtype=bool)  # set below from team coverage
    for c in ("season", "week", "pos", "player_id", "team", "query"):
        p[c] = players[c].to_numpy()
    p["trow"] = players["trow"].to_numpy().astype(int)
    for c in TEAM_COUNTS:
        p["N_" + c] = t[c][p["trow"]]
    p["played_team"] = t["played"][p["trow"]]
    # A player with no dropback on the field has no participation row: zero
    # routes, not missing, when the team-game has participation data.
    p["has_routes"] = p["N_T_db_part"] > 0
    tpanel = Panel(teams["team"].to_numpy(), t["season"])
    ppanel = Panel(p["player_id"], p["season"])
    return p, t, ppanel, tpanel


def _in_weeks(week) -> Any:
    return (week >= FIT_WEEKS[0]) & (week <= FIT_WEEKS[1])


def _volume(t: dict, tpanel: Panel, params: dict, train) -> dict:
    import numpy as np  # noqa: PLC0415

    x = np.column_stack([np.ones(t["implied"].size), t["implied"], t["spread"]])
    ones = t["played"].astype(float)
    fitting = train is not None
    if fitting:
        tr = np.isin(t["season"], list(train)) & t["played"]
        score = tr & _in_weeks(t["week"])
    out = {}
    for stat in VOLUME:
        y = t[stat]
        if fitting:
            b = _ols(x[tr], y[tr])
            r = np.where(t["played"], y - x @ b, 0.0)
            best: tuple = (np.inf,)
            for lam in LAMS:
                for d in (0.0, 0.5, 1.0):
                    big_r, w = tpanel.state(r, lam, d), tpanel.state(ones, lam, d)
                    for k in TEAM_K:
                        sse = float((((y - x @ b - big_r / (k + w)))[score] ** 2).sum())
                        if sse < best[0]:
                            best = (sse, lam, d, k)
            params["volume"][stat] = {"coef": [float(c) for c in b], "lam": best[1], "delta": best[2],
                                      "k": best[3], "mse": best[0] / max(int(score.sum()), 1)}
        h = params["volume"][stat]
        b = np.asarray(h["coef"])
        r = np.where(t["played"], y - x @ b, 0.0)
        big_r, w = tpanel.state(r, h["lam"], h["delta"]), tpanel.state(ones, h["lam"], h["delta"])
        out[stat] = np.maximum(0.0, x @ b + big_r / (h["k"] + w))
    return out


def _share(p: dict, panel: Panel, key: str, n, big_n, prior, params: dict, fit_mask) -> Any:
    """Posterior mean share per row: Beta(s * kappa * prior, s * (1 - kappa *
    prior)) updated with discounted successes and failures."""
    import numpy as np  # noqa: PLC0415

    n = np.minimum(n, big_n)
    fail = big_n - n
    store = params["share"].setdefault(key, {})
    if fit_mask is not None:
        masks, means = {}, {}
        for pos in POS:
            m = fit_mask & (p["pos"] == pos) & (big_n > 0)
            denom = float((prior[m] * big_n[m]).sum())
            kappa = float(n[m].sum()) / denom if denom > 0 else 0.0
            store[pos] = {"kappa": kappa, "lam": 1.0, "delta": 0.0, "s": STRENGTHS[-1], "ll": None,
                          "n": int(m.sum())}
            masks[pos], means[pos] = m, np.clip(kappa * prior, 1e-4, 0.97)
        best: dict = {pos: (-np.inf,) for pos in POS}
        for lam in LAMS:
            for d in DELTAS:
                a_, b_ = panel.state(n, lam, d), panel.state(fail, lam, d)
                for pos in POS:
                    m = masks[pos]
                    if m.sum() < 50 or store[pos]["kappa"] <= 0:
                        continue
                    nn, bn, aa, bb, mu = n[m], big_n[m], a_[m], b_[m], means[pos][m]
                    for s in STRENGTHS:
                        ll = float(bb_loglik(nn, bn, s * mu + aa, s * (1 - mu) + bb).sum())
                        if ll > best[pos][0]:
                            best[pos] = (ll, lam, d, s)
        for pos in POS:
            if len(best[pos]) > 1:
                ll, lam, d, s = best[pos]
                store[pos].update({"lam": lam, "delta": d, "s": s, "ll": ll})
    out = np.zeros(n.size)
    for pos in POS:
        h = store.get(pos)
        rows = p["pos"] == pos
        if not h or not rows.any():
            continue
        mu = np.clip(h["kappa"] * prior, 1e-4, 0.97)
        a_, b_ = panel.state(n, h["lam"], h["delta"]), panel.state(fail, h["lam"], h["delta"])
        out[rows] = ((h["s"] * mu + a_) / (h["s"] + a_ + b_))[rows]
    return out


def _efficiency(p: dict, panel: Panel, key: str, y, n, params: dict, fit_mask) -> Any:
    """Points per opportunity: (k * position mean + discounted points) /
    (k + discounted opportunities)."""
    import numpy as np  # noqa: PLC0415

    store = params["eff"].setdefault(key, {})
    if fit_mask is not None:
        masks = {}
        for pos in POS:
            m = fit_mask & (p["pos"] == pos)
            tot = float(n[m].sum())
            store[pos] = {"mu": float(y[m].sum()) / tot if tot > 0 else 0.0, "k": 1e9, "lam": 1.0, "delta": 0.0}
            masks[pos] = m & (n > 0)
        best: dict = {pos: (np.inf,) for pos in POS}
        for lam in (0.8, 0.9, 0.95, 1.0):
            for d in (0.0, 0.5, 1.0):
                yy, nn = panel.state(y, lam, d), panel.state(n, lam, d)
                for pos in POS:
                    m = masks[pos]
                    if m.sum() < 50:
                        continue
                    for k in EFF_K:
                        e = (k * store[pos]["mu"] + yy[m]) / (k + nn[m])
                        sse = float(((y[m] - n[m] * e) ** 2).sum())
                        if sse < best[pos][0]:
                            best[pos] = (sse, lam, d, k)
        for pos in POS:
            if len(best[pos]) > 1:
                store[pos].update({"lam": best[pos][1], "delta": best[pos][2], "k": best[pos][3]})
    out = np.zeros(n.size)
    for pos in POS:
        h = store.get(pos)
        rows = p["pos"] == pos
        if not h or not rows.any():
            continue
        yy, nn = panel.state(y, h["lam"], h["delta"]), panel.state(n, h["lam"], h["delta"])
        out[rows] = ((h["k"] * h["mu"] + yy) / (h["k"] + nn))[rows]
    return out


def _participation(p: dict, variant: str, snap, route) -> tuple[Any, Any]:
    """(prior scale for the target share, prior scale for carries and pass
    attempts) under each variant."""
    import numpy as np  # noqa: PLC0415

    ones = np.ones(snap.size)
    if variant == "plain":
        return ones, ones
    if variant == "routes":
        return route, snap
    return snap, snap


def _run(data: dict, params: dict, variant: str, train=None) -> dict:
    """Fit (when `train` is given) and project, through one code path."""
    import numpy as np  # noqa: PLC0415

    p, t, panel, tpanel = _arrays(data)
    nflraw = _nflraw()
    sc = nflraw.SCORING
    fit_mask = None
    if train is not None:
        fit_mask = np.isin(p["season"], list(train)) & _in_weeks(p["week"]) & ~p["query"].astype(bool)
        params.update({"variant": variant, "train": sorted(train), "volume": {}, "share": {}, "eff": {},
                       "calib": {}, "phi": {}})
        tr = np.isin(t["season"], list(train)) & t["played"]
        params["phi"] = {"rec": float(t["T_ptd_rz"][tr].sum() / max(t["T_ptd"][tr].sum(), 1.0)),
                         "rush": float(t["T_rtd_gl"][tr].sum() / max(t["T_rtd"][tr].sum(), 1.0))}
    vol = _volume(t, tpanel, params, train)
    ev = {k: v[p["trow"]] for k, v in vol.items()}

    snap_n = np.where(p["has_snaps"], p["snaps"], 0.0)
    snap_big = np.where(p["has_snaps"], p["N_T_snaps"], 0.0)
    snap = _share(p, panel, "snap", snap_n, snap_big, np.ones(snap_n.size), params, fit_mask)
    route = snap
    if variant == "routes":
        ok = p["has_routes"] & (p["N_T_db_part"] > 0)
        route = _share(p, panel, "route", np.where(ok, p["routes"], 0.0), np.where(ok, p["N_T_db_part"], 0.0),
                       np.ones(snap_n.size), params, fit_mask)
    tgt_prior, run_prior = _participation(p, variant, snap, route)
    th_tgt = _share(p, panel, "tgt", p["targets"], p["N_T_tgt"], tgt_prior, params, fit_mask)
    th_car = _share(p, panel, "car", p["carries"], p["N_T_car"], run_prior, params, fit_mask)
    th_att = _share(p, panel, "att", p["attempts"], p["N_T_att"], run_prior, params, fit_mask)
    th_rz = _share(p, panel, "rz", p["rz_tgt"], p["N_T_rz"], th_tgt, params, fit_mask)
    th_gl = _share(p, panel, "gl", p["gl_car"], p["N_T_gl"], th_car, params, fit_mask)

    e_rec = _efficiency(p, panel, "rec", p["rec_y"], p["targets"], params, fit_mask)
    e_rush = _efficiency(p, panel, "rush", p["rush_y"], p["carries"], params, fit_mask)
    e_pass = _efficiency(p, panel, "pass", p["pass_y"], p["attempts"], params, fit_mask)

    phi = params["phi"]
    comp = {
        "tgt": th_tgt * ev["T_tgt"], "car": th_car * ev["T_car"], "att": th_att * ev["T_att"],
        "rec_td": ev["T_ptd"] * (phi["rec"] * th_rz + (1 - phi["rec"]) * th_tgt),
        "rush_td": ev["T_rtd"] * (phi["rush"] * th_gl + (1 - phi["rush"]) * th_car),
        "pass_td": ev["T_ptd"] * th_att,
    }
    comp["rec"] = comp["tgt"] * e_rec
    comp["rush"] = comp["car"] * e_rush
    comp["pass"] = comp["att"] * e_pass
    comp["td_pts"] = comp["rec_td"] * sc["receiving_tds"] + comp["rush_td"] * sc["rushing_tds"]
    comp["pass_td_pts"] = comp["pass_td"] * sc["passing_tds"]
    raw = comp["rec"] + comp["rush"] + comp["pass"] + comp["td_pts"] + comp["pass_td_pts"]
    # Calibration: a + b * raw per position. A coefficient per component was
    # tried first; pass yards and pass touchdowns are nearly collinear for a
    # quarterback and their coefficients swung to 0.08 and 2.1.
    x = np.column_stack([np.ones(raw.size), raw])
    cal = np.zeros(raw.size)
    for pos in POS:
        rows = p["pos"] == pos
        if fit_mask is not None:
            m = fit_mask & rows
            params["calib"][pos] = [float(c) for c in _ols(x[m], p["pts"][m])] if m.sum() > 50 else None
        coef = params["calib"].get(pos)
        cal[rows] = np.maximum(0.0, x[rows] @ np.asarray(coef)) if coef else raw[rows]
    return {"season": p["season"], "week": p["week"], "player_id": p["player_id"], "pos": p["pos"],
            "team": p["team"], "query": p["query"], "pts": p["pts"], "raw": raw, "role": cal,
            "snap_share": snap, "route_share": route, "tgt_share": th_tgt, "car_share": th_car,
            "att_share": th_att, "rz_share": th_rz, "gl_share": th_gl, "e_tgt": comp["tgt"], "e_car": comp["car"],
            "e_att": comp["att"], "vol_tgt": ev["T_tgt"], "vol_car": ev["T_car"], "vol_att": ev["T_att"],
            "vol_ptd": ev["T_ptd"], "vol_rtd": ev["T_rtd"]}


def fit(data: dict, train, variant: str = "base") -> dict:
    """Every fitted number of the model, learned from the seasons in `train`
    only. `data` may hold other seasons too: earlier ones feed the
    carry-over, later ones are never read by a training row (the filters are
    causal) and are not scored."""
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}")
    params: dict = {}
    _run(data, params, variant, train=list(train))
    return params


def project(data: dict, params: dict) -> dict:
    """The pre-game projection for every player-game row of `data`, as numpy
    columns (role = calibrated points, raw = the structural sum)."""
    return _run(data, params, params["variant"])


# ---- one week -------------------------------------------------------------------------

def _universe(data: dict, season: int, week: int):
    """Players on an active roster for the week (the latest roster week at or
    before it), QB/RB/WR/TE."""
    import polars as pl  # noqa: PLC0415

    r = data["roster"].filter((pl.col("season") == season) & (pl.col("week") <= week)
                              & pl.col("pos").is_in(POS) & (pl.col("status") == "ACT"))
    if r.is_empty():
        return r.select(["gsis_id", "pos", "team"])
    wk = r["week"].max()
    return r.filter(pl.col("week") == wk).select(["gsis_id", "pos", "team"]).unique("gsis_id")


def week_projection(season: int, week: int, variant: str = "base", params: dict | None = None,
                    data: dict | None = None, universe=None) -> dict[str, float]:
    """gsis_id -> projected league points for `week` of `season`, from data
    before that week only. `data` (from load) is cut at week - 1 here, so a
    caller may pass a frame that already holds the week's results. `params`
    defaults to a fit on FIRST_FIT..season-1. `universe` is a frame with
    gsis_id, pos, team (default: the weekly roster)."""
    import polars as pl  # noqa: PLC0415

    routes = variant == "routes"
    if data is None:
        data = load(range(season - 1, season + 1), routes=routes, through=(season, week - 1))
    if params is None:
        hist = load(range(FIRST_FIT - 1, season), routes=routes)
        params = fit(hist, range(FIRST_FIT, season), variant)
        del hist
    past = truncate(data, season, week)
    uni = universe if universe is not None else _universe(data, season, week)
    if uni.is_empty():
        return {}
    q = uni.select([pl.lit(season, dtype=pl.Int64).alias("season"), pl.lit(week, dtype=pl.Int64).alias("week"),
                    pl.col("gsis_id").alias("player_id"), "pos", "team",
                    pl.lit(True).alias("query")])
    players = pl.concat([past["players"], q], how="diagonal_relaxed")
    out = project({"players": players, "teams": past["teams"], "roster": past["roster"]}, params)
    sel = out["query"].astype(bool)
    return {str(pid): round(float(v), 2) for pid, v in zip(out["player_id"][sel], out["role"][sel], strict=True)}


def live(season: int, week: int, params: dict | None = None) -> dict[str, float]:
    """week_projection for the current season. Participation data does not
    exist in-season, so this is the "base" variant (snap share)."""
    return week_projection(season, week, "base", params=params)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="role-based weekly projection")
    ap.add_argument("week", type=int)
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args()
    season = a.season or _nflraw().current_season()
    res = live(season, a.week)
    ids = _nflraw().id_table()
    names = {r["gsis_id"]: (r["name"], r["position"]) for r in ids.select(["gsis_id", "name", "position"]).to_dicts()}
    for pid, v in sorted(res.items(), key=lambda kv: -kv[1])[: a.top]:
        nm, ps = names.get(pid, (pid, "?"))
        print(f"{str(nm)[:24]:24} {ps or '?':3} {v:6.1f}")
