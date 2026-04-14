#!/usr/bin/env python3
"""Export Governance Map Obsidian notes to CSV for Google Sheets import."""

import csv
import os
import re
import sys
from pathlib import Path

VAULT = Path("/Users/alexhedtke/Documents/Exobrain")
MAP_DIR = VAULT / "Areas/Contribution & Impact/AI Governance & Safety/Governance Map"
OUTPUT = VAULT.parent / "Exobrain harness" / "exports" / "governance-map.csv"

TIER_LABELS = {
    1: "Tier 1: Can Stop Deployment",
    2: "Tier 2: Can Block Inputs",
    3: "Tier 3: Legal Obligations",
    4: "Tier 4: Norm Shapers",
    5: "Tier 5: Aspirational",
}

COLUMNS = [
    "Actor / Mechanism",
    "Power Tier",
    "Tier",
    "Type",
    "Layer",
    "Power",
    "Horizon",
    "Jurisdiction",
    "Enforcement",
    "Mechanism",
    "Notes",
    "URL",
]

PROP_MAP = {
    "Actor / Mechanism": "name",
    "Power Tier": "tier_label",
    "Tier": "tier",
    "Type": "actor_type",
    "Layer": "governance_layer",
    "Power": "power_level",
    "Horizon": "time_horizon",
    "Jurisdiction": "jurisdiction",
    "Enforcement": "enforcement",
    "Mechanism": "mechanism",
    "Notes": "notes",
    "URL": "url",
}


def parse_frontmatter(filepath: Path) -> dict:
    """Extract YAML frontmatter from an Obsidian note."""
    text = filepath.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}

    props = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Parse numeric tier
            if key == "tier":
                try:
                    value = int(value)
                except ValueError:
                    pass
            props[key] = value

    props["name"] = filepath.stem
    if isinstance(props.get("tier"), int):
        props["tier_label"] = TIER_LABELS.get(props["tier"], f"Tier {props['tier']}")

    return props


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    notes = sorted(MAP_DIR.glob("*.md"))
    if not notes:
        print(f"No .md files found in {MAP_DIR}", file=sys.stderr)
        sys.exit(1)

    rows = []
    for note in notes:
        props = parse_frontmatter(note)
        if not props:
            continue
        row = {col: props.get(PROP_MAP[col], "") for col in COLUMNS}
        rows.append(row)

    # Sort by tier (numeric), then by name
    rows.sort(key=lambda r: (r["Tier"] if isinstance(r["Tier"], int) else 99, r["Actor / Mechanism"]))

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} actors to {OUTPUT}")


if __name__ == "__main__":
    main()
