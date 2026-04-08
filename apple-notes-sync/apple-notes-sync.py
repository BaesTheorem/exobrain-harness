#!/usr/bin/env python3
"""
apple_notes_sync.py — One-way sync from Apple Notes → Obsidian vault.

Queries Apple Notes via macOS JavaScript for Automation (JXA), converts
HTML bodies to Markdown, and writes them into your Obsidian vault. Tracks
modification timestamps so only changed notes are re-synced.

Usage:
    python3 apple_notes_sync.py                # sync using default config
    python3 apple_notes_sync.py --config path  # sync using custom config
    python3 apple_notes_sync.py --full          # force full re-sync
    python3 apple_notes_sync.py --dry-run       # preview without writing
"""

import subprocess
import json
import os
import re
import sys
import hashlib
import logging
import argparse
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from html.parser import HTMLParser

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    # Path to your Obsidian vault root
    "vault_path": "~/Documents/Obsidian/YourVault",

    # Subfolder inside vault where Apple Notes land
    "notes_subfolder": "Inbox/Apple Notes",

    # Where to store sync state between runs
    "state_file": "~/.apple_notes_sync_state.json",

    # Sync options
    "sync_attachments": True,
    "delete_orphans": False,        # Delete from vault when deleted from Apple Notes
    "preserve_obsidian_links": True, # Append Obsidian links section that survives re-sync

    # Folder filters (Apple Notes folder names)
    "folders_to_sync": [],           # Empty = all folders
    "folders_to_exclude": ["Recently Deleted"],

    # Markdown output options
    "add_frontmatter": True,
    "add_readonly_banner": True,
    "filename_style": "title",       # "title" or "id"

    # Logging
    "log_level": "INFO",
}


def load_config(config_path=None):
    """Load config from JSON file, merged over defaults."""
    config = DEFAULT_CONFIG.copy()
    path = config_path or os.path.expanduser("~/.apple_notes_sync_config.json")
    if os.path.exists(path):
        with open(path) as f:
            user_config = json.load(f)
        config.update(user_config)
    return config


# ──────────────────────────────────────────────────────────────
# JXA extraction — talks to Apple Notes via osascript
# ──────────────────────────────────────────────────────────────

JXA_SCRIPT = """
'use strict';

const Notes = Application('Notes');
const result = [];

const folders = Notes.folders();
for (let fi = 0; fi < folders.length; fi++) {
    const folder = folders[fi];
    const folderName = folder.name();
    let notes;
    try {
        notes = folder.notes();
    } catch(e) {
        continue;
    }
    for (let ni = 0; ni < notes.length; ni++) {
        const note = notes[ni];
        try {
            const attachments = [];
            const noteAttachments = note.attachments();
            for (let ai = 0; ai < noteAttachments.length; ai++) {
                try {
                    const att = noteAttachments[ai];
                    attachments.push({
                        name: att.name(),
                        id: att.id(),
                        contentIdentifier: att.contentIdentifier()
                    });
                } catch(e) {}
            }

            result.push({
                id: note.id(),
                name: note.name(),
                body: note.body(),
                plaintext: note.plaintext(),
                creationDate: note.creationDate().toISOString(),
                modificationDate: note.modificationDate().toISOString(),
                folder: folderName,
                attachmentCount: attachments.length,
                attachments: attachments
            });
        } catch(e) {
            // Skip notes that error out
        }
    }
}

JSON.stringify(result);
"""


def fetch_apple_notes():
    """Run JXA to extract all notes from Apple Notes. Returns list of dicts."""
    logging.info("Querying Apple Notes via JXA...")

    # Write JXA to temp file to avoid shell escaping issues
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(JXA_SCRIPT)
        jxa_path = f.name

    try:
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", jxa_path],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            logging.error(f"osascript failed: {result.stderr}")
            sys.exit(1)

        notes = json.loads(result.stdout.strip())
        logging.info(f"Fetched {len(notes)} notes from Apple Notes")
        return notes
    finally:
        os.unlink(jxa_path)


# ──────────────────────────────────────────────────────────────
# HTML → Markdown conversion
# ──────────────────────────────────────────────────────────────

