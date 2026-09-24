#!/opt/homebrew/bin/python3
"""The running quest's Mac-side loop: verify, celebrate, nudge.

Runs every 30 minutes under launchd (``com.exobrain.quest-watch``):

1. ``exercise-log/bin/quest-verify --json`` matches the phone's quest
   attempts against Fitbit's activity log and writes verifications and free
   runs into ``exercise-log.json``.
2. Every event it reports becomes a banner (``mist-notify``) and a Discord
   post: verifications and free runs to Alex's own channel, level-ups and
   finished chapters to ``QUEST_DISCORD_CHANNEL`` (the friends' channel once
   he points it there; his own until then).
3. A finished chapter moves ``QUEST_LOOT_DOLLARS`` into envelope
   ``QUEST_LOOT_ENVELOPE_ID`` in the Envelope Budget app. Off unless both are
   set in the harness ``.env``.
4. If a quest is due today and the next two hours look runnable, one "go
   now" nudge per day goes out as a banner and a Discord DM.

State (last nudge date, last events) lives in ``.state.json`` next to this
file, gitignored. Log: ``~/Library/Logs/exobrain/quest-watch.log``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent
HOME = Path.home()
EXERCISE_LOG = HOME / "Documents/exercise-log"
VERIFY = EXERCISE_LOG / "bin/quest-verify"
NOTIFY = HARNESS / "mist-voice/bin/mist-notify"
DISCORD_SEND = HARNESS / "discord/discord-send.py"
STATE = HERE / ".state.json"
LOG = HOME / "Library/Logs/exobrain/quest-watch.log"
ENV = HARNESS / ".env"
BUDGET_MOVE = "https://127.0.0.1:5010/api/move"

# Kansas City. A runnable window: not freezing, not a heat advisory, dry, calm.
LAT, LON = 39.10, -94.58
GOOD_TEMP = (35, 85)
MAX_PRECIP_PROB = 30
MAX_WIND = 20
NUDGE_HOURS = range(7, 20)

sys.path.insert(0, str(EXERCISE_LOG / "lib"))
try:
    import quest as q
except ImportError:  # the repo moved; say so instead of a traceback
    q = None


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")


def env() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    out.update({k: v for k, v in os.environ.items() if k.startswith("QUEST_") or k.startswith("DISCORD_")})
    return out


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=1) + "\n")


def notify(msg: str, title: str = "Running quest", link: str = "console!", *extra: str) -> None:
    if NOTIFY.exists():
        subprocess.run([str(NOTIFY), msg, title, "Purr", link, *extra], check=False, capture_output=True)


def discord(channel: str | None, msg: str) -> None:
    if channel and DISCORD_SEND.exists():
        r = subprocess.run([sys.executable, str(DISCORD_SEND), channel, msg], capture_output=True, text=True)
        if r.returncode != 0:
            log(f"discord send failed: {r.stderr.strip()[:200]}")


# MARK: verify

def run_verify() -> dict | None:
    if not VERIFY.exists():
        log(f"quest-verify missing at {VERIFY}")
        return None
    r = subprocess.run([sys.executable, str(VERIFY), "--json", "--days", "14"], capture_output=True, text=True)
    if r.returncode != 0:
        log(f"verify exit {r.returncode}: {r.stderr.strip()[:300]}")
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        log(f"verify printed non-JSON: {r.stdout[:200]}")
        return None


def celebrate(result: dict, cfg: dict) -> None:
    own = cfg.get("DISCORD_NOTIFY_CHAT_ID")
    public = cfg.get("QUEST_DISCORD_CHANNEL") or own
    for ev in result.get("events", []):
        a = ev.get("activity", {})
        km = f"{a.get('distanceKm', 0):.2f} km" if a else ""
        mins = f"{a.get('durationSeconds', 0) // 60} min" if a else ""
        hr = f", {a['averageHeartRate']} bpm" if a.get("averageHeartRate") else ""
        if ev["type"] == "verified":
            text = f"Week {ev['week']} day {ev['day']} verified by Fitbit: {a['activityName']}, {mins}, {km}{hr}. +{ev['xp']:,} xp."
            notify(text)
            discord(own, f"(◠‿O) {text}")
        elif ev["type"] == "free_run":
            text = f"Free run found on Fitbit: {a['activityName']} on {a['startTime'][:10]}, {mins}, {km}{hr}. +{ev['xp']:,} xp."
            notify(text)
            discord(own, f"(o.o) {text}")
        elif ev["type"] == "level_up":
            text = f"Agility level {ev['to']}. ({ev['xp']:,} xp)"
            notify(text, "Level up")
            discord(public, f"(>‿<) Alex reached Agility level {ev['to']}. {ev['xp']:,} xp and counting.")
        elif ev["type"] == "chapter_done":
            text = f"Chapter {ev['week']} complete: {ev['title']}."
            notify(text, "Chapter complete")
            discord(public, f"(ᵔwᵔ) {text} Alex finished week {ev['week']} of Couch to 5K.")
            loot(ev, cfg)
        log(f"event: {json.dumps(ev)[:300]}")


def loot(ev: dict, cfg: dict) -> None:
    env_id, dollars = cfg.get("QUEST_LOOT_ENVELOPE_ID"), cfg.get("QUEST_LOOT_DOLLARS")
    if not env_id or not dollars:
        return
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # local self-signed cert on :5010
    body = json.dumps({"from": "rta", "to": int(env_id), "amount": float(dollars)}).encode()
    req = urllib.request.Request(BUDGET_MOVE, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            resp.read()
        text = f"Loot: ${float(dollars):.2f} moved to the loot envelope for chapter {ev['week']}."
        notify(text, "Loot", "https://127.0.0.1:5010/")
        log(text)
    except Exception as e:  # noqa: BLE001 - a budget hiccup must not kill the watcher
        log(f"loot move failed: {e}")


# MARK: nudge

def weather_window(hours: int = 2) -> tuple[bool, str]:
    url = ("https://api.open-meteo.com/v1/forecast?" + f"latitude={LAT}&longitude={LON}"
           "&hourly=apparent_temperature,precipitation_probability,wind_speed_10m,is_day"
           f"&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America%2FChicago&forecast_hours={hours + 1}")
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            h = json.load(resp)["hourly"]
    except Exception as e:  # noqa: BLE001
        return False, f"weather unavailable: {e}"
    rows = list(zip(h["apparent_temperature"], h["precipitation_probability"], h["wind_speed_10m"], h["is_day"], strict=True))[:hours]
    if not rows:
        return False, "no forecast rows"
    temps = [r[0] for r in rows]
    if not all(GOOD_TEMP[0] <= t <= GOOD_TEMP[1] for t in temps):
        return False, f"feels like {min(temps):.0f} to {max(temps):.0f}F"
    if any(r[1] > MAX_PRECIP_PROB for r in rows):
        return False, f"rain chance {max(r[1] for r in rows)}%"
    if any(r[2] > MAX_WIND for r in rows):
        return False, f"wind {max(r[2] for r in rows):.0f} mph"
    if not any(r[3] for r in rows):
        return False, "dark"
    return True, f"feels like {temps[0]:.0f}F, {max(r[1] for r in rows)}% rain, {max(r[2] for r in rows):.0f} mph wind"


def quest_due(summary: dict, quest: dict, now: datetime) -> tuple[bool, str]:
    if summary.get("next") is None:
        return False, "plan complete"
    if summary.get("completedThisWeek", 0) >= (q.DAYS_PER_WEEK if q else 3):
        return False, "week's quests done"
    today = now.astimezone().date()
    for s in quest.get("sessions", []):
        started = q.parse_ts(s["startedAt"]).astimezone().date() if q else today
        if started == today and (s.get("week") is not None):
            return False, "already ran today"
        if started == today - timedelta(days=1) and s.get("completed") and s.get("week") is not None:
            return False, "rest day after yesterday's quest"
    return True, "due"


def nudge(result: dict, cfg: dict, state: dict) -> None:
    now = datetime.now(timezone.utc)
    local = now.astimezone()
    if local.hour not in NUDGE_HOURS:
        return
    if state.get("last_nudge") == local.strftime("%Y-%m-%d"):
        return
    try:
        data = json.loads(Path(result["file"]).read_text())
    except (KeyError, OSError, json.JSONDecodeError):
        return
    quest = data.get("quest") or {}
    due, why = quest_due(result.get("summary", {}), quest, now)
    if not due:
        log(f"nudge skipped: {why}")
        return
    ok, wx = weather_window()
    if not ok:
        log(f"nudge held: {wx}")
        return
    nxt = result["summary"]["next"]
    text = (f"Good running window for the next two hours ({wx}). Next quest: week {nxt['week']} day {nxt['day']}, "
            f"{nxt['title']}, {nxt['totalSeconds'] // 60} min with {nxt['jogSeconds'] // 60} min of jogging.")
    notify(text, "Go now", "console!")
    discord(cfg.get("DISCORD_NOTIFY_CHAT_ID"), f"(ᵔwᵔ) {text} Open Exercise Log, Quest tab, Start quest, and start a Run on the watch.")
    state["last_nudge"] = local.strftime("%Y-%m-%d")
    log(f"nudged: {wx}")


def main() -> None:
    cfg = env()
    state = load_state()
    result = run_verify()
    if result is None:
        save_state(state)
        return
    s = result.get("summary", {})
    log(f"verify ok: level {s.get('level')} {s.get('xp')} xp, {len(result.get('events', []))} event(s), changed={result.get('changed')}")
    celebrate(result, cfg)
    nudge(result, cfg, state)
    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)


if __name__ == "__main__":
    main()
