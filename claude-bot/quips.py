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
