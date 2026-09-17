"""Refresh secrets/cookies.txt from a live desktop-browser session.

Facebook session cookies expire, and the documented fix was a manual export
via a browser extension. That fails silently: a logged-out scrape returns
empty results indistinguishable from "nothing there", which on a
missing-person search is the difference between "no new tips" and "the tool is
broken". So this reads the current session straight from Chrome/Brave's cookie
store on disk.

macOS Chromium v10 cookies are AES-128-CBC. The key is
PBKDF2-HMAC-**SHA1**(safe-storage secret from the login Keychain, salt
'saltysalt', 1003 iters, 16 bytes); IV = 16 spaces. The hash is SHA1, not
SHA256 (SHA256 derives a wrong key that decrypts to garbage and cost an hour to
rule out). Chrome >= v130 prepends a 32-byte SHA-256 domain hash to the
plaintext, stripped here.

Two things do NOT work on current Chrome and are recorded so they are not
retried: launching Chrome (headless or headed) against a COPIED profile returns
zero cookies, because the key is bound to the original profile; and there are
two "Chrome Safe Storage" Keychain items, but `-ws` returns the usable one.

v20 (App-Bound) cookies are not handled; Facebook's have stayed v10. Read-only:
copies the cookie DB (the browser may hold a write lock; reads are fine) and
never writes to the browser.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SUPPORT = Path.home() / "Library/Application Support"
# browser -> (cookie DB, Keychain service). Chrome writes the DB at
# Default/Cookies on this build; Default/Network/Cookies on others.
BROWSERS = {
    "chrome": (SUPPORT / "Google/Chrome/Default", "Chrome Safe Storage"),
    "brave": (SUPPORT / "BraveSoftware/Brave-Browser/Default", "Brave Safe Storage"),
}
NEEDED = {"c_user", "xs"}
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "secrets" / "cookies.txt"


def _cookie_db(profile: Path) -> Path:
    for rel in ("Network/Cookies", "Cookies"):
        db = profile / rel
        if db.exists():
            return db
    raise FileNotFoundError(f"no cookie DB under {profile}")


def _safe_storage_key(service: str) -> bytes:
    out = subprocess.run(["security", "find-generic-password", "-ws", service],
                         capture_output=True, text=True, check=True)
    secret = out.stdout.strip().encode()
    return hashlib.pbkdf2_hmac("sha1", secret, b"saltysalt", 1003, dklen=16)


def _decrypt(blob: bytes, key: bytes) -> str | None:
    if not blob or blob[:3] != b"v10":
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


def export_session(browser: str) -> list[tuple]:
    profile, service = BROWSERS[browser]
    if not profile.exists():
        raise FileNotFoundError(f"{browser}: no profile at {profile}")
    key = _safe_storage_key(service)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "Cookies"
        shutil.copy2(_cookie_db(profile), copy)
        con = sqlite3.connect(copy)
        rows = con.execute(
            "select host_key, path, is_secure, expires_utc, name, encrypted_value "
            "from cookies where host_key like '%facebook.com'").fetchall()
        con.close()
    out = []
    for host, path, secure, expires_utc, name, enc in rows:
        value = _decrypt(enc, key)
        if value is None:
            continue
        unix = max(0, expires_utc // 1_000_000 - 11644473600) if expires_utc else 0
        out.append((host, "TRUE" if host.startswith(".") else "FALSE", path,
                    "TRUE" if secure else "FALSE", unix, name, value))
    return out


def _to_netscape(rows: list[tuple]) -> str:
    lines = ["# Netscape HTTP Cookie File", "# Refreshed by fb refresh-cookies", ""]
    for host, flag, path, secure, expires, name, value in rows:
        lines.append("\t".join([host, flag, path, secure, str(expires), name, value]))
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="fb refresh-cookies", description=__doc__)
    ap.add_argument("--browser", choices=list(BROWSERS), default="chrome")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true", help="report the session, write nothing")
    args = ap.parse_args(argv)

    try:
        rows = export_session(args.browser)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"{args.browser}: {exc}", file=sys.stderr)
        return 1
    names = {r[5] for r in rows}
    missing = NEEDED - names
    if missing:
        print(f"{args.browser}: session incomplete, missing {missing}. "
              "Log in to facebook.com in that browser first.", file=sys.stderr)
        return 1
    print(f"{args.browser}: {len(rows)} facebook cookies, session present "
          f"({', '.join(sorted(names & NEEDED))})")
    if args.dry_run:
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_to_netscape(rows))
    out.chmod(0o600)
    print(f"wrote {out}")
    return 0
