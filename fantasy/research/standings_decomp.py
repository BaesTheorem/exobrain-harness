#!/usr/bin/env python3
"""Where fantasy standings come from, measured on real Sleeper redraft leagues.

Reads the league files that sleeper_crawl.py wrote (default /tmp/ffvoi) and
splits each team's regular season into four parts, all in points per week:

  PF        actual points for (sum of matchup points)
  OPT_A     each week's best legal lineup from the players on the roster that
            week (matchup `players` with `players_points`), summed
  LINEUP    OPT_A - PF, points left on the bench (>= 0)
  OPT_D     each week's best legal lineup from the drafted players only, held
            all season, scored with the league's own scoring_settings
  ACQ       OPT_A - OPT_D, net value of every add, drop and trade
  LUCK      actual wins - all-play expected wins (wins per season)

so that PF = OPT_D + ACQ - LINEUP exactly. Point parts are demeaned within
each league-season. Then it measures (1) the variance shares of PF, (2) how
much of the win variance PF and LUCK explain, (3) the leverage of each part on
bye, playoff and title odds (logistic regression), (4) whether each part
persists for the same Sleeper user across leagues (skill) or not (luck),
(5) acquisitions by type and week, and (6) how lineup losses are made.

ACQ is split exactly (two-way Shapley terms against the drafted players still
on the roster) into waiver/free-agent gains, trade gains, losses from dropped
drafted players and losses from drafted players traded away. LINEUP is split
into the dead-slot loss (empty slot, or a starter who did not play, refilled
from that week's bench with the other starters fixed) and the choice loss
(the rest). Draft rosters are matched to league rosters by week-1 overlap; a
league is dropped when the roster slots on file do not match the lineups
played, or when under 70% of drafted players are on their roster in week 1.

Scoring of a drafted player in a week he was on no roster uses the weekly
all-player box score (/stats/nfl/regular/<season>/<week>) times the league's
scoring_settings; when he was on any roster in that league that week, the
league's own players_points are used. Positions come from the Sleeper player
table (fantasy_positions), which is current, not as of the season.

Output: research/out/standings_decomp.json (aggregates only, no user ids,
league ids, names or usernames).

    python3 standings_decomp.py [--raw /tmp/ffvoi] [--boot 1000] [--max-leagues N]

INVARIANTS
- PF = OPT_D + ACQ - LINEUP for every team-season, within 1e-6.
- OPT_A >= PF for every team-week (checked; violations are counted and
  reported, never clipped).
- The greedy optimizer is used only where it is exact (single-position
  players, nested flex slots); everything else goes to linear_sum_assignment,
  and a random sample is cross-checked against it.
- Bootstrap resamples whole leagues (or whole users for persistence), never
  team-seasons.
- The output file holds aggregates only.
"""

import argparse
import collections
import gzip
import json
import math
import pathlib
import random
import time

import numpy as np
from scipy.optimize import linear_sum_assignment

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out" / "standings_decomp.json"

BASE = {"QB": 1, "RB": 2, "WR": 4, "TE": 8, "K": 16, "DEF": 32}
SLOTMASK = dict(BASE, FLEX=2 | 4 | 8, SUPER_FLEX=1 | 2 | 4 | 8,
                REC_FLEX=4 | 8, WRRB_FLEX=2 | 4)
SINGLE = frozenset(BASE.values())
WIRE = {"waiver", "free_agent"}
BUCKETS = ((1, 4), (5, 9), (10, 14))
WAIVER_NAME = {0: "rolling", 1: "reverse_standings", 2: "faab"}


def load_gz(path):
    with gzip.open(path, "rt") as f:
        return json.load(f)


def popcount(x):
    return bin(x).count("1")


# ---------------------------------------------------------------- optimizer

class Plan:
    """Starting slots of a league, prepared for the lineup optimizer."""

    def __init__(self, slots):
        self.slots = list(slots)
        self.masks = [SLOTMASK[s] for s in self.slots]
        self.ded = collections.Counter(SLOTMASK[s] for s in self.slots if s in BASE)
        self.flex = sorted((SLOTMASK[s] for s in self.slots if s not in BASE), key=popcount)
        self.chain = all((self.flex[i] & ~self.flex[i + 1]) == 0
                         for i in range(len(self.flex) - 1))


def best_lsa(pool, plan):
    """Exact best lineup by assignment. pool: list of (points, posmask)."""
    s = len(plan.masks)
    if not pool:
        return 0.0
    pts = np.array([p for p, _ in pool], dtype=float)
    pm = np.array([m for _, m in pool], dtype=np.int64)
    sm = np.array(plan.masks, dtype=np.int64)
    gain = np.where(((sm[:, None] & pm[None, :]) != 0) & (pts[None, :] > 0), pts[None, :], 0.0)
    if gain.shape[1] < s:
        gain = np.hstack([gain, np.zeros((s, s - gain.shape[1]))])
    r, c = linear_sum_assignment(-gain)
    return float(gain[r, c].sum())


def best_greedy(pool, plan):
    """Exact when every player has one position and flex slots are nested."""
    by = collections.defaultdict(list)
    for p, m in pool:
        if p > 0:
            by[m].append(p)
    total = 0.0
    rest = []
    for m, lst in by.items():
        lst.sort(reverse=True)
        k = plan.ded.get(m, 0)
        total += sum(lst[:k])
        rest.extend((p, m) for p in lst[k:])
    if plan.flex and rest:
        rest.sort(reverse=True)
        used = [False] * len(rest)
        for fm in plan.flex:
            for i, (p, m) in enumerate(rest):
                if not used[i] and (m & fm):
                    used[i] = True
                    total += p
                    break
    return total


def best(pool, plan):
    pool = [(p, m) for p, m in pool if m]
    if plan.chain and all(m in SINGLE for _, m in pool):
        return best_greedy(pool, plan)
    return best_lsa(pool, plan)


def optimizer_control():
    """Hand-built week with a known answer, and the same week through both paths."""
    plan = Plan(["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"])
    pool = [(20, 1), (15, 2), (10, 2), (8, 2), (12, 4), (11, 4), (9, 4), (7, 8),
            (3, 8), (5, 16), (4, 32), (-2, 32)]
    want = 20 + 15 + 10 + 12 + 11 + 7 + 9 + 5 + 4
    got_g, got_l = best_greedy(pool, plan), best_lsa(pool, plan)
    # two flex slots that are not nested: filling WRRB_FLEX first with the WR
    # would leave the TE for REC_FLEX (11); the right answer puts the WR in
    # REC_FLEX and the RB in WRRB_FLEX (19)
    sf = Plan(["REC_FLEX", "WRRB_FLEX"])
    pool2 = [(10, 4), (9, 2), (1, 8)]
    want2 = 19
    got2 = best(pool2, sf)
    return {"case1_expected": want, "case1_greedy": got_g, "case1_lsa": got_l,
            "case2_expected": want2, "case2_best": got2, "case2_nested": sf.chain,
            "ok": got_g == want == got_l and got2 == want2 and not sf.chain}


