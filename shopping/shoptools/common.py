"""Shared pieces for the shopping lanes: HTTP session, browser identity, home ZIP."""

from __future__ import annotations

import functools
import os
import re
import subprocess
from pathlib import Path

from curl_cffi import requests

ROOT = Path(__file__).resolve().parent.parent  # shopping/
HARNESS = ROOT.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class LaneError(RuntimeError):
    """A retailer lane could not answer. The message says why, so a block never reads as 'not sold'."""


@functools.lru_cache(maxsize=1)
def chrome_major() -> str:
    """Major version of the installed Chrome. Amazon binds a session to the browser identity."""
    try:
        out = subprocess.run([CHROME, "--version"], capture_output=True, text=True, timeout=10).stdout
        if m := re.search(r"(\d+)\.", out):
            return m.group(1)
    except (OSError, subprocess.SubprocessError):
        pass
    return "153"


def ua() -> str:
    """User-Agent for the Playwright (Amazon) lane. The curl_cffi lanes use impersonate's own UA."""
    return ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{chrome_major()}.0.0.0 Safari/537.36")


def session() -> requests.Session:
    """A Chrome-impersonating session. Akamai-walled retailers that 403 plain curl open to this."""
    return requests.Session(impersonate="chrome")


@functools.lru_cache(maxsize=1)
def home_zip() -> str:
    """HOME_ZIP from the environment or the harness .env (gitignored).

    Shelf prices, store stock and weekly ads are all local, so there is no default.
    """
    v = os.environ.get("HOME_ZIP", "")
    env = HARNESS / ".env"
    if not v and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("HOME_ZIP="):
                v = line.split("=", 1)[1].strip().strip("\"'")
    if not v:
        raise SystemExit("shop: HOME_ZIP is not set. Put HOME_ZIP=<zip> in the harness .env; local prices need it.")
    return v
