#!/usr/bin/env python3
"""Check a tailored resume or cover letter against the candidate's own facts.

The fit gate checks the input (does the JD fit the candidate?). Nothing
checked the output: a tailoring pass can drift from "reorder and reword" to
"claim the JD's keywords". This script is that check, in code, before a PDF
is built. (Same idea as career-ops verify-cv-facts and Seekter claims.mjs.)

Sources of truth, all optional except the first:
  data/resume_data.json   the canonical resume (every string in it)
  data/facts.md           a free-form fact bank: certifications, tools, numbers
                          you can back up but do not print on every resume
  --jd FILE               the job description; numbers it states (team sizes,
                          "24/7") may be repeated back

Findings:
  NUMBER     a figure (73%, $2M, 400 users, 5+ years) in the text that is in
             neither the sources nor the JD                       -> blocks
  CLAIMED    an acronym or CamelCase product name that the JD uses and the
             sources never mention: the JD keyword possibly echoed as your
             own experience. Often it is context ("your HUD clients"), so it
             is a review list; --strict makes it block.
  UNSOURCED  a term in neither the sources nor the JD             -> warns
  STYLE      an em dash, or a phrase from `writing.banned` in profile.yaml -> warns

Tested 2026-10-23 on real letters: with blocking on every capitalized JD
word, all of them failed on role titles, office cities and greetings. So
plain capitalized words only warn, the role title (--title) and the employer
(--company) are allowed, and greeting and sign-off lines are skipped.

A clean run does not prove the text is honest: two true facts can combine
into a false claim. Read every document before you send it.

Usage:
    python3 resume-builder/factcheck.py tailoring/acme.json --jd jd.txt
    python3 resume-builder/factcheck.py tailoring/acme_cover.md --jd jd.txt --company "Acme" \
        --title "GRC Analyst II"

Exit: 0 clean or warnings only, 1 when a NUMBER (or, with --strict, a
CLAIMED) finding blocks.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "resume_data.json"
FACTS = HERE / "data" / "facts.md"

NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?\s?(?:%|\+|[kKmM]\b|x\b)?")
TERM = re.compile(r"\b(?:[A-Z]{2,}[0-9]*(?:-[A-Z0-9]+)?|[A-Z][a-z]+[A-Z]\w*|[A-Z][a-z]{2,}(?:\s[A-Z][a-z]+)*)\b")
COMMON = set("""
a an and are as at be been but by for from has have he her his i if in into is it its me my of on or our she so
that the their them they this to was we were what when which who will with you your dear best regards sincerely
thank thanks hiring team manager role position company january february march april may june july august september
october november december monday tuesday wednesday thursday friday saturday sunday i'm im also while after before
during over across through about more most first second new senior junior lead my
""".split())
EM_DASH = "\u2014"
ROMAN = re.compile(r"^(?:I{1,3}|IV|V|VI{0,3})$")
TECH = re.compile(r"^(?:[A-Z]{2,}[0-9]*(?:-[A-Z0-9]+)?|[A-Z][a-z]+[A-Z]\w*)$")
SKIP_LINE = re.compile(r"^\s*(dear|best|sincerely|regards|thank you|thanks)\b", re.I)


def flatten(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in flatten(v)]
    if isinstance(obj, list):
        return [s for v in obj for s in flatten(v)]
    return []


def norm_num(s: str) -> str:
    s = s.strip().lower().replace(",", "").replace("$", "").replace(" ", "")
    return s.rstrip("+").rstrip("%").rstrip("x")


def numbers(text: str) -> set[str]:
    out = set()
    for m in NUM.finditer(text):
        n = norm_num(m.group(0))
        if n and not re.fullmatch(r"(19|20)\d\d", n):  # years are dates, not claims
            out.add(n)
    return out


def terms(text: str) -> set[str]:
    out = set()
    text = "\n".join(ln for ln in text.splitlines() if not SKIP_LINE.match(ln))
    for sent in re.split(r"(?<=[.!?:\n])\s+", text):
        for i, m in enumerate(TERM.finditer(sent)):
            t = m.group(0)
            if i == 0 and m.start() == 0 and not re.search(r"[A-Z].*[A-Z]", t):
                continue  # an ordinary capital at the start of a sentence
            if t.lower() in COMMON or ROMAN.match(t):
                continue
            out.add(t)
    return out


def text_of(path: Path) -> str:
    if path.suffix == ".json":
        d = json.loads(path.read_text(encoding="utf-8"))
        d.pop("_comment", None)
        d.pop("tag", None)
        return "\n".join(flatten(d))
    return path.read_text(encoding="utf-8")


def banned_phrases() -> list[str]:
    try:
        sys.path.insert(0, str(HERE.parent / "job-search"))
        import jobprofile
        return list(jobprofile.get("writing.banned", []))
    except Exception:  # noqa: BLE001  no profile: style checks fall back to em dashes only
        return []


def check(text: str, sources: str, jd: str, extra_ok: set[str]) -> list[tuple[str, str]]:
    src_l, jd_l = sources.lower(), jd.lower()
    src_nums, jd_nums = numbers(sources), numbers(jd)
    found: list[tuple[str, str]] = []
    for n in sorted(numbers(text)):
        if n not in src_nums and n not in jd_nums:
            found.append(("NUMBER", n))
    for t in sorted(terms(text)):
        words = [w.lower() for w in t.split()]
        if t.lower() in src_l or all(w in src_l or w in extra_ok or w in COMMON for w in words):
            continue
        claimed = TECH.match(t) and t.lower() in jd_l
        found.append(("CLAIMED" if claimed else "UNSOURCED", t))
    if EM_DASH in text:
        found.append(("STYLE", "em dash"))
    for b in banned_phrases():
        if b.lower() in text.lower():
            found.append(("STYLE", f"banned phrase: {b}"))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="fact-check tailored text against the candidate's sources")
    ap.add_argument("file", help="tailoring JSON or cover-letter markdown")
    ap.add_argument("--jd", help="job description text file")
    ap.add_argument("--company", default="", help="employer name (allowed in the text)")
    ap.add_argument("--title", default="", help="the role title (allowed in the text)")
    ap.add_argument("--strict", action="store_true", help="CLAIMED findings block too")
    ap.add_argument("--data", default=str(DATA))
    a = ap.parse_args()

    data_path = Path(a.data)
    if not data_path.exists():
        sys.exit(f"no canonical resume data at {data_path}; copy data/resume_data.example.json")
    sources = "\n".join(flatten(json.loads(data_path.read_text(encoding="utf-8"))))
    if FACTS.exists():
        sources += "\n" + FACTS.read_text(encoding="utf-8")
    jd = Path(a.jd).read_text(encoding="utf-8") if a.jd else ""
    ok = {w.lower() for w in f"{a.company} {a.title}".split()} | {a.company.lower(), a.title.lower()}

    found = check(text_of(Path(a.file)), sources, jd, ok)
    blocking = [f for f in found if f[0] == "NUMBER" or (a.strict and f[0] == "CLAIMED")]
    for kind, what in found:
        print(f"{kind:9} {what}")
    if not a.jd:
        print("note: no --jd given, so JD keywords cannot be told apart (all show as UNSOURCED)")
    print(f"\n{len(blocking)} blocking, {len(found) - len(blocking)} warnings")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
