#!/usr/bin/env python3
"""fp_eval: MIST's weekly ranks, scored the way FantasyPros scores experts.

Question: in the FantasyPros weekly accuracy competition, how would MIST's
blended half-PPR ranks do against the FantasyPros expert consensus (ECR)
and against each of MIST's own sources? The scorer is ffmodel.fpranks,
which carries the published method in its docstring. Each ranker is cut to
the contest depth (QB 20, RB 50, WR 60, TE 15):

  MIST        mean of Sleeper, ESPN (2026 only, players rostered in the
              league) and the market on closing lines, each on half PPR
  MIST-open   the same with the market on opening lines (a timing check;
              it is not in the penalty's field)
  MIST-PPR    MIST's sources on full PPR, so the list is in PPR order, scored
              on half PPR like everything else. The ECR archive holds only
              PPR pages, and this control measures what PPR order alone
              costs a list of MIST's quality (not in the field)
  ECR         FantasyPros' weekly consensus from the DynastyProcess archive
              (the file behind nflreadpy.load_ff_rankings('all')): the PPR
              pages, scraped each Friday. Half-PPR pages are not archived.
  Sleeper     Sleeper alone
  Market      the market alone (players with a line on their core stat)
  Oracle      ranked by the actual points: the positive control, which must
              come first
  Shuffled    MIST's list in random order: the negative control, which must
              come last

Weeks: every week 1-17 with an ECR scrape and market lines. That is 2024
weeks 4-17, 2025 weeks 2-13 and 2026 weeks 1-5.

Variants:
  as_filed          each list as it stood: ECR on Friday, the others at
                    kickoff (closing lines, final projections)
  inactive_removed  players with no box-score line that week leave every
                    list, the ECR list that builds the pool included, before
                    the cut to depth. FantasyPros reads ranks at kickoff,
                    when the inactives are known, so this is the fair test
                    of MIST against ECR.
  weekcurve         inactive_removed with the slot value read from that
                    week's own k-th best scores instead of the historical
                    curve (the methodology page does not give the formula)
  ecrcurve          inactive_removed with the slot value read as the mean
                    points of the player that ECR ranked k-th, in the
                    full-slate weeks of the three previous seasons (the other
                    reading of "the historical production that players at
                    WR #28 generate"; flatter, closer to the page's 8.1 for
                    WR #28)

Uncertainty: the difference MIST - X in Accuracy Gap per pool player-week
(penalties included), with 95% bootstrap intervals over player-weeks (as
asked) and over NFL weeks (rows of one week share rank slots, so the week
bootstrap is the more honest one).

    fp_eval.py [--ecr db_fpecr.parquet] [--boot 2000]

The ECR archive (about 40 MB) downloads to a temporary directory unless
--ecr names a local copy. ESPN's 2026 projections are read from the league's
roster view (5 calls). The run takes about a minute.

INVARIANTS
- Read-only on everything but research/out/fp_eval.json.
- The market model scored on a season was never fitted on it: 2024 is
  scored with a fit on 2025, 2025 with a fit on 2024, and 2026 with
  market_model.json (fit on 2024-2025).
- The slot curve for season S comes from seasons S-3 to S-1 only.
- Every ranker meets the same pool, the same depth and the same field.
- Deterministic: one seeded generator, and lists are in a fixed order
  before every draw.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

FANTASY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FANTASY))

from ffmodel import fpranks, market, nflraw  # noqa: E402

OUT = FANTASY / "research" / "out" / "fp_eval.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
ECR_URL = "https://github.com/dynastyprocess/data/raw/master/files/db_fpecr.parquet"
ECR_PAGES = {"weekly-qb": "QB", "weekly-rb": "RB", "weekly-wr": "WR", "weekly-te": "TE"}
METHOD_URL = "https://www.fantasypros.com/about/faq/football-inseason-accuracy-methodology/"
CONTEST_URL = "https://www.fantasypros.com/weekly-rankings-competition"
SEASONS = (2024, 2025, 2026)
LIVE = 2026
CURVE_YEARS = 3
LAST_WEEK = 17
BOOT = 2000
CHUNK = 200
SEED = 20261015
TRAIN = {2024: [2025], 2025: [2024]}               # 2026: market_model.json (fit 2024-2025)
ORDER = ("Oracle", "MIST", "MIST-open", "MIST-PPR", "ECR", "Sleeper", "Market", "Shuffled")
FIELD = ("MIST", "ECR", "Sleeper", "Market")       # "the average expert" of the penalty
SETS = {"2026": (2026,), "2024-2025": (2024, 2025), "all": SEASONS}
VARIANTS = ("as_filed", "inactive_removed", "weekcurve", "ecrcurve")
SMOOTH = 2                                         # ecrcurve: moving mean over +-2 slots
EXPECT = {
    "control": "Oracle has the lowest gap and Shuffled the highest, in every variant and set.",
    "mist_vs_ecr": ("MIST and ECR within 0.15 points per pool player-week of each other. As filed, MIST "
                    "ahead (its sources are read at kickoff, ECR on Friday). With inactives removed, "
                    "the gap closes and ECR can lead."),
    "blend": "MIST at or below Sleeper alone and Market alone, by less than 0.15.",
}


def slug(name: str) -> str:
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", " ", (name or "").lower())
    return re.sub(r"[^a-z]", "", s)


def r3(x: float) -> float:
    return round(float(x), 3)


# ---- ECR -------------------------------------------------------------------------------

def load_ecr(path: str | None) -> pl.DataFrame:
    """The weekly QB/RB/WR/TE pages of the archive since the 2024 preseason."""
    def scan(p: Path | str) -> pl.DataFrame:
        return (pl.scan_parquet(p)
                .filter(pl.col("page_type").is_in(list(ECR_PAGES))
                        & (pl.col("scrape_date") >= f"{SEASONS[0] - CURVE_YEARS}-08-01"))
                .select("page_type", "id", "player", "ecr", "scrape_date").collect())

    if path:
        df = scan(path)
    else:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "db_fpecr.parquet"
            req = urllib.request.Request(ECR_URL, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r, dest.open("wb") as f:
                shutil.copyfileobj(r, f)
            df = scan(dest)
    return df.with_columns(pl.col("page_type").replace_strict(ECR_PAGES).alias("pos"))


def ecr_lists(ecr: pl.DataFrame, games: pl.DataFrame) -> tuple[dict[tuple[int, int], dict[str, list[str]]], dict]:
    """(season, week) -> pos -> gsis ids in ECR order, from the last scrape
    before that week's games finished. FantasyPros ids map to gsis through
    nflverse's id table, then by unique name and position."""
    import nflreadpy as nfl  # noqa: PLC0415 -- slow import, only this loader needs it

    ids = nfl.load_ff_playerids().select(["fantasypros_id", "gsis_id", "name", "position"])
    by_id: dict[str, str] = {}
    by_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    for f, g, n, p in ids.iter_rows():
        if g is None:
            continue
        if f is not None:
            by_id.setdefault(str(f), str(g))
        if n:
            by_name[(slug(n), str(p))].add(str(g))
    span = list(games.group_by(["season", "week"])
                .agg(pl.col("gameday").min().alias("first"), pl.col("gameday").max().alias("last"))
                .sort(["season", "week"]).iter_rows())
    latest: dict[tuple[int, int], str] = {}
    for d in sorted(set(ecr["scrape_date"].to_list())):
        for s, w, first, last in span:
            if last >= d and (date.fromisoformat(first) - date.fromisoformat(d)).days <= 6:
                key = (int(s), int(w))
                latest[key] = max(d, latest.get(key, d))
                break
    out: dict[tuple[int, int], dict[str, list[str]]] = {}
    unmatched: list[dict] = []
    by_name_hits = 0
    for key, d in sorted(latest.items()):
        if key[1] > LAST_WEEK:
            continue
        sub = ecr.filter(pl.col("scrape_date") == d).sort(["pos", "ecr", "id"])
        lists: dict[str, list[str]] = {}
        for fid, player, pos, _val in sub.select(["id", "player", "pos", "ecr"]).iter_rows():
            g = by_id.get(str(fid))
            if g is None:
                cand = by_name.get((slug(player), pos), set())
                g = next(iter(cand)) if len(cand) == 1 else None
                by_name_hits += g is not None
            lst = lists.setdefault(pos, [])
            if g is None:
                g = f"fp:{fid}"
                if len(lst) < fpranks.CONTEST_DEPTH[pos] and key[0] in SEASONS:
                    unmatched.append({"week": f"{key[0]}-w{key[1]:02d}", "player": player, "pos": pos, "rank": len(lst) + 1})
            if g not in lst:
                lst.append(g)
        out[key] = lists
    report = {"file": ECR_URL, "pages": {v: k for k, v in ECR_PAGES.items()},
              "scrape_by_week": {f"{s}-w{w:02d}": d for (s, w), d in sorted(latest.items())
                                 if w <= LAST_WEEK and s in SEASONS},
              "weeks_before_2024_for_ecrcurve": sum(1 for (s, w) in latest if s < SEASONS[0] and w <= LAST_WEEK),
              "matched_by_name": by_name_hits, "unmatched_within_depth": unmatched}
    return out, report


