"""corr: how players' weekly surprises move together, measured.

The variance rule (`espncli.value.win_prob`) treated every starter as an
independent draw. Football does not: when a quarterback beats his
projection his receivers usually do too, and a defense that beats its
projection usually means the offense it faced did not. Starting a quarterback
with his own receiver widens a lineup's spread; starting a defense against
the opponent's quarterback ties the two sides together. This measures those
links so the win probability can carry them.

Method. Each player-week's surprise is z = (actual - expected) / sd, with
`expected` Sleeper's archived pre-game projection rescored on league points
(model.nflraw.sleeper_weeks) and sd the same tiered spread `win_prob` uses
(value.player_sd). Every pair of fantasy-relevant players in the same game
is a pair of surprises; the pair's category is the relation (same team or
opponents) and each player's role (position, and tier by projection). The
correlation per category is plain Pearson over every pair, 2022-2025.

    build()        estimate the table and write model/corr_table.json
    load()         read the table: {category: rho}
    pair_key(a, b) the category for two rows with pos, proj, team, opp
    rho(a, b, t)   the correlation `win_prob` applies to two starters

The table is aggregate statistics with no personal data, so it is tracked:
a fresh clone gets the same win probability as this machine.

INVARIANTS
- rho() is 0 for players in different NFL games and for a category with
  fewer than MIN_PAIRS pairs. A missing table means independence, which is
  the old behaviour, never a crash.
- Roles are assigned from the projection alone (TIER_CUTS), at estimation
  and at use, so the two can never disagree about who is a WR1.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TABLE = HERE / "corr_table.json"
SEASONS = (2022, 2023, 2024, 2025)
TIER_CUTS = {"RB": 11.0, "WR": 11.0, "TE": 8.0}    # projection at or above = tier 1
MIN_PROJ = {"QB": 10.0, "RB": 4.0, "WR": 4.0, "TE": 3.0, "K": 0.0, "D/ST": -99.0}
MIN_PAIRS = 300


def role(pos: str, proj: float) -> str:
    cut = TIER_CUTS.get(pos)
    if cut is None:
        return pos
    return f"{pos}1" if proj >= cut else f"{pos}2"


def _plain(team: str | None) -> str:
    return (team or "").lstrip("@")


def pair_key(a: dict, b: dict) -> str | None:
    """'same:QB|WR1' or 'opp:D/ST|QB', or None when the two are not in one game."""
    ta, tb = _plain(a.get("team")), _plain(b.get("team"))
    if not ta or not tb:
        return None
    if ta == tb:
        rel = "same"
    elif _plain(a.get("opp")) == tb or _plain(b.get("opp")) == ta:
        rel = "opp"
    else:
        return None
    ra = role(a.get("pos") or "?", float(a.get("proj") or 0.0))
    rb = role(b.get("pos") or "?", float(b.get("proj") or 0.0))
    lo, hi = sorted((ra, rb))
    return f"{rel}:{lo}|{hi}"


def load(path: Path = TABLE) -> dict[str, float]:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {k: float(v["rho"]) for k, v in (d.get("pairs") or {}).items() if v.get("n", 0) >= MIN_PAIRS}


def rho(a: dict, b: dict, table: dict[str, float]) -> float:
    k = pair_key(a, b)
    return table.get(k, 0.0) if k else 0.0


def _frames():
    import polars as pl  # noqa: PLC0415

    sys.path.insert(0, str(HERE.parent))
    from espncli.value import player_sd  # noqa: PLC0415
    from ffmodel import nflraw  # noqa: PLC0415

    seasons: list[int] = list(SEASONS)
    proj = nflraw.sleeper_weeks(seasons)
    off = nflraw.player_weeks(seasons).filter(pl.col("pos").is_in(["QB", "RB", "WR", "TE", "K"]))
    off = off.join(proj.filter(pl.col("gsis_id").is_not_null()).select(["season", "week", "gsis_id", "proj"]),
                   left_on=["season", "week", "player_id"], right_on=["season", "week", "gsis_id"], how="inner")
    dst = nflraw.dst_weeks(seasons).join(
        proj.filter(pl.col("pos") == "D/ST").select(["season", "week", "team", "proj"]),
        on=["season", "week", "team"], how="inner")
    cols = ["season", "week", "game_id", "team", "opp", "pos", "proj", "pts"]
    both = pl.concat([off.select(cols), dst.select(cols)], how="diagonal_relaxed")
    both = both.filter(pl.col("proj") >= pl.col("pos").replace_strict(MIN_PROJ, default=0.0))
    sd = [player_sd(p, x) or 1.5 for p, x in zip(both["pos"].to_list(), both["proj"].to_list(), strict=True)]
    return both.with_columns(((pl.col("pts") - pl.col("proj")) / pl.Series("sd", sd)).alias("z"))


def build(path: Path = TABLE) -> dict:
    """Estimate every category's correlation and write the table."""
    import numpy as np  # noqa: PLC0415

    df = _frames()
    sums: dict[str, list[float]] = {}
    by_season: dict[str, dict[int, list[float]]] = {}
    for (_gid,), g in df.group_by(["game_id"]):
        rows = g.to_dicts()
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                k = pair_key(rows[i], rows[j])
                if k is None:
                    continue
                a, b = rows[i]["z"], rows[j]["z"]
                s = sums.setdefault(k, [0.0] * 6)          # n, sa, sb, saa, sbb, sab
                s[0] += 1; s[1] += a; s[2] += b; s[3] += a * a; s[4] += b * b; s[5] += a * b
                bs = by_season.setdefault(k, {}).setdefault(rows[i]["season"], [0.0] * 6)
                bs[0] += 1; bs[1] += a; bs[2] += b; bs[3] += a * a; bs[4] += b * b; bs[5] += a * b

    def pearson(s: list[float]) -> float | None:
        n, sa, sb, saa, sbb, sab = s
        if n < 3:
            return None
        va, vb = saa / n - (sa / n) ** 2, sbb / n - (sb / n) ** 2
        if va <= 0 or vb <= 0:
            return None
        return ((sab / n) - (sa / n) * (sb / n)) / float(np.sqrt(va * vb))

    pairs = {}
    for k, s in sorted(sums.items()):
        r = pearson(s)
        if r is None:
            continue
        n = int(s[0])
        se = 1.0 / float(np.sqrt(max(n - 3, 1)))
        z = float(np.arctanh(np.clip(r, -0.999, 0.999)))
        pairs[k] = {"rho": round(r, 3), "n": n,
                    "ci95": [round(float(np.tanh(z - 1.96 * se)), 3), round(float(np.tanh(z + 1.96 * se)), 3)],
                    "by_season": {str(y): round(v, 3) for y, ss in sorted(by_season[k].items())
                                  if (v := pearson(ss)) is not None}}
    out = {"built_from": f"nflverse box scores vs Sleeper pre-game projections, seasons {SEASONS[0]}-{SEASONS[-1]}, "
                         "league scoring; z = (actual - projection) / value.player_sd",
           "tier_cuts": TIER_CUTS, "min_proj": MIN_PROJ, "player_weeks": df.height, "pairs": pairs}
    path.write_text(json.dumps(out, indent=1) + "\n")
    return out


