"""espn-tx plan: a later week's lineup through ESPN's FUTURE_ROSTER.

A plain ROSTER write for a later week is refused by ESPN (2026-10-04), and
FUTURE_ROSTER is the type its app writes (two rivals used it all season; our
first plan, week 9, verified 2026-10-22). These pin the request body and the
guards with a fake league. No network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fantasy"))

from espncli.client import BENCH, EspnError  # noqa: E402
from espncli.tx import EspnWriter  # noqa: E402

DANIELS, WATSON, VELE = 4426348, 3122840, 4688813


class FakeApi:
    season, league_id = 2026, 1
    creds = {"team_id": 12, "SWID": "{ME}"}

    def __init__(self, week: int, slots: dict[int, int]):
        self.week, self.slots = week, slots

    def league(self, *views, period=None, **kw):
        return {"scoringPeriodId": self.week, "views": views, "period": period}

    def current_week(self, data):
        return self.week

    def roster_entries(self, data, team_id):
        return [{"playerId": p, "lineupSlotId": s} for p, s in self.slots.items()]


def writer(week: int = 7) -> EspnWriter:
    return EspnWriter(FakeApi(week, {WATSON: 0, DANIELS: BENCH, VELE: 4}))  # type: ignore[arg-type]


def test_plan_body_is_a_future_roster_for_the_target_week():
    body = writer().plan_swap(9, DANIELS, WATSON, dry_run=True)["dry_run"]
    assert body["type"] == "FUTURE_ROSTER" and body["scoringPeriodId"] == 9 and body["teamId"] == 12
    assert body["items"] == [
        {"playerId": WATSON, "type": "LINEUP", "fromLineupSlotId": 0, "toLineupSlotId": BENCH},
        {"playerId": DANIELS, "type": "LINEUP", "fromLineupSlotId": BENCH, "toLineupSlotId": 0},
    ]


@pytest.mark.parametrize("week", [6, 7])
def test_this_week_or_earlier_is_refused(week):
    with pytest.raises(EspnError, match="not a later week"):
        writer(7).plan_swap(week, DANIELS, WATSON, dry_run=True)


def test_the_incoming_player_must_be_on_the_bench():
    with pytest.raises(EspnError, match="must be on the bench"):
        writer().plan_swap(9, VELE, WATSON, dry_run=True)
