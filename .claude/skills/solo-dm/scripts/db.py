#!/usr/bin/env python3
"""Solo DM database layer.

Canonical state for the solo-dm skill. All writes flow through this module so
invariants (append-only events, turns sealed after roll, retcon discipline)
are enforced in one place.

CLI surface (invoked by the skill):
    db.py init --slug <slug> --name "<Name>" --vault "<path>"
    db.py open-session --slug <slug>
    db.py close-session --slug <slug>
    db.py open-scene --slug <slug> --name "<name>" --goals-json <json>
    db.py close-scene --slug <slug>
    db.py commit-turn --slug <slug> --actor <id|name> --action "<text>" \
        --classification <c> [--target-number N] [--advantage adv|dis|none] \
        [--reasoning "<text>"] [--roc-original-dc N --roc-reason "<text>"]
    db.py append-event --slug <slug> --type <t> --data-json <json> [--turn-id N]
    db.py add-character --slug <slug> --kind pc|named_npc|mook --name <n> \
        --tier opus|sonnet|haiku --sheet-json <json>
    db.py update-character --slug <slug> --id N --json <partial>
    db.py add-memory --slug <slug> --character-id N --fact "<t>" [--salience 3]
    db.py promote --slug <slug> --character-id N --reason "<text>"
    db.py query <sql>    # read-only; rejects non-SELECT
    db.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

HARNESS_ROOT = Path("/Users/alexhedtke/Documents/Exobrain harness")
SCHEMA_PATH = HARNESS_ROOT / ".claude/skills/solo-dm/data/schema.sql"
DATA_ROOT = HARNESS_ROOT / "data/solo-dm"


def campaign_dir(slug: str) -> Path:
    return DATA_ROOT / slug


def db_path(slug: str) -> Path:
    return campaign_dir(slug) / "state.sqlite"


def connect(slug: str) -> sqlite3.Connection:
    path = db_path(slug)
    if not path.exists():
        sys.exit(f"no db for slug {slug!r}: {path}")
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_campaign(slug: str, name: str, vault_path: str) -> None:
    d = campaign_dir(slug)
    (d / "sessions").mkdir(parents=True, exist_ok=True)
    path = db_path(slug)
    fresh = not path.exists()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_PATH.read_text())
    if fresh:
        conn.execute(
            "INSERT INTO campaigns (slug, name, vault_path) VALUES (?,?,?)",
            (slug, name, vault_path),
        )
    conn.commit()
    conn.close()
    print(json.dumps({"ok": True, "db": str(path), "fresh": fresh}))


def _campaign_id(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM campaigns LIMIT 1").fetchone()
    if row is None:
        sys.exit("campaign row missing")
    return row["id"]


def open_session(slug: str) -> None:
    conn = connect(slug)
    cid = _campaign_id(conn)
    row = conn.execute(
        "SELECT COALESCE(MAX(number),0)+1 AS n FROM sessions WHERE campaign_id=?",
        (cid,),
    ).fetchone()
    n = row["n"]
    cur = conn.execute(
        "INSERT INTO sessions (campaign_id, number) VALUES (?,?)", (cid, n)
    )
    sid = cur.lastrowid
    conn.execute(
        "INSERT INTO events (session_id, type, data_json) VALUES (?,?,?)",
        (sid, "session_open", json.dumps({"number": n})),
    )
    conn.commit()
    jsonl = campaign_dir(slug) / "sessions" / f"Session-{n}.jsonl"
    jsonl.touch()
    print(json.dumps({"ok": True, "session_id": sid, "number": n, "jsonl": str(jsonl)}))


def close_session(slug: str) -> None:
    conn = connect(slug)
    sid = _open_session_id(conn)
    conn.execute("UPDATE sessions SET ended_at=datetime('now') WHERE id=?", (sid,))
    conn.execute(
        "INSERT INTO events (session_id, type, data_json) VALUES (?,?,?)",
        (sid, "session_close", "{}"),
    )
    conn.commit()
    print(json.dumps({"ok": True, "session_id": sid}))


def _open_session_id(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        sys.exit("no open session")
    return row["id"]


def _open_scene_id(conn: sqlite3.Connection, session_id: int) -> int | None:
    row = conn.execute(
        "SELECT id FROM scenes WHERE session_id=? AND closed_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return row["id"] if row else None


def open_scene(slug: str, name: str, location_id: int | None, goals_json: str) -> None:
    conn = connect(slug)
    sid = _open_session_id(conn)
    row = conn.execute(
        "SELECT COALESCE(MAX(ord),0)+1 AS n FROM scenes WHERE session_id=?", (sid,)
    ).fetchone()
    json.loads(goals_json)  # validate
    cur = conn.execute(
        "INSERT INTO scenes (session_id, ord, name, location_id, npc_goals_json) "
        "VALUES (?,?,?,?,?)",
        (sid, row["n"], name, location_id, goals_json),
    )
    scene_id = cur.lastrowid
    conn.execute(
        "INSERT INTO events (session_id, type, data_json) VALUES (?,?,?)",
        (sid, "scene_open", json.dumps({"scene_id": scene_id, "name": name})),
    )
    conn.commit()
    print(json.dumps({"ok": True, "scene_id": scene_id}))


def close_scene(slug: str, summary: str | None) -> None:
    conn = connect(slug)
    sid = _open_session_id(conn)
    scene_id = _open_scene_id(conn, sid)
    if scene_id is None:
        sys.exit("no open scene")
    conn.execute(
        "UPDATE scenes SET closed_at=datetime('now'), summary=? WHERE id=?",
        (summary, scene_id),
    )
    conn.execute(
        "INSERT INTO events (session_id, type, data_json) VALUES (?,?,?)",
        (sid, "scene_close", json.dumps({"scene_id": scene_id})),
    )
    conn.commit()
    print(json.dumps({"ok": True, "scene_id": scene_id}))


def resolve_actor(conn: sqlite3.Connection, actor: str) -> int | None:
    if actor is None or actor == "":
        return None
    if actor.isdigit():
        return int(actor)
    row = conn.execute(
        "SELECT id FROM characters WHERE campaign_id=? AND name=? LIMIT 1",
        (_campaign_id(conn), actor),
    ).fetchone()
    if row is None:
        sys.exit(f"unknown actor: {actor!r}")
    return row["id"]


def commit_turn(args: argparse.Namespace) -> None:
    conn = connect(args.slug)
    sid = _open_session_id(conn)
    scene_id = _open_scene_id(conn, sid)
    actor_id = resolve_actor(conn, args.actor) if args.actor else None
    row = conn.execute(
        "SELECT COALESCE(MAX(ord),0)+1 AS n FROM turns WHERE session_id=?", (sid,)
    ).fetchone()
    cur = conn.execute(
        "INSERT INTO turns (session_id, scene_id, ord, actor_character_id, "
        "action_text, classification, target_number, advantage, reasoning, "
        "rule_of_cool_original_dc, rule_of_cool_reason) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            sid,
            scene_id,
            row["n"],
            actor_id,
            args.action,
            args.classification,
            args.target_number,
            args.advantage,
            args.reasoning,
            args.roc_original_dc,
            args.roc_reason,
        ),
    )
    turn_id = cur.lastrowid
    conn.commit()
    print(
        json.dumps(
            {
                "ok": True,
                "turn_id": turn_id,
                "ord": row["n"],
                "session_id": sid,
                "scene_id": scene_id,
            }
        )
    )


def append_event(
    slug: str, type_: str, data_json: str, turn_id: int | None
) -> None:
    json.loads(data_json)  # validate
    conn = connect(slug)
    sid = _open_session_id(conn)
    cur = conn.execute(
        "INSERT INTO events (session_id, turn_id, type, data_json) VALUES (?,?,?,?)",
        (sid, turn_id, type_, data_json),
    )
    conn.commit()
    print(json.dumps({"ok": True, "event_id": cur.lastrowid}))


def add_character(args: argparse.Namespace) -> None:
    conn = connect(args.slug)
    json.loads(args.sheet_json)  # validate
    sheet = json.loads(args.sheet_json)
    hp = sheet.get("hp_max") or sheet.get("hp_current")
    cur = conn.execute(
        "INSERT INTO characters (campaign_id, name, kind, model_tier, sheet_json, "
        "current_hp) VALUES (?,?,?,?,?,?)",
        (_campaign_id(conn), args.name, args.kind, args.tier, args.sheet_json, hp),
    )
    conn.commit()
    print(json.dumps({"ok": True, "character_id": cur.lastrowid}))


def update_character(slug: str, cid: int, partial_json: str) -> None:
    patch = json.loads(partial_json)
    conn = connect(slug)
    row = conn.execute(
        "SELECT sheet_json, current_hp, temp_hp, conditions_json FROM characters WHERE id=?",
        (cid,),
    ).fetchone()
    if row is None:
        sys.exit(f"no character id {cid}")
    sheet = json.loads(row["sheet_json"])
    # deep-merge one level
    for k, v in patch.get("sheet", {}).items():
        if isinstance(v, dict) and isinstance(sheet.get(k), dict):
            sheet[k].update(v)
        else:
            sheet[k] = v
    fields = ["sheet_json=?"]
    vals: list = [json.dumps(sheet)]
    for k in ("current_hp", "temp_hp", "conditions_json"):
        if k in patch:
            fields.append(f"{k}=?")
            val = patch[k]
            if k == "conditions_json" and not isinstance(val, str):
                val = json.dumps(val)
            vals.append(val)
    vals.append(cid)
    conn.execute(f"UPDATE characters SET {', '.join(fields)} WHERE id=?", vals)
    conn.commit()
    print(json.dumps({"ok": True, "character_id": cid}))


def add_memory(slug: str, cid: int, fact: str, salience: int, turn_id: int | None) -> None:
    conn = connect(slug)
    cur = conn.execute(
        "INSERT INTO npc_memory (character_id, fact, salience, learned_in_turn_id) "
        "VALUES (?,?,?,?)",
        (cid, fact, salience, turn_id),
    )
    conn.commit()
    print(json.dumps({"ok": True, "memory_id": cur.lastrowid}))


def promote(slug: str, cid: int, reason: str, turn_id: int | None) -> None:
    conn = connect(slug)
    row = conn.execute(
        "SELECT kind, model_tier FROM characters WHERE id=?", (cid,)
    ).fetchone()
    if row is None:
        sys.exit(f"no character id {cid}")
    if row["kind"] != "mook":
        sys.exit(f"character is {row['kind']}, not a mook — cannot promote")
    conn.execute(
        "UPDATE characters SET kind='named_npc', model_tier='sonnet', "
        "promoted_from_mook=1, promotion_reason=?, promotion_turn_id=? WHERE id=?",
        (reason, turn_id, cid),
    )
    sid = _open_session_id(conn)
    conn.execute(
        "INSERT INTO events (session_id, turn_id, type, data_json) VALUES (?,?,?,?)",
        (sid, turn_id, "npc_promotion", json.dumps({"character_id": cid, "reason": reason})),
    )
    conn.commit()
    print(json.dumps({"ok": True, "character_id": cid}))


def query(slug: str, sql: str) -> None:
    lowered = sql.strip().lower()
    if not lowered.startswith("select") and not lowered.startswith("with"):
        sys.exit("query is read-only (SELECT/WITH only)")
    conn = connect(slug)
    rows = [dict(r) for r in conn.execute(sql).fetchall()]
    print(json.dumps(rows, indent=2))


def selftest() -> None:
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp(prefix="solo-dm-test-"))
    try:
        global DATA_ROOT
        DATA_ROOT = tmp
        init_campaign("test", "Testing", str(tmp / "vault"))
        open_session("test")
        open_scene("test", "opening", None, '[]')
        conn = connect("test")
        # add a PC
        pc_sheet = {"name": "Test", "hp_max": 10, "hp_current": 10, "ac": 14}
        conn.execute(
            "INSERT INTO characters (campaign_id, name, kind, model_tier, sheet_json, "
            "current_hp) VALUES (?,?,?,?,?,?)",
            (1, "Tester", "pc", "opus", json.dumps(pc_sheet), 10),
        )
        conn.commit()
        # commit a turn
        cur = conn.execute(
            "INSERT INTO turns (session_id, scene_id, ord, actor_character_id, "
            "action_text, classification, target_number) VALUES (?,?,?,?,?,?,?)",
            (1, 1, 1, 1, "attack goblin", "attack", 15),
        )
        tid = cur.lastrowid
        conn.execute(
            "INSERT INTO rolls (turn_id, spec, rolls_json, total, outcome) "
            "VALUES (?,?,?,?,?)",
            (tid, "1d20+5", "[18]", 18, "pass"),
        )
        conn.commit()
        # sealing: should fail to update turn
        try:
            conn.execute("UPDATE turns SET target_number=99 WHERE id=?", (tid,))
            conn.commit()
            raise SystemExit("SEAL FAILED: turn was editable after roll")
        except sqlite3.IntegrityError:
            pass
        # events are append-only
        conn.execute(
            "INSERT INTO events (session_id, type, data_json) VALUES (?,?,?)",
            (1, "damage", json.dumps({"amount": 4})),
        )
        conn.commit()
        try:
            conn.execute("UPDATE events SET type='xp'")
            conn.commit()
            raise SystemExit("EVENT UPDATE allowed (should be blocked)")
        except sqlite3.IntegrityError:
            pass
        try:
            conn.execute("DELETE FROM events")
            conn.commit()
            raise SystemExit("EVENT DELETE allowed (should be blocked)")
        except sqlite3.IntegrityError:
            pass
        conn.close()
        print("db.py selftest: OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init"); s.add_argument("--slug", required=True)
    s.add_argument("--name", required=True); s.add_argument("--vault", required=True)

    s = sub.add_parser("open-session"); s.add_argument("--slug", required=True)
    s = sub.add_parser("close-session"); s.add_argument("--slug", required=True)

    s = sub.add_parser("open-scene"); s.add_argument("--slug", required=True)
    s.add_argument("--name", required=True); s.add_argument("--location-id", type=int)
    s.add_argument("--goals-json", default="[]")

    s = sub.add_parser("close-scene"); s.add_argument("--slug", required=True)
    s.add_argument("--summary")

    s = sub.add_parser("commit-turn"); s.add_argument("--slug", required=True)
    s.add_argument("--actor"); s.add_argument("--action", required=True)
    s.add_argument("--classification", required=True,
                   choices=["narrative","check","attack","save","social","damage_dealt"])
    s.add_argument("--target-number", type=int)
    s.add_argument("--advantage", default="none", choices=["none","adv","dis"])
    s.add_argument("--reasoning")
    s.add_argument("--roc-original-dc", type=int)
    s.add_argument("--roc-reason")

    s = sub.add_parser("append-event"); s.add_argument("--slug", required=True)
    s.add_argument("--type", required=True, dest="type_")
    s.add_argument("--data-json", default="{}")
    s.add_argument("--turn-id", type=int)

    s = sub.add_parser("add-character"); s.add_argument("--slug", required=True)
    s.add_argument("--kind", required=True, choices=["pc","named_npc","mook"])
    s.add_argument("--name"); s.add_argument("--tier", choices=["opus","sonnet","haiku"])
    s.add_argument("--sheet-json", default="{}")

    s = sub.add_parser("update-character"); s.add_argument("--slug", required=True)
    s.add_argument("--id", type=int, required=True); s.add_argument("--json", required=True)

    s = sub.add_parser("add-memory"); s.add_argument("--slug", required=True)
    s.add_argument("--character-id", type=int, required=True); s.add_argument("--fact", required=True)
    s.add_argument("--salience", type=int, default=3); s.add_argument("--turn-id", type=int)

    s = sub.add_parser("promote"); s.add_argument("--slug", required=True)
    s.add_argument("--character-id", type=int, required=True)
    s.add_argument("--reason", required=True); s.add_argument("--turn-id", type=int)

    s = sub.add_parser("query"); s.add_argument("--slug", required=True); s.add_argument("sql")

    sub.add_parser("selftest")

    args = p.parse_args()

    if args.cmd == "init":
        init_campaign(args.slug, args.name, args.vault)
    elif args.cmd == "open-session":
        open_session(args.slug)
    elif args.cmd == "close-session":
        close_session(args.slug)
    elif args.cmd == "open-scene":
        open_scene(args.slug, args.name, args.location_id, args.goals_json)
    elif args.cmd == "close-scene":
        close_scene(args.slug, args.summary)
    elif args.cmd == "commit-turn":
        commit_turn(args)
    elif args.cmd == "append-event":
        append_event(args.slug, args.type_, args.data_json, args.turn_id)
    elif args.cmd == "add-character":
        add_character(args)
    elif args.cmd == "update-character":
        update_character(args.slug, args.id, args.json)
    elif args.cmd == "add-memory":
        add_memory(args.slug, args.character_id, args.fact, args.salience, args.turn_id)
    elif args.cmd == "promote":
        promote(args.slug, args.character_id, args.reason, args.turn_id)
    elif args.cmd == "query":
        query(args.slug, args.sql)
    elif args.cmd == "selftest":
        selftest()


if __name__ == "__main__":
    main()
