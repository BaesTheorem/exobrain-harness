"""fpranks: weekly half-PPR ranks for the FantasyPros accuracy competition,
and that competition's scorer, so any set of ranks can be judged by it.

FantasyPros grades more than 150 experts' weekly QB/RB/WR/TE ranks with a
published method. Sources, fetched 2026-10-15:
https://www.fantasypros.com/about/faq/football-inseason-accuracy-methodology/
and the contest page https://www.fantasypros.com/weekly-rankings-competition
(that page still shows the 2023 contest). The method, step by step:

  1. Half PPR. Ranks are read at kickoff: Thursday players at the Thursday
     kickoff, the rest at the 1 p.m. ET Sunday games. Weeks 1-17 count.
  2. The pool for a position is the top N of the week's consensus (ECR) plus
     the top N by actual points: QB 20, RB 40, WR 50, TE 15 (POOL_N).
  3. A rank becomes a prediction, "the average fantasy production for that
     particular rank slot, factoring in bye weeks". The Accuracy Gap of a
     player is |prediction - actual|, and a position's week score is the sum
     over the pool. A pool player that the expert did not rank gets rank
     last+1 when he came in through ECR, and the worse of ECR+1 and last+1
     when he came in only through actual points. A player that the expert
     ranked inside the top N, but who is not in the pool, costs
     max(0, own gap - the average expert's gap).
  4. Weekly gaps become z-scores among all experts. From week 8, the worst
     week of each position is dropped. Overall = QB + RB + WR + TE.

The page gives no formula for the slot value. Here it is the mean k-th best
half-PPR score at the position over the full-slate weeks (all 32 teams play)
of earlier seasons. A week with T teams playing reads slot k at k * 32 / T on
that curve: with four teams on bye, WR 20 reads the curve at 22.9. The page
also says nothing about ties. At the actual-points cutoff, every player tied
with the N-th score enters the pool.

MIST's ranks are the order of the mean of up to three half-PPR projections:
Sleeper (nflraw, league scoring less 0.5 per projected reception), ESPN
(players rostered in the league, less 0.5 per projected reception) and the
market (ffmodel.market, less 0.5 per receptions line; on 2024-2026 that line
is within 0.4 receptions of the mean result at each position).

    half_ppr(full, rec)             one projection on half PPR
    blend(*sources)                 mean of the sources that have the player
    ranks(proj, depth, exclude)     pos -> player ids, best first
    slot_curve(weeks)               the rank-slot value curve
    slot_value(curve, pos, rank, teams)
    player_pool(ecr, actual, pos)   pid -> "ecr" | "actual"
    score_week(rankers, ecr, actual, pos, curve, teams, field)
                                    one row per scored player, all rankers
    week_totals(rows)               ranker -> summed gap for the week
    season_scores(totals)           z-scores, worst week dropped, Overall
    sleeper_half / espn_half / market_half / actual_half
                                    the sources, keyed (season, week, gsis)
    mist_week(season, week)         the live blend for an unplayed week

    python3 -m ffmodel.fpranks week 6           # ranks at contest depth
    python3 -m ffmodel.fpranks week 6 --tsv     # tab-delimited

research/fp_eval.py scores these ranks against FantasyPros' own consensus.

INVARIANTS
- The scorer (half_ppr to season_scores) is pure: lists, dicts and numbers
  in, rows out, no network. tests/test_fantasy_fpranks.py plants each rule.
- One pool per position-week, shared by every ranker. The "average expert"
  of the penalty is the `field` argument, the same for every ranker.
- Ranks are 1-based. An unranked pool player never gets a better rank than
  last+1.
- Read-only against every source. The module writes no file.
"""

from __future__ import annotations

import statistics
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SKILL = ("QB", "RB", "WR", "TE")
CONTEST_DEPTH = {"QB": 20, "RB": 50, "WR": 60, "TE": 15}   # contest page, "Minimum Player Requirements"
POOL_N = {"QB": 20, "RB": 40, "WR": 50, "TE": 15}          # methodology page, step 2
FULL_SLATE = 32
CURVE_DEPTH = 400
HALF = 0.5
DROP_FROM = 8
ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}
ESPN_REC = "53"                                            # receptions, espncli/statmap.py
OUT_STATUS = {"OUT", "INJURY_RESERVE", "SUSPENSION", "DOUBTFUL"}

