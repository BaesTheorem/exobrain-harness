"""One currency and one variance model for every in-season fantasy decision.

Two things every tool here used to re-derive on its own, each slightly
differently, now live in one place:

1. **Rest-of-season value per week** (`ros_rate`). ESPN's `season_proj` (stat
   id `10<season>`) is a REST-OF-SEASON total that ESPN moves in season, so
   the prior per game is that total over the games the player's team has
   left. Measured 2026-10-14, week 6: Josh Allen carried 281.1 against 370 in
   the draft room on 09-07 and 143 scored in five games, which only reads as
   12 games at 23.4. (The static preseason number is `12<season>`, 362.0 for
   Allen.) Until that date this divided by 17 and called the number static
   preseason, which shrank every prior by games-left/17 and, with the PPG
   below, let a scan rate Jayden Daniels under Jared Goff.
   Before week 5 the blend is half that prior and half ESPN's live weekly
   projection, which tracks role and matchup. From week 5 it is 0.45 weekly
   projection + 0.35 prior + 0.20 season points per game (ROS_WEIGHTS,
   2026-10-15). Until then week 5 dropped the weekly projection for PPG (the
   Harstad 50/50); the backtest on 2022-2025, each season held out, found
   that dropping the projection was the loss: rest-of-season error 2.49
   against 2.60 points a game (difference -0.104, 95% CI -0.139 to -0.071),
   better in all 12 held-out season-weeks. Expected points from play-by-play
   (nflverse xFP) added nothing once the projection was in. PPG divides by
   the games the player appeared in (`games_appeared`, from bin/volume's box
   scores) when they are known, so a week missed hurt is not a 0-point game;
   otherwise by his team's games. A weekly projection of zero (bye, OUT)
   falls back to half prior and half PPG, within 0.03 of the best two-input
   blend, so a bye week never halves a trade valuation. A missing input
   drops out and the weights of the rest are scaled up.

2. **Per-player weekly spread** (`player_sd`) and the win probability of a
   lineup against an opponent (`win_prob`, `best_swaps`). The playbook's
   variance rule (favorite wants floor, underdog wants ceiling) was applied by
   adjective until 2026-09-20; this turns it into a number. Each unlocked
   starter is a normal with mean = his expected points (row_mean) and sd =
   that mean x the position-and-tier coefficient of variation (CV_TABLE).
   A locked player is his banked actual with sd 0. The matchup is a normal
   difference of sums, so P(win) is one erf. Until 2026-10-15 the sd also
   carried a per-player multiplier from his own game logs; a player's spread
   is not a stable trait (split-half r 0.03, season to season 0.04), and the
   multiplier made next-season forecasts worse, so it is gone. `mults` stays
   as a parameter for planted tests and any future measured trait.

INVARIANTS
- Pure functions over dicts; nothing here touches the network or the write
  lane. Tests plant fixtures and check both directions of every rule.
- The position priors are the same numbers `forecast.py` uses for a fresh
  clone (it imports them from here), so the forecast and the lineup check
  never disagree about how wide a wide receiver is.
- `best_swaps` never proposes moving a locked player, in or out, and never a
  player whose status makes him unusable.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from espncli.client import norm

NFL_WEEKS = 17
BLEND_SWITCH_WEEK = 5     # the playbook's "from week 5 on" for the production half
PRIOR_CV = {"QB": 0.40, "RB": 0.65, "WR": 0.85, "TE": 0.95, "K": 0.55, "D/ST": 1.0}   # forecast.py fresh-clone gamma prior
# The spread of actual around projection by position and projection tier,
# variance-matched on Sleeper 2022-2023 and checked on 2024-2025
# (fantasy/research/rule_backtests.py spread, 2026-10-15). The table before
# it was IQR/1.349, which is right for a median band and too narrow for a
# sum of starters: on 2024-2025 it covered 46% at 50% and 88.5% at 90%
# (RMS z 1.28). This one covers 50% and 90.5% and improves the held-out log
# likelihood by 0.040 a player-week (95% CI 0.031 to 0.051).
TIERS = ((0.0, 7.0), (7.0, 13.0), (13.0, 1e9))
CV_TABLE = {
    "QB": (0.60, 0.60, 0.44),
    "RB": (1.10, 0.66, 0.51),
    "WR": (1.17, 0.68, 0.55),
    "TE": (1.13, 0.69, 0.51),
    "K": (0.69, 0.58, 0.58),
    "D/ST": (1.14, 0.71, 0.71),
}
ROS_WEIGHTS = (0.45, 0.35, 0.20)   # weekly projection, prior, season PPG, from week 5
SD_FLOOR = 1.5            # points; even a 2-point projection can miss by more than its CV says
VOLUME_FILE = Path(__file__).resolve().parent.parent / ".cache" / "volume-{season}.json"
UNUSABLE = {"OUT", "IR", "SUSP", "D"}
BENCH_SLOT, IR_SLOT = 20, 21


# ---- currency -------------------------------------------------------------

def ros_rate(week: int, proj: float | None, season_proj: float | None,
             season_actual: float | None = None, games: int | None = None,
             played: int | None = None) -> float:
    """Points per remaining week for a player, on the playbook's blend.

    `games` is how many games his NFL team played before `week`; `played` is
    how many of those he appeared in, when the box scores say."""
    prior = float(season_proj or 0.0) / max(1, NFL_WEEKS - (games or 0))
    weekly = float(proj or 0.0)
    if week >= BLEND_SWITCH_WEEK and (played or games):
        ppg = float(season_actual or 0.0) / (played or games or 1)
        wp, wr, wg = ROS_WEIGHTS
        parts = [(wp, weekly), (wr, prior), (wg, ppg)] if weekly > 0 else [(0.5, prior), (0.5, ppg)]
    else:
        parts = [(0.5, prior), (0.5, weekly)]
    parts = [(w, v) for w, v in parts if v > 0]
    total = sum(w for w, _ in parts)
    return sum(w * v for w, v in parts) / total if total else 0.0


def games_played(pro_games: dict, week: int) -> int:
    """How many weeks before `week` a pro team had a game (byes excluded).
    17 minus this is the games left that `season_proj` covers. As a PPG
    denominator it counts a week a player missed hurt as a 0-point game, so
    it is only the fallback when `games_appeared` has no row for him."""
    return sum(1 for w in range(1, week) if pro_games.get(str(w)))


def games_appeared(rows: dict[str, dict], week: int) -> dict[str, int]:
    """`norm(name)|POS` -> games the player appeared in, from bin/volume's rows
    (.cache/volume-<season>.json "players"). Empty unless the rows reach the
    week before `week`: a count that stops at week 4 against a points total
    through week 5 would inflate his PPG. K and D/ST have no rows."""
    covered = max((w.get("week", 0) for r in rows.values() for w in r.get("weeks") or []), default=0)
    if covered < week - 1:
        return {}
    return {k: int(r["games"]) for k, r in rows.items() if r.get("games")}


def load_volume_rows(season: int, path: Path | None = None) -> dict[str, dict]:
    """bin/volume's per-player rows, or {} when the feed has not been built."""
    try:
        return json.loads((path or Path(str(VOLUME_FILE).format(season=season))).read_text())["players"]
    except (OSError, ValueError, KeyError):
        return {}


