"""One polite HTTP client for the instagram.com web endpoints.

INVARIANTS
- Every request is spaced by a randomized pause (MIN_GAP..MAX_GAP seconds).
  A burst is what got the first probe throttled; do not add a fast path.
- A 429, a login redirect, or a checkpoint/challenge body ends the run
  immediately and writes a cooldown. Subsequent runs refuse to start until it
  lapses (unless forced). We are borrowing a real person's session; the
  cost of being wrong is his account, not a failed cron job.
- Per-run request budget is hard-capped (MAX_REQUESTS). Deeper history is a
  second run tomorrow, not a bigger loop today.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import config

BASE = "https://www.instagram.com"
MIN_GAP = 6.0
MAX_GAP = 12.0
MAX_REQUESTS = 40
COOLDOWN_MINUTES = 90
CHALLENGE_MARKERS = ("checkpoint", "challenge_required", "login_required", "/accounts/login")


class Throttled(RuntimeError):
    """Instagram pushed back (429 / challenge / login wall). Stop the run."""


class NotFound(RuntimeError):
    """The account or media does not exist (or is private to this session)."""


@dataclass
class Session:
    cookies: config.Cookies
    log: list[str] = field(default_factory=list)
    requests_made: int = 0
    _last_at: float = 0.0

    @classmethod
    def open(cls, force: bool = False) -> "Session":
        jar = config.load_cookies()
        if not jar.ok:
            raise RuntimeError("no usable instagram cookies; run `ig cookies --from-chrome` first")
        until = config.cooldown_until()
        if until and not force:
            raise Throttled(f"cooldown active until {until.astimezone().strftime('%H:%M %Z')} (use --force to override)")
        return cls(cookies=jar)

    def _headers(self, referer: str) -> dict[str, str]:
        return {
            "User-Agent": config.user_agent(),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
            "Cookie": self.cookies.header(),
            "X-CSRFToken": self.cookies.values.get("csrftoken", ""),
            "X-IG-App-ID": config.IG_APP_ID,
            "X-ASBD-ID": config.IG_ASBD_ID,
            "X-IG-WWW-Claim": "0",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }

    def _pace(self) -> None:
        if self.requests_made >= MAX_REQUESTS:
            raise Throttled(f"per-run budget of {MAX_REQUESTS} requests spent")
        if self._last_at:
            wait = random.uniform(MIN_GAP, MAX_GAP) - (time.monotonic() - self._last_at)
            if wait > 0:
                time.sleep(wait)

    def get_json(self, path: str, params: dict | None = None, referer: str = BASE + "/") -> dict:
        self._pace()
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=self._headers(referer))
        self.requests_made += 1
        self._last_at = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                final = resp.geturl()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if exc.code == 429 or exc.code in (401, 403):
                self._throttle(f"HTTP {exc.code} on {path}")
            if exc.code == 404:
                raise NotFound(path) from exc
            raise RuntimeError(f"HTTP {exc.code} on {path}: {body[:200]}") from exc
        if "/accounts/login" in final:
            self._throttle(f"redirected to login on {path}")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            lowered = body[:4000].lower()
            if any(m in lowered for m in CHALLENGE_MARKERS) or "please wait" in lowered:
                self._throttle(f"non-JSON challenge body on {path}")
            raise RuntimeError(f"non-JSON response on {path}: {body[:200]!r}") from None
        if isinstance(data, dict):
            msg = str(data.get("message", "")).lower()
            if data.get("status") == "fail" and ("wait" in msg or "login" in msg or "challenge" in msg or data.get("require_login")):
                self._throttle(f"{data.get('message')} on {path}")
            if data.get("status") == "fail" and "not found" in msg:
                raise NotFound(path)
        return data

    def get_bytes(self, url: str, referer: str = BASE + "/") -> bytes:
        """Fetch a CDN asset (scontent). Light pacing: images are not the
        rate-limited surface, but stay polite."""
        time.sleep(random.uniform(0.4, 0.9))
        req = urllib.request.Request(url, headers={"User-Agent": config.user_agent(), "Referer": referer})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    def _throttle(self, reason: str) -> None:
        until = config.set_cooldown(COOLDOWN_MINUTES, reason)
        self.log.append(f"THROTTLED: {reason}; cooldown until {until.isoformat()}")
        raise Throttled(reason)
