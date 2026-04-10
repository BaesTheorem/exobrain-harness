#!/usr/bin/env python3
"""
Things 3 ↔ Obsidian Project/Area Sync

Reads Things 3 SQLite database and syncs project/area status with Obsidian
vault notes. Runs every 15 minutes via launchd.

Sync logic:
- Active Things projects → Projects/<name>/ with status: active
- Someday Things projects → Projects/Someday/<name>/ with status: someday
- Completed/cancelled/trashed → Projects/Archive/<name>/ with status: archive
- New projects get Obsidian notes auto-created
- Area assignments are synced from Things to Obsidian frontmatter
"""

import sqlite3
import os
import re
import shutil
import json
import logging
from datetime import datetime
from pathlib import Path

# --- Configuration ---

THINGS_DB = os.path.expanduser(
    "~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/"
    "ThingsData-VE3Z1/Things Database.thingsdatabase/main.sqlite"
)
VAULT = Path(os.path.expanduser("~/Documents/Exobrain"))
PROJECTS_DIR = VAULT / "Projects"
AREAS_DIR = VAULT / "Areas"
SOMEDAY_DIR = PROJECTS_DIR / "Someday"
ARCHIVE_DIR = PROJECTS_DIR / "Archive"
LOG_FILE = "/tmp/exobrain-things3-sync.log"

# Areas to exclude from sync (Morning/Evening are ritual areas, not project areas)
EXCLUDED_AREA_TITLES = {"Morning", "Evening"}

