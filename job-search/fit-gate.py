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

    Kind     knockout (a hard bar: degree with no equivalent clause, citizenship,
                       clearance, license) | required (a stated qualification) |
             core (a primary duty) | preferred (not scored)
    Asks / Alex  Own/Build | Administer | Operate | Support | Exposure | None | n/a
    Verdict  Met | Partial | Unmet

Decision:
    INVALID     a numbered row does not parse, or a verdict contradicts its own
                levels (Met while Alex is below what the JD asks, or Unmet while
                he reaches it). Fix the table; an INVALID note is never enforced.
    FAIL        an Unmet `knockout` row, or
                score < THRESHOLD (0.65), where score = (Met + 0.5 * Partial) / scored rows
    INCOMPLETE  fewer than MIN_ROWS scored rows (the scorer skimmed)
    UNSCORED    no scorecard section
    OVERRIDE    the frontmatter has `fit_override: "<reason>"`. Alex's deliberate
                exception; reported with the reason, never enforced
    PASS        otherwise

Usage:
    fit-gate.py                     report on active candidate notes
    fit-gate.py --note <path> ...   report on specific notes (use this in a scan)
    fit-gate.py --all               include declined / skipped / closed notes
    fit-gate.py --write             stamp fit_score + fit_gate into frontmatter
    fit-gate.py --enforce           --write, and decline FAIL notes: status skipped,
                                    declined true, and a `## Why skipped` section
                                    that quotes the failing rows
    fit-gate.py --restore           --write, and undo this script's own decline on
                                    notes that now PASS (after a rule or threshold
                                    change). A decline it did not write is left alone.

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
# Calibrated 2026-10-09 against 30 past applications scored blind (vault note
# "Fit Gate Calibration 2026-10-09"): every one that got a screen scored 0.66+,
# none of 12 under 0.65 did, and 0.80 would have blocked 3 of the 5 screens.
# Re-run the calibration when about ten more outcomes exist.
THRESHOLD = 0.65
MIN_ROWS = 5
WEIGHT = {"met": 1.0, "partial": 0.5, "unmet": 0.0}
KINDS = ("knockout", "required", "core", "preferred")
SCORED = ("knockout", "required", "core")
# Which kinds veto on an Unmet row. Narrowed to `knockout` by Alex on
# 2026-10-09: an unmet `required` skill or tool line is scored, not a veto.
# Blind controls showed employers interviewing him past such lines (Nerdio's
# "deploying AVD", Horizon3's "familiarity with Jira").
KNOCKOUT_KINDS = ("knockout",)
LEVEL = {"own/build": 5, "own": 5, "build": 5, "administer": 4, "operate": 3,
         "support": 2, "exposure": 1, "none": 0, "n/a": None}
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


def level(cell: str) -> int | None:
    key = cell.lower().replace(" ", "")
    return LEVEL.get(key)


def scorecard_rows(txt: str) -> list[dict] | None:
    """Parse the table. A numbered row that cannot be parsed comes back with an
    `error` key instead of being dropped, so a malformed table cannot pass."""
    m = re.search(r"^## Fit scorecard[^\n]*\n(.*?)(?=^#{1,2} |^> \[!|\Z)", txt, re.S | re.M)
    if not m:
        return None
    rows = []
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not re.match(r"\|\s*\d+\s*\|", line.strip()):
            continue
        if len(cells) < 6:
            rows.append({"error": f"row {cells[0]}: {len(cells)} cells (a pipe inside a quote?)"})
            continue
        kind, verdict = cells[2].lower(), cells[5].lower().strip("* ")
        if kind not in KINDS or verdict not in WEIGHT:
            rows.append({"error": f"row {cells[0]}: kind {cells[2]!r} / verdict {cells[5]!r} not recognized"})
            continue
        row = {"line": cells[1], "kind": kind, "verdict": verdict,
               "asks": level(cells[3]), "alex": level(cells[4]),
               "evidence": cells[6] if len(cells) > 6 else ""}
        a, b = row["asks"], row["alex"]
        if a is not None and b is not None:
            if verdict == "met" and b < a:
                row["error"] = f"row {cells[0]}: Met, but Alex {cells[4]} is below the {cells[3]} the JD asks"
            elif verdict == "unmet" and a > 0 and b >= a:
                row["error"] = f"row {cells[0]}: Unmet, but Alex {cells[4]} reaches the {cells[3]} the JD asks"
        rows.append(row)
    return rows


