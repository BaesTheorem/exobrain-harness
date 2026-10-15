"""fantasy/season_sim.py: the bye-odds simulator and its leverage report.

The leverage numbers feed playbook rules (the win-vs-points exchange rate and
the per-week weights for valuing a player), so the invariants that make them
interventions rather than correlations are pinned here on a synthetic league:
common random numbers (a zero bump changes nothing), a forced win or extra
Points For can never lower our bye odds, and the seed comparison holds our
team fixed.
"""

import pytest

np = pytest.importorskip("numpy", reason="season_sim needs numpy; install it into the pytest env")
from conftest import load_script

ss = load_script("fantasy/season_sim.py")

N_TEAMS, REG, ME = 8, 7, 1


def league():
    """Eight teams, a full round robin in seven weeks (circle method)."""
    teams = {t: {"name": f"T{t}", "espn": (120.0 + 3 * (N_TEAMS - t)) * ss.NFL_WEEKS} for t in range(1, N_TEAMS + 1)}
    ring = list(range(1, N_TEAMS + 1))
    games = []
    for w in range(1, REG + 1):
        for i in range(N_TEAMS // 2):
            games.append((w, ring[i], ring[-1 - i]))
        ring = [ring[0]] + [ring[-1]] + ring[1:-1]
    return teams, games


def test_round_robin_fixture_is_legal():
    _teams, games = league()
    for w in range(1, REG + 1):
        playing = [t for wk, h, a in games if wk == w for t in (h, a)]
        assert sorted(playing) == list(range(1, N_TEAMS + 1))


def test_simulate_probabilities_add_up():
    teams, games = league()
    probs = ss.simulate(teams, games, REG, 3000, 25.0, 8.0, 3)[-1]
    assert probs["bye"].sum() == pytest.approx(ss.BYES)
    assert probs["playoffs"].sum() == pytest.approx(ss.PLAYOFF_TEAMS)
    assert probs["champ"].sum() == pytest.approx(1.0)


def test_zero_bump_changes_nothing():
    teams, games = league()
    a = ss._season(teams, games, REG, 2000, 25.0, 8.0, 5)
    b = ss._season(teams, games, REG, 2000, 25.0, 8.0, 5, me=ME,
                   bump={"week": {3: 0.0}, "pf": 0.0, "playoff": {1: 0.0}})
    assert np.array_equal(a["order"], b["order"])
    assert np.array_equal(a["po"], b["po"])


def test_leverage_is_an_intervention():
    teams, games = league()
    actuals = {1: {t: 120.0 + t for t in teams}}
    lev = ss.leverage(teams, games, REG, actuals, ME, 4000, 25.0, 8.0, 9)
    assert sorted(lev["weeks"]) == list(range(2, REG + 1)), "played weeks are not levers"
    for w, v in lev["weeks"].items():
        assert v["win_bye"] >= 0.0, f"a forced win lowered the bye odds in week {w}"
    assert lev["pf_point"]["bye"] >= 0.0, "Points For alone lowered the bye odds"
    # Seed 1 plays two games and seed 3 plays three, with the same team.
    assert lev["placed"][1] > lev["placed"][3]
    assert lev["bye_worth_title"] > 0.0
    # The playoff weeks are elimination games; a regular-season week is not.
    assert lev["weight"][REG + 3] > lev["weight"][REG]


def test_measured_sigma_reads_within_team_scatter():
    teams, games = league()
    rng = np.random.default_rng(0)
    actuals = {w: {t: 100.0 + 5 * t + rng.normal(0, 30.0) for t in teams} for w in range(1, REG + 1)}
    assert ss.measured_sigma(games, actuals) == pytest.approx(30.0, rel=0.25)
    assert ss.measured_sigma(games, {w: actuals[w] for w in (1, 2, 3)}) is None, "too few weeks to measure"
