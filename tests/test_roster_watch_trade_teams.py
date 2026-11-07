"""roster-watch pings on trades that involve a watched team (2026-11-06).

ESPN shows a trade between two other teams only during its veto review. The
first ping is the trade appearing in the pending list; the second is the row
leaving it, with the outcome read off the rosters. Positive control: a trade
between watched team 4 and team 7 pings twice. Controls: a trade between two
unwatched teams and a trade that involves us (team 12) never ping here.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fantasy"))


@pytest.fixture()
def rw():
    loader = importlib.machinery.SourceFileLoader("roster_watch_tt", str(ROOT / "fantasy" / "bin" / "roster-watch"))
    spec = importlib.util.spec_from_loader("roster_watch_tt", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def team(tid, name, players):
    return {"id": tid, "name": name, "roster": {"entries": [
        {"playerId": pid, "playerPoolEntry": {"player": {"fullName": nm}}} for pid, nm in players]}}


def trade(tid, a, b, pa, pb):
    return {"id": tid, "type": "TRADE_ACCEPT", "items": [
        {"type": "TRADE", "playerId": pa, "fromTeamId": a, "toTeamId": b},
        {"type": "TRADE", "playerId": pb, "fromTeamId": b, "toTeamId": a}]}


WATCH = {4: {"id": 4, "name": "Watched"}}
BEFORE = [team(4, "Watched", [(1, "P One")]), team(7, "Seven", [(2, "P Two")]),
          team(9, "Nine", [(3, "P Three")]), team(12, "Us", [(5, "P Five")])]


def test_watched_trade_opens_then_executes(rw):
    state: dict = {}
    ev = rw.watched_trade_events([trade("t1", 4, 7, 1, 2)], BEFORE, WATCH, state, 12)
    assert [e["phase"] for e in ev] == ["opened"]
    assert "Seven gets P One" in rw.watched_trade_head(ev[0])
    assert rw.watched_trade_events([trade("t1", 4, 7, 1, 2)], BEFORE, WATCH, state, 12) == []  # no repeat
    after = [team(4, "Watched", [(2, "P Two")]), team(7, "Seven", [(1, "P One")])]
    ev = rw.watched_trade_events([], after, WATCH, state, 12)
    assert ev[0]["phase"] == "closed" and ev[0]["outcome"] == "executed" and state == {}


def test_vetoed_trade_reads_as_vetoed(rw):
    state: dict = {}
    rw.watched_trade_events([trade("t1", 4, 7, 1, 2)], BEFORE, WATCH, state, 12)
    ev = rw.watched_trade_events([], BEFORE, WATCH, state, 12)
    assert ev[0]["outcome"] == "vetoed or canceled"


@pytest.mark.parametrize("row", [trade("t2", 7, 9, 2, 3), trade("t3", 4, 12, 1, 5)])
def test_unwatched_or_ours_never_pings(rw, row):
    assert rw.watched_trade_events([row], BEFORE, WATCH, {}, 12) == []
