"""The live Rosy session, lifted from Chrome and turned into an API token.

Rosy's online booking is a Spring app behind a `JSESSIONID`. Alex signs in with
Google ("Continue with Google" -> /oauth2/authorization/google), and the login
page is guarded by reCAPTCHA, so no automated login is attempted here: we lift
the session he already has, exactly like the Booksy tool does.

The session cookie is not itself the API credential. Every server-rendered page
embeds a short-lived JWT (`jwtToken`) and the signed-in `customerId`, and the
`/api/v2` endpoints authenticate on `Authorization: Bearer <that JWT>`. The JWT
lasts 30 minutes, so it is scraped fresh on each run rather than cached to disk.

INVARIANTS (an edit must not break these):
- Only rosysalonsoftware.com cookies are ever read. This reads a personal
  browser profile; widening the host filter turns a scoped session grab into a
  credential dump.
- Never print, log, or return a token in a human-facing message. Report its
  length and whether it works, never its value.
- `context()` fails closed. A page that comes back logged-out raises instead of
  returning an anonymous token: the anonymous token can read the salon's
  catalogue fine, so a silent downgrade would look healthy right up until a
  booking POST returned 403.
"""

from __future__ import annotations

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
from hashlib import pbkdf2_hmac, sha256
from pathlib import Path

from .config import BASE, CHROME_UA

HERE = Path(__file__).resolve().parent.parent
SESSION_PATH = HERE / ".rosy-session.json"
COOKIE_DB = Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies"
COOKIE_HOST = "rosysalonsoftware.com"

# Chrome's fixed macOS key-derivation parameters.
SALT = b"saltysalt"
ITERATIONS = 1003
KEY_LEN = 16
IV = b" " * 16

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


def extract() -> dict[str, str]:
    """Read the Rosy cookies out of Chrome and save them, 0600."""
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
            "select name, encrypted_value, host_key from cookies "
            "where host_key like ? order by creation_utc desc",
            (f"%{COOKIE_HOST}",),
        ).fetchall()
        conn.close()
    finally:
        tmp_path.unlink(missing_ok=True)

    cookies: dict[str, str] = {}
    for name, blob, host in rows:
        if name in cookies:
            continue
        try:
            value = _decrypt(blob, key, host)
        except Exception as exc:  # noqa: BLE001 - one bad cookie must not stop the rest
            print(f"  ! {name}: {type(exc).__name__}", file=sys.stderr)
            continue
        if value:
            cookies[name] = value

    if "JSESSIONID" not in cookies:
        raise NoSession(f"no JSESSIONID cookie for {COOKIE_HOST}. {RELOGIN}")

    SESSION_PATH.write_text(json.dumps({"cookies": cookies}, indent=1) + "\n")
    SESSION_PATH.chmod(0o600)
    return cookies


def load_cookies() -> dict[str, str]:
    if not SESSION_PATH.exists():
        raise NoSession(f"no saved Rosy session. {RELOGIN}")
    cookies = json.loads(SESSION_PATH.read_text()).get("cookies") or {}
    if "JSESSIONID" not in cookies:
        raise NoSession(f"session file has no JSESSIONID. {RELOGIN}")
    return cookies


def _fetch(url: str, cookies: dict[str, str]) -> str:
    jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request(
        url,
        headers={"User-Agent": CHROME_UA, "cookie": jar, "accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise NoSession(f"{url} -> HTTP {exc.code}. {RELOGIN}") from exc


def context(cookies: dict[str, str] | None = None) -> Context:
    """Scrape a fresh customer JWT + customer id from a signed-in page."""
    cookies = cookies or load_cookies()
    html = _fetch(f"{BASE}/appointments", cookies)

    if "isCustomerLoggedIn = true" not in html:
        raise NoSession(f"Rosy says the session is signed out. {RELOGIN}")

    token = re.search(r'jwtToken = "([^"]+)"', html)
    customer = re.search(r"customerId = (\d+);", html)
    if not token or not customer:
        raise NoSession(f"signed-in page carried no token. {RELOGIN}")

    return Context(token=token.group(1), customer_id=int(customer.group(1)), cookies=cookies)
