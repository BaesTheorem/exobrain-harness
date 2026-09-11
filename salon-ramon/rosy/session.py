"""The live Rosy session, lifted from Chrome and turned into an API token.

Rosy's online booking is a Spring app behind a `JSESSIONID`. Alex signs in with
Google ("Continue with Google" -> /oauth2/authorization/google), and the login
page is guarded by reCAPTCHA, so no automated login is attempted here: we lift
the session he already has, exactly like the Booksy tool does.

The session cookie is not itself the API credential. Every server-rendered page
embeds a short-lived JWT (`jwtToken`) and the signed-in `customerId`, and the
`/api/v2` endpoints authenticate on `Authorization: Bearer <that JWT>`. The JWT
lasts 30 minutes, so it is scraped fresh on each run rather than cached to disk.

Rosy mints that JWT once, at sign-in, and never renews it, so a session goes
cold 30 minutes after Alex last signed in and every unattended run would have
needed him at the keyboard. `refresh()` closes that gap: it replays the Google
SSO cookies already in Chrome through Rosy's own OAuth endpoint, which Google
approves silently because Alex consented to this app long ago. No password, no
captcha, nobody at the keyboard.

INVARIANTS (an edit must not break these):
- Google cookies are read into memory for one OAuth redirect chain and never
  persisted, printed, or logged. `.rosy-session.json` holds Rosy cookies only.
  Alex authorised reading them for exactly this (2026-09-11); that authorisation
  does not extend to keeping them.
- The cookie jar stays domain-scoped, so Google's cookies are only ever sent to
  Google and Rosy's only to Rosy. This is why the flow uses http.cookiejar
  rather than a hand-built Cookie header: one wrong header would post Alex's
  Google session to a salon booking system.
- Never print, log, or return a token in a human-facing message. Report its
  length and whether it works, never its value.
- `context()` fails closed. A page that comes back logged-out raises instead of
  returning an anonymous token: the anonymous token can read the salon's
  catalogue fine, so a silent downgrade would look healthy right up until a
  booking POST returned 403.
"""

from __future__ import annotations

import base64
import http.cookiejar
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import pbkdf2_hmac, sha256
from pathlib import Path

from .config import BASE, CHROME_UA, load

HERE = Path(__file__).resolve().parent.parent
SESSION_PATH = HERE / ".rosy-session.json"
COOKIE_DB = Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies"
COOKIE_HOST = "rosysalonsoftware.com"
GOOGLE_HOST = "google.com"

# Chrome's fixed macOS key-derivation parameters.
SALT = b"saltysalt"
ITERATIONS = 1003
KEY_LEN = 16
IV = b" " * 16

# Refuse a token that cannot outlive the work. A booking is several calls, and
# one that dies between the POST and the read-back is the worst case: the
# appointment exists and nothing can confirm it.
MIN_TOKEN_LIFE = timedelta(minutes=2)

RELOGIN = (
    "Sign in at https://online.rosysalonsoftware.com/appointments in Chrome "
    "(Continue with Google), then run: ramon login"
)


class NoSession(RuntimeError):
    """No usable Rosy session."""


@dataclass
class Context:
    """One run's authenticated handle on the API."""

    token: str
    customer_id: int
    cookies: dict[str, str]


