"""Writing meetups into Google Calendar from a headless job.

The Google Calendar MCP connector only exists inside a Claude session; the watcher runs
under launchd, so it needs its own OAuth token. The backup uploader's Drive token is
drive-scope only and deliberately not reused: a calendar job should not hold a token
that can rewrite Drive.

INVARIANTS:
- Token and client secret live under secrets/ (gitignored) and in the harness .env.
  Never logged, never committed.
- Every event this writes carries `kcurbex-meetup-<topic_id>` in its private extended
  properties. That, not the title, is the dedup key: hosts rename and reschedule
  threads constantly, and matching on a title would double-book every rename.
- Writes are idempotent. Syncing twice updates in place rather than creating twins.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path

from .auth import HERE, env_value
from .meetups import Meetup

TOKEN_PATH = HERE / "secrets" / "gcal-token.json"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
REDIRECT_URI = "https://www.google.com"
SCOPE = "https://www.googleapis.com/auth/calendar.events"

# Meetups have no stated end time; urbex outings run long, so block a realistic window
# rather than Google's default hour.
DEFAULT_DURATION = timedelta(hours=3)
PROP_KEY = "kcurbexTopic"


class NotAuthorized(RuntimeError):
    """No calendar token yet. The caller should degrade to notifying, not crash."""


def client_creds() -> tuple[str, str]:
    cid = env_value("GOOGLE_OAUTH_CLIENT_ID")
    sec = env_value("GOOGLE_OAUTH_CLIENT_SECRET")
    if not cid or not sec:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET missing from harness .env")
    return cid, sec


def _read_token() -> dict:
    if not TOKEN_PATH.exists():
        raise NotAuthorized(f"no calendar token at {TOKEN_PATH}; run `kcurbex auth-calendar` once")
    return json.loads(TOKEN_PATH.read_text())


def _write_token(tok: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(tok, indent=2))
    TOKEN_PATH.chmod(0o600)


def access_token() -> str:
    """A valid access token, refreshed if it expires within five minutes."""
    tok = _read_token()
    if tok.get("access_token") and float(tok.get("expires_at", 0)) - time.time() > 300:
        return str(tok["access_token"])
    cid, sec = client_creds()
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": sec,
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body, method="POST"), timeout=60) as r:
        data = json.loads(r.read())
    tok["access_token"] = data["access_token"]
    tok["expires_at"] = time.time() + float(data.get("expires_in", 0))
    _write_token(tok)
    return str(tok["access_token"])


def authorize(prompt=input) -> Path:
    """One-time consent. Prints a URL; takes the pasted redirect back."""
    cid, sec = client_creds()
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": REDIRECT_URI, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent",
    })
    print("Open this URL, approve, then paste the FULL redirected URL back here:\n")
    print(url + "\n")
    pasted = prompt("Redirected URL (or bare code): ").strip()
    code = pasted
    if "code=" in pasted:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)["code"][0]
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": sec, "code": code,
        "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI,
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body, method="POST"), timeout=60) as r:
        data = json.loads(r.read())
    if "refresh_token" not in data:
        raise RuntimeError(f"no refresh_token in response (re-consent with prompt=consent): {data}")
    _write_token({
        "refresh_token": data["refresh_token"],
        "access_token": data.get("access_token", ""),
        "expires_at": time.time() + float(data.get("expires_in", 0)),
        "scope": SCOPE,
    })
    return TOKEN_PATH


def _api(method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
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


def calendar_id() -> str:
    """Which calendar to write to. KCURBEX_CALENDAR_ID overrides the primary."""
    return os.environ.get("KCURBEX_CALENDAR_ID") or env_value("KCURBEX_CALENDAR_ID") or "primary"


def describe(m: Meetup) -> str:
    """The context that makes the calendar entry worth having."""
    lines = [f"KC Urbex meetup posted by {m.host or 'a member'}.", ""]
    if m.confidence != "parsed":
        lines.append(f"NOTE: date parsed with lower confidence ({m.confidence}). Check the thread.")
        lines.append("")
    if m.all_day:
        lines.append("NOTE: the announcement gave no start time, so this is all-day. Check the thread.")
        lines.append("")
    if m.venue:
        lines.append(f"Meeting point: {m.venue}")
    if m.lat is not None:
        lines.append(f"Coordinates: {m.lat}, {m.lon}")
        lines.append(f"Map: https://www.google.com/maps/search/?api=1&query={m.lat},{m.lon}")
    if m.blurb:
        lines += ["", "From the announcement:", m.blurb]
    lines += ["", f"Thread: {m.url}"]
    return "\n".join(lines)


def _event_body(m: Meetup) -> dict:
    assert m.starts is not None
    if m.all_day:
        day = m.starts.date()
        when = {"start": {"date": day.isoformat()},
                "end": {"date": (day + timedelta(days=1)).isoformat()}}
    else:
        when = {"start": {"dateTime": m.starts.isoformat(), "timeZone": "America/Chicago"},
                "end": {"dateTime": (m.starts + DEFAULT_DURATION).isoformat(), "timeZone": "America/Chicago"}}
    location = m.venue or (f"{m.lat}, {m.lon}" if m.lat is not None else "")
    return {
        "summary": f"KC Urbex: {m.title}",
        "description": describe(m),
        "location": location,
        "extendedProperties": {"private": {PROP_KEY: str(m.topic_id)}},
        "source": {"title": "KC Urbex thread", "url": m.url},
        **when,
    }


def find_existing(m: Meetup) -> str | None:
    """The event id previously written for this topic, if any."""
    res = _api("GET", f"/calendars/{urllib.parse.quote(calendar_id())}/events",
               params={"privateExtendedProperty": f"{PROP_KEY}={m.topic_id}",
                       "showDeleted": "false", "maxResults": "5"})
    items = res.get("items", [])
    return items[0]["id"] if items else None


def sync(m: Meetup) -> tuple[str, str]:
    """Create or update the calendar event for a meetup. Returns (action, event_id)."""
    if m.starts is None:
        raise ValueError(f"meetup {m.topic_id} has no parsed date; refusing to guess one")
    cal = urllib.parse.quote(calendar_id())
    existing = find_existing(m)
    if existing:
        ev = _api("PATCH", f"/calendars/{cal}/events/{existing}", payload=_event_body(m))
        return "updated", ev.get("id", existing)
    ev = _api("POST", f"/calendars/{cal}/events", payload=_event_body(m))
    return "created", ev["id"]
