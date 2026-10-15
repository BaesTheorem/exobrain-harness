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
    # season_proj is rest-of-season: 144 over the 12 games a 5-game team has left is 12 a game.
    assert value.ros_rate(6, proj=12.0, season_proj=144.0, season_actual=60.0, games=5) == pytest.approx(12.0)
    # From week 5: 0.45 weekly projection + 0.35 prior + 0.20 PPG (backtest, 2026-10-15).
    assert value.ros_rate(6, proj=20.0, season_proj=144.0, season_actual=60.0, games=5) == pytest.approx(
        0.45 * 20 + 0.35 * 12 + 0.20 * 12)
    # A bye or OUT week (no weekly projection) is half prior, half PPG.
    assert value.ros_rate(6, proj=0.0, season_proj=144.0, season_actual=96.0, games=5) == pytest.approx(
        0.5 * 12 + 0.5 * 96 / 5)
    assert value.ros_rate(2, proj=7.0, season_proj=None) == 7.0


def test_ros_rate_divides_rest_of_season_by_games_left_not_17():
    # Josh Allen, week 6 2026: 281.1 rest-of-season with 12 games left is 23.4 a game, not 16.5.
    assert value.ros_rate(6, proj=0.0, season_proj=281.1, games=5) == pytest.approx(281.1 / 12)
    # The bye already taken (4 team games before week 6) leaves 13.
    assert value.ros_rate(6, proj=0.0, season_proj=130.0, games=4) == pytest.approx(10.0)
    # Preseason (no games yet) is the whole 17-game season, as before.
    assert value.ros_rate(1, proj=0.0, season_proj=170.0, games=0) == pytest.approx(10.0)


def test_ros_rate_ppg_skips_weeks_missed_hurt():
    # Jayden Daniels, week 6 2026: 64.66 in 3 games played of 5 team games.
    hurt = value.ros_rate(6, proj=19.9, season_proj=261.3, season_actual=64.66, games=5, played=3)
    assert hurt == pytest.approx(0.45 * 19.9 + 0.35 * 261.3 / 12 + 0.20 * 64.66 / 3)
    # Without box scores the team count is the fallback, and it is lower.
    assert value.ros_rate(6, proj=19.9, season_proj=261.3, season_actual=64.66, games=5) < hurt
    # played=0 (no row with games) falls back too, never a division by zero; a
    # zero PPG is a missing input, so the projection and the prior share its weight.
    assert value.ros_rate(6, proj=19.9, season_proj=120.0, season_actual=0.0, games=5, played=0) == pytest.approx(
        (0.45 * 19.9 + 0.35 * 10.0) / 0.80)


def test_games_played_counts_weeks_with_a_game():
    assert value.games_played({"1": [{}], "2": [{}], "3": [], "4": [{}]}, 5) == 3
    assert value.games_played({"1": [{}]}, 1) == 0


def test_games_appeared_only_when_the_feed_covers_last_week():
    rows = {"jayden daniels|QB": {"games": 3, "weeks": [{"week": 1}, {"week": 2}, {"week": 5}]},
            "nobody|WR": {"games": 0, "weeks": []}}
    assert value.games_appeared(rows, 6) == {"jayden daniels|QB": 3}
    # Week 7 needs week 6 in the feed; a feed that stops at 5 gives nothing, not a stale count.
    assert value.games_appeared(rows, 7) == {}
    assert value.games_appeared({}, 6) == {}


def test_load_volume_rows_missing_file_is_empty(tmp_path):
    assert value.load_volume_rows(2026, tmp_path / "absent.json") == {}
    f = tmp_path / "v.json"
    f.write_text('{"players": {"a|WR": {"games": 2}}}')
    assert value.load_volume_rows(2026, f) == {"a|WR": {"games": 2}}


def test_player_sd_is_tiered_and_floored():
    assert value.player_sd("WR", 20.0) == pytest.approx(20.0 * 0.55)
    assert value.player_sd("WR", 10.0) == pytest.approx(10.0 * 0.68)
    assert value.player_sd("WR", 1.0) == value.SD_FLOOR
    assert value.player_sd("WR", 0.0) == 0.0
    assert value.player_sd("RB", 20.0, mult=1.5) == pytest.approx(20.0 * 0.51 * 1.5)


def test_win_prob_positive_controls():
    me = [row(1, "A", "RB", 2, 20.0)]
    them = [row(2, "B", "RB", 2, 10.0)]
    assert value.win_prob(me, them)["p"] > 0.75
    assert value.win_prob(them, me)["p"] < 0.25
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


def test_swap_net_prices_the_projection_it_costs():
    """d_net: a variance swap that buys win probability by giving up projection
    is charged for the Points For it loses, at POINTS_PER_WIN_PCT."""
    starter = row(3, "Steady Starter", "WR", 4, 12.0)
    boom = row(10, "Boom Bench", "WR", 20, 10.0)
    mults = {"steady starter|WR": 0.5, "boom bench|WR": 2.0}
    mine = [row(1, "QB", "QB", 0, 20.0), starter, boom]
    underdog_opp = [row(21, "Their QB", "QB", 0, 60.0)]
    swaps = value.best_swaps(mine, underdog_opp, mults, min_gain=0.0)
    assert swaps, "an underdog's ceiling swap must register"
    sw = swaps[0]
    assert sw["d_proj"] == -2.0
    assert sw["d_net"] == pytest.approx(100 * sw["d_p"] - 2.0 / value.POINTS_PER_WIN_PCT, abs=0.06)
    assert sw["d_net"] < 100 * sw["d_p"], "a swap that costs projection is worth less than its win probability"


