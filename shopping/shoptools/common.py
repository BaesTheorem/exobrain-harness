"""Shared pieces for the shopping lanes: HTTP session, browser identity, home ZIP."""

from __future__ import annotations

import functools
import os
import re
import subprocess
from pathlib import Path

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


def session():
    """A Chrome-impersonating session. Akamai-walled retailers that 403 plain curl open to this.

    Imported here, not at module top, so the parsers import (and test) without curl_cffi.
    """
    from curl_cffi import requests

    return requests.Session(impersonate="chrome")


def env(name: str) -> str:
    """One value from the environment or the harness .env (gitignored)."""
    v = os.environ.get(name, "")
    dotenv = HARNESS / ".env"
    if not v and dotenv.exists():
        for line in dotenv.read_text().splitlines():
            if line.startswith(name + "="):
                v = line.split("=", 1)[1].strip().strip("\"'")
    return v


@functools.lru_cache(maxsize=1)
def home_zip() -> str:
    """HOME_ZIP. Shelf prices, store stock and weekly ads are all local, so there is no default."""
    v = env("HOME_ZIP")
    if not v:
        raise SystemExit("shop: HOME_ZIP is not set. Put HOME_ZIP=<zip> in the harness .env; local prices need it.")
    return v


@functools.lru_cache(maxsize=1)
def home_latlon() -> tuple[float, float]:
    """Home point for radius searches. MYKCMO_HOME_LAT/LON are the harness-wide home geocode."""
    lat, lon = env("MYKCMO_HOME_LAT"), env("MYKCMO_HOME_LON")
    if not lat or not lon:
        raise SystemExit("shop: MYKCMO_HOME_LAT/MYKCMO_HOME_LON are not set in the harness .env; "
                         "radius searches need a home point.")
    return float(lat), float(lon)