def judge(rows: list[dict] | None) -> tuple[str, float | None, list[str]]:
    if rows is None:
        return "UNSCORED", None, []
    errors = [r["error"] for r in rows if "error" in r]
    good = [r for r in rows if "line" in r]
    scored = [r for r in good if r["kind"] in SCORED]
    score = sum(WEIGHT[r["verdict"]] for r in scored) / len(scored) if scored else None
    if errors:
        return "INVALID", score, errors
    if len(scored) < MIN_ROWS:
        return "INCOMPLETE", None, [f"only {len(scored)} scored rows (minimum {MIN_ROWS})"]
    reasons = [f"knockout: {r['line']}" for r in scored
               if r["kind"] in KNOCKOUT_KINDS and r["verdict"] == "unmet"]
    if score < THRESHOLD:
        reasons.append(f"score {score:.2f} < {THRESHOLD:.2f}")
    return ("FAIL" if reasons else "PASS"), score, reasons


def why_skipped(score: float | None, reasons: list[str], rows: list[dict]) -> str:
    unmet = [r for r in rows if r.get("kind") in SCORED and r.get("verdict") == "unmet"]
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


GENERATED = re.compile(r"## Why skipped\nGate 4 failed in `job-search/fit-gate.py`.*?(?=^## |\Z)", re.S | re.M)


def restore(txt: str) -> str | None:
    """Reverse enforce(): only when the Why skipped block is the one it wrote."""
    fm, end = frontmatter(txt)
    body = txt[end:]
    if field(fm, "declined") != "true" or not GENERATED.search(body):
        return None
    fm = set_field(set_field(fm, "status", "candidate"), "declined", "false")
    return f"---\n{fm}\n---\n" + GENERATED.sub("", body, count=1)


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
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()

    tally: dict[str, int] = {}
    for p in notes(a.note, a.all):
        txt = open(p, encoding="utf-8").read()
        rows = scorecard_rows(txt)
        verdict, score, reasons = judge(rows)
        override = field(frontmatter(txt)[0], "fit_override")
        if override and verdict in ("FAIL", "INVALID", "INCOMPLETE", "UNSCORED"):
            reasons = [f"overridden ({verdict}): {override}"] + reasons
            verdict = "OVERRIDE"
        tally[verdict] = tally.get(verdict, 0) + 1
        shown = f"{score:.2f}" if score is not None else "  - "
        print(f"{verdict:<10} {shown}  {os.path.basename(p)[:-3]}")
        for r in reasons:
            print(f"{'':16}{r[:150]}")
        if not (a.write or a.enforce or a.restore) or score is None or verdict == "OVERRIDE":
            continue
        fm, end = frontmatter(txt)
        fm = set_field(set_field(fm, "fit_score", f"{score:.2f}"), "fit_gate", verdict.lower())
        txt = f"---\n{fm}\n---\n" + txt[end:]
        if a.enforce and verdict == "FAIL" and field(fm, "status") not in PROTECTED:
            txt = enforce(p, txt, score, reasons, rows or [])
            print(f"{'':16}-> declined (status skipped)")
        if a.restore and verdict == "PASS":
            back = restore(txt)
            if back is not None:
                txt = back
                print(f"{'':16}-> restored (status candidate)")
        with open(p, "w", encoding="utf-8") as f:
            f.write(txt)
    print("\n" + "  ".join(f"{k} {v}" for k, v in sorted(tally.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
