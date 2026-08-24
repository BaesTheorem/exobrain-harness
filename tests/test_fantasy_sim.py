"""Tests for fantasy/sim.py and the shared pieces of the draft stack.

The draft-legality test is the load-bearing one: an illegal roster from any
seat (no kicker, three quarterbacks, an unfilled RB slot) is exactly the class
of bug that shipped twice as a quiet zero. The floor test pins today's
unclamped-floor rule so a refactor cannot silently restore the clamp.

sim.run() needs vor.json, which is gitignored derived data; those tests skip
on a clone that has not built a board.
"""

import pytest
from conftest import REPO, load_script

sim = load_script("fantasy/sim.py")
grade = load_script("fantasy/draftbot/grade.py")

HAVE_BOARD = (REPO / "fantasy" / "draftbot" / "vor.json").exists()


def test_snake_order_shape():
    order = sim.snake_order()
    assert len(order) == sim.TEAMS * sim.ROUNDS
    for seat in range(1, sim.TEAMS + 1):
        assert order.count(seat) == sim.ROUNDS
    # Round 1 ascends, round 2 descends: the wheel picks back to back.
    assert order[sim.TEAMS - 1] == sim.TEAMS
    assert order[sim.TEAMS] == sim.TEAMS


def test_next_pick_skips_back_to_back():
    order = sim.snake_order()
    # Seat 13's first pick (index 12) is followed immediately by its own
    # second pick. The horizon must reach past both to pick 3 (index 51-ish),
    # not stop at the adjacent own pick.
    nxt = sim.my_next_pick(order, 12)
    assert nxt is not None and order[nxt] == 13
    assert nxt > 13, "horizon stopped at the back-to-back pick"
    # A middle seat's next pick is simply its slot in the next round.
    nxt = sim.my_next_pick(order, 6)  # seat 7, round 1
    assert nxt is not None and order[nxt] == 7 and 13 <= nxt < 26


def mk(name, pos, proj, bye=9):
    return {"name": name, "pos": pos, "proj": proj, "bye": bye}


def test_lineup_points_fills_slots_and_flex():
    roster = [
        mk("QB1", "QB", 300), mk("QB2", "QB", 290),
        mk("RB1", "RB", 250), mk("RB2", "RB", 200), mk("RB3", "RB", 150),
        mk("WR1", "WR", 240), mk("WR2", "WR", 230), mk("WR3", "WR", 160),
        mk("TE1", "TE", 140),
        mk("K1", "K", 130), mk("D1", "D/ST", 100),
    ]
    # Starters: QB1 RB1 RB2 WR1 WR2 TE1 K1 D1 + best flex (WR3 160 > RB3 150)
    assert sim.lineup_points(roster) == pytest.approx(
        300 + 250 + 200 + 240 + 230 + 140 + 130 + 100 + 160
    )
    # Depth term adds the best bench RB and the best bench WR/TE, discounted.
    # Bench after starters: QB2, RB3. Best bench RB = RB3; no WR/TE left.
    assert sim.lineup_points(roster, 0.25) == pytest.approx(
        1750 + 0.25 * 150
    )


def test_floor_is_unclamped():
    """A drained position's negative floor must count, not clamp to zero.

    Two equal-VOR players; WR's best survivor is far below replacement while
    RB's survivor is at replacement. The unclamped rule takes the WR (passing
    costs more there). The clamped rule saw both floors as 0 and fell to the
    raw-VOR tiebreak, a coin flip this test would not catch.
    """
    order = sim.snake_order()
    avail = [
        {"name": "RB now", "pos": "RB", "vor": 20.0, "adp": 5.0, "bye": 9,
         "proj": 190.0, "espnRank": 50},
        {"name": "WR now", "pos": "WR", "vor": 20.0, "adp": 5.0, "bye": 9,
         "proj": 210.0, "espnRank": 51},
        {"name": "RB later", "pos": "RB", "vor": 0.0, "adp": 999.0, "bye": 9,
         "proj": 170.0, "espnRank": 150},
        {"name": "WR later", "pos": "WR", "vor": -40.0, "adp": 999.0, "bye": 9,
         "proj": 150.0, "espnRank": 151},
    ]
    pick = sim.bot_pick(avail, [], order, 0, {"freeByeBonus": 0,
                                              "byeStackPenalty": 0})
    assert pick["name"] == "WR now"


@pytest.mark.skipif(not HAVE_BOARD, reason="vor.json not built on this clone")
def test_every_seat_drafts_a_legal_roster():
    for seat in (1, 7, 13):
        for model in ("auto", "human"):
            _, _, roster = sim.run(seat, {}, seed=3, model=model)
            counts: dict[str, int] = {}
            for p in roster:
                counts[p["pos"]] = counts.get(p["pos"], 0) + 1
            assert len(roster) == sim.ROUNDS, (seat, model)
            assert counts.get("QB", 0) == 1, (seat, model, counts)
            assert counts.get("K", 0) == 1, (seat, model, counts)
            assert counts.get("D/ST", 0) == 1, (seat, model, counts)
            assert counts.get("RB", 0) >= 2, (seat, model, counts)
            assert counts.get("TE", 0) >= 1, (seat, model, counts)


def test_grade_norm_handles_punctuation_and_suffixes():
    n = grade.norm
    assert n("Ka'imi Fairbairn") == n("Ka’imi Fairbairn")
    assert n("Brian Thomas Jr.") == n("Brian Thomas")
    assert n("Kenneth Walker III") == n("Kenneth Walker")
    assert n("A.J. Brown") == n("AJ Brown")
