"""fantasy/bin/swap-scan: the waiver gate, with the rules that bit.

Its failure mode is quiet (no PASS looks like "nothing worth doing"), so a
planted fixture must produce a PASS, and the 2026-09-20 bug (a second tight
end offered against a wide-receiver drop) must stay dead.
"""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "fantasy"))
_loader = importlib.machinery.SourceFileLoader("swap_scan", str(REPO / "fantasy" / "bin" / "swap-scan"))
spec = importlib.util.spec_from_loader("swap_scan", _loader)   # no .py suffix, so name the loader
assert spec is not None and spec.loader is not None
swap_scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(swap_scan)


def r(name, pos, slot_id, proj, season_proj, team="KC", avail="FA", owned=10.0):
    return {"name": name, "pos": pos, "slotId": slot_id, "slot": {20: "BE", 21: "IR", 4: "WR", 6: "TE", 0: "QB", 2: "RB"}[slot_id],
            "proj": proj, "season_proj": season_proj, "season_actual": None, "team": team,
            "avail": avail, "owned": owned, "trend": 0.0, "status": "", "eligible": [slot_id, 23, 20, 21]}


def roster():
    return [r("QB1", "QB", 0, 20.0, 340.0), r("TE1", "TE", 6, 12.0, 200.0), r("WR1", "WR", 4, 15.0, 250.0),
            r("Bench WR", "WR", 20, 6.0, 100.0), r("Bench TE", "TE", 20, 3.0, 50.0), r("IR WR", "WR", 21, 0.0, 99.9)]


def pool():
    return [r("Hot WR", "WR", 20, 12.0, 200.0, avail="WVR"),     # rate 11.9 vs bench WR 5.9: +6 x 12 = +72 PASS
            r("Free TE", "TE", 20, 9.0, 150.0),                 # a second TE: only against the TE drop
            r("Free QB", "QB", 20, 18.0, 300.0),                # a second QB: never
            r("Meh WR", "WR", 20, 6.0, 100.0)]                  # +0: below the gate


def test_gate_positive_control_and_the_second_te_rule():
    out = swap_scan.scan(2, roster(), pool(), position_max={"WR": 8, "TE": 3, "QB": 4})
    by_drop = {s["drop"]: s for s in out["swaps"]}
    wr = by_drop["Bench WR"]["candidates"]
    assert wr[0]["add"] == "Hot WR" and wr[0]["gain"] >= out["gate"], "the planted PASS must show"
    assert "Free TE" not in {c["add"] for c in wr}, "no second tight end against a WR drop"
    assert "Free QB" not in {c["add"] for c in wr}
    te = by_drop["Bench TE"]["candidates"]
    assert "Free TE" in {c["add"] for c in te}, "replacing the TE we hold is allowed"
    assert "Free QB" not in {c["add"] for c in te}


def test_position_cap_needs_a_same_position_drop():
    out = swap_scan.scan(2, roster(), pool(), position_max={"WR": 2})   # 2 active WRs (IR does not count): at the cap
    assert out["held"]["WR"] == 2
    by_drop = {s["drop"]: s for s in out["swaps"]}
    assert "Hot WR" in {c["add"] for c in by_drop["Bench WR"]["candidates"]}
    assert "Hot WR" not in {c["add"] for c in by_drop["Bench TE"]["candidates"]}


def test_a_streamer_on_the_bench_is_not_a_drop_for_a_skill_player():
    ros = [*roster(), r("Stream DST", "D/ST", 20, 4.0, 90.0)]
    out = swap_scan.scan(2, ros, pool(), position_max={"WR": 8, "TE": 3, "QB": 4})
    by_drop = {s["drop"]: s for s in out["swaps"]}
    assert by_drop["Stream DST"]["candidates"] == [], "a WR gain over a D/ST season rate is not a swap"
    assert by_drop["Bench WR"]["candidates"][0]["add"] == "Hot WR", "positive control: the WR drop still offers"


def test_role_and_heat_are_evidence_not_gate():
    vol = {"hot wr|WR": {"flags": ["ROLE-UP"], "last": {"snap": 0.9, "tgt_share": 0.25, "opps": 9.0}}}
    out = swap_scan.scan(2, roster(), pool(), {}, heat={"meh wr|WR": 5000}, volume=vol)
    cands = {c["add"]: c for s in out["swaps"] for c in s["candidates"]}
    assert cands["Hot WR"]["role"] is True and cands["Hot WR"]["flags"] == ["ROLE-UP"]
    assert cands["Meh WR"]["heat"] == 5000 and cands["Meh WR"]["gain"] < out["gate"], "heat never moves the gate"


def test_a_drop_spent_in_a_pending_claim_is_marked():
    """2026-09-20: the gate offered Wicks for Noel while Noel was the drop arming the
    QB waiver chain. The row stays (it is still information) but carries the mark
    roster-watch skips on; a positive control shows the mark can be false."""
    out = swap_scan.scan(2, roster(), pool(), {}, committed={swap_scan.norm("Bench WR")})
    by_drop = {s["drop"]: s for s in out["swaps"]}
    assert by_drop["Bench WR"]["pending_drop"] is True
    assert by_drop["Bench TE"]["pending_drop"] is False
    assert by_drop["Bench WR"]["candidates"][0]["gain"] >= out["gate"], "the PASS is still reported, just marked"


