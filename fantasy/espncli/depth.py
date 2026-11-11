"""What a roster is worth in weeks 16 and 17 once starters go missing.

The playbook's *The strategic thesis* rule 4 (2026-11-11): a starter who is
healthy in week 10 has no stat line in week 16 at 15.6% and in week 17 at
18.2% (`research/playoff_absence.py rates`). So the bench is a chain with
usage. The first RB/WR replacement plays in about 60% of playoff weeks and
the fourth in about 1%, and a bench move is worth the points it adds at the
place the player takes, not his rate gap times every week.

`expected` takes each rostered skill player out at his position's rate,
independently, and refills the best lineup from the bench, then from the
wire. The mean is exact (a sum over the states of each position), so two
rosters compare with no sampling noise. `tree` prices
each starter's absence and one more point at each place. `swap_title_value`
prices one swap, and `roster-watch` uses it to keep a held swap that is worth
almost nothing out of the banners.

INVARIANTS
- The pure functions take rows and rates and touch no network. `live_inputs`
  is the one reader, and it only reads.
- Standard library only. The launchd job's interpreter has no numpy, and an
  import error here would turn the banner filter off with no report
  (found 2026-11-11, the first version drew samples with numpy).
- Nothing here files, moves or drops a player.
- `swap_title_value` returns None when it cannot price the swap (a position
  outside RB and WR, a berth that is not safe, a missing or old input). None
  means "decide as before", never "worth nothing".
"""

from __future__ import annotations

import json
import time
from pathlib import Path

FANTASY = Path(__file__).resolve().parent.parent
RATES_FILE = FANTASY / "research" / "out" / "playoff_absence.json"
LEVERAGE_FILE = FANTASY / ".cache" / "leverage.json"
LEVERAGE_MAX_AGE = 8 * 86400     # older than a Tuesday cycle: do not price on it
SKILL = ("QB", "RB", "WR", "TE")
CHAIN = ("RB", "WR")              # the positions a flex-chain swap is priced for
FINAL_WEEKS = (16, 17)            # the two weeks we play with a bye
SAFE_BERTH = 0.99                 # playoff odds above which the playoff weeks are nearly all of a move's value
NEED = {"QB": 1, "RB": 3, "WR": 3, "TE": 2}   # players a position can put in the lineup: its slots plus FLEX

Player = tuple[str, str, float]   # name, position, points a game (`value.ros_rate`)


def best_lineup(avail: list[Player], wire: dict[str, float]) -> float:
    """Points of the best QB, 2 RB, 2 WR, TE and FLEX from the players available,
    with the wire's best player at each position as an unlimited fallback."""
    qb = max([r for _, p, r in avail if p == "QB"] + [wire["QB"]])
    tes = sorted([r for _, p, r in avail if p == "TE"], reverse=True) + [wire["TE"]] * 2
    rbs = sorted([r for _, p, r in avail if p == "RB"], reverse=True) + [wire["RB"]] * 3
    wrs = sorted([r for _, p, r in avail if p == "WR"], reverse=True) + [wire["WR"]] * 3
    return qb + tes[0] + rbs[0] + rbs[1] + wrs[0] + wrs[1] + max(rbs[2], wrs[2], tes[1])


def position_states(rates: list[float], p_miss: float, k: int, wire: float) -> dict[tuple[float, ...], float]:
    """The best `k` players available at one position, with the probability of each case.

    Each rostered player is missing with probability `p_miss`, independently,
    and the wire supplies any number of players at `wire`. Players are taken
    best first, so the first `k` who are available are the best `k`."""
    states: dict[tuple[float, ...], float] = {(): 1.0}
    for r in sorted(rates, reverse=True):
        nxt: dict[tuple[float, ...], float] = {}
        for st, pr in states.items():
            if len(st) == k:
                nxt[st] = nxt.get(st, 0.0) + pr
                continue
            nxt[st + (r,)] = nxt.get(st + (r,), 0.0) + pr * (1.0 - p_miss)
            nxt[st] = nxt.get(st, 0.0) + pr * p_miss
        states = nxt
    out: dict[tuple[float, ...], float] = {}
    for st, pr in states.items():
        top = tuple(sorted(st + (wire,) * k, reverse=True)[:k])
        out[top] = out.get(top, 0.0) + pr
    return out


