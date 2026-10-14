"""mykcmo: the daily update job asks once per 7 days, never about its own asks."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mykcmo"))

import civicapi  # noqa: E402

DAY = 86400
T0 = 1_790_000_000.0


def report(id_, ts, type_="Sidewalks and Curbs", description="Mud on the curb ramp."):
    return {"id": id_, "name": type_, "issue_type": type_, "status": "new",
            "added_on": str(int(ts)), "description": description}


def ask(id_, ts, target):
    # The city files the "311 Request Update" form under this type.
    return report(id_, ts, "Administration or Questions",
                  f"{civicapi.UPDATE_TEXT} myKCMO app report {target}: ADA Curb Issue at 1 Main St.")


def test_city_type_for_update_request_is_recognized():
    assert civicapi.is_update_request(ask("2", T0, "1"))
    assert not civicapi.is_update_request(report("1", T0))


def test_recent_ask_blocks_a_second_one():
    mine = [report("1", T0), ask("2", T0 + 8 * DAY, "1")]
    assert civicapi.due_for_update(mine, now=T0 + 9 * DAY) == []
    assert [r["id"] for r in civicapi.due_for_update(mine, now=T0 + 16 * DAY)] == ["1"]


def test_update_requests_for_finds_only_asks_naming_the_report():
    mine = [report("1", T0), ask("2", T0, "1"), ask("3", T0, "9"), report("4", T0)]
    assert [r["id"] for r in civicapi.update_requests_for(report("1", T0), mine)] == ["2"]