Key = tuple[int, int, str]                                 # (season, week, gsis id)


# ---- ranks ------------------------------------------------------------------

def half_ppr(full: float, rec: float | None, ppr: float = HALF) -> float:
    """Full-PPR points on this league's scoring, moved to FantasyPros half
    PPR. The two scales differ only in the reception: 1 point against 0.5.
    ppr=1.0 keeps full PPR (fp_eval's PPR-order control)."""
    return round(float(full) - (1.0 - ppr) * float(rec or 0.0), 3)


def blend(*sources: Mapping[str, tuple[str, float]]) -> dict[str, tuple[str, float, int]]:
    """pid -> (pos, mean points, number of sources). A player takes the mean
    of the sources that have him; the position comes from the first one."""
    acc: dict[str, list[Any]] = {}
    for src in sources:
        for pid, (pos, pts) in src.items():
            if pts is None:
                continue
            a = acc.setdefault(pid, [pos, 0.0, 0])
            a[1] += float(pts)
            a[2] += 1
    return {pid: (pos, round(s / n, 3), n) for pid, (pos, s, n) in acc.items()}


def ranks(proj: Mapping[str, Sequence[Any]], depth: Mapping[str, int] = CONTEST_DEPTH,
          exclude: Iterable[str] = ()) -> dict[str, list[str]]:
    """pos -> player ids by projection, best first, cut to depth. proj values
    start with (pos, points); ties go to the smaller id, so the order is
    stable."""
    skip = set(exclude)
    by: dict[str, list[tuple[float, str]]] = {}
    for pid, v in proj.items():
        pos, pts = v[0], v[1]
        if pos in depth and pid not in skip and pts is not None:
            by.setdefault(pos, []).append((float(pts), pid))
    return {pos: [pid for _, pid in sorted(rows, key=lambda t: (-t[0], t[1]))[: depth[pos]]]
            for pos, rows in by.items()}


# ---- the FantasyPros scorer -----------------------------------------------------

def slot_curve(weeks: Iterable[tuple[str, int, Sequence[float]]], depth: int = CURVE_DEPTH) -> dict[str, list[float]]:
    """pos -> mean k-th best score for k = 1..depth, over full-slate weeks.

    weeks: (pos, teams playing, every score at the position that week). A
    week with byes is skipped, because slot_value() rescales the rank for
    byes. Slots past the last player with a stat line are 0 points (an
    active player with no stat line scores nothing), and a negative score
    sorts below them."""
    sums: dict[str, list[float]] = {}
    count: dict[str, int] = {}
    for pos, teams, scores in weeks:
        if teams < FULL_SLATE:
            continue
        s = sorted([float(x) for x in scores] + [0.0] * max(0, depth - len(scores)), reverse=True)[:depth]
        acc = sums.setdefault(pos, [0.0] * depth)
        for i, v in enumerate(s):
            acc[i] += v
        count[pos] = count.get(pos, 0) + 1
    return {pos: [round(v / count[pos], 3) for v in acc] for pos, acc in sums.items()}


def slot_value(curve: Mapping[str, Sequence[float]], pos: str, rank: float, teams: int = FULL_SLATE) -> float:
    """The predicted points of rank `rank` in a week where `teams` teams play:
    the curve read at rank * 32 / teams, linear between slots."""
    c = curve[pos]
    x = max(1.0, float(rank) * FULL_SLATE / max(int(teams), 1))
    i = int(x)
    if i >= len(c):
        return float(c[-1])
    lo, hi = c[i - 1], c[i]
    return float(lo + (x - i) * (hi - lo))


