#!/usr/bin/env python3
"""Anki Session Sync — read Anki SQLite and write to Obsidian.

Mirrors the pomodoro module's pattern:
  - Sessions are written to ~/Exobrain/Anki Log.md (H3 date headers + bullet lines)
  - Today's daily note frontmatter is updated with anki_cards + anki_minutes
  - Active study Projects are appended to worked_on:

Idempotent: every run rewrites today's section in Anki Log.md and refreshes
today's daily-note frontmatter from scratch. Designed for polling by launchd
every 10 min.

Anki DB is read read-only (`?mode=ro`) so it's safe to read while Anki is open.

Stdlib only.
"""

import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ANKI_DB = Path.home() / "Library/Application Support/Anki2/User 1/collection.anki2"
VAULT = Path.home() / "Exobrain"
DAILY_NOTES = VAULT / "Daily notes"
ANKI_LOG = VAULT / "Anki Log.md"

# Minutes of idle time between reviews that starts a new session.
# 30 captures realistic study blocks (a 25-min lunch break still counts as
# "same session"); a fresh session reflects genuinely leaving and coming back.
SESSION_GAP_MIN = 30

# Deck-name pattern → (display label, Project wikilink for worked_on).
# First match wins. Patterns are case-insensitive.
PROJECT_MAPPINGS = [
    (re.compile(r"security\+|messer", re.I),
     "Security+",
     '"[[Projects/Get new job/Security+ Certification|Security+ Certification]]"'),
    (re.compile(r"az-?900", re.I),
     "AZ-900",
     '"[[Projects/Get new job/MS learnings|MS learnings]]"'),
]


# ─── Date helpers ──────────────────────────────────────────────────────────────

def ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def daily_note_filename(d) -> str:
    return f"{d.strftime('%A, %B')} {d.day}{ordinal(d.day)}, {d.year}.md"


# ─── Anki read ─────────────────────────────────────────────────────────────────

