#!/usr/bin/env python3
"""
Sailboat Retrospective — Exobrain Module
A DnD party retrospective tool using the Agile Sailboat framework.
Auto-syncs to Obsidian notes. No external dependencies — Python stdlib only.
"""

import json
import os
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import webbrowser

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retro-data.json")
DEFAULT_VAULT_PATH = os.path.expanduser("~/Documents/Exobrain/")
PORT = 5175


# ─── Data Layer ───────────────────────────────────────────────────────────────

def load_data():
    if not os.path.exists(DATA_FILE):
        data = {
            "parties": {
                "Default Campaign": {"island": [], "sails": [], "anchor": [], "rocks": [], "sun": []}
            },
            "settings": {
                "default_vault_path": DEFAULT_VAULT_PATH,
                "current_party": "Default Campaign"
            }
        }
        save_data(data)
        return data
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_party_data(data, party_name=None):
    if party_name is None:
        party_name = data["settings"]["current_party"]
    return data["parties"].get(party_name, {"island": [], "sails": [], "anchor": [], "rocks": [], "sun": []})


def get_obsidian_path(data, party_name=None):
    if party_name is None:
        party_name = data["settings"]["current_party"]
    vault_path = data["settings"].get("default_vault_path", DEFAULT_VAULT_PATH)
    # Allow per-party custom paths
    party = data["parties"].get(party_name)
    if isinstance(party, dict) and party.get("_obsidian_path"):
        return party["_obsidian_path"]
    return os.path.join(vault_path, f"Sailboat Retro - {party_name}.md")


# ─── Obsidian Sync ────────────────────────────────────────────────────────────

def sync_obsidian(data, party_name=None):
    """Regenerate the Obsidian note from current data. Called on every mutation."""
    if party_name is None:
        party_name = data["settings"]["current_party"]
    party = get_party_data(data, party_name)
    path = get_obsidian_path(data, party_name)

    # Ensure directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)

    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    lines = []
    lines.append(f"<< [[Dashboard]] >>")
    lines.append(f"[Open Sailboat Retro](http://localhost:{PORT})")
    lines.append("")
    lines.append(f"*Last synced: {now}*")
    lines.append("")

    # Goal
    lines.append("## \U0001f3dd\ufe0f Goal (Island)")
    for item in party.get("island", []):
        line = f"- {item['text']}"
        if item.get("notes"):
            line += f" \u2014 *{item['notes']}*"
        lines.append(line)
    if not party.get("island"):
        lines.append("- *(none yet)*")
    lines.append("")

    # Strengths
    lines.append("## \u26f5 Strengths (Sails & Wind)")
    for item in party.get("sails", []):
        extras = []
        if item.get("tag"):
            extras.append(f"`{item['tag']}`")
        if item.get("notes"):
            extras.append(f"*{item['notes']}*")
        line = f"- {item['text']}"
        if extras:
            line += " \u2014 " + " ".join(extras)
        lines.append(line)
    if not party.get("sails"):
        lines.append("- *(none yet)*")
    lines.append("")

    # Weaknesses
    lines.append("## \u2693 Weaknesses (Anchor)")
    for item in party.get("anchor", []):
        extras = []
        if item.get("tag"):
            extras.append(f"`{item['tag']}`")
        if item.get("negotiable") is not None:
            extras.append("`Negotiable`" if item["negotiable"] else "`Non-negotiable`")
        if item.get("notes"):
            extras.append(f"*{item['notes']}*")
        line = f"- {item['text']}"
        if extras:
            line += " \u2014 " + " ".join(extras)
        lines.append(line)
    if not party.get("anchor"):
        lines.append("- *(none yet)*")
    lines.append("")

    # Risks
    lines.append("## \U0001faa8 Risks (Rocks)")
    for item in party.get("rocks", []):
        extras = []
        if item.get("negotiable") is not None:
            extras.append("`Negotiable`" if item["negotiable"] else "`Non-negotiable`")
        if item.get("notes"):
            extras.append(f"*{item['notes']}*")
        line = f"- {item['text']}"
        if extras:
            line += " \u2014 " + " ".join(extras)
        lines.append(line)
    if not party.get("rocks"):
        lines.append("- *(none yet)*")
    lines.append("")

    # Joy
    lines.append("## \u2600\ufe0f Joy (Sun)")
    for item in party.get("sun", []):
        line = f"- {item['text']}"
        if item.get("notes"):
            line += f" \u2014 *{item['notes']}*"
        lines.append(line)
    if not party.get("sun"):
        lines.append("- *(none yet)*")
    lines.append("")

    # Analysis
    all_items = party.get("anchor", []) + party.get("rocks", [])
    negotiables = [i for i in all_items if i.get("negotiable") is True]
    non_negotiables = [i for i in all_items if i.get("negotiable") is False]

    lines.append("## \U0001f4ca Analysis")
    sails_count = len(party.get("sails", []))
    anchor_count = len(party.get("anchor", []))
    lines.append(f"**Party Balance:** {sails_count} strengths / {anchor_count} weaknesses")
    lines.append("")

    lines.append("**Negotiables** (can change):")
    if negotiables:
        for i in negotiables:
            lines.append(f"- {i['text']}")
    else:
        lines.append("- *(none tagged)*")
    lines.append("")

    lines.append("**Non-negotiables** (accept & work around):")
    if non_negotiables:
        for i in non_negotiables:
            lines.append(f"- {i['text']}")
    else:
        lines.append("- *(none tagged)*")
    lines.append("")

    # Auto-generated insights
    suggestions = generate_suggestions(party)
    if suggestions:
        lines.append("## \U0001f4a1 Insights")
        for s in suggestions:
            lines.append(f"- [ ] {s}")
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines))