def expected(roster: list[Player], wire: dict[str, float], miss: dict[str, float]) -> float:
    """Mean points of the best lineup with each player missing at his position's rate, independently. Exact."""
    by = {pos: position_states([r for _, p, r in roster if p == pos], miss[pos], NEED[pos], wire[pos]) for pos in SKILL}
    total = sum(pr * st[0] for st, pr in by["QB"].items())
    for te, p_te in by["TE"].items():
        for rb, p_rb in by["RB"].items():
            for wr, p_wr in by["WR"].items():
                total += p_te * p_rb * p_wr * (te[0] + rb[0] + rb[1] + wr[0] + wr[1] + max(rb[2], wr[2], te[1]))
    return total


def final_weeks(roster: list[Player], wire: dict[str, float], rates: dict[int, dict[str, float]]) -> dict[int, float]:
    """Expected lineup points in each of weeks 16 and 17."""
    return {w: expected(roster, wire, rates[w]) for w in FINAL_WEEKS}


def title_points(ev: dict[int, float], base: dict[int, float], per_point: dict[int, float]) -> float:
    """The difference between two lineups in points of title odds."""
    return sum((ev[w] - base[w]) * per_point[w] * 100 for w in FINAL_WEEKS)


def lineup_names(roster: list[Player], wire: dict[str, float]) -> tuple[list[str], list[str]]:
    """(the seven starters, the RB/WR bench in order of use) at full health."""
    by = {p: sorted([x for x in roster if x[1] == p], key=lambda x: -x[2]) for p in SKILL}
    starters = [x[0] for x in by["QB"][:1] + by["RB"][:2] + by["WR"][:2] + by["TE"][:1]]
    rest = sorted(by["RB"][2:] + by["WR"][2:], key=lambda x: -x[2])
    if rest:
        starters.append(rest[0][0])
    chain = [x[0] for x in rest[1:] if x[2] > min(wire["RB"], wire["WR"])]
    return starters, chain


def tree(roster: list[Player], wire: dict[str, float], rates: dict[int, dict[str, float]],
         per_point: dict[int, float]) -> dict:
    """The fault tree: each starter's absence and one more point at each place, in title points."""
    full = best_lineup(roster, wire)
    base = final_weeks(roster, wire, rates)
    starters, chain = lineup_names(roster, wire)
    modes = []
    for name, pos, rate in roster:
        if name not in starters:
            continue
        loss = full - best_lineup([x for x in roster if x[0] != name], wire)
        modes.append({"player": name, "pos": pos, "rate": rate, "lost_if_out": round(loss, 1),
                      "p_out": {w: rates[w][pos] for w in FINAL_WEEKS},
                      "title": round(sum(rates[w][pos] * loss * per_point[w] * 100 for w in FINAL_WEEKS), 2)})
    modes.sort(key=lambda m: -m["title"])
    plus_one = []
    for name in [*starters, *chain]:
        bumped = [(n, p, r + 1.0) if n == name else (n, p, r) for n, p, r in roster]
        plus_one.append({"player": name, "place": "starter" if name in starters else f"bench {chain.index(name) + 1}",
                         "title_per_point": round(title_points(final_weeks(bumped, wire, rates), base, per_point), 2)})
    return {"full_health": round(full, 1), "expected": {w: round(v, 1) for w, v in base.items()},
            "injury_tax_title": round(title_points(base, dict.fromkeys(FINAL_WEEKS, full), per_point), 1),
            "failure_modes": modes, "one_more_point": plus_one, "wire": wire}


