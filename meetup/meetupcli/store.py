"""Where the Meetup login cookie lives, and the default search location.

INVARIANTS:
- The cookie is the browser's whole Cookie header for meetup.com and is as good as the
  password while it lives: written 0600, never printed, never committed (secrets/ is
  gitignored, see secrets/README.md).
- Lookup order is MEETUP_COOKIE in the environment, then the harness .env, then
  secrets/cookie.txt, so a one-off override never has to touch the stored file.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent  # meetup/
SECRETS = HERE / "secrets"
COOKIE_PATH = SECRETS / "cookie.txt"
HARNESS_ENV = HERE.parent / ".env"

# Kansas City, MO as meetup.com's own locationSearch resolves it.
HOME_DEFAULT = ("Kansas City, MO", 39.0999, -94.5999)
DEFAULT_TZ = "America/Chicago"


def env_value(key: str) -> str | None:
    """A key from the process environment, falling back to the harness .env file."""
    val = os.environ.get(key)
    if val:
        return val
    if HARNESS_ENV.exists():
        for line in HARNESS_ENV.read_text().splitlines():
            if line.startswith(key + "="):
                val = line.split("=", 1)[1].strip().strip("'\"")
                return val or None
    return None


def clean_cookie(text: str) -> str:
    """Accept a pasted DevTools header line ('cookie: a=b; c=d') or a raw cookie string."""
    text = text.strip()
    text = re.sub(r"^cookie\s*:\s*", "", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def load_cookie() -> str | None:
    val = env_value("MEETUP_COOKIE")
    if val:
        return clean_cookie(val)
    if COOKIE_PATH.exists():
        return clean_cookie(COOKIE_PATH.read_text()) or None
    return None


def cookie_source() -> str | None:
    if os.environ.get("MEETUP_COOKIE"):
        return "MEETUP_COOKIE (environment)"
    if env_value("MEETUP_COOKIE"):
        return f"MEETUP_COOKIE ({HARNESS_ENV})"
    if COOKIE_PATH.exists() and COOKIE_PATH.read_text().strip():
        return str(COOKIE_PATH)
    return None


def save_cookie(text: str) -> Path:
    cleaned = clean_cookie(text)
    if not cleaned or "=" not in cleaned:
        raise ValueError("that does not look like a cookie header (expected name=value pairs)")
    SECRETS.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SECRETS, prefix=".cookie-", suffix=".txt")
    with os.fdopen(fd, "w") as fh:
        fh.write(cleaned + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, COOKIE_PATH)
    return COOKIE_PATH


def clear_cookie() -> bool:
    if COOKIE_PATH.exists():
        COOKIE_PATH.unlink()
        return True
    return False


def home_location() -> tuple[str, float, float]:
    """(label, lat, lon). MEETUP_HOME='lat,lon[,label]' overrides the built-in default."""
    raw = env_value("MEETUP_HOME")
    if raw:
        parts = [p.strip() for p in raw.split(",")]
        try:
            lat, lon = float(parts[0]), float(parts[1])
        except (IndexError, ValueError):
            raise ValueError(f"MEETUP_HOME must be 'lat,lon[,label]', got {raw!r}") from None
        label = parts[2] if len(parts) > 2 and parts[2] else f"{lat},{lon}"
        return label, lat, lon
    return HOME_DEFAULT


def timezone_name() -> str:
    return env_value("MEETUP_TZ") or DEFAULT_TZ


# -- browser import ----------------------------------------------------------------------------

BROWSERS = ("chrome", "safari", "firefox", "brave", "edge", "chromium")


def jar_to_header(text: str) -> str:
    """The meetup.com cookies in a Netscape cookies.txt, as one Cookie header value."""
    pairs: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw[len("#HttpOnly_"):] if raw.startswith("#HttpOnly_") else raw
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, _path, _secure, _expires, name, value = parts[:7]
        host = domain.lstrip(".")
        if host == "meetup.com" or host.endswith(".meetup.com"):
            pairs[name] = value
    return "; ".join(f"{k}={v}" for k, v in pairs.items())


def import_cookie_from_browser(browser: str = "chrome") -> str:
    """Pull the meetup.com cookies out of a browser profile with yt-dlp's extractor.

    yt-dlp already knows how to read (and on macOS decrypt) the Chrome, Safari, and Firefox
    cookie stores. It dumps a full jar to a private temp file; only the meetup.com lines are
    kept, and the rest is overwritten before the directory goes away, so no other site's
    session lands anywhere durable. The first Chrome read may raise a Keychain prompt for
    "Chrome Safe Storage"; allow it.
    """
    if browser not in BROWSERS:
        raise ValueError(f"unknown browser {browser!r}; pick one of {', '.join(BROWSERS)}")
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp is not installed (brew install yt-dlp), or paste the header with `meetup auth set`")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "jar.txt"
        # The URL is deliberately bogus: only the --cookies side effect matters.
        subprocess.run(
            ["yt-dlp", "--cookies-from-browser", browser, "--cookies", str(tmp), "--simulate",
             "--skip-download", "--no-warnings", "https://www.meetup.com/_cookie_export_/"],
            capture_output=True, check=False,
        )
        if not tmp.exists():
            raise RuntimeError(f"yt-dlp wrote no cookie jar from {browser}; is it installed and logged in to meetup.com?")
        header = jar_to_header(tmp.read_text(encoding="utf-8", errors="replace"))
        tmp.write_bytes(b"\0" * tmp.stat().st_size)
    if not header:
        raise RuntimeError(f"no meetup.com cookies in {browser}; log in to meetup.com there first")
    return header