def generate_suggestions(party):
    suggestions = []
    strengths = party.get("sails", [])
    weaknesses = party.get("anchor", [])
    risks = party.get("rocks", [])

    if strengths and weaknesses:
        s = strengths[0]
        w = weaknesses[0]
        suggestions.append(f'Consider addressing "{w["text"][:50]}" by leveraging "{s["text"][:50]}"')

    if len(weaknesses) > len(strengths):
        suggestions.append("The party has more weaknesses than strengths \u2014 consider a session focused on team synergy")

    negotiable_risks = [r for r in risks if r.get("negotiable") is True]
    non_neg_risks = [r for r in risks if r.get("negotiable") is False]
    if negotiable_risks:
        suggestions.append(f"{len(negotiable_risks)} risk(s) marked as negotiable \u2014 actionable and worth addressing soon")
    if non_neg_risks:
        suggestions.append(f"{len(non_neg_risks)} risk(s) are non-negotiable \u2014 build strategies to work around them")

    return suggestions


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class RetroHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _send_html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send_html(HTML_APP)
        elif path == "/api/data":
            self._send_json(load_data())
        elif path == "/api/parties":
            data = load_data()
            self._send_json({
                "parties": list(data["parties"].keys()),
                "current": data["settings"]["current_party"]
            })
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/api/parties":
            # Create new party
            data = load_data()
            name = body.get("name", "").strip()
            if not name:
                self._send_json({"error": "Name required"}, 400)
                return
            if name in data["parties"]:
                self._send_json({"error": "Party already exists"}, 400)
                return
            data["parties"][name] = {"island": [], "sails": [], "anchor": [], "rocks": [], "sun": []}
            data["settings"]["current_party"] = name
            save_data(data)
            sync_obsidian(data, name)
            self._send_json({"ok": True, "current": name})

        elif path == "/api/items":
            # Add item to a category
            data = load_data()
            party_name = data["settings"]["current_party"]
            cat = body.get("category")
            item = body.get("item", {})
            if cat not in ("island", "sails", "anchor", "rocks", "sun"):
                self._send_json({"error": "Invalid category"}, 400)
                return
            if not item.get("text"):
                self._send_json({"error": "Text required"}, 400)
                return
            data["parties"][party_name].setdefault(cat, []).append(item)
            save_data(data)
            sync_obsidian(data, party_name)
            self._send_json({"ok": True, "party": get_party_data(data)})

        elif path == "/api/switch-party":
            data = load_data()
            name = body.get("name")
            if name in data["parties"]:
                data["settings"]["current_party"] = name
                save_data(data)
                self._send_json({"ok": True, "party": get_party_data(data)})
            else:
                self._send_json({"error": "Party not found"}, 404)

        elif path == "/api/settings":
            data = load_data()
            if "vault_path" in body:
                data["settings"]["default_vault_path"] = body["vault_path"]
            if "obsidian_path" in body:
                party_name = data["settings"]["current_party"]
                data["parties"][party_name]["_obsidian_path"] = body["obsidian_path"]
            save_data(data)
            # Re-sync with new path
            sync_obsidian(data)
            self._send_json({"ok": True})

        elif path == "/api/sync":
            # Force re-sync
            data = load_data()
            party_name = body.get("party") or data["settings"]["current_party"]
            sync_obsidian(data, party_name)
            self._send_json({"ok": True, "path": get_obsidian_path(data, party_name)})

        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/api/items":
            # Update item
            data = load_data()
            party_name = data["settings"]["current_party"]
            cat = body.get("category")
            idx = body.get("index")
            item = body.get("item", {})
            party = data["parties"][party_name]
            if cat in party and 0 <= idx < len(party[cat]):
                party[cat][idx] = item
                save_data(data)
                sync_obsidian(data, party_name)
                self._send_json({"ok": True, "party": get_party_data(data)})
            else:
                self._send_json({"error": "Item not found"}, 404)

        elif path == "/api/items/reorder":
            # Reorder items within a category
            data = load_data()
            party_name = data["settings"]["current_party"]
            cat = body.get("category")
            new_order = body.get("order", [])  # list of indices
            party = data["parties"][party_name]
            if cat in party:
                old_items = party[cat]
                party[cat] = [old_items[i] for i in new_order if 0 <= i < len(old_items)]
                save_data(data)
                sync_obsidian(data, party_name)
                self._send_json({"ok": True, "party": get_party_data(data)})
            else:
                self._send_json({"error": "Invalid category"}, 400)

        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query)

        if path == "/api/items":
            data = load_data()
            party_name = data["settings"]["current_party"]
            cat = params.get("category", [None])[0]
            idx = int(params.get("index", [-1])[0])
            party = data["parties"][party_name]
            if cat in party and 0 <= idx < len(party[cat]):
                party[cat].pop(idx)
                save_data(data)
                sync_obsidian(data, party_name)
                self._send_json({"ok": True, "party": get_party_data(data)})
            else:
                self._send_json({"error": "Item not found"}, 404)

        elif path == "/api/parties":
            data = load_data()
            name = params.get("name", [None])[0]
            if not name or name not in data["parties"]:
                self._send_json({"error": "Party not found"}, 404)
                return
            if len(data["parties"]) <= 1:
                self._send_json({"error": "Cannot delete last party"}, 400)
                return
            # Remove the Obsidian note too
            note_path = get_obsidian_path(data, name)
            if os.path.exists(note_path):
                os.remove(note_path)
            del data["parties"][name]
            data["settings"]["current_party"] = list(data["parties"].keys())[0]
            save_data(data)
            self._send_json({"ok": True, "current": data["settings"]["current_party"]})

        else:
            self.send_response(404)
            self.end_headers()


# ─── HTML App ─────────────────────────────────────────────────────────────────

HTML_APP = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sailboat Retrospective — DnD Party Tool</title>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #0a1628;
  --bg-surface: #111d33;
  --bg-card: #162340;
  --bg-card-hover: #1c2d52;
  --teal: #2dd4bf;
  --teal-dim: #1a8a7a;
  --gold: #f59e0b;
  --gold-dim: #b47208;
  --cream: #fef3c7;
  --cream-dim: #d4c9a0;
  --red: #ef4444;
  --red-dim: #991b1b;
  --blue: #3b82f6;
  --green: #22c55e;
  --purple: #a855f7;
  --text: #e2e8f0;
  --text-dim: #94a3b8;
  --border: #1e3a5f;
  --glow-teal: 0 0 20px rgba(45, 212, 191, 0.15);
  --glow-gold: 0 0 20px rgba(245, 158, 11, 0.15);
  --radius: 12px;
  --transition: 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

html { font-size: 16px; }
body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}

h1, h2, h3, h4 { font-family: 'Cinzel', serif; color: var(--cream); }

/* Top Bar */
.top-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 1rem 2rem;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap; gap: 0.75rem;
}
.top-bar h1 { font-size: 1.4rem; white-space: nowrap; }
.top-bar h1 span { color: var(--gold); }
.party-controls { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }

.sync-status {
  display: flex; align-items: center; gap: 0.4rem;
  font-size: 0.75rem; color: var(--text-dim);
  padding: 0.3rem 0.6rem; border-radius: 999px;
  background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.2);
}
.sync-status.syncing { background: rgba(245,158,11,0.1); border-color: rgba(245,158,11,0.2); color: var(--gold); }
.sync-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); }
.sync-status.syncing .sync-dot { background: var(--gold); animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }

select, input[type="text"], textarea {
  background: var(--bg-card); color: var(--text); border: 1px solid var(--border);
  border-radius: 8px; padding: 0.5rem 0.75rem; font-family: inherit; font-size: 0.9rem;
  outline: none; transition: border var(--transition);
}
select:focus, input:focus, textarea:focus { border-color: var(--teal); }
select { cursor: pointer; min-width: 180px; }

