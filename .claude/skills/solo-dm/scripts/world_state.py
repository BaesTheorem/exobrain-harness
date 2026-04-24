#!/usr/bin/env python3
"""World state dashboard generator.

Reads:
  - DB world_state table (date, location, weather, moon, recent_event)
  - Filesystem Factions/, NPCs/, Locations/ folders (frontmatter + first paragraph)
  - Recent events for "what happened lately" context

Writes:
  - <vault>/Solo DnD/<Campaign>/World state.md

Usage:
  world_state.py export --slug theory-of-magic

The "## Curated threads" section (if present in the existing World state.md) is
PRESERVED across regenerations — the script only rewrites the auto-generated
sections. Put anything hand-curated inside that section.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HARNESS_ROOT = Path("/Users/alexhedtke/Documents/Exobrain harness")
DATA_ROOT = HARNESS_ROOT / "data/solo-dm"
VAULT_ROOT = Path("/Users/alexhedtke/Documents/Exobrain/Areas/Adventure & Creativity/Solo DnD")

# Campaign-folder name is controlled by the DB's campaigns table.
# For now, hardcode the mapping for theory-of-magic; add others as needed.
SLUG_TO_FOLDER = {
    "theory-of-magic": "Theory of Magic",
}

# Marker used to separate auto-generated content from curated content.
CURATED_MARKER = "## Curated threads"


def _conn(slug: str) -> sqlite3.Connection:
    db = DATA_ROOT / slug / "state.sqlite"
    if not db.exists():
        sys.exit(f"no db for slug {slug!r}")
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c


def _load_world_keys(c: sqlite3.Connection) -> dict:
    """Return {key: value} from world_state. value is raw string; JSON-decoded
    for known structured keys."""
    rows = c.execute("SELECT key, value FROM world_state").fetchall()
    out = {}
    for r in rows:
        k, v = r["key"], r["value"]
        if k in ("map_markers", "map_calibration", "pc_position", "residuum_theory_canon"):
            try:
                out[k] = json.loads(v)
            except Exception:
                out[k] = v
        else:
            out[k] = v
    return out


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text). Very small YAML-ish parser that
    handles flat key: value lines. Does not attempt full YAML."""
    try:
        text = path.read_text()
    except Exception:
        return {}, ""
    if not text.startswith("---"):
        return {}, text
    # Find closing ---
    m = re.search(r"^---\n(.*?)\n---\n?(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    raw_fm, body = m.group(1), m.group(2)
    fm = {}
    for line in raw_fm.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        # Strip quotes
        if v.startswith(("'", '"')) and v.endswith(("'", '"')) and len(v) >= 2:
            v = v[1:-1]
        fm[k] = v
    return fm, body


def _scan_folder(folder: Path) -> list[dict]:
    """Return list of {name, path, fm} for each .md file in folder."""
    if not folder.exists():
        return []
    entries = []
    for p in sorted(folder.glob("*.md")):
        fm, _ = _parse_frontmatter(p)
        entries.append({
            "name": p.stem,
            "path": p,
            "fm": fm,
        })
    return entries


def _preserve_curated(existing_path: Path) -> str:
    """Read the existing World state.md and return the curated section if
    present, else empty string. The curated section is everything from
    `## Curated threads` (as a header at line-start) to end of file.

    Uses regex with MULTILINE to avoid matching the marker inside the
    backtick-quoted intro-note.
    """
    if not existing_path.exists():
        return ""
    text = existing_path.read_text()
    m = re.search(r"^" + re.escape(CURATED_MARKER) + r"\s*$", text, re.MULTILINE)
    if not m:
        return ""
    return text[m.start():]


def _format_npc_line(npc: dict) -> str:
    fm = npc["fm"]
    name = npc["name"]
    disposition = fm.get("disposition", "")
    role = fm.get("role", "")
    last_seen = fm.get("last_seen", "")
    parts = []
    if role:
        parts.append(role)
    if last_seen:
        parts.append(f"last seen {last_seen}")
    suffix = f" — {' · '.join(parts)}" if parts else ""
    dispo_badge = f" *[{disposition}]*" if disposition else ""
    return f"- [[NPCs/{name}]]{dispo_badge}{suffix}"


def _format_faction_line(fac: dict) -> str:
    fm = fac["fm"]
    name = fac["name"]
    posture = fm.get("posture", "")
    tier = fm.get("tier", "")
    threat = fm.get("threat_level", "")
    parts = []
    if tier:
        parts.append(tier)
    if threat:
        parts.append(f"threat: {threat}")
    if posture:
        parts.append(posture[:80] + ("…" if len(posture) > 80 else ""))
    suffix = f" — {' · '.join(parts)}" if parts else ""
    return f"- [[Factions/{name}]]{suffix}"


def _format_location_line(loc: dict) -> str:
    fm = loc["fm"]
    name = loc["name"]
    region = fm.get("region", "")
    suffix = f" — {region}" if region else ""
    return f"- [[Locations/{name}]]{suffix}"


def _group_npcs_by_disposition(npcs: list[dict]) -> dict[str, list[dict]]:
    """Bucket NPCs by disposition keyword in frontmatter.

    Check deceased/dormant FIRST based on role (not disposition — disposition
    text may reference 'posthumous' authorship credit or similar without
    meaning the NPC is dead)."""
    buckets = {"ally": [], "intimate": [], "neutral": [], "hostile": [], "dormant": [], "unknown": []}
    for n in npcs:
        fm = n["fm"]
        d = (fm.get("disposition") or "").lower()
        role = (fm.get("role") or "").lower()
        status = (fm.get("status") or "").lower()

        # Explicit status field wins
        if status:
            if status in ("deceased", "dormant"):
                buckets["dormant"].append(n)
                continue
            if status in ("captured", "hostile"):
                buckets["hostile"].append(n)
                continue
            if status in ("intimate", "lover"):
                buckets["intimate"].append(n)
                continue
            if status in ("ally", "allied"):
                buckets["ally"].append(n)
                continue

        # Role-based deceased detection (doesn't false-positive on "posthumous authorship")
        if role.startswith("late ") or "(deceased)" in role or " deceased" in role:
            buckets["dormant"].append(n)
            continue

        # Disposition-based bucketing
        if any(k in d for k in ["hostile", "enemy", "captured", "imprisoned"]):
            buckets["hostile"].append(n)
        elif any(k in d for k in ["intimate", "lover"]):
            buckets["intimate"].append(n)
        elif "dormant" in d:
            buckets["dormant"].append(n)
        elif any(k in d for k in ["ally", "friendly", "supportive", "cooperating", "collaborator"]):
            buckets["ally"].append(n)
        elif any(k in d for k in ["open", "peer", "warm", "professional", "scholarly", "engaged"]):
            buckets["ally"].append(n)  # loosely ally-adjacent
        elif d:
            buckets["neutral"].append(n)
        else:
            buckets["unknown"].append(n)
    return buckets


def export(slug: str) -> Path:
    if slug not in SLUG_TO_FOLDER:
        sys.exit(f"unknown slug {slug!r} — add to SLUG_TO_FOLDER")
    campaign_folder = VAULT_ROOT / SLUG_TO_FOLDER[slug]
    if not campaign_folder.exists():
        sys.exit(f"campaign folder not found: {campaign_folder}")

    c = _conn(slug)
    ws = _load_world_keys(c)

    factions = _scan_folder(campaign_folder / "Factions")
    npcs = _scan_folder(campaign_folder / "NPCs")
    locations = _scan_folder(campaign_folder / "Locations")

    out_path = campaign_folder / "World state.md"
    curated = _preserve_curated(out_path)

    now_stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = []
    lines.append("# World state")
    lines.append("")
    lines.append(f"*Auto-generated by `world_state.py` — regenerate with "
                 f"`python3 {HARNESS_ROOT}/.claude/skills/solo-dm/scripts/world_state.py export --slug {slug}`. "
                 f"Edit the individual faction/NPC/location notes; do not edit the auto sections — they will be overwritten. "
                 f"Curated content goes below the `{CURATED_MARKER}` marker.*")
    lines.append("")
    lines.append(f"Last regenerated: {now_stamp}")
    lines.append("")

    # Now section
    lines.append("## Now")
    lines.append("")
    lines.append(f"- **Date**: {ws.get('in_game_date', '—')}")
    lines.append(f"- **Location**: {ws.get('current_location', '—')}")
    lines.append(f"- **Weather**: {ws.get('weather', '—')}")
    lines.append(f"- **Season**: {ws.get('season', '—')}")
    lines.append(f"- **Moon**: {ws.get('moon_phase', '—')}")
    if ws.get("recent_event"):
        lines.append(f"- **Recent regional event**: {ws['recent_event']}")
    lines.append("")
    lines.append("Character sheet: [[Characters/Charles yn Hakim el Xander]]")
    lines.append("")

    # Factions
    lines.append("## Factions")
    lines.append("")
    if factions:
        for f in factions:
            lines.append(_format_faction_line(f))
    else:
        lines.append("*(no faction notes yet)*")
    lines.append("")

    # NPCs grouped by disposition
    lines.append("## NPCs")
    lines.append("")
    buckets = _group_npcs_by_disposition(npcs)
    for label, key in [
        ("Allies / friendly", "ally"),
        ("Intimate / lovers", "intimate"),
        ("Neutral", "neutral"),
        ("Hostile / captured", "hostile"),
        ("Dormant / deceased", "dormant"),
        ("Unclassified", "unknown"),
    ]:
        if not buckets[key]:
            continue
        lines.append(f"### {label}")
        for n in buckets[key]:
            lines.append(_format_npc_line(n))
        lines.append("")

    # Locations
    lines.append("## Locations")
    lines.append("")
    if locations:
        for l in locations:
            lines.append(_format_location_line(l))
    else:
        lines.append("*(no location notes yet)*")
    lines.append("")

    # Curated section (preserve or seed)
    if curated:
        lines.append(curated.rstrip())
    else:
        lines.append(CURATED_MARKER)
        lines.append("")
        lines.append("*Hand-curated plot threads, open questions, and pending appointments go here. "
                     "This section is preserved across `world_state.py export` runs.*")
        lines.append("")

    out_path.write_text("\n".join(lines) + "\n")
    c.close()
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export", help="regenerate World state.md from DB + filesystem")
    e.add_argument("--slug", required=True)
    args = p.parse_args()
    if args.cmd == "export":
        path = export(args.slug)
        print(json.dumps({"ok": True, "path": str(path)}))


if __name__ == "__main__":
    main()
