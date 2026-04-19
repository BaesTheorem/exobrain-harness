#!/usr/bin/env python3
"""PC sheet mutations + markdown export.

Ergonomic wrappers over db.py for the most common turn-loop operations on a
player character. Every mutation appends a matching event so the DB is an
audit trail of damage/heal/slot-spend/condition changes.

    sheet.py damage   --slug <s> --id <c> --amount 7
    sheet.py heal     --slug <s> --id <c> --amount 5
    sheet.py temp-hp  --slug <s> --id <c> --amount 8
    sheet.py condition --slug <s> --id <c> --add prone
    sheet.py condition --slug <s> --id <c> --remove prone
    sheet.py spend-slot --slug <s> --id <c> --level 1
    sheet.py restore-slot --slug <s> --id <c> --level 1 --amount 1
    sheet.py concentration --slug <s> --id <c> --set "Produce Flame"
    sheet.py concentration --slug <s> --id <c> --clear
    sheet.py inventory --slug <s> --id <c> --add "Healing Potion:1"
    sheet.py inventory --slug <s> --id <c> --remove "Goodberry:1"
    sheet.py xp --slug <s> --id <c> --add 250
    sheet.py export --slug <s> --id <c>    # writes Characters/<name>.md
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HARNESS_ROOT = Path("/Users/alexhedtke/Documents/Exobrain harness")
DATA_ROOT = HARNESS_ROOT / "data/solo-dm"


def _conn(slug: str) -> sqlite3.Connection:
    db = DATA_ROOT / slug / "state.sqlite"
    if not db.exists():
        sys.exit(f"no db for slug {slug!r}")
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row
    return c


def _load(c: sqlite3.Connection, cid: int) -> dict:
    row = c.execute(
        "SELECT id, name, sheet_json, current_hp, temp_hp, conditions_json "
        "FROM characters WHERE id=?",
        (cid,),
    ).fetchone()
    if row is None:
        sys.exit(f"no character {cid}")
    return {
        "id": row["id"],
        "name": row["name"],
        "sheet": json.loads(row["sheet_json"] or "{}"),
        "current_hp": row["current_hp"] or 0,
        "temp_hp": row["temp_hp"] or 0,
        "conditions": json.loads(row["conditions_json"] or "[]"),
    }


def _save(
    c: sqlite3.Connection,
    cid: int,
    sheet: dict,
    hp: int,
    thp: int,
    conditions: list,
) -> None:
    c.execute(
        "UPDATE characters SET sheet_json=?, current_hp=?, temp_hp=?, conditions_json=? WHERE id=?",
        (json.dumps(sheet), hp, thp, json.dumps(conditions), cid),
    )
    c.commit()


def _event(c: sqlite3.Connection, type_: str, data: dict, turn_id: int | None = None) -> None:
    row = c.execute(
        "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return  # no open session; skip logging
    c.execute(
        "INSERT INTO events (session_id, turn_id, type, data_json) VALUES (?,?,?,?)",
        (row["id"], turn_id, type_, json.dumps(data)),
    )
    c.commit()


# --- Ops -------------------------------------------------------------------

def damage(slug: str, cid: int, amount: int, turn_id: int | None) -> None:
    c = _conn(slug)
    ch = _load(c, cid)
    thp = ch["temp_hp"]
    absorbed = min(amount, thp)
    thp -= absorbed
    remaining = amount - absorbed
    hp = max(0, ch["current_hp"] - remaining)
    _save(c, cid, ch["sheet"], hp, thp, ch["conditions"])
    _event(c, "damage", {"character_id": cid, "amount": amount, "absorbed_temp": absorbed,
                         "hp_after": hp, "temp_hp_after": thp}, turn_id)
    # Concentration check: damage of 10+ or half damage, whichever higher — DM's job. Log flag.
    conc = ch["sheet"].get("concentration")
    if conc and amount > 0:
        dc = max(10, amount // 2)
        _event(c, "note", {"flag": "concentration_check_needed", "dc": dc, "spell": conc,
                           "character_id": cid}, turn_id)
    print(json.dumps({"ok": True, "hp": hp, "temp_hp": thp,
                      "concentration_check_dc": (max(10, amount // 2) if conc else None)}))


def heal(slug: str, cid: int, amount: int, turn_id: int | None) -> None:
    c = _conn(slug)
    ch = _load(c, cid)
    hp_max = ch["sheet"].get("hp_max") or ch["current_hp"] + amount
    new_hp = min(hp_max, ch["current_hp"] + amount)
    _save(c, cid, ch["sheet"], new_hp, ch["temp_hp"], ch["conditions"])
    _event(c, "heal", {"character_id": cid, "amount": amount, "hp_after": new_hp}, turn_id)
    print(json.dumps({"ok": True, "hp": new_hp}))


def temp_hp(slug: str, cid: int, amount: int, turn_id: int | None) -> None:
    c = _conn(slug)
    ch = _load(c, cid)
    # Temp HP doesn't stack — take the higher.
    new_thp = max(ch["temp_hp"], amount)
    _save(c, cid, ch["sheet"], ch["current_hp"], new_thp, ch["conditions"])
    _event(c, "note", {"flag": "temp_hp_set", "character_id": cid,
                       "from": ch["temp_hp"], "to": new_thp}, turn_id)
    print(json.dumps({"ok": True, "temp_hp": new_thp}))


def condition(slug: str, cid: int, add: str | None, remove: str | None, turn_id: int | None) -> None:
    c = _conn(slug)
    ch = _load(c, cid)
    conds = list(ch["conditions"])
    if add:
        if add not in conds:
            conds.append(add)
        _event(c, "condition_add", {"character_id": cid, "condition": add}, turn_id)
    if remove:
        conds = [x for x in conds if x != remove]
        _event(c, "condition_remove", {"character_id": cid, "condition": remove}, turn_id)
    _save(c, cid, ch["sheet"], ch["current_hp"], ch["temp_hp"], conds)
    print(json.dumps({"ok": True, "conditions": conds}))


def spend_slot(slug: str, cid: int, level: int, turn_id: int | None) -> None:
    c = _conn(slug)
    ch = _load(c, cid)
    slots = ch["sheet"].setdefault("spell_slots", {})
    key = str(level)
    slot = slots.get(key, {})
    cur = slot.get("current", 0)
    if cur <= 0:
        sys.exit(f"no level-{level} slots remaining")
    slot["current"] = cur - 1
    slots[key] = slot
    _save(c, cid, ch["sheet"], ch["current_hp"], ch["temp_hp"], ch["conditions"])
    _event(c, "note", {"flag": "slot_spent", "character_id": cid, "level": level,
                       "remaining": slot["current"]}, turn_id)
    print(json.dumps({"ok": True, "level": level, "remaining": slot["current"]}))


def restore_slot(slug: str, cid: int, level: int, amount: int, turn_id: int | None) -> None:
    c = _conn(slug)
    ch = _load(c, cid)
    slots = ch["sheet"].setdefault("spell_slots", {})
    key = str(level)
    slot = slots.get(key, {"max": amount, "current": 0})
    slot["current"] = min(slot.get("max", amount), slot.get("current", 0) + amount)
    slots[key] = slot
    _save(c, cid, ch["sheet"], ch["current_hp"], ch["temp_hp"], ch["conditions"])
    print(json.dumps({"ok": True, "level": level, "current": slot["current"]}))


def concentration(slug: str, cid: int, set_: str | None, clear: bool, turn_id: int | None) -> None:
    c = _conn(slug)
    ch = _load(c, cid)
    if clear:
        ch["sheet"]["concentration"] = None
        _event(c, "note", {"flag": "concentration_cleared", "character_id": cid}, turn_id)
    elif set_:
        ch["sheet"]["concentration"] = set_
        _event(c, "note", {"flag": "concentration_set", "character_id": cid, "spell": set_}, turn_id)
    _save(c, cid, ch["sheet"], ch["current_hp"], ch["temp_hp"], ch["conditions"])
    print(json.dumps({"ok": True, "concentration": ch["sheet"].get("concentration")}))


def inventory(slug: str, cid: int, add: str | None, remove: str | None, turn_id: int | None) -> None:
    c = _conn(slug)
    ch = _load(c, cid)
    inv = ch["sheet"].setdefault("inventory", [])
    if add:
        name, qty = (add.split(":", 1) + ["1"])[:2]
        qty = int(qty)
        match = next((i for i in inv if i.get("name", "").lower() == name.lower()), None)
        if match:
            match["qty"] = match.get("qty", 1) + qty
        else:
            inv.append({"name": name, "qty": qty})
        _event(c, "loot", {"character_id": cid, "item": name, "qty": qty}, turn_id)
    if remove:
        name, qty = (remove.split(":", 1) + ["1"])[:2]
        qty = int(qty)
        match = next((i for i in inv if i.get("name", "").lower() == name.lower()), None)
        if match:
            match["qty"] = max(0, match.get("qty", 1) - qty)
            if match["qty"] == 0:
                inv.remove(match)
        _event(c, "note", {"flag": "item_consumed", "character_id": cid, "item": name, "qty": qty},
               turn_id)
    _save(c, cid, ch["sheet"], ch["current_hp"], ch["temp_hp"], ch["conditions"])
    print(json.dumps({"ok": True, "inventory": inv}))


def xp_add(slug: str, cid: int, amount: int, turn_id: int | None) -> None:
    c = _conn(slug)
    ch = _load(c, cid)
    cur = ch["sheet"].get("xp", 0)
    ch["sheet"]["xp"] = cur + amount
    _save(c, cid, ch["sheet"], ch["current_hp"], ch["temp_hp"], ch["conditions"])
    _event(c, "xp", {"character_id": cid, "amount": amount, "total": cur + amount}, turn_id)
    print(json.dumps({"ok": True, "xp": cur + amount}))


# --- Export ----------------------------------------------------------------

def _yaml_scalar(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace('"', '\\"')
    return f'"{s}"'


def _yaml_dump(obj, indent=0) -> str:
    out = []
    pad = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out.append(f"{pad}{k}:")
                out.append(_yaml_dump(v, indent + 1))
            else:
                out.append(f"{pad}{k}: {_yaml_scalar(v)}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                out.append(f"{pad}-")
                out.append(_yaml_dump(item, indent + 1))
            else:
                out.append(f"{pad}- {_yaml_scalar(item)}")
    else:
        out.append(f"{pad}{_yaml_scalar(obj)}")
    return "\n".join(line for line in out if line is not None)


def export(slug: str, cid: int) -> None:
    c = _conn(slug)
    ch = _load(c, cid)
    camp = c.execute("SELECT name, vault_path FROM campaigns LIMIT 1").fetchone()
    if not camp:
        sys.exit("no campaign row")
    vault = Path(camp["vault_path"])
    chars = vault / "Characters"
    chars.mkdir(parents=True, exist_ok=True)
    name = ch["name"] or f"Character-{cid}"
    path = chars / f"{name}.md"

    frontmatter = dict(ch["sheet"])
    frontmatter["name"] = name
    frontmatter["hp_current"] = ch["current_hp"]
    frontmatter["temp_hp"] = ch["temp_hp"]
    frontmatter["conditions"] = ch["conditions"]

    body_marker = "<!-- END_DM_MANAGED_FRONTMATTER -->"

    # Preserve user-written body below the marker if the file exists
    existing_body = ""
    if path.exists():
        text = path.read_text()
        if body_marker in text:
            existing_body = text.split(body_marker, 1)[1]
        else:
            # Old file or hand-written — don't clobber. Keep as backup.
            backup = path.with_suffix(".md.bak")
            backup.write_text(text)
            existing_body = "\n\n<!-- preserved body; previous file saved as .bak -->\n"

    ts = datetime.now(timezone.utc).isoformat()
    out = (
        "---\n"
        f"{_yaml_dump(frontmatter)}\n"
        "---\n"
        f"<!-- Solo DM managed frontmatter above. Last updated: {ts}. -->\n"
        f"{body_marker}\n"
        f"{existing_body}"
    )
    path.write_text(out)
    print(json.dumps({"ok": True, "path": str(path)}))


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    for name in ("damage", "heal", "temp-hp"):
        s = sub.add_parser(name)
        s.add_argument("--slug", required=True); s.add_argument("--id", type=int, required=True)
        s.add_argument("--amount", type=int, required=True); s.add_argument("--turn-id", type=int)

    s = sub.add_parser("condition")
    s.add_argument("--slug", required=True); s.add_argument("--id", type=int, required=True)
    s.add_argument("--add"); s.add_argument("--remove"); s.add_argument("--turn-id", type=int)

    for name in ("spend-slot", "restore-slot"):
        s = sub.add_parser(name)
        s.add_argument("--slug", required=True); s.add_argument("--id", type=int, required=True)
        s.add_argument("--level", type=int, required=True); s.add_argument("--turn-id", type=int)
        if name == "restore-slot":
            s.add_argument("--amount", type=int, default=1)

    s = sub.add_parser("concentration")
    s.add_argument("--slug", required=True); s.add_argument("--id", type=int, required=True)
    s.add_argument("--set", dest="set_"); s.add_argument("--clear", action="store_true")
    s.add_argument("--turn-id", type=int)

    s = sub.add_parser("inventory")
    s.add_argument("--slug", required=True); s.add_argument("--id", type=int, required=True)
    s.add_argument("--add"); s.add_argument("--remove"); s.add_argument("--turn-id", type=int)

    s = sub.add_parser("xp")
    s.add_argument("--slug", required=True); s.add_argument("--id", type=int, required=True)
    s.add_argument("--add", type=int, required=True); s.add_argument("--turn-id", type=int)

    s = sub.add_parser("export")
    s.add_argument("--slug", required=True); s.add_argument("--id", type=int, required=True)

    args = p.parse_args()
    if args.cmd == "damage":
        damage(args.slug, args.id, args.amount, args.turn_id)
    elif args.cmd == "heal":
        heal(args.slug, args.id, args.amount, args.turn_id)
    elif args.cmd == "temp-hp":
        temp_hp(args.slug, args.id, args.amount, args.turn_id)
    elif args.cmd == "condition":
        condition(args.slug, args.id, args.add, args.remove, args.turn_id)
    elif args.cmd == "spend-slot":
        spend_slot(args.slug, args.id, args.level, args.turn_id)
    elif args.cmd == "restore-slot":
        restore_slot(args.slug, args.id, args.level, args.amount, args.turn_id)
    elif args.cmd == "concentration":
        concentration(args.slug, args.id, args.set_, args.clear, args.turn_id)
    elif args.cmd == "inventory":
        inventory(args.slug, args.id, args.add, args.remove, args.turn_id)
    elif args.cmd == "xp":
        xp_add(args.slug, args.id, args.add, args.turn_id)
    elif args.cmd == "export":
        export(args.slug, args.id)


if __name__ == "__main__":
    main()