def test_swaps_rank_on_d_net_and_keep_a_points_swap_a_favorite_would_skip():
    """2026-10-15: a heavy favorite's swap that gains projection but almost no
    win probability passes d_net >= +1 and must show."""
    mine = [row(1, "QB", "QB", 0, 45.0), row(3, "Starter", "WR", 4, 8.0), row(4, "Bench", "WR", 20, 16.0)]
    opp = [row(21, "Their QB", "QB", 0, 3.0)]
    swaps = value.best_swaps(mine, opp)
    assert swaps and swaps[0]["bench"] == "Bench"
    assert swaps[0]["d_p"] < 0.005 and swaps[0]["d_net"] >= 1.0
    assert value.best_swaps(mine, opp, min_gain=0.005) == []        # the old filter hid it


def test_questionable_starter_is_a_mixture_with_the_cover_that_kicks_off_later():
    import datetime as dt
    sun, thu = dt.datetime(2026, 10, 18, 12), dt.datetime(2026, 10, 15, 19)
    q = {**row(3, "Q Starter", "WR", 4, 12.0), "p_play": 0.75, "kickoff": sun}
    late = {**row(4, "Late Cover", "WR", 20, 8.0), "kickoff": sun}
    early = {**row(5, "Early Cover", "WR", 20, 11.0), "kickoff": thu}       # locked before the inactives post
    rows = value.with_fallbacks([q, late, early])
    assert rows[0]["fallback_mean"] == 8.0
    m, _ = value.row_moments(rows[0], {})
    assert m == pytest.approx(0.75 * 12.0 + 0.25 * 8.0)
    # without a p_play the row is unchanged
    assert value.row_moments(row(6, "Healthy", "WR", 4, 12.0), {})[0] == 12.0



def test_a_rivals_questionable_starter_is_covered_at_his_fix_rate():
    """Until 2026-10-15 a rival's questionable starter counted as certain to
    play, above both real outcomes. His slot is now p x mean + (1 - p) x rate
    x cover; rate 1 is the mixture our own side has used since that morning."""
    import datetime as dt
    sun = dt.datetime(2026, 10, 18, 12)
    mine = [row(1, "QB", "QB", 0, 20.0)]
    theirs = [{**row(21, "Their Q", "WR", 4, 12.0), "p_play": 0.5, "kickoff": sun},
              {**row(22, "Their Cover", "WR", 20, 8.0), "kickoff": sun}]
    for rate, want in ((1.0, 6.0 + 4.0), (1 / 6, 6.0 + 4.0 / 6), (0.0, 6.0)):
        assert value.win_prob(mine, theirs, opp_fix_rate=rate)["mu_opp"] == pytest.approx(want, abs=0.05)
    assert value.win_prob(mine, theirs, opp_fix_rate=0.0)["p"] > value.win_prob(mine, theirs, opp_fix_rate=1.0)["p"]
    # Positive control: the same row on our side keeps the rate-1 mixture.
    assert value.win_prob(theirs, mine)["mu_me"] == pytest.approx(10.0, abs=0.05)


def test_a_rivals_bye_hole_is_priced_at_his_fix_rate_but_ours_stays_a_hole():
    mine = [row(1, "QB", "QB", 0, 20.0)]
    theirs = [row(21, "Their Bye", "WR", 4, 0.0, opp="BYE"), row(22, "Their Cover", "WR", 20, 9.0)]
    assert value.win_prob(mine, theirs, opp_fix_rate=0.5)["mu_opp"] == pytest.approx(4.5, abs=0.05)
    # Our own bye starter is not covered inside win_prob, so best_swaps shows the fix.
    ours = [row(1, "QB", "QB", 0, 20.0), row(3, "Our Bye", "WR", 4, 0.0, opp="BYE"), row(4, "Our Bench", "WR", 20, 9.0)]
    their_qb = [row(21, "Their QB", "QB", 0, 20.0)]
    assert value.win_prob(ours, their_qb)["mu_me"] == pytest.approx(20.0, abs=0.05)
    assert value.best_swaps(ours, their_qb)[0]["bench"] == "Our Bench"


def test_fix_rate_shrinks_toward_one_half():
    assert value.fix_rate(0, 0) == 0.5
    assert value.fix_rate(0, 4) == pytest.approx(1 / 6)
    assert value.fix_rate(1, 1) == pytest.approx(2 / 3)

def test_points_per_win_pct_reads_the_week_and_falls_back(tmp_path):
    f = tmp_path / "leverage.json"
    f.write_text('{"weeks": {"6": {"points_per_win_pct": 6.68}}}')
    assert value.load_points_per_win_pct(6, f) == pytest.approx(6.68)
    assert value.load_points_per_win_pct(7, f) == value.POINTS_PER_WIN_PCT
    assert value.load_points_per_win_pct(6, tmp_path / "missing.json") == value.POINTS_PER_WIN_PCT
