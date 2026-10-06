"""Google Calendar writes for a headless job, over the REST API with our own token.

The claude.ai Calendar connector exists only inside a Claude session, and syncing a
few dozen meetings is deterministic work that does not need a model. So this job
holds its own OAuth token, scope calendar.events only. Same pattern as
kcurbex/kcurbexcli/gcal.py (copied, not imported: islands do not share internals).

INVARIANTS:
- Token lives in secrets/gcal-token.json (gitignored, mode 600). Never logged.
- Every event carries extendedProperties.private.kccivicId = Meeting.key. That is
  the dedup key, so a rescheduled or renamed meeting updates in place.
- Writes are idempotent: syncing twice patches, never duplicates.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
HARNESS_ENV = HERE.parent / ".env"
TOKEN_PATH = HERE / "secrets" / "gcal-token.json"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
REDIRECT_URI = "https://www.google.com"
SCOPE = "https://www.googleapis.com/auth/calendar.events"
PROP_KEY = "kccivicId"


class NotAuthorized(RuntimeError):
    """No calendar token yet. The caller degrades to a single notice, not a crash."""


def env_value(key: str) -> str | None:
    val = os.environ.get(key)
    if val:
        return val
    if HARNESS_ENV.exists():
        for line in HARNESS_ENV.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def _client() -> tuple[str, str]:
    cid, sec = env_value("GOOGLE_OAUTH_CLIENT_ID"), env_value("GOOGLE_OAUTH_CLIENT_SECRET")
    if not cid or not sec:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET missing from harness .env")
    return cid, sec


def _write_token(tok: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tok, indent=2))
    TOKEN_PATH.chmod(0o600)


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST"), timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"token endpoint {e.code}: {e.read()[:300]!r}") from None


def access_token() -> str:
    if not TOKEN_PATH.exists():
        raise NotAuthorized(f"no calendar token at {TOKEN_PATH}; run `kc-civic auth-calendar`")
    tok = json.loads(TOKEN_PATH.read_text())
    if tok.get("access_token") and float(tok.get("expires_at", 0)) - time.time() > 300:
        return str(tok["access_token"])
    cid, sec = _client()
    data = _post_form(TOKEN_URL, {"client_id": cid, "client_secret": sec,
                                  "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    tok["access_token"] = data["access_token"]
    tok["expires_at"] = time.time() + float(data.get("expires_in", 0))
    _write_token(tok)
    return str(tok["access_token"])


def consent_url() -> str:
    cid, _ = _client()
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": REDIRECT_URI, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent",
    })


def exchange(pasted: str) -> Path:
    """Takes the redirected URL (or bare code) from the consent screen."""
    code = pasted.strip()
    if "code=" in code:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query)["code"][0]
    cid, sec = _client()
    data = _post_form(TOKEN_URL, {"client_id": cid, "client_secret": sec, "code": code,
                                  "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI})
    if "refresh_token" not in data:
        raise RuntimeError("no refresh_token in the response; open a fresh consent URL and retry")
    _write_token({"refresh_token": data["refresh_token"], "access_token": data.get("access_token", ""),
                  "expires_at": time.time() + float(data.get("expires_in", 0)), "scope": SCOPE})
    return TOKEN_PATH


def _api(method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict:
    url = f"{API}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {access_token()}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"calendar API {method} {path} failed: {e.code} {e.read()[:300]!r}") from None


def calendar_id(default: str = "primary") -> str:
    return env_value("KCCIVIC_CALENDAR_ID") or default


def find(cal: str, key: str) -> dict | None:
    res = _api("GET", f"/calendars/{urllib.parse.quote(cal)}/events",
               params={"privateExtendedProperty": f"{PROP_KEY}={key}", "showDeleted": "false", "maxResults": "5"})
    items = res.get("items", [])
    return items[0] if items else None


def upsert(cal: str, key: str, body: dict, adopt: str | None = None) -> tuple[str, dict]:
    """('created'|'updated'|'adopted', event). adopt = an event id to take over (a hold)."""
    body = {**body, "extendedProperties": {"private": {PROP_KEY: key}}}
    q = urllib.parse.quote(cal)
    existing = find(cal, key)
    if existing:
        return "updated", _api("PATCH", f"/calendars/{q}/events/{existing['id']}", payload=body)
    if adopt:
        try:
            return "adopted", _api("PATCH", f"/calendars/{q}/events/{adopt}", payload=body)
        except RuntimeError:
            pass  # the hold was deleted by hand; fall through and create
    return "created", _api("POST", f"/calendars/{q}/events", payload=body)


def delete(cal: str, event_id: str) -> None:
    try:
        _api("DELETE", f"/calendars/{urllib.parse.quote(cal)}/events/{event_id}")
    except RuntimeError as e:
        if " 404 " not in str(e) and " 410 " not in str(e):
            raise
