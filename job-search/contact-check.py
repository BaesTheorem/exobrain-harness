#!/usr/bin/env python3
"""Flag listing-note contacts whose current title was never read.

Contact research records people in a table with Name and Title columns. A row
whose Title cell is blank or a placeholder ("<Employer> employee", "role not read",
"unknown") means nobody opened that person's profile. On 2026-10-07 the warmest
contact on a candidate note was recorded with an employer and a former employer only;
their experience section named the role in one click.

Usage:
    contact-check.py                 audit every active job-listing note
    contact-check.py --note PATH     check one note (exit 1 on any hit)

INVARIANTS
- Read-only: never edits a note.
- Only tables whose header row has both a Name and a Title column are checked.
"""

import argparse
import os
import re
import sys

VAULT = "/Users/alexhedtke/Exobrain"
INACTIVE = {"closed", "withdrawn", "rejected", "skipped"}
PLACEHOLDER = re.compile(r"not read|unread|unknown|\btbd\b|pending|^\W*\?\W*$", re.I)
VAGUE = re.compile(r"\b(employee|staff|works? (here|there)|alum(na|nus|ni)?)\b", re.I)
ROLE = re.compile(
    r"analyst|manager|director|engineer|counsel|attorney|recruiter|specialist|"
    r"administrator|officer|lead\b|partner|associate|coordinator|consultant|"
    r"architect|head\b|\bvp\b|president|chief|ciso|\bcio\b|\bcto\b|technician|"
    r"sourcer|talent|scientist|developer|advisor|supervisor|intern\b|fellow\b",
    re.I,
)


def unread(title: str) -> bool:
    """A blank title, a placeholder, or an affiliation with no job title in it."""
    if not title or PLACEHOLDER.search(title):
        return True
    return bool(VAGUE.search(title)) and not ROLE.search(title)


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def check(path: str) -> list[str]:
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    hits, name_i, title_i = [], None, None
    for line in lines:
        if not line.lstrip().startswith("|"):
            name_i = title_i = None
            continue
        row = cells(line)
        if name_i is None or title_i is None:
            low = [c.lower() for c in row]
            ni = next((i for i, c in enumerate(low) if c == "name"), None)
            ti = next((i for i, c in enumerate(low) if c.startswith("title")), None)
            if ni is not None and ti is not None:
                name_i, title_i = ni, ti
            continue
        if set("".join(row)) <= set("-: "):
            continue
        if title_i >= len(row):
            continue
        title = row[title_i]
        if unread(title):
            hits.append("%s | %s" % (row[name_i] if name_i < len(row) else "?", title or "<blank>"))
    return hits


def active_notes() -> list[str]:
    out = []
    for root, dirs, files in os.walk(VAULT):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if not name.endswith(".md"):
                continue
            p = os.path.join(root, name)
            with open(p, encoding="utf-8", errors="replace") as f:
                head = f.read(1500)
            if not re.search(r"^type:\s*['\"]?job-listing\b", head, re.M):
                continue
            m = re.search(r"^status:\s*['\"]?(\w+)", head, re.M)
            if m and m.group(1) in INACTIVE:
                continue
            out.append(p)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--note")
    args = ap.parse_args()
    paths = [args.note] if args.note else active_notes()
    bad = 0
    for p in paths:
        hits = check(p)
        if hits:
            bad += 1
            print(os.path.basename(p)[:-3])
            for h in hits:
                print("   UNREAD  " + h)
    print("%d of %d notes have contacts with no title read" % (bad, len(paths)))
    return 1 if (args.note and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
