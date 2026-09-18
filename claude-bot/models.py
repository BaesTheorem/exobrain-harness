"""Which models and effort levels the installed `claude` CLI understands.

The chatter module lets Alex switch model and thinking depth from Discord, so
it needs to validate what he types. Rather than hardcode a list that goes stale
the day a new model ships, this greps the installed `claude` binary for the
clean model aliases it knows (the same trick the MIST Console uses for its
model picker), so a CLI update is all it takes for a new model to become
selectable. Pure stdlib on purpose: the harness test suite imports it without
the bot's venv.

INVARIANTS (do not break these in an edit):
  - Discovery failure is never fatal: with no binary to read, every model name
    is accepted and the CLI itself is left to reject it.
  - Effort levels are exactly the CLI's `--effort` choices plus "default"
    (meaning: don't pass the flag).
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

# The CLI accepts a bare family alias for the newest model of that family.
ALIASES = ("fable", "opus", "sonnet", "haiku")

# `claude --effort` choices, in ascending order. "default" means omit the flag
# and let the CLI pick its own (currently xhigh for Opus-class models).
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

_ALIAS_RE = re.compile(rb"claude-(fable|opus|sonnet|haiku)-[0-9][0-9-]*")
# A clean alias is family + short version with no dated / -v1 / -fast suffix,
# e.g. claude-opus-5, claude-opus-4-8, claude-fable-5-1. Version parts are at
# most two digits, which is what rejects dated snapshots like -4-20250514.
_CLEAN_RE = re.compile(r"^claude-(fable|opus|sonnet|haiku)-(\d{1,2}(?:-\d{1,2})?)$")


def find_claude_bin() -> str | None:
    """Locate the claude CLI. Under launchd PATH is minimal, so fall back to
    the known install homes rather than trusting which() alone."""
    found = shutil.which("claude")
    if found:
        return os.path.realpath(found)
    home = Path.home()
    for p in (home / ".local" / "bin" / "claude", home / ".npm-global" / "bin" / "claude"):
        if os.access(p, os.X_OK):
            return os.path.realpath(p)
    return None


def _version_tuple(ver: str) -> tuple[int, ...]:
    return tuple(int(x) for x in ver.split("-"))


def discover_models(binpath: str | None) -> list[str]:
    """Clean model ids the binary knows, newest first within each family and
    families in ALIASES order. Empty list when the binary can't be read."""
    if not binpath:
        return []
    try:
        data = Path(binpath).read_bytes()
    except OSError:
        return []
    by_family: dict[str, set[str]] = {}
    for m in _ALIAS_RE.finditer(data):
        tok = m.group(0).decode()
        clean = _CLEAN_RE.match(tok)
        if not clean:
            continue
        by_family.setdefault(clean.group(1), set()).add(clean.group(2))
    out: list[str] = []
    for fam in ALIASES:
        vers = sorted(by_family.get(fam, ()), key=_version_tuple, reverse=True)
        out.extend(f"claude-{fam}-{v}" for v in vers)
    return out


class ModelCatalog:
    """Lazily discovered, cached against the binary's mtime so a CLI update
    refreshes the list without a bot restart."""

    def __init__(self, binpath: str | None = None):
        self.binpath = binpath or find_claude_bin()
        self._key: float | None = None
        self._models: list[str] = []

    def models(self) -> list[str]:
        try:
            key = os.path.getmtime(self.binpath) if self.binpath else None
        except OSError:
            key = None
        if key != self._key or not self._models:
            self._models = discover_models(self.binpath)
            self._key = key
        return self._models

    def normalize(self, name: str) -> str | None:
        """Return the canonical model string for what Alex typed, or None if
        the CLI doesn't know it. Accepts family aliases, clean ids, and the
        `[1m]` context suffix. With no discovery data, accepts anything."""
        name = name.strip().lower()
        if not name:
            return None
        base, suffix = (name[:-4], "[1m]") if name.endswith("[1m]") else (name, "")
        if base in ALIASES:
            return base + suffix
        known = self.models()
        if not known or base in known:
            return base + suffix
        return None


def normalize_effort(level: str) -> str | None:
    """Canonical effort level, "default" to clear, or None if unknown."""
    level = level.strip().lower()
    if level in ("default", "auto", "reset"):
        return "default"
    if level in EFFORT_LEVELS:
        return level
    return None
