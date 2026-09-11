"""Usage ledger and abuse limits for MIST's Zulip listener.

Every spawned session is recorded with who triggered it and where its
transcript went, so the listener can refuse the next spawn when a sender or
the whole org is over budget, and ``zulip-admin usage`` can show who used
what. Cost is the CLI's list-price estimate per session (``total_cost_usd`` in
the stream-json result), which is a fair proxy for tokens on a subscription.

INVARIANTS:
- Exempt users (Alex) are never blocked.
- A blocked mention costs no tokens: the decision happens before any spawn.
- Limits are read from limits.json on every decision, so edits apply live.
- A session without a result line yet (still running, or killed) counts as
  ``est_cost_per_session`` so a burst of unfinished sessions still adds up.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

STATE_DIR = Path.home() / ".claude" / "channels" / "zulip"
SPAWNS_PATH = STATE_DIR / "spawns.jsonl"
LIMITS_PATH = Path(__file__).with_name("limits.json")
TZ = ZoneInfo("America/Chicago")
DEFAULT_LIMITS: dict[str, object] = {
    "owner_user_id": None,
    "exempt_user_ids": [],
    "per_sender_per_hour": 4,
    "per_sender_per_day": 12,
    "per_sender_usd_per_day": 3.0,
    "global_usd_per_day": 15.0,
    "est_cost_per_session": 0.75,
}


def load_limits(path: Path = LIMITS_PATH) -> dict:
    limits = dict(DEFAULT_LIMITS)
    try:
        limits.update(json.loads(path.read_text()))
    except (OSError, ValueError):
        pass
    return limits


def record_spawn(sender_id: int, sender_name: str, stream: str, topic: str,
                 log_path: str | None, path: Path = SPAWNS_PATH, now: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": now if now is not None else time.time(), "sender_id": sender_id,
           "sender_name": sender_name, "stream": stream, "topic": topic, "log": log_path}
    with path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def read_spawns(path: Path = SPAWNS_PATH) -> list[dict]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def session_cost(log_path: str | None) -> float | None:
    """List-price cost from the session's stream-json result line, or None if absent."""
    if not log_path:
        return None
    try:
        lines = Path(log_path).read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"type":"result"' not in line and '"type": "result"' not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") != "result":
            continue
        if isinstance(row.get("total_cost_usd"), (int, float)):
            return float(row["total_cost_usd"])
        models = row.get("modelUsage") or {}
        entries = [m for m in models.values() if isinstance(m, dict)]
        costs: list[float] = [float(m["costUSD"]) for m in entries if isinstance(m.get("costUSD"), (int, float))]
        if entries and len(costs) == len(entries):
            return sum(costs)
        return None
    return None


def day_start(now: float) -> float:
    local = datetime.fromtimestamp(now, TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def usage(spawns: list[dict], now: float, limits: dict) -> dict:
    """Today's sessions and cost per sender, plus the org-wide total."""
    est = float(limits["est_cost_per_session"])
    since_day, since_hour = day_start(now), now - 3600
    senders: dict[int, dict] = {}
    total = 0.0
    for s in spawns:
        if s["ts"] < since_day:
            continue
        cost = session_cost(s.get("log"))
        cost = est if cost is None else cost
        entry = senders.setdefault(s["sender_id"], {"name": s.get("sender_name", "?"), "hour": 0, "day": 0, "usd_day": 0.0})
        entry["day"] += 1
        entry["usd_day"] += cost
        if s["ts"] >= since_hour:
            entry["hour"] += 1
        total += cost
    return {"senders": senders, "global_usd_day": total}


def check(sender_id: int, spawns: list[dict], now: float, limits: dict) -> tuple[bool, str]:
    """Decide whether a mention from sender_id may spawn a session."""
    if sender_id in (limits.get("exempt_user_ids") or []):
        return True, "exempt"
    u = usage(spawns, now, limits)
    s = u["senders"].get(sender_id, {"hour": 0, "day": 0, "usd_day": 0.0})
    if s["hour"] >= int(limits["per_sender_per_hour"]):
        return False, f"{s['hour']} sessions in the last hour (limit {limits['per_sender_per_hour']})"
    if s["day"] >= int(limits["per_sender_per_day"]):
        return False, f"{s['day']} sessions today (limit {limits['per_sender_per_day']})"
    if s["usd_day"] >= float(limits["per_sender_usd_per_day"]):
        return False, f"${s['usd_day']:.2f} of Alex's budget today (limit ${float(limits['per_sender_usd_per_day']):.2f})"
    if u["global_usd_day"] >= float(limits["global_usd_per_day"]):
        return False, f"the org has used ${u['global_usd_day']:.2f} today (limit ${float(limits['global_usd_per_day']):.2f})"
    return True, "ok"


def block_message(reason: str) -> str:
    return (f"I'm rate-limited right now: {reason}. I'm here to coordinate with Alex, "
            "not as a general assistant, so your own Claude is the place for the rest. "
            "Alex can raise the limit if this was a real need.")


def summarize(spawns: list[dict], now: float, limits: dict, days: int = 7) -> str:
    """Human-readable usage for today and the last `days` days."""
    est = float(limits["est_cost_per_session"])
    today = usage(spawns, now, limits)
    lines = [f"today (since {datetime.fromtimestamp(day_start(now), TZ):%Y-%m-%d %H:%M}): "
             f"{sum(v['day'] for v in today['senders'].values())} sessions, ${today['global_usd_day']:.2f} list price"]
    for v in sorted(today["senders"].values(), key=lambda e: -e["usd_day"]):
        lines.append(f"  {v['name']:<24} {v['day']:>3} sessions  ${v['usd_day']:.2f}")
    since = now - days * 86400
    window: dict[int, dict] = {}
    for s in spawns:
        if s["ts"] < since:
            continue
        cost = session_cost(s.get("log"))
        cost = est if cost is None else cost
        e = window.setdefault(s["sender_id"], {"name": s.get("sender_name", "?"), "n": 0, "usd": 0.0})
        e["n"] += 1
        e["usd"] += cost
    lines.append(f"last {days} days: {sum(e['n'] for e in window.values())} sessions, "
                 f"${sum(e['usd'] for e in window.values()):.2f}")
    for e in sorted(window.values(), key=lambda e: -e["usd"]):
        lines.append(f"  {e['name']:<24} {e['n']:>3} sessions  ${e['usd']:.2f}")
    cutoff = datetime.fromtimestamp(now, TZ) - timedelta(days=days)
    lines.append(f"(window from {cutoff:%Y-%m-%d}; limits: {limits['per_sender_per_hour']}/h, "
                 f"{limits['per_sender_per_day']}/day, ${float(limits['per_sender_usd_per_day']):.2f}/sender/day, "
                 f"${float(limits['global_usd_per_day']):.2f}/org/day)")
    return "\n".join(lines)
