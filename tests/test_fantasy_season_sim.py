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


def test_force_applies_to_a_week_folded_into_actuals():
    """--live writes the week in progress into `actuals` at ESPN's projection;
    a --force on that week must still decide the game (it was ignored until
    2026-10-19), keeping both scores and only swapping who gets the higher."""
    teams, games = league()
    w, h, a = games[0]
    live = {w: {t: 100.0 for t in teams} | {h: 110.0, a: 90.0}}
    for winner, loser in ((h, a), (a, h)):
        raw = ss._season(teams, [g for g in games if g[0] == w], w, 500, 25.0, 8.0, 7, actuals=live,
                         force={(w, frozenset((h, a))): winner})
        i, j = raw["idx"][winner], raw["idx"][loser]
        assert (raw["wins"][:, i] == 1).all() and (raw["wins"][:, j] == 0).all()
        assert (raw["pf"][:, i] == 110.0).all() and (raw["pf"][:, j] == 90.0).all()


def test_locks_never_claim_a_tie():
    """Two clinch the top 2 outright; a three-way tie on wins clinches and eliminates nobody."""
    c, o = ss._locks([10, 9, 5, 4], [11, 9, 7, 4], 2)
    assert (c, o) == (0b0011, 0b1100)
    assert ss._locks([9, 9, 9], [9, 9, 9], 2) == (0, 0)


def test_outcome_table_cells_agree_with_their_locks():
    """Late in the season (weeks 1-5 played, the better team always won): every
    clinch in the table is a sure thing in the simulation and every out is a
    zero, a cell where we win our game is never worse for our bye than the
    same cell with a loss, and there is one cell per result of the week."""
    teams, games = league()
    actuals = {w: {t: 200.0 - 10 * t for t in teams} for w in range(1, 6)}
    tab = ss.outcome_table(teams, games, REG, 2000, 22.0, 8.0, 1, actuals, base_sims=2000)
    assert tab["week"] == 6 and len(tab["cells"]) == 2 ** len(tab["games"])
    locks = 0
    for cell in tab["cells"]:
        for metric in ("bye", "playoffs"):
            for i in range(N_TEAMS):
                if cell["clinch"][metric] >> i & 1:
                    assert cell[metric][i] == 10000
                    locks += 1
                if cell["out"][metric] >> i & 1:
                    assert cell[metric][i] == 0
                    locks += 1
    assert locks, "five played weeks of a fixed order must lock someone"
    me = tab["ids"].index(ME)
    j = next(j for j, g in enumerate(tab["games"]) if ME in g)
    home = tab["games"][j][0] == ME
    for k, cell in enumerate(tab["cells"]):
        if bool(k >> j & 1) == home:   # we win in cell k; flip our game for the loss
            assert cell["bye"][me] >= tab["cells"][k ^ (1 << j)]["bye"][me]


def test_unavailable_weeks_byes_and_injury_tags():
    games = {str(w): [{}] for w in range(1, 15) if w != 12}
    assert ss.unavailable_weeks(games, 11, 14, None) == [12]
    assert ss.unavailable_weeks(games, 11, 14, "OUT") == [11, 12]
    assert ss.unavailable_weeks(games, 11, 14, "INJURY_RESERVE") == [11, 12, 13, 14]
    assert ss.unavailable_weeks(games, 11, 14, "QUESTIONABLE") == [12]


def test_week_adjustment_prices_a_bye_against_the_bench():
    k = ss.NFL_WEEKS
    players = [{"name": n, "pos": pos, "proj": v * k, "off": off} for n, pos, v, off in [
        ("QB", "QB", 20, []), ("RB1", "RB", 25, [11]), ("RB2", "RB", 14, []), ("RB3", "RB", 4, []),
        ("WR1", "WR", 24, []), ("WR2", "WR", 17, [11]), ("WR3", "WR", 9, []), ("TE", "TE", 14, []),
        ("K", "K", 10, []), ("DST", "D/ST", 7, [12])]]
    adj = ss.week_adjustments({"players": players}, [11, 12, 13])
    # Week 11: RB3 and WR3 move up into the RB and WR slots, so the flex is empty.
    full = 20 + 25 + 14 + 24 + 17 + 14 + 10 + 7 + 9
    wk11 = 20 + 14 + 4 + 24 + 9 + 14 + 10 + 7 + 0
    assert adj[11] == pytest.approx((wk11 - full))
    assert adj[12] == pytest.approx(ss.REPLACEMENT["D/ST"] - 7)   # no second D/ST: the wire fills it
    assert 13 not in adj
    assert ss.week_adjustments({"players": [dict(p, off=[]) for p in players]}, [11]) == {}


def test_bye_adjustment_lowers_that_week_only():
    teams, games = league()
    k = ss.NFL_WEEKS
    base = ss._season(teams, games, REG, 1000, 25.0, 8.0, 2)
    roster = [{"name": f"p{i}", "pos": pos, "proj": 15 * k, "off": [3] if i == 0 else []}
              for i, pos in enumerate(["RB", "RB", "WR", "WR", "QB", "TE", "K", "D/ST", "WR"])]
    teams[ME] = dict(teams[ME], players=roster)
    hit = ss._season(teams, games, REG, 1000, 25.0, 8.0, 2)
    i = hit["idx"][ME]
    assert np.all(hit["scores"][:, 2, i] < base["scores"][:, 2, i])
    assert np.array_equal(hit["scores"][:, 3, i], base["scores"][:, 3, i])


def test_record_line_does_the_arithmetic():
    games = [(1, 1, 2), (2, 1, 3), (3, 1, 4), (4, 1, 5)]
    actuals = {1: {1: 100.0, 2: 90.0}, 2: {1: 80.0, 3: 95.0}}
    line = ss.record_line(games, actuals, 1, [{"p_win": 0.75}, {"p_win": 0.7}])
    assert "Now 1-1" in line and "1.4 (0 to 2 possible)" in line
    assert "2.5-1.5 over 4 games" in line
