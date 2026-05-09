#!/usr/bin/env python3
"""Reconcile job-listing frontmatter when status flags get out of sync.

Triggered when files in Projects/Get new job/Job Listings/ change. Logic:

- applied=true AND status=candidate
  → set status=applied AND application_date=today (if empty)
  This is the canonical "Alex just flipped the checkbox" case.

- status=rejected AND no rejection_date
  → set rejection_date=today
  Captures rejection-email confirmations.

We intentionally do NOT stamp application_date when status is already
{applied, rejected, withdrawn, closed, interviewing, offer} — those records
either have a real historical date already, or had an unknown date at
migration time that should not be backfilled with today's date.

Idempotent: safe to run on every file change, or as a periodic safety net.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

LISTINGS = Path(
    "/Users/alexhedtke/Documents/Exobrain/Projects/Get new job/Job Listings"
)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str, str]:
    """Return (fields, raw_yaml_block, body). Preserves original line order via dict."""
    if not text.startswith("---\n"):
        return {}, "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, "", text
    yaml_block = text[4:end]
    body = text[end + 5 :]
    fields: dict[str, str] = {}
    for line in yaml_block.split("\n"):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2)
    return fields, yaml_block, body


def update_yaml_block(yaml_block: str, updates: dict[str, str]) -> str:
    """Surgically update lines in the YAML block; preserve everything else."""
    lines = yaml_block.split("\n")
    keys_set: set[str] = set()
    for i, line in enumerate(lines):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m and m.group(1) in updates:
            key = m.group(1)
            new_value = updates[key]
            lines[i] = f"{key}: {new_value}"
            keys_set.add(key)
    # Append any keys that didn't exist
    for key, value in updates.items():
        if key not in keys_set:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def reconcile_file(path: Path, today: str) -> list[str]:
    """Return list of human-readable change descriptions, or [] if no changes."""
    text = path.read_text()
    fields, yaml_block, body = parse_frontmatter(text)
    if fields.get("type") != "job-listing":
        return []

    updates: dict[str, str] = {}
    changes: list[str] = []

    applied = fields.get("applied", "").strip().lower() == "true"
    status = fields.get("status", "").strip().strip('"').strip("'")
    application_date = fields.get("application_date", "").strip()
    rejection_date = fields.get("rejection_date", "").strip()

    # Rule 1: candidate→applied transition. When applied=true and status is
    # still 'candidate', this is the "Alex just flipped the checkbox" case.
    # Promote status, AND stamp application_date if empty.
    if applied and status == "candidate":
        updates["status"] = "applied"
        changes.append("set status=applied")
        if not application_date:
            updates["application_date"] = today
            changes.append(f"set application_date={today}")

    # Rule 2: status=rejected with empty rejection_date → set today.
    if status == "rejected" and not rejection_date:
        updates["rejection_date"] = today
        changes.append(f"set rejection_date={today}")

    # We deliberately do NOT auto-stamp application_date when applied=true but
    # status is already in {applied, rejected, withdrawn, closed, interviewing,
    # offer}. Those records either have a real historical date already, or
    # carried an unknown date through migration that should not be backfilled
    # with today's date.

    if not updates:
        return []

    new_yaml = update_yaml_block(yaml_block, updates)
    new_text = f"---\n{new_yaml}\n---\n{body}"
    path.write_text(new_text)
    return [f"{path.name}: {', '.join(changes)}"]


def main() -> int:
    if not LISTINGS.is_dir():
        print(f"ERROR: listings folder not found: {LISTINGS}", file=sys.stderr)
        return 1
    today = date.today().isoformat()
    all_changes: list[str] = []
    for md in sorted(LISTINGS.glob("*.md")):
        all_changes.extend(reconcile_file(md, today))
    if all_changes:
        for line in all_changes:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