# ---- variance ---------------------------------------------------------------

def position_cv(pos: str, proj: float) -> float:
    row = CV_TABLE.get(pos)
    if row is None:
        return PRIOR_CV.get(pos, 0.8)
    for (lo, hi), cv in zip(TIERS, row, strict=True):
        if lo <= proj < hi:
            return cv
    return row[-1]


def player_sd(pos: str, proj: float | None, mult: float = 1.0) -> float:
    p = float(proj or 0.0)
    if p <= 0:
        return 0.0
    return max(SD_FLOOR, p * position_cv(pos, p) * mult)


def phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


GAME_SECONDS = 3600.0     # regulation, for the share of a game still to play
OT_SHARE = 0.05           # overtime is a floor, not a fifth quarter


def clock_remaining(state: str | None, period: int | None, clock: str | None) -> float:
    """Share of one NFL game still to play, from ESPN's scoreboard status.

    0.0 covers both "has not kicked off" and "final", because neither has
    points still coming that an actual has not already counted."""
    if state != "in" or not period:
        return 0.0
    if period > 4:
        return OT_SHARE
    mins, _, secs = (clock or "0:00").partition(":")
    try:
        left = int(mins) * 60 + int(secs)
    except ValueError:
        left = 0
    return max(0.0, min(1.0, ((4 - period) * 900 + left) / GAME_SECONDS))


