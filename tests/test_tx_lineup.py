"""The write lane's lineup moves: several moves in one transaction, the route
through FLEX, and the exchange of two starters' slots (2026-11-11).

A fake league applies each posted transaction the way ESPN does: the whole
transaction or nothing, and a player only into a slot he can play. No network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fantasy"))

from espncli.client import BENCH, EspnError  # noqa: E402
from espncli.tx import FLEX, EspnWriter  # noqa: E402

RB_SLOT, WR_SLOT = 2, 4
RB = [RB_SLOT, FLEX, BENCH]
WR = [WR_SLOT, FLEX, BENCH]
TOP_RB, OUT_RB, FLEX_RB, WR_A, WR_B, BENCH_WR, BENCH_RB = 1, 2, 3, 4, 5, 6, 7


class FakeApi:
    season, league_id = 2026, 1
    creds = {"team_id": 12, "SWID": "{ME}"}

    def __init__(self, flex_pos=RB):
        self.slots = {TOP_RB: RB_SLOT, OUT_RB: RB_SLOT, FLEX_RB: FLEX, WR_A: WR_SLOT, WR_B: WR_SLOT,
                      BENCH_WR: BENCH, BENCH_RB: BENCH}
        self.eligible = {TOP_RB: RB, OUT_RB: RB, FLEX_RB: flex_pos, WR_A: WR, WR_B: WR, BENCH_WR: WR, BENCH_RB: RB}

    def league(self, *views, period=None, **kw):
        return {"scoringPeriodId": 10}

    def roster_entries(self, data, team_id):
        return [{"playerId": p, "lineupSlotId": s, "playerPoolEntry": {"player": {"eligibleSlots": self.eligible[p]}}}
                for p, s in self.slots.items()]


class Writer(EspnWriter):
    """`_post` is the network. This one applies a legal transaction to the fake roster."""

    def __init__(self, api, accept=True):
        super().__init__(api)
        self.bodies, self.accept = [], accept

    def _post(self, body, path="/transactions/"):
        self.bodies.append(body)
        if not self.accept:
            return {}
        after = dict(self.api.slots)
        for it in body["items"]:
            if it["toLineupSlotId"] not in self.api.eligible[it["playerId"]]:
                raise EspnError("ESPN HTTP 409: the player cannot play that slot")
            after[it["playerId"]] = it["toLineupSlotId"]
        self.api.slots = after
        return {"status": "EXECUTED"}


def items(body):
    return [(i["playerId"], i["fromLineupSlotId"], i["toLineupSlotId"]) for i in body["items"]]


def test_a_direct_swap_is_two_moves_in_one_transaction():
    w = Writer(FakeApi())
    res = w.swap(BENCH_RB, OUT_RB)
    assert len(w.bodies) == 1 and w.bodies[0]["type"] == "ROSTER"
    assert items(w.bodies[0]) == [(OUT_RB, RB_SLOT, BENCH), (BENCH_RB, BENCH, RB_SLOT)]
    assert res["verified"] and res["slot"] == "RB" and res["via"] is None


def test_a_bench_wr_replaces_an_rb_through_flex_in_one_transaction():
    w = Writer(FakeApi())
    res = w.swap(BENCH_WR, OUT_RB)
    assert len(w.bodies) == 1, "three moves that travel together"
    assert items(w.bodies[0]) == [(OUT_RB, RB_SLOT, BENCH), (FLEX_RB, FLEX, RB_SLOT), (BENCH_WR, BENCH, FLEX)]
    assert res["verified"] and res["slot"] == "FLEX" and res["via"] == FLEX_RB
    assert w.api.slots[FLEX_RB] == RB_SLOT and w.api.slots[BENCH_WR] == FLEX and w.api.slots[OUT_RB] == BENCH


def test_with_no_route_the_direct_swap_is_sent_and_espn_refuses_it():
    w = Writer(FakeApi(flex_pos=WR))                    # a WR in FLEX cannot take the RB slot
    assert w.flex_route(BENCH_WR, OUT_RB) is None
    with pytest.raises(EspnError, match="cannot play that slot"):
        w.swap(BENCH_WR, OUT_RB)
    assert w.api.slots[OUT_RB] == RB_SLOT, "nothing moved"


def test_a_swap_that_the_read_back_does_not_show_is_not_verified():
    w = Writer(FakeApi(), accept=False)
    assert w.swap(BENCH_WR, OUT_RB)["verified"] is False


def test_exchange_trades_two_starters_slots_and_refuses_the_rest():
    w = Writer(FakeApi())
    res = w.exchange(TOP_RB, FLEX_RB)
    assert items(w.bodies[0]) == [(TOP_RB, RB_SLOT, FLEX), (FLEX_RB, FLEX, RB_SLOT)]
    assert res["verified"] and w.api.slots[TOP_RB] == FLEX and w.api.slots[FLEX_RB] == RB_SLOT
    with pytest.raises(EspnError, match="two starters"):
        w.exchange(TOP_RB, BENCH_RB)
    with pytest.raises(EspnError, match="other's slot"):
        w.exchange(WR_A, OUT_RB)                        # a WR cannot play the RB slot
    assert len(w.bodies) == 1, "a refused exchange posts nothing"


def test_the_swap_guards_still_hold():
    w = Writer(FakeApi())
    with pytest.raises(EspnError, match="must be on the bench"):
        w.swap(WR_A, OUT_RB)
    with pytest.raises(EspnError, match="on the roster"):
        w.swap(99, OUT_RB)
    assert w.swap(BENCH_WR, OUT_RB, dry_run=True)["dry_run"]["items"][1]["playerId"] == FLEX_RB
    assert not w.bodies, "a dry run posts nothing"
