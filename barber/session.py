#!/usr/bin/env python3
"""The saved Booksy session, in the two shapes the rest of the code needs.

Booksy authenticates with the `identity-us` cookie value replayed as an
`x-access-token` header. The cookie itself is also needed when driving the
site in a browser. extract_session.py produces the file; this reads it.

INVARIANTS (an edit must not break these):
- Never print, log, or return a token in a human-facing message. Callers
  report presence and length, never the value.
- `require()` raises rather than returning a partial session. A half-loaded
  session fails later, deep inside a booking, where it is far more confusing.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SESSION_PATH = HERE / ".booksy-session.json"

WEB_API_KEY = "web-e3d812bf-d7a2-445d-ab38-55589ae6a121"
CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


class NoSession(RuntimeError):
    """No usable Booksy session on disk."""


def load() -> dict[str, str]:
    if not SESSION_PATH.exists():
        raise NoSession(
            "no saved Booksy session. Log in at booksy.com in Chrome, then run:\n"
            "  python3 extract_session.py --verify"
        )
    cookies = json.loads(SESSION_PATH.read_text()).get("cookies") or {}
    if "identity-us" not in cookies:
        raise NoSession("session file has no 'identity-us' cookie; re-run extract_session.py")
    return cookies


def token() -> str:
    return load()["identity-us"]


def api_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Headers for an authenticated customer_api call."""
    headers = {
        "User-Agent": CHROME_UA,
        "x-api-key": WEB_API_KEY,
        "x-access-token": token(),
        "accept": "application/json",
        "content-type": "application/json",
        "origin": "https://booksy.com",
        "referer": "https://booksy.com/",
    }
    headers.update(extra or {})
    return headers


def playwright_cookies() -> list:
    """The session as Playwright cookie dicts, for driving the site logged in."""
    out: list = []
    for name, value in load().items():
        # Booksy sets some cookies on the onboarding subdomain; the session
        # cookie itself is on the apex, which is all the booking flow needs.
        out.append(
            {
                "name": name,
                "value": value,
                "domain": ".booksy.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            }
        )
    return out
