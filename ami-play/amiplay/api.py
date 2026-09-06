"""HTTP client for the AMI Play "mobileserver" API.

Wire rules, as recovered from the app's Kotlin core (KMMApiClient / RequestExt.kt):

- Base URL per environment is ``https://<host>.net/mobileserver/mobile/``; every path is
  appended to it verbatim.
- GET sends the parameters as a query string; every other verb sends them as a JSON body
  with ``Content-Type: application/json``. There are no auth headers.
- Auth rides *inside* the parameters as ``playerId`` (int) and ``authentication`` (string),
  both returned by ``user/login``.
- Every response is JSON with an integer ``result``; 0 is success, anything else is a
  server error whose name lives in RESULT_CODES. Codes 9 and 26 mean the session is dead.
- Device identity for menus and check-in is a client-generated UUID sent as ``deviceUUID``.

Only the stdlib is used, so the CLI runs on the system python with no venv.

INVARIANTS:
- ``purchase()`` is the only method that spends credits. Everything else is read-only or
  edits the player's own favorites/playlists/check-in state.
- ``_call`` never raises on ``result != 0`` for callers that pass ``ok=`` explicitly; the
  default success test is ``result == 0`` exactly like the app's ``Request.isResponseSuccess``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from amiplay.store import Session

APP_VERSION = "5.2.0"

# (mobile api host, iris host, trivia schedule host, tournament host); ".net" is appended.
ENVIRONMENTS: dict[str, dict[str, str]] = {
    "prod": {
        "url": "https://mobile-v2.amientertainment.net/mobileserver/mobile/",
        "iris": "mobile-iris.amientertainment.net:1235",
        "schedule": "https://tapcontent.amientertainment.net/tapcontentwebservices/external/triviaScheduleExt/getForLocations/trivia",
        "tournament": "https://tournament.amientertainment.net/tournamentwebservices/external/tournament/",
    },
    "qa": {
        "url": "https://mobile01-v2.qa.amientertainment.net/mobileserver/mobile/",
        "iris": "mobile-iris01.qa.amientertainment.net:1235",
        "schedule": "https://tapcontent01.qa.amientertainment.net/tapcontentwebservices/external/triviaScheduleExt/getForLocations/trivia",
        "tournament": "https://tournament01.qa.amientertainment.net/tournamentwebservices/external/tournament/",
    },
    "eng": {
        "url": "https://mobile01-v2.eng.amientertainment.net/mobileserver/mobile/",
        "iris": "mobile-iris01.eng.amientertainment.net:1235",
        "schedule": "https://tapcontent01.eng.amientertainment.net/tapcontentwebservices/external/triviaScheduleExt/getForLocations/trivia",
        "tournament": "https://tournament01.eng.amientertainment.net/tournamentwebservices/external/tournament/",
    },
}

RESULT_CODES: dict[int, str] = {  # from the app's ServerResultCode enum
    -11: 'FAILED_JOIN_TRIVIA',
    -10: 'TRIVIA_OFFLINE',
    -9: 'USER_PAYMENT_UNFINISHED',
    -8: 'PAYMENT_PROVIDER_APP_ERROR',
    -7: 'VENUE_OFFLINE',
    -6: 'PAYMENT_CANCELLED',
    -4: 'INVALID_REQUEST',
    -3: 'TIMEOUT',
    -2: 'PAYMENT_PROVIDER_EXCEPTION',
    0: 'SUCCESS',
    1: 'FAILED',
    2: 'INVALID_ARGUMENT',
    3: 'INVALID_USERNAME',
    4: 'DUPLICATE_USERNAME',
    5: 'INVALID_EMAIL',
    6: 'DUPLICATE_EMAIL',
    7: 'INVALID_PASSWORD',
    8: 'INCORRECT_PASSWORD',
    9: 'INVALID_AUTHENTICATION',
    10: 'INSUFFICIENT_BALANCE',
    11: 'DUPLICATE_GUID',
    12: 'MISSING_GUID',
    13: 'MISSING_ARGUMENT',
    14: 'DUPLICATE_CARD',
    15: 'EXISTING_CARD',
    16: 'MISSING_CARD',
    17: 'UNKNOWN_BAR_LINK_ACCOUNT',
    18: 'UNKNOWN_EMAIL',
    19: 'MISSING_PLAYER_ID',
    20: 'MISSING_GAME',
    21: 'DUPLICATE_TOKEN_UPDATE',
    22: 'INVALID_PURCHASE_ID',
    23: 'UNABLE_TO_MODIFY_PURCHASE',
    24: 'INVALID_LOCATION_ID',
    25: 'INVALID_DEVICE',
    26: 'INVALID_PLAYER_ID',
    27: 'CARD_AUTH_DECLINED',
    28: 'CARD_AUTH_ERROR',
    29: 'CARD_AUTH_INVALID_CALLBACK',
    30: 'CARD_AUTH_REVIEW',
    31: 'INVALID_PROMO_CODE',
    32: 'PROMO_CODE_UNAVAILABLE',
    33: 'INVALID_TRANSACTION_ID',
    34: 'ACCOUNT_NOT_VALIDATED',
    35: 'INVALID_VALIDATION_TOKEN',
    36: 'ACCOUNT_ALREADY_VALIDATED',
    40: 'INAPPROPRIATE_USERNAME',
    41: 'FREE_PLAY_NO_LONGER_AVAILABLE',
    42: 'FREE_PLAY_NOW_AVAILABLE',
    43: 'INVALID_PURCHASE_TYPE_ID',
    44: 'VIDEO_PLAY_NOT_AVAILABLE',
    45: 'INCORRECT_ANSWER',
    46: 'NEGATIVE_BONUS_BALANCE',
    47: 'INCOMPLETE_PURCHASE',
    49: 'PLAYLIST_TITLE_TOO_LONG',
    50: 'MAX_ALLOWED_WALLET_EXCEEDED',
    53: 'ACCOUNT_LOCKED',
    54: 'PAYMENT_CHARGE_IN_PROGRESS',
    56: 'INVALID_LOCATION_FOR_PROMO',
    57: 'EXPIRED_PROMO_CODE',
    58: 'MAXIMUM_PROMOS_REACHED',
    59: 'INVALID_PURCHASE',
    60: 'INVALID_PROMO_CODE_TYPE',
    61: 'INVALID_PROMO_REUSE',
    62: 'FRIEND_REFERRAL_CODE_DOES_NOT_EXIST',
    63: 'INVALID_FRIEND_REFERRAL_CODE',
    64: 'EXPIRED_FRIEND_REFERRAL_CODE',
    65: 'FRIEND_REFERRAL_CODE_DEVICE_UUID_ALREADY_EXISTS',
    66: 'MISSING_DEVICE_UUID',
    67: 'VIRTUAL_COIN_MISMATCHED_CURRENCY',
    68: 'INVALID_AUTH_TOKEN',
    73: 'FRIEND_REFER_STATUS_FAILED',
    74: 'INVALID_PROMO_ID',
    75: 'PROMO_REDEMPTION_FAILED',
    104: 'SSO_MALFORMED_TOKEN',
    500: 'SSO_INVALID_PROVIDER',
    533: 'INVALID_PRICING',
}

FORCE_LOGOUT_CODES = {9, 26}

# Where a play was picked from; the app reports it with every purchase.
SELECTION_CODES: dict[str, int] = {
    "now_playing": 1,
    "playlist": 5010,
    "favorited": 5100,
    "favorited_play_all": 5110,
    "recently_played": 5200,
    "recently_played_play_all": 5210,
    "transactions": 5300,
    "local_albums": 5400,
    "local_albums_play_all": 5410,
    "search_song": 5510,
    "predictive_search_song": 5515,
    "search_artist": 5520,
    "search_artist_play_all": 5521,
    "predictive_search_artist": 5525,
    "search_album": 5530,
    "search_album_play_all": 5531,
    "album_notification": 5532,
    "predictive_search_album": 5535,
    "top40_artists": 5610,
    "top40_artists_play_all": 5611,
    "top40_songs": 5620,
    "top40_songs_play_all": 5621,
    "featured_playlists": 5700,
    "featured_playlists_play_all": 5701,
    "branded_charts": 5800,
    "nsm_charts": 5850,
    "more_from": 5900,
    "hit_videos": 6000,
    "staff_favorites": 6100,
    "staff_favorites_play_all": 6101,
}

DEVICE_TYPE_MUSIC = 1
DEVICE_TYPE_TRIVIA = 4
DEVICE_TYPE_AC_GAME = 9
DEVICE_TYPE_NAMES = {1: "jukebox", 4: "trivia", 9: "arcade"}

# transaction/v4/purchase itemType (Transaction.Purchase.Type)
ITEM_TYPE_SONG = 1
ITEM_TYPE_VIDEO = 2
ITEM_TYPE_AC_GAME = 40
SOURCE_DEVICE_TYPE_MOBILE = 6

Params = dict[str, Any]


class AmiError(Exception):
    """A non-success ``result`` from the server, or a transport failure."""

    def __init__(self, code: int | None, message: str, payload: Params | None = None, http_status: int | None = None):
        self.code = code
        self.name = RESULT_CODES.get(code, "UNKNOWN") if code is not None else "TRANSPORT"
        self.message = message
        self.payload = payload or {}
        self.http_status = http_status
        super().__init__(str(self))

    def __str__(self) -> str:
        if self.code is None:
            return f"transport error: {self.message}"
        return f"server result {self.code} ({self.name}): {self.message}"

    @property
    def forces_logout(self) -> bool:
        return self.code in FORCE_LOGOUT_CODES


def server_time_now() -> str:
    """``yyyy-MM-dd'T'HH:mm:ssZ`` in local time, the app's DateFormatType.ToServer."""
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


