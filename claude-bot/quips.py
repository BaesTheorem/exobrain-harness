"""Rolling quip picker.

MIST sprinkles a varied, in-character one-liner onto her slash-command replies
so they never read as canned. "Rolling" = a shuffle-bag: it deals out every
line in the pool in a random order, and only reshuffles once the bag is empty,
so you never see the same quip twice in a row (and you see all of them before
any repeat). The rotation lives in memory for the life of the process; it resets
on restart, which is fine for a cosmetic flourish.
"""

from __future__ import annotations

import random


class RollingQuips:
    def __init__(self, lines: list[str]):
        self._lines = list(lines)
        self._bag: list[str] = []

    def next(self) -> str:
        if not self._lines:
            return ""
        if len(self._lines) == 1:
            return self._lines[0]
        if not self._bag:
            # Fresh shuffled bag; avoid the new bag's first pick equalling the
            # last one dealt so there's never a back-to-back repeat across bags.
            last = getattr(self, "_last", None)
            self._bag = random.sample(self._lines, len(self._lines))
            if self._bag[-1] == last:
                self._bag.insert(0, self._bag.pop())
        quip = self._bag.pop()
        self._last = quip
        return quip


class Quips:
    """Central rolling-quip registry, shared across modules via ctx.quips.

    Each module registers a pool per command key in setup() (e.g. "portal.open"),
    then tags a response so MIST signs off with a rolling, relevant one-liner
    rendered as Discord subtext (-#). Any key without a registered pool falls
    back to the "general" pool, so EVERY command (current or future) gets a quip
    for free, even before someone writes it a bespoke pool.

    Keep quips short and dry: no narrating feelings, no 💛/🥺 filler.
    """

    _GENERAL = [
        "There you go ✨",
        "Done 🫡",
        "Handled ✨",
        "That's that 👀",
        "Anything else? ^_^",
        "Easy 🫡",
    ]

    def __init__(self):
        self._pools: dict[str, RollingQuips] = {"general": RollingQuips(list(self._GENERAL))}

    def add(self, key: str, lines: list[str]) -> None:
        self._pools[key] = RollingQuips(lines)

    def line(self, key: str = "general") -> str:
        pool = self._pools.get(key) or self._pools["general"]
        return pool.next()

    def tag(self, text: str, key: str = "general") -> str:
        """Append a rolling quip to `text` as Discord subtext."""
        quip = self.line(key)
        return f"{text}\n-# {quip}" if quip else text
