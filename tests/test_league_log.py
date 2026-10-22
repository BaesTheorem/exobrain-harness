"""Fixture tests for fantasy/espncli/league_log.py and the rival analysis.

The league log reads three ESPN sources whose fields mean different things by
message type, and slot ids overlap team ids (1-14), so a wrong field quietly
credits a move to the wrong team. The fixture carries one row of each shape
seen in the 2026 league (checked 2026-10-22) and pins the result. The same
fixture runs through the Worker's JavaScript twin (fantasy/scorebug/wire.js)
when node is on PATH. No network.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fantasy"))

from espncli import league_log  # noqa: E402
from espncli.rivals import base_rates, fits, p_claimed  # noqa: E402

ME = 12
TEAMS = list(range(1, 15))
WEB = {"platform": "espn-fantasy-web"}
STARTS = [1000, 2000, 3000]   # weeks 1, 2, 3 begin at these epoch ms


def topic(date: int, *msgs: dict, info: dict | None = WEB) -> dict:
    return {"date": date, "creationInfo": info, "messages": list(msgs)}


def msg(mid: str, mt: int, date: int, **kw) -> dict:
    return {"id": mid, "messageTypeId": mt, "date": date, **kw}


RAW = {
    "topics": [
        # A free-agent add puts the team in "to"; its drop puts it in "to" too (179).
        topic(2500, msg("a1", 178, 2500, to=13, targetId=-16030), msg("d1", 179, 2500, to=13, targetId=-16025)),
        # A drop (239) puts the team in "for" and the vacated slot in "from": slot 4
        # is also team 4, so reading "from" first would credit team 4.
        topic(2400, msg("d2", 239, 2400, **{"from": 4, "to": -1, "for": 9}, targetId=111)),
        # A lineup move: team in "for", slots in "from" and "to".
        topic(2300, msg("l1", 188, 2300, **{"from": 20, "to": 23, "for": 1}, targetId=222)),
        # ESPN carrying out a lineup planned in advance: no client platform.
        topic(2200, msg("l2", 188, 2200, **{"from": 4, "to": 20, "for": 7}, targetId=333), info={}),
        # A trade in review (224) and done (244): "from" team gives to "to" team; 245 a forced drop.
        topic(1500, msg("t1", 224, 1500, **{"from": 2, "to": 4}, targetId=444)),
        topic(1600, msg("t2", 244, 1600, **{"from": 2, "to": 4}, targetId=444), msg("t3", 245, 1600, **{"from": 4, "to": 0}, targetId=555)),
        # The same message twice in two topics is one event.
        topic(2500, msg("a1", 178, 2500, to=13, targetId=-16030)),
        # A waiver add processed by ESPN.
        topic(900, msg("w1", 180, 900, **{"from": 0, "to": 3, "for": 6}, targetId=666),
              info={"platform": "lm-processor"}),
    ],
    "transactions": [
        {"id": "x1", "type": "WAIVER", "status": "FAILED_INVALIDPLAYERSOURCE", "teamId": 5, "scoringPeriodId": 2,
         "processDate": 1700, "memberId": "NightlyLeagueUpdateTaskProcessor",
         "items": [{"type": "ADD", "playerId": 666}, {"type": "DROP", "playerId": 777}]},
        {"id": "x2", "type": "WAIVER", "status": "CANCELED", "teamId": 12, "scoringPeriodId": 2, "proposedDate": 1800,
         "memberId": "{ME}", "items": [{"type": "ADD", "playerId": 888}]},
        {"id": "x3", "type": "TRADE_UPHOLD", "status": "EXECUTED", "teamId": 10, "scoringPeriodId": 2,
         "proposedDate": 1550, "memberId": "{M10}", "relatedTransactionId": "p1"},
        {"id": "x4", "type": "TRADE_PROPOSAL", "status": "CANCELED", "teamId": 10, "scoringPeriodId": 1,
         "proposedDate": 1100, "memberId": "{M10}",
         "items": [{"type": "TRADE", "playerId": 1, "fromTeamId": 10, "toTeamId": 6},
                   {"type": "TRADE", "playerId": 2, "fromTeamId": 6, "toTeamId": 10}]},
        # Another pair's still-pending proposal is never shown; if it were, it is skipped.
        {"id": "x5", "type": "TRADE_PROPOSAL", "status": "PENDING", "teamId": 3, "scoringPeriodId": 2,
         "proposedDate": 1900, "memberId": "{M3}", "items": [{"type": "TRADE", "playerId": 3, "fromTeamId": 3, "toTeamId": 8}]},
        # Our own offer's original row stays PENDING after the offer ends.
        {"id": "x8", "type": "TRADE_PROPOSAL", "status": "PENDING", "teamId": 12, "scoringPeriodId": 2,
         "proposedDate": 1950, "memberId": "{ME}", "items": [{"type": "TRADE", "playerId": 4, "fromTeamId": 12, "toTeamId": 2}]},
        # A lineup set in advance for week 3, made at 1200 (week 1).
        {"id": "x9", "type": "FUTURE_ROSTER", "status": "EXECUTED", "teamId": 7, "scoringPeriodId": 3,
         "proposedDate": 1200, "memberId": "{M7}",
         "items": [{"type": "LINEUP", "playerId": 333, "fromLineupSlotId": 4, "toLineupSlotId": 20}]},
        # Executed adds and lineup rows are the feed's, so they are skipped here.
        {"id": "x6", "type": "WAIVER", "status": "EXECUTED", "teamId": 3, "processDate": 900, "items": []},
        {"id": "x7", "type": "ROSTER", "status": "EXECUTED", "teamId": 1, "items": []},
        # The same row read from two periods is one event (the later read wins).
        {"id": "x1", "type": "WAIVER", "status": "FAILED_INVALIDPLAYERSOURCE", "teamId": 5, "scoringPeriodId": 2,
         "processDate": 1700, "memberId": "NightlyLeagueUpdateTaskProcessor",
         "items": [{"type": "ADD", "playerId": 666}, {"type": "DROP", "playerId": 777}]},
    ],
    "pending": [
        {"id": "p9", "type": "WAIVER", "status": "PENDING", "teamId": 12, "processDate": 5000, "subOrder": 0,
         "items": [{"type": "ADD", "playerId": -16030, "fromTeamId": 0, "toTeamId": 12}]},
        {"id": "p8", "type": "TRADE_PROPOSAL", "status": "PENDING", "teamId": 2, "processDate": 6000,
         "items": [{"type": "TRADE", "playerId": 9, "fromTeamId": 2, "toTeamId": 5}]},
        {"id": "p7", "type": "TRADE_PROPOSAL", "status": "PENDING", "teamId": 1, "expirationDate": 7000,
         "items": [{"type": "TRADE", "playerId": 10, "fromTeamId": 1, "toTeamId": 12}]},
        {"id": "p6", "type": "WAIVER", "status": "PENDING", "teamId": 4, "processDate": 5000, "items": []},
    ],
}


@pytest.fixture(scope="module")
def log() -> dict:
    return league_log.normalize(RAW, TEAMS, ME, STARTS)


def by_id(log: dict) -> dict[str, dict]:
    return {e["id"]: e for e in log["events"]}


def test_team_fields_by_message_type(log):
    e = by_id(log)
    assert (e["a1"]["team_id"], e["a1"]["kind"], e["a1"]["how"]) == (13, "add", "fa")
    assert (e["d1"]["team_id"], e["d1"]["kind"]) == (13, "drop")
    assert e["d2"]["team_id"] == 9, "a 239 drop must read 'for', not the slot in 'from' (slot 4 = team 4)"
    assert (e["l1"]["team_id"], e["l1"]["detail"]) == (1, "BE>FLEX")
    assert (e["t1"]["team_id"], e["t1"]["other_team_id"], e["t1"]["kind"]) == (2, 4, "trade_accepted")
    assert (e["t2"]["team_id"], e["t2"]["other_team_id"], e["t2"]["kind"]) == (2, 4, "trade")
    assert (e["t3"]["team_id"], e["t3"]["kind"], e["t3"]["how"]) == (4, "drop", "trade")
    assert (e["w1"]["team_id"], e["w1"]["how"]) == (3, "waiver")


def test_auto_rows_and_weeks(log):
    e = by_id(log)
    assert e["l2"]["auto"] is True, "a feed row with no client platform is not a hand move"
    assert e["l1"]["auto"] is False and e["w1"]["auto"] is False
    assert e["x1"]["auto"] is True and e["x3"]["auto"] is False
    assert (e["w1"]["week"], e["l1"]["week"], e["a1"]["week"]) == (0, 2, 2)


def test_claims_votes_offers_and_dedupe(log):
    e = by_id(log)
    assert [x["id"] for x in log["events"]].count("a1") == 1
    assert [x["id"] for x in log["events"]].count("x1") == 1
    assert (e["x1"]["kind"], e["x1"]["detail"], e["x1"]["player_id"], e["x1"]["drop_id"]) == (
        "claim_failed", "invalidplayersource", 666, 777)
    assert (e["x2"]["kind"], e["x2"]["detail"]) == ("claim_canceled", None)
    assert (e["x3"]["kind"], e["x3"]["detail"], e["x3"]["related"]) == ("vote", "uphold", "p1")
    assert (e["x4"]["kind"], e["x4"]["other_team_id"], e["x4"]["detail"]) == ("offer", 6, "canceled")
    assert (e["x8"]["other_team_id"], e["x8"]["detail"]) == (2, "proposed"), "a PENDING original row is not proof the offer is open"
    assert (e["x9"]["kind"], e["x9"]["team_id"], e["x9"]["at"], e["x9"]["week"], e["x9"]["for_week"], e["x9"]["auto"]) == (
        "lineup_plan", 7, 1200, 1, 3, False), "a plan is the manager's own move, dated when it was made"
    assert e["x9"]["items"] == [{"player_id": 333, "from_slot": 4, "to_slot": 20}]
    assert "x5" not in e and "x6" not in e and "x7" not in e
    ats = [x["at"] or 0 for x in log["events"]]
    assert ats == sorted(ats, reverse=True)


def test_pending_directions(log):
    assert [(p["id"], p["direction"]) for p in log["pending"]] == [("p9", "out"), ("p7", "in"), ("p8", "league")]


def test_js_twin_matches(log):
    if not shutil.which("node"):
        pytest.skip("node not on PATH")
    script = f"""
