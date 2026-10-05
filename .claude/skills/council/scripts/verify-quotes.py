#!/usr/bin/env python3
"""Check that the quotes in a council member note occur in a source corpus.

Usage:
    verify-quotes.py NOTE.md CORPUS_DIR [CORPUS_DIR ...]
    verify-quotes.py --text "a quote to find" CORPUS_DIR [...]

A quote in a note is an Obsidian quote callout:

    > [!quote] Source citation
    > The quoted words.

Matching ignores case, punctuation, and typography, so curly quotes, dashes and
line breaks do not cause a miss. An ellipsis (... or the single character) splits
the quote into fragments that must all occur, in order, inside one file. When no
exact match exists, a fuzzy pass reports the best near match (ratio >= 0.85),
because OCR text and fan transcripts contain small errors.

The exit status is 1 if any quote is missing, so the script can gate a build.

INVARIANTS:
- A FOUND result names each file that contains the quote (up to three) and
  prints the text around the match, so a person can confirm who speaks the
  line. Presence alone does not prove the speaker.
- The script never edits the note.
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

CALLOUT = re.compile(r"^>\s*\[!quote\][^\n]*\n((?:>[^\n]*\n?)+)", re.M)
ELLIPSIS = re.compile(r"\.\s*\.\s*\.|…")


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    text = re.sub(r"[‘’ʼ`']", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def quotes_in_note(path: Path) -> list[str]:
    body = path.read_text(encoding="utf-8")
    found = []
    for m in CALLOUT.finditer(body):
        lines = [re.sub(r"^>\s?", "", ln) for ln in m.group(1).splitlines()]
        found.append(" ".join(ln for ln in lines if ln.strip()))
    return found


def load_corpus(dirs: list[Path]) -> list[tuple[Path, str, str]]:
    docs = []
    for d in dirs:
        files = [d] if d.is_file() else sorted(p for p in d.rglob("*") if p.is_file())
        for p in files:
            raw = p.read_text(encoding="utf-8", errors="replace")
            docs.append((p, raw, norm(raw)))
    return docs


def context(raw: str, fragment: str) -> str:
    words = norm(fragment).split()[:4]
    if not words:
        return ""
    pattern = r"\W+".join(re.escape(w) for w in words)
    m = re.search(pattern, unicodedata.normalize("NFKD", raw).lower().replace("’", "'"))
    if not m:
        return ""
    start = max(0, m.start() - 160)
    return re.sub(r"\s+", " ", raw[start : m.start() + 120]).strip()


def find(quote: str, docs) -> list[tuple[str, Path | None, str]]:
    frags = [norm(f) for f in ELLIPSIS.split(quote) if norm(f)]
    hits = []
    for path, raw, text in docs:
        pos, ok = 0, True
        for f in frags:
            i = text.find(f, pos)
            if i < 0:
                ok = False
                break
            pos = i + len(f)
        if ok:
            hits.append(("FOUND", path, context(raw, frags[0])))
    if hits:
        return hits
    target = " ".join(frags)
    best = (0.0, None, "")
    anchor = max(target.split(), key=len)
    for path, _raw, text in docs:
        for m in re.finditer(re.escape(anchor), text):
            lo = max(0, m.start() - len(target))
            window = text[lo : m.end() + len(target)]
            sm = SequenceMatcher(None, target, window, autojunk=False)
            blk = max(sm.get_matching_blocks(), key=lambda b: b.size)
            seg = window[max(0, blk.b - blk.a) : max(0, blk.b - blk.a) + len(target)]
            r = SequenceMatcher(None, target, seg, autojunk=False).ratio()
            if r > best[0]:
                best = (r, path, seg)
    if best[0] >= 0.85:
        return [(f"FUZZY {best[0]:.2f}", best[1], best[2])]
    return [(f"MISSING (best {best[0]:.2f})", best[1], best[2])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("note", nargs="?", type=Path)
    ap.add_argument("corpus", nargs="+", type=Path)
    ap.add_argument("--text", help="check one quote instead of a note")
    a = ap.parse_args()
    corpus = list(a.corpus)
    if a.text and a.note:
        corpus.insert(0, a.note)
    quotes = [a.text] if a.text else quotes_in_note(a.note)
    if not quotes:
        print("no [!quote] callouts found")
        return 1
    docs = load_corpus(corpus)
    missing = 0
    for q in quotes:
        hits = find(q, docs)
        status = hits[0][0]
        missing += status.startswith("MISSING")
        extra = f", {len(hits)} files" if len(hits) > 1 else ""
        print(f"[{status}{extra}] {q[:90]}")
        for _status, path, ctx in hits[:3]:
            if path:
                print(f"    in: {path.name}")
            if ctx and not status.startswith("MISSING"):
                print(f"    ctx: ...{ctx}...")
    print(f"\n{len(quotes) - missing}/{len(quotes)} quotes located")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