# ---- data --------------------------------------------------------------------------------

def by_week(src: dict[tuple[int, int, str], tuple[str, float]], pos_of: dict[tuple[int, str], str]) -> dict:
    """(season, week) -> gsis -> (nflverse position when known, points)."""
    out: dict[tuple[int, int], dict[str, tuple[str, float]]] = defaultdict(dict)
    for (s, w, g), (pos, pts) in src.items():
        out[(s, w)][g] = (pos_of.get((s, g), pos), pts)
    return out


def ecr_curve(ecr: dict, actual: dict, teams: dict, season: int) -> tuple[dict[str, list[float]], int]:
    """pos -> mean half-PPR points of the player that ECR ranked k-th (players
    who played only), over the full-slate weeks of the three previous
    seasons; smoothed over +-SMOOTH slots and made non-increasing. Also the
    number of weeks behind it."""
    sums: dict[str, np.ndarray] = {}
    count: dict[str, int] = defaultdict(int)
    weeks = 0
    for (s, w), lists in sorted(ecr.items()):
        if not (season - CURVE_YEARS <= s < season and w <= LAST_WEEK and teams.get((s, w)) == fpranks.FULL_SLATE):
            continue
        weeks += 1
        by = actual.get((s, w), {})
        played = {g for pts in by.values() for g in pts}
        for pos, lst in lists.items():
            pts = [by.get(pos, {}).get(g, 0.0) for g in lst if g in played][: fpranks.CURVE_DEPTH]
            arr = np.zeros(fpranks.CURVE_DEPTH)
            arr[: len(pts)] = pts
            sums[pos] = sums.get(pos, np.zeros(fpranks.CURVE_DEPTH)) + arr
            count[pos] += 1
    out = {}
    k = 2 * SMOOTH + 1
    for pos, tot in sums.items():
        sm = np.convolve(np.pad(tot / count[pos], SMOOTH, mode="edge"), np.ones(k) / k, mode="valid")
        out[pos] = [r3(x) for x in np.minimum.accumulate(sm)]
    return out, weeks


