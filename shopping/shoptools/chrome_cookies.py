"""Export the live amazon.com session out of Chrome's cookie store.

Alex signs in to amazon.com by hand in Chrome; this reads that session off
disk. The login itself is never automated, which is the whole point: Amazon's
login-anomaly detection is what locks accounts, and an account carrying Prime
and live payment methods is an expensive thing to get locked. No password is
ever read, stored, or required.

Adapted from facebook/fbtools/refresh_cookies.py. The top-level tool
directories are islands (checks/check_boundaries.py), so the crypto is
restated here rather than imported. The hard-won details, do not re-derive:

macOS Chromium v10 cookies are AES-128-CBC. The key is
PBKDF2-HMAC-**SHA1**(safe-storage secret from the login Keychain, salt
'saltysalt', 1003 iters, 16 bytes); IV = 16 spaces. The hash is SHA1, not
SHA256 (SHA256 derives a wrong key that decrypts to garbage and cost an hour
to rule out). Chrome >= v130 prepends a 32-byte SHA-256 domain hash to the
plaintext, stripped here. There are two "Chrome Safe Storage" Keychain items;
`security -ws` returns the usable one. Launching Chrome against a COPIED
profile returns zero cookies, because the key is bound to the original.

v20 (App-Bound) cookies are NOT handled. Amazon's were all v10 when this was
written (checked 2026-09-22, 23/23 cookies); `export_session` raises rather
than skipping them, so a future migration surfaces as an error instead of a
half-empty session that reads as "logged out".

Read-only: copies the cookie DB (the browser may hold a write lock; reads are
fine) and never writes to the browser.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SUPPORT = Path.home() / "Library/Application Support"
BROWSERS = {
    "chrome": (SUPPORT / "Google/Chrome/Default", "Chrome Safe Storage"),
    "brave": (SUPPORT / "BraveSoftware/Brave-Browser/Default", "Brave Safe Storage"),
}
# `at-main` is the access token and `x-main` identifies the account. Without
# both, the session will render signed-out pages that parse as empty results.
NEEDED = {"at-main", "x-main", "sess-at-main"}
SECRETS = Path(__file__).resolve().parent.parent / "secrets"
COOKIE_FILE = SECRETS / "amazon-cookies.json"


class NotLoggedIn(RuntimeError):
    """Chrome has no usable amazon.com session. Sign in there first."""


def _cookie_db(profile: Path) -> Path:
    for rel in ("Network/Cookies", "Cookies"):
        if (db := profile / rel).exists():
            return db
    raise FileNotFoundError(f"no cookie DB under {profile}")


def _safe_storage_key(service: str) -> bytes:
    out = subprocess.run(["security", "find-generic-password", "-ws", service],
                         capture_output=True, text=True, check=True)
    return hashlib.pbkdf2_hmac("sha1", out.stdout.strip().encode(), b"saltysalt", 1003, dklen=16)


def _decrypt(blob: bytes, key: bytes) -> str | None:
    if not blob:
        return None
    if blob[:3] == b"v20":
        raise RuntimeError(
            "Chrome has migrated amazon.com cookies to v20 App-Bound encryption, "
            "which this exporter cannot read. See the module docstring.")
    if blob[:3] != b"v10":
        return None
    dec = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    plain = dec.update(blob[3:]) + dec.finalize()
    if plain and plain[-1] <= 16:                 # strip PKCS7 padding
        plain = plain[: -plain[-1]]
    for candidate in (plain[32:], plain):         # Chrome >=130 domain-hash prefix, else raw
        try:
            return candidate.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def export_session(browser: str = "chrome") -> list[dict]:
    """Return amazon.com cookies as Playwright-shaped dicts."""
    profile, service = BROWSERS[browser]
    if not profile.exists():
        raise FileNotFoundError(f"{browser}: no profile at {profile}")
    key = _safe_storage_key(service)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "Cookies"
        shutil.copy2(_cookie_db(profile), copy)
        con = sqlite3.connect(copy)
        rows = con.execute(
            "select host_key, path, is_secure, is_httponly, expires_utc, name, encrypted_value, samesite "
            "from cookies where host_key like '%amazon.com'").fetchall()
        con.close()

    jar: list[dict] = []
    for host, path, secure, httponly, expires_utc, name, enc, samesite in rows:
        value = _decrypt(enc, key)
        if value is None:
            continue
        jar.append({
            "name": name,
            "value": value,
            "domain": host,
            "path": path or "/",
            "secure": bool(secure),
            "httpOnly": bool(httponly),
            "sameSite": {0: "None", 1: "Lax", 2: "Strict"}.get(samesite, "Lax"),
            # Chrome stores microseconds since 1601-01-01; Playwright wants unix seconds.
            "expires": (expires_utc // 1_000_000 - 11644473600) if expires_utc else -1,
        })
    missing = NEEDED - {c["name"] for c in jar}
    if missing:
        raise NotLoggedIn(
            f"{browser}: amazon.com session incomplete, missing {sorted(missing)}. "
            "Sign in to amazon.com in that browser, then re-run.")
    return jar


def save(jar: list[dict], path: Path = COOKIE_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jar, indent=2))
    path.chmod(0o600)
    return path


def load(path: Path = COOKIE_FILE) -> list[dict]:
    if not path.exists():
        raise NotLoggedIn(f"no saved session at {path}; run `amz auth --from-chrome` first")
    return json.loads(path.read_text())