class AppleNotesHTMLToMarkdown(HTMLParser):
    """
    Converts Apple Notes HTML to Obsidian-flavored Markdown.
    Handles the common elements Apple Notes produces: headings, lists,
    bold/italic, links, images, tables, checklists, code blocks.
    """

    def __init__(self):
        super().__init__()
        self.output = []
        self.tag_stack = []
        self.list_stack = []       # ('ul'|'ol', counter)
        self.in_pre = False
        self.in_code = False
        self.in_table = False
        self.table_row = []
        self.table_rows = []
        self.href = None
        self.pending_newlines = 0
        self.checklist_item = False
        self.checked = False

    def _push(self, text):
        self.output.append(text)

    def _current_list_prefix(self):
        if not self.list_stack:
            return ""
        indent = "  " * (len(self.list_stack) - 1)
        kind, counter = self.list_stack[-1]
        if kind == "ol":
            return f"{indent}{counter}. "
        if self.checklist_item:
            return f"{indent}- [{'x' if self.checked else ' '}] "
        return f"{indent}- "

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self.tag_stack.append(tag)

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self._push("\n" + "#" * level + " ")

        elif tag == "b" or tag == "strong":
            self._push("**")

        elif tag == "i" or tag == "em":
            self._push("*")

        elif tag == "u":
            pass  # Markdown doesn't natively support underline

        elif tag == "s" or tag == "strike" or tag == "del":
            self._push("~~")

        elif tag == "code":
            if not self.in_pre:
                self._push("`")
            self.in_code = True

        elif tag == "pre":
            self._push("\n```\n")
            self.in_pre = True

        elif tag == "a":
            self.href = attrs_dict.get("href", "")

        elif tag == "img":
            src = attrs_dict.get("src", "")
            alt = attrs_dict.get("alt", "image")
            self._push(f"![{alt}]({src})")

        elif tag == "br":
            self._push("\n")

        elif tag == "ul":
            self.list_stack.append(("ul", 0))
            self._push("\n")

        elif tag == "ol":
            self.list_stack.append(("ol", 0))
            self._push("\n")

        elif tag == "li":
            if self.list_stack:
                kind, counter = self.list_stack[-1]
                if kind == "ol":
                    counter += 1
                    self.list_stack[-1] = (kind, counter)
            # Check for Apple Notes checklist
            tt_val = attrs_dict.get("style", "")
            if "checkbox" in tt_val or attrs_dict.get("class", "") == "checklist":
                self.checklist_item = True
                self.checked = "checked" in tt_val
            self._push(self._current_list_prefix())

        elif tag == "table":
            self.in_table = True
            self.table_rows = []

        elif tag == "tr":
            self.table_row = []

        elif tag in ("td", "th"):
            pass

        elif tag == "blockquote":
            self._push("\n> ")

        elif tag == "hr":
            self._push("\n---\n")

        elif tag in ("div", "p"):
            self._push("\n")

    def handle_endtag(self, tag):
        if self.tag_stack and self.tag_stack[-1] == tag:
            self.tag_stack.pop()

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._push("\n")

        elif tag == "b" or tag == "strong":
            self._push("**")

        elif tag == "i" or tag == "em":
            self._push("*")

        elif tag == "s" or tag == "strike" or tag == "del":
            self._push("~~")

        elif tag == "code":
            if not self.in_pre:
                self._push("`")
            self.in_code = False

        elif tag == "pre":
            self._push("\n```\n")
            self.in_pre = False

        elif tag == "a":
            if self.href:
                # Link text is already in output; wrap it
                self._push(f"]({self.href})")
            self.href = None

        elif tag == "li":
            self._push("\n")
            self.checklist_item = False
            self.checked = False

        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()

        elif tag in ("td", "th"):
            self.table_row.append(self._drain_cell())

        elif tag == "tr":
            self.table_rows.append(self.table_row)
            self.table_row = []

        elif tag == "table":
            self.in_table = False
            self._push(self._render_table())

        elif tag == "blockquote":
            self._push("\n")

        elif tag in ("div", "p"):
            self._push("\n")

    def handle_data(self, data):
        if self.in_pre:
            self._push(data)
            return

        if self.href and not any(t == "a" for t in self.tag_stack):
            # We already printed link text; skip
            pass

        if self.href:
            # Inside an <a> tag — prefix the link text
            self._push(f"[{data}")
        else:
            self._push(data)

    def _drain_cell(self):
        """Pull accumulated text for the current table cell."""
        # Grab everything since the last td/th start
        text = "".join(self.output).strip()
        return text

    def _render_table(self):
        """Render accumulated table rows as Markdown."""
        if not self.table_rows:
            return ""
        lines = []
        for i, row in enumerate(self.table_rows):
            lines.append("| " + " | ".join(row) + " |")
            if i == 0:
                lines.append("| " + " | ".join(["---"] * len(row)) + " |")
        return "\n" + "\n".join(lines) + "\n"

    def get_markdown(self):
        raw = "".join(self.output)
        # Clean up excessive newlines
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_markdown(html_body):
    """Convert Apple Notes HTML to Markdown string."""
    if not html_body:
        return ""

    # Apple Notes wraps everything in <div> with inline styles; strip outer wrapper
    parser = AppleNotesHTMLToMarkdown()
    try:
        parser.feed(html_body)
        return parser.get_markdown()
    except Exception as e:
        logging.warning(f"HTML parse error, falling back to plaintext: {e}")
        # Rough fallback: strip tags
        return re.sub(r"<[^>]+>", "", html_body)


