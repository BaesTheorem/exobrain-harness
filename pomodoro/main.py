#!/usr/bin/env python3
"""Pomodoro Timer - Exobrain Edition
A Things 3-styled pomodoro timer that logs sessions to Obsidian.
"""

import webview
import json
import sqlite3
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

OBSIDIAN_VAULT = Path(os.path.expanduser("~/Exobrain"))
DAILY_NOTES = OBSIDIAN_VAULT / "Daily notes"
POMODORO_LOG = OBSIDIAN_VAULT / "Pomodoro Log.md"
THINGS_DB = Path(os.path.expanduser(
    "~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/"
    "ThingsData-VE3Z1/Things Database.thingsdatabase/main.sqlite"
))


def ordinal(n):
    suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(
        n % 10 if n % 100 not in (11, 12, 13) else 0, 'th'
    )
    return f"{n}{suffix}"


def today_header():
    now = datetime.now()
    return now.strftime("%A, %B ") + ordinal(now.day) + now.strftime(", %Y")


class API:
    _session_lines = {}
    # timer_id (int ms) → {"timer": threading.Timer, "end_ts": float,
    #                     "message": str, "is_break": bool, "remaining": float | None}
    _timers = {}

    # ─── Background timer (notify-while-minimized) ────────────────────────────

    def _notify_complete(self, timer_id):
        """Fire the completion notification. Called by threading.Timer."""
        info = self._timers.pop(timer_id, None)
        if info is None:
            return
        sound = "Purr" if info["is_break"] else "Hero"
        subprocess.run([
            'osascript', '-e',
            f'display notification "{info["message"]}" with title "Pomodoro" sound name "{sound}"'
        ], check=False)

    def _schedule(self, timer_id, seconds, message, is_break):
        timer = threading.Timer(seconds, self._notify_complete, args=[timer_id])
        timer.daemon = True
        timer.start()
        self._timers[timer_id] = {
            "timer": timer,
            "end_ts": time.time() + seconds,
            "message": message,
            "is_break": is_break,
            "remaining": None,
        }

    def _cancel(self, timer_id):
        info = self._timers.pop(timer_id, None)
        if info is not None:
            info["timer"].cancel()

    def pause_timer(self, timer_id):
        """JS calls this on pause. Returns {'remaining': seconds}."""
        info = self._timers.get(timer_id)
        if info is None:
            return {'remaining': 0}
        info["timer"].cancel()
        info["remaining"] = max(0.0, info["end_ts"] - time.time())
        return {'remaining': info["remaining"]}

    def resume_timer(self, timer_id):
        """JS calls this on resume. Re-arms with stored remaining seconds."""
        info = self._timers.get(timer_id)
        if info is None or info.get("remaining") is None:
            return {'success': False}
        seconds = info["remaining"]
        # Replace timer in place
        timer = threading.Timer(seconds, self._notify_complete, args=[timer_id])
        timer.daemon = True
        timer.start()
        info["timer"] = timer
        info["end_ts"] = time.time() + seconds
        info["remaining"] = None
        return {'success': True}

    def start_break_timer(self, duration_minutes, is_long):
        """JS calls this when starting a break. Returns {'timer_id': ...}."""
        timer_id = int(time.time() * 1000)
        msg = "Break's over! Ready to focus?"
        self._schedule(timer_id, duration_minutes * 60, msg, is_break=True)
        return {'timer_id': timer_id}

    def cancel_timer(self, timer_id):
        """JS calls this when stopping a focus or break timer pre-completion."""
        self._cancel(timer_id)
        return {'success': True}

    def get_today_tasks(self):
        """Fetch Things 3 Today tasks with project info and Obsidian backlinks."""
        try:
            conn = sqlite3.connect(f"file:{THINGS_DB}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT t.uuid, t.title, t.notes, t.type,
                       p.title AS project_title, p.notes AS project_notes,
                       COALESCE(a_task.title, a_proj.title) AS area_title,
                       COALESCE(a_task."index", a_proj."index", 999999) AS area_index,
                       COALESCE(p."index", t."index", 999999) AS project_index,
                       t.todayIndex
                FROM TMTask t
                LEFT JOIN TMTask p ON t.project = p.uuid
                LEFT JOIN TMTask a_task ON t.area = a_task.uuid
                LEFT JOIN TMTask a_proj ON p.area = a_proj.uuid
                WHERE t.status = 0
                  AND t.type IN (0, 1)
                  AND t.start = 1
                  AND t.trashed = 0
                  AND t.startDate IS NOT NULL
                ORDER BY area_index, project_index, t.todayIndex
            """)

            tasks = []
            current_area = None
            for row in cursor.fetchall():
                obsidian_link = self._extract_obsidian_link(
                    row['notes'] or row['project_notes'] or ''
                )
                area = row['area_title']
                task = {
                    'id': row['uuid'],
                    'title': row['title'],
                    'project': row['project_title'] if row['type'] == 0 else None,
                    'is_project': row['type'] == 1,
                    'area': area,
                    'show_area': area != current_area,
                    'obsidian_link': obsidian_link,
                    'things_link': f"things:///show?id={row['uuid']}",
                }
                current_area = area
                tasks.append(task)
            conn.close()
            return tasks
        except Exception as e:
            return {'error': str(e)}

    def _extract_obsidian_link(self, notes):
        match = re.search(r'obsidian://[^\s\)]+', notes)
        return match.group(0) if match else None

    def _daily_note_path(self):
        """Get today's daily note path using the vault's naming convention."""
        now = datetime.now()
        # Format: dddd, MMMM Do, YYYY (e.g., Monday, April 6th, 2026)
        name = now.strftime("%A, %B ") + ordinal(now.day) + now.strftime(", %Y")
        return DAILY_NOTES / f"{name}.md"

    def _ensure_daily_note(self):
        """Create the daily note with frontmatter + nav header if it doesn't exist.
        Frontmatter scaffold matches Templates/Daily Note.md so Bases queries work."""
        path = self._daily_note_path()
        if path.exists():
            return path

        now = datetime.now()
        iso_date = now.strftime("%Y-%m-%d")
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        def fmt(dt):
            return dt.strftime("%A, %B ") + ordinal(dt.day) + dt.strftime(", %Y")

        frontmatter = (
            "---\n"
            f"date: {iso_date}\n"
            "type: daily\n"
            "mood_score: \n"
            "mood_emotional: \n"
            "mood_energy: \n"
            "mood_self_care: \n"
            "mood_social: \n"
            "mood_purpose: \n"
            "steps: \n"
            "sleep_hours: \n"
            f'health_log: "[[Areas/Health & Fitness/Health Log/{iso_date}|Health Log]]"\n'
            "worked_on: []\n"
            "people: []\n"
            "pomodoros: \n"
            "anki_cards: \n"
            "anki_sessions: \n"
            "---\n"
        )
        nav = f"<< [[{fmt(yesterday)}|Yesterday]] | [[{fmt(tomorrow)}|Tomorrow]] >>"
        path.write_text(frontmatter + nav + "\n")
        return path

    # ─── Frontmatter helpers ──────────────────────────────────────────────────

    def _update_fm_scalar(self, content, key, value):
        """Set a scalar frontmatter field. Append if missing. Returns new content."""
        if not content.startswith("---\n"):
            return content
        end = content.find("\n---\n", 4)
        if end == -1:
            return content
        block_lines = content[4:end].split("\n")
        body = content[end + 5:]
        for i, line in enumerate(block_lines):
            stripped = line.split(":", 1)[0].strip()
            if stripped == key:
                block_lines[i] = f"{key}: {value}"
                return "---\n" + "\n".join(block_lines) + "\n---\n" + body
        block_lines.append(f"{key}: {value}")
        return "---\n" + "\n".join(block_lines) + "\n---\n" + body

    def _add_fm_list_item(self, content, key, item):
        """Add an item to a frontmatter list field if not already present.
        Handles inline empty form ('key: []') and block form. Rewrites as block form.
        Returns (new_content, changed)."""
        if not content.startswith("---\n"):
            return content, False
        end = content.find("\n---\n", 4)
        if end == -1:
            return content, False
        block_lines = content[4:end].split("\n")
        body = content[end + 5:]

        key_idx = None
        for i, line in enumerate(block_lines):
            stripped = line.split(":", 1)[0].strip()
            if stripped == key:
                key_idx = i
                break

        existing = []
        items_end = key_idx + 1 if key_idx is not None else 0

        if key_idx is not None:
            inline = re.match(r'^[^:]+:\s*\[(.*?)\]\s*$', block_lines[key_idx])
            if inline:
                items_str = inline.group(1).strip()
                if items_str:
                    existing = [x.strip() for x in items_str.split(',')]
            else:
                for j in range(key_idx + 1, len(block_lines)):
                    l = block_lines[j]
                    if l.startswith("  -") or l.startswith("- "):
                        existing.append(l.lstrip()[1:].strip())
                        items_end = j + 1
                    elif l == "":
                        items_end = j + 1
                        continue
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

    def _sync_pomodoro_count(self):
        """Recount today's sessions and update daily-note frontmatter `pomodoros`."""
        path = self._ensure_daily_note()
        content = path.read_text()
        count = len(self.get_today_sessions())
        new_content = self._update_fm_scalar(content, "pomodoros", count)
        if new_content != content:
            path.write_text(new_content)

    def _add_worked_on(self, obsidian_link):
        """If the session is linked to a Project note, add it to daily-note `worked_on`."""
        if not obsidian_link:
            return
        m = re.search(r'file=([^&]+)', obsidian_link)
        if not m:
            return
        file_path = unquote(m.group(1))
        if not file_path.startswith("Projects/") or file_path.startswith("Projects/Archive/"):
            return
        display = file_path.split("/")[-1]
        wikilink = f'"[[{file_path}|{display}]]"'
        path = self._ensure_daily_note()
        content = path.read_text()
        new_content, changed = self._add_fm_list_item(content, "worked_on", wikilink)
        if changed:
            path.write_text(new_content)

    def start_session(self, task_title, duration_minutes, obsidian_link):
        """Write a log entry when the session starts. Returns a session_id used
        later to delete (on Stop) or annotate (on completion). The session_id
        is tracked in memory; nothing is written into the log file itself."""
        now = datetime.now()
        session_id = int(now.timestamp() * 1000)
        time_str = now.strftime("%-I:%M %p")
        daily_note_name = now.strftime("%A, %B ") + ordinal(now.day) + now.strftime(", %Y")
        date_header = f"### [[{daily_note_name}]]"

        task_display = task_title
        if obsidian_link:
            file_match = re.search(r'file=([^&]+)', obsidian_link)
            if file_match:
                note_name = unquote(file_match.group(1)).replace('/', ' > ')
                task_display = f"[[{note_name}|{task_title}]]"

        line = f"- **{time_str}** -- {task_display} ({duration_minutes} min)"
        self._session_lines[session_id] = line

        content = POMODORO_LOG.read_text() if POMODORO_LOG.exists() else ""

        if date_header in content:
            # Today's section already exists — append within it (within-day stays chronological).
            idx = content.index(date_header) + len(date_header)
            next_section = content.find("\n### ", idx)
            if next_section == -1:
                content = content.rstrip() + "\n" + line + "\n"
            else:
                content = content[:next_section].rstrip() + "\n" + line + "\n" + content[next_section:]
        else:
            # New day — prepend a section at the top so day headers stay newest-first.
            new_section = date_header + "\n" + line + "\n"
            content = new_section + ("\n" + content.lstrip() if content.strip() else "")

        POMODORO_LOG.write_text(content.lstrip())
        self._sync_pomodoro_count()
        self._add_worked_on(obsidian_link)
        self._schedule(session_id, duration_minutes * 60, "Time's up — take a break", is_break=False)
        return {'session_id': session_id}

    def delete_session(self, session_id):
        """Remove the log line for this session_id (Stop before completion)."""
        self._cancel(session_id)
        line = self._session_lines.pop(session_id, None)
        if not line or not POMODORO_LOG.exists():
            return {'success': False}
        content = POMODORO_LOG.read_text()
        lines = content.split('\n')
        for i, l in enumerate(lines):
            if l == line:
                lines.pop(i)
                break
        POMODORO_LOG.write_text('\n'.join(lines))
        self._sync_pomodoro_count()
        return {'success': True}

    def update_session(self, session_id, notes):
        """Append user notes to the existing log line for this session_id."""
        self._cancel(session_id)
        line = self._session_lines.pop(session_id, None)
        if not line or not POMODORO_LOG.exists():
            return {'success': False}
        notes = (notes or '').strip()
        content = POMODORO_LOG.read_text()
        if notes:
            new_line = line + f" -- {notes}"
            lines = content.split('\n')
            for i, l in enumerate(lines):
                if l == line:
                    lines[i] = new_line
                    break
            POMODORO_LOG.write_text('\n'.join(lines))

        subprocess.run([
            'osascript', '-e',
            'display notification "Logged" with title "Pomodoro" sound name "Glass"'
        ], check=False)
        return {'success': True}

    def get_today_sessions(self):
        """Read today's pomodoro sessions from the dedicated Pomodoro Log note."""
        if not POMODORO_LOG.exists():
            return []

        content = POMODORO_LOG.read_text()
        now = datetime.now()
        daily_note_name = now.strftime("%A, %B ") + ordinal(now.day) + now.strftime(", %Y")
        date_header = f"### [[{daily_note_name}]]"

        if date_header not in content:
            return []

        idx = content.index(date_header) + len(date_header)
        next_section = content.find("\n### ", idx)
        section = content[idx:next_section] if next_section != -1 else content[idx:]

        return [
            line[2:].strip()
            for line in section.strip().split('\n')
            if line.startswith('- **')
        ]

    def notify(self, message, is_break):
        """Send macOS notification."""
        sound = "Purr" if is_break else "Hero"
        subprocess.run([
            'osascript', '-e',
            f'display notification "{message}" with title "Pomodoro" sound name "{sound}"'
        ], check=False)
        return {'success': True}


if __name__ == '__main__':
    api = API()
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
    window = webview.create_window(
        'Pomodoro',
        os.path.join(web_dir, 'index.html'),
        js_api=api,
        width=420,
        height=720,
        min_size=(360, 500),
    )
    webview.start()
