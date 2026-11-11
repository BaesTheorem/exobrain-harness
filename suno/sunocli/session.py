"""The Suno login: where it comes from and how it becomes an API token.

Suno signs users in through Clerk on auth.suno.com. The browser holds a long-lived
``__client`` cookie there. Clerk trades that cookie for a session id, and the session id for a
one-hour JWT, which every API call carries as ``Authorization: Bearer``. This module reads the
cookie out of Chrome once, keeps it in ``secrets/session.json``, and mints JWTs from it.

INVARIANTS:
- The ``__client`` cookie is as good as the password while it lives: written 0600, never
  printed, never committed (``secrets/`` is gitignored, see ``secrets/README.md``).
- The JWT's claims carry the account's e-mail address and phone number. Never print a JWT or
  its decoded claims. ``user_id()`` and ``handle()`` are the only claims this module gives out.
- Read-only on the browser: the cookie database is copied to a temp folder and read there.
  Chrome keeps its own files locked and nothing is ever written back.
- A JWT older than ``JWT_MAX_AGE`` is replaced even though its ``exp`` says one hour. Suno's
  generate endpoint has rejected tokens well inside their stated life.
- macOS Chromium ``v10`` cookies are AES-128-CBC with key PBKDF2-HMAC-SHA1(Keychain secret,
  ``saltysalt``, 1003 rounds, 16 bytes) and an IV of 16 spaces. Chrome 130 and later put
  SHA-256(host_key) before the plaintext; it is removed only when it matches (43 of 43
  suno.com cookies matched on 2026-11-11). ``v20`` (App-Bound) cookies raise, they are never
  skipped, so a future migration reads as an error and not as "logged out".
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

Json = dict[str, Any]
Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]]

HERE = Path(__file__).resolve().parent.parent  # suno/
SECRETS = HERE / "secrets"
SESSION_PATH = SECRETS / "session.json"

CLERK = "https://auth.suno.com"
# Clerk wants both on every call. Values the web app sent on 2026-11-11.
CLERK_QUERY = "__clerk_api_version=2025-11-10&_clerk_js_version=5.117.0"
JWT_MAX_AGE = 20 * 60

SUPPORT = Path.home() / "Library/Application Support"
BROWSERS = {
    "chrome": (SUPPORT / "Google/Chrome/Default", "Chrome Safe Storage"),
    "brave": (SUPPORT / "BraveSoftware/Brave-Browser/Default", "Brave Safe Storage"),
    "arc": (SUPPORT / "Arc/User Data/Default", "Arc Safe Storage"),
    "edge": (SUPPORT / "Microsoft Edge/Default", "Microsoft Edge Safe Storage"),
}
CHROME_APP = Path("/Applications/Google Chrome.app/Contents/Info.plist")


class LoginNeeded(RuntimeError):
    """No usable Suno session. Sign in at suno.com in the browser, then `suno auth import`."""


def user_agent() -> str:
    """A normal desktop Chrome User-Agent that matches the installed Chrome's major version."""
    major = "157"
    try:
        import plistlib

        with CHROME_APP.open("rb") as fh:
            major = plistlib.load(fh)["CFBundleShortVersionString"].split(".")[0]
    except (OSError, KeyError, ValueError):
        pass
    return (f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")


def http_transport(method: str, url: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
    """The one place this package touches the network for API and Clerk calls."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


# -- reading the browser -----------------------------------------------------------------------


def _cookie_db(profile: Path) -> Path:
    for rel in ("Network/Cookies", "Cookies"):
        if (db := profile / rel).exists():
            return db
    raise FileNotFoundError(f"no cookie database under {profile}")


def _safe_storage_key(service: str) -> bytes:
    out = subprocess.run(["security", "find-generic-password", "-ws", service],
                         capture_output=True, text=True, check=True)
    return hashlib.pbkdf2_hmac("sha1", out.stdout.strip().encode(), b"saltysalt", 1003, dklen=16)


def decrypt_cookie(blob: bytes, key: bytes, host: str = "") -> str | None:
    """One Chromium cookie value. None for an empty or unknown blob; v20 raises."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if not blob:
        return None
    if blob[:3] == b"v20":
        raise RuntimeError("the browser now stores suno.com cookies with v20 App-Bound encryption, "
                           "which this reader cannot open. Use `suno auth set` and paste the cookie.")
    if blob[:3] != b"v10":
        return None
    dec = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    plain = dec.update(blob[3:]) + dec.finalize()
    if plain and plain[-1] <= 16:  # PKCS7 padding
        plain = plain[: -plain[-1]]
    # Cookie database version 24 (Chrome 130) and later put SHA-256(host_key) before the value.
    # The prefix is compared, not assumed: a blind 32-byte cut truncates an older value.
    if host and plain[:32] == hashlib.sha256(host.encode()).digest():
        plain = plain[32:]
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        return None


def browser_cookies(browser: str = "chrome") -> list[Json]:
    """Every suno.com cookie in the browser, as Playwright-shaped dicts."""
    if browser not in BROWSERS:
        raise ValueError(f"unknown browser {browser!r}; one of {', '.join(BROWSERS)}")
    profile, service = BROWSERS[browser]
    if not profile.exists():
        raise FileNotFoundError(f"{browser}: no profile at {profile}")
    key = _safe_storage_key(service)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "Cookies"
        shutil.copy2(_cookie_db(profile), copy)
        con = sqlite3.connect(copy)
        try:
            rows = con.execute(
                "select host_key, path, is_secure, is_httponly, expires_utc, name, encrypted_value, samesite "
                "from cookies where host_key like '%suno.com'").fetchall()
        finally:
            con.close()
    jar: list[Json] = []
    for host, path, secure, httponly, expires_utc, name, enc, samesite in rows:
        value = decrypt_cookie(enc, key, host)
        if value is None:
            continue
        same = {0: "None", 1: "Lax", 2: "Strict"}.get(samesite, "Lax")
        if same == "None" and not secure:  # Playwright refuses SameSite=None without Secure
            same = "Lax"
        jar.append({
            "name": name, "value": value, "domain": host, "path": path or "/",
            "secure": bool(secure), "httpOnly": bool(httponly), "sameSite": same,
            # Chrome stores microseconds since 1601-01-01; Playwright wants unix seconds.
            "expires": (expires_utc // 1_000_000 - 11644473600) if expires_utc else -1,
        })
    return jar


def pick_login(jar: list[Json]) -> tuple[str, str | None]:
    """The Clerk cookie and the device id out of a browser cookie jar."""
    client = device = None
    for c in jar:
        if c["name"] == "__client" and c["value"] and (client is None or "auth." in c["domain"]):
            client = c["value"]
        if c["name"] == "suno_device_id" and c["value"]:
            device = c["value"].strip('"')
    if not client:
        raise LoginNeeded("the browser holds no Suno login. Sign in at suno.com there, then run "
                          "`suno auth import` again.")
    return client, device


def clean_pasted(text: str) -> str:
    """Accept a bare ``__client`` value, a ``__client=...`` pair, or a whole pasted Cookie header."""
    text = text.strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    if "=" in text.split(";")[0] or ";" in text:
        for part in text.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "__client" and value:
                return value
        raise ValueError("the pasted cookie header has no __client field")
    return text


# -- the stored session --------------------------------------------------------------------------


def load() -> Json | None:
    if not SESSION_PATH.exists():
        return None
    try:
        data = json.loads(SESSION_PATH.read_text())
    except (OSError, ValueError):
        return None
    return data if data.get("client") else None


def save(state: Json) -> None:
    SECRETS.mkdir(parents=True, exist_ok=True)
    tmp = SESSION_PATH.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, SESSION_PATH)


def clear() -> bool:
    if SESSION_PATH.exists():
        SESSION_PATH.unlink()
        return True
    return False


def import_from_browser(browser: str = "chrome") -> Json:
    client, device = pick_login(browser_cookies(browser))
    state = {"client": client, "device_id": device, "source": browser,
             "imported_at": int(time.time())}
    save(state)
    return state


# -- Clerk ---------------------------------------------------------------------------------------


def jwt_claims(jwt: str) -> Json:
    try:
        payload = jwt.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def _clerk(transport: Transport, method: str, path: str, client: str) -> tuple[int, Json]:
    headers = {
        "user-agent": user_agent(), "origin": "https://suno.com", "referer": "https://suno.com/",
        "authorization": client, "cookie": f"__client={client}", "accept": "*/*",
    }
    body = None
    if method == "POST":
        headers["content-type"] = "application/x-www-form-urlencoded"
        body = b""
    status, raw = transport(method, f"{CLERK}{path}?{CLERK_QUERY}", body, headers)
    try:
        return status, json.loads(raw or b"{}")
    except ValueError:
        return status, {}


def mint_jwt(state: Json, transport: Transport = http_transport) -> str:
    """Trade the stored cookie for a fresh JWT. Fills ``session_id`` on the way."""
    client = state["client"]
    sid = state.get("session_id")
    if not sid:
        status, body = _clerk(transport, "GET", "/v1/client", client)
        resp = body.get("response") or {}
        sessions = [s for s in resp.get("sessions") or [] if s.get("status") == "active"]
        sid = resp.get("last_active_session_id") or (sessions[0]["id"] if sessions else None)
        if status != 200 or not sid:
            raise LoginNeeded(f"Suno's sign-in service did not return an active session (HTTP {status}).")
        state["session_id"] = sid
    status, body = _clerk(transport, "POST", f"/v1/client/sessions/{sid}/tokens", client)
    jwt = body.get("jwt")
    if status != 200 or not jwt:
        state.pop("session_id", None)
        raise LoginNeeded(f"Suno's sign-in service refused the stored login (HTTP {status}).")
    state["jwt"] = jwt
    state["jwt_at"] = int(time.time())
    return jwt


class Session:
    """The stored login plus a fresh-enough JWT. One instance for each CLI run."""

    def __init__(self, transport: Transport = http_transport, state: Json | None = None,
                 reimport: Callable[[], Json] | None = import_from_browser,
                 clock: Callable[[], float] = time.time, persist: bool = True) -> None:
        self.transport = transport
        self.reimport = reimport
        self.clock = clock
        self.persist = persist
        self.state = state if state is not None else (load() or {})

    def _save(self) -> None:
        if self.persist:
            save(self.state)

    def ensure_login(self) -> None:
        if self.state.get("client"):
            return
        if self.reimport is None:
            raise LoginNeeded("no stored Suno login. Run `suno auth import`.")
        self.state = self.reimport()

    def token(self, force: bool = False) -> str:
        """A JWT young enough for the API. Imports from the browser when nothing is stored."""
        self.ensure_login()
        jwt, at = self.state.get("jwt"), self.state.get("jwt_at", 0)
        if jwt and not force and self.clock() - at < JWT_MAX_AGE:
            return jwt
        try:
            jwt = mint_jwt(self.state, self.transport)
        except LoginNeeded:
            # The stored cookie died (sign-out, new login). Chrome holds the current one.
            if self.reimport is None:
                raise
            self.state = self.reimport()
            jwt = mint_jwt(self.state, self.transport)
        self._save()
        return jwt

    @property
    def device_id(self) -> str:
        return self.state.get("device_id") or "00000000-0000-0000-0000-000000000000"

    def _claim(self, *names: str) -> str | None:
        claims = jwt_claims(self.token())
        for name in names:
            if claims.get(name):
                return str(claims[name])
        return None

    def user_id(self) -> str | None:
        """The account's UUID, as clips carry it in ``user_id``.

        The ``suno/user_id`` claim is a short internal number and does not match a clip's
        ``user_id``; a library filter built from it returns nothing (measured 2026-11-11).
        """
        value = self._claim("suno.com/claims/user_id", "sub")
        return value if value and len(value) == 36 and value.count("-") == 4 else None

    def handle(self) -> str | None:
        return self._claim("suno/handle")