import {{ normalize }} from {json.dumps(str(ROOT / 'fantasy' / 'scorebug' / 'wire.js'))};
import {{ readFileSync }} from 'fs';
const c = JSON.parse(readFileSync(0, 'utf8'));
console.log(JSON.stringify(normalize(c.raw, c.teams, c.me, c.starts)));
"""
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True,
                       input=json.dumps({"raw": RAW, "teams": TEAMS, "me": ME, "starts": STARTS}))
    assert json.loads(r.stdout) == json.loads(json.dumps(log))


def test_claim_rates():
    names = {1: {"pos": "D/ST"}, 2: {"pos": "RB"}}
    events = [
        {"kind": "drop", "how": None, "week": 2, "player_id": 1, "team_id": 4, "at": 10},
        {"kind": "add", "how": "fa", "week": 2, "player_id": 1, "team_id": 5, "at": 20},
        {"kind": "drop", "how": None, "week": 2, "player_id": 2, "team_id": 4, "at": 10},
        {"kind": "add", "how": "waiver", "week": 2, "player_id": 2, "team_id": 6, "at": 30},
        {"kind": "drop", "how": "trade", "week": 2, "player_id": 2, "team_id": 6, "at": 40},
    ]
    rates = base_rates(events, names)
    assert rates == {"D/ST": [0, 1], "RB": [1, 1]}, "a trade drop is not a waiver drop"
    assert p_claimed("D/ST", {"D/ST": [0, 11]}) == pytest.approx(1 / 13), "0 of 11 reads as 1 in 13, never 0"
    assert p_claimed("TE", {}) == pytest.approx(0.5)
    assert fits("WR", ["RB/WR/TE"]) and fits("D/ST", ["K", "D/ST"]) and not fits("QB", ["RB/WR/TE"])
