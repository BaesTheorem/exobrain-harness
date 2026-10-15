"""Tests for fantasy/ffmodel/fpranks: the FantasyPros weekly accuracy scorer
and the half-PPR conversions behind MIST's ranks.

The rule tests replay the worked examples on the FantasyPros methodology
page (Justice Hill, Tank Bigsby, the penalty). Every fixture is planted;
nothing here touches the network."""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fantasy"))

from ffmodel import fpranks  # noqa: E402


def _line(depth: int = 120) -> list[float]:
    """A strictly falling slot curve: slot k is worth 30 - 0.25 k."""
    return [30 - 0.25 * k for k in range(1, depth + 1)]


# ---- conversions and ranks ---------------------------------------------------------


def test_half_ppr_takes_half_a_point_per_reception():
    assert fpranks.half_ppr(21.5, 7) == 18.0
    assert fpranks.half_ppr(18.0, None) == 18.0
    assert fpranks.half_ppr(21.5, 7, ppr=1.0) == 21.5       # full PPR, the PPR-order control


def test_market_half_subtracts_half_the_receptions_line_but_not_for_a_qb():
    model = {"coef": {"WR": [1.0, 0.0, 0.1, 1.0], "QB": [0.0, 0.0, 0.04, 4.0, 0.1]}, "fills": {}}
    wr = {"season": 2026, "week": 3, "gsis_id": "W1", "pos": "WR", "implied": 24.0, "rec_yds": 60.0, "receptions": 5.0}
    qb = {"season": 2026, "week": 3, "gsis_id": "Q1", "pos": "QB", "implied": 24.0, "pass_yds": 250.0,
          "pass_td": 1.5, "rush_yds": 20.0}
    out = fpranks.market_half([wr, qb], model)
    assert out[(2026, 3, "W1")] == ("WR", 12.0 - 2.5)          # 1 + 6 + 5 full PPR, less 0.5 x 5
    assert out[(2026, 3, "Q1")] == ("QB", 10.0 + 6.0 + 2.0)    # no receptions to remove


def test_blend_is_the_mean_of_the_sources_that_have_the_player():
    b = fpranks.blend({"a": ("WR", 10.0), "b": ("WR", 6.0)}, {"a": ("WR", 14.0)}, {})
    assert b["a"] == ("WR", 12.0, 2)
    assert b["b"] == ("WR", 6.0, 1)


def test_ranks_keep_order_depth_tie_break_and_exclusions():
    proj = {"x": ("TE", 9.0), "y": ("TE", 9.0), "z": ("TE", 12.0), "q": ("QB", 20.0), "k": ("K", 8.0)}
    assert fpranks.ranks(proj, {"TE": 2, "QB": 1}) == {"TE": ["z", "x"], "QB": ["q"]}
    assert fpranks.ranks(proj, {"TE": 3}, exclude={"z"}) == {"TE": ["x", "y"]}


# ---- slot values -----------------------------------------------------------------------


def test_slot_curve_uses_full_slate_weeks_and_pads_with_zero():
    weeks = [("WR", 32, [10.0, 20.0, -1.0]), ("WR", 32, [30.0, 10.0]), ("WR", 28, [99.0, 99.0])]
    # week one sorted: 20, 10, 0, -1; week two: 30, 10, 0, 0; the bye week is skipped
    assert fpranks.slot_curve(weeks, depth=4)["WR"] == [25.0, 10.0, 0.0, -0.5]


def test_slot_value_rescales_the_rank_for_byes():
    c = {"WR": [40.0, 30.0, 20.0, 10.0, 8.0, 6.0, 4.0, 2.0]}
    assert fpranks.slot_value(c, "WR", 3) == 20.0
    assert abs(fpranks.slot_value(c, "WR", 7, teams=28) - 2.0) < 1e-9          # 7 x 32 / 28 = slot 8
    assert abs(fpranks.slot_value(c, "WR", 2, teams=30) - (30 - 10 * (64 / 30 - 2))) < 1e-9
    assert fpranks.slot_value(c, "WR", 50) == 2.0                              # past the end: last slot


# ---- the pool and the rules for players an expert left out --------------------------------


def test_pool_is_ecr_top_n_plus_actual_top_n_with_ties_at_the_cutoff():
    actual = {"a": 3.0, "e": 20.0, "f": 15.0, "g": 15.0, "b": 1.0}
    pool = fpranks.player_pool(["a", "b", "c", "d"], actual, "QB", n=2)
    assert pool == {"a": "ecr", "b": "ecr", "e": "actual", "f": "actual", "g": "actual"}