button {
  font-family: inherit; cursor: pointer; border: none; border-radius: 8px;
  padding: 0.5rem 1rem; font-size: 0.85rem; font-weight: 500;
  transition: all var(--transition); display: inline-flex; align-items: center; gap: 0.4rem;
}
.btn-primary { background: var(--teal); color: var(--bg); }
.btn-primary:hover { background: #5eead4; box-shadow: var(--glow-teal); }
.btn-secondary { background: var(--bg-card); color: var(--text); border: 1px solid var(--border); }
.btn-secondary:hover { background: var(--bg-card-hover); border-color: var(--teal); }
.btn-gold { background: var(--gold); color: var(--bg); }
.btn-gold:hover { background: #fbbf24; box-shadow: var(--glow-gold); }
.btn-danger { background: transparent; color: var(--red); border: 1px solid var(--red-dim); }
.btn-danger:hover { background: var(--red-dim); color: white; }
.btn-sm { padding: 0.3rem 0.6rem; font-size: 0.8rem; }
.btn-icon { background: transparent; color: var(--text-dim); padding: 0.3rem; border-radius: 6px; }
.btn-icon:hover { color: var(--text); background: var(--bg-card-hover); }

/* Layout */
.main-layout {
  display: flex; min-height: calc(100vh - 64px); max-height: calc(100vh - 64px); overflow: hidden;
}
.diagram-area {
  flex: 1; display: flex; flex-direction: column; align-items: center;
  justify-content: flex-start; padding: 1.5rem 2rem; position: relative;
  overflow-y: auto;
}
.side-panel {
  width: 380px; background: var(--bg-surface); border-left: 1px solid var(--border);
  overflow-y: auto; transition: width var(--transition), opacity var(--transition);
  display: flex; flex-direction: column;
}
.side-panel.collapsed { width: 0; overflow: hidden; opacity: 0; padding: 0; }
.side-panel-header {
  padding: 1rem 1.25rem; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.side-panel-header h2 { font-size: 1.1rem; }
.side-panel-body { padding: 1rem 1.25rem; flex: 1; overflow-y: auto; }

.toggle-panel-btn {
  position: fixed; right: 1rem; top: 5rem; z-index: 10;
  background: var(--bg-card); border: 1px solid var(--border);
  color: var(--teal); padding: 0.5rem; border-radius: 8px; cursor: pointer;
  transition: all var(--transition);
}
.toggle-panel-btn:hover { border-color: var(--teal); box-shadow: var(--glow-teal); }

/* SVG Scene */
.scene-container { width: 100%; max-width: 900px; position: relative; }
.scene-container svg { width: 100%; height: auto; max-height: 55vh; }

/* Clickable regions */
.clickable-region { cursor: pointer; transition: filter 0.2s; }
.clickable-region:hover { filter: brightness(1.2) drop-shadow(0 0 8px rgba(45,212,191,0.4)); }

/* Badge */
.badge-group { pointer-events: none; }
.badge-bg { fill: var(--gold); }
.badge-text { fill: var(--bg); font-family: 'Inter', sans-serif; font-weight: 700; font-size: 14px; }

/* Wave animation */
@keyframes wave1 { 0%, 100% { transform: translateX(0); } 50% { transform: translateX(-30px); } }
@keyframes wave2 { 0%, 100% { transform: translateX(0); } 50% { transform: translateX(20px); } }
@keyframes bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
@keyframes sunPulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 0.6; } }
.wave1 { animation: wave1 6s ease-in-out infinite; }
.wave2 { animation: wave2 5s ease-in-out infinite 0.5s; }
.boat-group { animation: bob 4s ease-in-out infinite; }
.sun-glow { animation: sunPulse 3s ease-in-out infinite; }

/* Modal */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 100;
  display: flex; align-items: center; justify-content: center;
  opacity: 0; pointer-events: none; transition: opacity 0.25s;
}
.modal-overlay.active { opacity: 1; pointer-events: auto; }
.modal {
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius);
  width: 90%; max-width: 560px; max-height: 85vh; overflow-y: auto;
  box-shadow: 0 25px 60px rgba(0,0,0,0.5); transform: translateY(20px);
  transition: transform 0.25s;
}
.modal-overlay.active .modal { transform: translateY(0); }
.modal-header {
  padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.modal-header h2 { font-size: 1.2rem; }
.modal-body { padding: 1.5rem; }

/* Items */
.item-card {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px;
  padding: 0.85rem 1rem; margin-bottom: 0.6rem;
  transition: all var(--transition); position: relative;
}
.item-card:hover { border-color: var(--teal-dim); background: var(--bg-card-hover); }
.item-card .item-text { font-size: 0.9rem; line-height: 1.4; margin-bottom: 0.3rem; }
.item-card .item-meta {
  display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; font-size: 0.75rem; color: var(--text-dim);
}
.item-card .item-actions {
  position: absolute; top: 0.5rem; right: 0.5rem; display: flex; gap: 0.2rem; opacity: 0;
  transition: opacity 0.2s;
}
.item-card:hover .item-actions { opacity: 1; }

.tag {
  display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px;
  font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em;
}
.tag-pc { background: rgba(59,130,246,0.2); color: var(--blue); }
.tag-player { background: rgba(168,85,247,0.2); color: var(--purple); }
.tag-negotiable { background: rgba(34,197,94,0.2); color: var(--green); }
.tag-non-negotiable { background: rgba(239,68,68,0.2); color: var(--red); }

/* Category header in side panel */
.category-section { margin-bottom: 1rem; }
.category-header {
  display: flex; align-items: center; gap: 0.5rem; padding: 0.6rem 0;
  cursor: pointer; user-select: none; border-bottom: 1px solid var(--border);
  margin-bottom: 0.5rem;
}
.category-header .cat-icon { font-size: 1.1rem; }
.category-header h3 { font-size: 0.95rem; flex: 1; }
.category-header .count { font-family: 'Inter', sans-serif; font-size: 0.75rem; color: var(--text-dim); }
.category-header .chevron { transition: transform 0.2s; color: var(--text-dim); }
.category-header.collapsed .chevron { transform: rotate(-90deg); }
.category-body { overflow: hidden; transition: max-height 0.3s ease; }
.category-header.collapsed + .category-body { max-height: 0 !important; overflow: hidden; }

/* Add item form */
.add-item-form { display: flex; flex-direction: column; gap: 0.75rem; margin-top: 0.75rem; }
.add-item-form textarea { min-height: 80px; resize: vertical; }
.form-row { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
.form-row label { font-size: 0.8rem; color: var(--text-dim); min-width: 60px; }

/* Balance indicator */
.balance-bar {
  display: flex; height: 8px; border-radius: 999px; overflow: hidden;
  background: var(--bg-card); margin: 0.5rem 0;
}
.balance-bar .strength { background: var(--green); transition: width 0.5s; }
.balance-bar .weakness { background: var(--red); transition: width 0.5s; }
.balance-label { font-size: 0.75rem; color: var(--text-dim); display: flex; justify-content: space-between; }

/* Suggestions */
.suggestion-card {
  background: rgba(45,212,191,0.08); border: 1px solid rgba(45,212,191,0.2);
  border-radius: 10px; padding: 0.85rem 1rem; margin-bottom: 0.5rem;
  font-size: 0.85rem; line-height: 1.5;
}
.suggestion-card::before { content: "💡 "; }

/* Settings panel */
.settings-panel {
  position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 100;
  display: flex; align-items: center; justify-content: center;
  opacity: 0; pointer-events: none; transition: opacity 0.25s;
}
.settings-panel.active { opacity: 1; pointer-events: auto; }
.settings-box {
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius);
  width: 90%; max-width: 500px; box-shadow: 0 25px 60px rgba(0,0,0,0.5);
}
.settings-box .modal-header { padding: 1.25rem 1.5rem; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
.settings-box .modal-body { padding: 1.5rem; }
.settings-box .modal-footer { padding: 1rem 1.5rem; border-top: 1px solid var(--border); display: flex; gap: 0.5rem; justify-content: flex-end; }

/* Tactician tips */
.tips-section {
  padding: 2rem; border-top: 1px solid var(--border); background: var(--bg-surface);
}
.tips-section h2 { font-size: 1.2rem; margin-bottom: 1rem; }
.tips-grid { column-count: 2; column-gap: 1rem; }
.tips-grid .tip-card { break-inside: avoid; margin-bottom: 1rem; }
.tip-card {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius);
  overflow: hidden; transition: all var(--transition);
}
.tip-card:hover { border-color: var(--gold-dim); box-shadow: var(--glow-gold); }
.tip-card-header {
  padding: 0.85rem 1rem; cursor: pointer; display: flex; align-items: center;
  justify-content: space-between; user-select: none;
}
.tip-card-header h4 { font-size: 0.9rem; font-family: 'Cinzel', serif; }
.tip-card-header .chevron { color: var(--text-dim); transition: transform 0.2s; font-size: 0.8rem; }
.tip-card-header.expanded .chevron { transform: rotate(90deg); }
.tip-card-body {
  max-height: 0; overflow: hidden; transition: max-height 0.3s ease, padding 0.3s;
  padding: 0 1rem;
}
.tip-card-body.expanded { max-height: 500px; padding: 0 1rem 1rem; }
.tip-card-body p, .tip-card-body li { font-size: 0.85rem; line-height: 1.6; color: var(--text-dim); }
.tip-card-body ul { padding-left: 1.2rem; margin-top: 0.5rem; }
.tip-card-body li { margin-bottom: 0.3rem; }

/* Toast */
.toast {
  position: fixed; bottom: 2rem; left: 50%; transform: translateX(-50%) translateY(20px);
  background: var(--bg-card); border: 1px solid var(--teal); color: var(--teal);
  padding: 0.75rem 1.5rem; border-radius: var(--radius); font-size: 0.9rem;
  opacity: 0; transition: all 0.3s; z-index: 200; pointer-events: none;
  box-shadow: var(--glow-teal);
}
.toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

/* Responsive */
@media (max-width: 900px) {
  .main-layout { flex-direction: column; }
  .side-panel { width: 100%; border-left: none; border-top: 1px solid var(--border); max-height: 50vh; }
  .side-panel.collapsed { max-height: 0; }
  .toggle-panel-btn { top: auto; bottom: 1rem; right: 1rem; }
  .top-bar { padding: 0.75rem 1rem; }
  .diagram-area { padding: 1rem; }
  .tips-grid { column-count: 1; }
}
</style>
</head>
<body>

<!-- Top Bar -->
<div class="top-bar">
  <h1>Sailboat <span>Retro</span></h1>
  <div class="party-controls">
    <select id="partySelect"></select>
    <button class="btn-secondary btn-sm" onclick="newParty()">+ New Party</button>
    <button class="btn-danger btn-sm" onclick="deleteParty()">Delete</button>
    <span style="color:var(--text-dim);font-size:0.8rem">|</span>
    <div class="sync-status" id="syncStatus">
      <span class="sync-dot"></span>
      <span id="syncLabel">Synced to Obsidian</span>
    </div>
    <button class="btn-secondary btn-sm" onclick="openSettings()">&#9881; Note</button>
    <button class="btn-secondary btn-sm" id="togglePanelBtn" onclick="toggleSidePanel()">Summary &#9656;</button>
  </div>
</div>

<!-- Main Layout -->
<div class="main-layout">
  <!-- Diagram Area -->
  <div class="diagram-area">
    <div class="scene-container">
      <svg viewBox="0 0 900 500" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="skyGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#0f1b36"/>
            <stop offset="60%" stop-color="#132347"/>
            <stop offset="100%" stop-color="#1a3a6b"/>
          </linearGradient>
          <linearGradient id="oceanGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#0c2d5e"/>
            <stop offset="100%" stop-color="#071428"/>
          </linearGradient>
          <linearGradient id="sailGrad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#f5f0e0"/>
            <stop offset="100%" stop-color="#d4c9a0"/>
          </linearGradient>
          <radialGradient id="sunGrad" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="#fbbf24"/>
            <stop offset="60%" stop-color="#f59e0b"/>
            <stop offset="100%" stop-color="#d97706"/>
          </radialGradient>
          <filter id="glow">
            <feGaussianBlur stdDeviation="3" result="blur"/>
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>

        <!-- Sky -->
        <rect width="900" height="500" fill="url(#skyGrad)"/>

        <!-- Stars -->
        <g opacity="0.4">
          <circle cx="120" cy="40" r="1.2" fill="white"/>
          <circle cx="250" cy="70" r="0.8" fill="white"/>
          <circle cx="400" cy="30" r="1" fill="white"/>
          <circle cx="550" cy="55" r="0.7" fill="white"/>
          <circle cx="700" cy="25" r="1.1" fill="white"/>
          <circle cx="820" cy="60" r="0.9" fill="white"/>
          <circle cx="180" cy="90" r="0.6" fill="white"/>
          <circle cx="650" cy="80" r="0.8" fill="white"/>
        </g>

        <!-- Sun (clickable) -->
        <g class="clickable-region" data-category="sun">
          <circle cx="130" cy="90" r="55" fill="transparent" class="hit-area"/>
          <circle cx="130" cy="90" r="50" fill="#f59e0b" opacity="0.08" class="sun-glow"/>
          <circle cx="130" cy="90" r="35" fill="#f59e0b" opacity="0.12" class="sun-glow"/>
          <circle cx="130" cy="90" r="28" fill="url(#sunGrad)" filter="url(#glow)"/>
          <g stroke="#f59e0b" stroke-width="2" opacity="0.6">
            <line x1="130" y1="55" x2="130" y2="45"/>
            <line x1="130" y1="125" x2="130" y2="135"/>
            <line x1="95" y1="90" x2="85" y2="90"/>
            <line x1="165" y1="90" x2="175" y2="90"/>
            <line x1="105" y1="65" x2="98" y2="58"/>
            <line x1="155" y1="65" x2="162" y2="58"/>
            <line x1="105" y1="115" x2="98" y2="122"/>
            <line x1="155" y1="115" x2="162" y2="122"/>
          </g>
          <text x="130" y="93" text-anchor="middle" font-family="Cinzel, serif" font-size="11" fill="#0a1628" font-weight="700">JOY</text>
          <g class="badge-group" id="badge-sun">
            <circle class="badge-bg" cx="158" cy="65" r="11"/>
            <text class="badge-text" x="158" y="69" text-anchor="middle">0</text>
          </g>
        </g>

        <!-- Ocean -->
        <rect y="290" width="900" height="210" fill="url(#oceanGrad)"/>

        <!-- Waves (animated) -->
        <g class="wave1" opacity="0.3">
          <path d="M0,310 Q50,295 100,310 Q150,325 200,310 Q250,295 300,310 Q350,325 400,310 Q450,295 500,310 Q550,325 600,310 Q650,295 700,310 Q750,325 800,310 Q850,295 900,310 L900,320 L0,320 Z" fill="#1e6091"/>
        </g>
        <g class="wave2" opacity="0.2">
          <path d="M0,320 Q60,308 120,320 Q180,332 240,320 Q300,308 360,320 Q420,332 480,320 Q540,308 600,320 Q660,332 720,320 Q780,308 840,320 Q870,332 900,320 L900,330 L0,330 Z" fill="#2980b9"/>
        </g>

        <!-- Island (clickable) -->
        <g class="clickable-region" data-category="island">
          <rect x="700" y="200" width="180" height="130" fill="transparent" class="hit-area"/>
          <ellipse cx="790" cy="295" rx="85" ry="22" fill="#8B6914"/>
          <ellipse cx="790" cy="292" rx="80" ry="18" fill="#a07d1e"/>
          <ellipse cx="790" cy="290" rx="72" ry="14" fill="#d4a43a"/>
          <rect x="798" y="230" width="6" height="60" rx="3" fill="#6d4c1a"/>
          <path d="M801,235 Q780,215 755,225" stroke="#228B22" stroke-width="5" fill="none" stroke-linecap="round"/>
          <path d="M801,235 Q820,210 845,220" stroke="#2ea043" stroke-width="5" fill="none" stroke-linecap="round"/>
          <path d="M801,232 Q785,205 770,212" stroke="#1a7a1a" stroke-width="4" fill="none" stroke-linecap="round"/>
          <path d="M801,232 Q825,200 840,208" stroke="#28a745" stroke-width="4" fill="none" stroke-linecap="round"/>
          <rect x="765" y="250" width="3" height="35" fill="#8B4513"/>
          <polygon points="768,252 790,260 768,268" fill="#ef4444"/>
          <text x="790" y="318" text-anchor="middle" font-family="Cinzel, serif" font-size="11" fill="#fef3c7" font-weight="600">GOAL</text>
          <g class="badge-group" id="badge-island">
            <circle class="badge-bg" cx="845" cy="262" r="11"/>
            <text class="badge-text" x="845" y="266" text-anchor="middle">0</text>
          </g>
        </g>

        <!-- Rocks (clickable) -->
        <g class="clickable-region" data-category="rocks">
          <rect x="590" y="270" width="100" height="80" fill="transparent" class="hit-area"/>
          <polygon points="610,310 625,280 640,310" fill="#4a4a4a"/>
          <polygon points="625,310 645,275 660,310" fill="#5a5a5a"/>
          <polygon points="650,315 662,288 678,315" fill="#4a4a4a"/>
          <polygon points="595,315 608,295 622,315" fill="#3d3d3d"/>
          <line x1="630" y1="285" x2="635" y2="300" stroke="#333" stroke-width="1"/>
          <line x1="655" y1="290" x2="660" y2="305" stroke="#333" stroke-width="1"/>
          <circle cx="620" cy="310" r="3" fill="white" opacity="0.3"/>
          <circle cx="655" cy="312" r="2" fill="white" opacity="0.25"/>
          <text x="635" y="340" text-anchor="middle" font-family="Cinzel, serif" font-size="10" fill="#ef4444" font-weight="600">RISKS</text>
          <g class="badge-group" id="badge-rocks">
            <circle class="badge-bg" cx="678" cy="275" r="11"/>
            <text class="badge-text" x="678" y="279" text-anchor="middle">0</text>
          </g>
        </g>

        <!-- Boat Group (animated bob) -->
        <g class="boat-group">
          <!-- Anchor (clickable) -->
          <g class="clickable-region" data-category="anchor">
            <rect x="345" y="315" width="70" height="135" fill="transparent" class="hit-area"/>
            <line x1="380" y1="320" x2="380" y2="380" stroke="#888" stroke-width="2" stroke-dasharray="4,3"/>
            <circle cx="380" cy="390" r="8" fill="none" stroke="#888" stroke-width="3"/>
            <line x1="380" y1="382" x2="380" y2="415" stroke="#888" stroke-width="3"/>
            <path d="M360,410 Q380,425 400,410" fill="none" stroke="#888" stroke-width="3"/>
            <line x1="365" y1="407" x2="360" y2="415" stroke="#888" stroke-width="3"/>
            <line x1="395" y1="407" x2="400" y2="415" stroke="#888" stroke-width="3"/>
            <text x="380" y="440" text-anchor="middle" font-family="Cinzel, serif" font-size="10" fill="#94a3b8" font-weight="600">ANCHOR</text>
            <g class="badge-group" id="badge-anchor">
              <circle class="badge-bg" cx="410" cy="385" r="11"/>
              <text class="badge-text" x="410" y="389" text-anchor="middle">0</text>
            </g>
          </g>

          <!-- Hull -->
          <path d="M300,295 L310,320 L450,320 L460,295 Z" fill="#6d4c1a"/>
          <path d="M305,300 L312,318 L448,318 L455,300 Z" fill="#8B6914"/>
          <line x1="310" y1="300" x2="450" y2="300" stroke="#a07d1e" stroke-width="1.5"/>

          <!-- Mast -->
          <rect x="377" y="180" width="6" height="120" fill="#5a3e10"/>

          <!-- Sails (clickable) -->
          <g class="clickable-region" data-category="sails">
            <rect x="235" y="160" width="235" height="140" fill="transparent" class="hit-area"/>
            <path d="M383,185 L383,280 L460,280 Z" fill="url(#sailGrad)" opacity="0.9"/>
            <path d="M383,185 L383,280 L460,280 Z" fill="none" stroke="#b8a070" stroke-width="1"/>
            <path d="M377,190 L377,275 L310,275 Z" fill="url(#sailGrad)" opacity="0.8"/>
            <path d="M377,190 L377,275 L310,275 Z" fill="none" stroke="#b8a070" stroke-width="1"/>
            <line x1="383" y1="220" x2="445" y2="220" stroke="#b8a070" stroke-width="0.5" opacity="0.5"/>
            <line x1="383" y1="250" x2="455" y2="250" stroke="#b8a070" stroke-width="0.5" opacity="0.5"/>
            <line x1="377" y1="225" x2="325" y2="225" stroke="#b8a070" stroke-width="0.5" opacity="0.5"/>
            <line x1="377" y1="250" x2="315" y2="250" stroke="#b8a070" stroke-width="0.5" opacity="0.5"/>
            <g stroke="#2dd4bf" stroke-width="1.5" opacity="0.5">
              <line x1="240" y1="220" x2="280" y2="220"/>
              <line x1="250" y1="240" x2="295" y2="240"/>
              <line x1="245" y1="260" x2="290" y2="260"/>
              <polyline points="275,215 280,220 275,225" fill="none"/>
              <polyline points="290,235 295,240 290,245" fill="none"/>
              <polyline points="285,255 290,260 285,265" fill="none"/>
            </g>
            <text x="400" y="175" text-anchor="middle" font-family="Cinzel, serif" font-size="11" fill="#2dd4bf" font-weight="600">SAILS</text>
            <g class="badge-group" id="badge-sails">
              <circle class="badge-bg" cx="465" cy="195" r="11"/>
              <text class="badge-text" x="465" y="199" text-anchor="middle">0</text>
            </g>
          </g>

          <!-- Crow's nest -->
          <rect x="370" y="176" width="20" height="4" rx="2" fill="#5a3e10"/>
          <!-- Flag at top -->
          <polygon points="380,176 380,162 395,169" fill="#2dd4bf" opacity="0.8"/>
        </g>

        <!-- Water reflections -->
        <g opacity="0.06">
          <rect x="320" y="325" width="120" height="2" rx="1" fill="white"/>
          <rect x="340" y="335" width="80" height="1.5" rx="1" fill="white"/>
          <rect x="350" y="342" width="60" height="1" rx="1" fill="white"/>
        </g>
      </svg>
    </div>
    <!-- Balance indicator -->
    <div style="width:100%;max-width:500px;margin-top:1rem;">
      <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.3rem;">
        <span style="font-family:Cinzel,serif;font-size:0.85rem;color:var(--cream);">Party Balance</span>
        <span id="balanceRatio" style="font-size:0.75rem;color:var(--text-dim);margin-left:auto;"></span>
      </div>
      <div class="balance-bar">
        <div class="strength" id="balanceStrength" style="width:50%"></div>
        <div class="weakness" id="balanceWeakness" style="width:50%"></div>
      </div>
      <div class="balance-label">
        <span>Strengths</span>
        <span>Weaknesses</span>
      </div>
    </div>
    <!-- Auto suggestions -->
    <div id="suggestionsArea" style="width:100%;max-width:500px;margin-top:1rem;"></div>
    <!-- Tactician Tips -->
    <div class="tips-section" style="width:100%;max-width:900px;margin-top:1.5rem;border-radius:var(--radius);background:var(--bg-surface);">
      <div style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;" onclick="toggleTipsSection()">
        <h2>Tactician Tips</h2>
        <span id="tipsChevron" style="color:var(--text-dim);font-size:1rem;transition:transform 0.2s;">&#9654;</span>
      </div>
      <div id="tipsBody" style="max-height:0;overflow:hidden;transition:max-height 0.4s ease;margin-top:0;">
        <div class="tips-grid" style="padding-top:1rem;" id="tipsGrid"></div>
      </div>
    </div>
  </div>

  <!-- Side Panel -->
  <div class="side-panel collapsed" id="sidePanel">
    <div class="side-panel-header">
      <h2>All Categories</h2>
      <button class="btn-icon" onclick="toggleSidePanel()">&#10005;</button>
    </div>
    <div class="side-panel-body" id="sidePanelBody"></div>
  </div>
</div>

<!-- Modal -->
<div class="modal-overlay" id="modalOverlay">
  <div class="modal">
    <div class="modal-header">
      <h2 id="modalTitle">Category</h2>
      <button class="btn-icon" onclick="closeModal()">&#10005;</button>
    </div>
    <div class="modal-body" id="modalBody"></div>
  </div>
</div>

<!-- Settings Panel -->
<div class="settings-panel" id="settingsPanel">
  <div class="settings-box">
    <div class="modal-header">
      <h2>Obsidian Note Settings</h2>
      <button class="btn-icon" onclick="closeSettings()">&#10005;</button>
    </div>
    <div class="modal-body">
      <div style="display:flex;flex-direction:column;gap:1rem;">
        <div>
          <label style="font-size:0.8rem;color:var(--text-dim);display:block;margin-bottom:0.3rem;">Vault Path (shared)</label>
          <input type="text" id="settingsVaultPath" style="width:100%;">
        </div>
        <div>
          <label style="font-size:0.8rem;color:var(--text-dim);display:block;margin-bottom:0.3rem;">Note Path Override (this party only, leave blank for default)</label>
          <input type="text" id="settingsNotePath" style="width:100%;" placeholder="Leave blank for auto: Sailboat Retro - [Party].md">
        </div>
        <div style="font-size:0.8rem;color:var(--text-dim);background:var(--bg-card);padding:0.75rem;border-radius:8px;">
          Current note: <span id="settingsCurrentPath" style="color:var(--teal);word-break:break-all;"></span>
        </div>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn-secondary" onclick="closeSettings()">Cancel</button>
      <button class="btn-primary" onclick="saveSettings()">Save</button>
    </div>
  </div>
</div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script>
// ─── Config ───
const API = '';  // same origin
const CATEGORIES = {
  island: { label: 'Goal (Island)', icon: '🏝️', color: '#d4a43a', allowTags: false, allowNeg: false },
  sails:  { label: 'Strengths (Sails & Wind)', icon: '⛵', color: '#2dd4bf', allowTags: true, allowNeg: false },
  anchor: { label: 'Weaknesses (Anchor)', icon: '⚓', color: '#94a3b8', allowTags: true, allowNeg: true },
  rocks:  { label: 'Risks (Rocks)', icon: '🪨', color: '#ef4444', allowTags: false, allowNeg: true },
  sun:    { label: 'Joy (Sun)', icon: '☀️', color: '#f59e0b', allowTags: false, allowNeg: false }
};

const TIPS = [
  {
    title: 'Servant Leadership',
    body: `<p>You serve your table, not the other way around. Whether you're the DM designing encounters or a player pushing a strategy, your job is to make the group better \u2014 not to be the boss.</p>
<ul><li><strong>As a player:</strong> Work with the party you have. Don't try to force teammates into builds or playstyles they didn't choose. Use your sailboat to understand their motivations, then tailor your suggestions to help them shine on their own terms</li>
<li><strong>As a DM:</strong> Your encounters and rulings should empower the table, not flex your authority. A DM who categorizes their table with the sailboat can design challenges that make every player feel essential</li>
<li>You genuinely care about the people at the table \u2014 that's what separates a tactician from an asshole. Lean into that</li></ul>`
  },
  {
    title: 'Clear Objectives',
    body: `<p>Before you deploy tactics, make sure everyone agrees on the goal. Half the conflicts at a table come from people optimizing toward different objectives without realizing it.</p>
<ul><li><strong>As a player:</strong> Share the big picture, not the micro-moves. "We need to split their forces" beats "Wizard, cast Wall of Force here, Fighter, use Action Surge on the boss." Trust your teammates to figure out the how</li>
<li><strong>As a DM:</strong> Restate the current objective at session start. "Last time, you were headed to the temple to confront..." keeps everyone aligned without railroading</li>
<li>If the table can't articulate what they're doing or why, that's the real problem to solve \u2014 not which spell to cast</li></ul>`
  },
  {
    title: 'Shared Decision-Making',
    body: `<p>Your goal is to win with a good plan, not to win with YOUR plan. The best ideas can come from anyone at the table.</p>
<ul><li><strong>As a player:</strong> Ask the party for input. "Yes, and..." their ideas. If someone has a creative approach you didn't think of, that's a gift \u2014 run with it. People who help shape the plan feel ownership, not resentment</li>
<li><strong>As a DM:</strong> When a player proposes something unexpected, your instinct might be to steer them back. Resist that. Ask "how would that work?" instead of "that won't work." You can always adapt</li>
<li>Give suggestions when asked. Ask questions instead of giving commands. You are not their boss, and even if you were \u2014 only unskilled leaders rely on the boss card to influence people</li></ul>`
  },
  {
    title: 'Spotlight Control',
    body: `<p>When things go well, put the spotlight on others. When things go wrong, put it on yourself. This applies whether you're behind the screen or in front of it.</p>
<ul><li><strong>As a player:</strong> "That Rogue play was clutch!" goes further than "my plan worked." When your strategy fails, own it: "I should have accounted for X" \u2014 don't blame the player who deviated from your script</li>
<li><strong>As a DM:</strong> Narrate player victories with enthusiasm. Rotate spotlight deliberately \u2014 if one player has dominated combat, create a moment for someone else's skills. "While that's happening, [quiet player], what is your character doing?"</li>
<li>Notice who's been quiet. A tactician who elevates everyone is a tactician who gets invited back</li></ul>`
  },
  {
    title: 'Disagree & Commit',
    body: `<p>You came together to play, not to argue. When consensus won't come, use this framework to keep the game moving.</p>
<ul><li><strong>The flowchart:</strong> Is this decision REALLY important to you? If no \u2192 commit to the group's plan and move on. If yes \u2192 try to persuade. Did it work? Great. If not \u2192 commit anyway and give it your all</li>
<li><strong>As a player:</strong> Walk the talk. When you're outvoted, don't sulk or sabotage. Do your best with the plan and let the dice decide. The more your table sees you commit gracefully, the more they'll do the same when you're in the majority</li>
<li><strong>As a DM:</strong> When the party is deadlocked, set a timer. "You have 2 minutes, then the patrol arrives." Urgency forces decisions. If they still can't agree, let the most affected character make the call</li>
<li>Make sure dissenting voices are heard and taken seriously, even if they don't carry the vote. "That's a real risk \u2014 let's keep it in mind" costs nothing and buys trust</li></ul>`
  },
  {
    title: 'Bank Account Metaphor',
    body: `<p>Every person at your table is a bank where you've opened an account. Every positive interaction is a deposit. Every time you push your agenda or do something annoying, you make a withdrawal.</p>
<ul><li><strong>Deposits:</strong> Celebrating others' wins, being prepared, making people laugh, helping a new player learn, running a great encounter, bringing snacks</li>
<li><strong>Withdrawals:</strong> Arguing about every decision, unsolicited "optimization" advice, hogging spotlight, rules lawyering, long planning monologues, underprepared sessions</li>
<li><strong>Before acting on your tactician instincts, ask:</strong> "Do I have enough in the bank for this withdrawal? Is this hill worth it?"</li>
<li>If your accounts are overdrawn, no amount of tactical brilliance will matter \u2014 people stop listening to you regardless of how right you are</li>
<li>Align your recommendations with what motivates the other person. The same suggestion framed around their goals costs less than one framed around yours</li></ul>`
  }
];

// ─── State ───
let partyData = {};
let currentParty = '';
let allParties = [];

// ─── API Layer ───
async function api(method, path, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  return res.json();
}

async function loadAll() {
  const data = await api('GET', '/api/data');
  allParties = Object.keys(data.parties);
  currentParty = data.settings.current_party;
  partyData = data.parties[currentParty] || { island: [], sails: [], anchor: [], rocks: [], sun: [] };
  renderPartySelect();
  renderAll();
}

function setSyncing(syncing) {
  const el = document.getElementById('syncStatus');
  const label = document.getElementById('syncLabel');
  if (syncing) {
    el.classList.add('syncing');
    label.textContent = 'Syncing...';
  } else {
    el.classList.remove('syncing');
    label.textContent = 'Synced to Obsidian';
  }
}

// ─── Party Management ───
async function newParty() {
  const name = prompt('Party / Table name:');
  if (!name || !name.trim()) return;
  setSyncing(true);
  const res = await api('POST', '/api/parties', { name: name.trim() });
  if (res.error) { showToast(res.error); setSyncing(false); return; }
  await loadAll();
  setSyncing(false);
  showToast('Party created & synced');
}

async function deleteParty() {
  if (allParties.length <= 1) { showToast('Cannot delete the last party'); return; }
  if (!confirm(`Delete "${currentParty}" and its Obsidian note?`)) return;
  setSyncing(true);
  await api('DELETE', `/api/parties?name=${encodeURIComponent(currentParty)}`);
  await loadAll();
  setSyncing(false);
  showToast('Party deleted');
}

function renderPartySelect() {
  const sel = document.getElementById('partySelect');
  sel.innerHTML = allParties.map(p =>
    `<option value="${esc(p)}" ${p === currentParty ? 'selected' : ''}>${esc(p)}</option>`
  ).join('');
  sel.onchange = async () => {
    setSyncing(true);
    await api('POST', '/api/switch-party', { name: sel.value });
    await loadAll();
    setSyncing(false);
  };
}

// ─── Rendering ───
function renderAll() {
  renderBadges();
  renderBalance();
  renderSuggestions();
  renderSidePanel();
}

function renderBadges() {
  for (const cat of Object.keys(CATEGORIES)) {
    const badge = document.getElementById(`badge-${cat}`);
    if (!badge) continue;
    const count = partyData[cat] ? partyData[cat].length : 0;
    badge.querySelector('.badge-text').textContent = count;
    badge.style.display = count > 0 ? '' : 'none';
  }
}

function renderBalance() {
  const s = partyData.sails ? partyData.sails.length : 0;
  const w = partyData.anchor ? partyData.anchor.length : 0;
  const total = s + w || 1;
  document.getElementById('balanceStrength').style.width = (s / total * 100) + '%';
  document.getElementById('balanceWeakness').style.width = (w / total * 100) + '%';
  document.getElementById('balanceRatio').textContent = `${s} strengths : ${w} weaknesses`;
}

function renderSuggestions() {
  const area = document.getElementById('suggestionsArea');
  const suggestions = generateSuggestions();
  if (suggestions.length === 0) { area.innerHTML = ''; return; }
  area.innerHTML = '<div style="font-family:Cinzel,serif;font-size:0.85rem;color:var(--cream);margin-bottom:0.5rem;">Auto-Generated Insights</div>' +
    suggestions.map(s => `<div class="suggestion-card">${esc(s)}</div>`).join('');
}

function generateSuggestions() {
  const suggestions = [];
  const strengths = partyData.sails || [];
  const weaknesses = partyData.anchor || [];
  const risks = partyData.rocks || [];

  if (strengths.length > 0 && weaknesses.length > 0) {
    suggestions.push(`Consider addressing "${truncate(weaknesses[0].text, 40)}" by leveraging "${truncate(strengths[0].text, 40)}".`);
  }
  if (weaknesses.length > strengths.length) {
    suggestions.push('The party has more weaknesses than strengths. Consider a session focused on team synergy.');
  }
  const negotiable = risks.filter(r => r.negotiable === true);
  const nonNeg = risks.filter(r => r.negotiable === false);
  if (negotiable.length > 0) {
    suggestions.push(`${negotiable.length} risk(s) marked as negotiable \u2014 actionable and worth addressing soon.`);
  }
  if (nonNeg.length > 0) {
    suggestions.push(`${nonNeg.length} risk(s) are non-negotiable \u2014 build strategies to work around them.`);
  }
  if (strengths.length === 0 && weaknesses.length === 0) {
    suggestions.push('Start by adding strengths and weaknesses to see balance insights.');
  }
  return suggestions;
}

function renderSidePanel() {
  const body = document.getElementById('sidePanelBody');
  body.innerHTML = Object.keys(CATEGORIES).map(cat => {
    const c = CATEGORIES[cat];
    const items = partyData[cat] || [];
    return `
      <div class="category-section">
        <div class="category-header" onclick="toggleCategory(this)">
          <span class="cat-icon">${c.icon}</span>
          <h3 style="color:${c.color}">${c.label}</h3>
          <span class="count">${items.length}</span>
          <span class="chevron">&#9660;</span>
        </div>
        <div class="category-body" style="max-height:${items.length * 100 + 60}px">
          ${items.map((item, i) => renderItemCard(cat, item, i)).join('')}
          <button class="btn-secondary btn-sm" style="width:100%;margin-top:0.3rem;" onclick="openModal('${cat}')">+ Add Item</button>
        </div>
      </div>`;
  }).join('');
}

function renderItemCard(cat, item, idx) {
  const c = CATEGORIES[cat];
  let tags = '';
  if (item.tag) {
    tags += `<span class="tag ${item.tag === 'PC' ? 'tag-pc' : 'tag-player'}">${item.tag}</span>`;
  }
  if (c.allowNeg && item.negotiable !== undefined) {
    tags += `<span class="tag ${item.negotiable ? 'tag-negotiable' : 'tag-non-negotiable'}">${item.negotiable ? 'Negotiable' : 'Non-negotiable'}</span>`;
  }
  return `
    <div class="item-card">
      <div class="item-actions">
        <button class="btn-icon btn-sm" onclick="editItem('${cat}',${idx})" title="Edit">&#9998;</button>
        <button class="btn-icon btn-sm" onclick="deleteItem('${cat}',${idx})" title="Delete">&#128465;</button>
      </div>
      <div class="item-text">${esc(item.text)}</div>
      <div class="item-meta">
        ${tags}
        ${item.notes ? `<span style="opacity:0.7">\u2014 ${esc(truncate(item.notes, 50))}</span>` : ''}
      </div>
    </div>`;
}

function toggleCategory(el) { el.classList.toggle('collapsed'); }

// ─── Modal ───
let modalCategory = null;
let editingIndex = null;
let modalOpenedAt = 0;

function openModal(cat) {
  modalCategory = cat;
  editingIndex = null;
  const c = CATEGORIES[cat];
  const items = partyData[cat] || [];

  modalOpenedAt = Date.now();
  document.getElementById('modalTitle').innerHTML = `${c.icon} ${c.label}`;
  const body = document.getElementById('modalBody');

  let html = items.map((item, i) => renderItemCard(cat, item, i)).join('');

  html += `
    <div class="add-item-form" id="addItemForm">
      <h4 style="font-family:Cinzel,serif;font-size:0.9rem;color:var(--cream);margin-top:0.5rem;" id="formTitle">Add New Item</h4>
      <textarea id="itemText" placeholder="Describe this item..."></textarea>
      ${c.allowTags ? `
        <div class="form-row">
          <label>Focus:</label>
          <select id="itemTag">
            <option value="">None</option>
            <option value="PC">PC-focused</option>
            <option value="Player">Player-focused</option>
          </select>
        </div>` : ''}
      ${c.allowNeg ? `
        <div class="form-row">
          <label>Type:</label>
          <select id="itemNeg">
            <option value="">Untagged</option>
            <option value="true">Negotiable</option>
            <option value="false">Non-negotiable</option>
          </select>
        </div>` : ''}
      <div class="form-row">
        <label>Notes:</label>
        <input type="text" id="itemNotes" placeholder="Optional notes..." style="flex:1;">
      </div>
      <div class="form-row" style="justify-content:flex-end;">
        <button class="btn-secondary btn-sm" id="cancelEditBtn" style="display:none;" onclick="cancelEdit()">Cancel Edit</button>
        <button class="btn-primary" id="saveItemBtn" onclick="saveItem()">Add Item</button>
      </div>
    </div>`;

  body.innerHTML = html;
  document.getElementById('modalOverlay').classList.add('active');
}

function closeModal() {
  document.getElementById('modalOverlay').classList.remove('active');
  modalCategory = null;
  editingIndex = null;
}

async function saveItem() {
  const text = document.getElementById('itemText').value.trim();
  if (!text) { showToast('Please enter some text'); return; }

  const c = CATEGORIES[modalCategory];
  const item = { text };

  if (c.allowTags) {
    const tagEl = document.getElementById('itemTag');
    if (tagEl && tagEl.value) item.tag = tagEl.value;
  }
  if (c.allowNeg) {
    const negEl = document.getElementById('itemNeg');
    if (negEl && negEl.value !== '') item.negotiable = negEl.value === 'true';
  }
  const notes = document.getElementById('itemNotes').value.trim();
  if (notes) item.notes = notes;

  setSyncing(true);

  if (editingIndex !== null) {
    await api('PUT', '/api/items', { category: modalCategory, index: editingIndex, item });
    editingIndex = null;
  } else {
    await api('POST', '/api/items', { category: modalCategory, item });
  }

  // Reload data
  const data = await api('GET', '/api/data');
  partyData = data.parties[currentParty];

  setSyncing(false);
  showToast('Saved & synced to Obsidian');
  openModal(modalCategory);
  renderAll();
}

function editItem(cat, idx) {
  const item = partyData[cat][idx];
  if (modalCategory !== cat) openModal(cat);

  editingIndex = idx;
  document.getElementById('itemText').value = item.text;
  const tagEl = document.getElementById('itemTag');
  if (tagEl) tagEl.value = item.tag || '';
  const negEl = document.getElementById('itemNeg');
  if (negEl) negEl.value = item.negotiable !== undefined ? String(item.negotiable) : '';
  document.getElementById('itemNotes').value = item.notes || '';
  document.getElementById('formTitle').textContent = 'Edit Item';
  document.getElementById('saveItemBtn').textContent = 'Update Item';
  document.getElementById('cancelEditBtn').style.display = '';
  document.getElementById('itemText').focus();
}

function cancelEdit() {
  editingIndex = null;
  document.getElementById('itemText').value = '';
  const tagEl = document.getElementById('itemTag');
  if (tagEl) tagEl.value = '';
  const negEl = document.getElementById('itemNeg');
  if (negEl) negEl.value = '';
  document.getElementById('itemNotes').value = '';
  document.getElementById('formTitle').textContent = 'Add New Item';
  document.getElementById('saveItemBtn').textContent = 'Add Item';
  document.getElementById('cancelEditBtn').style.display = 'none';
}

async function deleteItem(cat, idx) {
  if (!confirm('Delete this item?')) return;
  setSyncing(true);
  await api('DELETE', `/api/items?category=${cat}&index=${idx}`);
  const data = await api('GET', '/api/data');
  partyData = data.parties[currentParty];
  setSyncing(false);
  showToast('Deleted & synced');
  if (modalCategory === cat) openModal(cat);
  renderAll();
}

// ─── Side Panel ───
function toggleSidePanel() {
  const panel = document.getElementById('sidePanel');
  const btn = document.getElementById('togglePanelBtn');
  panel.classList.toggle('collapsed');
  btn.textContent = panel.classList.contains('collapsed') ? 'Summary \u25b8' : '\u25c2 Summary';
  renderSidePanel();
}

// ─── Settings ───
let settingsOpenedAt = 0;

async function openSettings() {
  settingsOpenedAt = Date.now();
  const data = await api('GET', '/api/data');
  document.getElementById('settingsVaultPath').value = data.settings.default_vault_path || '';
  const party = data.parties[currentParty];
  document.getElementById('settingsNotePath').value = (party && party._obsidian_path) || '';
  // Show computed path
  const vault = data.settings.default_vault_path || '';
  const custom = (party && party._obsidian_path) || '';
  document.getElementById('settingsCurrentPath').textContent = custom || (vault + `Sailboat Retro - ${currentParty}.md`);
  document.getElementById('settingsPanel').classList.add('active');
}

function closeSettings() {
  document.getElementById('settingsPanel').classList.remove('active');
}

async function saveSettings() {
  const vaultPath = document.getElementById('settingsVaultPath').value.trim();
  const notePath = document.getElementById('settingsNotePath').value.trim();
  setSyncing(true);
  const body = {};
  if (vaultPath) body.vault_path = vaultPath;
  if (notePath) body.obsidian_path = notePath;
  await api('POST', '/api/settings', body);
  setSyncing(false);
  closeSettings();
  showToast('Settings saved & note re-synced');
}

// ─── Tips ───
let tipsOpen = false;

function toggleTipsSection() {
  tipsOpen = !tipsOpen;
  const body = document.getElementById('tipsBody');
  const chevron = document.getElementById('tipsChevron');
  if (tipsOpen) {
    body.style.maxHeight = body.scrollHeight + 'px';
    chevron.style.transform = 'rotate(90deg)';
  } else {
    body.style.maxHeight = '0';
    chevron.style.transform = 'rotate(0deg)';
  }
}

function renderTips() {
  const grid = document.getElementById('tipsGrid');
  grid.innerHTML = TIPS.map((tip, i) => `
    <div class="tip-card">
      <div class="tip-card-header" onclick="toggleTip(${i}, this)">
        <h4>${tip.title}</h4>
        <span class="chevron">&#9654;</span>
      </div>
      <div class="tip-card-body" id="tipBody${i}">${tip.body}</div>
    </div>
  `).join('');
}

function toggleTip(idx, headerEl) {
  const body = document.getElementById(`tipBody${idx}`);
  const expanded = body.classList.toggle('expanded');
  headerEl.classList.toggle('expanded', expanded);
  if (tipsOpen) {
    setTimeout(() => {
      const tipsBody = document.getElementById('tipsBody');
      tipsBody.style.maxHeight = tipsBody.scrollHeight + 'px';
    }, 310);
  }
}

// ─── Utilities ───
function esc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function truncate(str, len) {
  return str.length > len ? str.slice(0, len) + '...' : str;
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2500);
}

// ─── Init ───
document.querySelectorAll('.clickable-region[data-category]').forEach(region => {
  const cat = region.dataset.category;
  region.style.pointerEvents = 'all';
  region.addEventListener('click', (e) => { e.stopPropagation(); e.preventDefault(); openModal(cat); });
  region.querySelectorAll('*').forEach(child => {
    child.addEventListener('click', (e) => { e.stopPropagation(); e.preventDefault(); openModal(cat); });
  });
});

document.getElementById('modalOverlay').addEventListener('mousedown', function(e) {
  if (e.target === this && Date.now() - modalOpenedAt > 300) closeModal();
});
document.getElementById('settingsPanel').addEventListener('mousedown', function(e) {
  if (e.target === this && Date.now() - settingsOpenedAt > 300) closeSettings();
});

renderTips();
loadAll();
</script>
</body>
</html>"""


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Initial sync on startup
    data = load_data()
    for party_name in data["parties"]:
        sync_obsidian(data, party_name)

    server = HTTPServer(("127.0.0.1", PORT), RetroHandler)
    print(f"Sailboat Retro running at http://localhost:{PORT}")

    if "--no-open" not in sys.argv:
        webbrowser.open(f"http://localhost:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        server.server_close()
