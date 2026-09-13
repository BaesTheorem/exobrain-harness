"""Logging in to the Kansas City Urban Explorers phpBB forum, and staying logged in.

INVARIANTS:
- The password and the session cookies are as good as each other; both live under
  secrets/ (gitignored, 0600) and are never printed, logged, or committed.
- A stored session is reused until the server says it is anonymous. phpBB hands out a
  session id to guests too, so "we have cookies" is NOT evidence of being logged in:
  only the user id cookie (phpbb3_*_u) being something other than 1 is. Anonymous is
  user id 1 in every phpBB install, which is why a bare 200 response proves nothing.
- Every request goes through Session, which paces itself. This is a small volunteer
  forum on shared hosting, not an API.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent.parent  # kcurbex/
SECRETS = HERE / "secrets"
CRED_PATH = SECRETS / "credentials.json"
COOKIE_PATH = SECRETS / "cookies.json"
HARNESS_ENV = HERE.parent / ".env"

BASE = "https://www.kcurbex.org"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
# Seconds between requests. Deliberately slow: the whole scan is a few hundred pages
# spread over a night, and a volunteer forum should never notice us.
MIN_INTERVAL = 2.5

ANONYMOUS_USER_ID = "1"


def env_value(key: str) -> str | None:
    """A key from the process environment, falling back to the harness .env file."""
    val = os.environ.get(key)
    if val:
        return val
    if HARNESS_ENV.exists():
        for line in HARNESS_ENV.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def load_credentials() -> tuple[str, str]:
    """(username, password), from the environment or the gitignored secrets file."""
    user = env_value("KCURBEX_USERNAME")
    pw = env_value("KCURBEX_PASSWORD")
    if user and pw:
        return user, pw
    if CRED_PATH.exists():
        data = json.loads(CRED_PATH.read_text())
        if data.get("username") and data.get("password"):
            return data["username"], data["password"]
    raise RuntimeError(
        f"no forum credentials: set KCURBEX_USERNAME/KCURBEX_PASSWORD or write {CRED_PATH} "
        "(see secrets/README.md)"
    )


def save_credentials(username: str, password: str) -> Path:
    SECRETS.mkdir(parents=True, exist_ok=True)
    CRED_PATH.write_text(json.dumps({"username": username, "password": password}))
    CRED_PATH.chmod(0o600)
    return CRED_PATH


class Session:
    """A polite, logged-in requests session against the forum."""

    def __init__(self) -> None:
        self.http = requests.Session()
        self.http.headers["User-Agent"] = UA
        self._last_request = 0.0
        self._username: str | None = None
        self._load_cookies()

    # -- plumbing ------------------------------------------------------------------

    def _load_cookies(self) -> None:
        if COOKIE_PATH.exists():
            for name, value in json.loads(COOKIE_PATH.read_text()).items():
                self.http.cookies.set(name, value, domain=".kcurbex.org")

    def _save_cookies(self) -> None:
        SECRETS.mkdir(parents=True, exist_ok=True)
        COOKIE_PATH.write_text(json.dumps(dict(self.http.cookies)))
        COOKIE_PATH.chmod(0o600)

    def get(self, url: str, **kw) -> requests.Response:
        """A paced GET. Relative paths are resolved against the forum root."""
        if not url.startswith("http"):
            url = f"{BASE}/{url.lstrip('./')}"
        gap = time.monotonic() - self._last_request
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        self._last_request = time.monotonic()
        resp = self.http.get(url, timeout=30, **kw)
        resp.raise_for_status()
        return resp

    def soup(self, url: str, **kw) -> BeautifulSoup:
        return BeautifulSoup(self.get(url, **kw).text, "lxml")

    # -- identity ------------------------------------------------------------------

    def is_logged_in(self) -> bool:
        """Whether the forum is treating us as a real user rather than a guest.

        Presence of a logout link is the signal. Do not trust the cookie jar: an expired
        session still leaves a phpbb3_*_u cookie sitting there with a real user id in it.
        Do not try to read the name off this page either -- this style renders the logout
        control as a bare icon, and the nearest username in the markup belongs to whoever
        happens to lead "who is online".
        """
        return "mode=logout" in self.get("index.php").text

    def user_id(self) -> str | None:
        """Our forum user id, per the session cookie. phpBB uses 1 for anonymous."""
        for name, value in self.http.cookies.items():
            if name.endswith("_u"):
                return None if value == ANONYMOUS_USER_ID else value
        return None

    def username(self) -> str | None:
        """Our display name, straight off our own profile page (cached per session)."""
        if self._username is not None:
            return self._username
        uid = self.user_id()
        if not uid:
            return None
        prof = self.soup(f"memberlist.php?mode=viewprofile&u={uid}")
        tag = prof.find(class_="username") or prof.find("h2")
        if tag:
            self._username = " ".join(tag.get_text(" ", strip=True).split()) or None
        return self._username

    def login(self, force: bool = False) -> str:
        """Ensure we are logged in; returns the username. Reuses a live session."""
        if not force and self.is_logged_in():
            return self.username() or "(logged in)"

        username, password = load_credentials()
        # phpBB stamps the login form with a one-shot token pair; it rejects a POST
        # that does not carry the exact pair it just rendered.
        form = self.soup("ucp.php?mode=login")
        payload = {
            "username": username,
            "password": password,
            "autologin": "on",
            "viewonline": "on",
            "login": "Login",
            "redirect": "index.php",
        }
        for field in ("sid", "creation_time", "form_token", "redirect"):
            tag = form.find("input", attrs={"name": field})
            if tag and tag.get("value"):
                payload[field] = tag["value"]

        gap = time.monotonic() - self._last_request
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        self._last_request = time.monotonic()
        resp = self.http.post(
            f"{BASE}/ucp.php?mode=login",
            data=payload,
            timeout=30,
            headers={"Referer": f"{BASE}/ucp.php?mode=login"},
        )
        resp.raise_for_status()

        self._username = None
        if not self.is_logged_in():
            reason = self._login_error(resp.text)
            raise RuntimeError(f"forum login failed for {username!r}{reason}")
        self._save_cookies()
        return self.username() or "(logged in)"

    @staticmethod
    def _login_error(html: str) -> str:
        """phpBB's own complaint about the login, if it rendered one."""
        soup = BeautifulSoup(html, "lxml")
        box = soup.find(class_="error") or soup.find(id="message")
        if box:
            text = " ".join(box.get_text(" ", strip=True).split())
            if text:
                return f": {text[:200]}"
        return " (no error message on the response; password may be stale)"
