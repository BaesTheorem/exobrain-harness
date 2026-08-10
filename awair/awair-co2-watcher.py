#!/usr/bin/env python3
"""
Polls the Awair Element local API every run. It ALWAYS logs the reading to the
air-log time series (24/7, so the bedroom's overnight CO2/humidity is captured),
and fires a macOS notification AND a Discord DM only when levels exceed
configured thresholds DURING active hours (so no 3am banners).

Hysteresis prevents notification spam: after notifying, suppress same-tier
alerts for HYSTERESIS_MIN minutes. Persists state in awair/state.json.

Config:
  - harness .env (AWAIR_HOST, DISCORD_NOTIFY_CHAT_ID)
  - ~/.claude/channels/discord/.env (DISCORD_BOT_TOKEN)
Tunable constants below.

INVARIANTS (do not break these in an edit):
  - Log first, alert second: every successful poll appends to air-log.csv,
    including quiet-hours readings. Alerting logic must never gate logging.
  - air-log.csv is append-only with a stable column order; other tools chart
    it, so schema changes need a migration, not an in-place reorder.
  - No notifications outside ACTIVE_HOUR_START..END, and hysteresis state
    lives in state.json; both exist to stop 3am banner spam.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = Path(__file__).resolve().parent / "state.json"
AIR_CSV = Path(__file__).resolve().parent / "air-log.csv"
LOG_FILE = Path.home() / ".claude" / "channels" / "awair" / "co2-watcher.log"
DISCORD_ENV = Path.home() / ".claude" / "channels" / "discord" / ".env"
DISCORD_API = "https://discord.com/api/v10"

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


def resolve_host(host):
    """Return an IP for host, or None. mDNS .local names often fail to
    resolve from a launchd context, so callers fall back to a cached IP."""
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def fetch_with_fallback(host, state):
    """Try the configured host, then a cached last-known IP. Returns
    (data, ip_used) on success or (None, None). Self-heals the cache so the
    watcher never goes silently blind when mDNS resolution flakes out."""
    candidates = []
    ip = resolve_host(host)
    if ip:
        candidates.append(ip)
    elif host not in (state.get("last_ip"),):
        candidates.append(host)  # let urllib try in case it resolves differently
    cached = state.get("last_ip")
    if cached and cached not in candidates:
        candidates.append(cached)

    last_err = None
    for cand in candidates:
        try:
            data = fetch_air_data(cand)
            if cand[0].isdigit():
                state["last_ip"] = cand
            return data, cand
        except Exception as e:  # noqa: BLE001 -- try the next candidate
            last_err = e
    if last_err:
        log(f"fetch failed (tried {candidates}): {last_err}")
    return None, None


CSV_COLS = ["timestamp", "co2", "co2_est", "humid", "temp", "pm25", "voc", "score"]


def append_csv(now, data):
    """Append one reading to the air-log time series (source of truth for the
    daily rollup). Best-effort: a logging failure must never block alerting."""
    def fmt(key, ndigits=None):
        v = data.get(key)
        if v is None:
            return ""
        return round(v, ndigits) if ndigits is not None else v

    row = [
        now.isoformat(timespec="seconds"),
        fmt("co2"), fmt("co2_est"), fmt("humid", 1),
        fmt("temp", 1), fmt("pm25"), fmt("voc"), fmt("score"),
    ]
    try:
        new = not AIR_CSV.exists()
        with AIR_CSV.open("a") as f:
            if new:
                f.write(",".join(CSV_COLS) + "\n")
            f.write(",".join(str(c) for c in row) + "\n")
    except OSError as e:
        log(f"csv append failed: {e}")


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


AWAIR_APP_BUNDLE_ID = "com.alexhedtke.energydashboard"  # Home Climate.app (shows the Awair air data)


def notify(title, message, urgent=False):
    sound = "Basso" if urgent else "Purr"
    label = "Exobrain URGENT" if urgent else "Exobrain"
    full_title = f"{label}: {title}"
    # Post via terminal-notifier so clicking the notification opens Home Climate.
    # Plain `osascript display notification` is owned by Script Editor, so a click
    # opened Script Editor instead. Fall back to osascript if it isn't installed.
    tn = shutil.which("terminal-notifier") or "/opt/homebrew/bin/terminal-notifier"
    try:
        if os.path.exists(tn):
            subprocess.run(
                [tn, "-title", full_title, "-message", message,
                 "-sender", AWAIR_APP_BUNDLE_ID,
                 "-execute", f"open -b {AWAIR_APP_BUNDLE_ID}", "-sound", sound],
                check=False,
            )
            return
    except Exception:
        pass
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{message}" with title "{full_title}" sound name "{sound}"'],
        check=False,
    )


def load_discord_token():
    if not DISCORD_ENV.exists():
        return None
    for line in DISCORD_ENV.read_text().splitlines():
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    return None


def notify_discord(channel_id, message):
    """Send a DM to Alex via the bot. Best-effort: log and return on failure."""
    token = load_discord_token()
    if not token or not channel_id:
        log("discord skip: missing token or DISCORD_NOTIFY_CHAT_ID")
        return
    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    body = json.dumps({"content": message}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://exobrain.local, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            r.read()
    except Exception as e:
        log(f"discord send failed: {e}")


def in_active_hours(now):
    return ACTIVE_HOUR_START <= now.hour < ACTIVE_HOUR_END


def main():
    env = load_env()
    host = env.get("AWAIR_HOST")
    if not host:
        log("AWAIR_HOST not set in .env; exiting")
        sys.exit(0)

    now = datetime.now()

    state = load_state()
    prev_ip = state.get("last_ip")
    data, _ = fetch_with_fallback(host, state)
    if state.get("last_ip") != prev_ip:
        save_state(state)
    if data is None:
        return  # fetch_with_fallback already logged the failure

    co2 = data.get("co2")
    if co2 is None:
        log(f"no co2 in response: {data}")
        return

    # Log every reading, around the clock -- overnight bedroom air is the data we
    # most want. Alerts, below, still respect active hours so we don't wake Alex.
    append_csv(now, data)

    if not in_active_hours(now):
        return

    tier = None
    if co2 >= CO2_URGENT:
        tier = "urgent"
    elif co2 >= CO2_WARN:
        tier = "warn"

    if tier is None:
        return

    last_iso = state.get(f"last_{tier}")
    if last_iso:
        last = datetime.fromisoformat(last_iso)
        if (now - last).total_seconds() < HYSTERESIS_MIN * 60:
            return

    score = data.get("score", "?")
    pm25 = data.get("pm25", "?")
    msg = f"CO2 {co2} ppm (score {score}, PM2.5 {pm25}) -- open a window"
    notify("Air quality", msg, urgent=(tier == "urgent"))

    emoji = "🚨" if tier == "urgent" else "🌬️"
    notify_discord(env.get("DISCORD_NOTIFY_CHAT_ID"), f"{emoji} **Air quality** -- {msg}")
    log(f"notified {tier}: co2={co2} score={score} pm25={pm25}")

    state[f"last_{tier}"] = now.isoformat(timespec="seconds")
    save_state(state)


if __name__ == "__main__":
    main()
