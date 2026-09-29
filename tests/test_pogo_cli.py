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


# ---- your account: box CSVs, the data-request export, the inbox classifier ----

GENIE = """Index,Name,Form,Pokemon,Gender,CP,HP,Atk IV,Def IV,Sta IV,IV Avg,Level Min,Level Max,Quick Move,Charge Move,Charge Move 2,Lucky,Shadow/Purified,Favorite,Rank # (G),Name (G)
1,Ninetales,Alola,38,♀,1500,127,0,15,15,66.7,20.0,20.0,Powder Snow,Weather Ball,Psyshock,0,1,0,12,Ninetales
2,Seismitoad,Normal,537,♂,1498,162,1,15,14,66.7,22.5,22.5,Mud Shot,Earth Power,Sludge Bomb,0,0,1,80,Seismitoad
3,Seismitoad,Normal,537,♂,1400,150,8,10,10,62.2,20.0,20.0,Mud Shot,Earth Power,,0,0,0,900,Seismitoad
4,Machamp,Normal,68,♂,2500,163,15,15,15,100,40.0,40.0,Counter,Dynamic Punch,Rock Slide,1,2,0,,
5,,,,,,,,,,,,,,,,,,,,
"""

CALCY = """Ancestor?,Scan date,Nr,Name,Nickname,Gender,Level,possibleLevels,CP,HP,ØATT IV,ØDEF IV,ØHP IV,ØIV%,Unique?,Fast move,Special move,Star,Form,Lucky,Shadow,GL Rank
0,1/1/2020 00:00:00,194,Wooper,box1,♂,20,20,500,85,0,15,15,66.7,1,Water Gun,Frustration,0,0,1,1,40
0,1/2/2020 00:00:00,38,Ninetales,box2,♀,20,20,1500,127,12,12,12,80.0,0,Charm,Psyshock,1,61,0,0,90
1,1/2/2020 00:00:00,38,Ninetales,-,-,18,18,1400,120,12,12,12,80.0,0,Charm,Psyshock,0,61,0,0,
0,1/4/2020 00:00:00,,,junk,,20,20,abc,0,-1,-1,-1,0,0,-,-,0,0,1,0,
"""

GAMEPLAY = """Start date: 2016-07-09
Level: 41
Total XP: 12345678
Pokecoin: 120
Stardust: 987654
Distance walked: 3456.7 km
Buddy nickname: Loki
Pokemon Home Trainer Name: SomeTrainer

Pokemon in your collection:
V0006_POKEMON_CHARIZARD (some detail)
BULBASAUR
V0150_POKEMON_MEWTWO

You have hatched 812 eggs and currently have 7 eggs.
You have 1450 items.
"""


def test_pokegenie_csv_is_detected_and_parsed():
    dialect, mons, issues = pogo.parse_box_csv(GENIE)
    assert dialect == "pokegenie"
    assert [m["name"] for m in mons] == ["Ninetales", "Seismitoad", "Seismitoad", "Machamp"]
    fox = mons[0]
    assert (fox["form"], fox["gender"], fox["atk"], fox["def"], fox["sta"]) == ("Alola", "f", 0, 15, 15)
    assert fox["shadow"] is True and fox["purified"] is False and fox["iv_pct"] == 66.7
    assert fox["level"] == 20.0 and fox["rank"] == {"great": 12}
    assert mons[1]["favorite"] is True and mons[1]["charged"] == ["Earth Power", "Sludge Bomb"]
    champ = mons[3]
    assert champ["iv_pct"] == 100 and champ["lucky"] is True and champ["purified"] is True and champ["rank"] == {}
    assert issues and "row 6" in issues[0]  # the empty trailing row is reported, not crashed on


def test_calcy_csv_skips_ancestor_rows_and_junk():
    dialect, mons, issues = pogo.parse_box_csv(CALCY)
    assert dialect == "calcyiv"
    assert [m["name"] for m in mons] == ["Wooper", "Ninetales"]  # ancestor row and junk row dropped
    wooper, fox = mons
    assert wooper["shadow"] is True and wooper["lucky"] is True and wooper["nickname"] == "box1"
    assert wooper["charged"] == ["Frustration"] and wooper["rank"] == {"great": 40}
    assert fox["iv_exact"] is False and fox["favorite"] is True and fox["form"] == "61"
    assert any("row 5" in i for i in issues)


def test_unknown_csv_is_rejected():
    dialect, mons, issues = pogo.parse_box_csv("name,age\nJohn,30\n")
    assert dialect == "" and mons == [] and "not a Poke Genie" in issues[0]