# ──────────────────────────────────────────────────────────────
# Attachment handling
# ──────────────────────────────────────────────────────────────

MEDIA_BASE = os.path.expanduser(
    "~/Library/Group Containers/group.com.apple.notes/"
)

def find_attachment_file(content_id, name):
    """Try to locate an attachment file in the Apple Notes media folders."""
    # Apple stores media under Accounts/*/Media/
    for root, dirs, files in os.walk(MEDIA_BASE):
        for fname in files:
            if fname == name or content_id in root:
                return os.path.join(root, fname)
    return None


def copy_attachments(note, dest_dir):
    """Copy note attachments into the vault, return list of relative paths."""
    if not note.get("attachments"):
        return []

    att_dir = dest_dir / "_attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    for att in note["attachments"]:
        src = find_attachment_file(att.get("contentIdentifier", ""), att.get("name", ""))
        if src and os.path.exists(src):
            dest = att_dir / att["name"]
            if not dest.exists():
                import shutil
                shutil.copy2(src, dest)
            # Return vault-relative path
            paths.append(f"_attachments/{att['name']}")
        else:
            logging.debug(f"  Attachment not found: {att.get('name', 'unknown')}")

    return paths


# ──────────────────────────────────────────────────────────────
# Sync state management
# ──────────────────────────────────────────────────────────────

def load_state(state_path):
    """Load sync state: {note_id: {mod_date, hash, filename}}"""
    path = os.path.expanduser(state_path)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"last_sync": None, "notes": {}}