def load_posmask(raw):
    cache = raw / "posmask.json"
    if cache.exists():
        return json.loads(cache.read_text())
    players = load_gz(raw / "players_nfl.json.gz")
    out = {}
    for pid, p in players.items():
        pos = p.get("fantasy_positions") or ([p["position"]] if p.get("position") else [])
        m = 0
        for x in pos:
            m |= BASE.get(x, 0)
        out[pid] = m
    cache.write_text(json.dumps(out))
    return out


class Stats:
    """Weekly all-player box scores as dense matrices, one per season-week."""

    def __init__(self, raw):
        data, keys = {}, set()
        for p in sorted((raw / "stats").glob("*.json.gz")):
            season, wk = (int(x) for x in p.name.split(".")[0].split("_"))
            d = load_gz(p)
            data[(season, wk)] = d
            for v in d.values():
                keys |= {k for k, x in v.items() if isinstance(x, (int, float))}
        keys.add("xpmiss")
        self.keys = sorted(keys)
        kidx = {k: i for i, k in enumerate(self.keys)}
        self.weeks = {}
        for sw, d in data.items():
            pids = list(d)
            M = np.zeros((len(pids), len(self.keys)), dtype=np.float64)
            played = set()
            for i, pid in enumerate(pids):
                v = d[pid]
                for k, x in v.items():
                    if isinstance(x, (int, float)):
                        M[i, kidx[k]] = x
                if "xpmiss" not in v and "xpa" in v:
                    M[i, kidx["xpmiss"]] = (v.get("xpa") or 0) - (v.get("xpm") or 0)
                if (v.get("gp") or 0) > 0 or any((v.get(s) or 0) > 0 for s in ("off_snp", "def_snp", "st_snp")):
                    played.add(pid)
            self.weeks[sw] = ({pid: i for i, pid in enumerate(pids)}, M, played)
        del data

    def points(self, season, week, scoring):
        idx, M, played = self.weeks[(season, week)]
        vec = np.array([float(scoring.get(k) or 0.0) for k in self.keys])
        pts = M @ vec
        return {pid: float(pts[i]) for pid, i in idx.items()}, played


# ---------------------------------------------------------------- one league

def bracket_outcomes(wb):
    if not wb:
        return None
    r1 = {t for m in wb if m.get("r") == 1 for t in (m.get("t1"), m.get("t2")) if isinstance(t, int)}
    r2 = {t for m in wb if m.get("r") == 2 for t in (m.get("t1"), m.get("t2")) if isinstance(t, int)}
    field = {t for m in wb for t in (m.get("t1"), m.get("t2")) if isinstance(t, int)}
    final = [m for m in wb if m.get("p") == 1]
    if not final:
        last = max(m.get("r", 0) for m in wb)
        final = [m for m in wb if m.get("r") == last and m.get("p") in (None, 1)]
    champ = final[0].get("w") if final else None
    return {"field": field, "byes": r2 - r1, "champ": champ}