def row_moments(r: dict, mults: dict[str, float],
                remaining: dict[str, float] | None = None) -> tuple[float, float]:
    """(mean, sd) for one lineup row: banked actual if the game is over,
    projection if it has not started, and the two blended while it is on.

    Found 2026-09-20 during SNF: a starter in the first quarter with 2.3
    points was banked at 2.3 with sd 0, which read the matchup as 1% when
    55 minutes of his game were still to play. A player mid-game is his
    banked points plus the share of his projection the clock still has
    left, with the spread on sqrt of that share (independent increments;
    a touchdown-lumpy scorer is probably wider than this says)."""
    key = f"{norm(r.get('name') or '')}|{r.get('pos')}"
    mean = row_mean(r)
    sd = player_sd(r.get("pos", "?"), mean, mults.get(key, 1.0))
    if r.get("actual") is None:
        return float(mean or 0.0), sd
    left = (remaining or {}).get(r.get("team") or "", 0.0)
    if left <= 0:
        return float(r["actual"]), 0.0
    return float(r["actual"]) + left * float(mean or 0.0), sd * math.sqrt(left)


def row_mean(r: dict) -> float | None:
    """The expected points the variance rule uses: `mean` when the caller set
    one (ESPN blended with the betting market, espncli.cli.attach_market),
    else ESPN's projection. Measured 2026-10-15 on 833 rostered player-weeks:
    the market alone beat ESPN by 0.162 points of absolute error a player
    (95% CI 0.065 to 0.261) and the even blend by 0.108 (0.058 to 0.159)."""
    m = r.get("mean")
    return float(m) if m is not None else (float(r["proj"]) if r.get("proj") is not None else None)


def is_starter(r: dict) -> bool:
    return r.get("slotId") not in (BENCH_SLOT, IR_SLOT)


def load_corr() -> dict[str, float]:
    """The measured teammate and opponent correlations (ffmodel/corr_table.json),
    or {} (independence) when the table is missing."""
    from ffmodel.corr import load  # noqa: PLC0415 -- keeps value importable on its own

    return load()


def _rho(a: dict, b: dict, corr: dict[str, float]) -> float:
    if not corr:
        return 0.0
    from ffmodel.corr import rho  # noqa: PLC0415

    return rho(a, b, corr)


def _cov(rows: list[tuple[dict, float]], other: list[tuple[dict, float]] | None,
         corr: dict[str, float]) -> float:
    """Sum of rho x sd x sd over distinct pairs within `rows` (other is None)
    or across `rows` and `other`."""
    total = 0.0
    if other is None:
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                (a, sa), (b, sb) = rows[i], rows[j]
                if sa and sb:
                    total += _rho(a, b, corr) * sa * sb
        return total
    for a, sa in rows:
        for b, sb in other:
            if sa and sb:
                total += _rho(a, b, corr) * sa * sb
    return total


def lineup_moments(rows: list[dict], mults: dict[str, float],
                   remaining: dict[str, float] | None = None,
                   corr: dict[str, float] | None = None) -> tuple[float, float]:
    mu, var = 0.0, 0.0
    parts = []
    for r in rows:
        if not is_starter(r):
            continue
        m, s = row_moments(r, mults, remaining)
        mu += m
        var += s * s
        parts.append((r, s))
    var += 2.0 * _cov(parts, None, corr or {})
    return mu, math.sqrt(max(var, 0.0))


def win_prob(me: list[dict], opp: list[dict], mults: dict[str, float] | None = None,
             remaining: dict[str, float] | None = None, corr: dict[str, float] | None = None) -> dict:
    """P(our starters outscore theirs), with both sides' means and spreads.

    With `corr` (load_corr()), starters in the same NFL game are correlated
    as measured (2026-10-15, ffmodel/corr.py): a quarterback and his own
    receiver move together (+0.39 for a WR1), so a stack widens our spread;
    a defense and the quarterback it faces move apart (-0.48), so starting a
    D/ST against the opponent's quarterback ties the two totals together and
    widens the margin's spread too. Var(us - them) = Var(us) + Var(them)
    - 2 Cov(us, them). Without `corr` every starter is independent, which is
    what this computed before that date."""
    mults = mults or {}
    corr = corr or {}
    mu_me, sd_me = lineup_moments(me, mults, remaining, corr)
    mu_opp, sd_opp = lineup_moments(opp, mults, remaining, corr)
    cross = 0.0
    if corr:
        mine = [(r, row_moments(r, mults, remaining)[1]) for r in me if is_starter(r)]
        theirs = [(r, row_moments(r, mults, remaining)[1]) for r in opp if is_starter(r)]
        cross = _cov(mine, theirs, corr)
    sd = math.sqrt(max(sd_me * sd_me + sd_opp * sd_opp - 2.0 * cross, 0.0))
    p = 0.5 if sd == 0 and mu_me == mu_opp else (1.0 if sd == 0 and mu_me > mu_opp else 0.0 if sd == 0 else phi((mu_me - mu_opp) / sd))
    return {"p": round(p, 3), "mu_me": round(mu_me, 1), "sd_me": round(sd_me, 1),
            "mu_opp": round(mu_opp, 1), "sd_opp": round(sd_opp, 1), "margin": round(mu_me - mu_opp, 1),
            "sd_diff": round(sd, 1)}