def player_pool(ecr: Sequence[str], actual: Mapping[str, float], pos: str, n: int | None = None) -> dict[str, str]:
    """pid -> "ecr" or "actual": the top n of the consensus, then every player
    whose actual points reach the n-th best score (ties at the cutoff are
    all in). `actual` holds this position's players only."""
    n = n or POOL_N[pos]
    pool = {pid: "ecr" for pid in ecr[:n]}
    scored = sorted(actual.items(), key=lambda t: (-t[1], t[0]))
    if scored:
        cut = scored[min(n, len(scored)) - 1][1]
        for pid, pts in scored:
            if pts < cut:
                break
            pool.setdefault(pid, "actual")
    return pool


def score_week(rankers: Mapping[str, Sequence[str]], ecr: Sequence[str], actual: Mapping[str, float], pos: str,
               curve: Mapping[str, Sequence[float]], teams: int = FULL_SLATE,
               field: Iterable[str] | None = None, n: int | None = None) -> list[dict]:
    """Score every ranker on one position-week, on one shared pool.

    rankers: name -> player ids as submitted (rank 1 first, already cut to
             depth)
    ecr:     the consensus order at full depth; it makes half the pool and
             gives the fallback rank of an actual-only pool player
    actual:  pid -> half-PPR points of this position's players (a player who
             is absent scored 0)
    field:   the rankers whose mean gap stands in for "the average expert"
             in the penalty (default: all of them)

    Returns one row per scored player: {"pid", "pool", "via", "actual",
    "rank": {name: r}, "loss": {name: points}}. A pool row's loss is the
    Accuracy Gap; a non-pool row's loss is the penalty (0 for a ranker that
    did not rank him inside the top n)."""
    n = n or POOL_N[pos]
    pool = player_pool(ecr, actual, pos, n)
    ecr_rank = {pid: i for i, pid in enumerate(ecr, 1)}
    idx = {name: {pid: i for i, pid in enumerate(lst, 1)} for name, lst in rankers.items()}
    fld = [f for f in (field if field is not None else rankers) if f in rankers] or list(rankers)

    def value(r: float) -> float:
        return slot_value(curve, pos, r, teams)

    rows: list[dict] = []
    for pid, via in pool.items():
        a = float(actual.get(pid, 0.0))
        row: dict = {"pid": pid, "pool": True, "via": via, "actual": a, "rank": {}, "loss": {}}
        for name, lst in rankers.items():
            r = idx[name].get(pid)
            if r is None:
                last = len(lst) + 1
                r = last if via == "ecr" else max(ecr_rank.get(pid, len(ecr) + 1) + 1, last)
            row["rank"][name] = r
            row["loss"][name] = round(abs(value(r) - a), 3)
        rows.append(row)
    inside = {pid for lst in rankers.values() for pid in lst[:n]}
    for pid in sorted(inside - set(pool)):
        a = float(actual.get(pid, 0.0))
        rank = {name: idx[name].get(pid, len(lst) + 1) for name, lst in rankers.items()}
        gap = {name: abs(value(r) - a) for name, r in rank.items()}
        avg = statistics.fmean(gap[f] for f in fld)
        loss = {name: round(max(0.0, gap[name] - avg), 3) if idx[name].get(pid, n + 1) <= n else 0.0
                for name in rankers}
        rows.append({"pid": pid, "pool": False, "via": None, "actual": a, "rank": rank, "loss": loss})
    return rows


def week_totals(rows: Iterable[dict]) -> dict[str, float]:
    """ranker -> the position-week score: Accuracy Gaps plus penalties."""
    out: dict[str, float] = {}
    for r in rows:
        for name, x in r["loss"].items():
            out[name] = out.get(name, 0.0) + x
    return {k: round(v, 3) for k, v in out.items()}


