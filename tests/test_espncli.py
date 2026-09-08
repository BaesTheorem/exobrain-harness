"""Fixture tests for fantasy/espncli, the read-only ESPN CLI.

The lineup check's failure mode is a quiet "everything OK", so it gets a
known-bad roster (an OUT starter, a starter on bye, two empty slots, a bench
player out-projecting a starter) and must flag every one. No network: the
fake client serves canned league data and pro-team schedules.
"""

import json
import sys
from argparse import Namespace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "fantasy"))

from espncli import cli, client  # noqa: E402

FUTURE = 4_102_444_800_000  # 2100-01-01 in ms: a kickoff that has not happened
PAST = 946_684_800_000      # 2000-01-01: a kickoff that has


def pro_fixture():
    def game(week, home, away, date):
        return {str(week): [{"homeProTeamId": home, "awayProTeamId": away, "date": date}]}
    return {
        12: {"id": 12, "abbrev": "KC", "name": "Kansas City Chiefs", "bye": 5, "games": game(1, 12, 7, FUTURE + 3_600_000)},
        7: {"id": 7, "abbrev": "DEN", "name": "Denver Broncos", "bye": 5, "games": game(1, 12, 7, FUTURE + 3_600_000)},
        8: {"id": 8, "abbrev": "DET", "name": "Detroit Lions", "bye": 6, "games": game(1, 8, 18, FUTURE)},
        18: {"id": 18, "abbrev": "NO", "name": "New Orleans Saints", "bye": 6, "games": game(1, 8, 18, FUTURE)},
        2: {"id": 2, "abbrev": "BUF", "name": "Buffalo Bills", "bye": 1, "games": {}},
        25: {"id": 25, "abbrev": "SF", "name": "San Francisco 49ers", "bye": 9, "games": game(1, 25, 14, PAST)},
        14: {"id": 14, "abbrev": "LAR", "name": "Los Angeles Rams", "bye": 9, "games": game(1, 25, 14, PAST)},
    }


def entry(pid, name, pos_id, team, slot, proj, status="ACTIVE", eligible=None, actual=None):
    stats = [{"seasonId": 2026, "scoringPeriodId": 1, "statSourceId": 1, "statSplitTypeId": 1, "appliedTotal": proj},
             {"seasonId": 2026, "scoringPeriodId": 0, "statSourceId": 1, "statSplitTypeId": 0, "appliedTotal": proj * 17}]
    if actual is not None:
        stats.append({"seasonId": 2026, "scoringPeriodId": 1, "statSourceId": 0, "statSplitTypeId": 1, "appliedTotal": actual})
    default_elig = {1: [0, 20, 21], 2: [2, 23, 20, 21], 3: [4, 23, 20, 21], 4: [6, 23, 20, 21], 5: [17, 20], 16: [16, 20]}
    return {"lineupSlotId": slot, "playerPoolEntry": {"player": {
        "id": pid, "fullName": name, "defaultPositionId": pos_id, "proTeamId": team,
        "injuryStatus": status, "eligibleSlots": eligible or default_elig[pos_id], "stats": stats,
        "ownership": {"percentOwned": 50.0}}}}


def league_fixture():
    mine = [
        entry(1, "Patrick Mahomes", 1, 12, 0, 20.0),
        entry(2, "Out Back", 2, 8, 2, 15.0, status="OUT"),
        entry(3, "Bye Back", 2, 2, 2, 12.0),
        entry(4, "Kansas Receiver", 3, 12, 4, 14.0),
        # second WR slot deliberately empty
        entry(5, "Questionable End", 4, 18, 6, 8.0, status="QUESTIONABLE"),
        entry(6, "Flex Broncos", 3, 7, 23, 9.0),
        entry(7, "Chiefs D/ST", 16, 12, 16, 5.0),
        # kicker slot deliberately empty, and no kicker on the bench
        entry(8, "Bench Lion", 2, 8, 20, 13.0),
        entry(9, "Bench Bronco", 3, 7, 20, 16.0),
        entry(10, "Bench Saint", 2, 18, 20, 3.0),
        entry(11, "Locked Niner", 3, 25, 20, 7.0, actual=21.4),
    ]
    theirs = [entry(21, "Their QB", 1, 7, 0, 18.0), entry(22, "Their RB", 2, 18, 2, 12.0),
              entry(23, "Their WR", 3, 8, 4, 11.0)]
    return {
        "scoringPeriodId": 1,
        "status": {"currentMatchupPeriod": 1, "finalScoringPeriod": 17},
        "settings": {"name": "Test League", "size": 2, "rosterSettings": {"lineupSlotCounts": {
            "0": 1, "2": 2, "4": 2, "6": 1, "16": 1, "17": 1, "20": 7, "21": 1, "23": 1}},
            "scheduleSettings": {"matchupPeriodCount": 14}},
        "teams": [{"id": 12, "name": "Chaos Legion", "abbrev": "LMAO", "owners": ["{S}"], "roster": {"entries": mine}},
                  {"id": 14, "name": "Other Team", "abbrev": "OT", "owners": ["{T}"], "roster": {"entries": theirs}}],
        "members": [{"id": "{S}", "firstName": "Some", "lastName": "Owner"}],
        "schedule": [{"id": 1, "matchupPeriodId": 1, "winner": "UNDECIDED",
                      "home": {"teamId": 12, "totalPoints": 0.0}, "away": {"teamId": 14, "totalPoints": 0.0}}],
    }