def test_unranked_pool_player_from_ecr_gets_last_plus_one():
    # "if an expert ranked 70 running backs and failed to include Justice Hill
    # in his rankings, we would slot Hill as the expert's RB #71"
    ecr = ["hill"] + [f"r{i}" for i in range(1, 80)]
    expert = [f"r{i}" for i in range(1, 71)]
    rows = fpranks.score_week({"x": expert}, ecr, {"hill": 5.0}, "RB", {"RB": _line()}, n=40)
    hill = next(r for r in rows if r["pid"] == "hill")
    assert hill["via"] == "ecr"
    assert hill["rank"]["x"] == 71


def test_unranked_actual_only_player_gets_the_worse_of_ecr_plus_one_and_last_plus_one():
    # "Tank Bigsby could have a weekly ECR of RB #57 and finish the week as
    # RB #33 ... For an expert who ranked 50 RBs and didn't include Bigsby
    # ... we slot Bigsby as their RB #58"
    ecr = [f"r{i}" for i in range(1, 57)] + ["bigsby"] + [f"s{i}" for i in range(20)]
    actual = {f"r{i}": 30.0 - 0.5 * i for i in range(1, 41)} | {"bigsby": 14.0}
    rankers = {"short": [f"r{i}" for i in range(1, 51)], "deep": ecr[:80], "short30": [f"r{i}" for i in range(1, 31)]}
    rows = fpranks.score_week(rankers, ecr, actual, "RB", {"RB": _line()}, n=40)
    b = next(r for r in rows if r["pid"] == "bigsby")
    assert b["via"] == "actual"
    assert b["rank"]["short"] == 58          # ECR 57 + 1 beats last 50 + 1
    assert b["rank"]["deep"] == 57           # he is ranked, so his own rank counts
    assert b["rank"]["short30"] == 58        # never better than ECR + 1, even for a short list


def test_penalty_only_when_worse_than_the_field_average():
    ecr = [f"r{i}" for i in range(1, 60)]
    actual = {f"r{i}": 30 - 0.25 * i for i in range(1, 60)}
    # "hurt" is outside the pool: not in ECR's top 40 and 0 points.
    a = ["hurt", *ecr[:49]]                  # ranks him 1st
    b = [*ecr[:38], "hurt", *ecr[38:49]]     # ranks him 39th, inside the top 40
    c = ecr[:50]                             # leaves him out
    rows = fpranks.score_week({"A": a, "B": b, "C": c}, ecr, actual, "RB", {"RB": _line()}, n=40)
    hurt = next(r for r in rows if r["pid"] == "hurt")
    assert hurt["pool"] is False
    gap = {"A": 30 - 0.25, "B": 30 - 0.25 * 39, "C": 30 - 0.25 * 51}
    avg = sum(gap.values()) / 3
    assert abs(hurt["loss"]["A"] - (gap["A"] - avg)) < 1e-3
    assert hurt["loss"]["B"] == 0.0          # inside the range, but better than the field
    assert hurt["loss"]["C"] == 0.0          # never ranked him inside the range


# ---- positive control ----------------------------------------------------------------------


def test_scorer_ranks_an_oracle_first_and_a_reversed_list_last():
    rng = random.Random(7)
    players = [f"p{i}" for i in range(90)]
    truth = {p: max(0.0, rng.gauss(10, 6)) for p in players}
    curve = {"WR": sorted(truth.values(), reverse=True) + [0.0] * 110}
    ecr = sorted(players, key=lambda p: -(truth[p] + rng.gauss(0, 4)))
    oracle = sorted(players, key=lambda p: -truth[p])[:60]
    rankers = {"oracle": oracle, "ecr": ecr[:60], "shuffled": rng.sample(oracle, len(oracle)),
               "reversed": oracle[::-1]}
    tot = fpranks.week_totals(fpranks.score_week(rankers, ecr, truth, "WR", curve, n=50))
    assert tot["oracle"] == min(tot.values())
    assert tot["oracle"] < tot["ecr"] < tot["shuffled"] < tot["reversed"]


# ---- step 4: z-scores and the dropped week --------------------------------------------------


def test_season_scores_use_z_scores_and_drop_the_worst_week_from_week_8():
    totals: dict[str, dict[tuple[int, str], float]] = {"a": {}, "b": {}}
    for w in range(1, 9):
        totals["a"][(w, "QB")] = 10.0
        totals["b"][(w, "QB")] = 20.0
    totals["a"][(8, "QB")] = 30.0            # a's one bad week
    s = fpranks.season_scores(totals)
    assert s["a"]["QB"] == -7.0              # seven weeks at -1; the +1 week is dropped
    assert s["b"]["QB"] == 5.0               # one -1 and seven +1, one +1 dropped
    assert s["a"]["overall"] == -7.0
    first7 = {k: {c: v for c, v in t.items() if c[0] <= 7} for k, t in totals.items()}
    s7 = fpranks.season_scores(first7)
    assert s7["a"]["QB"] == -7.0
    assert s7["b"]["QB"] == 7.0              # seven weeks: nothing dropped
