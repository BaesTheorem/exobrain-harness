"""Tests for fantasy/ffmodel: league scoring, prop-line parsing, the
correlation lookup, the correlated win probability, and the proper scores.

Every fixture is planted; nothing here touches the network."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fantasy"))

from espncli import value  # noqa: E402
from ffmodel import corr, market, nflraw, props, score  # noqa: E402

# ---- league scoring (positive controls taken from ESPN's own 2026 totals) ----


def test_offense_points_full_ppr_four_point_passing_td():
    wr = {"receptions": 7, "receiving_yards": 85, "receiving_tds": 1}
    assert nflraw.offense_points(wr) == 21.5
    qb = {"passing_yards": 250, "passing_tds": 2, "passing_interceptions": 1, "rushing_yards": 30,
          "fumbles_lost": 1}
    assert nflraw.offense_points(qb) == round(10 + 8 - 2 + 3 - 2, 2)


def test_kicker_points_by_distance_and_misses():
    k = {"fg_made_30_39": 2, "fg_made_40_49": 1, "fg_made_50_59": 1, "fg_missed_total": 1, "pat_made": 3}
    assert nflraw.offense_points(k) == 6 + 4 + 5 - 1 + 3


def test_dst_points_match_espn_week1_chiefs():
    # ESPN 2026 week 1, Chiefs D/ST: 10 allowed, 176 yards, 4 sacks, 1 INT, 1 FR = 14.0
    row = {"pa": 10, "ya": 176, "def_sacks": 4, "def_interceptions": 1, "fumble_recovery_opp": 1}
    assert nflraw.dst_points(row) == 14.0


def test_dst_bracket_edges():
    pa = {0: 5, 1: 4, 6: 4, 7: 3, 13: 3, 14: 1, 17: 1, 18: 0, 27: 0, 28: -1, 34: -1, 35: -3, 45: -3, 46: -5}
    for v, want in pa.items():
        assert nflraw.bracket(v, nflraw.PA_BRACKETS) == want, v
    ya = {99: 5, 100: 3, 199: 3, 200: 2, 299: 2, 300: 0, 349: 0, 350: -1, 449: -3, 450: -5, 549: -6, 550: -7}
    for v, want in ya.items():
        assert nflraw.bracket(v, nflraw.YA_BRACKETS) == want, v


# ---- prop lines -----------------------------------------------------------------


def _item(line, over=None, under=None):
    return {"cl": line, "co": over, "cu": under, "ol": line, "oo": over, "ou": under}


def test_main_line_prefers_the_priced_target_over_the_ladder():
    items = [_item(216.5, over=1.87), _item(274.5), _item(216.5, under=1.87), _item(149.5), _item(349.5)]
    line, p = props.main_line(items, "c")
    assert line == 216.5
    assert p is not None and abs(p - 0.5) < 1e-9


def test_main_line_without_prices():
    assert props.main_line([_item(54.5), _item(54.5)], "c") == (54.5, None)
    assert props.main_line([_item(3.5)], "c") == (3.5, None)
    # two different lone targets and no prices: no way to tell which is the main line
    assert props.main_line([_item(3.5), _item(4.5)], "c") == (None, None)


def test_devig_removes_the_margin():
    p = props.devig(1.5263, 2.4)       # -190 / +140
    assert p is not None and 0.6 < p < 0.62
    assert props.devig(None, 2.0) is None


# ---- correlations ---------------------------------------------------------------

TABLE = {"same:QB|WR1": 0.38, "opp:D/ST|QB": -0.48}


def test_pair_key_relations():
    qb = {"pos": "QB", "proj": 20, "team": "BUF", "opp": "@MIA"}
    wr = {"pos": "WR", "proj": 15, "team": "BUF", "opp": "@MIA"}
    dst = {"pos": "D/ST", "proj": 7, "team": "MIA", "opp": "BUF"}
    other = {"pos": "WR", "proj": 15, "team": "KC", "opp": "DEN"}
    assert corr.pair_key(qb, wr) == "same:QB|WR1"
    assert corr.pair_key(dst, qb) == "opp:D/ST|QB"
    assert corr.pair_key(qb, other) is None
    assert corr.rho(qb, wr, TABLE) == 0.38
    assert corr.rho(qb, other, TABLE) == 0.0


def _row(pid, pos, proj, team, opp, slot=0):
    return {"id": pid, "name": f"p{pid}", "pos": pos, "proj": proj, "team": team, "opp": opp,
            "slotId": slot, "actual": None, "eligible": [slot]}


def test_independent_win_prob_is_unchanged_without_a_table():
    me = [_row(1, "QB", 20, "BUF", "@MIA"), _row(2, "WR", 15, "BUF", "@MIA", 4)]
    them = [_row(3, "QB", 18, "KC", "DEN")]
    assert value.win_prob(me, them) == value.win_prob(me, them, corr={})


def test_a_stack_widens_our_spread_and_a_dst_against_their_qb_widens_the_margin():
    me = [_row(1, "QB", 20, "BUF", "@MIA"), _row(2, "WR", 15, "BUF", "@MIA", 4),
          _row(5, "D/ST", 7, "KC", "DEN", 16)]
    them = [_row(3, "QB", 18, "DEN", "@KC")]
    ind = value.win_prob(me, them)
    cor = value.win_prob(me, them, corr=TABLE)
    assert cor["sd_me"] > ind["sd_me"]            # QB + his own WR1 move together
    assert cor["sd_diff"] > ind["sd_diff"]        # our D/ST against their QB moves apart from him
    assert cor["mu_me"] == ind["mu_me"]           # correlation never moves a mean


# ---- proper scores --------------------------------------------------------------


def test_interval_and_weighted_interval_scores():
    assert score.interval_score(10, 5, 15, 0.5) == 10
    assert score.interval_score(20, 5, 15, 0.1) == 10 + 2 / 0.1 * 5
    w = score.wis(10, 10, [(0.5, 5, 15), (0.1, 0, 25)])
    assert math.isclose(w, (0 + 0.25 * 10 + 0.05 * 25) / 2.5)


def test_pit_bins_and_log_score():
    p90, p50 = [0, 30], [5, 20]
    assert [score.pit_bin(x, p90, p50, 12) for x in (-1, 2, 8, 15, 25, 31)] == [0, 1, 2, 3, 4, 5]
    assert math.isclose(score.log_score(0.8, True), -math.log(0.8))
    assert math.isclose(score.log_score(0.8, False), -math.log(0.2))


# ---- market ----------------------------------------------------------------------


def _model(pos, coef, fills=None):
    return {"coef": {pos: coef}, "fills": fills or {}}


def test_market_needs_a_core_line():
    model = _model("WR", [1.0, 0.0, 0.0, 0.0])
    assert market.predict_rows([{"pos": "WR", "implied": 24}], model) == [None]
    # a receiving line alone cannot build receptions without a learned fill
    assert market.predict_rows([{"pos": "WR", "implied": 24, "rec_yds": 50.5}], model) == [None]
    fills = {"WR": [{"target": "receptions", "sources": ["rec_yds"], "coef": [0.5, 0.08], "n": 100}]}
    assert market.predict_rows([{"pos": "WR", "implied": 24, "rec_yds": 50.5}], _model("WR", [1.0, 0.0, 0.0, 0.0], fills)) == [1.0]


def test_market_prediction_is_linear_in_the_core_lines():
    model = _model("TE", [0.0, 0.1, 0.2, 1.0])            # 1, implied, rec_yds, receptions
    got = market.predict_rows([{"pos": "TE", "implied": 20, "rec_yds": 40.5, "receptions": 3.5}], model)[0]
    assert got is not None and math.isclose(got, 2.0 + 8.1 + 3.5)


def test_market_rebuilds_a_quarterback_rushing_line_from_the_combined_line():
    x = market.identities({"pos": "QB", "pass_yds": 220.5, "pass_rush_yds": 250.5})
    assert math.isclose(x["rush_yds"], 30.0)
    assert x["implied"] == market.DEFAULT_IMPLIED


# ---- league-scan: the lineup a manager started against ESPN's projected best ----


def test_vs_proj_compares_the_started_lineup_with_the_projected_best():
    import importlib.machinery  # noqa: PLC0415
    import importlib.util  # noqa: PLC0415

    path = Path(__file__).resolve().parent.parent / "fantasy" / "bin" / "league-scan"
    loader = importlib.machinery.SourceFileLoader("league_scan", str(path))  # no .py suffix
    spec = importlib.util.spec_from_loader("league_scan", loader)
    assert spec is not None and spec.loader is not None
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)
    counts = {0: 1, 2: 1}
    rows = [
        {"slotId": 0, "pos": "QB", "proj": 20.0, "actual": 15.0},
        {"slotId": 20, "pos": "QB", "proj": 18.0, "actual": 30.0},     # benched, scored more
        {"slotId": 2, "pos": "RB", "proj": 8.0, "actual": 12.0},       # started over a higher projection
        {"slotId": 20, "pos": "RB", "proj": 11.0, "actual": 5.0},
        {"slotId": 21, "pos": "RB", "proj": 25.0, "actual": 40.0},     # IR never counts
    ]
    assert ls.best_by(rows, counts, "proj") == 15.0 + 5.0       # what ESPN's projections would have started
    assert ls.best_actual(rows, counts) == 30.0 + 12.0          # hindsight
