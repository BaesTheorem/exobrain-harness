#!/usr/bin/env python3
"""Pull the live Booksy session cookie out of Chrome's cookie store.

Booksy authenticates with an `identity-us` cookie on booksy.com. Chrome stores
cookie values encrypted with a key kept in the macOS Keychain ("Chrome Safe
Storage"), so reading the DB alone gives ciphertext. This derives the same key
Chrome uses and decrypts just that one cookie.

Why this exists at all: Booksy's login is behind hCaptcha, which no automated
browser gets through. Alex logs in normally, and we lift the resulting session
rather than replaying credentials. Nothing here needs, stores, or sees a
password.

INVARIANTS (an edit must not break these):
- Only booksy.com cookies are ever read or written out. This touches a
  personal browser profile; widening the host filter turns a scoped session
  grab into a credential dump.
- The output file is gitignored and holds a live session. Never print the
  token to stdout or a log -- report only its length and whether it works.

Usage:
    python3 extract_session.py            # writes .booksy-session.json
    python3 extract_session.py --verify   # also calls /me to prove it works
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from hashlib import pbkdf2_hmac, sha256
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HERE = Path(__file__).resolve().parent
OUT_PATH = HERE / ".booksy-session.json"
COOKIE_DB = Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies"

# Chrome's fixed macOS key-derivation parameters.
SALT = b"saltysalt"
ITERATIONS = 1003
KEY_LEN = 16
IV = b" " * 16

ME_URL = "https://us.booksy.com/core/v2/customer_api/me"
WEB_API_KEY = "web-e3d812bf-d7a2-445d-ab38-55589ae6a121"


class ExtractError(RuntimeError):
    """The session could not be read."""


def keychain_password() -> str:
    """Chrome's Safe Storage secret. macOS may prompt for access."""
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                "/usr/bin/security",
                "find-generic-password",
                "-w",
                "-s",
                "Chrome Safe Storage",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractError("Keychain prompt timed out; approve it and retry") from exc
    if out.returncode != 0:
        raise ExtractError(f"could not read Keychain: {out.stderr.strip()}")
    return out.stdout.strip()


def decrypt(blob: bytes, key: bytes, host: str) -> str:
    """Decrypt one Chrome cookie value.

    Chrome >=130 prepends a 32-byte SHA-256 of the cookie's host to the
    plaintext. Detect it by actually recomputing the hash rather than by
    sniffing whether the first byte looks printable -- that heuristic silently
    fails whenever the hash happens to begin with a printable byte (it did
    here: sha256("booksy.com") starts with 0x47, "G"), leaving 32 bytes of
    binary glued to the front of the token.
    """
    if not blob:
        return ""
    if blob[:3] not in (b"v10", b"v11"):
        # Unencrypted (rare on macOS) -- return as-is.
        return blob.decode("utf-8", "replace")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(IV)).decryptor()
    plain = decryptor.update(blob[3:]) + decryptor.finalize()
    if plain:
        plain = plain[: -plain[-1]]  # strip PKCS#7 padding

    bare = host.lstrip(".")
    for candidate in (bare, host):
        if plain[:32] == sha256(candidate.encode()).digest():
            plain = plain[32:]
            break
    return plain.decode("utf-8", "replace")


def read_cookies() -> dict[str, str]:
    if not COOKIE_DB.exists():
        raise ExtractError(f"no Chrome cookie DB at {COOKIE_DB}")

    key = pbkdf2_hmac("sha1", keychain_password().encode(), SALT, ITERATIONS, KEY_LEN)

    # Copy first: Chrome holds a lock on the live file.
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    shutil.copy(COOKIE_DB, tmp_path)
    try:
        conn = sqlite3.connect(tmp_path)
        rows = conn.execute(
            "select name, encrypted_value, host_key from cookies "
            "where host_key like '%booksy.com' order by creation_utc desc"
        ).fetchall()
    finally:
        tmp_path.unlink(missing_ok=True)

    out: dict[str, str] = {}
    for name, blob, host in rows:
        if name in out:
            continue
        try:
            value = decrypt(blob, key, host)
        except Exception as exc:  # noqa: BLE001 - one bad cookie must not stop the rest
            print(f"  ! {name}: {type(exc).__name__}", file=sys.stderr)
            continue
        if value:
            out[name] = value
    return out


def verify(cookies: dict[str, str]) -> bool:
    """Prove the session actually authenticates before we rely on it."""
    jar = "; ".join(f"{k}={v}" for k, v in cookies.items())
    req = urllib.request.Request(
        ME_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
            ),
            "x-api-key": WEB_API_KEY,
            "accept": "application/json",
            "cookie": jar,
            "origin": "https://booksy.com",
            "referer": "https://booksy.com/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"  /me -> HTTP {exc.code}: {exc.read()[:200].decode('utf-8', 'replace')}")
        return False
    except Exception as exc:  # noqa: BLE001 - report and fail closed
        print(f"  /me -> {type(exc).__name__}: {exc}")
        return False

    account = data.get("account") or data.get("customer") or data
    name = account.get("first_name") or account.get("name") or "(signed in)"
    print(f"  /me -> 200, authenticated as {name}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract the Booksy session from Chrome.")
    parser.add_argument("--verify", action="store_true", help="call /me to prove it works")
    args = parser.parse_args(argv)

    try:
        cookies = read_cookies()
    except ExtractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not cookies:
        print("no booksy.com cookies found", file=sys.stderr)
        return 1

    # Report shape only -- never the values.
    print(f"recovered {len(cookies)} booksy cookies:")
    for name, value in cookies.items():
        print(f"  {name:22} {len(value)} chars")

    if "identity-us" not in cookies:
        print("\nwarning: no 'identity-us' cookie -- that is the session one.")

    OUT_PATH.write_text(json.dumps({"cookies": cookies}, indent=1) + "\n")
    OUT_PATH.chmod(0o600)
    print(f"\nsaved -> {OUT_PATH.name} (gitignored, 0600)")

    if args.verify:
        print("\nverifying:")
        return 0 if verify(cookies) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
