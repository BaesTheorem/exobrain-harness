"""Staged reply: one message Alex pre-arranges, posted verbatim on his next cue.

The chatter module hands MIST a fresh, sandboxed CLI for every shared-server
turn, so a line agreed in a Console chat ("when I tag you under that comment,
say X") never reaches her. This store closes that gap deterministically: Alex
stages the exact text (through `bin/discord-stage` or from a Console session),
and the next time he addresses her in a server (an @mention or a reply to
her), the bot posts the text as-is and consumes the entry. No model runs, so
the wording is exactly what he approved.

One entry at a time, in a gitignored file outside the repo
(~/.claude/channels/discord/staged-reply.json), so the text never lands in
version control. An optional guild or channel filter keeps it from firing in
the wrong room, and a TTL stops a forgotten entry from surfacing days later.

The second store here is the standing per-person append: a line MIST adds
to the end of every reply she makes to a given Discord user (keyed by the
login username, which Discord keeps unique, never by display name). Alex
sets it through `bin/discord-append`; it lives in
~/.claude/channels/discord/appends.json, outside the repo, because a
username next to a message is a name-to-identity mapping.

INVARIANTS (do not break these in an edit):
  - Only the owner's own cue consumes a staged entry; a guest can never
    trigger it (chatter.py checks the owner gate before calling take()).
  - take() is the only path that deletes on a match. A miss (wrong room,
    expired) leaves the entry alone, except that an expired entry is dropped.
  - The files are the only state: nothing survives in memory across a restart.
  - Appends key on the username, never on a display name or nick.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

STORE = Path.home() / ".claude" / "channels" / "discord" / "staged-reply.json"
APPENDS = Path.home() / ".claude" / "channels" / "discord" / "appends.json"
DEFAULT_TTL_HOURS = 24.0


# ---- standing per-person appends -------------------------------------------

def _load_appends(store: Path) -> dict[str, str]:
    if not store.exists():
        return {}
    try:
        data = json.loads(store.read_text())
    except (OSError, ValueError):
        return {}
    return {str(k).lower(): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def set_append(username: str, text: str, *, store: Path = APPENDS) -> None:
    """Add or replace the line appended to every reply to `username`."""
    username = username.strip().lstrip("@").lower()
    text = text.strip()
    if not username or not text:
        raise ValueError("username and text are both required")
    data = _load_appends(store)
    data[username] = text
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def remove_append(username: str, *, store: Path = APPENDS) -> bool:
    """Drop the append for `username`. True when there was one."""
    data = _load_appends(store)
    if data.pop(username.strip().lstrip("@").lower(), None) is None:
        return False
    store.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True


def list_appends(*, store: Path = APPENDS) -> dict[str, str]:
    return _load_appends(store)


def append_for(username: str | None, *, store: Path = APPENDS) -> str | None:
    """The line to add to a reply aimed at `username`, or None."""
    if not username:
        return None
    return _load_appends(store).get(username.lower())


def with_append(reply: str, username: str | None, *, store: Path = APPENDS) -> str:
    """`reply` with the person's line on its own last line, when one is set."""
    line = append_for(username, store=store)
    if not line:
        return reply
    reply = reply.rstrip()
    return f"{reply}\n{line}" if reply else line


def stage(text: str, *, guild: str | None = None, channel: str | None = None,
          ttl_hours: float = DEFAULT_TTL_HOURS, store: Path = STORE) -> dict:
    """Write one staged entry, replacing any existing one. Returns the entry."""
    text = text.strip()
    if not text:
        raise ValueError("staged text is empty")
    entry = {
        "text": text,
        "guild": (guild or "").strip() or None,
        "channel": (channel or "").strip().lstrip("#") or None,
        "staged_at": time.time(),
        "expires_at": time.time() + ttl_hours * 3600,
    }
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(entry, indent=2) + "\n")
    return entry


def peek(store: Path = STORE) -> dict | None:
    """The current entry, or None when there is none or it has expired."""
    if not store.exists():
        return None
    try:
        entry = json.loads(store.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or not entry.get("text"):
        return None
    if time.time() > float(entry.get("expires_at", 0)):
        clear(store)
        return None
    return entry


def clear(store: Path = STORE) -> bool:
    """Remove the entry. True when there was one."""
    if store.exists():
        store.unlink()
        return True
    return False


def _matches(wanted: str | None, actual: str | None) -> bool:
    if not wanted:
        return True
    return wanted.lower() in (actual or "").lower()


def take(*, guild: str | None, channel: str | None, store: Path = STORE) -> str | None:
    """Consume the entry if it applies to this room. Returns the text or None.

    `guild` and `channel` are the names of the room the cue arrived in. An
    entry with no filter applies anywhere; a filter is a case-insensitive
    substring match on the name."""
    entry = peek(store)
    if entry is None:
        return None
    if not _matches(entry.get("guild"), guild) or not _matches(entry.get("channel"), channel):
        return None
    clear(store)
    return str(entry["text"])
