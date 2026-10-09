#!/usr/bin/env python3
"""Gate 4 (strong fit) as arithmetic, not as a feeling.

Every listing note that survives gates 1-3 carries a `## Fit scorecard` table,
one row per JD line, each scored against the verb-level Capability Boundaries
table in the gitignored Claude Reference. This script reads those tables and
decides gate 4, so a fluent "why this fits" paragraph can no longer pass a role
the rows do not support.

Table format (columns in this order, extra columns ignored):

    | # | JD line | Kind | Asks | Alex | Verdict | Evidence |
    |---|---|---|---|---|---|---|
    | 1 | "Deploy and maintain AVD environments" | core | Own/Build | Support | Unmet | Boundaries: AVD deployment |

    Kind     required (a stated qualification) | core (a primary duty) | preferred
    Verdict  Met | Partial | Unmet

Decision:
    FAIL        any `required` row is Unmet (a knockout), or
                score < 0.80, where score = (Met + 0.5 * Partial) / (required + core rows)
    INCOMPLETE  fewer than MIN_ROWS required + core rows (the scorer skimmed)
    UNSCORED    no scorecard section
    PASS        otherwise

Usage:
    fit-gate.py                     report on active candidate notes
    fit-gate.py --note <path> ...   report on specific notes (use this in a scan)
    fit-gate.py --all               include declined / skipped / closed notes
    fit-gate.py --write             stamp fit_score + fit_gate into frontmatter
    fit-gate.py --enforce           --write, and decline FAIL notes: status skipped,
                                    declined true, and a `## Why skipped` section
                                    that quotes the failing rows

Built 2026-10-09 after a sysadmin seat passed as "his day job restated" at
roughly 50% real overlap.

INVARIANTS
- The threshold and weights live here and nowhere else; the skill cites this file.
- --enforce never touches a note that is applied, interviewing, or offer.
- A note without a scorecard is never declined by --enforce, only reported.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = "/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings"
THRESHOLD = 0.80
MIN_ROWS = 5
WEIGHT = {"met": 1.0, "partial": 0.5, "unmet": 0.0}
PROTECTED = {"applied", "interviewing", "offer"}


def frontmatter(txt: str) -> tuple[str, int]:
    m = re.match(r"---\n(.*?)\n---\n", txt, re.S)
    return (m.group(1), m.end()) if m else ("", 0)


def field(fm: str, key: str) -> str:
    m = re.search(r"^%s:[ \t]*(.*)$" % key, fm, re.M)
    return m.group(1).strip().strip('"') if m else ""


def set_field(fm: str, key: str, value: str) -> str:
    line = f"{key}: {value}"
    if re.search(r"^%s:" % key, fm, re.M):
        return re.sub(r"^%s:.*$" % key, line, fm, count=1, flags=re.M)
    return fm + "\n" + line


def scorecard_rows(txt: str) -> list[dict] | None:
    m = re.search(r"^## Fit scorecard[^\n]*\n(.*?)(?=^#{1,2} |^> \[!|\Z)", txt, re.S | re.M)
    if not m:
        return None
    rows = []
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or set(cells[0]) <= set("-: ") or cells[0] == "#":
            continue
        kind, verdict = cells[2].lower(), cells[5].lower().strip("* ")
        if kind not in ("required", "core", "preferred") or verdict not in WEIGHT:
            continue
        rows.append({"line": cells[1], "kind": kind, "verdict": verdict,
                     "evidence": cells[6] if len(cells) > 6 else ""})
    return rows


def judge(rows: list[dict] | None) -> tuple[str, float | None, list[str]]:
    if rows is None:
        return "UNSCORED", None, []
    scored = [r for r in rows if r["kind"] in ("required", "core")]
    if len(scored) < MIN_ROWS:
        return "INCOMPLETE", None, [f"only {len(scored)} required/core rows (minimum {MIN_ROWS})"]
    score = sum(WEIGHT[r["verdict"]] for r in scored) / len(scored)
    reasons = [f"knockout: {r['line']}" for r in scored
               if r["kind"] == "required" and r["verdict"] == "unmet"]
    if score < THRESHOLD:
        reasons.append(f"score {score:.2f} < {THRESHOLD:.2f}")
    return ("FAIL" if reasons else "PASS"), score, reasons


def why_skipped(score: float | None, reasons: list[str], rows: list[dict]) -> str:
    unmet = [r for r in rows if r["kind"] in ("required", "core") and r["verdict"] == "unmet"]
    out = ["## Why skipped",
           f"Gate 4 failed in `job-search/fit-gate.py` (score {score:.2f}, threshold {THRESHOLD:.2f}).", ""]
    out += [f"- {r}" for r in reasons if not r.startswith("knockout")]
    out += [f"- Unmet {r['kind']}: {r['line']}" for r in unmet]
    return "\n".join(out) + "\n\n"


def enforce(path: str, txt: str, score: float | None, reasons: list[str], rows: list[dict]) -> str:
    fm, end = frontmatter(txt)
    fm = set_field(fm, "status", "skipped")
    fm = set_field(fm, "declined", "true")
    body = txt[end:]
    if "## Why skipped" not in body:
        block = why_skipped(score, reasons, rows)
        anchor = body.find("## Fit scorecard")
        body = body[:anchor] + block + body[anchor:] if anchor >= 0 else body + "\n" + block
    return f"---\n{fm}\n---\n" + body


def notes(paths: list[str], include_all: bool) -> list[str]:
    if paths:
        return paths
    out = []
    for dirpath, _, files in os.walk(ROOT):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(dirpath, fn)
            fm, _ = frontmatter(open(p, encoding="utf-8").read())
            if field(fm, "type") != "job-listing":
                continue
            active = (field(fm, "status") == "candidate" and field(fm, "applied") != "true"
                      and field(fm, "declined") != "true")
            if include_all or active:
                out.append(p)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--note", nargs="+", action="extend", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--enforce", action="store_true")
    a = ap.parse_args()

    tally: dict[str, int] = {}
    for p in notes(a.note, a.all):
        txt = open(p, encoding="utf-8").read()
        rows = scorecard_rows(txt)
        verdict, score, reasons = judge(rows)
        tally[verdict] = tally.get(verdict, 0) + 1
        shown = f"{score:.2f}" if score is not None else "  - "
        print(f"{verdict:<10} {shown}  {os.path.basename(p)[:-3]}")
        for r in reasons:
            print(f"{'':16}{r[:150]}")
        if not (a.write or a.enforce) or score is None:
            continue
        fm, end = frontmatter(txt)
        fm = set_field(set_field(fm, "fit_score", f"{score:.2f}"), "fit_gate", verdict.lower())
        txt = f"---\n{fm}\n---\n" + txt[end:]
        if a.enforce and verdict == "FAIL" and field(fm, "status") not in PROTECTED:
            txt = enforce(p, txt, score, reasons, rows or [])
            print(f"{'':16}-> declined (status skipped)")
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt)
    print("\n" + "  ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
