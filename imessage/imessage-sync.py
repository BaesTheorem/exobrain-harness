#!/usr/bin/env python3
"""
iMessage Sync for Exobrain — the Full-Disk-Access half of the reader.

WHY THIS EXISTS
---------------
Reading ~/Library/Messages/chat.db requires macOS Full Disk Access (FDA). TCC
grants FDA per *binary path*. When Claude Code shells out to python, the process
accessing chat.db is attributed to the Claude Code binary, which lives at a
versioned path that changes on every CC update — so the grant silently breaks
each time CC updates.

The fix: run THIS script under a stable interpreter path via launchd, and grant
FDA to that path exactly once. NOTE: /usr/bin/python3 is NOT that path — it's an
xcrun stub whose real exec target is the Command Line Tools python at a versioned
path (/Library/Developer/CommandLineTools/...), and TCC keys on that moving
target, so an FDA grant to the stub never applies. Instead we run under a
dedicated `python3.12 -m venv --copies` interpreter (imessage/.venv/bin/python3.12,
a real Mach-O copy at a fixed path we own, gitignored) that survives brew/CLT
updates. Grant FDA to THAT binary once. This script takes a
consistent snapshot of chat.db into imessage/cache/ and caches the contacts map.
imessage-reader.py then reads the *cache* (an ordinary file, no FDA needed), so
Claude never touches the protected path.

WHAT IT WRITES (all under imessage/cache/, which is gitignored)
    chat.db          — consistent snapshot via sqlite's online-backup API
    contacts.json    — {normalized_phone: "First Last"} built from AddressBook
    sync-status.json — {ok, synced_at, message_count, error} so a failed sync is
                       visible, never silent

Run manually (only works if the calling process has FDA):
    .venv/bin/python3 imessage-sync.py
Normally run by launchd: com.exobrain.imessage-sync (every 15 min + at load).
"""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HOME = Path.home()
LIVE_DB = HOME / "Library" / "Messages" / "chat.db"
CONTACTS_DIR = HOME / "Library" / "Application Support" / "AddressBook" / "Sources"

CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_DB = CACHE_DIR / "chat.db"
CACHE_CONTACTS = CACHE_DIR / "contacts.json"
STATUS_FILE = CACHE_DIR / "sync-status.json"


def _normalize_phone(number):
    """Strip non-digit chars, keep leading +. Mirror of the reader's logic."""
    if not number:
        return number
    digits = "".join(c for c in number if c.isdigit() or c == "+")
    if digits.startswith("1") and len(digits) == 11:
        digits = "+" + digits
    elif len(digits) == 10:
        digits = "+1" + digits
    return digits


def build_contacts():
    """Build a phone->name map from every AddressBook source database."""
    contacts = {}
    if not CONTACTS_DIR.is_dir():
        return contacts
    for source in os.listdir(CONTACTS_DIR):
        db_path = CONTACTS_DIR / source / "AddressBook-v22.abcddb"
        if not db_path.is_file():
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            rows = conn.execute(
                """
                SELECT p.ZFULLNUMBER, r.ZFIRSTNAME, r.ZLASTNAME
                FROM ZABCDPHONENUMBER p
                JOIN ZABCDRECORD r ON p.ZOWNER = r.Z_PK
                WHERE p.ZFULLNUMBER IS NOT NULL
                """
            ).fetchall()
            for phone, first, last in rows:
                name = " ".join(filter(None, [first, last])) or None
                if name:
                    contacts[_normalize_phone(phone)] = name
            conn.close()
        except Exception:
            # A single unreadable source shouldn't sink the whole sync.
            continue
    return contacts


def snapshot_db():
    """Take a consistent snapshot of chat.db (WAL-safe) into the cache.

    Uses sqlite's online-backup API from a read-only source connection so we get
    a single self-contained file that already includes any -wal contents. Writes
    to a temp file first, then atomically renames, so the reader never sees a
    half-written database.

    Returns the message count in the snapshot.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Read-only source. Not `immutable=1` — we WANT the WAL applied so recent
    # messages are included.
    src = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(CACHE_DIR), suffix=".tmp")
    os.close(tmp_fd)
    try:
        dst = sqlite3.connect(tmp_path)
        with dst:
            src.backup(dst)
        count = dst.execute("SELECT COUNT(*) FROM message").fetchone()[0]
        dst.close()
        os.replace(tmp_path, CACHE_DB)  # atomic
        return count
    finally:
        src.close()
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def write_status(ok, message_count=None, error=None):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    status = {
        "ok": ok,
        "synced_at": datetime.now().isoformat(timespec="seconds"),
        "message_count": message_count,
        "error": error,
    }
    STATUS_FILE.write_text(json.dumps(status, indent=2))


def main():
    if not LIVE_DB.exists():
        write_status(False, error=f"chat.db not found at {LIVE_DB}")
        print(f"Error: chat.db not found at {LIVE_DB}", file=sys.stderr)
        return 1
    try:
        count = snapshot_db()
    except (sqlite3.OperationalError, sqlite3.DatabaseError, PermissionError) as e:
        msg = str(e)
        if "authorization denied" in msg or "unable to open" in msg or "not permitted" in msg or isinstance(e, PermissionError):
            hint = (
                "Full Disk Access not granted to this interpreter. Grant FDA to "
                f"{sys.executable} (System Settings > Privacy & Security > Full "
                "Disk Access), then reload com.exobrain.imessage-sync."
            )
            write_status(False, error=f"FDA denied: {msg}")
            print(f"Error: {hint}", file=sys.stderr)
            return 1
        write_status(False, error=msg)
        print(f"Error: {msg}", file=sys.stderr)
        return 1

    # Contacts are best-effort — a failure here shouldn't fail the whole sync.
    try:
        contacts = build_contacts()
        tmp = CACHE_CONTACTS.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(contacts, ensure_ascii=False, indent=0))
        os.replace(tmp, CACHE_CONTACTS)
        n_contacts = len(contacts)
    except Exception as e:
        n_contacts = -1
        print(f"Warning: contacts cache failed: {e}", file=sys.stderr)

    write_status(True, message_count=count)
    print(f"Synced chat.db snapshot ({count} messages) + {n_contacts} contacts to {CACHE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
