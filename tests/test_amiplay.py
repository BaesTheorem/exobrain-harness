"""Characterization tests for the AMI Play client: request shapes and envelope handling.

They drive AmiClient through a fake transport, so nothing touches the network.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ami-play"))

from amiplay.api import AmiClient, AmiError  # noqa: E402
from amiplay.store import Session  # noqa: E402


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, json.loads(body) if body else None, headers))
        status, payload = self.responses.pop(0)
        return status, json.dumps(payload).encode()


@pytest.fixture
def session(tmp_path):
    return Session(tmp_path / "session.json")


def make(session, *responses):
    t = FakeTransport(responses)
    return AmiClient(session, env="prod", transport=t), t


def test_session_generates_stable_device_uuid(tmp_path):
    first = Session(tmp_path / "s.json").device_uuid
    assert Session(tmp_path / "s.json").device_uuid == first
    assert oct((tmp_path / "s.json").stat().st_mode & 0o777) == "0o600"


def test_get_sends_query_and_post_sends_json_body(session):
    session.set_login(42, "tok")
    client, t = make(session, (200, {"result": 0, "walletBalance": 500}), (200, {"result": 0, "locations": []}))
    client.funds(81943)
    method, url, body, headers = t.calls[0]
    assert method == "GET" and body is None
    assert url.startswith("https://mobile-v2.amientertainment.net/mobileserver/mobile/user/fundsBalance?")
    assert "playerId=42" in url and "authentication=tok" in url and "locationId=81943" in url
    client.venues_search("zoo", {"lat": 39.1, "lng": -94.6}, page=2, per_page=5)
    method, url, body, headers = t.calls[1]
    assert method == "POST" and headers["Content-Type"] == "application/json"
    assert body == {"playerId": 42, "authentication": "tok", "geocode": {"lat": 39.1, "lng": -94.6}, "name": "zoo", "page": 2, "resultsPerPage": 5}


def test_nonzero_result_raises_named_error(session):
    client, _ = make(session, (200, {"result": 24, "message": "InvalidLocationId"}))
    with pytest.raises(AmiError) as info:
        client.venue(1)
    assert info.value.code == 24 and info.value.name == "INVALID_LOCATION_ID"
    assert not info.value.forces_logout


def test_invalid_authentication_forces_logout(session):
    session.set_login(1, "dead")
    client, _ = make(session, (200, {"result": 9, "message": "InvalidAuthentication"}))
    with pytest.raises(AmiError) as info:
        client.playlists()
    assert info.value.forces_logout


def test_http_error_is_transport_error(session):
    client, _ = make(session, (404, {"status": 404, "error": "Not Found"}))
    with pytest.raises(AmiError) as info:
        client.play_queue("x")
    assert info.value.code is None and info.value.http_status == 404


def test_login_stores_credentials(session):
    client, t = make(session, (200, {"result": 0, "playerId": 7, "authentication": "abc"}))
    client.login("a@b.c", "pw")
    assert t.calls[0][2] == {"id": "a@b.c", "password": "pw"}
    assert session.logged_in and session.player_id == 7 and session.auth_token == "abc"
    assert Session(session.path).player_id == 7


def test_auth_required_without_login(session):
    client, t = make(session)
    with pytest.raises(AmiError):
        client.playlists()
    assert t.calls == []


ZOO_JUKEBOX = {"deviceId": 23184, "deviceType": 1, "basePrice": 66, "priorityPrice": 132, "downloadPrice": 66, "videoPrice": 66, "isFreeplay": False, "currency": "USD", "dpLevelUsed": 1, "dpAdditionalCredits": 1, "dpEstPosInQueue": 3}


def test_price_matches_app_formula():
    assert AmiClient.price_in_pennies(ZOO_JUKEBOX, local=True) == 66
    assert AmiClient.price_in_pennies(ZOO_JUKEBOX, local=False) == 132
    assert AmiClient.price_in_pennies(ZOO_JUKEBOX, local=False, priority=True) == 264
    assert AmiClient.price_in_pennies(ZOO_JUKEBOX, local=False, video=True) == 198
    assert AmiClient.price_in_pennies({**ZOO_JUKEBOX, "isFreeplay": True}) == 0
    assert AmiClient.pennies_to_credits(ZOO_JUKEBOX, 264) == 4


def test_purchase_body_matches_app(session):
    session.set_login(42, "tok")
    client, t = make(session, (200, {"result": 0, "transactionId": 9, "status": "COMPLETE_SUCCESS"}))
    song = {"songId": 13619506, "local": False}
    client.purchase(81943, ZOO_JUKEBOX, song, priority=True, client_purchase_id="cp-1")
    body = t.calls[0][2]
    assert t.calls[0][1].endswith("/transaction/v4/purchase")
    assert body["destinationLocationId"] == 81943
    assert body["destinationDeviceId"] == "23184" and body["destinationDeviceType"] == 1
    assert body["itemId"] == 13619506 and body["itemType"] == 1
    assert body["amount"] == 264 and body["priorityPlay"] is True
    assert body["selectionCode"] == 5510 and body["sourceDeviceType"] == 6 and body["currency"] == "USD"
    assert body["dpLevelUsed"] == 1 and body["dpAdditionalCredits"] == 1 and body["dpEstPosInQueue"] == 3
    assert body["clientPurchaseId"] == "cp-1"
    assert len(body["clientPurchaseTime"]) == 24  # yyyy-MM-ddTHH:mm:ss+HHMM


def test_song_detail_uses_destination_device_keys(session):
    client, t = make(session, (200, {"result": 0, "songs": [{"songId": 1}]}))
    assert client.song(1, 23184) == {"songId": 1}
    url = t.calls[0][1]
    assert "destinationDeviceId=23184" in url and "destinationDeviceTypeId=1" in url


def test_artist_sort_keys(session):
    client, t = make(session, (200, {"result": 0, "songs": []}))
    client.artist(5, 23184, media="songs", sort="popularity")
    url = t.calls[0][1]
    assert "sortBy=song.popularity" in url and "sortOrder=desc" in url and "mediaType=songs" in url