def test_our_side_of_a_pending_trade_is_committed():
    """2026-09-30: Godwin showed as a free +23.7 drop while he sat in the Allen
    offer, and a drop voids the trade. Our outgoing trade items count; the
    player we would receive, a claim's ADD and another team's DROP do not."""
    me = 12
    txs = [
        {"type": "TRADE_PROPOSAL", "items": [
            {"type": "TRADE", "fromTeamId": me, "toTeamId": 2, "playerId": 1},
            {"type": "TRADE", "fromTeamId": 2, "toTeamId": me, "playerId": 2}]},
        {"type": "WAIVER", "items": [
            {"type": "ADD", "fromTeamId": 0, "toTeamId": me, "playerId": 3},
            {"type": "DROP", "fromTeamId": me, "toTeamId": 0, "playerId": 4}]},
        {"type": "WAIVER", "items": [{"type": "DROP", "fromTeamId": 5, "toTeamId": 0, "playerId": 6}]},
    ]
    assert sorted(swap_scan.committed_ids(txs, me)) == [1, 4]


def test_an_injured_add_is_not_a_candidate():
    hurt = r("Hurt WR", "WR", 20, 12.0, 200.0, avail="WVR")
    hurt["status"] = "OUT"
    out = swap_scan.scan(2, roster(), [*pool(), hurt], position_max={"WR": 8, "TE": 3, "QB": 4})
    adds = {c["add"] for s in out["swaps"] for c in s["candidates"]}
    assert "Hot WR" in adds, "the healthy twin still shows"
    assert "Hurt WR" not in adds, "Thornton, 2026-10-06: OUT on the wire is not an add"


def test_a_backup_qb_is_priced_on_the_weeks_he_starts():
    # 2026-10-11: Rodgers for Deshaun Watson bannered at +20.6 over 9 weeks; a backup starts about 2
    ros = roster() + [r("Bench QB", "QB", 20, 12.0, 200.0)]
    out = swap_scan.scan(5, ros, pool(), position_max={"QB": 4}, backup_weeks={"QB": 2})
    qb = {s["drop"]: s for s in out["swaps"]}["Bench QB"]
    # two starter byes plus the measured 13% injury share (2026-10-15), in horizon units
    want = round(2 + swap_scan.BACKUP_START_REG * 9 + swap_scan.BACKUP_START_PO * swap_scan.PLAYOFF_UNITS, 1)
    assert qb["weeks"] == want and out["remaining_weeks"] == 9
    free = next(c for c in qb["candidates"] if c["add"] == "Free QB")
    # priced on the backup's weeks, not the season: a fraction of the full-horizon gap
    full = (free["add_rate"] - qb["drop_rate"]) * out["horizon"]
    assert free["gain"] == pytest.approx((free["add_rate"] - qb["drop_rate"]) * want, abs=0.2)
    assert free["gain"] < full / 3, "a backup upgrade is priced on the weeks he starts"
    assert out["horizon"] == 9 + swap_scan.PLAYOFF_UNITS
    assert {s["drop"]: s for s in out["swaps"]}["Bench WR"]["weeks"] == out["horizon"], "skill drops keep the full horizon"


def test_the_gate_does_not_choke_in_the_last_regular_season_weeks():
    """2026-10-14: the value stopped at week 14, so by week 13 a swap needed +20
    a game to clear +20. The playoff weeks are where the roster's value is, so
    the horizon counts them and the gate is per game: the planted +6 a game
    still passes in week 13, and a swap under the gate (1.0 a game since the
    2026-10-15 backtest) still does not."""
    small = r("Small WR", "WR", 20, 6.5, 108.0)   # about +0.5 a game over the bench WR
    out = swap_scan.scan(13, roster(), [*pool(), small], position_max={"WR": 8, "TE": 3, "QB": 4})
    cands = {c["add"]: c for c in {s["drop"]: s for s in out["swaps"]}["Bench WR"]["candidates"]}
    assert out["remaining_weeks"] == 1 and out["horizon"] > 20
    assert cands["Hot WR"]["gain"] >= out["gate"], "a real upgrade in week 13 must still clear"
    assert cands["Small WR"]["gain"] < out["gate"], "a swap under the per-game gate fails at any horizon"


def test_playoff_units_come_from_a_fresh_leverage_run(tmp_path):
    cache = tmp_path / "leverage.json"
    assert swap_scan.playoff_units_cached(cache) == swap_scan.PLAYOFF_UNITS, "no file: the default"
    cache.write_text('{"weight": {"13": 0.9, "14": 1.0, "15": 1.5, "16": 8.0, "17": 9.5}}')
    assert swap_scan.playoff_units_cached(cache) == 19.0
    stale = cache.stat().st_mtime + swap_scan.LEVERAGE_MAX_AGE + 60
    assert swap_scan.playoff_units_cached(cache, now=stale) == swap_scan.PLAYOFF_UNITS, "a stale run is ignored"