def process_league(d, li, pos, stats, ctl):
    lg = d["league"]
    st = lg["settings"]
    season = int(lg["season"])
    n = lg["total_rosters"]
    W = st["playoff_week_start"] - 1
    slots = [s for s in lg["roster_positions"] if s != "BN"]
    plan = Plan(slots)
    plans = {}
    sc = lg["scoring_settings"]
    owner = {r["roster_id"]: r.get("owner_id") for r in d["rosters"]}
    wpos = {r["roster_id"]: (r.get("settings") or {}).get("waiver_position") for r in d["rosters"]}
    # Roster settings read now must match the lineups played then.
    if any(len(m.get("starters") or []) != len(slots) for ms in d["matchups"].values() for m in ms):
        ctl["dropped_slot_mismatch"] += 1
        return None, None
    picked = collections.defaultdict(list)
    for p in d["picks"] or []:
        if p.get("player_id"):
            picked[p["roster_id"]].append(str(p["player_id"]))
    # Map draft rosters to league rosters by week-1 overlap. Commissioners
    # sometimes reassign teams after the draft; ties keep the identity.
    wk1 = {m["roster_id"]: {str(x) for x in m.get("players") or []} for m in d["matchups"]["1"]}
    rids, drs = sorted(owner), sorted(picked)
    ov = np.array([[len(set(picked[a]) & wk1.get(b, set())) + 0.5 * (a == b) for b in rids] for a in drs])
    r_i, c_i = linear_sum_assignment(-ov)
    mapping = {drs[i]: rids[j] for i, j in zip(r_i, c_i, strict=True)}
    drafted = collections.defaultdict(list)
    for a, v in picked.items():
        drafted[mapping.get(a, a)] = v
    kept = sum(len(set(drafted[r]) & wk1.get(r, set())) for r in rids)
    if kept < 0.7 * max(1, sum(len(v) for v in drafted.values())):
        ctl["dropped_draft_mismatch"] += 1
        return None, None
    if any(a != b for a, b in mapping.items()):
        ctl["draft_remapped_leagues"] += 1

    # transactions -> provenance of each add and each departure
    adds = collections.defaultdict(list)     # (rid, pid) -> [(leg, ts, kind)]
    leaves = collections.defaultdict(list)   # (rid, pid) -> [(leg, ts, kind)]
    n_adds = collections.Counter()
    n_fa = collections.Counter()
    n_adds_b = collections.Counter()
    rem_b = collections.Counter()   # regular-season weeks left after each wire add, by bucket
    n_trades = collections.Counter()
    for wk, txs in d["transactions"].items():
        for t in txs or []:
            if t.get("status") != "complete":
                continue
            kind = "wire" if t.get("type") in WIRE else ("trade" if t.get("type") == "trade" else "other")
            leg = int(t.get("leg") or wk)
            ts = t.get("status_updated") or t.get("created") or 0
            for pid, rid in (t.get("adds") or {}).items():
                adds[(rid, pid)].append((leg, ts, kind))
                if kind == "wire":
                    n_adds[rid] += 1
                    n_fa[rid] += t.get("type") == "free_agent"  # no claim priority needed
                    b = next((i for i, (lo, hi) in enumerate(BUCKETS) if lo <= leg <= hi), 2)
                    n_adds_b[(rid, b)] += 1
                    rem_b[(rid, b)] += max(0, W - leg + 1)
            for pid, rid in (t.get("drops") or {}).items():
                leaves[(rid, pid)].append((leg, ts, kind))
            if kind == "trade":
                for rid in t.get("roster_ids") or []:
                    n_trades[rid] += 1
    for v in adds.values():
        v.sort()
    for v in leaves.values():
        v.sort()

    def provenance(rid, pid, wk, is_drafted):
        ev = [e for e in adds.get((rid, pid), ()) if e[0] <= wk]
        if ev:
            return ev[-1][2], ev[-1][0]
        return ("draft", 0) if is_drafted else ("unknown", 0)

    def departure(rid, pid, wk):
        ev = [e for e in leaves.get((rid, pid), ()) if e[0] <= wk]
        return ev[-1][2] if ev else "unknown"

    T = {rid: collections.defaultdict(float) for rid in owner}
    weekly_rows = []
    for wk in range(1, W + 1):
        ms = d["matchups"][str(wk)]
        comp, played = stats.points(season, wk, sc)
        # negative control: the same check with half a point less per catch must fail
        comp_bad, _ = stats.points(season, wk, dict(sc, rec=float(sc.get("rec") or 0) - 0.5))
        official = {}
        for m in ms:
            official.update(m.get("players_points") or {})
        # scoring control: our box-score scoring vs the league's own points
        for pid, p in official.items():
            if pid in comp:
                ctl["score_n"] += 1
                ctl["score_ok"] += abs(comp[pid] - p) < 0.05
                ctl["score_absdiff"] += abs(comp[pid] - p)
                ctl["score_bad_ok"] += abs(comp_bad[pid] - p) < 0.05
        def pts_of(pid, official=official, comp=comp):
            return official[pid] if pid in official else comp.get(pid, 0.0)
        scores = {m["roster_id"]: m["points"] for m in ms}
        games = collections.defaultdict(list)
        for m in ms:
            if m.get("matchup_id") is not None:
                games[m["matchup_id"]].append(m["roster_id"])
        for m in ms:
            rid = m["roster_id"]
            t = T[rid]
            players = [str(x) for x in m.get("players") or []]
            pset = set(players)
            pf = float(m["points"])
            pool = [(official.get(pid, 0.0), pos.get(pid, 0)) for pid in players]
            opt_a = best(pool, plan)
            dset = drafted[rid]
            opt_d = best([(pts_of(pid), pos.get(pid, 0)) for pid in dset], plan)
            if opt_a < pf - 1e-6:
                ctl["opt_below_pf"] += 1
            ctl["team_weeks"] += 1
            starters = [str(x) for x in m.get("starters") or []]
            if abs(opt_a - pf) < 1e-6:
                ctl["perfect_weeks"] += 1
            # slot eligibility of the actual starters under our position map
            for s, pid in zip(slots, starters, strict=False):
                if pid not in ("0", "None"):
                    ctl["starter_n"] += 1
                    ctl["starter_inelig"] += (pos.get(pid, 0) & SLOTMASK[s]) == 0
            # acquisition split (Shapley over wire vs trade, drops vs trades away)
            K, Wg, Tg = [], [], []
            for pid in players:
                kind, leg = provenance(rid, pid, wk, pid in dset)
                item = (official.get(pid, 0.0), pos.get(pid, 0))
                if kind == "draft" or (pid in dset and kind == "unknown"):
                    K.append(item)
                elif kind == "trade":
                    Tg.append(item)
                else:
                    Wg.append(item)
                if pid in starters:
                    b = next((i for i, (a, z) in enumerate(BUCKETS) if a <= leg <= z), None)
                    key = kind if b is None else f"{kind}_b{b}"
                    t["start_" + key] += official.get(pid, 0.0)
                    ctl["prov_" + kind] += 1
            Dd, Dt = [], []
            for pid in dset:
                if pid in pset:
                    continue
                item = (pts_of(pid), pos.get(pid, 0))
                (Dt if departure(rid, pid, wk) == "trade" else Dd).append(item)
            oK = best(K, plan)
            oKW, oKT = best(K + Wg, plan), best(K + Tg, plan)
            oKDd, oKDt = best(K + Dd, plan), best(K + Dt, plan)
            t["gain_wire"] += 0.5 * ((oKW - oK) + (opt_a - oKT))
            t["gain_trade"] += 0.5 * ((oKT - oK) + (opt_a - oKW))
            t["loss_dropped"] += 0.5 * ((oKDd - oK) + (opt_d - oKDt))
            t["loss_tradedaway"] += 0.5 * ((oKDt - oK) + (opt_d - oKDd))
            # lineup loss: refill dead slots (empty or non-playing starter) from the bench first
            dead = [i for i, pid in enumerate(starters)
                    if pid in ("0", "None") or (official.get(pid, 0.0) == 0 and pid not in played)]
            for i in dead:
                pid = starters[i]
                if pid in ("0", "None"):
                    ctl["dead_empty_slot"] += 1
                else:
                    ctl["dead_pos_" + next((k for k, v in BASE.items() if pos.get(pid, 0) & v), "unknown")] += 1
                    ctl["dead_absent_from_box_score"] += pid not in comp
            g1 = 0.0
            if dead:
                key = tuple(slots[i] for i in dead)
                if key not in plans:
                    plans[key] = Plan(key)
                sset = set(starters)
                sub = [(official.get(pid, 0.0), pos.get(pid, 0)) for pid in players if pid not in sset]
                sub += [(official.get(starters[i], 0.0), pos.get(starters[i], 0)) for i in dead
                        if starters[i] not in ("0", "None")]
                deadpts = sum(official.get(starters[i], 0.0) for i in dead if starters[i] not in ("0", "None"))
                g1 = max(0.0, best(sub, plans[key]) - deadpts)
            lineup = opt_a - pf
            g1 = min(g1, lineup)
            # random cross-check of greedy against assignment
            if ctl["rng"].random() < 0.02:
                ctl["xcheck_n"] += 1
                if abs(best_lsa([q for q in pool if q[1]], plan) - opt_a) > 1e-6:
                    ctl["xcheck_bad"] += 1
            # wins and all-play
            opp = None
            for g in games.values():
                if rid in g and len(g) == 2:
                    opp = g[0] if g[1] == rid else g[1]
            if opp is not None:
                t["games"] += 1
                t["wins"] += 1.0 if pf > scores[opp] else (0.5 if pf == scores[opp] else 0.0)
                others = [scores[x] for x in scores if x != rid]
                t["apw"] += (sum(pf > s for s in others) + 0.5 * sum(pf == s for s in others)) / len(others)
            t["pf"] += pf
            t["opt_a"] += opt_a
            t["opt_d"] += opt_d
            t["lineup_dead"] += g1
            t["lineup_choice"] += lineup - g1
            weekly_rows.append((li, rid, wk, lineup, g1, len(dead)))

    bo = bracket_outcomes(d.get("winners_bracket"))
    order = sorted(owner, key=lambda r: (-T[r]["wins"], -T[r]["pf"]))
    seed = {r: i + 1 for i, r in enumerate(order)}
    rows = []
    pt = st.get("playoff_teams") or 0
    for rid in owner:
        t = T[rid]
        row = {"league": li, "season": season, "teams": n, "weeks": W,
               "waiver_type": st.get("waiver_type"), "playoff_teams": pt,
               "superflex": "SUPER_FLEX" in slots, "owner": owner[rid],
               "n_adds": n_adds[rid], "n_fa_adds": n_fa[rid], "n_trades": n_trades[rid],
               "n_adds_b0": n_adds_b[(rid, 0)], "n_adds_b1": n_adds_b[(rid, 1)],
               "n_adds_b2": n_adds_b[(rid, 2)],
               "rem_b0": rem_b[(rid, 0)], "rem_b1": rem_b[(rid, 1)], "rem_b2": rem_b[(rid, 2)],
               "waiver_position": wpos.get(rid),
               "seed": seed[rid], "games": t["games"], "wins": t["wins"], "apw": t["apw"]}
        for k, v in t.items():
            if k not in ("games", "wins", "apw"):
                row[k] = v / W
        row["acq"] = row["opt_a"] - row["opt_d"]
        row["lineup"] = row["opt_a"] - row["pf"]
        row["luck"] = t["wins"] - t["apw"]
        if bo:
            row["playoffs"] = int(rid in bo["field"])
            row["bye"] = int(rid in bo["byes"])
            row["champ"] = int(rid == bo["champ"])
            row["n_byes"] = len(bo["byes"])
            row["n_field"] = len(bo["field"])
        rows.append(row)
    if bo:
        comp_field = {r for r in owner if seed[r] <= len(bo["field"])}
        ctl["seed_field_match"] += comp_field == bo["field"]
        comp_byes = {r for r in owner if seed[r] <= len(bo["byes"])}
        ctl["seed_bye_match"] += comp_byes == bo["byes"]
        ctl["seed_checked"] += 1
    return rows, weekly_rows


