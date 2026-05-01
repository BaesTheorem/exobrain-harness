#!/usr/bin/env python3
"""Local dashboard for solo-dm — stdlib HTTP server, zero dependencies.

    python3 webui.py --slug theory-of-magic [--port 8765]

Then open http://localhost:8765 in your browser.

The server reads the DB directly for character sheet state, and stores
map-related state (pc position, calibration, markers) as JSON values in
world_state. All writes flow through well-defined endpoints.

Map image is loaded from <campaign-vault>/assets/map.{jpg,png,webp}.
Drop your map file at that path and refresh.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sqlite3
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HARNESS_ROOT = Path("/Users/alexhedtke/Documents/Exobrain harness")
DATA_ROOT = HARNESS_ROOT / "data/solo-dm"
WEBUI_DIR = HARNESS_ROOT / ".claude/skills/solo-dm/webui"
SCRIPTS_DIR = HARNESS_ROOT / ".claude/skills/solo-dm/scripts"
PREFS_PATH = DATA_ROOT / "preferences.json"
DEFAULT_5ETOOLS_BASE = "http://localhost:5050"

# Prepared-caster formulas (5e 2014). Returns (ability_key, level_divisor).
# count = max(1, ability_mod + level // divisor)  for half-casters.
# count = ability_mod + level                    for full-casters.
PREPARED_CASTERS = {
    "wizard":    ("int", 1),
    "cleric":    ("wis", 1),
    "druid":     ("wis", 1),
    "paladin":   ("cha", 2),
    "artificer": ("int", 2),
    "ranger":    ("wis", 2),  # Tasha's revised
}

# Import the local Harptos calendar module by file path so we don't shadow
# Python's stdlib `calendar` for anyone else.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("solo_dm_harptos", SCRIPTS_DIR / "calendar.py")
harptos = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(harptos)

# Set by main()
SLUG = None
VAULT_PATH = None


def db() -> sqlite3.Connection:
    path = DATA_ROOT / SLUG / "state.sqlite"
    if not path.exists():
        sys.exit(f"no db for slug {SLUG!r}")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def load_prefs() -> dict:
    try:
        return json.loads(PREFS_PATH.read_text())
    except Exception:
        return {}


def get_5etools_base() -> str:
    prefs = load_prefs()
    base = ((prefs.get("tools") or {}).get("5etools_base_url")) or DEFAULT_5ETOOLS_BASE
    return base.rstrip("/")


def compute_prepared_max(sheet: dict) -> int | None:
    """Auto-compute max prepared spells from class+level+ability. None if class
    isn't a prepared caster (e.g. sorcerer, bard, warlock — they know spells)."""
    cls = (sheet.get("class") or "").strip().lower()
    if cls not in PREPARED_CASTERS:
        return None
    ability_key, divisor = PREPARED_CASTERS[cls]
    abs_ = sheet.get("abilities") or {}
    score = abs_.get(ability_key, 10)
    mod = (score - 10) // 2
    level = int(sheet.get("level") or 0)
    if divisor == 1:
        n = mod + level
    else:
        n = mod + (level // divisor)
    return max(1, n)


# --- World state helpers ---------------------------------------------------

def ws_get(key: str, default=None):
    c = db()
    try:
        row = c.execute(
            "SELECT value FROM world_state WHERE key=? LIMIT 1", (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return row["value"]
    finally:
        c.close()


def ws_set(key: str, value) -> None:
    c = db()
    try:
        cid = c.execute("SELECT id FROM campaigns LIMIT 1").fetchone()["id"]
        c.execute(
            "INSERT INTO world_state (campaign_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT(campaign_id, key) DO UPDATE SET value=excluded.value, "
            "updated_at=datetime('now')",
            (cid, key, json.dumps(value) if not isinstance(value, str) else value),
        )
        c.commit()
    finally:
        c.close()


# --- API handlers ----------------------------------------------------------

def api_state():
    """Everything the dashboard needs on load."""
    c = db()
    try:
        campaign = dict(c.execute("SELECT * FROM campaigns LIMIT 1").fetchone())
        pc_row = c.execute(
            "SELECT id, name, kind, sheet_json, current_hp, temp_hp, conditions_json "
            "FROM characters WHERE kind='pc' LIMIT 1"
        ).fetchone()
        pc = dict(pc_row) if pc_row else {}
        if pc:
            pc["sheet"] = json.loads(pc.pop("sheet_json") or "{}")
            pc["conditions"] = json.loads(pc.pop("conditions_json") or "[]")
            # Auto-compute prepared-spell cap from class/level/ability mod.
            # Honor a manual override if the sheet already has one.
            if pc["sheet"].get("spells_prepared_max") in (None, 0):
                auto = compute_prepared_max(pc["sheet"])
                if auto is not None:
                    pc["sheet"]["spells_prepared_max"] = auto
                    pc["sheet"]["spells_prepared_max_auto"] = True
        session_row = c.execute(
            "SELECT id, number, started_at, ended_at FROM sessions "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        session = dict(session_row) if session_row else None
        # world state snapshot
        world = {}
        for row in c.execute("SELECT key, value FROM world_state"):
            try:
                world[row["key"]] = json.loads(row["value"])
            except Exception:
                world[row["key"]] = row["value"]
        # Quests (proper table — not the dummy strings on the sheet)
        quests = []
        for r in c.execute(
            "SELECT id, name, status, beats_json FROM quests "
            "WHERE status IN ('active','dormant') ORDER BY status, id"
        ):
            d = dict(r)
            d["beats"] = json.loads(d.pop("beats_json") or "[]")
            quests.append(d)
        # Calendar events for a window around the current in-game year
        ig_date = world.get("in_game_date")
        cur_year = ig_date.get("year", 1491) if isinstance(ig_date, dict) else 1491
        events = [
            dict(r) for r in c.execute(
                "SELECT id, year, day_of_year, time_of_day, title, notes, kind, quest_id "
                "FROM calendar_events WHERE year BETWEEN ? AND ? ORDER BY year, day_of_year, id",
                (cur_year - 1, cur_year + 2),
            )
        ]
        return {
            "campaign": {"name": campaign["name"], "slug": campaign["slug"]},
            "pc": pc,
            "session": session,
            "world": world,
            "quests": quests,
            "calendar_events": events,
            "tools_5etools_base_url": get_5etools_base(),
        }
    finally:
        c.close()


def api_markers_list():
    return ws_get("map_markers", [])


def api_markers_add(body: dict):
    markers = ws_get("map_markers", [])
    new = {
        "id": body.get("id") or uuid.uuid4().hex[:8],
        "x": float(body["x"]),
        "y": float(body["y"]),
        "label": body.get("label", ""),
        "kind": body.get("kind", "poi"),
    }
    markers.append(new)
    ws_set("map_markers", markers)
    return new


def api_markers_delete(marker_id: str):
    markers = ws_get("map_markers", [])
    markers = [m for m in markers if m.get("id") != marker_id]
    ws_set("map_markers", markers)
    return {"ok": True}


def api_markers_update(marker_id: str, body: dict):
    markers = ws_get("map_markers", [])
    for m in markers:
        if m.get("id") == marker_id:
            for k, v in body.items():
                m[k] = v
            break
    ws_set("map_markers", markers)
    return {"ok": True}


def api_pc_position_get():
    return ws_get("pc_position", {"x": None, "y": None, "label": ""})


def api_pc_position_set(body: dict):
    pos = {
        "x": float(body["x"]),
        "y": float(body["y"]),
        "label": body.get("label", "PC"),
    }
    ws_set("pc_position", pos)
    return pos


def api_inventory_move(body: dict):
    """Move inventory items (by id) into a target container. target_container_id='ROOT' means top level."""
    item_ids = body.get("item_ids") or []
    target_id = body.get("target_container_id") or "ROOT"
    if not item_ids:
        return {"ok": False, "error": "no item_ids"}
    conn = sqlite3.connect(DATA_ROOT / SLUG / "state.sqlite")
    c = conn.cursor()
    c.execute("SELECT id, sheet_json FROM characters WHERE kind='pc' LIMIT 1")
    row = c.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "no PC"}
    pc_id, sheet_json = row
    sheet = json.loads(sheet_json)
    inv = sheet.get("inventory", [])

    def walk(items, parent_id="ROOT"):
        for it in items:
            yield it, parent_id, items
            if it.get("container") and isinstance(it.get("contents"), list):
                yield from walk(it["contents"], it.get("id"))

    # Locate target container
    target_container_list = None
    if target_id == "ROOT":
        target_container_list = inv
    else:
        for it, _pid, _parent_list in walk(inv):
            if it.get("id") == target_id and it.get("container"):
                target_container_list = it.setdefault("contents", [])
                break
    if target_container_list is None:
        conn.close()
        return {"ok": False, "error": f"target container {target_id!r} not found"}

    # Descendants of dragged items (cannot drop into own subtree)
    def collect_descendants(item):
        ids = {item.get("id")}
        for child in item.get("contents", []) or []:
            ids |= collect_descendants(child)
        return ids
    # Pick up the moving items and remove them from their current lists
    picked = []
    for iid in item_ids:
        for it, _pid, parent_list in walk(inv):
            if it.get("id") == iid:
                # Guard: would we drop into our own subtree?
                if target_id != "ROOT" and target_id in collect_descendants(it):
                    continue
                parent_list.remove(it)
                picked.append(it)
                break
    for it in picked:
        target_container_list.append(it)

    sheet["inventory"] = inv
    c.execute("UPDATE characters SET sheet_json = ? WHERE id = ?", (json.dumps(sheet), pc_id))
    conn.commit()
    conn.close()
    # Re-render the markdown sheet
    try:
        import subprocess
        subprocess.run([sys.executable, str(Path(__file__).parent / "sheet.py"),
                        "export", "--slug", SLUG, "--id", str(pc_id)],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    return {"ok": True, "moved": [p.get("id") for p in picked]}


def api_inventory_create_container(body: dict):
    name = (body.get("name") or "").strip()
    parent_id = body.get("parent_id") or "ROOT"
    note = (body.get("note") or "").strip()
    if not name:
        return {"ok": False, "error": "name required"}
    conn = sqlite3.connect(DATA_ROOT / SLUG / "state.sqlite")
    c = conn.cursor()
    c.execute("SELECT id, sheet_json FROM characters WHERE kind='pc' LIMIT 1")
    row = c.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "no PC"}
    pc_id, sheet_json = row
    sheet = json.loads(sheet_json)
    inv = sheet.setdefault("inventory", [])
    new_c = {"id": uuid.uuid4().hex[:8], "name": name, "qty": 1, "container": True, "contents": []}
    if note:
        new_c["note"] = note

    if parent_id == "ROOT":
        inv.append(new_c)
    else:
        def find(items):
            for it in items:
                if it.get("id") == parent_id and it.get("container"):
                    return it
                sub = find(it.get("contents", []) or [])
                if sub:
                    return sub
            return None
        parent = find(inv)
        if not parent:
            conn.close()
            return {"ok": False, "error": f"parent {parent_id!r} not found"}
        parent.setdefault("contents", []).append(new_c)

    c.execute("UPDATE characters SET sheet_json = ? WHERE id = ?", (json.dumps(sheet), pc_id))
    conn.commit()
    conn.close()
    try:
        import subprocess
        subprocess.run([sys.executable, str(Path(__file__).parent / "sheet.py"),
                        "export", "--slug", SLUG, "--id", str(pc_id)],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    return {"ok": True, "id": new_c["id"], "name": name}


def _inv_walk(items, parent_list=None):
    """Yield (item, parent_list) for every item in the inventory tree."""
    if parent_list is None:
        parent_list = items
    for it in list(items):
        yield it, items
        if it.get("container") and isinstance(it.get("contents"), list):
            yield from _inv_walk(it["contents"], it["contents"])


def _inv_load():
    conn = sqlite3.connect(DATA_ROOT / SLUG / "state.sqlite")
    c = conn.cursor()
    c.execute("SELECT id, sheet_json FROM characters WHERE kind='pc' LIMIT 1")
    row = c.fetchone()
    if not row:
        conn.close()
        return None, None, None
    pc_id, sheet_json = row
    sheet = json.loads(sheet_json)
    return conn, pc_id, sheet


def _inv_save(conn, pc_id, sheet):
    c = conn.cursor()
    c.execute("UPDATE characters SET sheet_json = ? WHERE id = ?", (json.dumps(sheet), pc_id))
    conn.commit()
    conn.close()
    try:
        import subprocess
        subprocess.run([sys.executable, str(Path(__file__).parent / "sheet.py"),
                        "export", "--slug", SLUG, "--id", str(pc_id)],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def api_inventory_toggle_container(body: dict):
    item_id = body.get("item_id")
    make_container = bool(body.get("container", True))
    dissolve = bool(body.get("dissolve", False))
    if not item_id:
        return {"ok": False, "error": "item_id required"}
    conn, pc_id, sheet = _inv_load()
    if conn is None:
        return {"ok": False, "error": "no PC"}
    inv = sheet.setdefault("inventory", [])
    for it, parent in _inv_walk(inv):
        if it.get("id") == item_id:
            if make_container:
                it["container"] = True
                it.setdefault("contents", [])
            else:
                if dissolve:
                    # Move children up to parent, then remove the container entry itself
                    idx = parent.index(it)
                    children = it.get("contents", []) or []
                    parent[idx:idx+1] = children
                else:
                    # Just remove container flag, keep item (rare — contents would be lost)
                    it.pop("container", None)
                    it.pop("contents", None)
            _inv_save(conn, pc_id, sheet)
            return {"ok": True, "id": item_id, "container": make_container}
    conn.close()
    return {"ok": False, "error": "item not found"}


def api_inventory_rename(body: dict):
    item_id = body.get("item_id")
    if not item_id:
        return {"ok": False, "error": "item_id required"}
    new_name = body.get("name")
    new_note = body.get("note")
    conn, pc_id, sheet = _inv_load()
    if conn is None:
        return {"ok": False, "error": "no PC"}
    inv = sheet.setdefault("inventory", [])
    for it, parent in _inv_walk(inv):
        if it.get("id") == item_id:
            if new_name is not None:
                it["name"] = new_name
            if new_note is not None:
                if new_note == "":
                    it.pop("note", None)
                else:
                    it["note"] = new_note
            _inv_save(conn, pc_id, sheet)
            return {"ok": True}
    conn.close()
    return {"ok": False, "error": "item not found"}


def api_inventory_delete(body: dict):
    item_id = body.get("item_id")
    if not item_id:
        return {"ok": False, "error": "item_id required"}
    conn, pc_id, sheet = _inv_load()
    if conn is None:
        return {"ok": False, "error": "no PC"}
    inv = sheet.setdefault("inventory", [])
    for it, parent in _inv_walk(inv):
        if it.get("id") == item_id:
            parent.remove(it)
            _inv_save(conn, pc_id, sheet)
            return {"ok": True}
    conn.close()
    return {"ok": False, "error": "item not found"}


def api_calibration_get():
    return ws_get("map_calibration", {"px_per_rel": None, "miles_per_rel": None})


def api_calibration_set(body: dict):
    # body: {"p1": {"x","y"}, "p2": {"x","y"}, "miles": float}
    import math
    p1, p2, miles = body["p1"], body["p2"], float(body["miles"])
    dx, dy = p2["x"] - p1["x"], p2["y"] - p1["y"]
    rel = math.hypot(dx, dy)
    if rel == 0:
        return {"error": "points are identical"}
    cal = {
        "miles_per_rel": miles / rel,
        "calibration_p1": p1,
        "calibration_p2": p2,
        "known_miles": miles,
        "rel_distance": rel,
    }
    ws_set("map_calibration", cal)
    return cal


def api_distance(body: dict):
    import math
    p1, p2 = body["p1"], body["p2"]
    dx, dy = p2["x"] - p1["x"], p2["y"] - p1["y"]
    rel = math.hypot(dx, dy)
    cal = ws_get("map_calibration")
    miles = None
    if cal and cal.get("miles_per_rel"):
        miles = rel * cal["miles_per_rel"]
    return {
        "rel": rel,
        "miles": miles,
        "days_normal": (miles / 20) if miles else None,     # 20 mi/day normal
        "days_cart": (miles / 18) if miles else None,       # Olwin's pace
        "days_pushed": (miles / 25) if miles else None,     # pushed
    }


_WIKI_CACHE: dict = {}


def api_wiki_summary(slug: str):
    """Fetch a brief intro from forgottenrealms.fandom.com for the given slug.

    Uses `action=parse&section=0` (intro section HTML), strips infoboxes,
    tables, asides/figures, then pulls the first real paragraph. Fandom's
    MediaWiki doesn't have the TextExtracts extension so `prop=extracts`
    returns nothing — parse-and-scrape is the only path. Cached in memory.
    """
    import urllib.request, urllib.parse, re, html as _html
    slug = (slug or "").strip()
    if not slug:
        return {"error": "no slug"}
    if slug in _WIKI_CACHE:
        return _WIKI_CACHE[slug]
    base = "https://forgottenrealms.fandom.com"
    api_url = (
        f"{base}/api.php?action=parse&format=json"
        f"&prop=text&section=0&redirects=1&page={urllib.parse.quote(slug)}"
    )
    page_url = f"{base}/wiki/{urllib.parse.quote(slug)}"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "solo-dm/1.0 (personal campaign dashboard)"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        parse = data.get("parse") or {}
        title = parse.get("title") or slug
        h = (parse.get("text") or {}).get("*", "")
        if not h:
            err = data.get("error", {}).get("info", "no intro")
            result = {"title": title, "extract": "", "url": page_url, "error": err}
            _WIKI_CACHE[slug] = result
            return result
        # Strip infobox tables, asides, figures, nav/hatnote divs
        h = re.sub(r"<table[^>]*>.*?</table>", "", h, flags=re.DOTALL)
        h = re.sub(r"<aside[^>]*>.*?</aside>", "", h, flags=re.DOTALL)
        h = re.sub(r"<figure[^>]*>.*?</figure>", "", h, flags=re.DOTALL)
        h = re.sub(
            r'<div class="(?:hatnote|dablink|notice|toc|navbox|infobox).*?</div>',
            "", h, flags=re.DOTALL,
        )
        # Collect paragraphs, take the first few that look like prose
        paras = re.findall(r"<p[^>]*>(.*?)</p>", h, flags=re.DOTALL)
        cleaned = []
        total = 0
        for p in paras:
            text = re.sub(r"<[^>]+>", "", p)
            text = _html.unescape(text)
            text = re.sub(r"\[\d+\]", "", text)  # footnote refs
            text = re.sub(r"\s+", " ", text).strip()
            # Fandom sometimes injects a "Cite error:..." tail from broken refs
            text = re.sub(r"\s*Cite error:.*$", "", text).strip()
            if len(text) < 30:
                continue
            cleaned.append(text)
            total += len(text)
            if total > 700:
                break
        extract = " ".join(cleaned)
        if len(extract) > 800:
            cut = extract[:800].rsplit(". ", 1)
            extract = cut[0] + ("." if len(cut) == 2 else "…")
        result = {"title": title, "extract": extract, "url": page_url}
        if not extract:
            result["error"] = "no prose intro found"
        _WIKI_CACHE[slug] = result
        return result
    except Exception as e:
        return {"title": slug, "extract": "", "url": page_url, "error": str(e)}


# --- Harptos calendar & events --------------------------------------------

def _campaign_id(c: sqlite3.Connection) -> int:
    return c.execute("SELECT id FROM campaigns LIMIT 1").fetchone()["id"]


def api_calendar_structure():
    """Static Harptos structure + the campaign's current in-game date."""
    months = []
    for idx, (name, alt) in enumerate(harptos.MONTHS):
        # Festival, if any, sits AFTER this month (between month N and N+1).
        # Walk like calendar.day_of_year does to find this month's start doy.
        total = 0
        for i in range(idx):
            total += 30
            if (total + 1) in harptos.FESTIVAL_DAYS:
                total += 1
        start_doy = total + 1
        following_festival = None
        if (total + 30 + 1) in harptos.FESTIVAL_DAYS:
            following_festival = {
                "doy": total + 30 + 1,
                "name": harptos.FESTIVAL_DAYS[total + 30 + 1],
            }
        months.append({
            "index": idx,
            "name": name,
            "alt_name": alt,
            "days": 30,
            "start_doy": start_doy,
            "following_festival": following_festival,
            "wiki_slug": name,
        })
    festivals = [
        {"doy": doy, "name": name, "wiki_slug": name.replace(" ", "_")}
        for doy, name in harptos.FESTIVALS
    ]
    cur_raw = ws_get("in_game_date")
    cur = _normalize_ig_date(cur_raw)
    return {
        "months": months,
        "festivals": festivals,
        "times_of_day": harptos.TIMES_OF_DAY,
        "current": cur,
        "current_formatted": harptos.format_date(cur) if cur.get("day_of_year") else None,
        "current_raw": cur_raw if isinstance(cur_raw, str) else None,
    }


def _normalize_ig_date(raw):
    """Coerce whatever's in world_state['in_game_date'] into the structured form
    {year, day_of_year, time}. Older campaigns stored a free-form string like
    '2 Eleasis 1491 DR, ~6:30am (dawn, post-long-rest)' — best-effort parse it."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return harptos.parse_date_str(raw)
        except SystemExit:
            # parse_date_str sys.exit's on bad input; fall through to default
            pass
        except Exception:
            pass
    return {"year": 1491, "day_of_year": 1, "time": "morning"}


def api_calendar_events_list(year: int | None = None):
    c = db()
    try:
        if year is None:
            rows = c.execute(
                "SELECT id, year, day_of_year, time_of_day, title, notes, kind, quest_id "
                "FROM calendar_events ORDER BY year, day_of_year, id"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, year, day_of_year, time_of_day, title, notes, kind, quest_id "
                "FROM calendar_events WHERE year=? ORDER BY day_of_year, id",
                (year,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def api_calendar_events_add(body: dict):
    title = (body.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title required"}
    c = db()
    try:
        cid = _campaign_id(c)
        # Two ways to specify the date:
        #   1) {year, day_of_year}  — direct
        #   2) {date_str: "15 Flamerule 1491 DR, morning"} — parsed
        if "date_str" in body and body["date_str"]:
            parsed = harptos.parse_date_str(body["date_str"])
            year = parsed["year"]
            doy = parsed["day_of_year"]
            time_of_day = parsed.get("time")
        else:
            year = int(body.get("year"))
            doy = int(body.get("day_of_year"))
            time_of_day = body.get("time_of_day")
        kind = body.get("kind") or "event"
        if kind not in ("event", "task", "quest_beat"):
            kind = "event"
        notes = body.get("notes")
        quest_id = body.get("quest_id")
        cur = c.execute(
            "INSERT INTO calendar_events (campaign_id, year, day_of_year, time_of_day, title, notes, kind, quest_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cid, year, doy, time_of_day, title, notes, kind, quest_id),
        )
        c.commit()
        return {
            "ok": True,
            "id": cur.lastrowid,
            "year": year,
            "day_of_year": doy,
            "time_of_day": time_of_day,
            "title": title,
            "notes": notes,
            "kind": kind,
            "quest_id": quest_id,
        }
    finally:
        c.close()


def api_calendar_events_update(eid: int, body: dict):
    fields = []
    values = []
    for k in ("year", "day_of_year", "time_of_day", "title", "notes", "kind", "quest_id"):
        if k in body:
            fields.append(f"{k}=?")
            values.append(body[k])
    if not fields:
        return {"ok": False, "error": "no fields to update"}
    values.append(eid)
    c = db()
    try:
        c.execute(f"UPDATE calendar_events SET {', '.join(fields)} WHERE id=?", values)
        c.commit()
        return {"ok": True}
    finally:
        c.close()


def api_calendar_events_delete(eid: int):
    c = db()
    try:
        c.execute("DELETE FROM calendar_events WHERE id=?", (eid,))
        c.commit()
        return {"ok": True}
    finally:
        c.close()


def api_calendar_advance(body: dict):
    """Advance the in-game date by N days/hours, optionally to a time of day."""
    cur = _normalize_ig_date(ws_get("in_game_date"))
    days = int(body.get("days") or 0)
    hours = int(body.get("hours") or 0)
    to_time = body.get("to_time") or None
    new = harptos.advance(cur, days=days, hours=hours, to_time=to_time)
    ws_set("in_game_date", new)
    return {"ok": True, "from": cur, "to": new, "formatted": harptos.format_date(new)}


def api_calendar_set(body: dict):
    if "date_str" in body and body["date_str"]:
        new = harptos.parse_date_str(body["date_str"])
    else:
        new = {
            "year": int(body["year"]),
            "day_of_year": int(body["day_of_year"]),
            "time": body.get("time", "morning"),
        }
    ws_set("in_game_date", new)
    return {"ok": True, "to": new, "formatted": harptos.format_date(new)}


# --- Quests ---------------------------------------------------------------

def _quest_row(c, qid):
    r = c.execute(
        "SELECT id, name, status, beats_json, giver_character_id, source_session_id "
        "FROM quests WHERE id=?", (qid,)
    ).fetchone()
    if not r:
        return None
    d = dict(r)
    d["beats"] = json.loads(d.pop("beats_json") or "[]")
    return d


def api_quests_list(include_completed: bool = False):
    c = db()
    try:
        if include_completed:
            rows = c.execute(
                "SELECT id, name, status, beats_json, giver_character_id, source_session_id "
                "FROM quests ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'dormant' THEN 1 "
                "WHEN 'complete' THEN 2 WHEN 'failed' THEN 3 END, id"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT id, name, status, beats_json, giver_character_id, source_session_id "
                "FROM quests WHERE status IN ('active','dormant') ORDER BY status, id"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["beats"] = json.loads(d.pop("beats_json") or "[]")
            out.append(d)
        return out
    finally:
        c.close()


def api_quests_add(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name required"}
    status = body.get("status") or "active"
    if status not in ("active", "complete", "failed", "dormant"):
        status = "active"
    beats = body.get("beats") or []
    c = db()
    try:
        cid = _campaign_id(c)
        cur = c.execute(
            "INSERT INTO quests (campaign_id, name, status, beats_json) VALUES (?,?,?,?)",
            (cid, name, status, json.dumps(beats)),
        )
        c.commit()
        return {"ok": True, "id": cur.lastrowid, "name": name, "status": status, "beats": beats}
    finally:
        c.close()


def api_quests_update(qid: int, body: dict):
    fields = []
    values = []
    if "name" in body:
        fields.append("name=?"); values.append(body["name"])
    if "status" in body:
        st = body["status"]
        if st not in ("active", "complete", "failed", "dormant"):
            return {"ok": False, "error": "bad status"}
        fields.append("status=?"); values.append(st)
    if "beats" in body:
        fields.append("beats_json=?"); values.append(json.dumps(body["beats"]))
    if not fields:
        return {"ok": False, "error": "no fields"}
    values.append(qid)
    c = db()
    try:
        c.execute(f"UPDATE quests SET {', '.join(fields)} WHERE id=?", values)
        c.commit()
        return {"ok": True, "quest": _quest_row(c, qid)}
    finally:
        c.close()


def api_quests_delete(qid: int):
    c = db()
    try:
        c.execute("DELETE FROM quests WHERE id=?", (qid,))
        c.commit()
        return {"ok": True}
    finally:
        c.close()


def api_spells_toggle_prepared(body: dict):
    """Toggle whether a spell is prepared. Body: {spell: str, prepared?: bool}."""
    spell = (body.get("spell") or "").strip()
    if not spell:
        return {"ok": False, "error": "spell required"}
    conn, pc_id, sheet = _inv_load()
    if conn is None:
        return {"ok": False, "error": "no PC"}
    prepared = list(sheet.get("spells_prepared") or [])
    is_prepared = spell in prepared
    desired = body.get("prepared")
    if desired is None:
        desired = not is_prepared
    if desired and not is_prepared:
        prepared.append(spell)
    elif not desired and is_prepared:
        prepared = [s for s in prepared if s != spell]
    sheet["spells_prepared"] = prepared
    _inv_save(conn, pc_id, sheet)
    return {"ok": True, "spell": spell, "prepared": desired, "count": len(prepared)}


def api_abilities_set(body: dict):
    """Set uses_remaining on a long-rest ability. Body: {name: str, uses_remaining: int}."""
    name = (body.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name required"}
    try:
        uses = int(body.get("uses_remaining"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "uses_remaining must be an integer"}
    conn, pc_id, sheet = _inv_load()
    if conn is None:
        return {"ok": False, "error": "no PC"}
    abilities = sheet.get("long_rest_abilities") or []
    match = next((a for a in abilities if a.get("name") == name), None)
    if match is None:
        return {"ok": False, "error": f"ability {name!r} not found"}
    max_uses = int(match.get("max", 1))
    match["uses_remaining"] = max(0, min(max_uses, uses))
    sheet["long_rest_abilities"] = abilities
    _inv_save(conn, pc_id, sheet)
    return {"ok": True, "name": name, "uses_remaining": match["uses_remaining"], "max": max_uses}


def api_spells_set_prepared_max(body: dict):
    """Set or clear a manual override for max prepared. Body: {max: int|null}."""
    conn, pc_id, sheet = _inv_load()
    if conn is None:
        return {"ok": False, "error": "no PC"}
    val = body.get("max")
    if val in (None, "", 0):
        sheet.pop("spells_prepared_max", None)
    else:
        try:
            sheet["spells_prepared_max"] = int(val)
        except (TypeError, ValueError):
            return {"ok": False, "error": "max must be an integer"}
    sheet.pop("spells_prepared_max_auto", None)
    _inv_save(conn, pc_id, sheet)
    return {"ok": True, "max": sheet.get("spells_prepared_max")}


def api_ki_set(body: dict):
    """Set the PC's current ki. Body: {current: int}. Clamps to [0, ki.max].
    Only valid when the character has a ki block on their sheet (Monk class)."""
    conn, pc_id, sheet = _inv_load()
    if conn is None:
        return {"ok": False, "error": "no PC"}
    ki = sheet.get("ki")
    if not isinstance(ki, dict) or "max" not in ki:
        return {"ok": False, "error": "no ki on this sheet (not a Monk?)"}
    try:
        cur = int(body.get("current"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "current must be an integer"}
    ki["current"] = max(0, min(int(ki.get("max", 0)), cur))
    sheet["ki"] = ki
    _inv_save(conn, pc_id, sheet)
    return {"ok": True, "ki": ki}


# --- Combat encounter -----------------------------------------------------
#
# A single active encounter lives in world_state['combat']. The grid uses
# offset (col, row) coords with pointy-top hexes; each hex is 5 ft.
# The frontend handles monster lookup against the 5etools server directly
# (CORS open at localhost:5050) and POSTs hydrated tokens here.

def _combat_default_state(cols: int = 20, rows: int = 14) -> dict:
    return {
        "active": True,
        "grid": {"cols": int(cols), "rows": int(rows)},
        "tokens": [],
        "round": 1,
        "started_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }


def _place_pc_token(state: dict) -> None:
    """Drop in a token for the PC if one isn't already present."""
    if any(t.get("kind") == "pc" for t in state["tokens"]):
        return
    c = db()
    try:
        row = c.execute(
            "SELECT name, current_hp, sheet_json FROM characters WHERE kind='pc' LIMIT 1"
        ).fetchone()
    finally:
        c.close()
    if not row:
        return
    sheet = json.loads(row["sheet_json"] or "{}")
    state["tokens"].append({
        "id": uuid.uuid4().hex[:8],
        "kind": "pc",
        "name": row["name"] or "PC",
        "source": None,
        "image_url": None,
        "size": "M",
        "col": 1,
        "row": state["grid"]["rows"] // 2,
        "hp": int(row["current_hp"] or sheet.get("hp_max") or 1),
        "hp_max": int(sheet.get("hp_max") or row["current_hp"] or 1),
        "ac": int(sheet.get("ac_with_mage_armor") or sheet.get("ac") or 10),
        "initiative": None,
        "conditions": [],
    })


def api_combat_get():
    state = ws_get("combat")
    if not state or not state.get("active"):
        return {"active": False}
    return state


def api_combat_start(body: dict):
    """Body: {cols?, rows?, tokens?: [{name,source,image_url,hp,hp_max,ac,size,kind?}], place_pc?: bool}.

    Initial enemy/ally tokens are auto-placed clustered on the right; PC on
    the left. The caller (frontend or CLI) is responsible for hydrating
    monster stats from 5etools — this endpoint just stores what it's given.
    """
    cols = int(body.get("cols") or 20)
    rows = int(body.get("rows") or 14)
    state = _combat_default_state(cols, rows)
    incoming = body.get("tokens") or []
    place_pc = body.get("place_pc", True)
    # Auto-place enemies in a cluster on the right side, alternating rows
    # around vertical center.
    mid_row = rows // 2
    for i, t in enumerate(incoming):
        kind = t.get("kind") or "enemy"
        col = t.get("col")
        row = t.get("row")
        if col is None or row is None:
            if kind == "enemy":
                col = max(0, cols - 2 - (i // 4))
                row = max(0, min(rows - 1, mid_row + ((-1) ** i) * ((i + 1) // 2)))
            else:
                col = 2 + (i // 4)
                row = max(0, min(rows - 1, mid_row + ((-1) ** i) * ((i + 1) // 2)))
        hp_max = int(t.get("hp_max") or t.get("hp") or 1)
        state["tokens"].append({
            "id": t.get("id") or uuid.uuid4().hex[:8],
            "kind": kind,
            "name": t.get("name") or "Token",
            "source": t.get("source"),
            "image_url": t.get("image_url"),
            "size": t.get("size") or "M",
            "col": int(col),
            "row": int(row),
            "hp": int(t.get("hp") or hp_max),
            "hp_max": hp_max,
            "ac": int(t.get("ac") or 10),
            "initiative": t.get("initiative"),
            "conditions": t.get("conditions") or [],
            "monster_meta": t.get("monster_meta"),
        })
    if place_pc:
        _place_pc_token(state)
    ws_set("combat", state)
    return state


def api_combat_end():
    ws_set("combat", {"active": False})
    return {"ok": True}


def api_combat_token_add(body: dict):
    state = ws_get("combat") or _combat_default_state()
    if not state.get("active"):
        return {"ok": False, "error": "no active encounter — start one first"}
    hp_max = int(body.get("hp_max") or body.get("hp") or 1)
    tok = {
        "id": body.get("id") or uuid.uuid4().hex[:8],
        "kind": body.get("kind") or "enemy",
        "name": body.get("name") or "Token",
        "source": body.get("source"),
        "image_url": body.get("image_url"),
        "size": body.get("size") or "M",
        "col": int(body.get("col") or 0),
        "row": int(body.get("row") or 0),
        "hp": int(body.get("hp") or hp_max),
        "hp_max": hp_max,
        "ac": int(body.get("ac") or 10),
        "initiative": body.get("initiative"),
        "conditions": body.get("conditions") or [],
        "monster_meta": body.get("monster_meta"),
    }
    state["tokens"].append(tok)
    ws_set("combat", state)
    return tok


def api_combat_token_update(tok_id: str, body: dict):
    state = ws_get("combat")
    if not state or not state.get("active"):
        return {"ok": False, "error": "no active encounter"}
    for t in state["tokens"]:
        if t.get("id") == tok_id:
            for k in ("col", "row", "hp", "hp_max", "ac", "name", "kind",
                     "initiative", "conditions", "image_url", "size"):
                if k in body:
                    t[k] = body[k]
            ws_set("combat", state)
            return t
    return {"ok": False, "error": f"token {tok_id!r} not found"}


def api_combat_token_delete(tok_id: str):
    state = ws_get("combat")
    if not state or not state.get("active"):
        return {"ok": False, "error": "no active encounter"}
    state["tokens"] = [t for t in state["tokens"] if t.get("id") != tok_id]
    ws_set("combat", state)
    return {"ok": True}


def api_campaigns_list():
    """List every campaign that has a SQLite DB on disk."""
    out = []
    if not DATA_ROOT.exists():
        return out
    for d in sorted(DATA_ROOT.iterdir()):
        if not d.is_dir():
            continue
        sqlite_path = d / "state.sqlite"
        if not sqlite_path.exists():
            continue
        try:
            c = sqlite3.connect(sqlite_path)
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT slug, name FROM campaigns LIMIT 1").fetchone()
            c.close()
            if row:
                out.append({
                    "slug": row["slug"],
                    "name": row["name"],
                    "current": row["slug"] == SLUG,
                })
        except Exception:
            continue
    return out


def api_campaign_switch(body: dict):
    """Switch the dashboard's active campaign in-place. Caller should reload the page."""
    global SLUG, VAULT_PATH
    new_slug = (body.get("slug") or "").strip()
    if not new_slug:
        return {"ok": False, "error": "slug required"}
    sqlite_path = DATA_ROOT / new_slug / "state.sqlite"
    if not sqlite_path.exists():
        return {"ok": False, "error": f"no campaign at {new_slug!r}"}
    try:
        c = sqlite3.connect(sqlite_path)
        row = c.execute("SELECT vault_path FROM campaigns LIMIT 1").fetchone()
        c.close()
    except Exception as e:
        return {"ok": False, "error": f"db error: {e}"}
    if not row:
        return {"ok": False, "error": "no campaign row"}
    SLUG = new_slug
    VAULT_PATH = row[0]
    (Path(VAULT_PATH) / "assets").mkdir(parents=True, exist_ok=True)
    return {"ok": True, "slug": SLUG, "vault_path": VAULT_PATH}


def find_map_file() -> Path | None:
    """Look for a map image in the campaign's vault assets folder."""
    assets = Path(VAULT_PATH) / "assets"
    if not assets.exists():
        return None
    for ext in ("jpg", "jpeg", "png", "webp", "gif"):
        for candidate in (assets / f"map.{ext}", assets / f"Map.{ext}"):
            if candidate.exists():
                return candidate
    # any image file in assets as fallback
    for f in assets.iterdir():
        if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            return f
    return None


# --- HTTP server -----------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # quiet: only log errors
        if "404" in fmt % args or "500" in fmt % args:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, content_type: str | None = None):
        if not path.exists():
            self.send_error(404, f"not found: {path.name}")
            return
        if content_type is None:
            content_type, _ = mimetypes.guess_type(str(path))
            content_type = content_type or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_GET(self):
        url = urlparse(self.path)
        p = url.path
        try:
            if p == "/" or p == "/index.html":
                return self._send_file(WEBUI_DIR / "index.html", "text/html; charset=utf-8")
            if p == "/style.css":
                return self._send_file(WEBUI_DIR / "style.css", "text/css; charset=utf-8")
            if p == "/app.js":
                return self._send_file(WEBUI_DIR / "app.js", "application/javascript; charset=utf-8")
            if p == "/map":
                mf = find_map_file()
                if mf is None:
                    self.send_error(404, "no map file at <vault>/assets/map.{jpg,png,webp}")
                    return
                return self._send_file(mf)
            if p == "/api/state":
                return self._send_json(api_state())
            if p == "/api/markers":
                return self._send_json(api_markers_list())
            if p == "/api/pc-position":
                return self._send_json(api_pc_position_get())
            if p == "/api/calibration":
                return self._send_json(api_calibration_get())
            if p == "/api/health":
                return self._send_json({"ok": True, "slug": SLUG})
            if p == "/api/wiki-summary":
                qs = parse_qs(url.query)
                slug = (qs.get("slug") or [""])[0]
                return self._send_json(api_wiki_summary(slug))
            if p == "/api/calendar/structure":
                return self._send_json(api_calendar_structure())
            if p == "/api/calendar/events":
                qs = parse_qs(url.query)
                yr = qs.get("year", [None])[0]
                return self._send_json(api_calendar_events_list(int(yr) if yr else None))
            if p == "/api/quests":
                qs = parse_qs(url.query)
                inc = (qs.get("include_completed", ["0"])[0] in ("1", "true", "yes"))
                return self._send_json(api_quests_list(inc))
            if p == "/api/campaigns":
                return self._send_json(api_campaigns_list())
            if p == "/api/combat":
                return self._send_json(api_combat_get())
            self.send_error(404, f"unknown path: {p}")
        except Exception as e:
            self.send_error(500, f"server error: {e}")

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            body = self._read_json()
            if p == "/api/markers":
                return self._send_json(api_markers_add(body))
            if p == "/api/pc-position":
                return self._send_json(api_pc_position_set(body))
            if p == "/api/calibration":
                return self._send_json(api_calibration_set(body))
            if p == "/api/distance":
                return self._send_json(api_distance(body))
            if p == "/api/inventory/move":
                return self._send_json(api_inventory_move(body))
            if p == "/api/inventory/create-container":
                return self._send_json(api_inventory_create_container(body))
            if p == "/api/inventory/toggle-container":
                return self._send_json(api_inventory_toggle_container(body))
            if p == "/api/inventory/rename":
                return self._send_json(api_inventory_rename(body))
            if p == "/api/inventory/delete":
                return self._send_json(api_inventory_delete(body))
            if p == "/api/calendar/events":
                return self._send_json(api_calendar_events_add(body))
            if p == "/api/calendar/advance":
                return self._send_json(api_calendar_advance(body))
            if p == "/api/calendar/set":
                return self._send_json(api_calendar_set(body))
            if p == "/api/quests":
                return self._send_json(api_quests_add(body))
            if p == "/api/spells/toggle-prepared":
                return self._send_json(api_spells_toggle_prepared(body))
            if p == "/api/spells/prepared-max":
                return self._send_json(api_spells_set_prepared_max(body))
            if p == "/api/abilities/set":
                return self._send_json(api_abilities_set(body))
            if p == "/api/ki/set":
                return self._send_json(api_ki_set(body))
            if p == "/api/campaign/switch":
                return self._send_json(api_campaign_switch(body))
            if p == "/api/combat/start":
                return self._send_json(api_combat_start(body))
            if p == "/api/combat/end":
                return self._send_json(api_combat_end())
            if p == "/api/combat/token":
                return self._send_json(api_combat_token_add(body))
            self.send_error(404, f"unknown path: {p}")
        except Exception as e:
            self.send_error(500, f"server error: {e}")

    def do_DELETE(self):
        p = urlparse(self.path).path
        m = re.match(r"^/api/markers/([A-Za-z0-9_-]+)$", p)
        if m:
            return self._send_json(api_markers_delete(m.group(1)))
        m = re.match(r"^/api/calendar/events/(\d+)$", p)
        if m:
            return self._send_json(api_calendar_events_delete(int(m.group(1))))
        m = re.match(r"^/api/quests/(\d+)$", p)
        if m:
            return self._send_json(api_quests_delete(int(m.group(1))))
        m = re.match(r"^/api/combat/token/([A-Za-z0-9_-]+)$", p)
        if m:
            return self._send_json(api_combat_token_delete(m.group(1)))
        self.send_error(404, f"unknown path: {p}")

    def do_PATCH(self):
        p = urlparse(self.path).path
        m = re.match(r"^/api/markers/([A-Za-z0-9_-]+)$", p)
        if m:
            body = self._read_json()
            return self._send_json(api_markers_update(m.group(1), body))
        m = re.match(r"^/api/calendar/events/(\d+)$", p)
        if m:
            body = self._read_json()
            return self._send_json(api_calendar_events_update(int(m.group(1)), body))
        m = re.match(r"^/api/quests/(\d+)$", p)
        if m:
            body = self._read_json()
            return self._send_json(api_quests_update(int(m.group(1)), body))
        m = re.match(r"^/api/combat/token/([A-Za-z0-9_-]+)$", p)
        if m:
            body = self._read_json()
            return self._send_json(api_combat_token_update(m.group(1), body))
        self.send_error(404, f"unknown path: {p}")


def main():
    global SLUG, VAULT_PATH
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()

    SLUG = args.slug
    # Resolve vault path from DB
    c = sqlite3.connect(DATA_ROOT / SLUG / "state.sqlite")
    row = c.execute("SELECT vault_path FROM campaigns LIMIT 1").fetchone()
    c.close()
    if row is None:
        sys.exit("no campaign row")
    VAULT_PATH = row[0]

    # Ensure assets dir exists
    (Path(VAULT_PATH) / "assets").mkdir(parents=True, exist_ok=True)

    mf = find_map_file()
    print(f"=== solo-dm dashboard ===")
    print(f"Campaign: {SLUG}")
    print(f"Vault:    {VAULT_PATH}")
    print(f"Map file: {mf if mf else '(none — drop an image at ' + VAULT_PATH + '/assets/map.jpg)'}")
    print(f"URL:      http://localhost:{args.port}/")
    print(f"Stop:     Ctrl-C")
    print()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(f"http://localhost:{args.port}/")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping...")
        server.shutdown()


if __name__ == "__main__":
    main()
