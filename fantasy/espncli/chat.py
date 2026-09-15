"""ESPN Fantasy Chat: league chat and per-member direct messages.

Reading lives here. Sending lives in `tx.EspnWriter.chat_send`, because
`bin/espn-tx` is the only command in this tree that POSTs and that boundary is
worth more than the convenience of putting both halves in one file.

Endpoints, verified live 2026-09-14:

    GET  {READS}/.../communication/topics?view=kona_league_communication
    POST {WRITES}/.../communication/topics/{topicId}/messages
         {"author": "{SWID}", "content": str, "topicId": str, "messageTypeId": 0}

INVARIANTS
  - The view is MANDATORY on the read. Without it ESPN returns the correct
    NUMBER of topic objects with every field stripped, so the response looks
    like an empty inbox rather than a rejected request. This cost an hour on
    2026-09-14: an empty result was read as a permissions wall, and the actual
    fault was the query. Anything that fetches topics goes through `fetch`.
  - Content is capped server-side. 560 characters returns HTTP 409
    TOPIC_MAX_LENGTH_CONTENT; 238 posts cleanly. The exact boundary is unknown
    because finding it means sending real messages into a friend's chat, so
    `split_message` chunks conservatively instead of probing for it.
  - Real names are never rendered, per the same rule as the rest of this CLI.
    Authors resolve to their team name, or to owner initials when a SWID owns
    no team.
"""

from __future__ import annotations

import datetime
from typing import Any

from .client import TZ, Espn, initials

VIEW = "kona_league_communication"
TOPICS_PATH = "/communication/topics"

# Threads a human wrote in. The rest of the feed is ESPN's own activity log
# (ACTIVITY_TRANSACTIONS, ACTIVITY_SETTINGS, ACTIVITY_STATUS), which `espn
# activity` already covers in a more useful shape.
CHAT_TYPES = frozenset({"CHAT", "CHAT_DIRECT_MESSAGE", "CHAT_ALL_MEMBERS"})

# Well under the server cap. See INVARIANTS.
MAX_CONTENT = 240


def split_message(text: str, limit: int = MAX_CONTENT) -> list[str]:
    """Break text into chunks at or under `limit`, preferring clean seams.

    Paragraph breaks first, then sentence ends, then whitespace, and only then
    a hard cut. A hard cut is always available as the last resort so this
    terminates on pathological input (one very long unbroken token).
    """
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = -1
        for seam in ("\n\n", ". ", "! ", "? ", "\n", " "):
            cut = window.rfind(seam)
            if cut > limit // 3:
                cut += len(seam) if seam != " " else 1
                break
            cut = -1
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


def _author_names(api: Espn) -> tuple[dict[str, str], str]:
    """Map SWID -> display label, and return Alex's own SWID.

    Teams win over initials because a team name is the identity everyone in the
    league actually uses, and it keeps real names out of stdout.
    """
    data = api.league("mTeam")
    members = {m["id"]: m for m in data.get("members", [])}
    names: dict[str, str] = {}
    for t in data.get("teams", []):
        owner = t.get("primaryOwner") or (t.get("owners") or [None])[0]
        if owner:
            names[owner] = t.get("name") or t.get("abbrev") or initials(members.get(owner))
    for swid, member in members.items():
        names.setdefault(swid, initials(member))
    return names, str(api.creds["SWID"])


def _stamp(ms: int | None) -> str:
    if not ms:
        return ""
    return datetime.datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d %H:%M:%S")


def fetch(api: Espn, include_activity: bool = False) -> list[dict[str, Any]]:
    """Every chat thread, newest activity last within each thread.

    Threads are sorted by their most recent message so the live conversation is
    the final one printed.
    """
    raw = api.league(VIEW, path=TOPICS_PATH)
    names, me = _author_names(api)
    threads: list[dict[str, Any]] = []
    for topic in raw if isinstance(raw, list) else []:
        kind = topic.get("type") or ""
        if not include_activity and kind not in CHAT_TYPES:
            continue
        messages = []
        for m in sorted(topic.get("messages") or [], key=lambda x: x.get("date") or 0):
            content = m.get("content")
            if content is None:
                continue  # ESPN's own system rows carry no body
            author = m.get("author") or ""
            messages.append({
                "id": m.get("id"),
                "date": m.get("date"),
                "at": _stamp(m.get("date")),
                "author": author,
                "who": "you" if author == me else names.get(author, author or "ESPN"),
                "mine": author == me,
                "content": content,
            })
        if not messages and not include_activity:
            continue
        viewable = topic.get("viewableBy") or []
        threads.append({
            "id": topic.get("id"),
            "type": kind,
            "created": _stamp((topic.get("creationInfo") or {}).get("date")),
            "with": [names.get(s, s) for s in viewable if s != me],
            "messages": messages,
            "last": messages[-1]["date"] if messages else 0,
        })
    threads.sort(key=lambda t: t["last"] or 0)
    return threads


def unanswered(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Threads whose most recent message came from somebody else.

    This is the watcher's trigger. Deliberately not "messages since timestamp":
    a thread where they spoke last is the thing that wants a reply, and it
    survives a watcher restart without needing durable cursor state.
    """
    return [t for t in threads if t["messages"] and not t["messages"][-1]["mine"]]
