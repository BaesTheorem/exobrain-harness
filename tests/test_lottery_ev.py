"""Positive controls for lottery/lottery_ev.py. No network.

The model is trusted only as far as it reproduces numbers the lotteries
publish themselves: the "overall chances" line on each game page, the
break-even arithmetic of the prize tables, and a Scratchers game whose
unsold tickets must return the printed payout when prizes fall evenly.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lottery"))

import lottery_ev as ev  # noqa: E402


def overall_odds(game: ev.Game) -> float:
    return 1 / (1 / game.jackpot_odds + sum(1 / odds for _, odds in game.tiers))


def test_prize_tables_reproduce_published_overall_chances():
    # molottery.com prints 1 in 8.77 (Show Me Cash) and 1 in 11.74 (MO Millions).
    assert overall_odds(ev.GAMES["smc"]) == pytest.approx(8.77, abs=0.01)
    assert overall_odds(ev.GAMES["mom"]) == pytest.approx(11.74, abs=0.01)
    # The Kansas brochure prints 1 in 12 for a $1 Super Kansas Cash ticket.
    assert overall_odds(ev.GAMES["skc"]) == pytest.approx(12.0, abs=0.2)


def test_naive_break_even_follows_from_the_prize_table():
    smc = ev.GAMES["smc"]
    assert smc.low_return == pytest.approx(0.2754, abs=0.0005)
    assert smc.naive_break_even == pytest.approx(417_000, rel=0.01)
    # MO Millions advertises an annuity worth about twice the cash.
    assert ev.GAMES["mom"].naive_break_even == pytest.approx(17_140_000, rel=0.01)


def test_federal_brackets_2026():
    assert ev.fed_tax(0) == 0
    assert ev.fed_tax(12_400) == pytest.approx(1_240)
    assert ev.fed_tax(50_400) == pytest.approx(1_240 + 0.12 * 38_000)


def test_return_rises_with_jackpot_and_tax_and_sharing_lower_it():
    smc = ev.GAMES["smc"]
    low, high = ev.ticket_return(smc, 200_000), ev.ticket_return(smc, 800_000)
    assert low < high
    assert ev.ticket_return(smc, 800_000, taxed=True) < high
    assert ev.ticket_return(smc, 800_000, unpopular=True) > high


def test_break_even_orders_and_is_finite():
    smc = ev.GAMES["smc"]
    naive = smc.naive_break_even
    pre = ev.break_even(smc)
    pre_unpopular = ev.break_even(smc, unpopular=True)
    after = ev.break_even(smc, taxed=True, unpopular=True)
    assert naive < pre_unpopular < pre < 600_000
    assert pre_unpopular < after < 1_000_000
    assert ev.ticket_return(smc, after, taxed=True, unpopular=True) == pytest.approx(1.0, abs=0.001)


def test_loss_rule_taxes_a_break_even_year():
    # $50,000 of tickets, $50,000 of prizes: 10 percent of the losses stay taxable.
    assert ev.extra_tax(50_000, 50_000, 50_000) > 0
    # Kansas allows no deduction for losing tickets, so the same year costs more there.
    assert ev.extra_tax(50_000, 50_000, 50_000, "KS") > ev.extra_tax(50_000, 50_000, 50_000, "MO")


def test_full_coverage_needs_a_jackpot_above_the_combination_count():
    smc = ev.GAMES["smc"]
    assert ev.coverage(smc, 400_000, 0)["pre_tax"] < 0
    solo = ev.coverage(smc, 900_000, 0)
    shared = ev.coverage(smc, 900_000, 2)
    assert solo["after_tax"] > 0 > shared["after_tax"]
    assert solo["cost"] == pytest.approx(575_757)


def scratcher(sold: float, top_left: int) -> dict:
    """A $10 game: 1,000,000 tickets, common prizes claimed in step with sales."""
    tiers = [
        {"value": 10.0, "total": 150_000, "unclaimed": round(150_000 * (1 - sold * 0.95))},
        {"value": 50.0, "total": 50_000, "unclaimed": round(50_000 * (1 - sold))},
        {"value": 100.0, "total": 20_000, "unclaimed": round(20_000 * (1 - sold))},
        {"value": 500_000.0, "total": 2, "unclaimed": top_left},
    ]
    total = sum(t["total"] for t in tiers)
    return {"game": 1, "name": "TEST", "price": 10.0, "odds": 1_000_000 / total, "end": "TBD", "tiers": tiers}


def test_scratcher_sold_fraction_ignores_the_underclaimed_low_tier():
    row = ev.scratcher_return(scratcher(0.60, 2))
    assert row is not None
    assert row["sold"] == pytest.approx(0.60, abs=0.001)


def test_scratcher_with_no_top_prize_left_returns_less_than_printed():
    row = ev.scratcher_return(scratcher(0.80, 0))
    assert row is not None
    assert row["return_now"] < row["printed_return"]


def test_scratcher_turns_positive_only_late_with_top_prizes_left():
    early = ev.scratcher_return(scratcher(0.50, 2))
    late = ev.scratcher_return(scratcher(0.92, 2))
    assert early is not None and late is not None
    assert early["return_now"] < 1.0 < late["return_now"]
    assert early["turns_positive_at"] == pytest.approx(late["turns_positive_at"], abs=0.001)
    assert 0.5 < early["turns_positive_at"] < 0.92
