"""kc-civic parsers: Legistar times, iCal unfolding/TZ, and body matching."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "kc-civic"))

from kccivic import edc, legistar  # noqa: E402
from kccivic.model import TZ  # noqa: E402

ICS = (
    "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;TZID=America/Chicago:20261014T093000\r\n"
    "DTEND;TZID=America/Chicago:20261014T123000\r\nUID:1@edckc.com\r\nSUMMARY:TIF Board Meeting\r\n"
    "DESCRIPTION:Agenda\\, and\r\n  more\r\nURL:https://edckc.com/event/tif/\r\n"
    "LOCATION:EDCKC Office\\, 300 Wyandotte\r\nEND:VEVENT\r\n"
    "BEGIN:VEVENT\r\nDTSTART:20261015T140000Z\r\nUID:2@edckc.com\r\nSUMMARY:PIEA Executive Team Meeting\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n"
)


def test_parse_time_pm_and_noon():
    assert legistar.parse_time("2026-10-08T00:00:00", "2:00 PM")[0].hour == 14
    assert legistar.parse_time("2026-10-08T00:00:00", "12:15 PM")[0].hour == 12
    assert legistar.parse_time("2026-10-08T00:00:00", "12:00 AM")[0].hour == 0
    start, known = legistar.parse_time("2026-10-08T00:00:00", None)
    assert (start.hour, known) == (9, False)


def test_ics_unfold_unescape_and_utc():
    evs = edc.parse_ics(ICS)
    assert evs[0]["DESCRIPTION"] == "Agenda, and more"
    assert evs[0]["LOCATION"] == "EDCKC Office, 300 Wyandotte"
    assert evs[0]["DTSTART"] == datetime(2026, 10, 14, 9, 30, tzinfo=TZ)
    assert evs[1]["DTSTART"].astimezone(TZ).hour == 9  # 14:00Z is 09:00 CDT


def test_edc_matches_only_configured_bodies():
    bodies = [{"match": "TIF Board Meeting", "short": "TIF Commission", "tier": "1"}]
    ms = edc.to_meetings(edc.parse_ics(ICS), bodies, 60, now=datetime(2026, 10, 5, tzinfo=TZ))
    assert [m.short for m in ms] == ["TIF Commission"]
    assert ms[0].key == "edc-1@edckc.com" and ms[0].extra["pages"] == ["https://edckc.com/event/tif/"]


def test_legistar_join_link_and_cancel():
    ev = {"EventId": 7, "EventBodyName": "Council ", "EventDate": "2026-10-08T00:00:00",
          "EventTime": "2:00 PM", "EventLocation": "CANCELLED", "EventComment": "Meeting Link: https://us02web.zoom.us/j/845.",
          "EventAgendaFile": None, "EventInSiteURL": "u"}
    m = legistar.to_meeting(ev, {"short": "City Council", "tier": "core", "minutes": 150})
    assert m.join_link == "https://us02web.zoom.us/j/845" and m.cancelled and m.title().startswith("CANCELLED")
    assert (m.end - m.start).seconds == 150 * 60


def test_holds_follow_nth_weekday_skip_dates_and_cutoff():
    from kccivic import holds

    cfg = [{"body": "City Plan Commission", "short": "CPC", "tier": "1", "weekday": "wed", "time": "09:00",
            "nth": [1, 3], "pattern": "1st and 3rd Wed"}]
    now = datetime(2026, 10, 7, 6, 0, tzinfo=TZ)  # 3h before the 10/7 slot: inside the cutoff
    days = [m.start.date().isoformat() for m in holds.generate(cfg, 45, {"2026-11-04"}, now=now)]
    assert days == ["2026-10-21", "2026-11-18"]
    assert holds.hold_key("City Council", datetime(2026, 10, 8).date()) == "hold-city-council-2026-10-08"


def test_drop_stale_holds_spares_an_adopted_event(monkeypatch):
    # 2026-10-08: a prep pass resurrected an adopted hold record, and the
    # hold drop then deleted the published Council meeting it pointed at.
    from kccivic import cli, gcal
    deleted = []
    monkeypatch.setattr(gcal, "delete", lambda cal, eid: deleted.append(eid))
    soon = datetime.now(TZ).isoformat()
    st = {"synced": {
        "legistar-1": {"event_id": "ev1", "start": soon},
        "hold-city-council-x": {"event_id": "ev1", "start": soon},
        "hold-city-council-y": {"event_id": "ev2", "start": soon},
    }}
    cli.drop_stale_holds({}, st, set(), dry=False)
    assert deleted == ["ev2"]
    assert set(st["synced"]) == {"legistar-1"}
