"""Static facts about the booking target, plus the tunable preferences.

Everything here is public information about a business (its Rosy salon id, its
address, the service menu it publishes). Nothing personal lives in this file:
the customer id and the session token are read from the live browser session at
runtime, never stored in the repo.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CONFIG_PATH = HERE / "config.json"

BASE = "https://online.rosysalonsoftware.com"
API = f"{BASE}/api/v2"

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

DEFAULTS = {
    "salonId": 41947,
    "salonName": "Salon Ramon",
    "defaultService": "Men's Haircut",
    "defaultProvider": "Ramon",
    "preferWeekdays": True,
    "searchDays": 21,
    "preferredWindow": ["10:00", "18:00"],
}


def load() -> dict:
    """Config from disk, with the defaults filled in for anything missing."""
    data = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        data.update(json.loads(CONFIG_PATH.read_text()))
    return data