def usable(r: dict) -> bool:
    return r.get("opp") != "BYE" and (r.get("status") or "") not in UNUSABLE


# Projected points worth one point of this week's win probability, through
# the Points For tiebreak. Measured by `season_sim.py --leverage` on
# 2026-10-14: 4.6 to 5.2 across weeks 6-14 (3 to 8 across the noise
# settings), because a point of Points For alone is worth about a fifth of a
# point that also moves the game. Rerun on Tuesdays; move this if it drifts.
POINTS_PER_WIN_PCT = 5.0


def best_swaps(me: list[dict], opp: list[dict], mults: dict[str, float] | None = None,
               min_gain: float = 0.005, top: int = 5,
               remaining: dict[str, float] | None = None,
               points_per_win_pct: float = POINTS_PER_WIN_PCT,
               corr: dict[str, float] | None = None) -> list[dict]:
    """Every single bench-for-starter swap that raises win probability, best first.

    Only unlocked, usable bench players into unlocked starter slots they are
    eligible for. `d_proj` is what the projection-only view would have said,
    so a reader can see when variance, not the mean, made the call. `d_net`
    is the swap in points of win probability with the projection it costs or
    gains priced at `points_per_win_pct` (the Points For tiebreak): the
    variance rule applies a swap at d_net >= +1."""
    mults = mults or {}
    base = win_prob(me, opp, mults, remaining, corr)["p"]
    out = []
    starters = [r for r in me if is_starter(r)]
    bench = [r for r in me if r.get("slotId") == BENCH_SLOT]
    for b in bench:
        if b.get("actual") is not None or not usable(b) or row_mean(b) is None:
            continue
        for s in starters:
            if s.get("actual") is not None or s.get("slotId") not in (b.get("eligible") or []):
                continue
            trial = [dict(r) for r in me]
            for r in trial:
                if r.get("id") == s.get("id"):
                    r["slotId"] = BENCH_SLOT
                elif r.get("id") == b.get("id"):
                    r["slotId"] = s["slotId"]
            p = win_prob(trial, opp, mults, remaining, corr)["p"]
            if p - base >= min_gain:
                d_proj = float(row_mean(b) or 0) - float(row_mean(s) or 0)
                out.append({"bench": b["name"], "bench_pos": b.get("pos"), "starter": s["name"],
                            "slot": s.get("slot"), "slotId": s.get("slotId"),
                            "p_before": base, "p_after": round(p, 3), "d_p": round(p - base, 3),
                            "d_proj": round(d_proj, 1),
                            "d_net": round(100 * (p - base) + d_proj / points_per_win_pct, 2)})
    out.sort(key=lambda x: -x["d_p"])
    return out[:top]


def best_fill(me: list[dict], opp: list[dict] | None, slot_id: int, exclude: int | None,
              mults: dict[str, float] | None = None,
              remaining: dict[str, float] | None = None,
              corr: dict[str, float] | None = None) -> dict | None:
    """The bench player to put into `slot_id`: by win probability when there is
    an opponent to beat, by projection otherwise (idle week, or no matchup)."""
    mults = mults or {}
    bench = [b for b in me if b.get("slotId") == BENCH_SLOT and slot_id in (b.get("eligible") or [])
             and usable(b) and b.get("id") != exclude and b.get("actual") is None]
    if not bench:
        return None
    if not opp:
        return max(bench, key=lambda b: float(row_mean(b) or 0.0))
    scored = []
    for b in bench:
        trial = [dict(r) for r in me]
        for r in trial:
            if r.get("id") == exclude:
                r["slotId"] = BENCH_SLOT
            elif r.get("id") == b.get("id"):
                r["slotId"] = slot_id
        scored.append((win_prob(trial, opp, mults, remaining, corr)["p"], float(row_mean(b) or 0.0), b))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    best = dict(scored[0][2])
    best["p_after"] = round(scored[0][0], 3)
    return best
