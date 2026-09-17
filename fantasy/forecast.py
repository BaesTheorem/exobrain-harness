#!/usr/bin/env python3
"""forecast: the weekly prediction-and-review loop for Chaos Legion.

Alex's standing instruction (2026-09-17): every fantasy week opens with a 50%
and a 90% interval on every rostered player, the team total, the matchup, and
the league standing, written by MIST as a judgment call; every week closes
with a review of where reality fell against those intervals and a strategy
change only where the reasoning, not the outcome, failed.

This file is the deterministic half of that loop. It never predicts. It:

  dossier    assembles the evidence pack MIST reads before predicting: every
             source's weekly projection per player (ESPN, Sleeper, CBS,
             FantasyPros, FFToday), the consensus mean and the spread across
             sources, each player's season log against ESPN's own projections,
             injury status, kickoff, the Vegas line and implied total for his
             game, and the historical distribution of actual/projection by
             position, so interval widths are anchored on measured error
             rather than feel. It also runs a mechanical baseline (consensus
             center, bootstrapped historical residuals, Monte Carlo over every
             matchup in the league) so the review can tell whether MIST's
             judgment beats the average of the sources or only adds noise.
  record     validates MIST's forecast (nested intervals, every player
             resolvable) and files it with the baseline beside it.
  settle     pulls the week's actuals and scores both forecasts: inside the
             50, inside the 90, or outside; error against the median; Brier on
             the win probability; cumulative coverage across the season.
  calibrate  rebuilds the residual library (Sleeper 2025 weekly projections vs
             actuals, plus every 2026 week played) in .cache/residuals.json.
  history    the coverage table so far.
  note       attach MIST's judgment text (forecast commentary or the Tuesday
             review) to the week's file, so it renders into the playbook.
  playbook   rewrite the playbook's Season log grouped by week, with each
             week's forecast table and review scorecard at the top of its
             section, regenerated from the filed JSON. Every daily bullet is
             kept verbatim; only the week headers and the marked blocks are
             the tool's. `record`, `settle` and `note` run it automatically.

Forecasts live in fantasy/forecasts/<season>-wNN.json, one file per week,
committed: they are the predictions that pay rent. ESPN is one vote in the
consensus, never the model; that was Alex's second instruction the same day.

INVARIANTS:
- Read-only against ESPN and every other source. Nothing here writes to a
  league. The only files written are forecasts/*.json and .cache/*.
- The baseline is a yardstick for MIST's judgment, never a substitute for
  it. `record` refuses a forecast that is missing the judgment fields.
- A 50% interval sits inside its 90% interval, always; `record` rejects
  anything else, because a prediction that cannot fail is not one.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from espncli.cli import (  # noqa: E402
    matchup_view,
    nfl_events,
    roster_rows,
    side_entries,
)
from espncli.client import (  # noqa: E402
    BENCH,
    IR,
    TZ,
    Espn,
    load_creds,
    norm,
    team_name,
    week_actual,
    week_proj,
)

HERE = Path(__file__).resolve().parent
FORECASTS = HERE / "forecasts"
CACHE = HERE / ".cache"
RESIDUALS = CACHE / "residuals.json"
PLAYBOOK = Path.home() / "Exobrain/Areas/Adventure & Creativity/Fantasy Football/Fantasy Football Playbook.md"
LOG_HEADER = "## Season log"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
POSITIONS = ("QB", "RB", "WR", "TE", "K", "D/ST")
MIN_PROJ = 3.0        # ratios below this projection blow up and mean nothing
SIMS = 5000
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
# Fallback coefficient of variation per position when the residual library is
# missing (a fresh clone). Rough, from the week-1 2026 and week-5 2025 probes
# recorded in the playbook; the library replaces it on the first calibrate.
PRIOR_CV = {"QB": 0.40, "RB": 0.65, "WR": 0.85, "TE": 0.95, "K": 0.55, "D/ST": 1.0}


# ---- small helpers --------------------------------------------------------

def fetch(url: str, tries: int = 3) -> str:
    last: Exception | None = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as e:  # pragma: no cover - network
            last = e
    raise RuntimeError(f"could not fetch {url}: {last}")


def fetch_json(url: str) -> Any:
    return json.loads(fetch(url))


def slug(name: str) -> str:
    """norm() with the spaces gone too, so Ja'Marr, JaMarr and Ja Marr agree."""
    return re.sub(r"[^a-z]", "", norm(name))


def nick(full_team_name: str) -> str:
    """'Kansas City Chiefs' -> 'chiefs'. Every current NFL nickname is one word."""
    return slug(full_team_name.split()[-1]) if full_team_name else ""


def key_for(name: str, pos: str, dst_nick: str | None = None) -> str:
    """The cross-source identity of a player: normalized name and position.
    Team defenses key on the nickname, since every source spells them differently."""
    if pos == "D/ST":
        return f"dst:{dst_nick or nick(name)}"
    return f"{pos}:{slug(name)}"


def quantiles(xs: list[float], qs=QUANTILES) -> dict[str, float]:
    if not xs:
        return {}
    s = sorted(xs)
    out = {}
    for q in qs:
        i = max(0, min(len(s) - 1, round(q * (len(s) - 1))))
        out[f"q{int(q * 100):02d}"] = round(s[i], 2)
    return out


def rank_teams(teams: list[dict]) -> list[dict]:
    """ESPN's standings order: win percentage, then total points for."""
    def pct(t):
        g = t["w"] + t["l"]
        return t["w"] / g if g else 0.0
    return sorted(teams, key=lambda t: (-pct(t), -t["pf"]))


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


# ---- projection sources ---------------------------------------------------
# Each returns {key_for(...): points} for one week in full-PPR scoring.

SLEEPER_POS = {"DEF": "D/ST"}
SLEEPER_ABBR = {"WAS": "WSH"}


def sleeper_week(season: int, week: int, what: str = "projections") -> list[dict]:
    pos = "&".join(f"position[]={p}" for p in ("QB", "RB", "WR", "TE", "K", "DEF"))
    url = f"https://api.sleeper.app/{what}/nfl/{season}/{week}?season_type=regular&{pos}"
    return fetch_json(url)


def sleeper_map(rows: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in rows:
        p = r.get("player") or {}
        pts = (r.get("stats") or {}).get("pts_ppr")
        pos_raw = p.get("position") or ""
        pos = SLEEPER_POS.get(pos_raw, pos_raw)
        if pts is None or pos not in POSITIONS:
            continue
        name = f"{p.get('first_name', '')} {p.get('last_name', '')}"
        k = key_for(name, pos, dst_nick=slug(p.get("last_name", "")) if pos == "D/ST" else None)
        out[k] = float(pts)
    return out


def sleeper_proj(season: int, week: int) -> dict[str, float]:
    return sleeper_map(sleeper_week(season, week, "projections"))


def sleeper_actual(season: int, week: int) -> dict[str, float]:
    return sleeper_map(sleeper_week(season, week, "stats"))


CBS_POS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "D/ST": "DST"}


