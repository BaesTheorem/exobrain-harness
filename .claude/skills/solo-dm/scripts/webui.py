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
        return {
            "campaign": {"name": campaign["name"], "slug": campaign["slug"]},
            "pc": pc,
            "session": session,
            "world": world,
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
        "label": body.get("label", "Charles"),
    }
    ws_set("pc_position", pos)
    return pos


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
            self.send_error(404, f"unknown path: {p}")
        except Exception as e:
            self.send_error(500, f"server error: {e}")

    def do_DELETE(self):
        p = urlparse(self.path).path
        m = re.match(r"^/api/markers/([A-Za-z0-9_-]+)$", p)
        if m:
            return self._send_json(api_markers_delete(m.group(1)))
        self.send_error(404, f"unknown path: {p}")

    def do_PATCH(self):
        p = urlparse(self.path).path
        m = re.match(r"^/api/markers/([A-Za-z0-9_-]+)$", p)
        if m:
            body = self._read_json()
            return self._send_json(api_markers_update(m.group(1), body))
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
