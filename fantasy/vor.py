#!/usr/bin/env python3
"""Build a value-over-replacement draft board for the draftbot.

Why this exists: the autopilot used to score on raw overall board rank, which is
the wrong yardstick in a one-QB league. Rank compares a player to the whole
field; what actually decides a pick is how much better he is than the guy you
could have at his own position anyway. That is why a rank board takes a QB in
round 4 (QB1 ranks well but the 13th QB is nearly as good) and never takes a
tight end (TEs rank poorly overall but the 14th TE is dreadful).

Two sources, each doing what it is good at:

- **The Ringer** decides *who* is the best player at a position. It is the board
  Alex chose, it is editorial, and it is not replaceable by a projection.
- **ESPN's own 2026 projections** decide *how much* a WR3 is worth against an
  RB5. They come back already scored in this league's full-PPR settings, which
  makes them the only cross-positional common scale available.

So a player's value is `curve[pos][his positional rank] - curve[pos][replacement]`,
where the curve is ESPN's projections sorted within the position. The Ringer
picks the slot on the curve; ESPN says what the slot is worth.

Read-only against ESPN, same credentials as `bin/ff`.
"""

import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CREDS = os.path.join(HERE, "espn-credentials.json")
BOARD = os.path.join(HERE, "ringer_board.json")
OUT = os.path.join(HERE, "draftbot", "vor.json")

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}

# Replacement level for 13 teams starting QB/RB/RB/WR/WR/TE/FLEX/D/ST/K.
# Base is starters (13 x slots); the flex is split toward WR because full PPR is
# the receiver-friendly extreme (RB12 returns 56.4% of RB1 and lands below WR24).
REPLACEMENT = {"QB": 13, "RB": 30, "WR": 34, "TE": 14, "K": 13, "D/ST": 13}

# Elite projections are systematically too high, and by a measured amount:
# Fantasy Football Analytics' 2019-2024 bias study (skill evidence, §5) has
# RB1-5 missing their season projections by ~55 points, WR1-5 by ~31, TE1-5 by
# ~23, and QB6-10 by ~42.
#
# OFF BY DEFAULT after a negative experiment (2026-08-24): drafting on the
# corrected board graded WORSE under the independent consensus judge at both
# full and half strength (avg rank 2.56 -> 2.67 / 2.70 across 312 sim rooms).
# The likely reason is instructive: the correction moves the board toward
# reality, but the judge is built from other projections that share the same
# industry-wide elite optimism (CBS has Gibbs at 387), so the only instrument
# able to validate this correction is actual season results. Revisit via the
# disagreement ledger once real games exist; do not re-enable on projections
# alone. ELITE_BIAS: pos -> (first_rank, last_rank, points_over_projected).
ELITE_BIAS = {
    "RB": (1, 5, 55.0),
    "WR": (1, 5, 31.0),
    "TE": (1, 5, 23.0),
    "QB": (6, 10, 42.0),
}
BIAS_STRENGTH = float(os.environ.get("VOR_BIAS_STRENGTH", "0.0"))


def debias(pos, curve):
    """Shrink a positional projection curve by the published elite bias.

    Flat correction inside the band; past the band it decays linearly to zero
    at the position's replacement rank (replacement players are projected
    fine, so the correction must vanish there and the baseline stays put); a
    3-rank ramp on a leading edge (QB's band starts at 6).

    Then a strict-monotonicity pass. Several curves (QB especially) are
    flatter than the correction is tall, so a corrected rank-6 can land below
    an uncorrected rank-7. A plain running minimum would clamp whole stretches
    to one value and erase the Ringer's ordering inside them, so ties are
    broken by forcing each rank at least EPS below the one above it.
    """
    band = ELITE_BIAS.get(pos)
    if not band or not curve or BIAS_STRENGTH == 0:
        return curve
    lo, hi, mean = band
    repl = REPLACEMENT.get(pos, hi + 10)
    eps = 0.5
    out = []
    for i, val in enumerate(curve, start=1):
        if lo <= i <= hi:
            w = 1.0
        elif i < lo:
            w = max(0.0, 1.0 - (lo - i) / 3.0)
        elif i < repl:
            w = (repl - i) / (repl - hi)
        else:
            w = 0.0
        out.append(val - BIAS_STRENGTH * mean * w)
    for i in range(1, len(out)):
        out[i] = min(out[i], out[i - 1] - eps)
    return out


def norm(s):
    s = unicodedata.normalize("NFKD", s).replace("’", "").replace("'", "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def get(url, creds, extra=None):
    headers = {
        "Cookie": f"espn_s2={creds['espn_s2']}; SWID={creds['SWID']}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "application/json",
    }
    headers.update(extra or {})
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=40
        ) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"ESPN HTTP {e.code}: {e.reason}. Try `bin/ff refresh`.")


