"""fantasy/espncli/value.py: the shared currency and the variance rule as a number.

The variance rule's failure mode is silent (a projection-only fill looks
identical to a win-probability fill until the week ends), so every rule is
tested in both directions with planted lineups: a favorite must prefer the
floor and an underdog the ceiling, at equal projection.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fantasy"))

from espncli import value  # noqa: E402


def row(pid, name, pos, slot_id, proj, actual=None, status="", opp="KC", eligible=None):
    default = {"QB": [0], "RB": [2, 23], "WR": [4, 23], "TE": [6, 23], "K": [17], "D/ST": [16]}
    return {"id": pid, "name": name, "pos": pos, "slotId": slot_id, "slot": {0: "QB", 2: "RB", 4: "WR", 6: "TE", 23: "FLEX", 20: "BE"}[slot_id],
            "proj": proj, "actual": actual, "status": status, "opp": opp, "eligible": eligible or default[pos] + [20, 21]}


def test_ros_rate_blends_prior_and_weekly_before_week_5_and_ppg_after():
    assert value.ros_rate(2, proj=10.0, season_proj=170.0) == pytest.approx(10.0)
    assert value.ros_rate(2, proj=20.0, season_proj=170.0) == pytest.approx(15.0)
    assert value.ros_rate(2, proj=0.0, season_proj=170.0) == pytest.approx(10.0), "a bye week is the prior, not half"
    assert value.ros_rate(6, proj=99.0, season_proj=170.0, season_actual=60.0, games=5) == pytest.approx(11.0)
    assert value.ros_rate(2, proj=7.0, season_proj=None) == 7.0


def test_games_played_counts_weeks_with_a_game():
    assert value.games_played({"1": [{}], "2": [{}], "3": [], "4": [{}]}, 5) == 3
    assert value.games_played({"1": [{}]}, 1) == 0


def test_player_sd_is_tiered_and_floored():
    assert value.player_sd("WR", 20.0) == pytest.approx(20.0 * 0.54)
    assert value.player_sd("WR", 10.0) == pytest.approx(10.0 * 0.64)
    assert value.player_sd("WR", 1.0) == value.SD_FLOOR
    assert value.player_sd("WR", 0.0) == 0.0
    assert value.player_sd("RB", 20.0, mult=1.5) == pytest.approx(20.0 * 0.46 * 1.5)


def test_win_prob_positive_controls():
    me = [row(1, "A", "RB", 2, 20.0)]
    them = [row(2, "B", "RB", 2, 10.0)]
    assert value.win_prob(me, them)["p"] > 0.8
    assert value.win_prob(them, me)["p"] < 0.2
    # locked players are banked: no spread, and the actual replaces the projection
    me_locked = [row(1, "A", "RB", 2, 20.0, actual=3.0)]
    w = value.win_prob(me_locked, them)
    assert w["sd_me"] == 0 and w["mu_me"] == 3.0 and w["p"] < 0.5


def test_variance_rule_flips_with_the_side_at_equal_projection():
    """Same two bench options, same projection, opposite answers by side."""
    floor = row(10, "Floor Guy", "WR", 20, 12.0)
    ceiling = row(11, "Ceiling Guy", "WR", 20, 12.0)
    mults = {"floor guy|WR": 0.5, "ceiling guy|WR": 1.8}
    starter = row(3, "Incumbent", "WR", 4, 11.0)
    mine = [row(1, "QB", "QB", 0, 20.0), starter, floor, ceiling]
    favorite_opp = [row(21, "Their QB", "QB", 0, 10.0)]
    underdog_opp = [row(21, "Their QB", "QB", 0, 45.0)]

    fav = value.best_fill(mine, favorite_opp, 4, exclude=3, mults=mults)
    dog = value.best_fill(mine, underdog_opp, 4, exclude=3, mults=mults)
    assert fav["name"] == "Floor Guy", "a favorite cuts variance"
    assert dog["name"] == "Ceiling Guy", "an underdog buys it"
    # no opponent: projection decides, and a tie keeps the first max
    assert value.best_fill(mine, None, 4, exclude=3, mults=mults)["proj"] == 12.0


def test_best_swaps_never_moves_a_locked_or_unusable_player():
    mine = [row(1, "QB", "QB", 0, 20.0), row(2, "Starter", "WR", 4, 8.0, actual=4.0),
            row(3, "Open Starter", "WR", 4, 8.0), row(4, "Hot Bench", "WR", 20, 14.0),
            row(5, "Locked Bench", "WR", 20, 30.0, actual=30.0), row(6, "Out Bench", "WR", 20, 30.0, status="OUT"),
            row(7, "Bye Bench", "WR", 20, 30.0, opp="BYE")]
    opp = [row(21, "Their QB", "QB", 0, 30.0)]
    swaps = value.best_swaps(mine, opp)
    assert swaps, "a 14-point bench WR over an 8-point starter must register"
    assert {(s["bench"], s["starter"]) for s in swaps} == {("Hot Bench", "Open Starter")}
    assert swaps[0]["d_proj"] == 6.0 and swaps[0]["p_after"] > swaps[0]["p_before"]


def test_sd_multipliers_missing_file_is_empty(tmp_path):
    assert value.load_sd_multipliers(tmp_path / "nope.json") == {}
    (tmp_path / "sd.json").write_text('{"mult": {"a b|WR": 1.4}}')
    assert value.load_sd_multipliers(tmp_path / "sd.json") == {"a b|WR": 1.4}
