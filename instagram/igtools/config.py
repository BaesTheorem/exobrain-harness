"""Paths, cookie loading, and the borrowed-browser identity.

INVARIANTS
- Nothing under secrets/ or data/ is ever printed in full; the cookie file is
  written 0600 and the sessionid never reaches stdout.
- The User-Agent is derived from the installed Chrome so it matches the
  browser the session cookie came from; a mismatched UA is the cheapest way
  to get a session challenged.
"""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "secrets"
COOKIES = SECRETS / "cookies.txt"
DATA = ROOT / "data"
COOLDOWN = DATA / "cooldown.json"
SCAN_OUT = DATA / "kc-events-scan.json"
MEDIA = DATA / "media"
ACCOUNTS_EXAMPLE = ROOT / "accounts.example.json"
PREFS = ROOT.parent / "local-events" / "local-events-prefs.json"

CHROME_PLIST = Path("/Applications/Google Chrome.app/Contents/Info.plist")
FALLBACK_CHROME = "140.0.0.0"

IG_APP_ID = "936619743392459"  # the instagram.com web client's X-IG-App-ID
IG_ASBD_ID = "129477"


def chrome_version() -> str:
    try:
        with CHROME_PLIST.open("rb") as fh:
            return str(plistlib.load(fh)["CFBundleShortVersionString"])
    except Exception:
        return FALLBACK_CHROME


def user_agent() -> str:
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{chrome_version()} Safari/537.36"
    )


@dataclass
class Cookies:
    values: dict[str, str] = field(default_factory=dict)
    expires: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.values.get("sessionid") and self.values.get("csrftoken"))

    def header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.values.items())

    def expiry(self, name: str) -> datetime | None:
        ts = self.expires.get(name)
        return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def load_cookies(path: Path = COOKIES) -> Cookies:
    """Parse a Netscape cookies.txt, keeping only instagram.com entries.

    Handles the `#HttpOnly_` prefix that browser exporters and yt-dlp emit.
    """
    jar = Cookies()
    if not path.exists():
        return jar
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, _path, _secure, expires, name, value = parts[:7]
        if "instagram.com" not in domain:
            continue
        jar.values[name] = value
        try:
            jar.expires[name] = _unix_expiry(int(expires))
        except ValueError:
            pass
    return jar


def _unix_expiry(raw: int) -> int:
    """Browser exporters write Unix seconds; yt-dlp's Chrome path leaks the
    raw WebKit stamp (microseconds since 1601). Anything past year 5000 in
    seconds is the latter, so convert."""
    if raw > 100_000_000_000:
        return raw // 1_000_000 - 11_644_473_600
    return raw


def import_cookies_from_chrome(dest: Path = COOKIES) -> Cookies:
    """Pull the instagram.com cookies out of the running Chrome profile.

    yt-dlp already knows how to decrypt Chrome's cookie store on macOS, so we
    let it dump a jar to a private temp file, keep only the instagram.com
    lines, and shred the rest. The full jar (every site's session) never
    lands anywhere durable.
    """
    SECRETS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "all.txt"
        # A deliberately bogus URL: we only want the side effect of --cookies.
        subprocess.run(
            [
                "yt-dlp",
                "--cookies-from-browser",
                "chrome",
                "--cookies",
                str(tmp),
                "--simulate",
                "--skip-download",
                "--no-warnings",
                "https://www.instagram.com/p/_cookie_export_/",
            ],
            capture_output=True,
            check=False,
        )
        if not tmp.exists():
            raise RuntimeError("yt-dlp wrote no cookie jar; is yt-dlp installed and Chrome logged in?")
        keep = ["# Netscape HTTP Cookie File", "# instagram.com only; exported by `ig cookies --from-chrome`"]
        for line in tmp.read_text(encoding="utf-8", errors="replace").splitlines():
            if "instagram.com" in line:
                keep.append(line)
        _write_private(dest, "\n".join(keep) + "\n")
        # Overwrite before the tempdir goes away so the plaintext does not linger.
        tmp.write_bytes(b"\0" * tmp.stat().st_size)
    return load_cookies(dest)


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def cookie_health() -> dict:
    jar = load_cookies()
    exp = jar.expiry("sessionid")
    return {
        "present": COOKIES.exists(),
        "ok": jar.ok,
        "user_id": jar.values.get("ds_user_id"),
        "sessionid_expires": exp.isoformat() if exp else None,
        "expired": bool(exp and exp < datetime.now(timezone.utc)),
        "names": sorted(jar.values),
    }


def load_accounts(path: Path | None = None) -> list[str]:
    """Accounts to scan: an explicit file, else `instagramAccounts` in the
    local-events prefs, else the tracked example list."""
    if path is not None:
        return _accounts_from(json.loads(path.read_text()))
    if PREFS.exists():
        prefs = json.loads(PREFS.read_text())
        if prefs.get("instagramAccounts"):
            return _accounts_from(prefs["instagramAccounts"])
    return _accounts_from(json.loads(ACCOUNTS_EXAMPLE.read_text()))


def _accounts_from(obj) -> list[str]:
    if isinstance(obj, dict):
        obj = obj.get("accounts", [])
    out: list[str] = []
    for item in obj:
        handle = item["username"] if isinstance(item, dict) else str(item)
        handle = handle.strip().lstrip("@").lower()
        if handle and handle not in out:
            out.append(handle)
    return out


def cooldown_until() -> datetime | None:
    if not COOLDOWN.exists():
        return None
    try:
        until = datetime.fromisoformat(json.loads(COOLDOWN.read_text())["until"])
    except Exception:
        return None
    return until if until > datetime.now(timezone.utc) else None


def set_cooldown(minutes: int, reason: str) -> datetime:
    from datetime import timedelta

    DATA.mkdir(parents=True, exist_ok=True)
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    COOLDOWN.write_text(json.dumps({"until": until.isoformat(), "reason": reason}, indent=2))
    return until


def clear_cooldown() -> None:
    if COOLDOWN.exists():
        COOLDOWN.unlink()