def read_today_reviews() -> list[tuple[int, str, int]]:
    """Return (timestamp_ms, deck_name, time_ms) for today's reviews."""
    if not ANKI_DB.exists():
        return []
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff_ms = int(today_start.timestamp() * 1000)
    try:
        conn = sqlite3.connect(f"file:{ANKI_DB}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return []
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT r.id, d.name, r.time
        FROM revlog r
        JOIN cards c ON r.cid = c.id
        JOIN decks d ON c.did = d.id
        WHERE r.id > ?
        ORDER BY r.id
    """, (cutoff_ms,)).fetchall()
    conn.close()
    return rows


def classify_deck(deck_name: str) -> tuple[str | None, str | None]:
    """Return (display_label, project_wikilink) for the first matching mapping, or (None, None)."""
    for pattern, label, project in PROJECT_MAPPINGS:
        if pattern.search(deck_name):
            return label, project
    return None, None


# ─── Session grouping ──────────────────────────────────────────────────────────

def group_sessions(reviews, gap_min=SESSION_GAP_MIN):
    """Cluster reviews into sessions by idle gap. Returns list of session dicts."""
    if not reviews:
        return []
    gap_ms = gap_min * 60 * 1000

    sessions = []
    current = None
    for ts, deck, t_ms in reviews:
        if current is None or ts - current["end_ms"] > gap_ms:
            if current is not None:
                sessions.append(current)
            current = {
                "start_ms": ts,
                "end_ms": ts,
                "cards": 0,
                "time_ms": 0,
                "deck_counts": {},
            }
        current["end_ms"] = ts
        current["cards"] += 1
        current["time_ms"] += t_ms
        label, project = classify_deck(deck)
        bucket = label if label else "Other"
        current["deck_counts"][bucket] = current["deck_counts"].get(bucket, 0) + 1
    sessions.append(current)
    return sessions


def primary_label(session) -> str:
    counts = session["deck_counts"]
    if not counts:
        return "Anki"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def projects_for_today(reviews) -> set[str]:
    """Return the set of project wikilinks that should be added to worked_on for today."""
    out = set()
    for _, deck, _ in reviews:
        _, project = classify_deck(deck)
        if project:
            out.add(project)
    return out


# ─── Anki Log.md write ─────────────────────────────────────────────────────────

def format_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%-I:%M %p")


def session_line(session) -> str:
    primary = primary_label(session)
    minutes = max(1, round(session["time_ms"] / 60000))
    return f"- **{format_time(session['start_ms'])}** -- {primary} ({session['cards']} cards, {minutes} min)"


def rewrite_anki_log(sessions, today_label: str) -> None:
    """Place today's section at the TOP of Anki Log.md (newest-first ordering)."""
    date_header = f"### [[{today_label}]]"
    existing = ANKI_LOG.read_text() if ANKI_LOG.exists() else ""

    # Strip today's old section if it's already in the file (anywhere)
    if date_header in existing:
        idx = existing.index(date_header)
        next_idx = existing.find("\n### ", idx + len(date_header))
        head = existing[:idx].rstrip()
        tail = "" if next_idx == -1 else existing[next_idx + 1:].lstrip()
        existing = (head + ("\n\n" if head and tail else "") + tail).strip()

    new_section = "\n".join([date_header] + [session_line(s) for s in sessions])

    if existing:
        ANKI_LOG.write_text(new_section + "\n\n" + existing + "\n")
    else:
        ANKI_LOG.write_text(new_section + "\n")


# ─── Daily note frontmatter ────────────────────────────────────────────────────

def update_fm_scalar(content: str, key: str, value) -> str:
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---\n", 4)
    if end == -1:
        return content
    block_lines = content[4:end].split("\n")
    body = content[end + 5:]
    for i, line in enumerate(block_lines):
        if line.split(":", 1)[0].strip() == key:
            block_lines[i] = f"{key}: {value}"
            return "---\n" + "\n".join(block_lines) + "\n---\n" + body
    block_lines.append(f"{key}: {value}")
    return "---\n" + "\n".join(block_lines) + "\n---\n" + body


def add_fm_list_item(content: str, key: str, item: str) -> tuple[str, bool]:
    if not content.startswith("---\n"):
        return content, False
    end = content.find("\n---\n", 4)
    if end == -1:
        return content, False
    block_lines = content[4:end].split("\n")
    body = content[end + 5:]

    key_idx = None
    for i, line in enumerate(block_lines):
        if line.split(":", 1)[0].strip() == key:
            key_idx = i
            break

    existing = []
    items_end = key_idx + 1 if key_idx is not None else 0
    if key_idx is not None:
        inline = re.match(r'^[^:]+:\s*\[(.*?)\]\s*$', block_lines[key_idx])
        if inline:
            inner = inline.group(1).strip()
            if inner:
                existing = [x.strip() for x in inner.split(",")]
        else:
            for j in range(key_idx + 1, len(block_lines)):
                l = block_lines[j]
                if l.startswith("  -") or l.startswith("- "):
                    existing.append(l.lstrip()[1:].strip())
                    items_end = j + 1
                elif l == "":
                    items_end = j + 1
                else:
                    break

    if item in existing:
        return content, False

    new_items = existing + [item]
    new_lines = [f"{key}:"] + [f"  - {it}" for it in new_items]
    if key_idx is None:
        block_lines = block_lines + new_lines
    else:
        block_lines = block_lines[:key_idx] + new_lines + block_lines[items_end:]
    return "---\n" + "\n".join(block_lines) + "\n---\n" + body, True


def update_daily_note(sessions, today, projects) -> None:
    fname = daily_note_filename(today)
    path = DAILY_NOTES / fname
    if not path.exists():
        return  # don't create the daily note from here; pomodoro/skills do that
    content = path.read_text()
    total_cards = sum(s["cards"] for s in sessions)
    session_count = len(sessions)
    content = update_fm_scalar(content, "anki_cards", total_cards)
    content = update_fm_scalar(content, "anki_sessions", session_count)
    for p in projects:
        content, _ = add_fm_list_item(content, "worked_on", p)
    path.write_text(content)


# ─── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    reviews = read_today_reviews()
    sessions = group_sessions(reviews)
    today = datetime.now().date()
    today_label = daily_note_filename(today)[:-3]  # strip ".md"

    if sessions:
        rewrite_anki_log(sessions, today_label)
    update_daily_note(sessions, today, projects_for_today(reviews))

    total_cards = sum(s["cards"] for s in sessions)
    print(f"{datetime.now():%H:%M} sync: {len(sessions)} sessions, {total_cards} cards today")
    return 0


if __name__ == "__main__":
    sys.exit(main())