def test_gameplay_txt_parses_stats_and_species_list():
    g = pogo.parse_gameplay(GAMEPLAY)
    assert g["level"] == 41 and g["total_xp"] == 12345678 and g["distance_km"] == 3456.7
    assert g["start_date"] == "2016-07-09" and g["buddy"] == "Loki"
    assert g["pokemon"] == ["Charizard", "Bulbasaur", "Mewtwo"]
    assert (g["eggs_hatched"], g["eggs_held"], g["items"]) == (812, 7, 1450)


def test_parse_when_handles_the_export_timestamp_shapes():
    assert pogo.parse_when("2026-09-28T13:00:00Z").year == 2026
    assert pogo.parse_when("2026-09-28 13:00:00 UTC").hour == 13
    assert pogo.parse_when("1/2/2020 00:00:00").month == 1
    assert pogo.parse_when("1690000000").tzinfo is not None
    assert pogo.parse_when("1690000000000").year == 2023
    assert pogo.parse_when("-") is None and pogo.parse_when("") is None
    assert pogo.month_key(pogo.parse_when("2026-09-28")) == "2026-09"


def test_dupe_groups_put_the_best_copy_first():
    _, mons, _ = pogo.parse_box_csv(GENIE)
    groups = pogo.dupe_groups(mons)
    assert len(groups) == 1 and [m["cp"] for m in groups[0]] == [1498, 1400]  # 66.7% before 62.2%


def test_inbox_classifier_and_import_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(pogo, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(pogo, "BOX_DIR", tmp_path / "data" / "box")
    monkeypatch.setattr(pogo, "ACCOUNT_DIR", tmp_path / "data" / "account")
    monkeypatch.setattr(pogo, "IMPORTS", tmp_path / "data" / "imports.json")
    csv_path = tmp_path / "scan.csv"
    csv_path.write_text(GENIE, encoding="utf-8")
    other = tmp_path / "other.csv"
    other.write_text("name,age\nJohn,30\n", encoding="utf-8")
    import zipfile
    zpath = tmp_path / "export.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("Gameplay.txt", GAMEPLAY)
        z.writestr("InAppPurchases.tsv", "Time\tCurrency\tMoney spent on purchase\tChange in pokecoins\n2022-06-29T07:21:13Z\tUSD\t9.99\t1200\n2022-07-01T00:00:00Z\tUSD\t0\t-550\n")
        z.writestr("FriendList.tsv", "Friend\tFriendship initiated by\nA\tYou\nB\tThem\n")
        z.writestr("Pokestop_spin1.csv", "Time,Detail\n2026-08-01T10:00:00Z,x\n2026-09-02T10:00:00Z,y\n")
    assert pogo.classify_export(csv_path) == "box"
    assert pogo.classify_export(other) == ""
    assert pogo.classify_export(zpath) == "account"
    snap = pogo.import_box(csv_path)
    assert snap["count"] == 4 and (tmp_path / "data" / "box" / "latest.json").exists()
    summary = pogo.import_account(zpath)
    assert summary["gameplay"]["level"] == 41
    assert summary["purchases"]["money_by_currency"] == {"USD": 9.99}
    assert summary["purchases"]["pokecoins_bought"] == 1200 and summary["purchases"]["pokecoins_spent"] == 550
    assert summary["friends"] == {"count": 2, "you_initiated": 1}
    assert summary["journey"]["spins"]["rows"] == 2 and summary["journey"]["spins"]["months"] == {"2026-08": 1, "2026-09": 1}
    imports = pogo.read_json(tmp_path / "data" / "imports.json", {})
    assert {v["kind"] for v in imports.values()} == {"box", "account"}


def test_pogo_lens_columns_ride_along():
    header = "Index,Name,Form,Pokemon,Gender,CP,HP,Atk IV,Def IV,Sta IV,IV Avg,Level Min,Level Max,Quick Move,Charge Move,Charge Move 2,Lucky,Shadow/Purified,Favorite,Rank # (G),Name (G),Nickname,Dust,IV Exact,Candidates,Scan Date,Source,Candy,Candy XL,Mega Energy,Evolve Candy,Caught Date\n"
    row = "1,Bulbasaur,Normal,1,,608,82,14,10,10,75.6,20.0,20.5,Tackle,,,0,0,0,,,,2500,0,7,2026-09-29T12:53:00Z,pogolens,242,29,340,25,2022-06-26\n"
    dialect, mons, issues = pogo.parse_box_csv(header + row)
    assert dialect == "pokegenie" and len(mons) == 1 and not issues
    m = mons[0]
    assert m["iv_exact"] is False and m["level"] is None and (m["level_min"], m["level_max"]) == (20.0, 20.5)
    assert (m["candy"], m["candy_xl"], m["caught"]) == (242, 29, "2022-06-26")
    assert pogo.ivs_label(m) == "14/10/10~"
