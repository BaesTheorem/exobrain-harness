"""Client for suno.com's own web API (the endpoints the Create page and the library call).

Suno publishes no API. The website talks to ``https://suno.com/a/api/...`` with the Clerk JWT
as a Bearer token. This client speaks to those endpoints. It is unofficial and Suno can change
it at any time. Every call below was captured from the live web client or checked against the
live service on 2026-11-11; ``suno doctor --drift`` repeats the capture.

INVARIANTS:
- Two things cost money and are never retried or sent twice: ``generate`` (credits) and
  ``authorize_download`` (one of the plan's monthly downloads). Each is one POST. A transport
  failure after the send raises ``OutcomeUnknown``; the caller reads the library before any
  second attempt.
- Everything else is a read, or a write that costs nothing, and is retried on 429, 5xx and
  transport errors.
- ``prepare_download`` is a GET and spends nothing. On a locked clip it answers
  ``{"ok": false, "reason": "not_authorized"}`` and the download counter does not move.
- ``audio_url`` on a clip is a placeholder (``.../api/forbidden``) and ``media_urls`` is an
  encoded playback stream for Suno's own player. Neither is a file. The only route to audio is
  ``authorize_download`` then ``prepare_download``.
- The ``/session/`` response carries the account's e-mail, phone number and birthday.
  ``whoami`` returns three harmless fields and drops the rest.
- A library listing is paged by an opaque cursor, 20 rows a page as the website asks for them.
  Thirty pages in quick succession earned a 429, so ``library`` waits between pages.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
from typing import Any, Callable, Iterator

from sunocli.session import Session, Transport, http_transport, user_agent

Json = dict[str, Any]

BASE = "https://suno.com/a/api"
SITE = "https://suno.com"
PAGE_SIZE = 20
PAGE_PAUSE = 0.6
TERMINAL = ("complete", "error")
AUTH_TEXT = ("token validation failed", "jwt expired", "jwt is expired", "invalid jwt",
             "invalid token", "not authenticated", "unauthenticated")


class SunoError(RuntimeError):
    """The service refused or failed a call. ``code`` is stable and safe to branch on."""

    code = "api_error"

    def __init__(self, message: str, status: int = 0, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class AuthRejected(SunoError):
    code = "auth_rejected"


class RateLimited(SunoError):
    code = "rate_limited"


class NotFound(SunoError):
    code = "not_found"


class SchemaDrift(SunoError):
    """Suno rejected the shape of a request: the web API changed under this client."""

    code = "schema_drift"


class OutcomeUnknown(SunoError):
    """A paid request left this machine and no answer came back. It may have been accepted."""

    code = "outcome_unknown"


class NotAuthorized(SunoError):
    """The clip is locked: the account has not spent a download on it."""

    code = "download_locked"


class Rejected(SunoError):
    """Suno understood the request and said no (moderation, plan limits, a bad value)."""

    code = "rejected"


def _is_validation_error(body: Any) -> bool:
    """FastAPI's field-level 422: ``detail`` is a list of ``{"loc": [...], "msg": ...}``."""
    detail = body.get("detail") if isinstance(body, dict) else None
    return isinstance(detail, list) and any(isinstance(d, dict) and "loc" in d for d in detail)


def browser_token(now_ms: int) -> str:
    """The ``browser-token`` header the web client sends: a base64 timestamp in a JSON shell."""
    inner = base64.b64encode(json.dumps({"timestamp": now_ms}, separators=(",", ":")).encode()).decode()
    return json.dumps({"token": inner}, separators=(",", ":"))


