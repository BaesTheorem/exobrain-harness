"""Characterization tests for the Meetup CLI: ref parsing, date windows, normalization, and
the client's request shapes and pagination.

The client is driven through a fake transport, so nothing touches the network.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "meetup"))

from meetupcli import cli, store  # noqa: E402
from meetupcli.api import MeetupClient, MeetupError  # noqa: E402
from meetupcli.model import normalize_event, normalize_group, parse_event_ref, parse_group_ref, window  # noqa: E402

TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 9, 6, 10, 0, tzinfo=TZ)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, json.loads(body) if body else None, headers))
        status, payload = self.responses.pop(0)
        return status, (payload if isinstance(payload, bytes) else json.dumps(payload).encode())


def make(*responses, cookie=None):
    t = FakeTransport(*responses)
    return MeetupClient(cookie=cookie, transport=t, page_size=5), t


def node(i, **extra):
    base = {
        "id": str(i), "title": f"Event {i}", "dateTime": "2026-09-10T18:00:00-05:00",
        "eventType": "PHYSICAL", "eventUrl": f"https://www.meetup.com/g/events/{i}/",
        "group": {"id": "1", "name": "G", "urlname": "g"}, "going": {"totalCount": i},
    }
    base.update(extra)
    return base


def page(key, ids, has_next, cursor="NQ=="):
    return {"data": {key: {"pageInfo": {"hasNextPage": has_next, "endCursor": cursor}, "edges": [{"node": node(i)} for i in ids]}}}


# -- refs ------------------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["316119292", "https://www.meetup.com/data-science-kc/events/316119292/",
                                 "meetup.com/x/events/316119292?utm=1", " 316119292 "])
def test_parse_event_ref_accepts_ids_and_urls(ref):
    assert parse_event_ref(ref) == "316119292"


def test_parse_event_ref_rejects_junk():
    with pytest.raises(ValueError):
        parse_event_ref("https://www.meetup.com/pykc/")


@pytest.mark.parametrize("ref", ["pykc", "https://www.meetup.com/pykc/", "https://www.meetup.com/pykc/events/123/",
                                 "meetup.com/pykc?x=1", "/pykc/"])
def test_parse_group_ref_accepts_urlnames_and_urls(ref):
    assert parse_group_ref(ref) == "pykc"


@pytest.mark.parametrize("ref", ["https://www.meetup.com/find/?keywords=ai", "a b", "", "x/y"])
def test_parse_group_ref_rejects_site_pages_and_junk(ref):
    with pytest.raises(ValueError):
        parse_group_ref(ref)


# -- dates -----------------------------------------------------------------------------------


def test_window_days_counts_from_now_to_end_of_day():
    assert window(days=7, tz=TZ, now=NOW) == ("2026-09-06T10:00:00-05:00", "2026-09-13T23:59:59-05:00")


def test_window_explicit_dates_and_words():
    assert window(start="2026-09-10", end="2026-09-12", tz=TZ, now=NOW) == ("2026-09-10T00:00:00-05:00", "2026-09-12T23:59:59-05:00")
    assert window(end="tomorrow", tz=TZ, now=NOW) == (None, "2026-09-07T23:59:59-05:00")
    assert window(start="+2d", days=1, tz=TZ, now=NOW) == ("2026-09-08T00:00:00-05:00", "2026-09-09T23:59:59-05:00")
    assert window(start="2026-09-10 18:30", tz=TZ, now=NOW) == ("2026-09-10T18:30:00-05:00", None)
    assert window(tz=TZ, now=NOW) == (None, None)


def test_window_rejects_bad_dates():
    with pytest.raises(ValueError):
        window(start="next tuesday", tz=TZ, now=NOW)


# -- client ----------------------------------------------------------------------------------


def test_event_search_builds_filter_and_pages_until_limit():
    client, t = make((200, page("eventSearch", [1, 2, 3, 4, 5], True, "NQ==")),
                     (200, page("eventSearch", [6, 7, 8, 9, 10], True, "MTA=")))
    got = client.event_search("AI", 39.1, -94.6, radius=10, start="2026-09-06T00:00:00-05:00", sort="DATETIME", limit=7)
    assert [n["id"] for n in got] == ["1", "2", "3", "4", "5", "6", "7"]
    assert len(t.calls) == 2, "stops once the limit is reached even though hasNextPage is true"
    method, url, body, headers = t.calls[0]
    assert method == "POST" and url == "https://www.meetup.com/gql2"
    assert headers["Content-Type"] == "application/json" and "Cookie" not in headers
    assert body["variables"] == {
        "filter": {"query": "AI", "lat": 39.1, "lon": -94.6, "radius": 10, "startDateRange": "2026-09-06T00:00:00-05:00"},
        "sort": {"sortField": "DATETIME"}, "first": 5, "after": None,
    }
    assert t.calls[1][2]["variables"]["after"] == "NQ=="
    assert t.calls[1][2]["variables"]["first"] == 2


def test_event_search_stops_on_last_page_and_empty_query_is_refused():
    client, t = make((200, page("eventSearch", [1, 2], False)))
    assert len(client.event_search("x", 0, 0, limit=50)) == 2
    assert len(t.calls) == 1
    with pytest.raises(MeetupError):
        client.event_search("   ", 0, 0)


def test_graphql_errors_and_bad_http_raise():
    client, _ = make((200, {"errors": [{"message": "Validation error (FieldUndefined@[x])"}]}))
    with pytest.raises(MeetupError) as info:
        client.location_search("kc")
    assert "FieldUndefined" in str(info.value)
    client, _ = make((403, b"<html>blocked</html>"))
    with pytest.raises(MeetupError) as info:
        client.location_search("kc")
    assert info.value.http_status == 403 and "non-JSON" in str(info.value)


def test_personal_calls_need_a_cookie_and_detect_rejection():
    client, t = make()
    with pytest.raises(MeetupError) as info:
        client.my_events()
    assert info.value.auth and not t.calls, "no request is made without a cookie"
    client, t = make((200, {"data": {"self": None}}), cookie="MEETUP_MEMBER=x")
    with pytest.raises(MeetupError) as info:
        client.self_member()
    assert info.value.auth
    assert t.calls[0][3]["Cookie"] == "MEETUP_MEMBER=x"


def test_my_events_carries_rsvp_state_and_mutations_surface_payload_errors():
    client, _ = make((200, {"data": {"self": {"memberEvents": {"pageInfo": {"hasNextPage": False}, "edges": [{"rsvpState": "YES", "node": node(1)}]}}}}), cookie="c=1")
    got = client.my_events()
    assert got[0]["myRsvp"] == "YES"
    client, t = make((200, {"data": {"rsvp": {"errors": [{"code": "FULL", "field": None, "message": "Event is full"}], "rsvp": None}}}), cookie="c=1")
    with pytest.raises(MeetupError) as info:
        client.rsvp("5", True, guests=2)
    assert "Event is full" in str(info.value)
    assert t.calls[0][2]["variables"] == {"input": {"eventId": "5", "response": "YES", "guestsCount": 2}}


# -- normalization ---------------------------------------------------------------------------


def test_normalize_event_flattens_venue_fee_and_extras():
    online = normalize_event(node(1, isOnline=True, venue={"name": "Online event", "venueType": "online", "lat": -8.5, "lon": 179.2}))
    assert online["online"] and online["venue"] is None and online["free"] and online["going"] == 1
    assert "hosts" not in online, "detail-only fields stay absent on search rows"
    paid = normalize_event(node(2, feeSettings={"amount": 15.0, "currency": "USD"}, maxTickets=0,
                                venue={"name": "Bar", "address": "1 Main", "city": "KC", "state": "MO", "lat": 39.0, "lon": -94.0},
                                eventHosts=[{"name": "Sam"}, {"name": None}], topics={"edges": [{"node": {"name": "AI"}}]},
                                series={"description": "Every week on Monday"}, waitlist={"totalCount": 4}))
    assert paid["fee"] == {"amount": 15.0, "currency": "USD"} and not paid["free"]
    assert paid["maxTickets"] is None, "0 means unlimited"
    assert paid["venue"]["name"] == "Bar" and paid["venue"]["lat"] == 39.0
    assert paid["hosts"] == ["Sam"] and paid["topics"] == ["AI"] and paid["series"] == "Every week on Monday" and paid["waitlist"] == 4
    assert paid["group"]["url"] == "https://www.meetup.com/g/"


def test_normalize_group_folds_stats_and_connections():
    g = normalize_group({
        "id": "9", "name": "PyKC", "urlname": "pythonkc", "city": "Kansas City", "state": "MO", "isPrivate": False,
        "memberships": {"totalCount": 1200}, "stats": {"eventRatings": {"average": 4.7, "totalRatings": 30}},
        "topicCategory": {"name": "Technology"}, "activeTopics": [{"name": "Python"}], "organizer": {"name": "Org"},
        "upcoming": {"totalCount": 2, "edges": [{"node": node(1)}]},
        "past": {"totalCount": 400, "edges": [{"node": {"id": "0", "title": "Old", "dateTime": "2026-08-01T18:00:00-05:00"}}]},
    })
    assert g["url"] == "https://www.meetup.com/pythonkc/" and g["members"] == 1200 and g["rating"] == 4.7
    assert g["category"] == "Technology" and g["topics"] == ["Python"] and g["organizer"] == "Org"
    assert g["upcomingCount"] == 2 and g["upcoming"][0]["id"] == "1"
    assert g["pastCount"] == 400 and g["lastEvent"]["title"] == "Old"


# -- store -----------------------------------------------------------------------------------


def test_clean_cookie_strips_header_prefix_and_newlines():
    assert store.clean_cookie("Cookie: a=b;\n c=d\n") == "a=b; c=d"
    assert store.clean_cookie("a=b; c=d") == "a=b; c=d"


def test_save_cookie_writes_0600_and_load_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "SECRETS", tmp_path)
    monkeypatch.setattr(store, "COOKIE_PATH", tmp_path / "cookie.txt")
    monkeypatch.setattr(store, "HARNESS_ENV", tmp_path / "nope.env")
    monkeypatch.delenv("MEETUP_COOKIE", raising=False)
    with pytest.raises(ValueError):
        store.save_cookie("not a cookie")
    path = store.save_cookie("cookie: MEETUP_MEMBER=abc; x=y\n")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert store.load_cookie() == "MEETUP_MEMBER=abc; x=y"
    monkeypatch.setenv("MEETUP_COOKIE", "override=1")
    assert store.load_cookie() == "override=1"
    assert store.clear_cookie() and not path.exists()


def test_home_location_env_override(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "HARNESS_ENV", tmp_path / "nope.env")
    monkeypatch.delenv("MEETUP_HOME", raising=False)
    assert store.home_location() == store.HOME_DEFAULT
    monkeypatch.setenv("MEETUP_HOME", "40.7,-74.0,NYC")
    assert store.home_location() == ("NYC", 40.7, -74.0)
    monkeypatch.setenv("MEETUP_HOME", "garbage")
    with pytest.raises(ValueError):
        store.home_location()


# -- cli -------------------------------------------------------------------------------------


def test_cli_event_json_prints_normalized_record(monkeypatch, capsys):
    client, _ = make((200, {"data": {"events": [node(316119292, description="Talk", eventHosts=[{"name": "N"}])]}}))
    monkeypatch.setattr(cli, "make_client", lambda: client)
    assert cli.main(["event", "https://www.meetup.com/x/events/316119292/", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["id"] == "316119292" and out["hosts"] == ["N"] and out["description"] == "Talk"


def test_cli_exit_codes(monkeypatch, capsys):
    client, _ = make()
    monkeypatch.setattr(cli, "make_client", lambda: client)
    monkeypatch.setattr(store, "load_cookie", lambda: None)
    assert cli.main(["my-events"]) == 3
    assert cli.main(["event", "not-an-id"]) == 2
    assert "meetup:" in capsys.readouterr().err