def validate(holdout: int = 2025, sims: int = 20000, seed: int = 3) -> dict:
    """Out-of-sample check: estimate the table without `holdout`, then score
    synthetic head-to-head matchups built from that season's real player-weeks.

    Each matchup is two legal starting nines (QB, RB, RB, WR, WR, TE, FLEX,
    K, D/ST) drawn from one week's fantasy-relevant players. Two draws: plain
    random lineups (stacks only by chance, as in a real draft), and stressed
    ones where each side starts its QB with his WR1 and its D/ST against the
    other side's QB. For each, the z of the realized margin against the
    projected margin over the model's sd should have variance 1. The
    prediction: independence understates the spread on the stressed draws
    and the measured correlations do not."""
    import numpy as np  # noqa: PLC0415

    global SEASONS  # noqa: PLW0603 -- the estimate must not see the held-out season
    keep = SEASONS
    SEASONS = tuple(s for s in keep if s != holdout)
    tmp = HERE.parent / ".cache" / "corr-validate.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    try:
        build(tmp)
    finally:
        SEASONS = keep
    table = load(tmp)
    SEASONS_HOLD = (holdout,)
    import polars as pl  # noqa: PLC0415

    sys.path.insert(0, str(HERE.parent))
    from espncli.value import player_sd  # noqa: PLC0415
    from ffmodel import nflraw  # noqa: PLC0415

    proj = nflraw.sleeper_weeks(list(SEASONS_HOLD))
    off = nflraw.player_weeks(list(SEASONS_HOLD)).join(
        proj.filter(pl.col("gsis_id").is_not_null()).select(["season", "week", "gsis_id", "proj"]),
        left_on=["season", "week", "player_id"], right_on=["season", "week", "gsis_id"], how="inner")
    dst = nflraw.dst_weeks(list(SEASONS_HOLD)).join(
        proj.filter(pl.col("pos") == "D/ST").select(["season", "week", "team", "proj"]),
        on=["season", "week", "team"], how="inner")
    cols = ["week", "team", "opp", "pos", "proj", "pts"]
    rows = pl.concat([off.select(cols), dst.select(cols)], how="diagonal_relaxed").filter(
        pl.col("proj") >= pl.col("pos").replace_strict(MIN_PROJ, default=0.0)).to_dicts()
    for r in rows:
        r["sd"] = player_sd(r["pos"], r["proj"]) or 1.5
    rng = np.random.default_rng(seed)
    by_week: dict[int, dict[str, list[dict]]] = {}
    for r in rows:
        by_week.setdefault(r["week"], {}).setdefault(r["pos"], []).append(r)

    def lineup(pool: dict[str, list[dict]], used: set[int], forced: list[dict]) -> list[dict] | None:
        need = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "D/ST": 1}
        out = list(forced)
        for f in forced:
            need[f["pos"]] -= 1
            used.add(id(f))
        for pos, n in need.items():
            cands = [p for p in pool.get(pos, []) if id(p) not in used]
            if len(cands) < n:
                return None
            for k in rng.choice(len(cands), size=n, replace=False) if n else []:
                out.append(cands[int(k)])
                used.add(id(cands[int(k)]))
        flex = [p for pos in ("RB", "WR", "TE") for p in pool.get(pos, []) if id(p) not in used]
        pick = flex[int(rng.integers(len(flex)))]
        used.add(id(pick))
        return [*out, pick]

    def sd_of(a: list[dict], b: list[dict], tab: dict[str, float]) -> float:
        var = sum(p["sd"] ** 2 for p in a + b)
        for side in (a, b):
            for i in range(len(side)):
                for j in range(i + 1, len(side)):
                    var += 2 * rho(side[i], side[j], tab) * side[i]["sd"] * side[j]["sd"]
        var -= 2 * sum(rho(x, y, tab) * x["sd"] * y["sd"] for x in a for y in b)
        return float(np.sqrt(max(var, 1e-9)))

    def stressed(pool: dict[str, list[dict]], used: set[int]) -> tuple[list[dict], list[dict]] | None:
        qbs = [q for q in pool.get("QB", [])]
        rng.shuffle(qbs)
        sides = []
        for q in qbs:
            wr1 = [w for w in pool.get("WR", []) if w["team"] == q["team"] and id(w) not in used]
            if not wr1:
                continue
            sides.append((q, max(wr1, key=lambda w: w["proj"])))
            if len(sides) == 2:
                break
        if len(sides) < 2:
            return None
        (qa, wa), (qb, wb) = sides
        da = [d for d in pool.get("D/ST", []) if d["opp"] == qb["team"]]
        db = [d for d in pool.get("D/ST", []) if d["opp"] == qa["team"]]
        if not da or not db or da[0] is db[0]:
            return None
        a = lineup(pool, used, [qa, wa, da[0]])
        b = lineup(pool, used, [qb, wb, db[0]])
        return (a, b) if a and b else None

    out = {}
    for kind in ("random", "stressed"):
        z_ind, z_cor = [], []
        weeks = sorted(by_week)
        for _ in range(sims):
            pool = by_week[weeks[int(rng.integers(len(weeks)))]]
            used: set[int] = set()
            if kind == "random":
                a, b = lineup(pool, used, []), lineup(pool, used, [])
                pair = (a, b) if a and b else None
            else:
                pair = stressed(pool, used)
            if not pair:
                continue
            a, b = pair
            d = sum(p["pts"] for p in a) - sum(p["pts"] for p in b)
            m = sum(p["proj"] for p in a) - sum(p["proj"] for p in b)
            z_ind.append((d - m) / sd_of(a, b, {}))
            z_cor.append((d - m) / sd_of(a, b, table))
        zi, zc = np.asarray(z_ind), np.asarray(z_cor)
        out[kind] = {"n": len(zi), "var_z_independent": round(float(zi.var()), 3),
                     "var_z_correlated": round(float(zc.var()), 3),
                     "cover90_independent": round(float(np.mean(np.abs(zi) <= 1.645)), 3),
                     "cover90_correlated": round(float(np.mean(np.abs(zc) <= 1.645)), 3)}
    return {"holdout": holdout, "fit_seasons": [s for s in SEASONS if s != holdout], **out}


if __name__ == "__main__":
    if sys.argv[1:2] == ["validate"]:
        print(json.dumps(validate(), indent=1))
        sys.exit(0)
    t = build()
    print(f"corr: {len(t['pairs'])} categories from {t['player_weeks']} player-weeks -> {TABLE}")
    for k, v in sorted(t["pairs"].items(), key=lambda kv: -abs(kv[1]["rho"]))[:30]:
        print(f"  {k:22} rho {v['rho']:+.3f}  n {v['n']:6d}  ci {v['ci95']}  seasons {v['by_season']}")
