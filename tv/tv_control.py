"""
Samsung Tizen TV control wrapper.

Pairing: first WebSocket connection triggers an on-screen approval prompt on
the TV. Approve it once, and the auth token persists in tv/token.json for all
future calls.

Power: TV cannot be turned ON via the WebSocket (it's offline). Use Wake-on-LAN
with TV_MAC from .env. The MAC must be reachable via L2 broadcast on the LAN.
"""

import json
import os
import socket
import sys
from pathlib import Path

from samsungtvws import SamsungTVWS
from wakeonlan import send_magic_packet
import urllib.request

HARNESS_DIR = Path(__file__).resolve().parent.parent
TOKEN_FILE = Path(__file__).resolve().parent / "token.json"

APP_IDS = {
    "netflix": "3201907018807",
    "youtube": "111299001912",
    "prime": "3201910019365",
    "primevideo": "3201910019365",
    "plex": "3201512006963",
    "disney": "3201901017640",
    "disneyplus": "3201901017640",
    "hulu": "3201601007625",
    "hbomax": "3201601007230",
    "max": "3201601007230",
    "spotify": "3201606009684",
    "apple": "3201807016597",
    "appletv": "3201807016597",
}


def load_env():
    env = {}
    env_path = HARNESS_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def _connect():
    env = load_env()
    host = env.get("TV_HOST")
    if not host:
        raise RuntimeError("TV_HOST not set in .env")
    return SamsungTVWS(
        host=host,
        port=8002,
        token_file=str(TOKEN_FILE),
        name="Claude Code",
        timeout=10,
    )


def rest_info():
    """Hit the unauthenticated REST endpoint — works whether TV is paired or not."""
    env = load_env()
    host = env.get("TV_HOST")
    url = f"http://{host}:8001/api/v2/"
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, socket.timeout, ConnectionRefusedError):
        return None


def is_on():
    """True if the TV is reachable on its control port — i.e., powered on."""
    return rest_info() is not None


def status():
    info = rest_info()
    if info is None:
        return {"power": "off", "reachable": False}
    dev = info.get("device", {})
    return {
        "power": dev.get("PowerState", "unknown"),
        "reachable": True,
        "name": dev.get("name"),
        "model": dev.get("modelName"),
        "resolution": dev.get("resolution"),
    }


def send_key(key):
    """Send a remote key (e.g. KEY_PAUSE, KEY_VOLUP)."""
    tv = _connect()
    tv.send_key(key)


def power_off():
    send_key("KEY_POWER")


def wake():
    """Wake-on-LAN. Works only if Network Standby is enabled on the TV."""
    env = load_env()
    mac = env.get("TV_MAC")
    if not mac:
        raise RuntimeError("TV_MAC not set in .env")
    send_magic_packet(mac)


def launch_app(name_or_id):
    """Launch an app by friendly name (netflix/youtube/plex/etc.) or raw app ID."""
    app_id = APP_IDS.get(name_or_id.lower(), name_or_id)
    tv = _connect()
    tv.rest_app_run(app_id)


def pair():
    """Triggers the on-screen approval prompt. User must Allow on the TV."""
    print("Connecting to TV — APPROVE the prompt on the TV screen now...", flush=True)
    tv = _connect()
    info = tv.rest_device_info()
    print(f"Paired. Token saved to {TOKEN_FILE}")
    print(f"Device: {info.get('device', {}).get('name')}")
    return info


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "pair":
        pair()
    else:
        print(json.dumps(status(), indent=2))
