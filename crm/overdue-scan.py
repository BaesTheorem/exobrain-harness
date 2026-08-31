#!/usr/bin/env python3
"""Scan People/ notes and report who is overdue for contact.

Reads CRM frontmatter (category, frequency, last_contact) from every note in the
People/ directory and computes overdue status per the /crm skill's rule:
    days_since = today - last_contact
    overdue if days_since > frequency

Notes with category "null" are reference-only and are skipped.

INVARIANTS
- Never writes to the vault. Read-only by construction.
- A note missing last_contact or frequency is reported as "incomplete", not
  silently dropped -- a missing field is a data gap worth seeing, not an OK.
"""
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import sys

PEOPLE = pathlib.Path(
    "/Users/alexhedtke/Exobrain/Areas/Relationships & Community/People"
)
FM = re.compile(r"\A---\n(.*?)\n---", re.S)


def field(block: str, key: str) -> str | None:
    m = re.search(rf"^{key}:\s*(.*?)\s*$", block, re.M)
    if not m:
        return None
    v = m.group(1).strip().strip("\"'")
    return v or None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--all", action="store_true", help="include non-overdue contacts")
    args = ap.parse_args()
    today = dt.date.fromisoformat(args.today)

    overdue, incomplete = [], []
    for p in sorted(PEOPLE.glob("*.md")):
        m = FM.match(p.read_text(encoding="utf-8", errors="replace"))
        if not m:
            continue
        block = m.group(1)
        cat = field(block, "category")
        if not cat or cat.lower() == "null":
            continue
        freq, last = field(block, "frequency"), field(block, "last_contact")
        if not freq or not last:
            incomplete.append((p.stem, cat, freq, last))
            continue
        try:
            days = (today - dt.date.fromisoformat(last[:10])).days
            n = int(re.sub(r"\D", "", freq))
        except ValueError:
            incomplete.append((p.stem, cat, freq, last))
            continue
        (overdue.append((days - n, p.stem, cat, days, n))
         if days > n or args.all else None)

    overdue.sort(key=lambda r: (-r[0], r[2]))
    print(f"# CRM overdue scan -- {today}\n")
    print(f"{len(overdue)} overdue, {len(incomplete)} with incomplete frontmatter\n")
    for by, name, cat, days, n in overdue:
        print(f"  {by:+4d}d  {name:<28} cat {cat}  last contact {days}d ago (every {n}d)")
    if incomplete:
        print("\n## Incomplete frontmatter (cannot compute)")
        for name, cat, freq, last in incomplete:
            print(f"  {name:<28} cat={cat} frequency={freq} last_contact={last}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
