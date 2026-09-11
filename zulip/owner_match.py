"""Match minted bots to the friends they were minted for.

A bot minted by the admin is named "<First>'s Claude" and stays owned by the
admin until its person joins the org. This module decides which of those bots
can be handed over: the bot's first name must match exactly one active human
member's first name (case-insensitive), and that human must not be the admin.

INVARIANTS:
- Only active bots owned by the admin are considered.
- Ambiguous cases (two humans, or two bots, sharing a first name) are never
  transferred; they are reported instead.
- A bot whose person has not joined yet is "pending", never an error.
"""

from __future__ import annotations

import re

BOT_NAME = re.compile(r"^(?P<first>.+?)'s Claude$", re.IGNORECASE)


def first_name(full_name: str) -> str:
    parts = full_name.strip().split()
    return parts[0] if parts else ""


def bot_first(bot: dict) -> str | None:
    m = BOT_NAME.match(bot.get("full_name", "").strip())
    return m.group("first").strip().lower() if m else None


def plan_transfers(members: list[dict], admin_id: int) -> tuple[list[tuple[dict, dict]], list[dict], list[tuple[dict, list[dict]]]]:
    """Return (transfers, pending, ambiguous).

    transfers: (bot, human) pairs safe to hand over.
    pending: minted bots whose person has not joined.
    ambiguous: (bot, candidate humans) where the first name is not unique.
    """
    bots = [m for m in members if m.get("is_bot") and m.get("bot_owner_id") == admin_id
            and m.get("is_active", True) and bot_first(m)]
    humans = [m for m in members if not m.get("is_bot") and m.get("is_active", True)
              and m["user_id"] != admin_id]
    humans_by_first: dict[str, list[dict]] = {}
    for h in humans:
        humans_by_first.setdefault(first_name(h["full_name"]).lower(), []).append(h)
    bots_by_first: dict[str, list[dict]] = {}
    for b in bots:
        bots_by_first.setdefault(bot_first(b) or "", []).append(b)
    transfers, pending, ambiguous = [], [], []
    for b in bots:
        key = bot_first(b) or ""
        matches = humans_by_first.get(key, [])
        if not matches:
            pending.append(b)
        elif len(matches) == 1 and len(bots_by_first[key]) == 1:
            transfers.append((b, matches[0]))
        else:
            ambiguous.append((b, matches))
    return transfers, pending, ambiguous