class FakeEspn(client.Espn):
    def __init__(self, data=None, pro=None):
        self.creds = {"league_id": 1, "season": 2026, "espn_s2": "x", "SWID": "{S}", "team_id": 12}
        self.season, self.league_id, self.fresh = 2026, 1, True
        self._pro = pro or pro_fixture()
        self._index = []
        self.data = data or league_fixture()

    def _get(self, url, headers=None, timeout=60, retries=1):
        raise AssertionError(f"tests must not touch the network: {url}")

    def league(self, *views, period=None, filt=None, path=""):
        return self.data


def run_json(api, cmd, **kw):
    args = Namespace(json=True, fresh=True, week=1, team=None, **kw)
    cli.COMMANDS[cmd](api, args)


def test_stat_value_needs_the_season_to_tell_dst_rows_apart():
    p = {"stats": [
        {"seasonId": 2025, "scoringPeriodId": 0, "statSourceId": 1, "statSplitTypeId": 0, "appliedTotal": 128.8},
        {"seasonId": 2026, "scoringPeriodId": 0, "statSourceId": 1, "statSplitTypeId": 0, "appliedTotal": 129.1},
        {"seasonId": 2025, "scoringPeriodId": 0, "statSourceId": 0, "statSplitTypeId": 0, "appliedTotal": 173.0},
    ]}
    assert client.season_proj(p, 2026) == 129.1
    assert client.season_proj(p, 2025) == 128.8
    assert client.season_actual(p, 2025) == 173.0
    assert client.season_actual(p, 2026) is None


def test_norm_strips_suffixes_and_punctuation():
    assert client.norm("LeQuint Allen Jr.") == "lequint allen"
    assert client.norm("Ka'imi Fairbairn") == "ka imi fairbairn"
    assert client.norm("Amon-Ra St. Brown") == client.norm("amon ra st brown")


def test_find_players_ranks_exact_then_fantasy_positions():
    api = FakeEspn()
    api._index = [
        {"id": 1, "name": "Josh Allen", "pos": "QB", "team": 2},
        {"id": 2, "name": "Keenan Allen", "pos": "WR", "team": 18},
        {"id": 3, "name": "Brevin Allen", "pos": "", "team": 0},
        {"id": 4, "name": "Josh Allen", "pos": "", "team": 0},  # the linebacker
    ]
    assert api.resolve_one("josh allen")["id"] == 1
    assert api.resolve_one("keenan")["id"] == 2
    with pytest.raises(client.EspnError):
        api.resolve_one("allen")
    assert api.resolve_one("2")["id"] == 2


def test_initials_never_leak_a_name():
    assert client.initials({"firstName": "Some", "lastName": "Owner"}) == "S.O."
    assert client.initials({"displayName": "someone"}) == "S."
    assert client.initials(None) == "?"


def test_variance_rule_sides():
    assert cli.variance_line(3.0).startswith("favorite")
    assert cli.variance_line(-3.0).startswith("underdog")
    assert cli.variance_line(2.9).startswith("coin flip")


def test_opponent_kickoff_and_bye_from_pro_schedule():
    api = FakeEspn()
    assert api.opponent(12, 1) == "DEN"
    assert api.opponent(7, 1) == "@KC"
    assert api.opponent(2, 1) == "BYE"
    assert api.kickoff(2, 1) is None
    assert api.kickoff(8, 1) > cli.now()


