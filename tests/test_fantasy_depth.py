"""espncli/depth.py: the roster's worth in weeks 16-17 once starters go missing.

The model decides which held swaps reach Alex as a banner, so both directions
are pinned: a swap high in the chain must be worth far more than one at the
bottom, and every case the model does not cover must come back None (which
means "decide as before"), never zero. No network: rosters are planted.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fantasy"))

from espncli import depth  # noqa: E402

WIRE = {"QB": 13.0, "RB": 7.5, "WR": 8.8, "TE": 8.5}
RATES = {16: {"QB": 0.154, "RB": 0.162, "WR": 0.144, "TE": 0.185}, 17: {"QB": 0.222, "RB": 0.203, "WR": 0.147, "TE": 0.203}}
NONE_OUT = {w: dict.fromkeys(("QB", "RB", "WR", "TE"), 0.0) for w in (16, 17)}
PER_POINT = {16: 0.0045, 17: 0.0051}
ROSTER = [("QB1", "QB", 19.0), ("RB1", "RB", 25.0), ("RB2", "RB", 14.0), ("RB3", "RB", 11.5), ("RB4", "RB", 7.6),
          ("WR1", "WR", 22.5), ("WR2", "WR", 17.0), ("WR3", "WR", 10.6), ("WR4", "WR", 9.8), ("WR5", "WR", 9.0),
          ("WR6", "WR", 8.9), ("TE1", "TE", 15.0)]
SIMS = 40_000


def test_best_lineup_fills_from_the_bench_then_the_wire():
    assert depth.best_lineup(ROSTER, WIRE) == pytest.approx(19 + 25 + 14 + 22.5 + 17 + 15 + 11.5)
    no_te = [x for x in ROSTER if x[0] != "TE1"]
    assert depth.best_lineup(ROSTER, WIRE) - depth.best_lineup(no_te, WIRE) == pytest.approx(15 - 8.5), "the wire's TE"
    no_rb1 = [x for x in ROSTER if x[0] != "RB1"]
    assert depth.best_lineup(ROSTER, WIRE) - depth.best_lineup(no_rb1, WIRE) == pytest.approx(25 - 10.6), "RB3 to RB, WR3 to FLEX"


def test_with_nobody_missing_the_expected_lineup_is_the_full_one():
    ev = depth.final_weeks(ROSTER, WIRE, NONE_OUT, sims=2_000)
    assert ev[16] == pytest.approx(depth.best_lineup(ROSTER, WIRE)) and ev[17] == ev[16]
    with_absences = depth.final_weeks(ROSTER, WIRE, RATES, sims=SIMS)
    assert with_absences[16] < ev[16] - 5 and with_absences[17] < with_absences[16], "week 17 misses more"


def test_a_point_is_worth_less_at_each_place_down_the_chain():
    out = depth.tree(ROSTER, WIRE, RATES, PER_POINT, sims=SIMS)
    place = {r["place"]: r["title_per_point"] for r in out["one_more_point"]}
    assert place["starter"] > place["bench 1"] > place["bench 2"] > place["bench 3"] >= 0
    assert place["bench 1"] > 0.4 and place["bench 3"] < 0.15, "about 0.55 and 0.08 on the 2026-11-11 roster"
    assert out["failure_modes"][0]["player"] == "RB1", "the best player with the worst cover costs most"


def test_a_swap_is_priced_by_the_place_the_add_takes():
    def value(drop, add):
        return depth.swap_value(ROSTER, WIRE, RATES, PER_POINT, drop, add, sims=SIMS)
    bottom = value("WR6", ("Wire WR", "WR", 9.4))            # he lands at the fourth place
    top = value("WR6", ("Good WR", "WR", 13.0))              # he starts at FLEX
    assert 0 <= bottom < 0.15 and top > 1.0 and top > 10 * bottom
    assert value("WR6", ("Same", "WR", 8.9)) == pytest.approx(0.0, abs=1e-9), "the same player again moves nothing"
    assert value("WR3", ("Worse", "WR", 8.9)) < 0, "a worse first replacement costs"
    with pytest.raises(ValueError, match="not on the roster"):
        value("Nobody", ("X", "WR", 9.0))


def leverage(tmp_path, playoffs=0.999, age=0.0):
    f = tmp_path / "leverage.json"
    f.write_text(json.dumps({"base": {"playoffs": playoffs}, "playoff_per_point": {"15": 0.0001, "16": 0.0045, "17": 0.0051}}))
    if age:
        old = time.time() - age
        os.utime(f, (old, old))
    return f


def rates_file(tmp_path):
    f = tmp_path / "rates.json"
    f.write_text(json.dumps({"by_pos": {p: {str(w): {"miss": RATES[w][p]} for w in (16, 17)} for p in RATES[16]}}))
    return f


def test_swap_title_value_prices_a_chain_swap_and_returns_none_for_what_it_does_not_cover(tmp_path):
    kw = {"inputs": (ROSTER, WIRE), "rates_file": rates_file(tmp_path)}
    good = depth.swap_title_value("WR6", ("Good WR", "WR", 13.0), "WR", leverage_file=leverage(tmp_path), **kw)
    assert good is not None and good > 1.0, "the control: a real upgrade is priced, and priced high"
    low = depth.swap_title_value("WR6", ("Wire RB", "RB", 9.4), "WR", leverage_file=leverage(tmp_path), **kw)
    assert low is not None and low < 0.25
    none = [
        depth.swap_title_value("WR6", ("Kicker", "K", 10.0), "WR", leverage_file=leverage(tmp_path), **kw),
        depth.swap_title_value("TE1", ("Good WR", "WR", 13.0), "TE", leverage_file=leverage(tmp_path), **kw),
        depth.swap_title_value("TE1", ("Good WR", "WR", 13.0), None, leverage_file=leverage(tmp_path), **kw),
        depth.swap_title_value("WR6", ("Good WR", "WR", 13.0), "WR", leverage_file=leverage(tmp_path, playoffs=0.93), **kw),
        depth.swap_title_value("WR6", ("Good WR", "WR", 13.0), "WR", leverage_file=leverage(tmp_path, age=9 * 86400), **kw),
        depth.swap_title_value("WR6", ("Good WR", "WR", 13.0), "WR", leverage_file=tmp_path / "missing.json", **kw),
        depth.swap_title_value("WR6", ("Good WR", "WR", 13.0), "WR", leverage_file=leverage(tmp_path),
                               inputs=(ROSTER, WIRE), rates_file=tmp_path / "missing-rates.json"),
    ]
    assert none == [None] * 7, "a kicker, a TE drop (named or found), an unsafe berth, an old file, no file, no rates"