def adp(player):
    """Where the crowd actually takes him, not where ESPN ranks him.

    Real ADP off ESPN's own leagues. It is what makes value-over-next-available
    possible: without it there is no way to ask who will still be there at the
    next turn, and value over replacement alone will happily spend an early pick
    on a player nobody else was going to take for another two rounds.
    """
    own = player.get("ownership") or {}
    a = own.get("averageDraftPosition")
    if a and a > 0:
        return round(a, 1)
    return float(espn_rank(player))


def espn_rank(player):
    """ESPN's own PPR draft rank: the list AUTO teams actually draft from."""
    ranks = player.get("draftRanksByRankType") or {}
    ppr = ranks.get("PPR") or {}
    return int(ppr.get("rank") or 9999)


def sleeper_projections():
    """Second, independent projection source: Sleeper's public API (no auth).

    The blend exists because no single projection source wins consistently,
    while a simple average across sources grades top-3 at every position every
    year (see the skill, §5). ESPN and Sleeper disagree by 30+ points on real
    players (Gibbs 364.9 vs 331.4 in Aug 2026), which is exactly the disagreement
    averaging is for. Failure here must never block a draft-morning rebuild, so
    any error returns {} and the board falls back to ESPN alone, loudly.
    """
    url = (
        "https://api.sleeper.app/projections/nfl/2026?season_type=regular"
        "&position[]=QB&position[]=RB&position[]=WR&position[]=TE"
        "&position[]=K&position[]=DEF&order_by=pts_ppr"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception as exc:  # noqa: BLE001 - any failure means "no second source"
        print(f"WARNING: Sleeper projections unavailable ({exc}); ESPN-only board")
        return {}
    out = {}
    for entry in data:
        pl = entry.get("player") or {}
        pts = (entry.get("stats") or {}).get("pts_ppr")
        if pts is None:
            continue
        if pl.get("position") == "DEF":
            name = f"{pl.get('last_name', '')} D/ST"
        else:
            name = f"{pl.get('first_name', '')} {pl.get('last_name', '')}"
        out[norm(name)] = float(pts)
    return out


def season_projection(player):
    """2026 full-season projection: statSourceId 1 (projected), split 0 (season)."""
    for s in player.get("stats", []):
        if (
            s.get("seasonId") == 2026
            and s.get("statSourceId") == 1
            and s.get("statSplitTypeId") == 0
        ):
            return s.get("appliedTotal")
    return None


def main():
    creds = json.load(open(CREDS))
    base = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"

    byes = {}
    sched = get(f"{base}/seasons/{creds['season']}?view=proTeamSchedules_wl", creds)
    for t in sched.get("settings", {}).get("proTeams", []):
        byes[t["id"]] = t.get("byeWeek", 0)

    filt = {
        "players": {
            "limit": 900,
            "sortDraftRanks": {
                "sortPriority": 100,
                "sortAsc": True,
                "value": "PPR",
            },
        }
    }
    raw = get(
        f"{base}/seasons/{creds['season']}/segments/0/leagues/{creds['league_id']}"
        "/players?scoringPeriodId=0&view=kona_player_info",
        creds,
        {"X-Fantasy-Filter": json.dumps(filt)},
    )

    sleeper = sleeper_projections()

    espn = {}
    blended = 0
    for entry in raw:
        p = entry["player"]
        pos = POS.get(p.get("defaultPositionId"))
        proj = season_projection(p)
        if not pos or proj is None:
            continue
        sl = sleeper.get(norm(p["fullName"]))
        if sl is not None:
            proj = (proj + sl) / 2.0
            blended += 1
        espn[norm(p["fullName"])] = {
            "pos": pos,
            "proj": round(proj, 1),
            "bye": byes.get(p.get("proTeamId"), 0),
            "name": p["fullName"],
            "adp": adp(p),
            "espnRank": espn_rank(p),
            "injured": bool(p.get("injured")),
        }

    # ESPN's projection curve per position: the value of the Nth-best at that spot.
    curve = {}
    for pos in POS.values():
        curve[pos] = sorted(
            (v["proj"] for v in espn.values() if v["pos"] == pos), reverse=True
        )
        curve[pos] = debias(pos, curve[pos])

    def at(pos, k):
        """Projection of the k-th best player at a position (1-indexed, clamped)."""
        c = curve.get(pos) or [0.0]
        return c[min(max(k, 1), len(c)) - 1]

    baseline = {pos: at(pos, n) for pos, n in REPLACEMENT.items()}

    ringer = {}
    if os.path.exists(BOARD):
        for p in json.load(open(BOARD))["players"]:
            ringer[norm(p["name"])] = p

    out = {}
    # Off-board players fall back to their own projection's slot on the curve.
    espn_pos_rank = {}
    for pos in POS.values():
        ranked = sorted(
            ((v["proj"], k) for k, v in espn.items() if v["pos"] == pos), reverse=True
        )
        for i, (_, k) in enumerate(ranked, 1):
            espn_pos_rank[k] = i

    # Signed dispositions from the pre-draft divergence sign-off (signoff.py):
    # a "consensus" player is re-slotted at his ECR positional rank, so the
    # board only diverges from the market where Alex has signed a thesis.
    overrides = {}
    ov_path = os.path.join(HERE, "board-overrides.json")
    if os.path.exists(ov_path):
        overrides = json.load(open(ov_path))
    ecr_slot = {}
    ecr_path = os.path.join(HERE, "draftbot", "ecr.json")
    if os.path.exists(ecr_path):
        bypos = {}
        for kk, vv in json.load(open(ecr_path)).items():
            bypos.setdefault(vv["pos"], []).append((vv["ecr"], kk))
        for _pos, lst in bypos.items():
            for i, (_, kk) in enumerate(sorted(lst), 1):
                ecr_slot[kk] = i
    corrections_wanted = {
        k for k, d in overrides.items() if d.get("action") == "consensus"
    }
    if corrections_wanted and not ecr_slot:
        sys.exit(
            "board-overrides.json has consensus corrections but draftbot/"
            "ecr.json is missing; run examiner.py --refresh first"
        )

    corrected = 0
    for key, e in espn.items():
        r = ringer.get(key)
        pos = e["pos"]
        if key in corrections_wanted and key in ecr_slot:
            k = ecr_slot[key]
            src = "signoff-consensus"
            corrected += 1
        elif r and r.get("pos") == pos and r.get("pos_rank"):
            k = r["pos_rank"]
            src = "ringer"
        else:
            k = espn_pos_rank.get(key, 999)
            src = "espn"
        vor = at(pos, k) - baseline.get(pos, 0.0)
        out[key] = {
            "name": e["name"],
            "pos": pos,
            "posRank": k,
            "vor": round(vor, 1),
            "adp": e["adp"],
            "espnRank": e["espnRank"],
            "bye": r["bye"] if r and r.get("bye") else e["bye"],
            "rank": r["rank"] if r else None,
            "injured": e["injured"],
            "src": src,
        }

    with open(OUT, "w") as fh:
        json.dump(
            {
                "replacement": REPLACEMENT,
                "baseline": {k: round(v, 1) for k, v in baseline.items()},
                "players": out,
            },
            fh,
        )

    print(f"players: {len(out)}   from ESPN projections + {len(ringer)} Ringer ranks")
    if corrected:
        print(f"signed consensus corrections applied: {corrected}")
    if ecr_slot:
        # Draft-morning gate: surface any divergence nobody has signed, so a
        # source update cannot smuggle a new counter-consensus bet onto the
        # board. signoff.py status exits nonzero on the same condition.
        unsigned = []
        sys.path.insert(0, HERE)
        from signoff import GAP as gap_min  # noqa: PLC0415 -- one source of truth for thresholds
        from signoff import RANGE as rng  # noqa: PLC0415

        for key, v in out.items():
            th = ecr_slot.get(key)
            if th is None or key in overrides:
                continue
            gap = abs(th - v["posRank"])
            if gap >= gap_min.get(v["pos"], 5) and min(th, v["posRank"]) <= rng.get(
                v["pos"], 40
            ):
                unsigned.append(f"{v['name']} ({v['pos']} ours {v['posRank']} ecr {th})")
        if unsigned:
            print(f"WARNING: {len(unsigned)} UNSIGNED divergences -- run signoff.py:")
            for u in unsigned[:15]:
                print("  " + u)
    print("replacement level (projected points):")
    for pos in ("QB", "RB", "WR", "TE", "K", "D/ST"):
        print(f"  {pos:<5} {REPLACEMENT[pos]:>3}th = {baseline[pos]:>6.1f}")
    missing_adp = sum(1 for v in out.values() if v["adp"] >= 9999)
    print(f"ADP present for {len(out) - missing_adp}/{len(out)} players")
    print(
        f"projections blended ESPN+Sleeper for {blended}/{len(espn)} players"
        + ("" if sleeper else "  (SLEEPER DOWN, ESPN ONLY)")
    )

    print("\ntop 30 by value over replacement:")
    top = sorted(out.values(), key=lambda v: -v["vor"])[:30]
    for i, v in enumerate(top, 1):
        rk = f"#{v['rank']}" if v["rank"] else "--"
        print(
            f"{i:>2}. {v['vor']:>6.1f}  {v['name']:<24}{v['pos']:<6}"
            f"posRk{v['posRank']:<4}Ringer{rk:<6}adp{v['adp']:<7}bye{v['bye']}"
        )


if __name__ == "__main__":
    main()