def season_scores(totals: Mapping[str, Mapping[tuple[int, str], float]], drop_from: int = DROP_FROM) -> dict[str, dict]:
    """Step 4 for one season. totals: ranker -> {(week, pos): week score}.

    Each (week, pos) becomes z-scores across the rankers that have it (lower
    is better, as with the gap). A position with drop_from or more weeks
    drops its worst one. Returns ranker -> {pos: summed z, "overall": QB +
    RB + WR + TE}. With a small field the z-scores say only how the rankers
    here compare, never where they would place among FantasyPros' experts."""
    names = list(totals)
    cells = sorted(set().union(*[set(t) for t in totals.values()])) if totals else []
    z: dict[str, dict[str, list[float]]] = {nm: {} for nm in names}
    for cell in cells:
        have = [nm for nm in names if cell in totals[nm]]
        if len(have) < 2:
            continue
        xs = [float(totals[nm][cell]) for nm in have]
        mu, sd = statistics.fmean(xs), statistics.pstdev(xs)
        for nm, x in zip(have, xs, strict=True):
            z[nm].setdefault(cell[1], []).append(0.0 if sd == 0 else (x - mu) / sd)
    out: dict[str, dict] = {}
    for nm in names:
        res: dict[str, float] = {}
        for pos, zs in z[nm].items():
            kept = sorted(zs)[:-1] if len(zs) >= drop_from else zs
            res[pos] = round(sum(kept), 3)
        res["overall"] = round(sum(res.get(p, 0.0) for p in SKILL), 3)
        out[nm] = res
    return out


# ---- sources --------------------------------------------------------------------

def _pkg() -> None:
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))


def actual_half(seasons: list[int]) -> dict[Key, tuple[str, float]]:
    """Box-score points on half PPR for every QB/RB/WR/TE with a stat line."""
    import polars as pl  # noqa: PLC0415 -- heavy import, only the data path needs it

    _pkg()
    from ffmodel import nflraw  # noqa: PLC0415

    pw = (nflraw.player_weeks(seasons).filter(pl.col("pos").is_in(SKILL))
          .select(["season", "week", "player_id", "pos", "pts", "receptions"]))
    return {(int(s), int(w), str(g)): (str(p), half_ppr(pts, rec)) for s, w, g, p, pts, rec in pw.iter_rows()}


def sleeper_half(seasons: list[int], ppr: float = HALF) -> dict[Key, tuple[str, float]]:
    """Sleeper's weekly projection (nflraw, league scoring) on half PPR. When
    two Sleeper rows map to one player, the larger projection is kept."""
    import polars as pl  # noqa: PLC0415

    _pkg()
    from ffmodel import nflraw  # noqa: PLC0415

    sl = (nflraw.sleeper_weeks(seasons).filter(pl.col("gsis_id").is_not_null() & pl.col("pos").is_in(SKILL))
          .select(["season", "week", "gsis_id", "pos", "proj", "proj_rec"]))
    out: dict[Key, tuple[str, float]] = {}
    for s, w, g, pos, proj, rec in sl.iter_rows():
        k = (int(s), int(w), str(g))
        v = half_ppr(proj, rec, ppr)
        if k not in out or v > out[k][1]:
            out[k] = (str(pos), v)
    return out


def market_half(rows: list[dict], model: dict, ppr: float = HALF) -> dict[Key, tuple[str, float]]:
    """Market points on half PPR for rows of market.frame(): the model's
    full-PPR projection less half the receptions line (rebuilt by the
    model's fills when the book posted none). Conditional on playing, like
    market.predict_rows."""
    _pkg()
    from ffmodel import market  # noqa: PLC0415

    pred = market.predict_rows(rows, model)
    out: dict[Key, tuple[str, float]] = {}
    for r, v in zip(rows, pred, strict=True):
        if v is None or r.get("pos") not in SKILL or r.get("gsis_id") is None:
            continue
        out[(int(r["season"]), int(r["week"]), str(r["gsis_id"]))] = (r["pos"], half_ppr(v, _rec_line(r, model), ppr))
    return out


def _rec_line(r: dict, model: dict) -> float:
    if r.get("pos") == "QB":
        return 0.0
    _pkg()
    from ffmodel import market  # noqa: PLC0415

    x = market.complete(r, model.get("fills") or {})
    return float(x["receptions"]) if x and x.get("receptions") is not None else 0.0


def _espn_to_gsis() -> dict[str, str]:
    _pkg()
    from ffmodel import nflraw  # noqa: PLC0415

    return {str(e): str(g) for e, g in nflraw.id_table().select(["espn_id", "gsis_id"]).drop_nulls().iter_rows()}