def _keychain_password() -> str:
    """Chrome's Safe Storage secret. macOS may prompt for Keychain access."""
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["/usr/bin/security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise NoSession("Keychain prompt timed out; approve it and retry") from exc
    if out.returncode != 0:
        raise NoSession(f"could not read Keychain: {out.stderr.strip()}")
    return out.stdout.strip()


def _decrypt(blob: bytes, key: bytes, host: str) -> str:
    """Decrypt one Chrome cookie value.

    Chrome >=130 prepends a 32-byte SHA-256 of the cookie's host to the
    plaintext. Detect it by recomputing the hash, never by sniffing whether the
    first byte looks printable -- that heuristic fails silently whenever the
    hash happens to start with a printable byte.
    """
    if not blob:
        return ""
    if blob[:3] not in (b"v10", b"v11"):
        return blob.decode("utf-8", "replace")
    # Imported here, not at module scope: reading an already-saved session and
    # every API call work without `cryptography`, and only the Chrome cookie
    # lift needs it. A module-level import would make the whole tool (and its
    # tests) refuse to load on an interpreter that lacks the package.
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:  # pragma: no cover - environment problem, not logic
        raise NoSession("pip install cryptography to read Chrome's cookie store") from exc
    decryptor = Cipher(algorithms.AES(key), modes.CBC(IV)).decryptor()
    plain = decryptor.update(blob[3:]) + decryptor.finalize()
    if plain:
        plain = plain[: -plain[-1]]  # strip PKCS#7 padding
    for candidate in (host.lstrip("."), host):
        if plain[:32] == sha256(candidate.encode()).digest():
            plain = plain[32:]
            break
    return plain.decode("utf-8", "replace")


def _chrome_rows(host_suffix: str) -> list[tuple[str, str, str, str, bool]]:
    """(name, value, host, path, secure) for one host suffix, decrypted."""
    if not COOKIE_DB.exists():
        raise NoSession(f"no Chrome cookie DB at {COOKIE_DB}")

    key = pbkdf2_hmac("sha1", _keychain_password().encode(), SALT, ITERATIONS, KEY_LEN)

    # Copy first: Chrome holds a lock on the live file.
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    shutil.copy(COOKIE_DB, tmp_path)
    try:
        conn = sqlite3.connect(tmp_path)
        rows = conn.execute(
            "select name, encrypted_value, host_key, path, is_secure from cookies "
            "where host_key like ? order by creation_utc desc",
            (f"%{host_suffix}",),
        ).fetchall()
        conn.close()
    finally:
        tmp_path.unlink(missing_ok=True)

    out: list[tuple[str, str, str, str, bool]] = []
    seen: set[tuple[str, str]] = set()
    for name, blob, host, path, secure in rows:
        if (host, name) in seen:
            continue
        seen.add((host, name))
        try:
            value = _decrypt(blob, key, host)
        except Exception as exc:  # noqa: BLE001 - one bad cookie must not stop the rest
            print(f"  ! {name}: {type(exc).__name__}", file=sys.stderr)
            continue
        if value:
            out.append((name, value, host, path or "/", bool(secure)))
    return out


def extract() -> dict[str, str]:
    """Read the Rosy cookies out of Chrome and save them, 0600."""
    cookies = {name: value for name, value, _, _, _ in _chrome_rows(COOKIE_HOST)}
    if "JSESSIONID" not in cookies:
        raise NoSession(f"no JSESSIONID cookie for {COOKIE_HOST}. {RELOGIN}")
    _save(cookies)
    return cookies


def _save(cookies: dict[str, str]) -> None:
    SESSION_PATH.write_text(json.dumps({"cookies": cookies}, indent=1) + "\n")
    SESSION_PATH.chmod(0o600)


def load_cookies() -> dict[str, str]:
    if not SESSION_PATH.exists():
        raise NoSession(f"no saved Rosy session. {RELOGIN}")
    cookies = json.loads(SESSION_PATH.read_text()).get("cookies") or {}
    if "JSESSIONID" not in cookies:
        raise NoSession(f"session file has no JSESSIONID. {RELOGIN}")
    return cookies


def _token_lifetime(token: str) -> tuple[datetime, datetime] | None:
    """(issued, expires) from the JWT payload, or None if it will not decode."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return (
            datetime.fromtimestamp(claims["iat"], tz=timezone.utc),
            datetime.fromtimestamp(claims["exp"], tz=timezone.utc),
        )
    except Exception:  # noqa: BLE001 - an unreadable token is simply unverifiable
        return None


def _fetch(url: str, cookies: dict[str, str]) -> str:
    jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": CHROME_UA,
            "cookie": jar,
            "accept": "text/html",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise NoSession(f"{url} -> HTTP {exc.code}. {RELOGIN}") from exc


def _scrape(html: str) -> tuple[str, int]:
    if "isCustomerLoggedIn = true" not in html:
        raise NoSession(f"Rosy says the session is signed out. {RELOGIN}")
    token = re.search(r'jwtToken = "([^"]+)"', html)
    customer = re.search(r"customerId = (\d+);", html)
    if not token or not customer:
        raise NoSession(f"signed-in page carried no token. {RELOGIN}")
    return token.group(1), int(customer.group(1))


def _sso_jar() -> http.cookiejar.CookieJar:
    """A jar holding Chrome's Google cookies and nothing else.

    Deliberately excludes Rosy's own cookies: the OAuth callback fails with
    `id=null` if it lands on a stale session, because Rosy stores which salon
    the sign-in is for in the session it creates at the start of the flow.
    """
    jar = http.cookiejar.CookieJar()
    for name, value, host, path, secure in _chrome_rows(GOOGLE_HOST):
        dotted = host.startswith(".")
        jar.set_cookie(
            http.cookiejar.Cookie(
                0, name, value, None, False,
                host, dotted, dotted,
                path, True, secure,
                None, False, None, None, {},
            )
        )
    return jar


def refresh(salon_id: int) -> dict[str, str]:
    """Mint a new Rosy session by replaying Chrome's Google SSO. No human needed.

    Rosy has no token refresh of any kind, so the only way to get a live token
    is to sign in again. Google will do that silently for an app Alex has
    already consented to, which makes the whole thing a redirect chain:

        /login?id=<salon>            establishes which salon this sign-in is for
        /oauth2/authorization/google Rosy hands off to Google
        accounts.google.com          approves from Chrome's cookies, returns a code
        /login/oauth2/code/google    Rosy exchanges it and starts a session

    The first hop is not optional. Skip it and the callback comes back
    `id=null`, Rosy cannot tell which salon's customer list to match the Google
    identity against, decides this must be a new customer, and bounces off
    `newOnlineAccountCreationsAreNotAllowed`. That error names the wrong cause
    and will send the next reader hunting for a permissions problem.
    """
    jar = _sso_jar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    headers = {"User-Agent": CHROME_UA, "accept": "text/html,application/xhtml+xml"}

    login = f"{BASE}/login?id={salon_id}"
    try:
        opener.open(urllib.request.Request(login, headers=headers), timeout=40).read()
        chain = opener.open(
            urllib.request.Request(
                f"{BASE}/oauth2/authorization/google?id={salon_id}",
                headers={**headers, "referer": login},
            ),
            timeout=40,
        )
        html = chain.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise NoSession(
            f"Google sign-in replay failed at HTTP {exc.code}. {RELOGIN}"
        ) from exc

    if "isCustomerLoggedIn = true" not in html:
        raise NoSession(
            "Google sign-in replay completed but Rosy did not sign us in "
            f"(landed on {chain.url.split('?')[0]}). {RELOGIN}"
        )

    cookies = {c.name: c.value for c in jar if COOKIE_HOST in c.domain and c.value}
    if "JSESSIONID" not in cookies:
        raise NoSession(f"Google sign-in replay left no Rosy session. {RELOGIN}")
    _save(cookies)
    return cookies


def context(cookies: dict[str, str] | None = None) -> Context:
    """A customer JWT with enough life left to finish the run.

    THE 30-MINUTE WALL. Rosy mints the JWT once, at sign-in, and stores it in
    the server session; every authenticated page then replays that same token
    for its 30-minute life. Re-fetching the page does not re-mint it (verified:
    `cache-control: no-store`, a fresh `Date`, `isCustomerLoggedIn = true`, and
    the same `iat` as half an hour earlier), and the app ships no refresh
    endpoint -- it never handles a 401, because it assumes a human finishes
    booking in one sitting. So the JSESSIONID outliving the token means
    nothing; only a fresh Google sign-in mints a new one.

    That makes the expiry check load-bearing rather than defensive. Without it
    the failure surfaces as a bare `401` from whichever call happened to run
    first, which reads like a broken session or a bad cookie lift and sends you
    diagnosing the wrong thing entirely.
    """
    cookies = cookies or load_cookies()

    def usable(jar: dict[str, str]) -> tuple[str, int] | None:
        """A token from this session, if it is signed in and not spent."""
        html = _fetch(f"{BASE}/appointments", jar)
        if "isCustomerLoggedIn = true" not in html:
            return None
        token, customer_id = _scrape(html)
        life = _token_lifetime(token)
        if life and life[1] - datetime.now(timezone.utc) < MIN_TOKEN_LIFE:
            return None
        return token, customer_id

    got = usable(cookies)
    if got is None:
        # Signed out, or holding a token too spent to finish the run. Both have
        # the same cure and it needs no human, so take it rather than reporting
        # a dead session.
        cookies = refresh(load().get("salonId", 41947))
        got = usable(cookies)
        if got is None:
            raise NoSession(f"signed in again but Rosy still will not talk. {RELOGIN}")

    token, customer_id = got
    return Context(token=token, customer_id=customer_id, cookies=cookies)
