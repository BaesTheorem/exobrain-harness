"""fantasy/bin/swap-scan: the waiver gate, with the rules that bit.

Its failure mode is quiet (no PASS looks like "nothing worth doing"), so a
planted fixture must produce a PASS, and the 2026-09-20 bug (a second tight
end offered against a wide-receiver drop) must stay dead.
"""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

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


def test_role_and_heat_are_evidence_not_gate():
    vol = {"hot wr|WR": {"flags": ["ROLE-UP"], "last": {"snap": 0.9, "tgt_share": 0.25, "opps": 9.0}}}
    out = swap_scan.scan(2, roster(), pool(), {}, heat={"meh wr|WR": 5000}, volume=vol)
    cands = {c["add"]: c for s in out["swaps"] for c in s["candidates"]}
    assert cands["Hot WR"]["role"] is True and cands["Hot WR"]["flags"] == ["ROLE-UP"]
    assert cands["Meh WR"]["heat"] == 5000 and cands["Meh WR"]["gain"] < out["gate"], "heat never moves the gate"