class AmiClient:
    def __init__(
        self,
        session: Session,
        env: str | None = None,
        timeout: float = 25.0,
        transport: Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]] | None = None,
    ):
        self.session = session
        self.env = env or session.env
        if self.env not in ENVIRONMENTS:
            raise ValueError(f"unknown environment {self.env!r}; pick one of {', '.join(ENVIRONMENTS)}")
        self.base = ENVIRONMENTS[self.env]["url"]
        self.timeout = timeout
        self._transport = transport or self._urllib_transport
        self.last_response: Params = {}

    # -- transport ---------------------------------------------------------------------------

    def _urllib_transport(self, method: str, url: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise AmiError(None, f"{method} {url}: {e}") from e

    def _call(self, method: str, path: str, params: Params | None = None, ok: Callable[[int], bool] | None = None) -> Params:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        url = path if path.startswith("http") else self.base + path
        headers = {"User-Agent": f"AMI Play/{APP_VERSION} (amiplay cli)", "Accept": "application/json"}
        body = None
        if method.upper() == "GET":
            if params:
                url += "?" + urllib.parse.urlencode({k: _query_value(v) for k, v in params.items()})
        else:
            headers["Content-Type"] = "application/json"
            body = json.dumps(params).encode()
        status, raw = self._transport(method.upper(), url, body, headers)
        try:
            data = json.loads(raw.decode() or "{}")
        except ValueError:
            raise AmiError(None, f"non-JSON response (HTTP {status}) from {path}: {raw[:200]!r}", http_status=status) from None
        if not isinstance(data, dict):
            data = {"value": data}
        self.last_response = data
        if status < 200 or status >= 300:
            raise AmiError(None, f"HTTP {status} from {path}: {data.get('error') or data.get('message') or raw[:200]!r}", data, status)
        result = data.get("result")
        if result is None:
            return data
        is_ok = ok or (lambda code: code == 0)
        if not is_ok(int(result)):
            raise AmiError(int(result), str(data.get("message") or ""), data, status)
        return data

    def get(self, path: str, params: Params | None = None) -> Params:
        return self._call("GET", path, params)

    def post(self, path: str, params: Params | None = None) -> Params:
        return self._call("POST", path, params)

    # -- parameter helpers (RequestExt.kt) ---------------------------------------------------

    def _auth(self, required: bool = True) -> Params:
        if not self.session.logged_in:
            if required:
                raise AmiError(None, "not logged in; run `ami-play login` first")
            return {}
        return {"playerId": self.session.player_id, "authentication": self.session.auth_token}

    @staticmethod
    def _device(device_id: str | int | None, device_type: int = DEVICE_TYPE_MUSIC, key: str = "device", type_suffix: str = "") -> Params:
        if device_id is None:
            return {}
        return {f"{key}Id": str(device_id), f"{key}Type{type_suffix}": device_type}

    def _device_uuid(self) -> Params:
        return {"deviceUUID": self.session.device_uuid}

    @staticmethod
    def _geocode(geocode: dict[str, float] | None) -> Params:
        if not geocode:
            return {}
        return {"geocode": {"lat": float(geocode["lat"]), "lng": float(geocode["lng"])}}

    @staticmethod
    def _page(page: int = 1, per_page: int = 20) -> Params:
        return {"page": int(page), "resultsPerPage": int(per_page)}

    # sort name -> (server field, default order); the server rejects anything else
    SORTS: dict[str, tuple[str, str]] = {
        "title": ("title", "asc"),
        "popularity": ("popularity", "desc"),
        "year": ("releaseYear", "desc"),
        "track": ("trackOrder", "asc"),
    }

    @classmethod
    def _sort(cls, media: str | None, sort: str | None, order: str | None) -> Params:
        """``sortBy`` is ``<singular media>.<field>`` (``song.title``); ``sortOrder`` is asc/desc."""
        if not sort:
            return {}
        if sort not in cls.SORTS:
            raise ValueError(f"unknown sort {sort!r}; choose from {', '.join(cls.SORTS)}")
        field, default_order = cls.SORTS[sort]
        singular = (media or "songs").rstrip("s")
        return {"sortBy": f"{singular}.{field}", "sortOrder": order or default_order}

    def _device_info(self) -> Params:
        return {
            "deviceInfo": {
                "osVersion": "14",
                "mobileApp": "BarLink",
                "os": "Android",
                "uuid": self.session.device_uuid,
                "language": "en",
                "mobileAppVersion": APP_VERSION,
            }
        }

    # -- account -----------------------------------------------------------------------------

    def login(self, email: str, password: str) -> Params:
        data = self.post("user/login", {"id": email, "password": password})
        if "playerId" not in data or "authentication" not in data:
            raise AmiError(None, f"login response lacked playerId/authentication: {data}")
        self.session.set_login(int(data["playerId"]), str(data["authentication"]), email)
        self.session.env = self.env
        self.session.save()
        return data

    def login_sso(self, provider: str, provider_token: str) -> Params:
        data = self.post("SSO/v2/login", {"provider": provider, "providerToken": provider_token})
        if "playerId" not in data or "authentication" not in data:
            raise AmiError(None, f"SSO login response lacked playerId/authentication: {data}")
        self.session.set_login(int(data["playerId"]), str(data["authentication"]))
        self.session.env = self.env
        self.session.save()
        return data

    def logout(self) -> None:
        try:
            self.post("user/logout", self._auth())
        finally:
            self.session.clear_login()
            self.session.save()

    def reset_password(self, email: str) -> Params:
        return self.post("password/v2/reset", {"email": email})

    def user(self) -> Params:
        return self.post("user/v2/get", {**self._auth(), **self._device_info()})

    def funds(self, location_id: int | None = None) -> Params:
        return self.get("user/fundsBalance", {**self._auth(), "locationId": location_id})

    def transactions(self, page: int = 1, per_page: int = 20, purchase_types: list[int] | None = None) -> Params:
        return self.post("transaction/v3/get", {**self._auth(), **self._page(page, per_page), "purchaseTypes": purchase_types})

    def referral_amount_cents(self) -> int:
        return int(self.get("user/refer/amount").get("amount", 0))

    def validation_rules(self) -> Params:
        return self.get("user/getAccountValidationRules")

    def notification_preferences(self) -> Params:
        return self.get("user/getNotificationPreferences", self._auth())

    # -- venues ------------------------------------------------------------------------------

    def venues_search(
        self,
        name: str | None = None,
        geocode: dict[str, float] | None = None,
        page: int = 1,
        per_page: int = 20,
        device_types: list[int] | None = None,
    ) -> list[Params]:
        params = {
            **self._auth(required=False),
            **self._geocode(geocode),
            "name": name or None,
            **self._page(page, per_page),
            "deviceTypes": device_types,
        }
        return list(self.post("location/v3/search", params).get("locations", []))

    def venues_recent(self, geocode: dict[str, float] | None = None) -> list[Params]:
        return list(self.post("location/v3/recent", {**self._auth(), **self._geocode(geocode)}).get("locations", []))

    def venues_favorites(self, geocode: dict[str, float] | None = None) -> list[Params]:
        return list(self.post("favorites/locations/v3/get", {**self._auth(), **self._geocode(geocode)}).get("locations", []))

    def venue_set_favorite(self, location_id: int, favorite: bool = True) -> Params:
        return self.post("favorites/locations/set", {**self._auth(), "locationId": int(location_id), "favorite": bool(favorite)})

    def venue(self, location_id: int) -> Params:
        return self.post(f"location/id/{int(location_id)}", self._auth(required=False))

    def checkin(self, location_id: int, geocode: dict[str, float] | None = None) -> Params:
        params = {**self._auth(), "locationId": int(location_id), **self._geocode(geocode), **self._device_uuid()}
        return self.post("location/checkin", params)

    def checkout(self, geocode: dict[str, float] | None = None) -> Params:
        return self.post("location/checkout", {**self._auth(), **self._geocode(geocode), **self._device_uuid()})

    def redeem_promo(self, location_id: int, code: str) -> Params:
        return self.post("promo/v2/redeemCode", {**self._auth(), "locationId": int(location_id), "promoCode": code})

    # -- jukebox state -----------------------------------------------------------------------

    def device(self, device_id: str | int, device_type: int = DEVICE_TYPE_MUSIC, include_song: bool = True) -> Params:
        return self.get(f"device/get/{device_id}", {**self._auth(required=False), "includeSong": include_song, "deviceType": device_type})

    def play_queue(self, device_id: str | int, device_type: int = DEVICE_TYPE_MUSIC) -> Params:
        return self.get(f"device/getPlayQueue/{device_type}/{device_id}", {**self._auth(required=False), "includeSong": True})

    def jam_now_next(self, location_id: int) -> Params:
        return self.get(f"location/id/{int(location_id)}/jamNowNext", self._auth(required=False))

    # -- catalog -----------------------------------------------------------------------------

    def search(
        self,
        query: str,
        device_id: str | int | None,
        page: int = 1,
        per_page: int = 20,
        sort: str | None = None,
        order: str | None = None,
    ) -> Params:
        params = {
            **self._device(device_id),
            "searchString": query,
            "playerId": self.session.player_id,
            **self._page(page, per_page),
            **self._sort("songs", sort, order),
        }
        return self.post("media/search", params)

    def song(self, song_id: int, device_id: str | int | None) -> Params | None:
        data = self.get(f"media/song/{int(song_id)}", self._device(device_id, key="destinationDevice", type_suffix="Id"))
        songs = data.get("songs") or []
        return songs[0] if songs else None

    def album_info(self, album_id: int, device_id: str | int | None) -> Params | None:
        data = self.get(f"media/albumdetails/{int(album_id)}", self._device(device_id, key="destinationDevice", type_suffix="Id"))
        albums = data.get("albums") or []
        return albums[0] if albums else None

    def album(self, album_id: int, device_id: str | int | None, page: int = 1, per_page: int = 50, sort: str = "track", order: str | None = None) -> Params:
        """The album's songs (``media/album/<id>``); ``album_info`` has the album's own metadata."""
        params = {**self._device(device_id), **self._page(page, per_page), **self._sort("songs", sort, order)}
        return self.get(f"media/album/{int(album_id)}", params)

    def artist(
        self,
        artist_id: int,
        device_id: str | int | None,
        media: str = "songs",
        page: int = 1,
        per_page: int = 20,
        sort: str | None = None,
        order: str | None = None,
    ) -> Params:
        """Songs or albums by an artist. The server insists on a sort, so one is always sent."""
        sort = sort or ("year" if media == "albums" else "popularity")
        params = {**self._device(device_id), **self._page(page, per_page), "mediaType": media, **self._sort(media, sort, order)}
        return self.get(f"media/v2/artist/{int(artist_id)}", params)

    def lists(self, location_id: int, device_id: str | int | None, language: str = "en") -> list[Params]:
        params = {
            **self._auth(required=False),
            **self._device(device_id),
            "locationId": int(location_id),
            **self._device_uuid(),
            "deviceTypeId": DEVICE_TYPE_MUSIC,
            "language": language,
        }
        return list(self.post("menu/locationLists/v2/getMetadata", params).get("lists", []))

    def list_data(self, location_id: int, device_id: str | int | None, identifier: str) -> Params:
        params = {
            **self._auth(required=False),
            **self._device_uuid(),
            "locationId": int(location_id),
            **self._device(device_id, type_suffix="Id"),
            "listIdentifier": identifier,
        }
        return self.post("menu/locationLists/getData", params)

    def featured_playlist(self, playlist_id: int, location_id: int, device_id: str | int | None) -> Params:
        params = {**self._auth(required=False), **self._device_uuid(), "locationId": int(location_id), **self._device(device_id)}
        return self.post(f"media/featuredPlaylist/{int(playlist_id)}", params)

    def venue_playlist(self, playlist_id: int, device_id: str | int | None) -> Params:
        return self.post("playlist/getplaylistdetails/venue", {**self._device(device_id), "playlistId": int(playlist_id)})

    # -- the player's own music --------------------------------------------------------------

    def favorites(self, device_id: str | int | None, page: int = 1, per_page: int = 50) -> list[Params]:
        params = {**self._auth(), **self._page(page, per_page), **self._device(device_id, key="destinationDevice")}
        return list(self.get("media/getPlayerFavorites", params).get("songs", []))

    def set_favorite(self, song_id: int, favorite: bool = True) -> Params:
        return self.post("favorites/songs/set", {**self._auth(), "songId": int(song_id), "favorite": bool(favorite)})

    def check_favorites(self, song_ids: list[int], device_id: str | int | None) -> list[int]:
        params = {**self._auth(), "songIdList": [int(s) for s in song_ids], **self._device(device_id, key="destinationDevice")}
        return [int(x) for x in self.post("media/checkFavorites", params).get("favorites", [])]

    def playlists(self) -> list[Params]:
        return list(self.post("playlist/getplaylists", self._auth()).get("playlists", []))

    def playlist(self, playlist_id: int, device_id: str | int | None, page: int = 1, per_page: int = 100) -> Params:
        params = {**self._auth(), "playlistId": int(playlist_id), **self._page(page, per_page), **self._device(device_id)}
        return self.post("playlist/getplaylistdetails", params).get("playlist", {})

    def playlist_create(self, title: str) -> Params:
        return self.post("playlist/create", {**self._auth(), "title": title}).get("playlist", {})

    def playlist_delete(self, playlist_id: int) -> Params:
        return self.post("playlist/delete", {**self._auth(), "playlistId": int(playlist_id)})

    def playlist_add(self, playlist_id: int, song_id: int, device_id: str | int | None) -> Params:
        params = {**self._auth(), "songId": int(song_id), **self._device(device_id, key="destinationDevice")}
        return self.post(f"playlist/{int(playlist_id)}/add", params)

    def playlist_rename(self, playlist_id: int, title: str) -> Params:
        return self.post(f"playlist/{int(playlist_id)}/update", {**self._auth(), "title": title})

    def playlist_set_songs(self, playlist_id: int, song_ids: list[int]) -> Params:
        return self.post(f"playlist/{int(playlist_id)}/update", {**self._auth(), "songIds": [int(s) for s in song_ids]})

    # -- spending credits --------------------------------------------------------------------

    @staticmethod
    def price_in_pennies(jukebox: Params, local: bool = False, priority: bool = False, video: bool = False) -> int:
        """Device.Music.getPriceInPennies: base + download (non-local) + priority + video."""
        if jukebox.get("isFreeplay"):
            return 0
        base = int(jukebox.get("basePrice") or 0)
        if base == 0:
            return 0
        price = base
        if not local:
            price += int(jukebox.get("downloadPrice") or 0)
        if priority:
            price += int(jukebox.get("priorityPrice") or 0)
        if video:
            price += int(jukebox.get("videoPrice") or 0)
        return price

    @staticmethod
    def pennies_to_credits(jukebox: Params, pennies: int) -> int:
        base = int(jukebox.get("basePrice") or 0)
        return pennies // base if base > 0 else 0

    def purchase(
        self,
        location_id: int,
        jukebox: Params,
        song: Params,
        priority: bool = False,
        video: bool = False,
        selection: str = "search_song",
        amount: int | None = None,
        client_purchase_id: str | None = None,
    ) -> Params:
        """Queue one song on the venue's jukebox. This spends wallet credits."""
        local = bool(song.get("local"))
        if amount is None:
            amount = self.price_in_pennies(jukebox, local=local, priority=priority, video=video)
        song_id = song.get("songId") if song.get("songId") is not None else song.get("id")
        item_id = song.get("videoId") if video and song.get("videoId") is not None else song_id
        if item_id is None:
            raise AmiError(None, "song has no id to purchase")
        params: Params = {
            **self._auth(),
            "destinationLocationId": int(location_id),
            "destinationDeviceId": str(jukebox["deviceId"]),
            "destinationDeviceType": int(jukebox.get("deviceType") or DEVICE_TYPE_MUSIC),
            "itemId": int(item_id),
            "itemType": ITEM_TYPE_VIDEO if video else ITEM_TYPE_SONG,
            "amount": int(amount),
            "priorityPlay": bool(priority),
            "dpLevelUsed": _not_default(jukebox.get("dpLevelUsed")),
            "dpAdditionalCredits": _not_default(jukebox.get("dpAdditionalCredits")),
            "dpEstPosInQueue": _not_default(jukebox.get("dpEstPosInQueue")),
            "clientPurchaseTime": server_time_now(),
            "clientPurchaseId": client_purchase_id or str(uuid.uuid4()),
            "selectionCode": SELECTION_CODES[selection],
            "sourceDeviceType": SOURCE_DEVICE_TYPE_MOBILE,
            "currency": jukebox.get("currency") or "USD",
        }
        return self.post("transaction/v4/purchase", params)


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _not_default(value: Any) -> int | None:
    """The app drops dynamic-pricing fields that are unset (its NO_VALUE sentinel, -1)."""
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return None if value < 0 else value


__all__ = [
    "APP_VERSION",
    "AmiClient",
    "AmiError",
    "DEVICE_TYPE_MUSIC",
    "DEVICE_TYPE_NAMES",
    "ENVIRONMENTS",
    "RESULT_CODES",
    "SELECTION_CODES",
    "server_time_now",
]
