"""MIST's Zulip listener: zulipmcp's listener plus catch-up after sleep.

zulipmcp.listener only sees @mentions that arrive while it is connected. When
the Mac sleeps, the event queue dies and mentions posted in the gap are never
delivered, so nobody answers them. This wrapper, on every start, looks back for
mentions MIST has not answered and spawns a session for each, then hands off to
the stock listener. Same command line as ``python -m zulipmcp.listener``.

INVARIANTS:
- A mention is "answered" only if MIST posted in that topic after it.
- Catch-up never spawns twice for one topic: one session per (stream, topic).
- The last seen mention id is persisted so a restart does not re-answer.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import zulip
from zulipmcp import listener as stock

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


def _spawn_and_remember(cfg: stock.Config, msg: dict) -> None:
    _remember(msg["id"])
    _orig_spawn(cfg, msg)


_orig_run = stock.run


def _run_with_catch_up(cfg: stock.Config) -> None:
    try:
        catch_up(cfg)
    except Exception as exc:  # noqa: BLE001 - catch-up must never block the live listener
        _log(f"failed: {exc}")
    _orig_run(cfg)


stock._spawn = _spawn_and_remember  # noqa: SLF001
stock.run = _run_with_catch_up

if __name__ == "__main__":
    stock.main()