def load_all(ecr_path: str | None) -> dict[str, Any]:
    seasons_all = list(range(SEASONS[0] - CURVE_YEARS, SEASONS[-1] + 1))
    games = nflraw.games(seasons_all)
    teams = {(int(s), int(w)): 2 * int(n) for s, w, n in games.group_by(["season", "week"]).len().iter_rows()}
    act = fpranks.actual_half(seasons_all)
    pos_of = {(s, g): pos for (s, _w, g), (pos, _p) in sorted(act.items())}
    actual: dict[tuple[int, int], dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for (s, w, g), (pos, pts) in act.items():
        actual[(s, w)][pos][g] = pts
    curves = {}
    for season in SEASONS:
        weeks = [(pos, teams[(s, w)], list(d.values())) for (s, w), by in actual.items()
                 if season - CURVE_YEARS <= s < season and w <= LAST_WEEK for pos, d in by.items()]
        curves[season] = fpranks.slot_curve(sorted(weeks, key=lambda t: (t[0], t[1], len(t[2]))))
    ecr, ecr_report = ecr_lists(load_ecr(ecr_path), games)
    ecr_curves, ecr_curve_weeks = {}, {}
    for season in SEASONS:
        ecr_curves[season], ecr_curve_weeks[str(season)] = ecr_curve(ecr, actual, teams, season)
    ecr_report["ecrcurve_full_slate_weeks"] = ecr_curve_weeks
    src: dict[str, dict] = {"sleeper": by_week(fpranks.sleeper_half(list(SEASONS)), pos_of),
                            "sleeper_ppr": by_week(fpranks.sleeper_half(list(SEASONS), ppr=1.0), pos_of)}
    mk: dict[str, dict] = {"close": {}, "open": {}, "close_ppr": {}}
    fits: dict[str, Any] = {}
    for s in SEASONS:
        model = market.fit(market.frame(TRAIN[s], "close")) if s in TRAIN else market.load()
        assert model, "market_model.json is missing; run `python3 -m ffmodel.market fit`"
        fits[str(s)] = TRAIN.get(s, model.get("fit_seasons"))
        for when in ("close", "open"):
            rows = market.frame([s], when).to_dicts()
            mk[when].update(fpranks.market_half(rows, model))
            if when == "close":
                mk["close_ppr"].update(fpranks.market_half(rows, model, ppr=1.0))
    src["market"] = by_week(mk["close"], pos_of)
    src["market_open"] = by_week(mk["open"], pos_of)
    src["market_ppr"] = by_week(mk["close_ppr"], pos_of)
    live_weeks = sorted(w for (s, w) in ecr if s == LIVE)
    src["espn"] = by_week(fpranks.espn_half(LIVE, live_weeks), pos_of)
    src["espn_ppr"] = by_week(fpranks.espn_half(LIVE, live_weeks, ppr=1.0), pos_of)
    eval_weeks = sorted(k for k in ecr if k[0] in SEASONS and k[1] <= LAST_WEEK and k in src["market"] and k in actual)
    return {"teams": teams, "actual": actual, "curves": curves, "ecr_curves": ecr_curves, "ecr": ecr,
            "ecr_report": ecr_report,
            "src": src, "eval_weeks": eval_weeks, "market_fit": fits}


# ---- scoring -------------------------------------------------------------------------------

def week_rankers(d: dict, key: tuple[int, int], variant: str, rng: np.random.Generator) -> tuple[dict, dict, dict]:
    """pos -> ranker -> list, the ECR pool list per position, and source coverage."""
    actual = d["actual"][key]
    played = {g for by in actual.values() for g in by}
    keep_all = variant == "as_filed"

    def gone(proj: dict) -> set[str]:
        return set() if keep_all else {g for g in proj if g not in played}

    sl, mc, mo = d["src"]["sleeper"].get(key, {}), d["src"]["market"].get(key, {}), d["src"]["market_open"].get(key, {})
    es = d["src"]["espn"].get(key, {})
    mist, mist_open = fpranks.blend(sl, es, mc), fpranks.blend(sl, es, mo)
    mist_ppr = fpranks.blend(*(d["src"][k].get(key, {}) for k in ("sleeper_ppr", "espn_ppr", "market_ppr")))
    lists = {"Oracle": fpranks.ranks({g: (pos, pts) for pos, by in actual.items() for g, pts in by.items()}),
             "MIST": fpranks.ranks(mist, exclude=gone(mist)),
             "MIST-open": fpranks.ranks(mist_open, exclude=gone(mist_open)),
             "MIST-PPR": fpranks.ranks(mist_ppr, exclude=gone(mist_ppr)),
             "Sleeper": fpranks.ranks(sl, exclude=gone(sl)),
             "Market": fpranks.ranks(mc, exclude=gone(mc))}
    ecr_full = {pos: [g for g in lst if keep_all or g in played] for pos, lst in d["ecr"][key].items()}
    lists["ECR"] = {pos: lst[: fpranks.CONTEST_DEPTH[pos]] for pos, lst in ecr_full.items()}
    lists["Shuffled"] = {pos: [str(x) for x in rng.permutation(lst)] for pos, lst in sorted(lists["MIST"].items())}
    ranked = [g for lst in lists["MIST"].values() for g in lst]
    cover = {"mist_ranked": len(ranked), "with_espn": sum(g in es for g in ranked),
             "with_market": sum(g in mc for g in ranked), "sources": [mist[g][2] for g in ranked],
             "ecr_pool_inactive": sum(1 for pos, lst in ecr_full.items()
                                      for g in lst[: fpranks.POOL_N[pos]] if g not in played)}
    return {pos: {nm: lists[nm].get(pos, []) for nm in ORDER} for pos in fpranks.SKILL}, ecr_full, cover


def score_all(d: dict, variant: str) -> tuple[list[tuple], dict]:
    """Rows (season, week, pos, pool, losses in ORDER) for one variant."""
    rng = np.random.default_rng(SEED)
    rows: list[tuple] = []
    cover: dict[str, list] = defaultdict(list)
    for key in d["eval_weeks"]:
        s, w = key
        per_pos, ecr_full, cv = week_rankers(d, key, variant, rng)
        for k, v in cv.items():
            cover[k].append((s, w, v))
        for pos in fpranks.SKILL:
            act = d["actual"][key].get(pos, {})
            if variant == "weekcurve":
                curve, teams = fpranks.slot_curve([(pos, fpranks.FULL_SLATE, list(act.values()))]), fpranks.FULL_SLATE
            elif variant == "ecrcurve":
                curve, teams = d["ecr_curves"][s], d["teams"][key]
            else:
                curve, teams = d["curves"][s], d["teams"][key]
            for r in fpranks.score_week(per_pos[pos], ecr_full.get(pos, []), act, pos, curve, teams, field=FIELD):
                rows.append((s, w, pos, r["pool"], [r["loss"][nm] for nm in ORDER]))
    return rows, cover


def boot_ci(dif: np.ndarray, pool: np.ndarray, groups: np.ndarray | None, rng: np.random.Generator,
            n: int) -> list[float]:
    """95% interval of sum(dif) / sum(pool), resampling rows or whole groups."""
    stats = []
    if groups is None:
        m = dif.size
        for start in range(0, n, CHUNK):
            idx = rng.integers(0, m, size=(min(CHUNK, n - start), m))
            stats.append(dif[idx].sum(1) / pool[idx].sum(1))
    else:
        _, g = np.unique(groups, return_inverse=True)
        k = int(g.max()) + 1
        sd, sp = np.bincount(g, weights=dif, minlength=k), np.bincount(g, weights=pool, minlength=k)
        idx = rng.integers(0, k, size=(n, k))
        stats.append(sd[idx].sum(1) / sp[idx].sum(1))
    s = np.concatenate(stats)
    return [r3(np.percentile(s, 2.5)), r3(np.percentile(s, 97.5))]


def summarize(rows: list[tuple], seasons: tuple[int, ...], n_boot: int) -> dict:
    rng = np.random.default_rng(SEED)
    sel = [r for r in rows if r[0] in seasons]
    loss = np.asarray([r[4] for r in sel], dtype=float)
    pool = np.asarray([r[3] for r in sel], dtype=float)
    weeks = np.asarray([f"{r[0]}-{r[1]:02d}" for r in sel])
    pos = np.asarray([r[2] for r in sel])
    n_pool = float(pool.sum())
    mean = {nm: r3(loss[:, i].sum() / n_pool) for i, nm in enumerate(ORDER)}
    by_pos = {p: {nm: r3(loss[pos == p, i].sum() / pool[pos == p].sum()) for i, nm in enumerate(ORDER)}
              for p in fpranks.SKILL}
    by_season = {str(s): {nm: r3(loss[np.char.startswith(weeks, str(s)), i].sum()
                                 / pool[np.char.startswith(weeks, str(s))].sum()) for i, nm in enumerate(ORDER)}
                 for s in seasons}
    cells: dict[tuple, np.ndarray] = defaultdict(lambda: np.zeros(len(ORDER)))
    for r in sel:
        cells[(r[0], r[1], r[2])] += np.asarray(r[4])
    m = ORDER.index("MIST")
    vs: dict[str, dict] = {}
    for i, nm in enumerate(ORDER):
        if nm == "MIST":
            continue
        dif = loss[:, m] - loss[:, i]
        tot = np.asarray([c[m] - c[i] for c in cells.values()])
        vs[nm] = {"mist_minus": r3(dif.sum() / n_pool),
                  "ci_player_weeks": boot_ci(dif, pool, None, rng, n_boot),
                  "ci_weeks": boot_ci(dif, pool, weeks, rng, n_boot),
                  "position_weeks_mist_better": int((tot < 0).sum()), "position_weeks": int(tot.size)}
    order = sorted(ORDER, key=lambda nm: mean[nm])
    z: dict[str, dict] = {}
    for s in seasons:
        totals = {nm: {(w, p): float(c[ORDER.index(nm)]) for (s2, w, p), c in cells.items() if s2 == s} for nm in FIELD}
        z[str(s)] = fpranks.season_scores(totals)
    return {"n_pool_player_weeks": int(n_pool), "n_rows": len(sel), "weeks": len({(r[0], r[1]) for r in sel}),
            "mean_gap": mean, "order": order, "by_pos": by_pos, "by_season": by_season, "vs_mist": vs,
            "season_z_within_field": z,
            "control": {"oracle_first": order[0] == "Oracle", "shuffled_last": order[-1] == "Shuffled"}}


def coverage_summary(cover: dict[str, list]) -> dict:
    out: dict[str, Any] = {}
    for s in SEASONS:
        ranked = sum(v for s2, _, v in cover["mist_ranked"] if s2 == s)
        if not ranked:
            continue
        srcs = [x for s2, _, v in cover["sources"] if s2 == s for x in v]
        out[str(s)] = {"mist_ranked_player_weeks": ranked,
                       "share_with_espn": r3(sum(v for s2, _, v in cover["with_espn"] if s2 == s) / ranked),
                       "share_with_market": r3(sum(v for s2, _, v in cover["with_market"] if s2 == s) / ranked),
                       "sources_per_player": {str(k): srcs.count(k) for k in (1, 2, 3)},
                       "ecr_pool_players_inactive": sum(v for s2, _, v in cover["ecr_pool_inactive"] if s2 == s)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="score MIST's weekly ranks with the FantasyPros accuracy method")
    ap.add_argument("--ecr", help="local copy of db_fpecr.parquet (default: download to a temp dir)")
    ap.add_argument("--boot", type=int, default=BOOT)
    a = ap.parse_args()
    t0 = time.time()
    d = load_all(a.ecr)
    weeks = defaultdict(list)
    for s, w in d["eval_weeks"]:
        weeks[str(s)].append(w)
    c26, e26 = d["curves"][LIVE], d["ecr_curves"][LIVE]
    out: dict[str, Any] = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M"), "expect": EXPECT,
        "sources": {"method": METHOD_URL, "contest": CONTEST_URL, "ecr": d["ecr_report"],
                    "market_fit_seasons": d["market_fit"]},
        "rules": {"contest_depth": fpranks.CONTEST_DEPTH, "pool_n": fpranks.POOL_N, "field": FIELD,
                  "curve": f"mean k-th best half-PPR score, full-slate weeks of the {CURVE_YEARS} previous seasons, "
                           "rank rescaled by 32 / teams playing"},
        "weeks": dict(weeks),
        "curve_2026_check": {
            "order_statistic": {"WR11": c26["WR"][10], "WR28": c26["WR"][27], "QB1": c26["QB"][0],
                                "RB1": c26["RB"][0], "TE12": c26["TE"][11]},
            "ecr_rank": {"WR11": e26["WR"][10], "WR28": e26["WR"][27], "QB1": e26["QB"][0],
                         "RB1": e26["RB"][0], "TE12": e26["TE"][11]},
            "note": "FantasyPros' example: WR #28 'e.g. 8.1 pts', a WR #11 finish '14.3 pts'"},
        "variants": {},
    }
    for v in VARIANTS:
        rows, cover = score_all(d, v)
        out["variants"][v] = {name: summarize(rows, seasons, a.boot) for name, seasons in SETS.items()}
        if v == "as_filed":
            out["coverage"] = coverage_summary(cover)
    out["elapsed_s"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    for v in VARIANTS:
        print(f"\n== {v}")
        for name in SETS:
            sm = out["variants"][v][name]
            print(f"  {name:10} weeks {sm['weeks']:2d}  pool player-weeks {sm['n_pool_player_weeks']}  control {sm['control']}")
            for nm in sm["order"]:
                vs = sm["vs_mist"].get(nm)
                extra = (f"  MIST-{nm} {vs['mist_minus']:+.3f} rows{vs['ci_player_weeks']} weeks{vs['ci_weeks']}"
                         f" better {vs['position_weeks_mist_better']}/{vs['position_weeks']}") if vs else ""
                print(f"    {nm:10} {sm['mean_gap'][nm]:6.3f}{extra}")
    print(f"\nwrote {OUT} in {out['elapsed_s']} s")


if __name__ == "__main__":
    main()