def espn_half(season: int, weeks: list[int], out_ids: set[str] | None = None,
              ppr: float = HALF) -> dict[Key, tuple[str, float]]:
    """ESPN's weekly projection on half PPR for every player rostered in the
    league that week (the roster view of a period keeps that period's
    projection; see market._espn_projections). Only the league's own season
    is reachable; another season returns {}. When out_ids is a set, the
    gsis ids of rostered players listed OUT, IR, suspended or doubtful are
    added to it (the status is today's, so it means something only for the
    coming week)."""
    _pkg()
    from espncli.client import SRC_PROJ, STAT_WEEK, Espn  # noqa: PLC0415

    api = Espn()
    if season != api.season:
        return {}
    ids = _espn_to_gsis()
    out: dict[Key, tuple[str, float]] = {}
    for w in weeks:
        data = api.league("mRoster", period=w)
        for t in data["teams"]:
            for e in (t.get("roster") or {}).get("entries", []):
                p = (e.get("playerPoolEntry") or {}).get("player") or {}
                pos = ESPN_POS.get(p.get("defaultPositionId") or 0)
                gsis = ids.get(str(p.get("id")))
                if pos is None or gsis is None:
                    continue
                if out_ids is not None and str(p.get("injuryStatus") or "") in OUT_STATUS:
                    out_ids.add(gsis)
                for s in p.get("stats") or []:
                    if (s.get("seasonId") == season and s.get("scoringPeriodId") == w
                            and s.get("statSourceId") == SRC_PROJ and s.get("statSplitTypeId") == STAT_WEEK
                            and s.get("appliedTotal") is not None):
                        out[(season, w, gsis)] = (pos, half_ppr(s["appliedTotal"], (s.get("stats") or {}).get(ESPN_REC), ppr))
                        break
    return out


def market_live_half(season: int, week: int) -> dict[str, tuple[str, float]]:
    """gsis -> market points on half PPR from the current lines of an
    unplayed week (market.week_cached; {} when the books are unreachable)."""
    _pkg()
    from ffmodel import market  # noqa: PLC0415

    model = market.load() or {}
    ids = _espn_to_gsis()
    out: dict[str, tuple[str, float]] = {}
    for ath, v in market.week_cached(season, week).items():
        pos, gsis = v.get("pos"), ids.get(str(ath))
        if pos not in SKILL or gsis is None:
            continue
        row = {**(v.get("lines") or {}), "pos": pos, "implied": v.get("implied")}
        out[gsis] = (pos, half_ppr(v["market"], _rec_line(row, model)))
    return out


def mist_week(season: int, week: int) -> tuple[dict[str, dict], set[str]]:
    """The live blend for an unplayed week: gsis -> {"name", "team", "pos",
    "half", "n", "sleeper", "espn", "market"}, and the ids ESPN lists as out.
    A dead source is reported on stderr and left out of the mean."""
    _pkg()
    from ffmodel import nflraw  # noqa: PLC0415

    sl = {g: v for (_, w, g), v in sleeper_half([season]).items() if w == week}
    out_ids: set[str] = set()
    try:
        es = {g: v for (_, _, g), v in espn_half(season, [week], out_ids).items()}
    except Exception as exc:  # noqa: BLE001 -- ESPN is one vote of three; the ranks run without it
        print(f"fpranks: espn unavailable ({exc})", file=sys.stderr)
        es = {}
    mk = market_live_half(season, week)
    names = {str(g): (n, t) for g, n, t in nflraw.id_table().select(["gsis_id", "name", "team"]).drop_nulls("gsis_id").iter_rows()}
    res: dict[str, dict] = {}
    for g, (pos, pts, n) in blend(sl, es, mk).items():
        nm, team = names.get(g, (g, None))
        res[g] = {"name": nm, "team": team, "pos": pos, "half": pts, "n": n,
                  "sleeper": (sl.get(g) or (None, None))[1], "espn": (es.get(g) or (None, None))[1],
                  "market": (mk.get(g) or (None, None))[1]}
    return res, out_ids


