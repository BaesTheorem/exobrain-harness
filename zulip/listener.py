"""MIST's Zulip listener: zulipmcp's listener plus catch-up after sleep.

zulipmcp.listener only sees @mentions that arrive while it is connected. When
the Mac sleeps, the event queue dies and mentions posted in the gap are never
delivered, so nobody answers them. This wrapper, on every start, looks back for
mentions MIST has not answered and spawns a session for each, then hands off to
the stock listener. Same command line as ``python -m zulipmcp.listener``.

It also gates every spawn through ``usage_ledger``: per-sender and org-wide
limits from ``limits.json``, so a friend cannot use MIST as a free assistant or
burn Alex's tokens for fun. A blocked mention gets a canned reply through the
Zulip API (no tokens) and Alex gets one ``[audit]`` DM per sender per hour.

INVARIANTS:
- A mention is "answered" only if MIST posted in that topic after it.
- Catch-up never spawns twice for one topic: one session per (stream, topic).
- The last seen mention id is persisted so a restart does not re-answer.
- Exempt users (Alex) are never blocked; blocked mentions never spawn.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import zulip
from zulipmcp import listener as stock

import usage_ledger as ledger

STATE = Path.home() / ".claude" / "channels" / "zulip" / "last_seen_id"
LOOKBACK_S = 3 * 24 * 3600


def _last_seen() -> int | None:
    try:
        return int(STATE.read_text().strip())
    except (OSError, ValueError):
        return None


def _remember(msg_id: int) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if msg_id > (_last_seen() or 0):
        STATE.write_text(str(msg_id))


def _log(text: str) -> None:
    print(f"[catch-up] {text}", file=sys.stderr, flush=True)


def catch_up(cfg: stock.Config) -> None:
    """Spawn a session for every unanswered mention since the last seen id."""
    client = zulip.Client(config_file=str(cfg.zuliprc))
    me = client.get_profile()["user_id"]
    res = client.get_messages({
        "anchor": "newest", "num_before": 200, "num_after": 0, "apply_markdown": False,
        "narrow": [{"operator": "is", "operand": "mentioned"}],
    })
    if res.get("result") != "success":
        _log(f"could not fetch mentions: {res.get('msg')}")
        return
    last = _last_seen()
    cutoff = time.time() - LOOKBACK_S
    newest_per_topic: dict[tuple[str, str], dict] = {}
    for m in res["messages"]:
        if m.get("type") != "stream" or m["sender_id"] == me:
            continue
        if (last is not None and m["id"] <= last) or m["timestamp"] < cutoff:
            continue
        key = (m["display_recipient"].lower(), m["subject"].lower())
        if key not in newest_per_topic or m["id"] > newest_per_topic[key]["id"]:
            newest_per_topic[key] = m
    for m in newest_per_topic.values():
        after = client.get_messages({
            "anchor": m["id"], "num_before": 0, "num_after": 50, "apply_markdown": False,
            "narrow": [{"operator": "stream", "operand": m["display_recipient"]},
                       {"operator": "topic", "operand": m["subject"]}],
        })
        answered = any(x["sender_id"] == me and x["id"] > m["id"] for x in after.get("messages", []))
        if answered:
            continue
        _log(f"unanswered mention in #{m['display_recipient']} > {m['subject']} (id {m['id']}), spawning")
        try:
            client.add_reaction({"message_id": m["id"], "emoji_name": "eyes"})
        except Exception:  # noqa: BLE001 - the reaction is cosmetic
            pass
        stock._spawn(cfg, m)  # noqa: SLF001 - the stock listener keeps its spawner private
    if res["messages"]:
        _remember(max(x["id"] for x in res["messages"]))


_orig_spawn = stock._spawn  # noqa: SLF001
_client: zulip.Client | None = None
_blocked_notified: dict[int, float] = {}


def _zulip_client(cfg: stock.Config) -> zulip.Client:
    global _client
    if _client is None:
        _client = zulip.Client(config_file=str(cfg.zuliprc))
    return _client


def _block(cfg: stock.Config, msg: dict, reason: str, limits: dict) -> None:
    where = f"#{msg['display_recipient']} > {msg['subject']}"
    who = msg.get("sender_full_name", "?")
    _log(f"blocked {who} in {where}: {reason}")
    client = _zulip_client(cfg)
    client.send_message({"type": "stream", "to": msg["display_recipient"], "topic": msg["subject"],
                         "content": ledger.block_message(reason)})
    owner = limits.get("owner_user_id")
    now = time.time()
    if owner and now - _blocked_notified.get(msg["sender_id"], 0) > 3600:
        client.send_message({"type": "private", "to": [owner],
                             "content": f"[audit] rate limit: {who} blocked in {where} ({reason})"})
        _blocked_notified[msg["sender_id"]] = now


def _spawn_gated(cfg: stock.Config, msg: dict) -> None:
    """Rate-limit, remember, spawn, and record the new session's transcript path."""
    limits = ledger.load_limits()
    ok, reason = ledger.check(msg["sender_id"], ledger.read_spawns(), time.time(), limits)
    if not ok:
        _block(cfg, msg, reason, limits)
        return
    _remember(msg["id"])
    before = set(cfg.log_dir.glob("*.jsonl")) if cfg.log_dir.exists() else set()
    _orig_spawn(cfg, msg)
    fresh = [p for p in cfg.log_dir.glob("*.jsonl") if p not in before]
    if not fresh:
        return  # an existing session for this topic will pick the message up via listen()
    log = max(fresh, key=lambda p: p.stat().st_mtime)
    ledger.record_spawn(msg["sender_id"], msg.get("sender_full_name", "?"),
                        msg["display_recipient"], msg["subject"], str(log))


_orig_run = stock.run


def _run_with_catch_up(cfg: stock.Config) -> None:
    try:
        catch_up(cfg)
    except Exception as exc:  # noqa: BLE001 - catch-up must never block the live listener
        _log(f"failed: {exc}")
    _orig_run(cfg)


stock._spawn = _spawn_gated  # noqa: SLF001
stock.run = _run_with_catch_up

if __name__ == "__main__":
    stock.main()
