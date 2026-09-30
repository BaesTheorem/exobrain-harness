"""Natural-language model / effort switches for the chatter module.

Alex asked (2026-09-30) to change MIST's model and thinking depth by just
saying so ("switch to sonnet", "think harder", "max effort") instead of typing
`!model` / `!effort`. This module turns a chat message into a switch request
with plain regexes, so a switch never costs a CLI call and can never become a
tool call. Pure stdlib on purpose: the harness test suite imports it without
the bot's venv.

INVARIANTS (do not break these in an edit):
  - Phrasings must be explicit requests. "a low effort meme", "write me a
    haiku", "I use sonnet for code" are NOT switches; every pattern needs a
    command verb or a sentence boundary around it. A missed switch costs one
    `!model`; a false switch silently changes her model.
  - The parser only reports what was asked. Validation (is that model real?)
    and stepping (harder than what?) belong to the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Ascending, same as models.EFFORT_LEVELS (duplicated so this stays importable
# on its own). "default" = omit the flag; the CLI then picks xhigh for Opus.
LEVELS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_AS = "xhigh"

_FAM = (
    r"(?:claude[\s-]+)?(?P<fam>fable|opus|sonnet|haiku)"
    r"(?:[\s-]+(?P<ver>\d{1,2}(?:[.\-]\d{1,2})?))?"
    r"(?P<ctx>\s*(?:\[1m\]|\(?1m(?:\s+context)?\)?))?"
    r"(?![\w-])"
)
# What can follow a bare "use <model>" / "<level> effort" for it to count as a
# request rather than a mention inside a longer sentence.
_TAIL = (
    r"(?=\s*(?:$|[.!?,;:)]|and\b|please\b|plz\b|pls\b|now\b|instead\b|"
    r"for\s+(?:this|now|a\s+bit|a\s+while|the\s+rest)|from\s+now|again\b|mode\b|model\b))"
)
_LVL = r"(?P<lvl>low|med(?:ium)?|high|x-?high|extra[\s-]high|max(?:imum)?|default|auto)"

_MODEL_PATTERNS = [
    re.compile(
        r"\b(?:switch|swap|change|flip|go|move|hop)"
        r"(?:\s+(?:yourself|over|back|models?|it))*\s+to\s+(?:the\s+)?" + _FAM,
        re.I,
    ),
    re.compile(r"\buse\s+(?:the\s+)?" + _FAM + r"(?:\s+model)?" + _TAIL, re.I),
]

_EFFORT_PATTERNS = [
    # "set your effort to high", "bump thinking up to max", "effort: low"
    re.compile(
        r"\b(?:set|put|change|switch|turn|crank|bump|drop|dial)\s+(?:your\s+|the\s+)?"
        r"(?:effort|thinking(?:\s+depth)?|reasoning|thinking\s+level)(?:\s+level)?"
        r"\s+(?:up\s+|down\s+|back\s+)?(?:to|at)\s+" + _LVL + r"\b",
        re.I,
    ),
    re.compile(r"\b(?:effort|thinking)\s*[:=]\s*" + _LVL + r"\b", re.I),
    # "max effort please", "use high thinking", "go low effort"
    re.compile(
        r"(?:^|[,.;:!?]\s*|\b(?:use|go|switch\s+to|set\s+(?:it\s+)?to|try|give\s+me|do|go\s+with)\s+)"
        r"(?:a\s+)?" + _LVL + r"\s+(?:effort|thinking|reasoning)(?:\s+mode)?" + _TAIL,
        re.I,
    ),
]
_MAX = re.compile(r"\bthink\s+(?:as\s+hard\s+as\s+(?:you\s+)?(?:can|possible)|really\s+really\s+hard)\b", re.I)
_UP = re.compile(r"\bthink\s+(?:a\s+lot\s+|much\s+|way\s+|a\s+bit\s+|a\s+little\s+)?(?:harder|deeper|longer)\b", re.I)
_DOWN = re.compile(
    r"\b(?:think\s+(?:a\s+bit\s+|a\s+little\s+|way\s+)?(?:less|lighter|faster|quicker)(?!\s+of\b)"
    r"|(?:don'?t|do\s+not)\s+(?:over)?think\s+(?:so\s+much|as\s+hard|too\s+hard))\b",
    re.I,
)
_RESET = re.compile(r"\b(?:reset|clear)\s+(?:your\s+|the\s+)?(?:effort|thinking)(?:\s+level)?\b", re.I)

_FILLER = re.compile(
    r"@[\w.]+|\b(?:please|plz|pls|and|ok(?:ay)?|now|also|then|mist|hey|hi|thanks|thank\s+you|ty|"
    r"for\s+(?:this|now|a\s+bit|a\s+while|the\s+rest)|from\s+now(?:\s+on)?|instead|again|"
    r"can\s+you|could\s+you|would\s+you|will\s+you|you|mode|model|the|a|to|yourself|"
    r"let'?s|i\s+want|i'?d\s+like|go\s+ahead)\b|[^\w]+",
    re.I,
)


@dataclass
class Switch:
    model: str | None = None   # as typed, lightly canonicalized; caller validates
    effort: str | None = None  # an absolute level or "default"
    step: int = 0              # +1 harder, -1 lighter (ignored when effort is set)
    rest: str = ""             # the message minus the switch phrases

    @property
    def any(self) -> bool:
        return bool(self.model or self.effort or self.step)

    @property
    def substantive(self) -> bool:
        """True when the rest still asks something beyond the switch."""
        return bool(_FILLER.sub("", self.rest).strip())


def _canon_model(m: re.Match) -> str:
    fam = m.group("fam").lower()
    ver = m.group("ver")
    name = f"claude-{fam}-{ver.replace('.', '-')}" if ver else fam
    return name + ("[1m]" if m.group("ctx") else "")


def _canon_level(raw: str) -> str:
    raw = re.sub(r"[\s-]", "", raw.lower())
    return {"med": "medium", "extrahigh": "xhigh", "maximum": "max", "auto": "default"}.get(raw, raw)


def parse(text: str) -> Switch:
    """Find a model and/or effort switch in one chat message."""
    spans: list[tuple[int, int]] = []
    out = Switch()
    for pat in _MODEL_PATTERNS:
        if m := pat.search(text):
            out.model = _canon_model(m)
            spans.append(m.span())
            break
    for pat in _EFFORT_PATTERNS:
        if m := pat.search(text):
            out.effort = _canon_level(m.group("lvl"))
            spans.append(m.span())
            break
    if out.effort is None:
        for pat, eff, step in ((_RESET, "default", 0), (_MAX, "max", 0), (_UP, None, 1), (_DOWN, None, -1)):
            if m := pat.search(text):
                out.effort, out.step = eff, step
                spans.append(m.span())
                break
    rest = text
    for a, b in sorted(spans, reverse=True):
        rest = rest[:a] + " " + rest[b:]
    out.rest = " ".join(rest.split())
    return out


def stepped(current: str, step: int) -> str:
    """Move one effort level up or down; "default" counts as DEFAULT_AS."""
    cur = DEFAULT_AS if current not in LEVELS else current
    i = max(0, min(len(LEVELS) - 1, LEVELS.index(cur) + step))
    return LEVELS[i]
