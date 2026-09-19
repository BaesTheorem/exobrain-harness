"""Discord attachments for the chatter -- make files in a message visible.

A Discord message can carry files and no text at all. The chatter renders the
channel as a plain "Name: text" transcript, so an image-only message rendered
as an empty line and got dropped entirely: MIST was handed a turn with nothing
in it and answered the emptiness ("I don't see an image"). This module is what
puts the attachment into the transcript.

Two contexts, two behaviours:

  - **Private** (Alex in a DM or his personal server): the file is downloaded
    to a cache dir outside the repo and the transcript carries the local path,
    so MIST can open it with Read. She has file tools there.
  - **Shared** (anyone else, anywhere): nothing is downloaded. The transcript
    only names the file, because the sandboxed CLI has no tool that could open
    it and the bytes are not ours to stash.

INVARIANTS (do not break these in an edit):
  - Never download for a shared/guest context.
  - The cache lives outside the repo (Alex's data, not code) and is pruned by
    age, so it can't grow without bound.
  - Filenames from Discord are untrusted: always run them through safe_name()
    before joining them to a path.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

log = logging.getLogger("fletcher")

# Outside the repo on purpose: these are Alex's files, not source.
CACHE_DIR = Path.home() / ".claude" / "channels" / "discord" / "attachments"

# Discord's own upload ceiling for a normal account is 25MB; skip anything
# bigger rather than pulling a surprise file onto an 8GB machine.
MAX_BYTES = 25 * 1024 * 1024
# How many files one prompt may pull. Enough for a burst of screenshots.
MAX_FILES = 6
# Cached downloads older than this are deleted on the next build.
TTL_DAYS = 7

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(message_id: int, attachment_id: int, filename: str) -> str:
    """A collision-free, path-safe cache filename for one attachment.

    The ids make it unique (so a re-read of the same message reuses the file)
    and the sanitized original name keeps it recognizable in a prompt.
    """
    stem = _UNSAFE.sub("_", filename or "").strip("._-")[-80:] or "file"
    return f"{message_id}-{attachment_id}-{stem}"


def kind_of(content_type: str | None, filename: str = "") -> str:
    """The word used in the transcript marker: image, video, audio, or file."""
    ctype = (content_type or "").lower()
    for prefix in ("image", "video", "audio"):
        if ctype.startswith(prefix + "/"):
            return prefix
    if filename.lower().endswith(".pdf") or ctype == "application/pdf":
        return "PDF"
    return "file"


def marker(filename: str, content_type: str | None, path: Path | str | None = None) -> str:
    """The bracketed note that stands in for a file inside the transcript."""
    kind = kind_of(content_type, filename)
    if path is None:
        return f"[{kind} attached: {filename}]"
    return f'[{kind} attached: "{filename}" -- saved locally at {path} , open it with Read]'


def prune(cache_dir: Path = CACHE_DIR, ttl_days: float = TTL_DAYS,
          now: float | None = None) -> int:
    """Delete cached files older than the TTL. Returns how many went."""
    if not cache_dir.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - ttl_days * 86400
    gone = 0
    for path in cache_dir.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                gone += 1
        except OSError:
            continue
    return gone


def pick(messages, limit: int = MAX_FILES, max_bytes: int = MAX_BYTES) -> list:
    """Choose which attachments to download, newest message first.

    `messages` is the transcript in chronological order. Recency wins: if Alex
    dropped five screenshots and then one more, the newest ones are the ones
    he is talking about, so they get the budget.
    """
    chosen = []
    for message in reversed(list(messages)):
        for att in getattr(message, "attachments", ()):
            if len(chosen) >= limit:
                return chosen
            if getattr(att, "size", 0) > max_bytes:
                log.info("skipping attachment %s (%s bytes, over cap)", att.filename, att.size)
                continue
            chosen.append((message, att))
    return chosen


async def download(message_id: int, att, cache_dir: Path = CACHE_DIR) -> Path | None:
    """Save one attachment into the cache; returns its path, or None on error.

    Re-uses an existing non-empty file, so quoting the same image across
    several turns costs one fetch.
    """
    path = cache_dir / safe_name(message_id, att.id, att.filename)
    try:
        if path.is_file() and path.stat().st_size > 0:
            return path
        cache_dir.mkdir(parents=True, exist_ok=True)
        await att.save(path)
    except Exception:  # noqa: BLE001 - a bad file must never kill the reply
        log.warning("could not save attachment %s", att.filename, exc_info=True)
        return None
    return path
