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
from datetime import datetime
from pathlib import Path

OBSIDIAN_VAULT = Path(os.path.expanduser("~/Documents/Exobrain"))
DAILY_NOTES = OBSIDIAN_VAULT / "Daily notes"
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
        """Create the daily note with nav header if it doesn't exist."""
        path = self._daily_note_path()
        if path.exists():
            return path

        now = datetime.now()
        from datetime import timedelta
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        def fmt(dt):
            return dt.strftime("%A, %B ") + ordinal(dt.day) + dt.strftime(", %Y")

        yesterday_name = fmt(yesterday)
        tomorrow_name = fmt(tomorrow)
        nav = f"<< [[{yesterday_name}|Yesterday]] | [[{tomorrow_name}|Tomorrow]] >>"
        path.write_text(nav + "\n")
        return path

    def log_session(self, task_title, duration_minutes, notes, obsidian_link):
        """Log a completed pomodoro session to today's daily note."""
        now = datetime.now()
        time_str = now.strftime("%-I:%M %p")
        path = self._ensure_daily_note()

        # Build the log entry
        task_display = task_title
        if obsidian_link:
            file_match = re.search(r'file=([^&]+)', obsidian_link)
            if file_match:
                from urllib.parse import unquote
                note_name = unquote(file_match.group(1)).replace('/', ' > ')
                task_display = f"[[{note_name}|{task_title}]]"

        line = f"- **{time_str}** -- {task_display} ({duration_minutes} min)"
        if notes and notes.strip():
            line += f" -- {notes.strip()}"

        content = path.read_text()
        pomodoro_header = "### Pomodoro Log"

        if pomodoro_header in content:
            # Append under existing Pomodoro Log section
            idx = content.index(pomodoro_header) + len(pomodoro_header)
            next_section = content.find("\n### ", idx)
            if next_section == -1:
                content = content.rstrip() + "\n" + line + "\n"
            else:
                content = content[:next_section] + "\n" + line + content[next_section:]
        else:
            # Append new Pomodoro Log section at end of file
            content = content.rstrip() + "\n" + pomodoro_header + "\n" + line + "\n"

        path.write_text(content)

        subprocess.run([
            'osascript', '-e',
            f'display notification "Logged: {task_title} ({duration_minutes} min)" '
            f'with title "Pomodoro" sound name "Glass"'
        ], check=False)

        return {'success': True}

    def get_today_sessions(self):
        """Read today's pomodoro sessions from the daily note."""
        path = self._daily_note_path()
        if not path.exists():
            return []

        content = path.read_text()
        pomodoro_header = "### Pomodoro Log"

        if pomodoro_header not in content:
            return []

        idx = content.index(pomodoro_header) + len(pomodoro_header)
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