def swap_value(roster: list[Player], wire: dict[str, float], rates: dict[int, dict[str, float]],
               per_point: dict[int, float], drop: str, add: Player) -> float:
    """Title points of one swap: the roster with `add` in the place of `drop`, against the roster as it is."""
    if not any(n == drop for n, _, _ in roster):
        raise ValueError(f"{drop} is not on the roster")
    after = [add if n == drop else (n, p, r) for n, p, r in roster]
    return title_points(final_weeks(after, wire, rates), final_weeks(roster, wire, rates), per_point)


# ---- inputs -----------------------------------------------------------------

def load_rates(path: Path = RATES_FILE) -> dict[int, dict[str, float]]:
    saved = json.loads(path.read_text())
    return {w: {pos: float(saved["by_pos"][pos][str(w)]["miss"]) for pos in SKILL} for w in FINAL_WEEKS}


def load_leverage(path: Path = LEVERAGE_FILE, now: float | None = None) -> tuple[dict[int, float], float] | None:
    """(title odds per point in each playoff week, our playoff odds) from this
    Tuesday's `season_sim --leverage`, or None when the file is missing or old."""
    try:
        if (now or time.time()) - path.stat().st_mtime > LEVERAGE_MAX_AGE:
            return None
        d = json.loads(path.read_text())
        per_point = {int(k): float(v) for k, v in d["playoff_per_point"].items()}
        if any(w not in per_point for w in FINAL_WEEKS):
            return None
        return per_point, float(d["base"]["playoffs"])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def live_inputs() -> tuple[list[Player], dict[str, float]]:
    """Our roster and the best healthy free agent at each position, on `ros_rate`."""
    from espncli.cli import pool_rows, roster_rows  # noqa: PLC0415
    from espncli.client import IR, Espn, norm  # noqa: PLC0415
    from espncli.value import games_appeared, games_played, load_volume_rows, ros_rate  # noqa: PLC0415

    api = Espn()
    data = api.league("mTeam", "mRoster", "mSettings", "mStatus")
    week = api.current_week(data)
    games = {pt["abbrev"]: games_played(pt["games"], week) for pt in api.pro_teams().values()}
    appeared = games_appeared(load_volume_rows(api.season), week)

    def rate(r: dict) -> float:
        return ros_rate(week, r.get("proj"), r.get("season_proj"), r.get("season_actual"),
                        games.get(r.get("team") or ""), appeared.get(f"{norm(r['name'])}|{r['pos']}"))

    mine = roster_rows(api, api.roster_entries(data, api.resolve_team(data, None)["id"]), week)
    roster = [(r["name"], r["pos"], round(rate(r), 2)) for r in mine if r["pos"] in SKILL and r["slotId"] != IR]
    wire = {}
    for pos in SKILL:
        rows = [r for r in pool_rows(api, week, pos, 60, ["FREEAGENT"]) if not r.get("status")]
        wire[pos] = round(max((rate(r) for r in rows), default=0.0), 2)
    return roster, wire


def swap_title_value(drop: str, add: Player, drop_pos: str | None = None,
                     inputs: tuple[list[Player], dict[str, float]] | None = None,
                     rates_file: Path = RATES_FILE, leverage_file: Path = LEVERAGE_FILE) -> float | None:
    """Title points of a bench-for-wire swap on the live roster, or None when
    this model does not cover it: a position outside RB and WR on either side,
    playoff odds under SAFE_BERTH (the regular season still carries value this
    model leaves out), or a missing or old input."""
    if add[1] not in CHAIN or (drop_pos is not None and drop_pos not in CHAIN):
        return None
    lev = load_leverage(leverage_file)
    if lev is None or lev[1] < SAFE_BERTH:
        return None
    try:
        rates = load_rates(rates_file)
    except (OSError, ValueError, KeyError):
        return None
    roster, wire = inputs or live_inputs()
    held = next((p for n, p, _ in roster if n == drop), None)
    if held not in CHAIN:
        return None
    return round(swap_value(roster, wire, rates, lev[0], drop, add), 3)