def cbs_proj(season: int, week: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for pos, path in CBS_POS.items():
        html = fetch(f"https://www.cbssports.com/fantasy/football/stats/{path}/{season}/{week}/projections/ppr/")
        for row in re.findall(r'<tr class="TableBase-bodyTr[^"]*">(.*?)</tr>', html, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(cells) < 3:
                continue
            try:
                pts = float(strip_tags(cells[-1]).replace(",", ""))
            except ValueError:
                continue
            if pos == "D/ST":
                m = re.search(r"/nfl/teams/[A-Z]+/([a-z-]+)/", cells[0])
                if not m:
                    continue
                out[key_for("", pos, dst_nick=slug(m.group(1).split("-")[-1]))] = pts
            else:
                m = re.search(r'CellPlayerName--long.*?<a[^>]*>([^<]+)</a>', cells[0], re.S)
                if m:
                    out[key_for(m.group(1), pos)] = pts
    return out


FP_POS = {"QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "K": "k", "D/ST": "dst"}


def fantasypros_proj(week: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for pos, path in FP_POS.items():
        html = fetch(f"https://www.fantasypros.com/nfl/projections/{path}.php?week={week}&scoring=PPR")
        for row in re.findall(r'<tr class="mpb-player-\d+[^"]*">(.*?)</tr>', html, re.S):
            m = re.search(r'fp-player-name="([^"]+)"', row)
            pts = re.findall(r'data-sort-value="([\d.]+)"', row)
            if not m or not pts:
                continue
            name = m.group(1)
            k = key_for(name, pos, dst_nick=nick(name) if pos == "D/ST" else None)
            out[k] = float(pts[-1])
    return out


FFT_POS = {"QB": 10, "RB": 20, "WR": 30, "TE": 40, "K": 80, "D/ST": 99}


def fftoday_proj(season: int, week: int) -> dict[str, float]:
    out: dict[str, float] = {}
    for pos, pid in FFT_POS.items():
        url = (f"https://www.fftoday.com/rankings/playerwkproj.php?Season={season}&GameWeek={week}"
               f"&PosID={pid}&LeagueID=190")
        html = fetch(url)
        rows = re.findall(r'<A HREF="/stats/[^"]*"[^>]*>([^<]+)</A>(.*?)</TR>', html, re.S | re.I)
        for name, rest in rows:
            nums = re.findall(r">\s*(-?[\d.,]+)\s*<", rest)
            if not nums:
                continue
            name = name.strip()
            k = key_for(name, pos, dst_nick=nick(name) if pos == "D/ST" else None)
            out[k] = float(nums[-1].replace(",", ""))
    return out


ANCHORS = ("espn", "sleeper", "fantasypros")   # share this league's 4-point passing TD scale


def normalize_units(sources: dict[str, dict[str, float]], espn: dict[str, float]) -> dict[str, dict[str, float]]:
    """Rescale each source, per position, onto the anchor sources' scale.

    A source that scores a passing touchdown 6 instead of 4 runs a fixed
    fraction hot on every quarterback; that is a unit, not an opinion, and
    averaging it in would bias the consensus. The factor is the median of
    source/anchor over every player both have, applied only when it moves
    more than 5%. Returned as {source: {position: factor}}; sources are
    rescaled in place."""
    anchor: dict[str, list[float]] = {}
    tables = {"espn": espn, **{k: v for k, v in sources.items() if k in ANCHORS}}
    keys = set().union(*[set(t) for t in tables.values()]) if tables else set()
    for k in keys:
        vals = [t[k] for t in tables.values() if k in t]
        if vals:
            anchor[k] = vals
    factors: dict[str, dict[str, float]] = {}
    for name, table in sources.items():
        if name in ANCHORS:
            continue
        by_pos: dict[str, list[float]] = {}
        for k, v in table.items():
            a = anchor.get(k)
            if not a or v < MIN_PROJ:
                continue
            am = statistics.fmean(a)
            if am < MIN_PROJ:
                continue
            pos = "D/ST" if k.startswith("dst:") else k.split(":", 1)[0]
            by_pos.setdefault(pos, []).append(v / am)
        for pos, ratios in by_pos.items():
            if len(ratios) < 8:
                continue
            f = 1 / statistics.median(ratios)
            if abs(1 - f) > 0.05:
                factors.setdefault(name, {})[pos] = round(f, 3)
        for k in list(table):
            pos = "D/ST" if k.startswith("dst:") else k.split(":", 1)[0]
            f = factors.get(name, {}).get(pos)
            if f:
                table[k] = round(table[k] * f, 2)
    return factors


def pull_sources(season: int, week: int) -> tuple[dict[str, dict[str, float]], list[str]]:
    """Every non-ESPN source that answered, plus the names of those that did not."""
    pulls = {
        "sleeper": lambda: sleeper_proj(season, week),
        "cbs": lambda: cbs_proj(season, week),
        "fantasypros": lambda: fantasypros_proj(week),
        "fftoday": lambda: fftoday_proj(season, week),
    }
    got: dict[str, dict[str, float]] = {}
    failed: list[str] = []
    for name, fn in pulls.items():
        try:
            got[name] = fn()
        except Exception as e:  # noqa: BLE001 - a dead source must not kill the dossier
            print(f"forecast: source {name} failed: {e}", file=sys.stderr)
            failed.append(name)
    return got, failed


# ---- residual library -----------------------------------------------------

TIERS = ((0.0, 7.0), (7.0, 13.0), (13.0, 1e9))   # projection bands: deep bench, flex, starter


def tier_of(proj: float) -> tuple[float, float]:
    for lo, hi in TIERS:
        if lo <= proj < hi:
            return (lo, hi)
    return TIERS[-1]


def load_residuals() -> dict[str, list]:
    """Per position, a list of [ratio, projection] pairs (older libraries held bare ratios)."""
    if RESIDUALS.exists():
        d = json.loads(RESIDUALS.read_text())
        return {k: v for k, v in d.get("samples", {}).items()}
    return {}


def prior_samples(pos: str, n: int = 400, seed: int = 7) -> list[float]:
    """Gamma-shaped ratios with mean 1 and the prior CV; only for a fresh clone."""
    rng = random.Random(seed)
    cv = PRIOR_CV.get(pos, 0.8)
    k = 1 / (cv * cv)
    return [rng.gammavariate(k, 1 / k) for _ in range(n)]


def ratio_samples(pos: str, lib: dict[str, list], proj: float | None = None) -> list[float]:
    """Historical actual/projection ratios for a position, narrowed to the
    projection tier of `proj` when there are enough of them (a 4-point deep
    bench player and an 18-point starter do not miss by the same shape)."""
    raw = lib.get(pos) or []
    pairs = [(x[0], x[1]) if isinstance(x, list) else (x, None) for x in raw]
    if proj is not None:
        lo, hi = tier_of(proj)
        tiered = [r for r, pj in pairs if pj is not None and lo <= pj < hi]
        if len(tiered) >= 40:
            return tiered
    xs = [r for r, _ in pairs]
    return xs if len(xs) >= 40 else prior_samples(pos)


def calibrate(seasons: list[int], through: dict[int, int]) -> dict:
    """Actual/projection ratios by position from Sleeper, for every week asked.
    `through` maps season -> last week to include (a season in progress stops
    at the last week actually played)."""
    samples: dict[str, list[list[float]]] = {p: [] for p in POSITIONS}
    weeks_used: list[str] = []
    for season in seasons:
        for week in range(1, through.get(season, 18) + 1):
            try:
                proj = sleeper_proj(season, week)
                act = sleeper_actual(season, week)
            except Exception as e:  # noqa: BLE001 - one dead week is not fatal
                print(f"forecast: calibrate {season} w{week} failed: {e}", file=sys.stderr)
                continue
            if sum(1 for v in act.values() if v) < 50:
                continue  # a week not yet played
            for k, pr in proj.items():
                if pr < MIN_PROJ:
                    continue
                pos = "D/ST" if k.startswith("dst:") else k.split(":", 1)[0]
                samples[pos].append([round((act.get(k, 0.0) or 0.0) / pr, 4), round(pr, 1)])
            weeks_used.append(f"{season}w{week}")
            print(f"  {season} week {week}: {len(proj)} projections", file=sys.stderr)
    out = {"built": datetime.now(TZ).isoformat(timespec="minutes"), "weeks": weeks_used,
           "samples": samples,
           "quantiles": {p: quantiles([x[0] for x in v]) for p, v in samples.items()},
           "tier_quantiles": {p: {f"{lo:g}-{hi:g}": quantiles([x[0] for x in v if lo <= x[1] < hi])
                                  for lo, hi in TIERS} for p, v in samples.items()},
           "n": {p: len(v) for p, v in samples.items()}}
    CACHE.mkdir(exist_ok=True)
    RESIDUALS.write_text(json.dumps(out))
    return out


# ---- the dossier ----------------------------------------------------------

def _team_id_of(row: dict, api: Espn) -> int | None:
    for tid, t in api.pro_teams().items():
        if t["abbrev"] == row["team"]:
            return tid
    return None


def _key_of(row: dict, api: Espn) -> str:
    if row["pos"] == "D/ST":
        return key_for("", "D/ST", dst_nick=nick(api.pro(_team_id_of(row, api)).get("name", "")))
    return key_for(row["name"], row["pos"])


def enrich(rows: list[dict], api: Espn, week: int, sources: dict[str, dict[str, float]],
           games: dict[str, dict], cards: dict[int, dict],
           cards_by_week: dict[int, dict[int, dict]] | None = None) -> list[dict]:
    cards_by_week = cards_by_week or {}
    """Attach every source's number, the consensus, the season log and the game context."""
    out = []
    for r in rows:
        k = _key_of(r, api)
        proj = {"espn": round(r["proj"], 1) if r["proj"] is not None else None}
        for s, table in sources.items():
            if k in table:
                proj[s] = round(table[k], 1)
        votes = [v for v in proj.values() if v is not None]
        card = cards.get(r["id"] or -1) or {}
        log = []
        for w in range(1, week):
            a = week_actual(card, api.season, w)
            p = week_proj((cards_by_week.get(w) or {}).get(r["id"] or -1) or {}, api.season, w)
            if a is not None or p is not None:
                log.append({"week": w, "actual": a, "espn_proj": round(p, 1) if p is not None else None})
        g = games.get(r["team"]) or {}
        out.append({
            **{x: r[x] for x in ("slot", "slotId", "id", "name", "pos", "team", "opp", "kick", "status")},
            "key": k,
            "proj": proj,
            "consensus": round(statistics.fmean(votes), 1) if votes else None,
            "spread": round(max(votes) - min(votes), 1) if len(votes) > 1 else None,
            "n_sources": len(votes),
            "season_log": log,
            "game": g,
        })
    return out


def game_context(api: Espn, week: int) -> dict[str, dict]:
    """Per NFL team abbrev: line, implied total, weather, roof."""
    out: dict[str, dict] = {}
    for g in nfl_events(api, week):
        for side, imp in (("home", "implied_home"), ("away", "implied_away")):
            t = g.get(side) or {}
            if not t.get("abbrev"):
                continue
            out[t["abbrev"]] = {
                "line": g.get("line"), "ou": g.get("ou"), "implied": g.get(imp),
                "opp_implied": g.get("implied_home" if side == "away" else "implied_away"),
                "indoor": g.get("indoor"), "weather": g.get("weather"), "temp": g.get("temp"),
                "kickoff": g["kickoff"].isoformat(timespec="minutes") if g.get("kickoff") else None,
            }
    return out


def league_lineups(api: Espn, data: dict, week: int) -> tuple[list[dict], list[str]]:
    """Every matchup's two lineups for the week, and the idle team(s)."""
    names = {t["id"]: team_name(t) for t in data["teams"]}
    games, idle = [], []
    for m in sorted(data.get("schedule", []), key=lambda m: m.get("id", 0)):
        if m.get("matchupPeriodId") != week:
            continue
        if not (m.get("home") and m.get("away")):
            s = m.get("home") or m.get("away")
            idle.append(names.get(s["teamId"], "?"))
            continue
        g: dict[str, Any] = {"id": m.get("id")}
        for side in ("home", "away"):
            s = m[side]
            entries, _ = side_entries(api, data, s)
            rows = roster_rows(api, entries, week)
            g[side] = {"team_id": s["teamId"], "team": names.get(s["teamId"], "?"),
                       "starters": [r for r in rows if r["slotId"] not in (BENCH, IR)],
                       "espn_total": s.get("totalPoints")}
        games.append(g)
    return games, idle


def standings_now(data: dict) -> list[dict]:
    out = []
    for t in data["teams"]:
        rec = (t.get("record") or {}).get("overall") or {}
        out.append({"team_id": t["id"], "team": team_name(t), "w": rec.get("wins", 0),
                    "l": rec.get("losses", 0), "pf": round(rec.get("pointsFor", 0.0), 1)})
    return rank_teams(out)


def center_for(row: dict, sources: dict[str, dict[str, float]], api: Espn) -> float:
    """Consensus projection for any league starter; ESPN alone when no source has him."""
    k = _key_of(row, api)
    votes = [row["proj"]] if row["proj"] is not None else []
    votes += [t[k] for t in sources.values() if k in t]
    return statistics.fmean(votes) if votes else 0.0


def baseline(api: Espn, me: list[dict], opp: list[dict], league: list[dict],
             standings: list[dict], my_team_id: int, sources: dict[str, dict[str, float]],
             lib: dict[str, list[float]], seed: int = 2026) -> dict:
    """Mechanical forecast: consensus center times a bootstrapped historical ratio,
    summed over starters, over every matchup, SIMS times. The yardstick."""
    rng = random.Random(seed)
    samp: dict[tuple, list[float]] = {}

    def draw(pos: str, center: float) -> float:
        key = (pos, tier_of(center))
        if key not in samp:
            samp[key] = ratio_samples(pos, lib, center)
        return center * rng.choice(samp[key] or [1.0])

    # per-player quantiles on our roster (starters and bench alike)
    players = {}
    for r in me:
        c = r["consensus"] or 0.0
        xs = sorted(draw(r["pos"], c) for _ in range(2000))
        players[r["name"]] = quantiles(xs)

    # league-wide sim: team totals, wins, resulting rank
    my_tot: list[float] = []
    opp_tot: list[float] = []
    wins = 0
    rank_hist: dict[int, int] = {}
    centers = {}
    for g in league:
        for side in ("home", "away"):
            t = g[side]
            centers[t["team_id"]] = [(r["pos"], center_for(r, sources, api)) for r in t["starters"]]
    base = {t["team_id"]: t for t in standings}
    my_opp_id = None
    for g in league:
        ids = (g["home"]["team_id"], g["away"]["team_id"])
        if my_team_id in ids:
            my_opp_id = ids[1] if ids[0] == my_team_id else ids[0]
    for _ in range(SIMS):
        tot = {tid: sum(draw(p, c) for p, c in cs) for tid, cs in centers.items()}
        rows = []
        for tid, t in base.items():
            rows.append({"team_id": tid, "w": t["w"], "l": t["l"], "pf": t["pf"] + tot.get(tid, 0.0)})
        rows_by = {r["team_id"]: r for r in rows}
        for g in league:
            h, a = g["home"]["team_id"], g["away"]["team_id"]
            if tot[h] >= tot[a]:
                rows_by[h]["w"] += 1; rows_by[a]["l"] += 1
            else:
                rows_by[a]["w"] += 1; rows_by[h]["l"] += 1
        order = rank_teams(rows)
        rank = next(i for i, r in enumerate(order, 1) if r["team_id"] == my_team_id)
        rank_hist[rank] = rank_hist.get(rank, 0) + 1
        my_tot.append(tot.get(my_team_id, 0.0))
        if my_opp_id is not None:
            opp_tot.append(tot[my_opp_id])
            wins += tot[my_team_id] > tot[my_opp_id]
    n = SIMS
    ranks = sorted(rank_hist.items())
    cum, rank_q = 0, {}
    for rk, cnt in ranks:
        cum += cnt
        for q in QUANTILES:
            if f"q{int(q * 100):02d}" not in rank_q and cum / n >= q:
                rank_q[f"q{int(q * 100):02d}"] = rk
    return {
        "players": players,
        "team_total": quantiles(my_tot),
        "opp_total": quantiles(opp_tot) if opp_tot else None,
        "win_prob": round(wins / n, 3) if opp_tot else None,
        "rank": rank_q,
        "p_first": round(rank_hist.get(1, 0) / n, 3),
        "p_top2": round((rank_hist.get(1, 0) + rank_hist.get(2, 0)) / n, 3),
        "p_top6": round(sum(c for r, c in rank_hist.items() if r <= 6) / n, 3),
        "rank_dist": {str(k): round(v / n, 3) for k, v in ranks},
        "sims": n,
        "residual_n": {p: len(lib.get(p) or []) for p in POSITIONS},
    }


def build_dossier(api: Espn, week: int) -> dict:
    data = api.league("mTeam", "mRoster", "mMatchup", "mMatchupScore", "mSettings", "mStatus", period=week)
    my_id = api.my_team_id(data)
    if my_id is None:
        raise SystemExit("forecast: could not identify our team")
    mv = matchup_view(api, week, data, my_id)
    if mv is None or not mv.get("opp"):
        raise SystemExit(f"forecast: no matchup for week {week} (idle week?)")
    sources, failed = pull_sources(api.season, week)
    league, idle = league_lineups(api, data, week)
    espn_table: dict[str, float] = {}
    for g in league:
        for side in ("home", "away"):
            for r in g[side]["starters"]:
                if r["proj"] is not None:
                    espn_table[_key_of(r, api)] = r["proj"]
    for r in mv["me"]["rows"]:
        if r["proj"] is not None:
            espn_table[_key_of(r, api)] = r["proj"]
    unit_factors = normalize_units(sources, espn_table)
    games = game_context(api, week)
    ids = [r["id"] for r in mv["me"]["rows"] + mv["opp"]["rows"] if r.get("id")]
    cards = {}
    for c in api.player_cards(ids, period=week):
        p = c.get("player") or c
        cards[p.get("id")] = p
    cards_by_week: dict[int, dict[int, dict]] = {}
    for w in range(1, week):   # ESPN only returns a period's projection when asked for that period
        cards_by_week[w] = {}
        for c in api.player_cards(ids, period=w):
            p = c.get("player") or c
            cards_by_week[w][int(p.get("id") or -1)] = p
    me = enrich(mv["me"]["rows"], api, week, sources, games, cards, cards_by_week)
    opp = enrich([r for r in mv["opp"]["rows"] if r["slotId"] not in (BENCH, IR)],
                 api, week, sources, games, cards, cards_by_week)
    standings = standings_now(data)
    lib = load_residuals()
    base = baseline(api, me, opp, league, standings, my_id, sources, lib)
    lib_meta = json.loads(RESIDUALS.read_text()) if RESIDUALS.exists() else {}
    return {
        "week": week, "season": api.season, "built": datetime.now(TZ).isoformat(timespec="minutes"),
        "team_id": my_id, "team": mv["me"]["team"], "opponent": mv["opp"]["team"],
        "opponent_id": mv["opp"]["team_id"],
        "sources_ok": sorted(sources), "sources_failed": failed,
        "unit_factors": unit_factors,
        "me": me, "opp": opp,
        "espn_margin": mv.get("margin"),
        "league": [{"home": g["home"]["team"], "away": g["away"]["team"],
                    "home_consensus": round(sum(center_for(r, sources, api) for r in g["home"]["starters"]), 1),
                    "away_consensus": round(sum(center_for(r, sources, api) for r in g["away"]["starters"]), 1)}
                   for g in league],
        "idle": idle,
        "standings": standings,
        "residual_quantiles": lib_meta.get("quantiles", {}),
        "residual_tier_quantiles": lib_meta.get("tier_quantiles", {}),
        "residual_weeks": lib_meta.get("weeks", []),
        "baseline": base,
    }


def render_dossier(d: dict) -> None:
    print(f"{d['team']} -- week {d['week']} evidence pack (built {d['built']})")
    print(f"  opponent: {d['opponent']}   ESPN margin: {d['espn_margin']:+.1f}")
    print(f"  sources: {', '.join(d['sources_ok'])}" + (f"   FAILED: {', '.join(d['sources_failed'])}" if d['sources_failed'] else ""))
    for src_name, fs in d.get("unit_factors", {}).items():
        print(f"  unit-normalized {src_name}: " + ", ".join(f"{p} x{f}" for p, f in fs.items()) + "  (scoring-format difference, not opinion)")
    src = ["espn", "sleeper", "cbs", "fantasypros", "fftoday"]
    hdr = f"  {'SLOT':5} {'PLAYER':24} {'POS':4} {'OPP':5} {'ST':3} " + " ".join(f"{s[:6]:>6}" for s in src) + f" {'CONS':>6} {'SPRD':>5}  {'season log (actual/espn)':30} {'implied':>7} {'line':10} {'wx'}"
    print(hdr)
    for section, rows in (("OURS", d["me"]), ("THEIRS (starters)", d["opp"])):
        print(f"  -- {section}")
        for r in rows:
            cells = " ".join(f"{(r['proj'].get(s) if r['proj'].get(s) is not None else ''):>6}" for s in src)
            log = " ".join(f"{(x['actual'] if x['actual'] is not None else '-')}/{(x['espn_proj'] if x['espn_proj'] is not None else '-')}" for x in r["season_log"])
            g = r["game"] or {}
            wx = "dome" if g.get("indoor") else (g.get("weather") or "")
            print(f"  {r['slot']:5} {r['name'][:24]:24} {r['pos']:4} {r['opp'] or '-':5} {r['status'] or '':3} {cells} {r['consensus'] if r['consensus'] is not None else '':>6} {r['spread'] if r['spread'] is not None else '':>5}  {log:30} {g.get('implied') if g.get('implied') is not None else '':>7} {(g.get('line') or '')[:10]:10} {wx}")
    print("  -- historical actual/projection ratios (q05 q25 q50 q75 q95), from", len(d["residual_weeks"]), "weeks; by projection tier")
    for p, tiers in d.get("residual_tier_quantiles", {}).items():
        for band, q in tiers.items():
            if q:
                print(f"     {p:5} proj {band:>8} {q['q05']:5.2f} {q['q25']:5.2f} {q['q50']:5.2f} {q['q75']:5.2f} {q['q95']:5.2f}")
    b = d["baseline"]
    print("  -- mechanical baseline (consensus x bootstrapped ratios, every matchup simulated)")
    print(f"     our total   q05 {b['team_total']['q05']:6.1f}  q25 {b['team_total']['q25']:6.1f}  q50 {b['team_total']['q50']:6.1f}  q75 {b['team_total']['q75']:6.1f}  q95 {b['team_total']['q95']:6.1f}")
    if b["opp_total"]:
        print(f"     their total q05 {b['opp_total']['q05']:6.1f}  q25 {b['opp_total']['q25']:6.1f}  q50 {b['opp_total']['q50']:6.1f}  q75 {b['opp_total']['q75']:6.1f}  q95 {b['opp_total']['q95']:6.1f}")
    print(f"     win prob {b['win_prob']}   rank q05..q95 {b['rank']}   P(1st) {b['p_first']}  P(top2) {b['p_top2']}  P(top6) {b['p_top6']}")
    print("     rank distribution:", " ".join(f"{k}:{v:.2f}" for k, v in b["rank_dist"].items()))
    print("  -- league (consensus totals)")
    for g in d["league"]:
        print(f"     {g['away'][:24]:24} {g['away_consensus']:6.1f}  at  {g['home'][:24]:24} {g['home_consensus']:6.1f}")
    if d["idle"]:
        print(f"     idle: {', '.join(d['idle'])}")
    print("  -- standings now")
    for i, t in enumerate(d["standings"], 1):
        print(f"     {i:2} {t['team'][:24]:24} {t['w']}-{t['l']} {t['pf']:6.1f}")


# ---- record ---------------------------------------------------------------

def interval_ok(p50: list, p90: list) -> bool:
    try:
        a, b = float(p50[0]), float(p50[1])
        c, d = float(p90[0]), float(p90[1])
    except (TypeError, ValueError, IndexError):
        return False
    return c <= a <= b <= d and (a < b or c < d)


def validate_forecast(f: dict, roster_names: list[str]) -> list[str]:
    """Every reason the forecast cannot be filed. Empty means file it."""
    errs = []
    for k in ("week", "players", "team_total", "opp_total", "win_prob", "standing"):
        if k not in f:
            errs.append(f"missing field: {k}")
    if errs:
        return errs
    want = {slug(n) for n in roster_names}
    seen = set()
    for p in f["players"]:
        nm = p.get("name", "?")
        if slug(nm) not in want:
            errs.append(f"player not on the roster in the dossier: {nm}")
        if slug(nm) in seen:
            errs.append(f"duplicate player: {nm}")
        seen.add(slug(nm))
        if not interval_ok(p.get("p50", []), p.get("p90", [])):
            errs.append(f"{nm}: intervals must satisfy p90.lo <= p50.lo <= p50.hi <= p90.hi")
        if not isinstance(p.get("median"), (int, float)):
            errs.append(f"{nm}: needs a numeric median")
        if not p.get("why"):
            errs.append(f"{nm}: needs a 'why' (the judgment is the point)")
    missing = want - seen
    if missing:
        errs.append(f"roster players without a forecast: {sorted(missing)}")
    for k in ("team_total", "opp_total"):
        if not interval_ok(f[k].get("p50", []), f[k].get("p90", [])):
            errs.append(f"{k}: bad intervals")
        if not isinstance(f[k].get("median"), (int, float)):
            errs.append(f"{k}: needs a numeric median")
    try:
        wp = float(f["win_prob"])
        if not 0 < wp < 1:
            errs.append("win_prob must be strictly between 0 and 1 (0 and 1 are not probabilities you can hold)")
    except (TypeError, ValueError):
        errs.append("win_prob must be a number")
    s = f["standing"]
    if not interval_ok(s.get("p50", []), s.get("p90", [])):
        errs.append("standing: bad intervals")
    if not isinstance(s.get("median"), (int, float)):
        errs.append("standing: needs a numeric median rank")
    for k in ("p_first", "p_top2"):
        try:
            v = float(s.get(k))
            if not 0 <= v <= 1:
                errs.append(f"standing.{k} out of range")
        except (TypeError, ValueError):
            errs.append(f"standing.{k} must be a number")
    if not s.get("why"):
        errs.append("standing: needs a 'why'")
    return errs


def week_file(season: int, week: int) -> Path:
    return FORECASTS / f"{season}-w{week:02d}.json"


def record(api: Espn, forecast: dict, dossier: dict) -> Path:
    names = [r["name"] for r in dossier["me"]]
    errs = validate_forecast(forecast, names)
    if errs:
        for e in errs:
            print("forecast: " + e, file=sys.stderr)
        raise SystemExit(2)
    by_name = {slug(r["name"]): r for r in dossier["me"]}
    for p in forecast["players"]:
        r = by_name[slug(p["name"])]
        p["id"], p["pos"], p["slot"] = r["id"], r["pos"], r["slot"]
        p["consensus"], p["espn"] = r["consensus"], r["proj"].get("espn")
    out = {
        "season": api.season, "week": forecast["week"],
        "issued": datetime.now(TZ).isoformat(timespec="minutes"),
        "team_id": dossier["team_id"], "team": dossier["team"],
        "opponent": dossier["opponent"], "opponent_id": dossier["opponent_id"],
        "forecast": forecast,
        "baseline": dossier["baseline"],
        "sources": {"ok": dossier["sources_ok"], "failed": dossier["sources_failed"]},
        "standings_before": dossier["standings"],
        "settled": None,
    }
    FORECASTS.mkdir(exist_ok=True)
    path = week_file(api.season, forecast["week"])
    path.write_text(json.dumps(out, indent=1))
    return path


# ---- settle ---------------------------------------------------------------

def place(actual: float, p50: list, p90: list) -> str:
    if p50[0] <= actual <= p50[1]:
        return "in50"
    if p90[0] <= actual <= p90[1]:
        return "in90"
    return "below" if actual < p90[0] else "above"


def score_interval(actual: float, p50: list, p90: list, median: float | None) -> dict:
    where = place(actual, p50, p90)
    return {"actual": round(actual, 1), "where": where,
            "in50": where == "in50", "in90": where in ("in50", "in90"),
            "error": round(actual - median, 1) if median is not None else None,
            "width50": round(p50[1] - p50[0], 1), "width90": round(p90[1] - p90[0], 1)}


def baseline_intervals(q: dict) -> tuple[list, list, float]:
    return [q["q25"], q["q75"]], [q["q05"], q["q95"]], q["q50"]


def settle_week(api: Espn, path: Path) -> dict:
    rec = json.loads(path.read_text())
    week, my_id = rec["week"], rec["team_id"]
    data = api.league("mTeam", "mRoster", "mMatchup", "mMatchupScore", "mSettings", "mStatus", period=week)
    if int(data.get("scoringPeriodId") or 0) <= week:
        raise SystemExit(f"forecast: week {week} is not over yet (ESPN is on period {data.get('scoringPeriodId')})")
    mv = matchup_view(api, week, data, my_id)
    if mv is None or not mv.get("opp"):
        raise SystemExit("forecast: could not read the finished matchup")
    # player actuals: the roster as it stood in that period, bench included
    actual_by_id: dict[int, float] = {}
    for r in mv["me"]["rows"]:
        if r.get("id") is not None and r.get("actual") is not None:
            actual_by_id[r["id"]] = r["actual"]
    f, b = rec["forecast"], rec["baseline"]
    players = []
    for p in f["players"]:
        a = actual_by_id.get(p["id"])
        if a is None:
            players.append({"name": p["name"], "unsettled": "not on the roster at week end"})
            continue
        row = {"name": p["name"], "pos": p["pos"], "slot": p["slot"],
               "mist": score_interval(a, p["p50"], p["p90"], p.get("median"))}
        bq = b["players"].get(p["name"])
        if bq:
            l50, l90, med = baseline_intervals(bq)
            row["baseline"] = score_interval(a, l50, l90, med)
        players.append(row)
    my_tot = mv["me"]["espn_total"] if mv["me"]["espn_total"] else mv["me"]["actual"]
    opp_tot = mv["opp"]["espn_total"] if mv["opp"]["espn_total"] else mv["opp"]["actual"]
    won = my_tot > opp_tot
    standings = standings_now(data)
    rank = next(i for i, t in enumerate(standings, 1) if t["team_id"] == my_id)
    s = f["standing"]
    out = {
        "settled_at": datetime.now(TZ).isoformat(timespec="minutes"),
        "players": players,
        "team_total": {"mist": score_interval(my_tot, f["team_total"]["p50"], f["team_total"]["p90"], f["team_total"].get("median")),
                       "baseline": score_interval(my_tot, *baseline_intervals(b["team_total"]))},
        "opp_total": {"mist": score_interval(opp_tot, f["opp_total"]["p50"], f["opp_total"]["p90"], f["opp_total"].get("median")),
                      "baseline": score_interval(opp_tot, *baseline_intervals(b["opp_total"])) if b.get("opp_total") else None},
        "result": {"won": won, "us": my_tot, "them": opp_tot,
                   "mist_win_prob": f["win_prob"], "baseline_win_prob": b.get("win_prob"),
                   "mist_brier": round((f["win_prob"] - won) ** 2, 4),
                   "baseline_brier": round((b["win_prob"] - won) ** 2, 4) if b.get("win_prob") is not None else None},
        "standing": {"rank": rank,
                     "mist": score_interval(rank, s["p50"], s["p90"], None),
                     "baseline": score_interval(rank, [b["rank"].get("q25"), b["rank"].get("q75")],
                                                [b["rank"].get("q05"), b["rank"].get("q95")], None),
                     "mist_p_first": s.get("p_first"), "baseline_p_first": b.get("p_first"),
                     "mist_p_top2": s.get("p_top2"), "baseline_p_top2": b.get("p_top2"),
                     "first_brier_mist": round((float(s["p_first"]) - (rank == 1)) ** 2, 4),
                     "first_brier_baseline": round((b["p_first"] - (rank == 1)) ** 2, 4)},
        "standings_after": standings,
    }
    out["coverage"] = coverage([{"settled": out}])
    rec["settled"] = out
    path.write_text(json.dumps(rec, indent=1))
    return rec


def coverage(recs: list[dict]) -> dict:
    """Hit rates over every settled interval in the given records, for both forecasters."""
    tally = {"mist": {"n": 0, "in50": 0, "in90": 0, "abs_err": 0.0},
             "baseline": {"n": 0, "in50": 0, "in90": 0, "abs_err": 0.0}}
    for r in recs:
        s = r.get("settled")
        if not s:
            continue
        items = [p for p in s["players"] if "mist" in p] + [s["team_total"], s["opp_total"]]
        for it in items:
            for who in ("mist", "baseline"):
                sc = it.get(who)
                if not sc:
                    continue
                t = tally[who]
                t["n"] += 1; t["in50"] += sc["in50"]; t["in90"] += sc["in90"]
                t["abs_err"] += abs(sc["error"] or 0.0)
    out = {}
    for who, t in tally.items():
        n = t["n"] or 1
        out[who] = {"n": t["n"], "cov50": round(t["in50"] / n, 3), "cov90": round(t["in90"] / n, 3),
                    "mae": round(t["abs_err"] / n, 2)}
    return out


def render_settled(rec: dict) -> None:
    s = rec["settled"]
    r = s["result"]
    print(f"{rec['team']} -- week {rec['week']} review (settled {s['settled_at']})")
    print(f"  result: {'WON' if r['won'] else 'LOST'} {r['us']:.1f} to {r['them']:.1f} vs {rec['opponent']}   "
          f"MIST win prob {r['mist_win_prob']} (Brier {r['mist_brier']})   baseline {r['baseline_win_prob']} (Brier {r['baseline_brier']})")
    print(f"  {'PLAYER':24} {'POS':4} {'SLOT':5} {'ACT':>6}  {'MIST 50%':>14} {'MIST 90%':>14} {'where':6} {'err':>6}  {'BASE 50%':>14} {'where':6}")
    f = {p["name"]: p for p in rec["forecast"]["players"]}
    for p in s["players"]:
        if "unsettled" in p:
            print(f"  {p['name'][:24]:24} unsettled: {p['unsettled']}")
            continue
        m, fp = p["mist"], f[p["name"]]
        b = p.get("baseline") or {}
        bq = rec["baseline"]["players"].get(p["name"]) or {}
        print(f"  {p['name'][:24]:24} {p['pos']:4} {p['slot']:5} {m['actual']:6.1f}  "
              f"{fp['p50'][0]:6.1f}-{fp['p50'][1]:<6.1f} {fp['p90'][0]:6.1f}-{fp['p90'][1]:<6.1f} {m['where']:6} {m['error'] if m['error'] is not None else '':>6}  "
              f"{bq.get('q25', 0):6.1f}-{bq.get('q75', 0):<6.1f} {b.get('where', ''):6}")
    for k, label in (("team_total", "our total"), ("opp_total", "their total")):
        m = s[k]["mist"]; b = s[k].get("baseline") or {}
        fi = rec["forecast"][k]
        print(f"  {label:24} {'':4} {'':5} {m['actual']:6.1f}  {fi['p50'][0]:6.1f}-{fi['p50'][1]:<6.1f} {fi['p90'][0]:6.1f}-{fi['p90'][1]:<6.1f} {m['where']:6} {m['error'] if m['error'] is not None else '':>6}  {'':14} {b.get('where', ''):6}")
    st = s["standing"]
    fs = rec["forecast"]["standing"]
    print(f"  standing: #{st['rank']}   MIST 50% {fs['p50']} 90% {fs['p90']} -> {st['mist']['where']}   "
          f"P(1st) MIST {st['mist_p_first']} base {st['baseline_p_first']}   P(top2) MIST {st['mist_p_top2']} base {st['baseline_p_top2']}")
    c = s["coverage"]
    print(f"  this week's coverage: MIST 50%={c['mist']['cov50']:.2f} 90%={c['mist']['cov90']:.2f} MAE={c['mist']['mae']}  (n={c['mist']['n']})   "
          f"baseline 50%={c['baseline']['cov50']:.2f} 90%={c['baseline']['cov90']:.2f} MAE={c['baseline']['mae']}")


def all_records(season: int) -> list[dict]:
    if not FORECASTS.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(FORECASTS.glob(f"{season}-w*.json"))]


def render_history(recs: list[dict]) -> None:
    print(f"  {'WEEK':4} {'RESULT':10} {'MIST cov50':>10} {'cov90':>6} {'MAE':>6} {'Brier':>6}  {'BASE cov50':>10} {'cov90':>6} {'MAE':>6} {'Brier':>6}  rank/MIST/base")
    for r in recs:
        s = r.get("settled")
        if not s:
            print(f"  {r['week']:4} open       (issued {r['issued']})")
            continue
        c, res, st = s["coverage"], s["result"], s["standing"]
        result = ("W" if res["won"] else "L") + f" {res['us']:.0f}-{res['them']:.0f}"
        print(f"  {r['week']:4} {result:10} "
              f"{c['mist']['cov50']:10.2f} {c['mist']['cov90']:6.2f} {c['mist']['mae']:6.2f} {res['mist_brier']:6.3f}  "
              f"{c['baseline']['cov50']:10.2f} {c['baseline']['cov90']:6.2f} {c['baseline']['mae']:6.2f} {res['baseline_brier'] if res['baseline_brier'] is not None else float('nan'):6.3f}  "
              f"#{st['rank']} {st['mist']['where']}/{st['baseline']['where']}")
    settled = [r for r in recs if r.get("settled")]
    if settled:
        c = coverage(settled)
        print(f"  season: MIST 50%={c['mist']['cov50']:.2f} 90%={c['mist']['cov90']:.2f} MAE={c['mist']['mae']} (n={c['mist']['n']})   "
              f"baseline 50%={c['baseline']['cov50']:.2f} 90%={c['baseline']['cov90']:.2f} MAE={c['baseline']['mae']}")
        print("  a well-calibrated forecaster lands near 0.50 and 0.90; far above means intervals are too wide, far below too narrow")


# ---- playbook: the Season log by week, with the forecast and review on top ---

def week1_start(api: Espn) -> date:
    """The Tuesday that opens fantasy week 1: two days before its first kickoff."""
    first = None
    for t in api.pro_teams().values():
        for g in (t.get("games") or {}).get("1") or []:
            k = g.get("date")
            if k and (first is None or k < first):
                first = k
    if first is None:
        raise SystemExit("forecast: ESPN has no week-1 schedule to anchor the calendar on")
    kick = datetime.fromtimestamp(first / 1000, TZ).date()
    return kick - timedelta(days=(kick.weekday() - 1) % 7)   # back to Tuesday


def week_of(d: date, start: date) -> int:
    """Fantasy week for a calendar date; 0 is the preseason."""
    if d < start:
        return 0
    return (d - start).days // 7 + 1


def week_label(week: int, start: date) -> str:
    if week == 0:
        return f"Preseason (through {(start - timedelta(days=1)).strftime('%b %-d')})"
    a = start + timedelta(days=7 * (week - 1))
    b = a + timedelta(days=6)
    return f"Week {week} ({a.strftime('%b %-d')} to {b.strftime('%b %-d')})"


BULLET_RE = re.compile(r"^- \*\*(\d{4})-(\d{2})-(\d{2})")
MARK_RE = re.compile(r"<!-- (forecast|review):(\d{4})-w(\d{2}) -->.*?<!-- /\1:\2-w\3 -->\n?", re.S)
WEEK_HDR_RE = re.compile(r"^### (Week \d+|Preseason) \(.*\)\n", re.M)


def split_log(body: str) -> tuple[str, list[tuple[date | None, str]]]:
    """The Season log body -> (intro, [(date, chunk)]). A chunk is one dated
    bullet with every continuation line and callout that follows it, verbatim.
    Week headers and the tool's marked blocks are removed first; they are
    regenerated. Text before the first bullet is the intro and is kept."""
    body = MARK_RE.sub("", body)
    body = WEEK_HDR_RE.sub("", body)
    lines = body.split("\n")
    intro: list[str] = []
    chunks: list[tuple[date | None, str]] = []
    cur: list[str] = []
    cur_date: date | None = None
    for ln in lines:
        m = BULLET_RE.match(ln)
        if m:
            if cur:
                chunks.append((cur_date, "\n".join(cur).rstrip("\n")))
            cur, cur_date = [ln], date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif cur:
            cur.append(ln)
        else:
            intro.append(ln)
    if cur:
        chunks.append((cur_date, "\n".join(cur).rstrip("\n")))
    return "\n".join(intro).strip("\n"), chunks


def fmt_iv(iv: list) -> str:
    return f"{iv[0]:g} to {iv[1]:g}"


def render_forecast_md(rec: dict) -> str:
    f = rec["forecast"]
    issued = datetime.fromisoformat(rec["issued"]).strftime("%a %Y-%m-%d %-I:%M %p")
    tag = f"{rec['season']}-w{rec['week']:02d}"
    out = [f"<!-- forecast:{tag} -->",
           f"#### Forecast (MIST, issued {issued}) vs {rec['opponent']}", ""]
    tt, ot, st = f["team_total"], f["opp_total"], f["standing"]
    b = rec.get("baseline") or {}
    out.append("| | Median | 50% | 90% | Baseline 50% |")
    out.append("|---|---|---|---|---|")
    bq = b.get("team_total") or {}
    out.append(f"| **Our total** | {tt['median']:g} | {fmt_iv(tt['p50'])} | {fmt_iv(tt['p90'])} | {bq.get('q25', '')} to {bq.get('q75', '')} |")
    bq = b.get("opp_total") or {}
    out.append(f"| **{rec['opponent']}** | {ot['median']:g} | {fmt_iv(ot['p50'])} | {fmt_iv(ot['p90'])} | {bq.get('q25', '')} to {bq.get('q75', '')} |")
    out.append(f"| **Win probability** | {f['win_prob']:.2f} | | | {b.get('win_prob', '')} |")
    rq = b.get("rank") or {}
    out.append(f"| **Standing after the week** | {st['median']} | {fmt_iv(st['p50'])} | {fmt_iv(st['p90'])} | {rq.get('q25', '')} to {rq.get('q75', '')} |")
    out.append(f"| **P(first) / P(top two)** | {st['p_first']:.2f} / {st['p_top2']:.2f} | | | {b.get('p_first', '')} / {b.get('p_top2', '')} |")
    out.append("")
    out.append("| Slot | Player | Median | 50% | 90% | Consensus | ESPN |")
    out.append("|---|---|---|---|---|---|---|")
    for p in f["players"]:
        cons = p.get("consensus"); espn = p.get("espn")
        out.append(f"| {p.get('slot', '')} | {p['name']} | {p['median']:g} | {fmt_iv(p['p50'])} | {fmt_iv(p['p90'])} | "
                   f"{'' if cons is None else f'{cons:g}'} | {'' if espn is None else f'{espn:g}'} |")
    out.append("")
    out.append("> [!info]- Why, line by line")
    if f.get("method"):
        out.append(f"> **Method.** {f['method']}")
        out.append(">")
    for p in f["players"]:
        out.append(f"> **{p['name'].rstrip('.')}.** {p['why']}")
    for k, label in (("team_total", "Our total"), ("opp_total", rec["opponent"]), ("standing", "Standing")):
        out.append(f"> **{label}.** {f[k]['why']}")
    if rec.get("forecast_note"):
        out.append("")
        out.append(rec["forecast_note"].rstrip())
    out.append(f"<!-- /forecast:{tag} -->")
    return "\n".join(out) + "\n"


def render_review_md(rec: dict, start: date | None = None) -> str:
    tag = f"{rec['season']}-w{rec['week']:02d}"
    s = rec.get("settled")
    out = [f"<!-- review:{tag} -->"]
    if not s:
        when = ""
        if start:
            tue = start + timedelta(days=7 * rec["week"])
            when = f", settles Tuesday {tue.strftime('%Y-%m-%d')}"
        out += [f"#### Review: pending{when}", f"<!-- /review:{tag} -->"]
        return "\n".join(out) + "\n"
    r, st, c = s["result"], s["standing"], s["coverage"]
    settled = datetime.fromisoformat(s["settled_at"]).strftime("%a %Y-%m-%d %-I:%M %p")
    out.append(f"#### Review (settled {settled}): {'WON' if r['won'] else 'LOST'} {r['us']:.1f} to {r['them']:.1f}, finished #{st['rank']}")
    out.append("")
    out.append("| | MIST 50% | MIST 90% | MAE | Win Brier | P(first) Brier |")
    out.append("|---|---|---|---|---|---|")
    out.append(f"| **MIST** | {c['mist']['cov50']:.2f} | {c['mist']['cov90']:.2f} | {c['mist']['mae']} | {r['mist_brier']} | {st['first_brier_mist']} |")
    out.append(f"| **Baseline** | {c['baseline']['cov50']:.2f} | {c['baseline']['cov90']:.2f} | {c['baseline']['mae']} | {r['baseline_brier']} | {st['first_brier_baseline']} |")
    out.append("")
    out.append("Coverage is the share of intervals that held; calibrated is 0.50 and 0.90. n = " + str(c["mist"]["n"]) + ".")
    out.append("")
    out.append("| Slot | Player | Actual | Median | 50% | 90% | MIST | Baseline | Error |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    fp = {p["name"]: p for p in rec["forecast"]["players"]}
    for p in s["players"]:
        if "unsettled" in p:
            out.append(f"| | {p['name']} | | | | | unsettled: {p['unsettled']} | | |")
            continue
        m, f = p["mist"], fp[p["name"]]
        b = (p.get("baseline") or {}).get("where", "")
        out.append(f"| {p['slot']} | {p['name']} | {m['actual']:g} | {f['median']:g} | {fmt_iv(f['p50'])} | {fmt_iv(f['p90'])} | {m['where']} | {b} | {m['error'] if m['error'] is not None else ''} |")
    for k, label in (("team_total", "Our total"), ("opp_total", rec["opponent"])):
        m = s[k]["mist"]; f = rec["forecast"][k]; b = (s[k].get("baseline") or {}).get("where", "")
        out.append(f"| | **{label}** | {m['actual']:g} | {f['median']:g} | {fmt_iv(f['p50'])} | {fmt_iv(f['p90'])} | {m['where']} | {b} | {m['error'] if m['error'] is not None else ''} |")
    fs = rec["forecast"]["standing"]
    out.append(f"| | **Standing** | #{st['rank']} | {fs['median']} | {fmt_iv(fs['p50'])} | {fmt_iv(fs['p90'])} | {st['mist']['where']} | {st['baseline']['where']} | |")
    out.append("")
    if rec.get("review_note"):
        out.append(rec["review_note"].rstrip())
    else:
        out.append("*Judgment pending: the Tuesday routine writes which misses were reasoning errors and what changes, via `forecast note --review`.*")
    out.append(f"<!-- /review:{tag} -->")
    return "\n".join(out) + "\n"


def rebuild_log(text: str, recs: list[dict], start: date) -> str:
    """The playbook text with its Season log regrouped by week. Every dated
    bullet survives verbatim, newest first within its week; weeks run newest
    first; each week opens with its forecast and review blocks when a filed
    forecast exists."""
    i = text.find(LOG_HEADER)
    if i < 0:
        raise SystemExit("forecast: playbook has no '## Season log' section")
    head, body = text[:i + len(LOG_HEADER)], text[i + len(LOG_HEADER):]
    nxt = re.search(r"^## ", body, re.M)
    tail = ""
    if nxt:
        body, tail = body[:nxt.start()], body[nxt.start():]
    intro, chunks = split_log(body)
    by_rec = {r["week"]: r for r in recs}
    weeks: dict[int, list[str]] = {}
    for d, chunk in chunks:
        weeks.setdefault(week_of(d, start) if d else 0, []).append(chunk)
    for w in by_rec:
        weeks.setdefault(w, [])
    out = [head, ""]
    if intro:
        out += [intro, ""]
    for w in sorted(weeks, reverse=True):
        out.append(f"### {week_label(w, start)}")
        out.append("")
        rec = by_rec.get(w)
        if rec:
            out.append(render_forecast_md(rec))
            out.append(render_review_md(rec, start))
        for chunk in weeks[w]:
            out.append(chunk)
            out.append("")
    result = "\n".join(out).rstrip("\n") + "\n"
    if tail:
        result += "\n" + tail
    return result


def bump_updated(text: str, today: date) -> str:
    return re.sub(r"^updated: .*$", f"updated: {today.isoformat()}", text, count=1, flags=re.M)


def write_playbook(api: Espn, path: Path = PLAYBOOK) -> None:
    text = path.read_text()
    new = rebuild_log(text, all_records(api.season), week1_start(api))
    new = bump_updated(new, datetime.now(TZ).date())
    if new != text:
        path.write_text(new)


# ---- main -----------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="forecast", description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dossier", help="the evidence pack for the week (MIST reads this, then predicts)")
    d.add_argument("--week", type=int)
    d.add_argument("--json", action="store_true")
    d.add_argument("--save", help="also write the dossier JSON here")
    r = sub.add_parser("record", help="validate and file MIST's forecast JSON")
    r.add_argument("path", help="forecast JSON written by MIST ('-' for stdin)")
    r.add_argument("--dossier", help="dossier JSON saved by `dossier --save` (rebuilt if omitted)")
    s = sub.add_parser("settle", help="score a finished week against its forecast")
    s.add_argument("--week", type=int, help="default: the latest unsettled forecast")
    s.add_argument("--json", action="store_true")
    c = sub.add_parser("calibrate", help="rebuild the residual library from Sleeper history")
    c.add_argument("--seasons", default="2025", help="comma list, e.g. 2025,2026")
    h = sub.add_parser("history", help="coverage across the season")
    h.add_argument("--json", action="store_true")
    n = sub.add_parser("note", help="attach MIST's commentary to a week (renders into the playbook)")
    n.add_argument("--week", type=int, required=True)
    g = n.add_mutually_exclusive_group(required=True)
    g.add_argument("--forecast", help="commentary under the forecast block ('-' for stdin)")
    g.add_argument("--review", help="the Tuesday judgment under the review block ('-' for stdin)")
    pb = sub.add_parser("playbook", help="regroup the playbook's Season log by week with forecast and review blocks")
    pb.add_argument("--path", help="playbook path (default: the vault's)")
    for sp in (r, s):
        sp.add_argument("--no-playbook", action="store_true", help="do not rewrite the playbook afterwards")
    args = ap.parse_args(argv)

    api = Espn(load_creds())
    if args.cmd == "calibrate":
        seasons = [int(x) for x in args.seasons.split(",")]
        cur = api.current_week(api.league("mStatus"))
        through = {api.season: max(0, cur - 1)}
        out = calibrate(seasons, through)
        print(json.dumps({"weeks": len(out["weeks"]), "n": out["n"], "quantiles": out["quantiles"]}, indent=1))
        return 0
    if args.cmd == "dossier":
        week = args.week or api.current_week(api.league("mStatus"))
        doss = build_dossier(api, week)
        if args.save:
            Path(args.save).write_text(json.dumps(doss, indent=1, default=str))
        if args.json:
            print(json.dumps(doss, indent=1, default=str))
        else:
            render_dossier(doss)
        return 0
    if args.cmd == "record":
        text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text()
        forecast = json.loads(text)
        if args.dossier:
            doss = json.loads(Path(args.dossier).read_text())
            if doss["week"] != forecast["week"]:
                raise SystemExit("forecast: dossier and forecast are for different weeks")
        else:
            doss = build_dossier(api, int(forecast["week"]))
        path = record(api, forecast, doss)
        print(f"filed {path.relative_to(HERE.parent)}")
        if not args.no_playbook:
            write_playbook(api)
            print("playbook updated")
        return 0
    if args.cmd == "settle":
        recs = all_records(api.season)
        if args.week:
            path = week_file(api.season, args.week)
        else:
            open_ = [r for r in recs if not r.get("settled")]
            if not open_:
                print("forecast: nothing to settle")
                return 0
            path = week_file(api.season, open_[0]["week"])
        rec = settle_week(api, path)
        if args.json:
            print(json.dumps(rec["settled"], indent=1))
        else:
            render_settled(rec)
        if not args.no_playbook:
            write_playbook(api)
            print("playbook updated")
        return 0
    if args.cmd == "note":
        path = week_file(api.season, args.week)
        if not path.exists():
            raise SystemExit(f"forecast: no forecast filed for week {args.week}")
        rec = json.loads(path.read_text())
        raw = args.forecast if args.forecast is not None else args.review
        text = sys.stdin.read() if raw == "-" else raw
        rec["forecast_note" if args.forecast is not None else "review_note"] = text.strip()
        path.write_text(json.dumps(rec, indent=1))
        write_playbook(api)
        print("noted; playbook updated")
        return 0
    if args.cmd == "playbook":
        write_playbook(api, Path(args.path) if args.path else PLAYBOOK)
        print("playbook updated")
        return 0
    if args.cmd == "history":
        recs = all_records(api.season)
        if args.json:
            print(json.dumps([{"week": r["week"], "settled": r.get("settled", {}) and r["settled"].get("coverage")} for r in recs], indent=1))
        else:
            render_history(recs)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
