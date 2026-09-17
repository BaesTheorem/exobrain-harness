"""Tests for fantasy/forecast.py, the weekly prediction-and-review loop.

The load-bearing checks are the ones whose failure mode is a quiet pass: a
forecast whose 50% interval is not inside its 90% cannot be filed; a forecast
missing a rostered player cannot be filed; and the scorer must place an actual
below, inside the 50, inside the 90, or above with no gaps. The standings
order must match ESPN's (win percentage, then points for) or every rank
forecast settles against the wrong number. No network anywhere here.
"""

from conftest import load_script

fc = load_script("fantasy/forecast.py")


def test_keys_merge_sources_by_name_and_position():
    assert fc.key_for("Ja'Marr Chase", "WR") == fc.key_for("JaMarr Chase", "WR")
    assert fc.key_for("Chris Godwin Jr.", "WR") == fc.key_for("Chris Godwin", "WR")
    assert fc.key_for("Kansas City Chiefs", "D/ST") == fc.key_for("", "D/ST", dst_nick="chiefs")
    assert fc.key_for("Josh Allen", "QB") != fc.key_for("Josh Allen", "WR")


def test_rank_teams_is_win_pct_then_points_for():
    teams = [
        {"team": "a", "w": 1, "l": 1, "pf": 300.0},
        {"team": "b", "w": 2, "l": 0, "pf": 200.0},
        {"team": "c", "w": 1, "l": 0, "pf": 100.0},   # idle once: 1.000 pct, low PF
        {"team": "d", "w": 2, "l": 0, "pf": 250.0},
    ]
    assert [t["team"] for t in fc.rank_teams(teams)] == ["d", "b", "c", "a"]


def test_place_covers_the_whole_line():
    p50, p90 = [10.0, 14.0], [6.0, 20.0]
    assert fc.place(12.0, p50, p90) == "in50"
    assert fc.place(10.0, p50, p90) == "in50"
    assert fc.place(7.0, p50, p90) == "in90"
    assert fc.place(20.0, p50, p90) == "in90"
    assert fc.place(5.9, p50, p90) == "below"
    assert fc.place(25.0, p50, p90) == "above"


def test_interval_ok_requires_nesting():
    assert fc.interval_ok([10, 14], [6, 20])
    assert fc.interval_ok([10, 10], [6, 20])          # a point 50 inside a real 90 is allowed
    assert not fc.interval_ok([5, 14], [6, 20])       # 50 pokes out below
    assert not fc.interval_ok([10, 21], [6, 20])      # 50 pokes out above
    assert not fc.interval_ok([14, 10], [6, 20])      # reversed
    assert not fc.interval_ok([10, 10], [10, 10])     # cannot fail, so not a prediction
    assert not fc.interval_ok([10], [6, 20])


def good_forecast():
    return {
        "week": 2,
        "players": [
            {"name": "Ja'Marr Chase", "p50": [14, 24], "p90": [6, 34], "median": 18.5, "why": "volume"},
            {"name": "Rams D/ST", "p50": [3, 9], "p90": [-2, 16], "median": 6, "why": "streamer"},
        ],
        "team_total": {"p50": [112, 136], "p90": [95, 155], "median": 124, "why": "sum"},
        "opp_total": {"p50": [98, 122], "p90": [80, 142], "median": 110, "why": "sum"},
        "win_prob": 0.7,
        "standing": {"p50": [1, 2], "p90": [1, 4], "p_first": 0.5, "p_top2": 0.75, "why": "PF lead"},
    }


ROSTER = ["Ja'Marr Chase", "Rams D/ST"]


def test_validate_accepts_a_complete_forecast():
    assert fc.validate_forecast(good_forecast(), ROSTER) == []


def test_validate_rejects_missing_player_bad_nesting_and_certainty():
    f = good_forecast()
    f["players"].pop()                                  # Rams missing
    f["players"][0]["p90"] = [8, 34]                    # 50 lo (14) is fine, but make 90 lo above 50 lo? 8 < 14 ok; break it:
    f["players"][0]["p50"] = [7, 24]                    # now 50 pokes below the 90
    f["win_prob"] = 1.0
    errs = fc.validate_forecast(f, ROSTER)
    joined = "\n".join(errs)
    assert "without a forecast" in joined
    assert "intervals must satisfy" in joined
    assert "win_prob" in joined


def test_validate_rejects_a_player_not_on_the_roster_and_no_why():
    f = good_forecast()
    f["players"][0]["name"] = "Puka Nacua"
    f["players"][1]["why"] = ""
    errs = fc.validate_forecast(f, ROSTER)
    assert any("not on the roster" in e for e in errs)
    assert any("needs a 'why'" in e for e in errs)


def test_score_interval_reports_error_against_the_median():
    sc = fc.score_interval(21.0, [14, 24], [6, 34], 18.5)
    assert sc["where"] == "in50" and sc["in50"] and sc["in90"]
    assert sc["error"] == 2.5
    assert sc["width50"] == 10.0 and sc["width90"] == 28.0


def test_coverage_counts_both_forecasters():
    settled = {"settled": {
        "players": [
            {"name": "a", "mist": fc.score_interval(10, [8, 12], [5, 15], 10), "baseline": fc.score_interval(10, [12, 14], [11, 15], 13)},
            {"name": "b", "mist": fc.score_interval(20, [8, 12], [5, 15], 10)},
            {"name": "gone", "unsettled": "dropped"},
        ],
        "team_total": {"mist": fc.score_interval(120, [110, 130], [100, 140], 120), "baseline": fc.score_interval(120, [100, 110], [95, 125], 105)},
        "opp_total": {"mist": fc.score_interval(100, [110, 130], [100, 140], 120), "baseline": None},
    }}
    c = fc.coverage([settled])
    assert c["mist"]["n"] == 4
    assert c["mist"]["cov50"] == 0.5          # a and team_total inside the 50
    assert c["mist"]["cov90"] == 0.75         # plus opp_total on the 90 edge; b is above
    assert c["baseline"]["n"] == 2
    assert c["baseline"]["cov50"] == 0.0
    assert c["baseline"]["cov90"] == 0.5


def test_quantiles_are_monotone_and_prior_has_mean_one():
    q = fc.quantiles([float(x) for x in range(1, 101)])
    assert q["q05"] <= q["q25"] <= q["q50"] <= q["q75"] <= q["q95"]
    xs = fc.prior_samples("WR", n=4000)
    assert 0.9 < sum(xs) / len(xs) < 1.1
    assert fc.ratio_samples("WR", {"WR": [1.0] * 10}) is not None   # too few samples -> prior, not the 10
    assert len(fc.ratio_samples("WR", {"WR": [1.0] * 10})) > 10
