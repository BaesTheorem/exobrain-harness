#!/bin/bash
# vault-snapshot.sh — Build a compact snapshot of the Obsidian vault for session-start injection.
# Output is written outside the repo (private), and consumed by .claude/hooks/session-start.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

DASHBOARD="$VAULT_DIR/Dashboard.md"
PROJECTS_DIR="$VAULT_DIR/Projects"
OUT_DIR="$HOME/.claude/projects/-Users-alexhedtke-Documents-Exobrain-harness"
OUT="$OUT_DIR/vault-snapshot.md"

mkdir -p "$OUT_DIR"

NOW_ISO=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Build to a temp file, then atomic mv at the end
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

{
    echo "---"
    echo "generated_at: $NOW_ISO"
    echo "sources: [Dashboard.md, Projects/*]"
    echo "---"
    echo ""
    echo "## Dashboard"
    if [ -f "$DASHBOARD" ]; then
        cat "$DASHBOARD"
    else
        echo "_(missing — $DASHBOARD)_"
    fi
    echo ""
    echo "## Active Projects"
    if [ -d "$PROJECTS_DIR" ]; then
        # Collect candidate project notes:
        #   - Top-level .md files in Projects/ (e.g. "Order HPMOR hardcovers.md")
        #   - <Folder>/<Folder>.md inside each subdir (the project's main note)
        # Skip anything under Archive/ or Someday/.
        python3 - "$PROJECTS_DIR" <<'PY'
import os, re, sys

PROJECTS = sys.argv[1]
SKIP_DIRS = {"Archive", "Someday"}

candidates = {}  # name -> (path, mtime); folder version wins over top-level on collision

# Top-level .md (added first so folder version overwrites)
for entry in os.listdir(PROJECTS):
    full = os.path.join(PROJECTS, entry)
    if entry.startswith("."):
        continue
    if os.path.isfile(full) and entry.endswith(".md"):
        name = entry[:-3]
        candidates[name] = (full, os.path.getmtime(full))

# Then <Folder>/<Folder>.md — overwrites top-level if same name
for entry in os.listdir(PROJECTS):
    full = os.path.join(PROJECTS, entry)
    if entry.startswith("."):
        continue
    if os.path.isdir(full) and entry not in SKIP_DIRS:
        main = os.path.join(full, entry + ".md")
        if os.path.isfile(main):
            candidates[entry] = (main, os.path.getmtime(main))

def parse_status(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            head = f.read(2048)
    except Exception:
        return None
    m = re.match(r"^---\n(.*?)\n---", head, re.DOTALL)
    if not m:
        return None
    fm = m.group(1)
    sm = re.search(r"^status:\s*(.+?)\s*$", fm, re.MULTILINE)
    return sm.group(1).strip() if sm else None

rows = []
for name, (path, mtime) in candidates.items():
    status = parse_status(path)
    if status in ("archived", "done", "completed"):
        continue
    rows.append((path, name, mtime, status or "(no status)"))

# Sort: active first, then by mtime desc
def sort_key(r):
    _path, _name, mtime, status = r
    active_rank = 0 if status == "active" else 1
    return (active_rank, -mtime)

rows.sort(key=sort_key)

import datetime
for path, name, mtime, status in rows:
    rel = os.path.relpath(path, os.path.dirname(PROJECTS))
    date_str = datetime.date.fromtimestamp(mtime).isoformat()
    print(f"- **{name}** — status: {status}")
    print(f"  - Last modified: {date_str}")
    print(f"  - Path: {rel}")
PY
    else
        echo "_(Projects directory missing — $PROJECTS_DIR)_"
    fi
} > "$TMP"

mv "$TMP" "$OUT"
trap - EXIT

# Sanity bound — warn if file blows past 4 KB
SIZE=$(stat -f %z "$OUT")
if [ "$SIZE" -gt 4096 ]; then
    echo "WARN: vault-snapshot.md is ${SIZE} bytes (>4 KB target)" >&2
fi

echo "Wrote $OUT (${SIZE} bytes)"