def save_state(state, state_path):
    path = os.path.expanduser(state_path)
    state["last_sync"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


# ──────────────────────────────────────────────────────────────
# Filename generation
# ──────────────────────────────────────────────────────────────

def sanitize_filename(name, max_len=100):
    """Make a string safe for use as a filename."""
    # Remove or replace unsafe chars
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > max_len:
        name = name[:max_len].strip()
    return name or "Untitled"


def note_filename(note, style="title"):
    """Generate a markdown filename for a note."""
    if style == "id":
        safe_id = hashlib.md5(note["id"].encode()).hexdigest()[:12]
        return f"{safe_id}.md"
    title = sanitize_filename(note.get("name", "Untitled"))
    # Deduplicate by appending short hash if needed
    short_hash = hashlib.md5(note["id"].encode()).hexdigest()[:6]
    return f"{title} ({short_hash}).md"


# ──────────────────────────────────────────────────────────────
# Markdown document assembly
# ──────────────────────────────────────────────────────────────

def build_markdown(note, config, attachment_paths=None):
    """Assemble the full Markdown document for a note."""
    parts = []

    # Frontmatter
    if config["add_frontmatter"]:
        fm = {
            "apple_notes_id": note["id"],
            "apple_notes_folder": note["folder"],
            "created": note["creationDate"],
            "modified": note["modificationDate"],
            "synced": datetime.now(timezone.utc).isoformat(),
            "source": "apple-notes-sync",
        }
        parts.append("---")
        for k, v in fm.items():
            parts.append(f'{k}: "{v}"')
        parts.append("---\n")

    # Read-only banner
    if config["add_readonly_banner"]:
        parts.append("> [!warning] Auto-synced from Apple Notes")
        parts.append("> Do not edit this file — changes will be overwritten on next sync.")
        parts.append(f"> **Source folder:** {note['folder']}\n")

    # Title
    parts.append(f"# {note.get('name', 'Untitled')}\n")

    # Body
    body_md = html_to_markdown(note.get("body", ""))
    # Strip the title if Apple Notes duplicated it as the first line
    title = note.get("name", "")
    if body_md.startswith(f"# {title}"):
        body_md = body_md[len(f"# {title}"):].lstrip("\n")
    elif body_md.startswith(title):
        body_md = body_md[len(title):].lstrip("\n")
    parts.append(body_md)

    # Attachments section
    if attachment_paths:
        parts.append("\n\n## Attachments\n")
        for p in attachment_paths:
            parts.append(f"![[{p}]]")

    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────
# Core sync logic
# ──────────────────────────────────────────────────────────────

def sync(config, full=False, dry_run=False):
    """Run the sync process."""
    vault_path = Path(os.path.expanduser(config["vault_path"]))
    notes_dir = vault_path / config["notes_subfolder"]
    notes_dir.mkdir(parents=True, exist_ok=True)

    state = load_state(config["state_file"])
    if full:
        state["notes"] = {}

    # Fetch all notes
    all_notes = fetch_apple_notes()

    # Filter folders
    include = set(config["folders_to_sync"]) if config["folders_to_sync"] else None
    exclude = set(config["folders_to_exclude"])

    notes = []
    for n in all_notes:
        folder = n.get("folder", "")
        if folder in exclude:
            continue
        if include and folder not in include:
            continue
        notes.append(n)

    logging.info(f"Processing {len(notes)} notes after folder filtering")

    # Track which note IDs we see this run (for orphan detection)
    seen_ids = set()
    synced = 0
    skipped = 0

    for note in notes:
        nid = note["id"]
        seen_ids.add(nid)
        mod = note["modificationDate"]

        # Check if note has changed since last sync
        prev = state["notes"].get(nid, {})
        if prev.get("mod_date") == mod and not full:
            skipped += 1
            continue

        fname = note_filename(note, config["filename_style"])

        # If filename changed (title edit), remove old file
        old_fname = prev.get("filename")
        if old_fname and old_fname != fname:
            old_path = notes_dir / old_fname
            if old_path.exists():
                if dry_run:
                    logging.info(f"  [DRY RUN] Would remove renamed: {old_fname}")
                else:
                    old_path.unlink()
                    logging.info(f"  Removed old file (renamed): {old_fname}")

        # Handle attachments
        att_paths = []
        if config["sync_attachments"] and note.get("attachmentCount", 0) > 0:
            if not dry_run:
                att_paths = copy_attachments(note, notes_dir)

        # Build markdown
        md = build_markdown(note, config, att_paths)
        dest = notes_dir / fname

        if dry_run:
            logging.info(f"  [DRY RUN] Would write: {fname}")
        else:
            dest.write_text(md, encoding="utf-8")
            logging.info(f"  Synced: {fname}")

        # Update state
        state["notes"][nid] = {
            "mod_date": mod,
            "filename": fname,
            "folder": note["folder"],
        }
        synced += 1

    # Handle orphaned notes (deleted from Apple Notes)
    if config["delete_orphans"]:
        orphan_ids = set(state["notes"].keys()) - seen_ids
        for oid in orphan_ids:
            info = state["notes"][oid]
            orphan_path = notes_dir / info["filename"]
            if orphan_path.exists():
                if dry_run:
                    logging.info(f"  [DRY RUN] Would delete orphan: {info['filename']}")
                else:
                    orphan_path.unlink()
                    logging.info(f"  Deleted orphan: {info['filename']}")
            del state["notes"][oid]

    if not dry_run:
        save_state(state, config["state_file"])

    logging.info(f"Sync complete: {synced} synced, {skipped} unchanged")
    return synced, skipped


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sync Apple Notes → Obsidian vault"
    )
    parser.add_argument(
        "--config", "-c",
        help="Path to config JSON (default: ~/.apple_notes_sync_config.json)"
    )
    parser.add_argument(
        "--full", "-f",
        action="store_true",
        help="Force full re-sync (ignore previous state)"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Preview what would happen without writing files"
    )
    args = parser.parse_args()

    config = load_config(args.config)

    logging.basicConfig(
        level=getattr(logging, config["log_level"]),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    sync(config, full=args.full, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