# ---------------------------------------------------------------- statistics

def boot_weights(groups, B, rng):
    """Multinomial resampling of whole groups. Returns (B, n_groups) weights."""
    G = len(groups)
    return rng.multinomial(G, np.full(G, 1.0 / G), size=B).astype(float)


def ci(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return [None, None]
    return [round(float(np.percentile(x, 2.5)), 4), round(float(np.percentile(x, 97.5)), 4)]


def demean(rows, key):
    by = collections.defaultdict(list)
    for r in rows:
        by[r["league"]].append(r[key])
    mu = {k: sum(v) / len(v) for k, v in by.items()}
    return np.array([r[key] - mu[r["league"]] for r in rows])


def r2_from_moments(M, S, y):
    """R-squared of column y on columns S from a second-moment matrix of demeaned data."""
    if not S:
        return 0.0
    S = list(S)
    c = M[S, y]
    return float(c @ np.linalg.solve(M[np.ix_(S, S)], c) / M[y, y])


def pf_split(M):
    """Variance shares, sequential and Shapley R-squared of PF (col 3) on D, A, L (cols 0-2)."""
    v = M[3, 3]
    out = {"draft": M[0, 0] / v, "acq": M[1, 1] / v, "lineup": M[2, 2] / v,
           "2cov_draft_acq": 2 * M[0, 1] / v, "-2cov_draft_lineup": -2 * M[0, 2] / v,
           "-2cov_acq_lineup": -2 * M[1, 2] / v,
           "corr_draft_acq": M[0, 1] / math.sqrt(M[0, 0] * M[1, 1]),
           "corr_draft_lineup": M[0, 2] / math.sqrt(M[0, 0] * M[2, 2]),
           "corr_acq_lineup": M[1, 2] / math.sqrt(M[1, 1] * M[2, 2])}
    r2 = {}
    for k in range(8):
        S = tuple(i for i in range(3) if k >> i & 1)
        r2[S] = r2_from_moments(M, S, 3)
    out["seq_r2_draft"] = r2[(0,)]
    out["seq_r2_add_acq"] = r2[(0, 1)] - r2[(0,)]
    out["seq_r2_add_lineup"] = 1 - r2[(0, 1)]
    out["r2_draft_alone"] = r2[(0,)]
    out["r2_acq_alone"] = r2[(1,)]
    out["r2_lineup_alone"] = r2[(2,)]
    for i, name in enumerate(("draft", "acq", "lineup")):
        others = [j for j in range(3) if j != i]
        tot = 0.0
        for k in range(4):
            S = tuple(o for b, o in enumerate(others) if k >> b & 1)
            wgt = math.factorial(len(S)) * math.factorial(2 - len(S)) / 6
            tot += wgt * (r2[tuple(sorted(S + (i,)))] - r2[S])
        out["shapley_" + name] = tot
    return out


def variance_shares(D, A, L, PF, lg_idx, Wb):
    """Decompose var(PF) for PF = D + A - L. Point estimate plus bootstrap over leagues."""
    Z = np.c_[D, A, L, PF]
    nL = Wb.shape[1]
    S = np.zeros((nL, 4, 4))
    np.add.at(S, lg_idx, Z[:, :, None] * Z[:, None, :])
    est = pf_split(S.sum(0))
    boots = [pf_split(np.tensordot(Wb[b], S, axes=1)) for b in range(Wb.shape[0])]
    out: dict = {k: {"est": round(float(v), 4), "ci95": ci([bb[k] for bb in boots])} for k, v in est.items()}
    out["check_sum_of_shares"] = round(float(sum(est[k] for k in ("draft", "acq", "lineup", "2cov_draft_acq",
                                                                   "-2cov_draft_lineup", "-2cov_acq_lineup"))), 6)
    out["sd_points_per_week"] = {k: round(float(np.sqrt((v * v).mean())), 3)
                                 for k, v in (("pf", PF), ("draft", D), ("acq", A), ("lineup", L))}
    return out


def wls(X, y, w):
    Xw = X * w[:, None]
    beta = np.linalg.lstsq(Xw.T @ X, Xw.T @ y, rcond=None)[0]
    res = y - X @ beta
    ybar = (w * y).sum() / w.sum()
    r2 = 1 - (w * res ** 2).sum() / (w * (y - ybar) ** 2).sum()
    return beta, r2


def logit_fit(X, y, w, iters=50):
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        eta = np.clip(X @ beta, -30, 30)
        p = 1 / (1 + np.exp(-eta))
        g = X.T @ (w * (y - p))
        H = (X * (w * p * (1 - p))[:, None]).T @ X + 1e-8 * np.eye(X.shape[1])
        step = np.linalg.solve(H, g)
        beta += step
        if np.abs(step).max() < 1e-9:
            break
    return beta


def pct(x):
    return round(100 * float(x), 2)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="/tmp/ffvoi")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--boot-logit", type=int, default=300)
    ap.add_argument("--max-leagues", type=int, default=0)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    t0 = time.time()
    raw = pathlib.Path(a.raw)
    rng = np.random.default_rng(20261015)
    ctl = collections.Counter()
    ctl_rng = random.Random(7)

    oc = optimizer_control()
    pos = load_posmask(raw)
    stats = Stats(raw)
    files = sorted((raw / "leagues").glob("*.json.gz"))
    if a.max_leagues:
        files = files[: a.max_leagues]
    rows, weekly = [], []
    ctl_obj = collections.defaultdict(int)
    ctl_obj["rng"] = ctl_rng  # type: ignore[assignment]
    league_meta = []
    for li, f in enumerate(files):
        d = load_gz(f)
        r, w = process_league(d, li, pos, stats, ctl_obj)
        if r is None:
            continue
        li_used = len(league_meta)
        for x in r:
            x["league"] = li_used
        w = [(li_used,) + tuple(z[1:]) for z in w]
        rows.extend(r)
        weekly.extend(w)
        n_tx = sum(len(v or []) for v in d["transactions"].values())
        league_meta.append({"season": int(d["league"]["season"]), "teams": d["league"]["total_rosters"],
                            "waiver_type": d["league"]["settings"].get("waiver_type"),
                            "weeks": d["league"]["settings"]["playoff_week_start"] - 1,
                            "superflex": "SUPER_FLEX" in d["league"]["roster_positions"],
                            "n_tx": n_tx})
    ctl.update({k: v for k, v in ctl_obj.items() if k != "rng"})
    nL = len(league_meta)
    print(f"processed {nL} leagues, {len(rows)} team-seasons in {time.time() - t0:.0f}s", flush=True)

    # exact identity
    ident = max(abs(r["pf"] - (r["opt_d"] + r["acq"] - r["lineup"])) for r in rows)

    lg_idx = np.array([r["league"] for r in rows])
    D, A, Lp, PF = (demean(rows, k) for k in ("opt_d", "acq", "lineup", "pf"))
    LUCK = np.array([r["luck"] for r in rows])
    WINS = demean(rows, "wins")
    APW = demean(rows, "apw")
    Wb = boot_weights(range(nL), a.boot, rng)

    res = {"generated": time.strftime("%Y-%m-%d %H:%M"),
           "controls": {}, "sample": {}, "variance_pf": {}, "wins": {}, "leverage": {},
           "persistence": {}, "acquisitions": {}, "lineup": {}}

    # ------------------------------------------------ sample
    by_size = collections.Counter(m["teams"] for m in league_meta)
    by_wt = collections.Counter(WAIVER_NAME.get(m["waiver_type"], str(m["waiver_type"])) for m in league_meta)
    by_season = collections.Counter(m["season"] for m in league_meta)
    by_weeks = collections.Counter(m["weeks"] for m in league_meta)
    res["sample"] = {"league_seasons": nL, "team_seasons": len(rows),
                     "by_teams": dict(sorted(by_size.items())), "by_waiver_type": dict(by_wt),
                     "by_season": dict(sorted(by_season.items())), "by_regular_weeks": dict(sorted(by_weeks.items())),
                     "teams_by_waiver_type": {f"{t}_{WAIVER_NAME.get(w, w)}": c for (t, w), c in sorted(
                         collections.Counter((m["teams"], m["waiver_type"]) for m in league_meta).items())},
                     "superflex_leagues": len({r["league"] for r in rows if r["superflex"]}),
                     "leagues_under_20_transactions": sum(m["n_tx"] < 20 for m in league_meta),
                     "distinct_users": len({r["owner"] for r in rows if r["owner"]})}
    # waiver-type label check: final waiver position against wins
    wcheck = collections.defaultdict(list)
    for li in range(nL):
        rr = [r for r in rows if r["league"] == li and r["waiver_position"] is not None]
        if len(rr) < 4:
            continue
        x = np.argsort(np.argsort([r["wins"] + 1e-6 * r["pf"] for r in rr]))
        y = np.argsort(np.argsort([r["waiver_position"] for r in rr]))
        wcheck[WAIVER_NAME.get(rr[0]["waiver_type"], "?")].append(float(np.corrcoef(x, y)[0, 1]))
    res["controls"]["waiver_position_vs_wins_spearman"] = {k: round(float(np.nanmean(v)), 3) for k, v in wcheck.items()}

    # ------------------------------------------------ controls
    res["controls"].update({
        "optimizer_hand_cases": oc,
        "identity_max_abs_error": ident,
        "team_weeks": ctl["team_weeks"],
        "opt_below_pf_team_weeks": ctl["opt_below_pf"],
        "perfect_lineup_share": round(ctl["perfect_weeks"] / max(1, ctl["team_weeks"]), 4),
        "greedy_vs_lsa_checked": ctl["xcheck_n"], "greedy_vs_lsa_mismatch": ctl["xcheck_bad"],
        "scoring_player_weeks": ctl["score_n"],
        "scoring_match_share_0.05": round(ctl["score_ok"] / max(1, ctl["score_n"]), 4),
        "scoring_mean_abs_diff": round(ctl["score_absdiff"] / max(1, ctl["score_n"]), 4),
        "scoring_negative_control_match_share_rec_minus_half": round(ctl["score_bad_ok"] / max(1, ctl["score_n"]), 4),
        "dead_starters": {k: v for k, v in ctl.items() if k.startswith("dead_")},
        "starter_slot_ineligible_share": round(ctl["starter_inelig"] / max(1, ctl["starter_n"]), 5),
        "starter_provenance_counts": {k[5:]: v for k, v in ctl.items() if k.startswith("prov_")},
        "seed_rule_matches_bracket_field": f"{ctl['seed_field_match']}/{ctl['seed_checked']}",
        "seed_rule_matches_bracket_byes": f"{ctl['seed_bye_match']}/{ctl['seed_checked']}",
        "draft_remapped_leagues": ctl["draft_remapped_leagues"],
        "dropped_draft_mismatch_leagues": ctl["dropped_draft_mismatch"],
        "dropped_slot_mismatch_leagues": ctl["dropped_slot_mismatch"],
    })

    # ------------------------------------------------ 1. variance of PF per week
    res["variance_pf"]["all"] = variance_shares(D, A, Lp, PF, lg_idx, Wb)
    subsets = {
        "faab": lambda m: m["waiver_type"] == 2,
        "non_faab": lambda m: m["waiver_type"] in (0, 1),
        "reverse_standings": lambda m: m["waiver_type"] == 1,
        "teams_12_to_14": lambda m: m["teams"] >= 12,
        "active_leagues_20plus_tx": lambda m: m["n_tx"] >= 20,
        "one_qb": lambda m: not m["superflex"],
        "one_qb_non_faab_12_to_14": lambda m: not m["superflex"] and m["waiver_type"] in (0, 1) and m["teams"] >= 12,
    }
    sub_masks = {}
    for name, fn in subsets.items():
        keep_l = np.array([fn(m) for m in league_meta])
        if keep_l.sum() < 20:
            continue
        mask = keep_l[lg_idx]
        sub_masks[name] = mask
        remap = -np.ones(nL, dtype=int)
        remap[np.where(keep_l)[0]] = np.arange(keep_l.sum())
        Wsub = boot_weights(range(int(keep_l.sum())), a.boot, rng)
        res["variance_pf"][name] = variance_shares(D[mask], A[mask], Lp[mask], PF[mask], remap[lg_idx[mask]], Wsub)
        res["variance_pf"][name]["leagues"] = int(keep_l.sum())

    # ------------------------------------------------ 2. wins: PF versus LUCK
    def wins_block(mask, Wsub, gidx):
        out = {}
        y, pf, lk, ap = WINS[mask], PF[mask], LUCK[mask], APW[mask]
        one = np.ones(len(y))

        def stats_for(w):
            _, r2pf = wls(np.c_[one, pf], y, w)
            _, r2lk = wls(np.c_[one, lk], y, w)
            _, r2both = wls(np.c_[one, pf, lk], y, w)
            v = lambda z: (w * z * z).sum() / w.sum()  # noqa: E731
            c = lambda z1, z2: (w * z1 * z2).sum() / w.sum()  # noqa: E731
            vw = v(y)
            return [r2pf, r2lk, r2both,
                    0.5 * (r2pf + (r2both - r2lk)), 0.5 * (r2lk + (r2both - r2pf)),
                    v(ap) / vw, v(lk) / vw, 2 * c(ap, lk) / vw]
        names = ["r2_wins_on_pf", "r2_wins_on_luck", "r2_wins_on_pf_and_luck",
                 "shapley_pf", "shapley_luck", "var_share_allplay_wins", "var_share_luck",
                 "var_share_2cov_allplay_luck"]
        est = stats_for(np.ones(len(y)))
        bs = np.array([stats_for(Wsub[b][gidx]) for b in range(min(300, Wsub.shape[0]))])
        for i, nme in enumerate(names):
            out[nme] = {"est": round(float(est[i]), 4), "ci95": ci(bs[:, i])}
        out["sd_wins"] = round(float(np.sqrt((y * y).mean())), 3)
        out["sd_luck_wins"] = round(float(np.sqrt((lk * lk).mean())), 3)
        return out
    res["wins"]["all"] = wins_block(np.ones(len(rows), bool), Wb, lg_idx)

    # ------------------------------------------------ 3. outcome leverage
    fmt = [(r["teams"], r.get("n_field"), r.get("n_byes")) for r in rows]
    have_b = np.array(["playoffs" in r for r in rows])

    def leverage(outcome, mask, ref_fmt):
        idx = np.where(mask & have_b)[0]
        y = np.array([rows[i][outcome] for i in idx], dtype=float)
        fm = [fmt[i] for i in idx]
        levels = sorted(set(fm), key=lambda z: (-fm.count(z)))
        if ref_fmt not in levels:
            ref_fmt = levels[0]
        dummies = [lv for lv in levels if lv != ref_fmt]
        Z = np.array([[1.0 * (f == lv) for lv in dummies] for f in fm]).reshape(len(idx), len(dummies))
        Xc = np.c_[D[idx], A[idx], -Lp[idx], LUCK[idx]]  # lineup entered as points gained (-LINEUP)
        X = np.c_[np.ones(len(idx)), Xc, Z]
        g = lg_idx[idx]

        def fit(w):
            b = logit_fit(X, y, w)
            p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
            ame = [float((w * b[1 + k] * p * (1 - p)).sum() / w.sum()) for k in range(4)]
            # reference format, others at 0, component k at its 25th and 75th percentile
            ref = [np.percentile(Xc[:, k], [25, 75]) for k in range(4)]
            spread = []
            for k in range(4):
                lo = b[0] + b[1 + k] * ref[k][0]
                hi = b[0] + b[1 + k] * ref[k][1]
                spread += [1 / (1 + math.exp(-lo)), 1 / (1 + math.exp(-hi))]
            base = 1 / (1 + math.exp(-b[0]))
            # average predictive comparison: every team moved to the reference
            # format, its other parts kept, part k set to its 25th / 75th percentile
            Xr = X.copy()
            Xr[:, 5:] = 0.0
            apc = []
            for k in range(4):
                for qv in ref[k]:
                    Xq = Xr.copy()
                    Xq[:, 1 + k] = qv
                    pq = 1 / (1 + np.exp(-np.clip(Xq @ b, -30, 30)))
                    apc.append(float((w * pq).sum() / w.sum()))
            p_ref = 1 / (1 + np.exp(-np.clip(Xr @ b, -30, 30)))
            return list(b[1:5]) + ame + spread + [base] + apc + [float((w * p_ref).sum() / w.sum())]
        est = fit(np.ones(len(idx)))
        bs = np.array([fit(Wb[bb][g]) for bb in range(a.boot_logit)])
        comps = ["draft", "acq", "lineup_gain", "luck_win"]
        out = {"n": int(len(idx)), "events": int(y.sum()), "reference_format_teams_field_byes": list(ref_fmt),
               "prob_average_team_at_reference": round(est[16], 4),
               "mean_prob_at_reference_format": round(est[25], 4)}
        for k, c in enumerate(comps):
            q = np.percentile(Xc[:, k], [25, 75])
            lo, hi = 17 + 2 * k, 18 + 2 * k
            out[c] = {"coef_logit": round(est[k], 4), "coef_ci95": ci(bs[:, k]),
                      "ame_pp_per_unit": pct(est[4 + k]), "ame_ci95_pp": [pct(z) for z in ci(bs[:, 4 + k])],
                      "p25_p75_value": [round(float(q[0]), 2), round(float(q[1]), 2)],
                      "apc_prob_at_p25_p75": [pct(est[lo]), pct(est[hi])],
                      "apc_gap_pp": pct(est[hi] - est[lo]),
                      "apc_gap_ci95_pp": [pct(z) for z in ci(bs[:, hi] - bs[:, lo])],
                      "avg_team_prob_at_p25_p75": [pct(est[8 + 2 * k]), pct(est[9 + 2 * k])],
                      "avg_team_gap_pp": pct(est[9 + 2 * k] - est[8 + 2 * k])}
        # points are points: coefficient differences
        for i, j in ((0, 1), (0, 2), (1, 2)):
            dlt = bs[:, i] - bs[:, j]
            out[f"diff_{comps[i]}_minus_{comps[j]}"] = {"est": round(est[i] - est[j], 4), "ci95": ci(dlt)}
        return out
    ref6 = (12, 6, 2)
    allmask = np.ones(len(rows), bool)
    bye_mask = np.array([(r.get("n_byes") or 0) > 0 for r in rows])
    res["leverage"]["bye"] = leverage("bye", bye_mask, ref6)
    res["leverage"]["playoffs"] = leverage("playoffs", allmask, ref6)
    res["leverage"]["title"] = leverage("champ", allmask, ref6)
    six = np.array([(r.get("n_field"), r.get("n_byes")) == (6, 2) for r in rows])
    if six.sum() > 1000:
        res["leverage"]["title_6team_2bye_only"] = leverage("champ", six, ref6)
        res["leverage"]["bye_6team_2bye_only"] = leverage("bye", six, ref6)

    def leverage_pf(outcome, mask):
        """Points for and luck only: the per-point anchor for the component effects."""
        idx = np.where(mask & have_b)[0]
        y = np.array([rows[i][outcome] for i in idx], dtype=float)
        fm = [fmt[i] for i in idx]
        levels = sorted(set(fm), key=lambda z: (-fm.count(z)))
        ref = ref6 if ref6 in levels else levels[0]
        dummies = [lv for lv in levels if lv != ref]
        Z = np.array([[1.0 * (f == lv) for lv in dummies] for f in fm]).reshape(len(idx), len(dummies))
        X = np.c_[np.ones(len(idx)), PF[idx], LUCK[idx], Z]
        g = lg_idx[idx]

        def fit(w):
            bb = logit_fit(X, y, w)
            p = 1 / (1 + np.exp(-np.clip(X @ bb, -30, 30)))
            return [bb[1], bb[2], float((w * bb[1] * p * (1 - p)).sum() / w.sum()),
                    float((w * bb[2] * p * (1 - p)).sum() / w.sum())]
        est = fit(np.ones(len(idx)))
        bs = np.array([fit(Wb[k][g]) for k in range(a.boot_logit)])
        return {"coef_pf": round(est[0], 4), "coef_pf_ci95": ci(bs[:, 0]),
                "coef_luck": round(est[1], 4), "coef_luck_ci95": ci(bs[:, 1]),
                "ame_pp_per_point_pf": pct(est[2]), "ame_pf_ci95_pp": [pct(z) for z in ci(bs[:, 2])],
                "ame_pp_per_luck_win": pct(est[3]), "ame_luck_ci95_pp": [pct(z) for z in ci(bs[:, 3])],
                "points_per_week_equal_to_one_win": round(est[1] / est[0], 2)}
    res["leverage"]["pf_only"] = {"bye": leverage_pf("bye", bye_mask),
                                  "playoffs": leverage_pf("playoffs", allmask),
                                  "title": leverage_pf("champ", allmask)}

    # ------------------------------------------------ 4. persistence by user
    comps = {"pf": PF, "draft": D, "acq": A, "lineup": Lp, "luck": LUCK, "wins": WINS,
             "lineup_dead": demean(rows, "lineup_dead"), "lineup_choice": demean(rows, "lineup_choice"),
             "n_adds": demean(rows, "n_adds")}
    for r in rows:
        r["net_wire"] = r["gain_wire"] - r["loss_dropped"]
        r["net_trade"] = r["gain_trade"] - r["loss_tradedaway"]
    comps["net_wire"] = demean(rows, "net_wire")
    comps["net_trade"] = demean(rows, "net_trade")
    by_user = collections.defaultdict(list)
    for i, r in enumerate(rows):
        if r["owner"]:
            by_user[r["owner"]].append(i)

    def pairs(kind):
        P, U = [], []
        non_faab = kind.endswith("_non_faab")
        kind = kind.removesuffix("_non_faab")
        for u, ix in by_user.items():
            pr = []
            if non_faab:
                ix = [i for i in ix if rows[i]["waiver_type"] in (0, 1)]
            if kind == "same_season":
                for s in (2024, 2025):
                    xs = [i for i in ix if rows[i]["season"] == s]
                    pr += [(i, j) for i in xs for j in xs if i != j and rows[i]["league"] != rows[j]["league"]]
            else:
                a24 = [i for i in ix if rows[i]["season"] == 2024]
                a25 = [i for i in ix if rows[i]["season"] == 2025]
                pr += [(i, j) for i in a24 for j in a25]
            if pr:
                P.extend(pr)
                U.extend([u] * len(pr))
        return P, U
    for kind in ("same_season", "year_over_year", "same_season_non_faab", "year_over_year_non_faab"):
        P, U = pairs(kind)
        if len(P) < 30:
            continue
        users = sorted(set(U))
        uidx = {u: k for k, u in enumerate(users)}
        ui = np.array([uidx[u] for u in U])
        npair = np.bincount(ui).astype(float)
        base_w = 1.0 / npair[ui]
        I = np.array([p[0] for p in P])
        J = np.array([p[1] for p in P])
        Wu = boot_weights(users, a.boot, rng)
        block: dict = {"pairs": len(P), "users": len(users)}
        for name, x in comps.items():
            xi, xj = x[I], x[J]

            def wcorr(w, xi=xi, xj=xj):
                mi, mj = (w * xi).sum() / w.sum(), (w * xj).sum() / w.sum()
                cv = (w * (xi - mi) * (xj - mj)).sum()
                return cv / math.sqrt((w * (xi - mi) ** 2).sum() * (w * (xj - mj) ** 2).sum())
            est = wcorr(base_w)
            bs = np.array([wcorr(base_w * Wu[b][ui]) for b in range(a.boot)])
            ri = np.argsort(np.argsort(xi)).astype(float)
            rj = np.argsort(np.argsort(xj)).astype(float)
            block[name] = {"r": round(float(est), 3), "ci95": ci(bs),
                           "spearman": round(float(wcorr(base_w, ri, rj)), 3)}
        res["persistence"][kind] = block

    # ------------------------------------------------ 5. acquisitions
    acq = {}
    keys = sorted({k for r in rows for k in r if k.startswith("start_")})
    for name, fn in (("all", lambda r: True), ("faab", lambda r: r["waiver_type"] == 2),
                     ("non_faab", lambda r: r["waiver_type"] in (0, 1)),
                     ("reverse_standings", lambda r: r["waiver_type"] == 1)):
        rr = [r for r in rows if fn(r)]
        if len(rr) < 100:
            continue
        lg = np.array([r["league"] for r in rr])
        uniq = {v: k for k, v in enumerate(sorted(set(lg)))}
        gi = np.array([uniq[v] for v in lg])
        Wl = boot_weights(range(len(uniq)), a.boot, rng)
        blk: dict = {"team_seasons": len(rr), "leagues": len(uniq)}
        for k in ["acq", "gain_wire", "gain_trade", "loss_dropped", "loss_tradedaway", "n_adds", "n_trades",
                  "n_adds_b0", "n_adds_b1", "n_adds_b2"] + keys:
            v = np.array([r.get(k, 0.0) for r in rr])
            s = np.bincount(gi, weights=v, minlength=len(uniq))
            c = np.bincount(gi, minlength=len(uniq)).astype(float)
            blk[k] = {"mean_per_week": round(float(v.mean()), 3), "ci95": ci((Wl @ s) / (Wl @ c)),
                      "sd": round(float(v.std()), 3)}
        nw = np.array([r["gain_wire"] - r["loss_dropped"] for r in rr])
        nt = np.array([r["gain_trade"] - r["loss_tradedaway"] for r in rr])
        for bkt in range(3):
            pts = sum(r.get(f"start_wire_b{bkt}", 0.0) * r["weeks"] for r in rr)
            cnt = sum(r[f"n_adds_b{bkt}"] for r in rr)
            blk[f"wire_started_points_per_add_b{bkt}"] = round(pts / max(1, cnt), 2)
            rem = sum(r[f"rem_b{bkt}"] for r in rr)
            blk[f"wire_started_points_per_add_per_week_left_b{bkt}"] = round(pts / max(1, rem), 3)
            blk[f"wire_mean_weeks_left_per_add_b{bkt}"] = round(rem / max(1, cnt), 2)
        blk["free_agent_share_of_adds"] = round(sum(r["n_fa_adds"] for r in rr) / max(1, sum(r["n_adds"] for r in rr)), 3)
        blk["net_wire_mean"] = round(float(nw.mean()), 3)
        blk["net_trade_mean"] = round(float(nt.mean()), 3)
        # how the net parts spread within leagues (demeaned SD) and their share of var(ACQ)
        nwd = nw - np.array([nw[gi == g].mean() for g in gi])
        ntd = nt - np.array([nt[gi == g].mean() for g in gi])
        ad = nwd + ntd
        blk["var_acq_share_wire"] = round(float((nwd * nwd).sum() / (ad * ad).sum()), 3)
        blk["var_acq_share_trade"] = round(float((ntd * ntd).sum() / (ad * ad).sum()), 3)
        blk["var_acq_share_2cov"] = round(float(2 * (nwd * ntd).sum() / (ad * ad).sum()), 3)
        blk["sd_net_wire_demeaned"] = round(float(nwd.std()), 3)
        blk["sd_net_trade_demeaned"] = round(float(ntd.std()), 3)
        acq[name] = blk
    res["acquisitions"] = acq

    # ------------------------------------------------ 6. lineup losses
    wk = np.array([w[3] for w in weekly])
    dead = np.array([w[4] for w in weekly])
    order = np.sort(wk)[::-1]
    top10 = order[: max(1, len(order) // 10)].sum() / max(1e-9, order.sum())
    # within team-season: worst 10% of weeks (rounded up)
    per_team = collections.defaultdict(list)
    for w in weekly:
        per_team[(w[0], w[1])].append(w[3])
    within = []
    for v in per_team.values():
        v = sorted(v, reverse=True)
        k = max(1, math.ceil(0.1 * len(v)))
        if sum(v) > 0:
            within.append(sum(v[:k]) / sum(v))
    res["lineup"] = {
        "team_weeks": len(wk),
        "mean_per_week": round(float(wk.mean()), 3),
        "median_per_week": round(float(np.median(wk)), 3),
        "p90_per_week": round(float(np.percentile(wk, 90)), 3),
        "share_team_weeks_perfect": round(float((wk < 1e-6).mean()), 4),
        "share_of_total_from_worst_10pct_team_weeks": round(float(top10), 4),
        "share_of_team_season_total_from_its_worst_10pct_weeks_mean": round(float(np.mean(within)), 4),
        "dead_slot_share_of_total": round(float(dead.sum() / wk.sum()), 4),
        "choice_share_of_total": round(float(1 - dead.sum() / wk.sum()), 4),
        "team_weeks_with_dead_starter": round(float((np.array([w[5] for w in weekly]) > 0).mean()), 4),
        "dead_loss_when_present_mean": round(float(dead[dead > 0].mean()) if (dead > 0).any() else 0.0, 3),
    }
    for name in ("lineup", "lineup_dead", "lineup_choice"):
        v = np.array([r[name] for r in rows])
        res["lineup"][f"team_season_{name}_per_week_p10_p25_p50_p75_p90"] = [
            round(float(x), 2) for x in np.percentile(v, [10, 25, 50, 75, 90])]
        res["lineup"][f"team_season_{name}_per_week_mean"] = round(float(v.mean()), 3)
    zero_dead = np.array([r["lineup_dead"] < 1e-9 for r in rows])
    res["lineup"]["team_seasons_with_zero_dead_slot_loss"] = round(float(zero_dead.mean()), 4)
    # ------------------------------------------------ skill table: persistent spread x leverage
    sd = dict(res["variance_pf"]["all"]["sd_points_per_week"])
    yoy = res["persistence"].get("year_over_year", {})
    table = {}
    for name in ("lineup_dead", "lineup_choice"):
        sd[name] = round(float(np.sqrt((comps[name] ** 2).mean())), 3)
    for comp, lev_key in (("draft", "draft"), ("acq", "acq"), ("lineup", "lineup_gain"),
                          ("lineup_dead", "lineup_gain"), ("lineup_choice", "lineup_gain"), ("pf", None)):
        if comp not in yoy:
            continue
        r = yoy[comp]["r"]
        psd = sd[comp] * math.sqrt(max(r, 0.0))
        row = {"sd_points_per_week": sd[comp], "r_year_over_year": r, "r_ci95": yoy[comp]["ci95"],
               "persistent_sd_points_per_week": round(psd, 2)}
        for out_name in ("bye", "title"):
            lv = res["leverage"][out_name]
            ame = lv[lev_key]["ame_pp_per_unit"] if lev_key else res["leverage"]["pf_only"][out_name]["ame_pp_per_point_pf"]
            row[f"{out_name}_pp_per_persistent_sd"] = round(ame * psd, 2)
            row[f"{out_name}_pp_per_total_sd"] = round(ame * sd[comp], 2)
        table[comp] = row
    res["skill_table"] = table
    res["runtime_s"] = round(time.time() - t0, 1)
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(json.dumps({k: res[k] for k in ("sample", "controls")}, indent=1, default=str))
    print("wrote", out, f"in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
