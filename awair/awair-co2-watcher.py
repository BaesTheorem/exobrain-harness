#!/usr/bin/env python3
"""
Polls the Awair Element local API for CO2 and fires a macOS notification
when levels exceed configured thresholds during active hours.

Hysteresis prevents notification spam: after notifying, suppress same-tier
alerts for HYSTERESIS_MIN minutes. Persists state in awair/state.json.

Config via env (.env at harness root): AWAIR_HOST.
Tunable constants below.
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = Path(__file__).resolve().parent / "state.json"
LOG_FILE = Path.home() / ".claude" / "channels" / "awair" / "co2-watcher.log"

CO2_WARN = 1000
CO2_URGENT = 1500
HYSTERESIS_MIN = 30
ACTIVE_HOUR_START = 7
ACTIVE_HOUR_END = 23


def load_env():
    env_path = HARNESS_DIR / ".env"
    if not env_path.exists():
        return {}
    out = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def log(msg):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().isoformat(timespec="seconds")
    with LOG_FILE.open("a") as f:
        f.write(f"[{ts}] {msg}\n")


def fetch_air_data(host):
    url = f"http://{host}/air-data/latest"
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read())


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def notify(title, message, urgent=False):
    sound = "Basso" if urgent else "Purr"
    label = "Exobrain URGENT" if urgent else "Exobrain"
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "{message}" with title "{label}: {title}" sound name "{sound}"',
        ],
        check=False,
    )


def in_active_hours(now):
    return ACTIVE_HOUR_START <= now.hour < ACTIVE_HOUR_END


def main():
    env = load_env()
    host = env.get("AWAIR_HOST")
    if not host:
        log("AWAIR_HOST not set in .env; exiting")
        sys.exit(0)

    now = datetime.now()
    if not in_active_hours(now):
        return

    try:
        data = fetch_air_data(host)
    except Exception as e:
        log(f"fetch failed: {e}")
        return

    co2 = data.get("co2")
    if co2 is None:
        log(f"no co2 in response: {data}")
        return

    tier = None
    if co2 >= CO2_URGENT:
        tier = "urgent"
    elif co2 >= CO2_WARN:
        tier = "warn"

    if tier is None:
        return

    state = load_state()
    last_iso = state.get(f"last_{tier}")
    if last_iso:
        last = datetime.fromisoformat(last_iso)
        if (now - last).total_seconds() < HYSTERESIS_MIN * 60:
            return

    score = data.get("score", "?")
    pm25 = data.get("pm25", "?")
    msg = f"CO2 {co2} ppm (score {score}, PM2.5 {pm25}) — open a window"
    notify("Air quality", msg, urgent=(tier == "urgent"))
    log(f"notified {tier}: co2={co2} score={score} pm25={pm25}")

    state[f"last_{tier}"] = now.isoformat(timespec="seconds")
    save_state(state)


if __name__ == "__main__":
    main()
