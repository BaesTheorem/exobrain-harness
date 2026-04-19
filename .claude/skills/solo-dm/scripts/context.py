#!/usr/bin/env python3
"""Per-turn context slice builder for solo-dm.

The main DM agent does NOT hold the campaign log. It calls this before each
turn to get a lean JSON bundle: current scene, PC sheet, last ~10 turns of
the active scene, active conditions, quests, world state, Alex's Notes,
and any > [!alex] callouts in scene-relevant vault notes.

Goal: bounded at ~1-2k tokens regardless of campaign length.

    context.py turn --slug <slug>
    context.py npc  --slug <slug> --character-id N [--turns-back 5]
    context.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

HARNESS_ROOT = Path("/Users/alexhedtke/Documents/Exobrain harness")
DATA_ROOT = HARNESS_ROOT / "data/solo-dm"

ALEX_CALLOUT_RE = re.compile(r"^>\s*\[!alex\]", re.IGNORECASE | re.MULTILINE)


def _conn(slug: str) -> sqlite3.Connection:
    db = DATA_ROOT / slug / "state.sqlite"
    if not db.exists():
        sys.exit(f"no db for slug {slug!r}")
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    return c


def _dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def _load_campaign(c: sqlite3.Connection) -> dict:
    row = c.execute("SELECT * FROM campaigns LIMIT 1").fetchone()
    return _dict(row) if row else {}


def _load_open_session(c: sqlite3.Connection) -> dict | None:
    row = c.execute(
        "SELECT * FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _dict(row) if row else None


def _load_open_scene(c: sqlite3.Connection, session_id: int) -> dict | None:
    row = c.execute(
        "SELECT * FROM scenes WHERE session_id=? AND closed_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return _dict(row) if row else None


def _recent_turns(c: sqlite3.Connection, scene_id: int | None, limit: int) -> list[dict]:
    if scene_id is None:
        return []
    rows = c.execute(
        """
        SELECT t.id, t.ord, t.action_text, t.classification, t.target_number,
               t.advantage, t.rule_of_cool_original_dc, t.rule_of_cool_reason,
               ch.name AS actor,
               r.spec, r.total, r.outcome, r.rolls_json
        FROM turns t
        LEFT JOIN characters ch ON ch.id = t.actor_character_id
        LEFT JOIN rolls r       ON r.turn_id = t.id
        WHERE t.scene_id = ?
        ORDER BY t.ord DESC
        LIMIT ?
        """,
        (scene_id, limit),
    ).fetchall()
    return [_dict(r) for r in reversed(rows)]


def _pc(c: sqlite3.Connection) -> dict | None:
    row = c.execute(
        "SELECT id, name, sheet_json, current_hp, temp_hp, conditions_json "
        "FROM characters WHERE kind='pc' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    d = _dict(row)
    d["sheet"] = json.loads(d.pop("sheet_json") or "{}")
    d["conditions"] = json.loads(d.pop("conditions_json") or "[]")
    return d


def _npcs_present(c: sqlite3.Connection, scene_id: int | None) -> list[dict]:
    if scene_id is None:
        return []
    rows = c.execute(
        """
        SELECT DISTINCT ch.id, ch.name, ch.kind, ch.model_tier,
               ch.current_hp, ch.temp_hp, ch.conditions_json, ch.disposition
        FROM characters ch
        JOIN turns t ON t.actor_character_id = ch.id
        WHERE t.scene_id = ? AND ch.kind IN ('named_npc','mook')
        """,
        (scene_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = _dict(r)
        d["conditions"] = json.loads(d.pop("conditions_json") or "[]")
        out.append(d)
    return out


def _active_quests(c: sqlite3.Connection) -> list[dict]:
    rows = c.execute(
        "SELECT id, name, status, beats_json FROM quests "
        "WHERE status='active' ORDER BY id"
    ).fetchall()
    out = []
    for r in rows:
        d = _dict(r)
        beats = json.loads(d.pop("beats_json") or "[]")
        next_beat = next((b for b in beats if not b.get("done")), None)
        d["next_beat"] = next_beat
        out.append(d)
    return out


def _world_state(c: sqlite3.Connection) -> dict:
    rows = c.execute("SELECT key, value FROM world_state").fetchall()
    return {r["key"]: r["value"] for r in rows}


def _npc_memory(c: sqlite3.Connection, cid: int, top_n: int = 5) -> list[dict]:
    rows = c.execute(
        "SELECT fact, salience, last_referenced FROM npc_memory "
        "WHERE character_id=? ORDER BY salience DESC, last_referenced DESC LIMIT ?",
        (cid, top_n),
    ).fetchall()
    return [_dict(r) for r in rows]


def _read_vault(campaign: dict) -> dict:
    out: dict = {"alex_notes": None, "claude_reference": None, "callouts": []}
    vault_path = campaign.get("vault_path")
    if not vault_path:
        return out
    root = Path(vault_path)
    if not root.exists():
        return out
    alex = root / "Alex's Notes.md"
    if alex.exists():
        out["alex_notes"] = alex.read_text()
    ref = root / "Claude reference.md"
    if ref.exists():
        out["claude_reference"] = ref.read_text()
    # Scan scene-relevant notes for [!alex] callouts
    for sub in ("Characters", "NPCs", "Factions", "Locations"):
        d = root / sub
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            text = f.read_text()
            if ALEX_CALLOUT_RE.search(text):
                # extract each callout block (> [!alex] and following > lines)
                blocks = re.findall(
                    r"(^>\s*\[!alex\][^\n]*(?:\n>[^\n]*)*)", text, re.MULTILINE | re.IGNORECASE
                )
                for b in blocks:
                    out["callouts"].append({"file": str(f.relative_to(root)), "text": b})
    return out


def build_turn_context(slug: str) -> dict:
    c = _conn(slug)
    try:
        campaign = _load_campaign(c)
        session = _load_open_session(c)
        scene = _load_open_scene(c, session["id"]) if session else None
        pc = _pc(c)
        npcs = _npcs_present(c, scene["id"] if scene else None)
        turns = _recent_turns(c, scene["id"] if scene else None, 10)
        quests = _active_quests(c)
        world = _world_state(c)
        vault = _read_vault(campaign)
        # attach memory snippets for NPCs present
        for n in npcs:
            n["memory"] = _npc_memory(c, n["id"])
        return {
            "campaign": {"name": campaign.get("name"), "slug": campaign.get("slug")},
            "session": session and {"id": session["id"], "number": session["number"]},
            "scene": scene and {
                "id": scene["id"],
                "name": scene["name"],
                "summary": scene.get("summary"),
                "npc_goals": json.loads(scene.get("npc_goals_json") or "[]"),
            },
            "pc": pc,
            "npcs_present": npcs,
            "recent_turns": turns,
            "active_quests": quests,
            "world_state": world,
            "alex_notes": vault["alex_notes"],
            "claude_reference": vault["claude_reference"],
            "alex_callouts": vault["callouts"],
        }
    finally:
        c.close()


def build_npc_context(slug: str, cid: int, turns_back: int = 5) -> dict:
    """Scoped context for an NPC/monster subagent.

    What the NPC knows: their own sheet, personality, memory, scene summary,
    this scene's turns filtered to what they witnessed. What they do NOT know:
    PC HP, PC spell slots, PC backstory, offstage events, DM reasoning.
    """
    c = _conn(slug)
    try:
        ch = c.execute(
            "SELECT id, name, kind, model_tier, sheet_json, current_hp, temp_hp, "
            "conditions_json, disposition FROM characters WHERE id=?",
            (cid,),
        ).fetchone()
        if ch is None:
            sys.exit(f"no character {cid}")
        sheet = json.loads(ch["sheet_json"] or "{}")
        memory = _npc_memory(c, cid, top_n=8)
        session = _load_open_session(c)
        scene = _load_open_scene(c, session["id"]) if session else None
        scene_summary = scene["summary"] if scene else None
        scene_goals = json.loads(scene["npc_goals_json"]) if scene else []
        # find this NPC's logged goal/fallback/walk-away
        my_goal = next(
            (g for g in scene_goals if g.get("character_id") == cid or g.get("name") == ch["name"]),
            None,
        )
        # recent turns in scene — strip PC meta-info (damage totals redacted to 'hit'/'miss')
        turns = _recent_turns(c, scene["id"] if scene else None, turns_back)
        redacted = []
        for t in turns:
            r = {
                "ord": t["ord"],
                "actor": t["actor"],
                "action": t["action_text"],
                "outcome": t.get("outcome"),
            }
            redacted.append(r)
        return {
            "self": {
                "id": ch["id"],
                "name": ch["name"],
                "kind": ch["kind"],
                "current_hp": ch["current_hp"],
                "temp_hp": ch["temp_hp"],
                "conditions": json.loads(ch["conditions_json"] or "[]"),
                "disposition": ch["disposition"],
                "sheet": sheet,
            },
            "memory": memory,
            "scene": {
                "name": scene["name"] if scene else None,
                "summary": scene_summary,
                "my_goal": my_goal,
            },
            "perceived_turns": redacted,
            "hard_constraints": [
                "Do not roll dice.",
                "Do not narrate outcomes (hits, misses, damage landing).",
                "Do not reveal PC HP or resources you wouldn't know.",
                "Declare intent in-character + mechanical choice only.",
            ],
        }
    finally:
        c.close()


def selftest() -> None:
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp(prefix="solo-dm-ctx-"))
    try:
        global DATA_ROOT
        DATA_ROOT = tmp
        vault = tmp / "vault"
        vault.mkdir()
        (vault / "Alex's Notes.md").write_text("My druid is afraid of spiders.")
        (vault / "Claude reference.md").write_text("High-fantasy tone.")
        (vault / "Characters").mkdir()
        (vault / "Characters" / "NPC.md").write_text(
            "# NPC\n> [!alex] correction\n> Freya is actually a spy for the guild, not the crown.\n"
        )
        # seed a campaign
        (tmp / "test").mkdir()
        conn = sqlite3.connect(tmp / "test" / "state.sqlite")
        conn.executescript(
            (HARNESS_ROOT / ".claude/skills/solo-dm/data/schema.sql").read_text()
        )
        conn.execute(
            "INSERT INTO campaigns (slug, name, vault_path) VALUES (?,?,?)",
            ("test", "Test", str(vault)),
        )
        conn.execute("INSERT INTO sessions (campaign_id, number) VALUES (1,1)")
        conn.execute("INSERT INTO scenes (session_id, ord, name, npc_goals_json) "
                     "VALUES (1,1,'Opening','[]')")
        conn.execute(
            "INSERT INTO characters (campaign_id, name, kind, model_tier, sheet_json, current_hp) "
            "VALUES (1,'Korvara','pc','opus',?,19)",
            (json.dumps({"class": "Druid", "level": 2, "ac": 14}),),
        )
        for i in range(15):
            conn.execute(
                "INSERT INTO turns (session_id, scene_id, ord, action_text, classification, target_number) "
                "VALUES (1,1,?,?,?,?)",
                (i + 1, f"action {i+1}", "check", 15),
            )
        conn.commit()
        conn.close()
        ctx = build_turn_context("test")
        # should contain Alex's Notes + exactly 1 callout
        assert ctx["alex_notes"] is not None and "spiders" in ctx["alex_notes"]
        assert len(ctx["alex_callouts"]) == 1
        assert "Freya" in ctx["alex_callouts"][0]["text"]
        # should have exactly 10 recent turns, not 15
        assert len(ctx["recent_turns"]) == 10, f"got {len(ctx['recent_turns'])} turns"
        # rough token cap: json size <= ~8k chars (= ~2k tokens)
        size = len(json.dumps(ctx))
        assert size < 12_000, f"context too large: {size}"
        print(f"context.py selftest: OK (size={size} chars, ~{size//4} tokens)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("turn"); s.add_argument("--slug", required=True)
    s = sub.add_parser("npc");  s.add_argument("--slug", required=True)
    s.add_argument("--character-id", type=int, required=True)
    s.add_argument("--turns-back", type=int, default=5)
    sub.add_parser("selftest")

    args = p.parse_args()
    if args.cmd == "turn":
        print(json.dumps(build_turn_context(args.slug), indent=2, default=str))
    elif args.cmd == "npc":
        print(json.dumps(build_npc_context(args.slug, args.character_id, args.turns_back),
                         indent=2, default=str))
    elif args.cmd == "selftest":
        selftest()


if __name__ == "__main__":
    main()
