#!/usr/bin/env python3
"""SRD lookup for solo-dm.

Reads JSON from data/srd/ (vendored 2014 5e-bits SRD, MIT-licensed) and
data/extensions/ (user-supplied TCoE/XGtE/homebrew — not vendored).

    srd.py lookup monster "goblin"
    srd.py lookup spell "fireball"
    srd.py lookup condition "prone"
    srd.py list monsters
    srd.py list spells
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from functools import lru_cache

DATA = Path(__file__).resolve().parent.parent / "data"
SRD = DATA / "srd"
EXT = DATA / "extensions"

KIND_MAP = {
    "monster":   ("5e-SRD-Monsters.json",  "monster"),
    "spell":     ("5e-SRD-Spells.json",    "spell"),
    "condition": ("5e-SRD-Conditions.json","condition"),
    "rule":      ("5e-SRD-Rules.json",     "rule"),
    "rule-section": ("5e-SRD-Rule-Sections.json", "rule-section"),
    "equipment": ("5e-SRD-Equipment.json", "equipment"),
    "magic-item":("5e-SRD-Magic-Items.json","magic-item"),
    "feature":   ("5e-SRD-Features.json",  "feature"),
    "feat":      ("5e-SRD-Feats.json",     "feat"),
    "class":     ("5e-SRD-Classes.json",   "class"),
    "subclass":  ("5e-SRD-Subclasses.json","subclass"),
    "race":      ("5e-SRD-Races.json",     "race"),
    "subrace":   ("5e-SRD-Subraces.json",  "subrace"),
    "skill":     ("5e-SRD-Skills.json",    "skill"),
    "level":     ("5e-SRD-Levels.json",    "level"),
    "trait":     ("5e-SRD-Traits.json",    "trait"),
    "alignment": ("5e-SRD-Alignments.json","alignment"),
    "ability":   ("5e-SRD-Ability-Scores.json","ability"),
    "language":  ("5e-SRD-Languages.json", "language"),
    "damage":    ("5e-SRD-Damage-Types.json","damage"),
    "proficiency":("5e-SRD-Proficiencies.json","proficiency"),
    "background":("5e-SRD-Backgrounds.json","background"),
    "weapon-property":("5e-SRD-Weapon-Properties.json","weapon-property"),
    "magic-school":("5e-SRD-Magic-Schools.json","magic-school"),
}


@lru_cache(maxsize=None)
def _load_srd(kind: str) -> list[dict]:
    filename, _ = KIND_MAP[kind]
    path = SRD / filename
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _load_extensions(kind: str) -> list[dict]:
    out: list[dict] = []
    if not EXT.exists():
        return out
    _, kind_tag = KIND_MAP.get(kind, (None, kind))
    for f in EXT.glob("*.json"):
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        if isinstance(data, list):
            for item in data:
                if item.get("kind") == kind_tag or item.get("type") == kind_tag:
                    item = dict(item)
                    item["source"] = item.get("source") or f"extension:{f.name}"
                    out.append(item)
    return out


def lookup(kind: str, name: str) -> dict | None:
    if kind not in KIND_MAP:
        sys.exit(f"unknown kind: {kind!r}. Known: {', '.join(sorted(KIND_MAP))}")
    needle = name.lower().strip()
    for entry in _load_srd(kind):
        if entry.get("name", "").lower() == needle or entry.get("index", "") == needle:
            return entry
    # partial match fallback in SRD
    for entry in _load_srd(kind):
        if needle in entry.get("name", "").lower():
            return entry
    # extensions
    for entry in _load_extensions(kind):
        if entry.get("name", "").lower() == needle or entry.get("index", "") == needle:
            return entry
    return None


def list_kind(kind: str) -> list[str]:
    if kind not in KIND_MAP:
        sys.exit(f"unknown kind: {kind!r}. Known: {', '.join(sorted(KIND_MAP))}")
    names_srd = [e.get("name", "") for e in _load_srd(kind)]
    names_ext = [f"{e.get('name','')} (ext)" for e in _load_extensions(kind)]
    return sorted(names_srd + names_ext)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("lookup")
    s.add_argument("kind"); s.add_argument("name")

    s = sub.add_parser("list")
    s.add_argument("kind")

    args = p.parse_args()

    if args.cmd == "lookup":
        kind = args.kind.rstrip("s")
        kind = {"monster": "monster", "spell": "spell", "condition": "condition"}.get(kind, kind)
        res = lookup(kind, args.name)
        if res is None:
            print(json.dumps({"found": False, "kind": kind, "name": args.name,
                              "hint": "not in SRD or extensions — narrate as house_rule"}))
            sys.exit(2)
        print(json.dumps(res, indent=2))
    elif args.cmd == "list":
        kind = args.kind.rstrip("s")
        for n in list_kind(kind):
            print(n)


if __name__ == "__main__":
    main()