# ---- the prospective test: both lists at kickoff, scored after the games ----------
# research/fp_eval.py found MIST's ranks ahead of FantasyPros' consensus on 31
# past weeks, but its consensus was a Friday snapshot and in PPR order. The
# clean test saves MIST's ranks and the half-PPR ECR at the same moment before
# the Sunday 1 p.m. ET games, and scores both on the week's results.

FP_PAGES = {"QB": "qb.php", "RB": "half-point-ppr-rb.php", "WR": "half-point-ppr-wr.php",
            "TE": "half-point-ppr-te.php"}
SNAPSHOTS = HERE.parent / "forecasts" / "fp"


def ecr_live(week: int) -> dict[str, list[str]]:
    """pos -> gsis ids in FantasyPros' current weekly consensus order (half
    PPR for RB/WR/TE). Raises when a page is not for `week`."""
    import json as _json  # noqa: PLC0415
    import re  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    import nflreadpy as nfl  # noqa: PLC0415
    import polars as pl  # noqa: PLC0415

    ua = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/141.0 Safari/537.36"}
    ids = nfl.load_ff_playerids().select(["fantasypros_id", "gsis_id"]).drop_nulls()
    fp_to_gsis = {str(int(f)) if str(f).replace(".0", "").isdigit() else str(f): str(g)
                  for f, g in ids.iter_rows()}
    _ = pl
    out: dict[str, list[str]] = {}
    for pos, page in FP_PAGES.items():
        html = urllib.request.urlopen(urllib.request.Request(f"https://www.fantasypros.com/nfl/rankings/{page}", headers=ua),
                                      timeout=40).read().decode("utf-8", "replace")
        m = re.search(r"var ecrData = (\{.*?\});", html, re.S)
        if not m:
            raise RuntimeError(f"no ecrData on {page}")
        d = _json.loads(m.group(1))
        if int(d.get("week") or 0) != week:
            raise RuntimeError(f"{page} is for week {d.get('week')}, not {week}")
        players = sorted(d.get("players") or [], key=lambda x: x.get("rank_ecr") or 9999)
        out[pos] = [g for x in players if (g := fp_to_gsis.get(str(x.get("player_id"))))]
    return out


def snapshot(season: int, week: int) -> Path:
    """Save MIST's ranks and the live consensus side by side, timestamped."""
    import datetime as _dt  # noqa: PLC0415
    import json as _json  # noqa: PLC0415

    proj, out_ids = mist_week(season, week)
    mine = ranks({g: (v["pos"], v["half"]) for g, v in proj.items()}, CONTEST_DEPTH, exclude=out_ids)
    rec = {"season": season, "week": week, "taken": _dt.datetime.now().astimezone().isoformat(timespec="minutes"),
           "mist": {p: list(v) for p, v in mine.items()}, "ecr": ecr_live(week),
           "names": {g: v["name"] for g, v in proj.items()}}
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS / f"{season}-w{week:02d}.json"
    path.write_text(_json.dumps(rec, indent=1) + "\n")
    return path


def _curve(season: int) -> dict[str, list[float]]:
    """The slot curve from the three seasons before `season`, full-slate weeks."""
    _pkg()
    from ffmodel import nflraw  # noqa: PLC0415

    seasons = [season - 3, season - 2, season - 1]
    act = actual_half(seasons)
    games = nflraw.games(seasons)
    teams = {(int(s), int(w)): 0 for s, w in games.select(["season", "week"]).iter_rows()}
    for s, w in games.select(["season", "week"]).iter_rows():
        teams[(int(s), int(w))] += 2
    by: dict[tuple[int, int, str], list[float]] = {}
    for (s, w, _g), (pos, pts) in act.items():
        by.setdefault((s, w, pos), []).append(pts)
    return slot_curve([(pos, teams.get((s, w), 0), v) for (s, w, pos), v in sorted(by.items())])