# Projects to exclude from area requirement
AREA_EXEMPT_PROJECTS = {"Shopping list"}

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def query_things_db():
    """Read projects and areas from Things 3 SQLite database."""
    conn = sqlite3.connect(f"file:{THINGS_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # Get all areas
    areas = {}
    for row in conn.execute("SELECT uuid, title FROM TMArea"):
        title = row["title"]
        if title.lstrip("☀️🌙⚙️👥⚕️🧬🧠❤️🏠💰✨🔥💼 ").strip():
            # Strip emoji prefix to get clean name
            clean = re.sub(r"^[\U0001f300-\U0001fad6\u2600-\u27bf\ufe0f\u200d\u2764\u2b50\u26a1\u2699\u267b\U0001fa7a]+\s*", "", title).strip()
            areas[row["uuid"]] = clean

    # Get all projects (type=1)
    projects = []
    for row in conn.execute(
        "SELECT uuid, title, status, start, trashed, area, notes FROM TMTask WHERE type = 1"
    ):
        # Determine sync status
        if row["trashed"] == 1 or row["status"] in (2, 3):
            sync_status = "archive"
        elif row["start"] == 2:
            sync_status = "someday"
        else:
            sync_status = "active"

        area_name = areas.get(row["area"])

        projects.append({
            "uuid": row["uuid"],
            "title": row["title"],
            "sync_status": sync_status,
            "area_name": area_name,
            "area_uuid": row["area"],
            "notes": row["notes"] or "",
        })

    conn.close()
    return projects, areas


def parse_frontmatter(filepath):
    """Extract YAML frontmatter from a markdown file."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return None, text if 'text' in dir() else ""

    m = re.match(r"^---\n(.*?\n)---\n", text, re.DOTALL)
    if not m:
        return None, text

    fm_text = m.group(1)
    fm = {}
    for line in fm_text.strip().split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip().strip('"').strip("'")
            fm[key.strip()] = val
    return fm, text


def update_frontmatter_field(text, key, new_value):
    """Update a single frontmatter field in markdown text."""
    m = re.match(r"^(---\n)(.*?\n)(---\n)", text, re.DOTALL)
    if not m:
        return text

    fm_block = m.group(2)
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    if pattern.search(fm_block):
        fm_block = pattern.sub(f"{key}: {new_value}", fm_block)
    else:
        fm_block += f"{key}: {new_value}\n"

    return m.group(1) + fm_block + m.group(3) + text[m.end():]


def find_project_note(things_id):
    """Find an Obsidian project note by things_id in frontmatter."""
    for md in PROJECTS_DIR.rglob("*.md"):
        fm, _ = parse_frontmatter(md)
        if fm and fm.get("things_id") == things_id:
            return md
    return None


def find_project_dir(note_path):
    """Get the project directory (folder containing the note, or just the file)."""
    # If note is in a subfolder named after itself, the folder is the project unit
    parent = note_path.parent
    if parent.name == note_path.stem and parent != PROJECTS_DIR and parent not in (SOMEDAY_DIR, ARCHIVE_DIR):
        return parent
    return note_path


def target_dir_for_status(status):
    """Return the parent directory for a given project status."""
    if status == "someday":
        return SOMEDAY_DIR
    elif status == "archive":
        return ARCHIVE_DIR
    else:
        return PROJECTS_DIR


def clean_title(title):
    """Remove emoji prefixes from project titles."""
    return re.sub(r"^[\U0001f300-\U0001fad6\u2600-\u27bf\ufe0f\u200d\U0001f6d2]+\s*", "", title).strip()


def create_project_note(project):
    """Create a new Obsidian project note for a Things 3 project."""
    title = clean_title(project["title"])
    target = target_dir_for_status(project["sync_status"])
    project_dir = target / title
    project_dir.mkdir(parents=True, exist_ok=True)
    note_path = project_dir / f"{title}.md"

    area_line = ""
    if project["area_name"] and title not in AREA_EXEMPT_PROJECTS:
        area_line = f'area: "[[{project["area_name"]}]]"\n'

    content = (
        f"---\n"
        f"type: project\n"
        f"status: {project['sync_status']}\n"
        f"{area_line}"
        f"things_id: {project['uuid']}\n"
        f"created: {datetime.now().strftime('%Y-%m-%d')}\n"
        f"---\n"
        f"**Things project**: [things:///show?id={project['uuid']}](things:///show?id={project['uuid']})\n"
    )
    note_path.write_text(content, encoding="utf-8")
    log.info(f"Created note: {note_path}")

    # Update Things project notes with Obsidian backlink if missing
    return note_path


def move_project(note_path, new_status):
    """Move a project note/folder to the correct status directory."""
    project_unit = find_project_dir(note_path)
    target_parent = target_dir_for_status(new_status)
    target_parent.mkdir(parents=True, exist_ok=True)

    if project_unit.is_dir():
        dest = target_parent / project_unit.name
        if dest.exists():
            log.warning(f"Destination already exists, skipping move: {dest}")
            return note_path
        shutil.move(str(project_unit), str(dest))
        new_note = dest / note_path.name
        log.info(f"Moved folder {project_unit} → {dest}")
        return new_note
    else:
        # Single file — wrap in a folder
        folder_name = note_path.stem
        dest_dir = target_parent / folder_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / note_path.name
        if dest.exists():
            log.warning(f"Destination already exists, skipping move: {dest}")
            return note_path
        shutil.move(str(note_path), str(dest))
        log.info(f"Moved file {note_path} → {dest}")
        return dest


def current_status_from_path(note_path):
    """Infer the current status from the note's directory location."""
    parts = note_path.parts
    projects_idx = None
    for i, p in enumerate(parts):
        if p == "Projects":
            projects_idx = i
            break
    if projects_idx is None:
        return "active"

    remaining = parts[projects_idx + 1:]
    if remaining and remaining[0] == "Someday":
        return "someday"
    elif remaining and remaining[0] == "Archive":
        return "archive"
    return "active"


def sync():
    """Main sync logic."""
    log.info("Starting Things 3 ↔ Obsidian sync")

    if not Path(THINGS_DB).exists():
        log.error(f"Things DB not found: {THINGS_DB}")
        return

    projects, areas = query_things_db()
    changes = 0

    for project in projects:
        title = clean_title(project["title"])
        note_path = find_project_note(project["uuid"])

        if note_path is None:
            # Only create notes for non-ancient archived projects
            if project["sync_status"] == "archive":
                continue
            create_project_note(project)
            changes += 1
            continue

        # Check if status or area needs updating
        fm, text = parse_frontmatter(note_path)
        if fm is None:
            continue

        needs_write = False
        current_path_status = current_status_from_path(note_path)
        target_status = project["sync_status"]

        # Update status in frontmatter
        if fm.get("status") != target_status:
            text = update_frontmatter_field(text, "status", target_status)
            needs_write = True
            log.info(f"Status change: {title} → {target_status}")

        # Update area in frontmatter
        if project["area_name"] and title not in AREA_EXEMPT_PROJECTS:
            expected_area = f'"[[{project["area_name"]}]]"'
            current_area = fm.get("area", "")
            # Normalize for comparison
            clean_current = current_area.strip('"').strip("'")
            clean_expected = f"[[{project['area_name']}]]"
            if clean_current != clean_expected:
                text = update_frontmatter_field(text, "area", expected_area)
                needs_write = True
                log.info(f"Area change: {title} → {project['area_name']}")

        if needs_write:
            note_path.write_text(text, encoding="utf-8")
            changes += 1

        # Move file if directory doesn't match status
        if current_path_status != target_status:
            note_path = move_project(note_path, target_status)
            changes += 1

    log.info(f"Sync complete: {changes} change(s)")


if __name__ == "__main__":
    try:
        sync()
    except Exception as e:
        log.exception(f"Sync failed: {e}")
        raise
