"""pogo CLI (pokemon-go/pogocli.py): the game math and data shaping that need no network.

The CP multiplier table from pogoapi stops at level 45; the CLI extends it with the
game's fixed 0.0025-per-half-level step. Known in-game values pin the formula:
a hundo Mewtwo at level 40 is 4178 CP, and pogoapi's own max_cp for Bulbasaur (1275)
is the level 51 hundo, which is what the extension has to reproduce.
"""

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("pogocli", REPO / "pokemon-go" / "pogocli.py")
assert _spec and _spec.loader
pogo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pogo)

CPM_RAW = [
    {"level": 1, "multiplier": 0.094},
    {"level": 20, "multiplier": 0.5974},
    {"level": 20.5, "multiplier": 0.6079},
    {"level": 40, "multiplier": 0.79030001},
    {"level": 45, "multiplier": 0.81529999},
]


@pytest.fixture
def cpm():
    return pogo.cpm_table(CPM_RAW)


def test_cpm_extends_past_the_published_table(cpm):
    assert cpm[40.0] == 0.79030001
    assert cpm[45.0] == 0.81529999  # published value wins over the extension
    assert cpm[50.0] == pytest.approx(0.8403, abs=1e-6)
    assert cpm[51.0] == pytest.approx(0.8453, abs=1e-6)
    assert 55.0 in cpm and 55.5 not in cpm


def test_cp_matches_known_in_game_values(cpm):
    assert pogo.calc_cp(300, 182, 214, (15, 15, 15), cpm[40.0]) == 4178  # Mewtwo hundo L40
    assert pogo.calc_cp(118, 111, 128, (15, 15, 15), cpm[51.0]) == 1275  # Bulbasaur, pogoapi max_cp
    assert pogo.calc_cp(1, 1, 1, (0, 0, 0), cpm[1.0]) == 10  # CP never shows below 10


def test_hp_floors_and_never_shows_below_ten(cpm):
    assert pogo.calc_hp(214, 15, cpm[40.0]) == 180  # floor(229 * 0.7903)
    assert pogo.calc_hp(1, 0, cpm[1.0]) == 10


def test_iv_solver_round_trips_and_only_returns_exact_fits(cpm):
    base = (118, 111, 128)
    cp = pogo.calc_cp(*base, (12, 7, 3), cpm[20.0])
    hp = pogo.calc_hp(base[2], 3, cpm[20.0])
    hits = pogo.solve_ivs(base, cp, hp, [20.0, 20.5], cpm)
    assert (20.0, 12, 7, 3) in hits
    for level, a, d, s in hits:
        assert pogo.calc_cp(*base, (a, d, s), cpm[level]) == cp
        assert pogo.calc_hp(base[2], s, cpm[level]) == hp


def test_iv_solver_returns_nothing_for_an_impossible_pair(cpm):
    assert pogo.solve_ivs((118, 111, 128), 9999, 10, [20.0], cpm) == []


def _chart():
    types = ["Fire", "Flying", "Rock", "Water", "Electric", "Grass", "Ground", "Bug"]
    chart = {a: {d: 1.0 for d in types} for a in types}
    chart["Rock"]["Fire"] = chart["Rock"]["Flying"] = 1.6
    chart["Electric"]["Flying"] = 1.6
    chart["Water"]["Fire"] = 1.6
    chart["Ground"]["Fire"] = 1.6
    chart["Ground"]["Flying"] = 0.390625
    chart["Grass"]["Fire"] = chart["Grass"]["Flying"] = 0.625
    chart["Bug"]["Fire"] = chart["Bug"]["Flying"] = 0.625
    return chart


def test_defensive_matchups_multiply_across_both_types():
    mults = pogo.defensive_matchups(_chart(), ["Fire", "Flying"])
    assert mults["Rock"] == 2.56
    assert mults["Electric"] == 1.6
    assert mults["Ground"] == 0.625  # 1.6 * 0.390625: the Ground hit is neutral overall
    assert mults["Grass"] == pytest.approx(0.391, abs=1e-3)
    weak, resist = pogo.matchup_lines(mults)
    assert weak.startswith("Rock x2.56")
    assert "Fire x1" not in weak and "Fire x1" not in resist


def test_event_rows_classify_against_local_now():
    now = dt.datetime(2026, 10, 10, 15, 0)
    events = [
        {"name": "CD", "start": "2026-10-10T14:00:00.000", "end": "2026-10-10T17:00:00.000"},
        {"name": "Later", "start": "2026-10-11T10:00:00.000", "end": "2026-10-12T20:00:00.000"},
        {"name": "Gone", "start": "2026-10-01T10:00:00.000", "end": "2026-10-05T20:00:00.000"},
        {"name": "Broken", "start": None, "end": None},
    ]
    rows = pogo.event_rows(events, now)
    assert [r["name"] for r in rows] == ["Gone", "CD", "Later"]  # sorted by start, broken row dropped
    assert {r["name"]: r["_status"] for r in rows} == {"Gone": "ended", "CD": "NOW", "Later": "upcoming"}
    assert pogo.fmt_range(rows[1]["_start"], rows[1]["_end"]) == "Sat Oct 10 14:00 to 17:00"


def test_text_helpers():
    assert pogo.norm("Mr. Mime") == "mrmime"
    assert pogo.norm("Farfetch'd") == pogo.norm("farfetchd")
    assert pogo.strip_html("<span>Catch 5 Grass-type Pokémon</span>") == "Catch 5 Grass-type Pokémon"
    assert pogo.title_move("THUNDER_SHOCK_FAST") == "Thunder Shock"
    assert pogo.parse_ivs("15/14/13") == (15, 14, 13)
    with pytest.raises(SystemExit):
        pogo.parse_ivs("16/0/0")


def test_research_rows_keep_shiny_and_cp_range():
    rows = pogo.research_rows([{"text": "<span>Catch 5</span>", "rewards": [
        {"name": "Foongus", "canBeShiny": True, "combatPower": {"min": 386, "max": 419}},
        {"name": "Skwovet", "combatPower": {}},
    ]}])
    assert rows == [{"task": "Catch 5", "rewards": [
        {"name": "Foongus", "shiny": True, "cp": "386-419"},
        {"name": "Skwovet", "shiny": False, "cp": "?-?"},
    ]}]