def test_lineup_check_flags_every_planted_problem(capsys):
    run_json(FakeEspn(), "check")
    out = json.loads(capsys.readouterr().out)
    kinds = sorted((p["kind"], p["slot"]) for p in out["problems"])
    assert kinds == [("BYE", "RB"), ("EMPTY", "K"), ("EMPTY", "WR"), ("OUT", "RB"), ("QUESTIONABLE", "TE")]
    fixes = {(p["kind"], p["slot"]): p["fix"] for p in out["problems"]}
    assert "Bench Bronco" in fixes[("EMPTY", "WR")]          # best eligible bench WR
    assert "Bench Lion" in fixes[("OUT", "RB")]              # best usable bench RB
    assert "nobody eligible" in fixes[("EMPTY", "K")]        # no kicker anywhere
    assert "no usable bench" in fixes[("QUESTIONABLE", "TE")]
    top = out["nudges"][0]
    assert (top["bench"], top["slot"], top["gain"]) == ("Bench Bronco", "FLEX", 7.0)
    assert out["first_kickoff"]["game"] == "LAR @ SF"        # the earliest game on the slate
    assert out["margin"] == pytest.approx(83.0 - 41.0)
    assert out["rule"].startswith("favorite")


def test_lineup_check_is_clean_on_a_clean_roster(capsys):
    data = league_fixture()
    ok = [entry(1, "QB", 1, 12, 0, 20.0), entry(2, "RB1", 2, 8, 2, 15.0), entry(3, "RB2", 2, 18, 2, 12.0),
          entry(4, "WR1", 3, 12, 4, 14.0), entry(5, "WR2", 3, 7, 4, 13.0), entry(6, "TE", 4, 18, 6, 8.0),
          entry(7, "FLX", 3, 7, 23, 9.0), entry(8, "DST", 16, 12, 16, 5.0), entry(9, "K", 5, 12, 17, 8.0)]
    data["teams"][0]["roster"]["entries"] = ok
    run_json(FakeEspn(data), "check")
    out = json.loads(capsys.readouterr().out)
    assert out["problems"] == [] and out["nudges"] == []


def test_matchup_reads_lineups_and_locked_actuals(capsys):
    run_json(FakeEspn(), "matchup")
    out = json.loads(capsys.readouterr().out)
    assert out["me"]["team"] == "Chaos Legion" and out["opp"]["team"] == "Other Team"
    assert out["me"]["projected"] == 83.0 and out["opp"]["projected"] == 41.0
    locked = next(r for r in out["me"]["rows"] if r["name"] == "Locked Niner")
    assert locked["actual"] == 21.4 and "locked" in locked["kick"]
    unlocked = next(r for r in out["me"]["rows"] if r["name"] == "Patrick Mahomes")
    assert unlocked["actual"] is None


def test_implied_totals_from_home_spread(monkeypatch):
    api = FakeEspn()
    event = {"id": "1", "shortName": "NE @ SEA", "date": "2026-09-10T00:20Z",
             "status": {"type": {"state": "pre", "shortDetail": "9/9 - 8:20 PM EDT"}},
             "weather": {"displayValue": "Mostly sunny", "temperature": 74},
             "competitions": [{"competitors": [
                 {"homeAway": "home", "team": {"abbreviation": "SEA", "id": "26"}, "score": "0", "records": []},
                 {"homeAway": "away", "team": {"abbreviation": "NE", "id": "17"}, "score": "0", "records": []}],
                 "odds": [{"details": "SEA -3.5", "overUnder": 44.5, "spread": -3.5}],
                 "venue": {"fullName": "Lumen Field", "indoor": False}, "broadcast": "NBC"}]}
    monkeypatch.setattr(api, "public", lambda path, **kw: {"events": [event]})
    g = cli.nfl_events(api, 1)[0]
    assert (g["implied_home"], g["implied_away"]) == (24.0, 20.5)
    assert g["kickoff"].hour == 19 and g["kickoff"].tzname() == "CDT"


def test_short_status_and_signed():
    assert cli.short_status("ACTIVE") == ""
    assert cli.short_status("INJURY_RESERVE") == "IR"
    assert cli.signed(-0.0) == "+0.0"
    assert cli.signed(None) == "-"