def score_snapshot(season: int, week: int) -> dict:
    """MIST against the consensus for one saved week, on FantasyPros' method."""
    import json as _json  # noqa: PLC0415

    _pkg()
    from ffmodel import nflraw  # noqa: PLC0415

    rec = _json.loads((SNAPSHOTS / f"{season}-w{week:02d}.json").read_text())
    act = {g: v for (s, w, g), v in actual_half([season]).items() if s == season and w == week}
    games = nflraw.games([season])
    teams = 2 * games.filter(games["week"] == week).height
    curve = _curve(season)
    out: dict = {"season": season, "week": week, "taken": rec["taken"], "by_pos": {}}
    for pos in SKILL:
        actual = {g: pts for g, (p, pts) in act.items() if p == pos}
        ecr = rec["ecr"].get(pos) or []
        rankers = {"mist": rec["mist"].get(pos) or [], "ecr": ecr[:CONTEST_DEPTH[pos]]}
        rows = score_week(rankers, ecr, actual, pos, curve, teams)
        tot = week_totals(rows)
        out["by_pos"][pos] = {"mist": tot.get("mist", 0.0), "ecr": tot.get("ecr", 0.0), "pool": sum(r["pool"] for r in rows)}
    out["mist"] = round(sum(v["mist"] for v in out["by_pos"].values()), 2)
    out["ecr"] = round(sum(v["ecr"] for v in out["by_pos"].values()), 2)
    out["mist_minus_ecr"] = round(out["mist"] - out["ecr"], 2)
    return out


if __name__ == "__main__":
    import argparse

    _pkg()
    from ffmodel import nflraw

    ap = argparse.ArgumentParser(description="MIST's weekly half-PPR ranks at FantasyPros contest depth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    wk = sub.add_parser("week")
    wk.add_argument("week", type=int)
    wk.add_argument("--season", type=int, default=nflraw.current_season())
    wk.add_argument("--tsv", action="store_true", help="tab-delimited: pos, rank, name, team, half-PPR points")
    sn = sub.add_parser("snapshot", help="save MIST's ranks and the live consensus before Sunday kickoff")
    sn.add_argument("week", type=int)
    sn.add_argument("--season", type=int, default=nflraw.current_season())
    sc = sub.add_parser("score", help="score every saved week (or one) on FantasyPros' method")
    sc.add_argument("--week", type=int)
    sc.add_argument("--season", type=int, default=nflraw.current_season())
    a = ap.parse_args()
    if a.cmd == "snapshot":
        print(f"saved {snapshot(a.season, a.week)}")
        raise SystemExit(0)
    if a.cmd == "score":
        weeks = [a.week] if a.week else sorted(int(f.stem.split("-w")[1]) for f in SNAPSHOTS.glob(f"{a.season}-w*.json"))
        diffs = []
        for w in weeks:
            try:
                r = score_snapshot(a.season, w)
            except FileNotFoundError:
                continue
            diffs.append(r["mist_minus_ecr"])
            print(f"week {w:2d}  MIST {r['mist']:8.1f}  ECR {r['ecr']:8.1f}  MIST-ECR {r['mist_minus_ecr']:+7.1f}  "
                  + "  ".join(f"{p} {v['mist'] - v['ecr']:+.1f}" for p, v in r["by_pos"].items()))
        if diffs:
            print(f"{len(diffs)} weeks, mean MIST-ECR {statistics.fmean(diffs):+.1f} (lower is better for MIST)")
        raise SystemExit(0)
    proj, out_ids = mist_week(a.season, a.week)
    order = ranks({g: (v["pos"], v["half"]) for g, v in proj.items()}, CONTEST_DEPTH, exclude=out_ids)
    for pos in SKILL:
        if not a.tsv:
            print(f"\n{pos} (top {CONTEST_DEPTH[pos]})")
        for i, g in enumerate(order.get(pos, []), 1):
            v = proj[g]
            if a.tsv:
                print(f"{pos}\t{i}\t{v['name']}\t{v['team'] or ''}\t{v['half']:.2f}")
            else:
                src = " ".join(f"{k[0].upper()}{v[k]:.1f}" for k in ("sleeper", "espn", "market") if v[k] is not None)
                print(f"{i:3d} {v['name'][:24]:24} {v['team'] or '':4} {v['half']:6.2f}  {src}")
