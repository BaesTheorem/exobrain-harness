"""Pronunciation fixes for XTTS -- respell words the model mangles, phonetically.

XTTS occasionally mispronounces specific words (e.g. "synced" -> "sinsed").
There's no per-word phoneme input, so we respell the offender to a spelling the
model says correctly, applied right before synthesis. Whole-word, case-aware.

Grow PRON as you hit new offenders. Keys are lowercase; matching is
case-insensitive and preserves the original capitalization pattern.
"""
import re

# offender (lowercase) -> phonetic respelling that XTTS says correctly
PRON = {
    "synced": "synked",    # XTTS says "sinsed" for "synced" (verified by ear)
}

_word = re.compile(r"[A-Za-z]+")

def _match_case(src: str, repl: str) -> str:
    if src.isupper():
        return repl.upper()
    if src[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl

def fix_pronunciation(text: str) -> str:
    if not PRON:
        return text
    def sub(m):
        w = m.group(0)
        r = PRON.get(w.lower())
        return _match_case(w, r) if r else w
    return _word.sub(sub, text)
