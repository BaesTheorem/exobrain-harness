"""Pure logic for the `use_threads` preference (Fletcher's thread auto-join).

Kept free of discord.py so the tests can load it without a gateway. The
module in modules/threads.py wires these onto real guilds and threads.

A `use_threads` value is one of:
  * a bool-like  -> every public thread in the guild (True) or none (False)
  * a target list -> only threads whose parent channel id, category id, or
    category name (case-insensitive) is listed. Tokens may be raw ids,
    `<#id>` mentions, `#names`, or bare names, separated by commas or spaces.
"""

from __future__ import annotations

import re
from difflib import get_close_matches

TRUE_WORDS = {"true", "yes", "on", "1", "all", "always"}
FALSE_WORDS = {"false", "no", "off", "0", "none", "never"}
DELETE_WORD = "null"
MAX_VALUE = 4096
SECRET_WORDS = ("secret", "password", "token")

_MENTION_RE = re.compile(r"^<#(\d+)>$")
_USER_MENTION_RE = re.compile(r"^<@!?(\d+)>$")
_SPLIT_RE = re.compile(r"[,\s]+")


def normalize(value: str) -> bool | list[str]:
    """Bool-like words collapse to a bool; anything else is a target list."""
    text = value.strip()
    if text.lower() in TRUE_WORDS:
        return True
    if text.lower() in FALSE_WORDS:
        return False
    targets: list[str] = []
    for tok in _SPLIT_RE.split(text):
        if not tok:
            continue
        m = _MENTION_RE.match(tok)
        if m:
            targets.append(m.group(1))
            continue
        targets.append(tok.lstrip("#"))
    return targets


def unknown_targets(targets: list[str], channel_ids: set[int], category_ids: set[int],
                    category_names: dict[str, str]) -> list[str]:
    """Targets that match no known channel id, category id, or category name.
    category_names maps lowercased name -> display name."""
    unknown = []
    for t in targets:
        if t.isdigit() and (int(t) in channel_ids or int(t) in category_ids):
            continue
        if t.lower() in category_names:
            continue
        unknown.append(t)
    return unknown


def matches(value: bool | list[str], parent_id: int, category_id: int | None,
            category_name: str | None) -> bool:
    """Does this user's use_threads value cover a thread under parent_id?"""
    if isinstance(value, bool):
        return value
    lowered = (category_name or "").lower()
    for t in value:
        if t.isdigit():
            n = int(t)
            if n == parent_id or (category_id is not None and n == category_id):
                return True
        elif lowered and t.lower() == lowered:
            return True
    return False


def validation_message(unknown: list[str], category_names: dict[str, str],
                       guild_name: str) -> str:
    """Fletcher's 'did you mean' reply for a bad use_threads value."""
    parts = []
    any_suggestion = False
    for u in unknown:
        close = get_close_matches(u.lower(), list(category_names), n=2, cutoff=0.6)
        if close:
            any_suggestion = True
            shown = ", ".join(f"`{category_names[c]}`" for c in close)
            parts.append(f"`{u}` (did you mean: {shown}?)")
        else:
            parts.append(f"`{u}`")
    msg = "Unknown category/channel: " + "; ".join(parts)
    if not any_suggestion and category_names:
        names = sorted(category_names.values())
        msg += f"\nKnown categories in {guild_name}: " + ", ".join(f"`{n}`" for n in names[:5])
        if len(names) > 5:
            msg += f" ({len(names) - 5} more)"
    msg += "\nYou can also use channel/category IDs, or `true`/`false`."
    return msg


def parse_key(raw: str) -> tuple[int | None, str]:
    """`guild_id:key` -> (guild_id, key); plain `key` -> (None, key)."""
    if ":" in raw:
        head, tail = raw.split(":", 1)
        if head.isdigit() and tail:
            return int(head), tail
    return None, raw


def parse_user_mention(tok: str) -> int | None:
    """`<@id>`, `<@!id>`, or a bare snowflake -> user id, else None."""
    m = _USER_MENTION_RE.match(tok)
    if m:
        return int(m.group(1))
    if tok.isdigit() and len(tok) >= 15:
        return int(tok)
    return None


def is_secret_key(key: str) -> bool:
    k = key.lower()
    return any(w in k for w in SECRET_WORDS)