def _detail(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("detail", "message", "error", "reason"):
            val = body.get(key)
            if isinstance(val, str) and val:
                return val
            if val:
                return json.dumps(val)[:400]
    return (body if isinstance(body, str) else json.dumps(body))[:400] if body else ""


class SunoClient:
    def __init__(self, session: Session, transport: Transport = http_transport, base: str = BASE,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time) -> None:
        self.session = session
        self.transport = transport
        self.base = base.rstrip("/")
        self.sleep = sleep
        self.clock = clock

    # -- plumbing ------------------------------------------------------------------------------

    def _headers(self, has_body: bool) -> dict[str, str]:
        headers = {
            "authorization": f"Bearer {self.session.token()}",
            "device-id": self.session.device_id,
            "browser-token": browser_token(int(self.clock() * 1000)),
            "user-agent": user_agent(),
            "origin": SITE,
            "referer": f"{SITE}/create",
            "accept": "*/*",
        }
        if has_body:
            headers["content-type"] = "application/json"
        return headers

    def _once(self, method: str, path: str, body: Any) -> tuple[int, Any]:
        raw = None if body is None else json.dumps(body).encode()
        status, data = self.transport(method, self.base + path, raw, self._headers(raw is not None))
        if not data:
            return status, None
        try:
            return status, json.loads(data)
        except ValueError:
            return status, data.decode("utf-8", "replace")

    def call(self, method: str, path: str, body: Any = None, *, spends: bool = False) -> Any:
        """One API call. ``spends`` marks the two paid POSTs, which are never repeated."""
        attempts = 1 if spends else 4
        refreshed = False
        delay = 2.0
        last: SunoError | None = None
        for attempt in range(attempts + 1):
            try:
                status, data = self._once(method, path, body)
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                if spends:
                    raise OutcomeUnknown(f"no answer from Suno after the request was sent ({err})") from err
                last = SunoError(f"network error: {err}")
                if attempt >= attempts - 1:
                    raise last from err
                self.sleep(delay)
                delay = min(delay * 2, 20)
                continue
            text = _detail(data)
            if 200 <= status < 300:
                return data
            if status == 401 or any(t in text.lower() for t in AUTH_TEXT):
                # A rejected token means the request was not processed, so one resend is safe
                # even for a paid POST.
                if not refreshed:
                    refreshed = True
                    self.session.token(force=True)
                    continue
                raise AuthRejected(f"Suno rejected the login (HTTP {status}): {text}", status, data)
            if status == 404:
                raise NotFound(f"HTTP 404 on {path}: {text}", status, data)
            if status == 422 and _is_validation_error(data):
                raise SchemaDrift(f"Suno rejected the request shape (HTTP 422): {text}", status, data)
            if status == 429:
                last = RateLimited(f"rate limited: {text}", status, data)
            elif status >= 500:
                if spends:  # the server may have accepted the request before it failed
                    raise OutcomeUnknown(f"Suno server error on a paid request (HTTP {status}): {text}",
                                         status, data)
                last = SunoError(f"Suno server error (HTTP {status}): {text}", status, data)
            else:
                raise Rejected(f"Suno refused the request (HTTP {status}): {text}", status, data)
            if spends or attempt >= attempts - 1:
                raise last
            self.sleep(delay)
            delay = min(delay * 2, 20)
        raise last or SunoError("request failed")

    # -- account -------------------------------------------------------------------------------

    def billing(self) -> Json:
        """Plan, credits, model catalogue with input limits, and the download counter."""
        return self.call("GET", "/billing/info/")

    def whoami(self) -> Json:
        user = (self.call("GET", "/session/") or {}).get("user") or {}
        return {"handle": user.get("handle"), "display_name": user.get("display_name"),
                "total_clips": user.get("total_clips")}

    def captcha_gate(self) -> Json:
        """``{"required": bool, "captcha_version": 1|2}``: 1 is hCaptcha, 2 is Turnstile."""
        return self.call("POST", "/c/check", {"ctype": "generation"})

    # -- library -------------------------------------------------------------------------------

    def feed_page(self, cursor: str | None = None, search: str | None = None,
                  trashed: bool = False, limit: int = PAGE_SIZE) -> Json:
        """One page of the account's songs, with the filters the website's library sends."""
        filters: Json = {
            "disliked": "False", "trashed": "True" if trashed else "False",
            "fromStudioProject": {"presence": "False"}, "stem": {"presence": "False"},
            "stemComplement": "False",
        }
        user_id = self.session.user_id()
        if user_id:
            filters["user"] = {"presence": "True", "userId": user_id}
        if search:
            filters["searchText"] = search
        return self.call("POST", "/feed/v3", {"cursor": cursor, "limit": limit, "filters": filters})

    def library(self, limit: int = PAGE_SIZE, search: str | None = None,
                trashed: bool = False) -> Iterator[Json]:
        """Songs newest first, up to ``limit`` (0 means every song)."""
        cursor, seen = None, 0
        while True:
            page = self.feed_page(cursor, search, trashed)
            for clip in page.get("clips") or []:
                yield clip
                seen += 1
                if limit and seen >= limit:
                    return
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                return
            self.sleep(PAGE_PAUSE)

    def clip(self, clip_id: str) -> Json:
        return self.call("GET", f"/clip/{clip_id}")

    def clips(self, ids: list[str]) -> list[Json]:
        """Several clips by id. Asked two at a time: larger batches have come back short."""
        out: list[Json] = []
        for i in range(0, len(ids), 2):
            got = self.call("GET", "/feed/?ids=" + urllib.parse.quote(",".join(ids[i:i + 2]), safe=","))
            out.extend(got if isinstance(got, list) else (got or {}).get("clips") or [])
        return out

    def aligned_lyrics(self, clip_id: str) -> Json:
        """Timed lyrics: ``aligned_lyrics`` (lines with words) and ``aligned_words``."""
        return self.call("GET", f"/gen/{clip_id}/aligned_lyrics/v2/")

    def set_metadata(self, clip_id: str, fields: Json) -> Any:
        return self.call("POST", f"/gen/{clip_id}/set_metadata/", fields)

    def set_trashed(self, ids: list[str], trash: bool) -> Any:
        return self.call("POST", "/gen/trash", {"clip_ids": ids, "trash": trash})

    # -- creating ------------------------------------------------------------------------------

    def generate(self, payload: Json) -> list[Json]:
        """Submit one generation. Costs credits. Sent once, never retried."""
        data = self.call("POST", "/generate/v2-web/", payload, spends=True)
        clips = (data or {}).get("clips") or []
        if str((data or {}).get("status", "")).lower() == "error" or not clips:
            raise OutcomeUnknown("Suno answered without clips. Read `suno list` before a second attempt.",
                                 200, data)
        return clips

    def wait(self, ids: list[str], timeout: float = 600, interval: float = 5,
             on_tick: Callable[[list[Json]], None] | None = None) -> list[Json]:
        """Poll until every id is ``complete`` or ``error``. Returns the last state on timeout."""
        deadline = self.clock() + timeout
        known: dict[str, Json] = {}
        delay = max(interval, 1.0)
        while True:
            try:
                for clip in self.clips(ids):
                    known[clip["id"]] = clip
            except RateLimited:
                delay = max(delay, 15.0)
            state = [known[i] for i in ids if i in known]
            if on_tick:
                on_tick(state)
            if len(state) == len(ids) and all(c.get("status") in TERMINAL for c in state):
                return state
            if self.clock() >= deadline:
                return state
            self.sleep(delay)
            delay = min(delay * 1.5, 15.0)

    # -- downloading ---------------------------------------------------------------------------

    def authorize_download(self, clip_id: str) -> Json:
        """Unlock a clip for download. Costs one of the plan's downloads. Sent once."""
        data = self.call("POST", "/download/authorize", {"item_id": clip_id, "item_type": "clip"},
                         spends=True) or {}
        if data.get("ok") is not True:
            raise SunoError(f"Suno did not confirm the unlock: {_detail(data)}", 200, data)
        return data

    def prepare_download(self, clip_id: str, fmt: str = "mp3", timeout: float = 180) -> str:
        """A short-lived signed URL for the file. Free. Raises NotAuthorized on a locked clip."""
        if fmt == "wav":
            return self._wav_url(clip_id, timeout)
        deadline = self.clock() + timeout
        while True:
            data = self.call("GET", f"/download/clip/{clip_id}?format={fmt}") or {}
            status, reason = data.get("status"), data.get("reason")
            if data.get("ok") and status == "ready" and str(data.get("download_url", "")).startswith("https://"):
                return data["download_url"]
            if reason == "not_authorized":
                raise NotAuthorized("the clip is locked for download", 200, data)
            if not (status == "processing" or "rate_limited" in (status, reason)):
                raise SunoError(f"download preparation failed: {_detail(data) or data}", 200, data)
            if self.clock() >= deadline:
                raise SunoError("download preparation timed out; run the download again")
            self.sleep(2)

    def _wav_url(self, clip_id: str, timeout: float) -> str:
        deadline = self.clock() + timeout
        asked = False
        while True:
            data = self.call("GET", f"/gen/{clip_id}/wav_file/") or {}
            url = data.get("wav_file_url")
            if isinstance(url, str) and url.startswith("https://"):
                return url
            if not asked:
                self.call("POST", f"/gen/{clip_id}/convert_wav/")
                asked = True
            if self.clock() >= deadline:
                raise SunoError("WAV conversion timed out; run the download again")
            self.sleep(2)
