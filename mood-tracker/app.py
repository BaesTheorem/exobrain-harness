#!/usr/bin/env python3
"""
Alex's Mood Tracker — Exobrain Module
A self-contained mood tracking web app with heatmap calendar, sub-category scoring,
weekly summaries, trend visualization, and Obsidian sync.
No external dependencies — uses Python stdlib only.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import webbrowser

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mood-data.json")
MOOD_JOURNAL = "/Users/alexhedtke/Documents/Exobrain/Mood Journal.md"
PORT = 5174

SCORE_COLORS = {
    1: "#e74c3c", 1.5: "#e25b2c",
    2: "#e67e22", 2.5: "#ea9a1e",
    3: "#f1c40f", 3.5: "#9bce3f",
    4: "#2ecc71", 4.5: "#2db4c7",
    5: "#3498db"
}

SCORE_LABELS = {1: "Struggling", 2: "Low", 3: "Neutral", 4: "Good", 5: "Thriving"}
SCORE_EMOJI = {1: "\U0001f534", 2: "\U0001f7e0", 3: "\U0001f7e1", 4: "\U0001f7e2", 5: "\U0001f535"}

CATEGORIES = ["emotional", "energy", "self_care", "social", "purpose"]
CAT_LABELS = {
    "emotional": "Emotional State",
    "energy": "Energy",
    "self_care": "Self-Care",
    "social": "Social",
    "purpose": "Purpose"
}

FLAG_OPTIONS = [
    "bedtime_drift", "sleep_deficit", "self_care_slip", "social_marathon_start",
    "post_social_crash", "declining_trend", "recovery_needed", "procrastination",
    "alcohol", "high_stress", "breakthrough", "good_sleep", "exercise_win"
]


# ─── Data Layer ───────────────────────────────────────────────────────────────

def load_data():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_color(score):
    if score is None:
        return "#2c2c2c"
    rounded = round(score * 2) / 2
    return SCORE_COLORS.get(rounded, "#2c2c2c")

def get_label(score):
    if score is None:
        return "—"
    rounded = int(round(score))
    return SCORE_LABELS.get(min(max(rounded, 1), 5), "—")

def get_emoji(score):
    if score is None:
        return ""
    rounded = int(round(score))
    return SCORE_EMOJI.get(min(max(rounded, 1), 5), "")

def get_week_bounds(date_str):
    """Get Monday-Sunday bounds for the week containing the given date."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")

def compute_weekly_summary(data, week_start):
    """Compute weekly summary from daily entries."""
    ws = datetime.strptime(week_start, "%Y-%m-%d")
    we = ws + timedelta(days=6)
    entries = [e for e in data["entries"]
               if ws <= datetime.strptime(e["date"], "%Y-%m-%d") <= we]
    if not entries:
        return None

    summary = {
        "week_start": week_start,
        "week_end": we.strftime("%Y-%m-%d"),
        "overall": round(sum(e["overall"] for e in entries) / len(entries), 1),
    }
    for cat in CATEGORIES:
        vals = [e[cat] for e in entries if e.get(cat) is not None]
        summary[cat] = round(sum(vals) / len(vals), 1) if vals else None

    # Find prior week summary for trend
    prior_start = (ws - timedelta(days=7)).strftime("%Y-%m-%d")
    prior = next((s for s in data.get("weekly_summaries", [])
                  if s["week_start"] == prior_start), None)
    if prior:
        diff = summary["overall"] - prior["overall"]
        summary["trend"] = "up" if diff > 0.3 else "down" if diff < -0.3 else "flat"
    else:
        summary["trend"] = None

    return summary

def get_streak_info(data):
    """Get current streak info — consecutive days scored."""
    entries = sorted(data["entries"], key=lambda e: e["date"], reverse=True)
    if not entries:
        return {"streak": 0, "last_date": None}
    streak = 1
    for i in range(1, len(entries)):
        prev = datetime.strptime(entries[i-1]["date"], "%Y-%m-%d")
        curr = datetime.strptime(entries[i]["date"], "%Y-%m-%d")
        if (prev - curr).days == 1:
            streak += 1
        else:
            break
    return {"streak": streak, "last_date": entries[0]["date"]}

def get_trends(data, days=14):
    """Get trend data for the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    entries = sorted(
        [e for e in data["entries"] if e["date"] >= cutoff],
        key=lambda e: e["date"]
    )
    return entries


# ─── Obsidian Sync ────────────────────────────────────────────────────────────

def sync_obsidian(data):
    """Regenerate the full Mood Journal note from data."""
    entries = sorted(data["entries"], key=lambda e: e["date"])
    if not entries:
        return

    lines = []
    lines.append("<< [[Dashboard]] >>")
    lines.append("[Open Mood Tracker](http://localhost:5174) \u00b7 [Launch App](file:///Users/alexhedtke/Desktop/MoodTracker.app)")
    lines.append("")

    # ─── Calendar Heatmaps ───
    # Group entries by month
    months = {}
    for e in entries:
        dt = datetime.strptime(e["date"], "%Y-%m-%d")
        key = (dt.year, dt.month)
        months.setdefault(key, {})[dt.day] = e["overall"]

    # Also include current month even if no entries
    now = datetime.now()
    curr_key = (now.year, now.month)
    if curr_key not in months:
        months[curr_key] = {}

    for (year, month) in sorted(months.keys(), reverse=True):
        scores = months[(year, month)]
        month_name = datetime(year, month, 1).strftime("%B %Y")

        lines.append('<div style="margin-bottom: 20px;">')
        lines.append('<table style="border-collapse: separate; border-spacing: 3px; font-family: monospace; font-size: 12px;">')
        lines.append(f'<caption style="font-weight: bold; margin-bottom: 4px; font-size: 14px;">{month_name}</caption>')
        lines.append("<tr>")
        for day_name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            lines.append(f'<th style="padding: 4px 8px;">{day_name}</th>')
        lines.append("</tr>")

        # Build weeks
        import calendar
        cal = calendar.monthcalendar(year, month)
        for week in cal:
            lines.append("<tr>")
            for day in week:
                if day == 0:
                    lines.append('<td style="padding: 6px 8px; background-color: transparent; text-align: center;"></td>')
                else:
                    score = scores.get(day)
                    bg = get_color(score)
                    if score is not None:
                        dt = datetime(year, month, day)
                        title = f' title="{dt.strftime("%b %d")} — {score}/5"'
                        color = "white"
                    else:
                        title = ""
                        color = "#555"
                    lines.append(f'<td style="padding: 6px 8px; background-color: {bg}; color: {color}; text-align: center; border-radius: 4px;"{title}>{day}</td>')
            lines.append("</tr>")
        lines.append("</table>")
        lines.append("</div>")
        lines.append("")

    lines.append("**Legend:** \U0001f535 5 Thriving | \U0001f7e2 4 Good | \U0001f7e1 3 Neutral | \U0001f7e0 2 Low | \U0001f534 1 Struggling")
    lines.append("")
    lines.append("---")

    # ─── Weekly Summaries ───
    lines.append("## Weekly Summaries")

    summaries = sorted(data.get("weekly_summaries", []),
                       key=lambda s: s["week_start"], reverse=True)
    for s in summaries:
        ws = datetime.strptime(s["week_start"], "%Y-%m-%d")
        we = datetime.strptime(s["week_end"], "%Y-%m-%d")
        label = f"{ws.strftime('%B %d')}–{we.strftime('%d, %Y')}"
        emoji = get_emoji(s["overall"])
        trend_str = ""
        if s.get("trend") == "up":
            trend_str = " ↑"
        elif s.get("trend") == "down":
            trend_str = " ↓"
        elif s.get("trend") == "flat":
            trend_str = " →"

        lines.append(f"### Week of {label}")
        lines.append(f"**Overall: {s['overall']}/5** {emoji}{trend_str}")

        # Category table — get daily scores for this week
        week_entries = sorted(
            [e for e in entries if s["week_start"] <= e["date"] <= s["week_end"]],
            key=lambda e: e["date"]
        )
        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        lines.append(f"| Category | {' | '.join(day_labels)} | Avg |")
        lines.append(f"|----------|{'|'.join(['-----|'] * 7)}-----|")

        for cat in CATEGORIES:
            row = [CAT_LABELS[cat]]
            for i in range(7):
                day_date = (ws + timedelta(days=i)).strftime("%Y-%m-%d")
                entry = next((e for e in week_entries if e["date"] == day_date), None)
                row.append(str(entry[cat]) if entry and entry.get(cat) is not None else "—")
            avg = s.get(cat)
            row.append(str(avg) if avg is not None else "—")
            lines.append("| " + " | ".join(row) + " |")

        # Overall row
        row = ["**Overall**"]
        for i in range(7):
            day_date = (ws + timedelta(days=i)).strftime("%Y-%m-%d")
            entry = next((e for e in week_entries if e["date"] == day_date), None)
            row.append(f"**{entry['overall']}**" if entry else "—")
        row.append(f"**{s['overall']}**")
        lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        if s.get("narrative"):
            lines.append(s["narrative"])
            lines.append("")

        if s.get("trend") is not None:
            trend_label = {"up": "Improving ↑", "down": "Declining ↓", "flat": "Steady →", None: "No prior data"}
            lines.append(f"**Trend vs. prior week:** {trend_label.get(s['trend'], 'No data yet (first week tracked)')}")
        else:
            lines.append("**Trend vs. prior week:** No data yet (first week tracked)")
        lines.append("")
        lines.append("---")
        lines.append("")

    # ─── Daily Log ───
    lines.append("## Daily Log")

    daily_sorted = sorted(entries, key=lambda e: e["date"], reverse=True)
    for e in daily_sorted:
        dt = datetime.strptime(e["date"], "%Y-%m-%d")
        day_name = dt.strftime("%A, %B ")
        day_num = dt.day
        suffix = "th" if 11 <= day_num <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day_num % 10, "th")
        day_link = f"{dt.strftime('%A, %B ')}{ day_num}{suffix}, {dt.year}"
        emoji = get_emoji(e["overall"])

        lines.append(f"### [[{day_link}]]")
        lines.append(f"**Overall: {e['overall']}/5** {emoji}")
        lines.append("")
        lines.append("| Category  | Score | Notes |")
        lines.append("| --------- | ----- | ----- |")

        for cat in CATEGORIES:
            score = e.get(cat, "—")
            lines.append(f"| {CAT_LABELS[cat]} | {score} | |")

        lines.append("")
        if e.get("primary_driver"):
            lines.append(f"**Primary driver:** {e['primary_driver']}")
        if e.get("notes"):
            lines.append(f"**Notes:** {e['notes']}")
        if e.get("flags"):
            lines.append(f"**Flags:** {', '.join(e['flags'])}")
        lines.append("")
        lines.append("---")

    content = "\n".join(lines)

    with open(MOOD_JOURNAL, "w") as f:
        f.write(content)


# ─── HTTP Server ──────────────────────────────────────────────────────────────

class MoodTrackerHandler(BaseHTTPRequestHandler):
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
        elif path == "/api/trends":
            params = parse_qs(urlparse(self.path).query)
            days = int(params.get("days", [14])[0])
            data = load_data()
            self._send_json(get_trends(data, days))
        elif path == "/api/streak":
            self._send_json(get_streak_info(load_data()))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/api/entries":
            data = load_data()
            entry = {
                "date": body["date"],
                "overall": body.get("overall"),
                "emotional": body.get("emotional"),
                "energy": body.get("energy"),
                "self_care": body.get("self_care"),
                "social": body.get("social"),
                "purpose": body.get("purpose"),
                "primary_driver": body.get("primary_driver", ""),
                "notes": body.get("notes", ""),
                "flags": body.get("flags", [])
            }
            # Update existing or add new
            found = False
            for i, e in enumerate(data["entries"]):
                if e["date"] == body["date"]:
                    data["entries"][i] = entry
                    found = True
                    break
            if not found:
                data["entries"].append(entry)

            # Auto-update weekly summary
            ws, we = get_week_bounds(body["date"])
            summary = compute_weekly_summary(data, ws)
            if summary:
                # Preserve narrative if one exists
                existing = next((s for s in data.get("weekly_summaries", [])
                                 if s["week_start"] == ws), None)
                if existing and existing.get("narrative"):
                    summary["narrative"] = existing["narrative"]
                else:
                    summary["narrative"] = ""

                data.setdefault("weekly_summaries", [])
                replaced = False
                for i, s in enumerate(data["weekly_summaries"]):
                    if s["week_start"] == ws:
                        data["weekly_summaries"][i] = summary
                        replaced = True
                        break
                if not replaced:
                    data["weekly_summaries"].append(summary)

            save_data(data)
            sync_obsidian(data)
            self._send_json(entry, 201)

        elif path == "/api/weekly-narrative":
            data = load_data()
            ws = body["week_start"]
            narrative = body.get("narrative", "")
            for s in data.get("weekly_summaries", []):
                if s["week_start"] == ws:
                    s["narrative"] = narrative
                    break
            save_data(data)
            sync_obsidian(data)
            self._send_json({"ok": True})

        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        path = urlparse(self.path).path
        params = parse_qs(urlparse(self.path).query)

        if path == "/api/entries":
            date = params.get("date", [None])[0]
            if date:
                data = load_data()
                data["entries"] = [e for e in data["entries"] if e["date"] != date]
                # Recompute weekly summary
                ws, we = get_week_bounds(date)
                summary = compute_weekly_summary(data, ws)
                if summary:
                    for i, s in enumerate(data["weekly_summaries"]):
                        if s["week_start"] == ws:
                            summary["narrative"] = s.get("narrative", "")
                            data["weekly_summaries"][i] = summary
                            break
                else:
                    data["weekly_summaries"] = [s for s in data["weekly_summaries"]
                                                 if s["week_start"] != ws]
                save_data(data)
                sync_obsidian(data)
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "date required"}, 400)
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        self.do_POST()


# ─── HTML App ─────────────────────────────────────────────────────────────────

HTML_APP = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mood Tracker — Exobrain</title>
<style>
  :root {
    --bg: #1a1a2e;
    --surface: #16213e;
    --surface2: #0f3460;
    --text: #eee;
    --text-muted: #8899aa;
    --struggling: #e74c3c;
    --low: #e67e22;
    --neutral: #f1c40f;
    --good: #2ecc71;
    --thriving: #3498db;
    --radius: 12px;
    --shadow: 0 4px 24px rgba(0,0,0,0.3);
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
  }
  .app { max-width: 1200px; margin: 0 auto; padding: 24px; }
  header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 32px;
  }
  header h1 {
    font-size: 28px; font-weight: 700;
    background: linear-gradient(135deg, var(--good), var(--thriving));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }
  header .subtitle { color: var(--text-muted); font-size: 14px; margin-top: 4px; }

  .stats-bar { display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap; }
  .stat-card {
    background: var(--surface); border-radius: var(--radius);
    padding: 16px 24px; flex: 1; min-width: 140px; box-shadow: var(--shadow);
  }
  .stat-card .label { font-size: 12px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  .stat-card .value { font-size: 28px; font-weight: 700; }
  .stat-card .detail { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

  .main-grid { display: grid; grid-template-columns: 1fr 400px; gap: 24px; }
  @media (max-width: 960px) { .main-grid { grid-template-columns: 1fr; } }

  .card { background: var(--surface); border-radius: var(--radius); padding: 24px; box-shadow: var(--shadow); margin-bottom: 24px; }
  .card h2 { font-size: 18px; font-weight: 600; margin-bottom: 16px; }

  /* Calendar heatmap */
  .cal-nav { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .cal-nav button { background: var(--surface2); border: none; color: var(--text); padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 16px; }
  .cal-nav button:hover { background: var(--good); }
  .cal-nav .month-label { font-size: 18px; font-weight: 600; }

  .cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
  .cal-header { text-align: center; font-size: 11px; color: var(--text-muted); padding: 4px; text-transform: uppercase; letter-spacing: 1px; }
  .cal-day {
    aspect-ratio: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
    border-radius: 10px; font-size: 14px; cursor: pointer; transition: all 0.15s; position: relative;
  }
  .cal-day:hover { transform: scale(1.1); }
  .cal-day.empty { cursor: default; }
  .cal-day.empty:hover { transform: none; }
  .cal-day.today { outline: 2px solid var(--text); outline-offset: -2px; }
  .cal-day.scored { color: white; }
  .cal-day.unscored { background: #2c2c2c; color: #555; }
  .cal-day .score-label { font-size: 9px; position: absolute; bottom: 3px; opacity: 0.8; }

  .legend { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; font-size: 12px; }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .legend-dot { width: 12px; height: 12px; border-radius: 4px; }

  /* Trend chart */
  .trend-chart { width: 100%; height: 200px; position: relative; margin-top: 8px; }
  .trend-svg { width: 100%; height: 100%; }

  /* Form */
  .form-group { margin-bottom: 16px; }
  .form-group label { display: block; font-size: 13px; color: var(--text-muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
  input[type="date"], select, textarea {
    width: 100%; padding: 10px 14px; background: var(--bg);
    border: 1px solid var(--surface2); border-radius: 8px; color: var(--text); font-size: 14px;
  }
  input[type="date"]:focus, select:focus, textarea:focus { outline: none; border-color: var(--good); }
  textarea { resize: vertical; min-height: 60px; font-family: inherit; }

  .btn { padding: 10px 20px; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.15s; width: 100%; }
  .btn-primary { background: linear-gradient(135deg, var(--good), var(--thriving)); color: white; }
  .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(46,204,113,0.4); }
  .btn-secondary { background: var(--surface2); color: var(--text); margin-top: 8px; }
  .btn-secondary:hover { background: #1a4a8a; }

  /* Score slider */
  .score-slider { margin-bottom: 12px; }
  .score-slider .slider-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  .score-slider .slider-header .cat-name { font-size: 13px; font-weight: 600; }
  .score-slider .slider-header .score-display { font-size: 16px; font-weight: 700; min-width: 40px; text-align: right; }
  .score-slider input[type="range"] { width: 100%; accent-color: var(--good); height: 6px; }
  .score-ticks { display: flex; justify-content: space-between; font-size: 10px; color: var(--text-muted); margin-top: 2px; }

  /* Chip/flag grid */
  .chip-grid { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip {
    padding: 6px 14px; border-radius: 20px; font-size: 12px; cursor: pointer;
    border: 1px solid var(--surface2); background: var(--bg); color: var(--text-muted); transition: all 0.15s; user-select: none;
  }
  .chip.selected { background: var(--thriving); color: white; border-color: var(--thriving); }
  .chip:hover { border-color: var(--thriving); }

  /* History items */
  .history-item {
    padding: 12px; border-radius: 8px; background: var(--bg); margin-bottom: 8px;
    font-size: 13px; border-left: 4px solid #2c2c2c; position: relative;
  }
  .history-item .date { font-weight: 600; }
  .history-item .meta { color: var(--text-muted); margin-top: 4px; }
  .history-item .sub-scores { display: flex; gap: 8px; margin-top: 6px; flex-wrap: wrap; }
  .history-item .sub-score { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: var(--surface2); }
  .history-item .actions { display: flex; gap: 6px; margin-top: 8px; }
  .history-item .actions button {
    padding: 4px 12px; border-radius: 6px; border: 1px solid var(--surface2);
    background: var(--surface); color: var(--text-muted); font-size: 11px; cursor: pointer; transition: all 0.15s;
  }
  .history-item .actions button:hover { border-color: var(--good); color: var(--text); }
  .history-item .actions button.delete-btn:hover { border-color: var(--struggling); background: var(--struggling); color: white; }

  /* Weekly summary card */
  .weekly-card { padding: 16px; border-radius: 8px; background: var(--bg); margin-bottom: 12px; }
  .weekly-card .week-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
  .weekly-card .week-header .week-range { font-weight: 600; font-size: 14px; }
  .weekly-card .week-header .week-score { font-size: 20px; font-weight: 700; }
  .weekly-card .cat-bars { display: flex; flex-direction: column; gap: 4px; }
  .cat-bar { display: flex; align-items: center; gap: 8px; }
  .cat-bar .cat-label { font-size: 11px; width: 70px; color: var(--text-muted); }
  .cat-bar .bar-track { flex: 1; height: 8px; background: var(--surface2); border-radius: 4px; overflow: hidden; }
  .cat-bar .bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
  .cat-bar .bar-val { font-size: 11px; width: 24px; text-align: right; }
  .weekly-card .narrative { font-size: 12px; color: var(--text-muted); margin-top: 8px; line-height: 1.5; }
  .weekly-card .narrative-edit { margin-top: 8px; }
  .weekly-card .narrative-edit textarea { font-size: 12px; min-height: 80px; }

  /* Day detail */
  .day-detail { display: none; margin-top: 16px; padding: 16px; background: var(--bg); border-radius: 8px; border-left: 3px solid var(--good); }
  .day-detail.visible { display: block; }
  .day-detail h3 { font-size: 14px; margin-bottom: 8px; }

  /* Modal */
  .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 100; align-items: center; justify-content: center; }
  .modal-overlay.visible { display: flex; }
  .modal { background: var(--surface); border-radius: var(--radius); padding: 28px; width: 480px; max-width: 90vw; max-height: 85vh; overflow-y: auto; box-shadow: 0 8px 40px rgba(0,0,0,0.5); }
  .modal h2 { font-size: 18px; margin-bottom: 20px; }
  .modal .btn-row { display: flex; gap: 8px; margin-top: 16px; }
  .modal .btn-row .btn { flex: 1; }

  /* Tabs */
  .tabs { display: flex; gap: 4px; margin-bottom: 16px; }
  .tab { padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 13px; background: var(--bg); color: var(--text-muted); border: none; transition: all 0.15s; }
  .tab.active { background: var(--good); color: white; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }
</style>
</head>
<body>
<div class="app">
  <header>
    <div>
      <h1>Mood Tracker</h1>
      <div class="subtitle">Alex's mental health & wellbeing — Exobrain</div>
    </div>
    <div id="current-mood-badge" style="font-size:32px"></div>
  </header>

  <div class="stats-bar">
    <div class="stat-card">
      <div class="label">Today</div>
      <div class="value" id="stat-today">—</div>
      <div class="detail" id="stat-today-label"></div>
    </div>
    <div class="stat-card">
      <div class="label">7-Day Avg</div>
      <div class="value" id="stat-week-avg">—</div>
      <div class="detail" id="stat-week-trend"></div>
    </div>
    <div class="stat-card">
      <div class="label">Streak</div>
      <div class="value" id="stat-streak">0</div>
      <div class="detail">days scored</div>
    </div>
    <div class="stat-card">
      <div class="label">Weakest</div>
      <div class="value" id="stat-weakest">—</div>
      <div class="detail" id="stat-weakest-label"></div>
    </div>
    <div class="stat-card">
      <div class="label">Strongest</div>
      <div class="value" id="stat-strongest">—</div>
      <div class="detail" id="stat-strongest-label"></div>
    </div>
  </div>

  <div class="main-grid">
    <div>
      <!-- Calendar -->
      <div class="card">
        <div class="cal-nav">
          <button onclick="changeMonth(-1)">&larr;</button>
          <span class="month-label" id="month-label"></span>
          <button onclick="changeMonth(1)">&rarr;</button>
        </div>
        <div class="cal-grid" id="cal-grid"></div>
        <div class="legend">
          <div class="legend-item"><div class="legend-dot" style="background:var(--struggling)"></div>1 Struggling</div>
          <div class="legend-item"><div class="legend-dot" style="background:var(--low)"></div>2 Low</div>
          <div class="legend-item"><div class="legend-dot" style="background:var(--neutral)"></div>3 Neutral</div>
          <div class="legend-item"><div class="legend-dot" style="background:var(--good)"></div>4 Good</div>
          <div class="legend-item"><div class="legend-dot" style="background:var(--thriving)"></div>5 Thriving</div>
        </div>
        <div class="day-detail" id="day-detail">
          <h3 id="day-detail-title"></h3>
          <div id="day-detail-content"></div>
        </div>
      </div>

      <!-- Trend Chart -->
      <div class="card">
        <h2>14-Day Trend</h2>
        <div class="trend-chart">
          <svg class="trend-svg" id="trend-svg" viewBox="0 0 600 200"></svg>
        </div>
      </div>

      <!-- Weekly Summaries -->
      <div class="card">
        <h2>Weekly Summaries</h2>
        <div id="weekly-list"></div>
      </div>
    </div>

    <div>
      <!-- Log Entry -->
      <div class="card">
        <h2>Log Mood</h2>
        <div class="tabs">
          <button class="tab active" onclick="switchTab('scores', this)">Scores</button>
          <button class="tab" onclick="switchTab('context', this)">Context</button>
        </div>

        <div id="tab-scores" class="tab-content active">
          <div class="form-group">
            <label>Date</label>
            <input type="date" id="entry-date">
          </div>

          <div class="score-slider" id="slider-overall">
            <div class="slider-header">
              <span class="cat-name">Overall</span>
              <span class="score-display" id="val-overall">3</span>
            </div>
            <input type="range" min="1" max="5" step="0.5" value="3" id="range-overall"
                   oninput="updateSlider('overall', this.value)">
            <div class="score-ticks"><span>1</span><span>2</span><span>3</span><span>4</span><span>5</span></div>
          </div>

          <div class="score-slider">
            <div class="slider-header">
              <span class="cat-name">Emotional</span>
              <span class="score-display" id="val-emotional">3</span>
            </div>
            <input type="range" min="1" max="5" step="0.5" value="3" id="range-emotional"
                   oninput="updateSlider('emotional', this.value)">
          </div>

          <div class="score-slider">
            <div class="slider-header">
              <span class="cat-name">Energy</span>
              <span class="score-display" id="val-energy">3</span>
            </div>
            <input type="range" min="1" max="5" step="0.5" value="3" id="range-energy"
                   oninput="updateSlider('energy', this.value)">
          </div>

          <div class="score-slider">
            <div class="slider-header">
              <span class="cat-name">Self-Care</span>
              <span class="score-display" id="val-self_care">3</span>
            </div>
            <input type="range" min="1" max="5" step="0.5" value="3" id="range-self_care"
                   oninput="updateSlider('self_care', this.value)">
          </div>

          <div class="score-slider">
            <div class="slider-header">
              <span class="cat-name">Social</span>
              <span class="score-display" id="val-social">3</span>
            </div>
            <input type="range" min="1" max="5" step="0.5" value="3" id="range-social"
                   oninput="updateSlider('social', this.value)">
          </div>

          <div class="score-slider">
            <div class="slider-header">
              <span class="cat-name">Purpose</span>
              <span class="score-display" id="val-purpose">3</span>
            </div>
            <input type="range" min="1" max="5" step="0.5" value="3" id="range-purpose"
                   oninput="updateSlider('purpose', this.value)">
          </div>
        </div>

        <div id="tab-context" class="tab-content">
          <div class="form-group">
            <label>Primary Driver</label>
            <textarea id="entry-driver" placeholder="What most influenced today's score?"></textarea>
          </div>
          <div class="form-group">
            <label>Notes</label>
            <textarea id="entry-notes" placeholder="Observations, quotes, signals..."></textarea>
          </div>
          <div class="form-group">
            <label>Flags</label>
            <div class="chip-grid" id="flag-chips"></div>
          </div>
        </div>

        <button class="btn btn-primary" onclick="saveEntry()" style="margin-top:12px">Save Entry</button>
      </div>

      <!-- Recent Entries -->
      <div class="card">
        <h2>Recent Entries</h2>
        <div id="history-list"></div>
      </div>
    </div>
  </div>
</div>

<!-- Edit Modal -->
<div class="modal-overlay" id="edit-modal">
  <div class="modal">
    <h2>Edit Entry</h2>
    <input type="hidden" id="edit-orig-date">
    <div class="form-group">
      <label>Date</label>
      <input type="date" id="edit-date">
    </div>
    <div id="edit-sliders"></div>
    <div class="form-group">
      <label>Primary Driver</label>
      <textarea id="edit-driver"></textarea>
    </div>
    <div class="form-group">
      <label>Notes</label>
      <textarea id="edit-notes"></textarea>
    </div>
    <div class="form-group">
      <label>Flags</label>
      <div class="chip-grid" id="edit-flag-chips"></div>
    </div>
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveEdit()">Save Changes</button>
    </div>
  </div>
</div>

<script>
const API = '';
const CATEGORIES = ['emotional','energy','self_care','social','purpose'];
const CAT_LABELS = {emotional:'Emotional',energy:'Energy',self_care:'Self-Care',social:'Social',purpose:'Purpose'};
const SCORE_COLORS = {1:'#e74c3c',1.5:'#e25b2c',2:'#e67e22',2.5:'#ea9a1e',3:'#f1c40f',3.5:'#9bce3f',4:'#2ecc71',4.5:'#2db4c7',5:'#3498db'};
const SCORE_LABELS = {1:'Struggling',2:'Low',3:'Neutral',4:'Good',5:'Thriving'};
const SCORE_EMOJI = {1:'\u{1F534}',2:'\u{1F7E0}',3:'\u{1F7E1}',4:'\u{1F7E2}',5:'\u{1F535}'};
const FLAGS = ['bedtime_drift','sleep_deficit','self_care_slip','social_marathon_start','post_social_crash','declining_trend','recovery_needed','procrastination','alcohol','high_stress','breakthrough','good_sleep','exercise_win'];

let appData = null;
let currentMonth = new Date().getMonth();
let currentYear = new Date().getFullYear();
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const DAYS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

function getColor(score) {
  if (!score) return '#2c2c2c';
  const r = Math.round(score * 2) / 2;
  return SCORE_COLORS[r] || '#2c2c2c';
}
function getLabel(score) { return SCORE_LABELS[Math.round(score)] || '—'; }
function getEmoji(score) { return SCORE_EMOJI[Math.round(score)] || ''; }

async function fetchData() {
  const res = await fetch(API + '/api/data');
  appData = await res.json();
  render();
}

function render() {
  renderStats();
  renderCalendar();
  renderTrend();
  renderHistory();
  renderWeeklies();
  renderFlagChips();
}

function renderStats() {
  const today = new Date().toISOString().split('T')[0];
  const todayEntry = appData.entries.find(e => e.date === today);
  const el = document.getElementById('stat-today');
  const lbl = document.getElementById('stat-today-label');
  const badge = document.getElementById('current-mood-badge');

  if (todayEntry) {
    el.textContent = todayEntry.overall;
    el.style.color = getColor(todayEntry.overall);
    lbl.textContent = getLabel(todayEntry.overall);
    badge.textContent = getEmoji(todayEntry.overall);
  } else {
    el.textContent = '—';
    el.style.color = '';
    lbl.textContent = 'not scored yet';
    badge.textContent = '';
  }

  // 7-day avg
  const cutoff = new Date(); cutoff.setDate(cutoff.getDate() - 7);
  const cutStr = cutoff.toISOString().split('T')[0];
  const recent = appData.entries.filter(e => e.date >= cutStr);
  if (recent.length) {
    const avg = (recent.reduce((s,e) => s + e.overall, 0) / recent.length).toFixed(1);
    document.getElementById('stat-week-avg').textContent = avg;
    document.getElementById('stat-week-avg').style.color = getColor(parseFloat(avg));
  }

  // Prior 7-day for trend
  const priorCutoff = new Date(); priorCutoff.setDate(priorCutoff.getDate() - 14);
  const priorStr = priorCutoff.toISOString().split('T')[0];
  const prior = appData.entries.filter(e => e.date >= priorStr && e.date < cutStr);
  if (prior.length && recent.length) {
    const priorAvg = prior.reduce((s,e) => s + e.overall, 0) / prior.length;
    const recentAvg = recent.reduce((s,e) => s + e.overall, 0) / recent.length;
    const diff = recentAvg - priorAvg;
    document.getElementById('stat-week-trend').textContent =
      diff > 0.3 ? 'Improving \u2191' : diff < -0.3 ? 'Declining \u2193' : 'Steady \u2192';
  }

  // Streak
  const sorted = [...appData.entries].sort((a,b) => b.date.localeCompare(a.date));
  let streak = 0;
  if (sorted.length) {
    streak = 1;
    for (let i = 1; i < sorted.length; i++) {
      const prev = new Date(sorted[i-1].date + 'T00:00:00');
      const curr = new Date(sorted[i].date + 'T00:00:00');
      if ((prev - curr) / 86400000 === 1) streak++; else break;
    }
  }
  document.getElementById('stat-streak').textContent = streak;

  // Weakest/strongest category (7-day)
  if (recent.length) {
    const catAvgs = {};
    CATEGORIES.forEach(cat => {
      const vals = recent.filter(e => e[cat] != null).map(e => e[cat]);
      catAvgs[cat] = vals.length ? vals.reduce((s,v) => s+v, 0) / vals.length : null;
    });
    const valid = Object.entries(catAvgs).filter(([,v]) => v != null);
    if (valid.length) {
      valid.sort((a,b) => a[1] - b[1]);
      const [weakCat, weakVal] = valid[0];
      const [strongCat, strongVal] = valid[valid.length - 1];
      document.getElementById('stat-weakest').textContent = weakVal.toFixed(1);
      document.getElementById('stat-weakest').style.color = getColor(weakVal);
      document.getElementById('stat-weakest-label').textContent = CAT_LABELS[weakCat];
      document.getElementById('stat-strongest').textContent = strongVal.toFixed(1);
      document.getElementById('stat-strongest').style.color = getColor(strongVal);
      document.getElementById('stat-strongest-label').textContent = CAT_LABELS[strongCat];
    }
  }
}

function renderCalendar() {
  const grid = document.getElementById('cal-grid');
  document.getElementById('month-label').textContent = `${MONTHS[currentMonth]} ${currentYear}`;

  let html = DAYS.map(d => `<div class="cal-header">${d}</div>`).join('');

  // JS getDay: 0=Sun, we want Mon=0
  const firstDay = (new Date(currentYear, currentMonth, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
  const today = new Date(); today.setHours(0,0,0,0);

  for (let i = 0; i < firstDay; i++) html += '<div class="cal-day empty"></div>';

  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${currentYear}-${String(currentMonth+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
    const isToday = new Date(dateStr + 'T00:00:00').getTime() === today.getTime();
    const entry = appData.entries.find(e => e.date === dateStr);
    const score = entry ? entry.overall : null;
    const bg = getColor(score);
    const scored = score != null;

    html += `<div class="cal-day ${isToday ? 'today' : ''} ${scored ? 'scored' : 'unscored'}"
      style="background:${bg}" onclick="showDayDetail('${dateStr}')" title="${dateStr}${scored ? ' — '+score+'/5' : ''}">
      ${d}
      ${scored ? `<span class="score-label">${score}</span>` : ''}
    </div>`;
  }
  grid.innerHTML = html;
}

function showDayDetail(dateStr) {
  const detail = document.getElementById('day-detail');
  const title = document.getElementById('day-detail-title');
  const content = document.getElementById('day-detail-content');
  const date = new Date(dateStr + 'T00:00:00');
  title.textContent = date.toLocaleDateString('en-US', {weekday:'long', month:'long', day:'numeric', year:'numeric'});

  const entry = appData.entries.find(e => e.date === dateStr);
  if (!entry) {
    content.innerHTML = `<span style="color:var(--text-muted)">No entry. <a href="#" onclick="prefillDate('${dateStr}');return false" style="color:var(--thriving)">Log this day</a></span>`;
    detail.classList.add('visible');
    return;
  }

  let html = `<div style="font-size:20px;font-weight:700;color:${getColor(entry.overall)};margin-bottom:8px">${entry.overall}/5 ${getEmoji(entry.overall)} ${getLabel(entry.overall)}</div>`;
  html += '<div style="display:flex;flex-direction:column;gap:4px;margin-bottom:8px">';
  CATEGORIES.forEach(cat => {
    const v = entry[cat];
    if (v != null) {
      const pct = (v / 5) * 100;
      html += `<div class="cat-bar"><span class="cat-label">${CAT_LABELS[cat]}</span><div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${getColor(v)}"></div></div><span class="bar-val">${v}</span></div>`;
    }
  });
  html += '</div>';
  if (entry.primary_driver) html += `<div style="margin-bottom:4px"><strong>Driver:</strong> ${entry.primary_driver}</div>`;
  if (entry.notes) html += `<div style="margin-bottom:4px"><strong>Notes:</strong> ${entry.notes}</div>`;
  if (entry.flags && entry.flags.length) html += `<div><strong>Flags:</strong> ${entry.flags.join(', ')}</div>`;

  content.innerHTML = html;
  detail.classList.add('visible');

  // Pre-fill log date
  document.getElementById('entry-date').value = dateStr;
}

function prefillDate(dateStr) {
  document.getElementById('entry-date').value = dateStr;
  // Reset sliders
  ['overall',...CATEGORIES].forEach(k => {
    document.getElementById('range-'+k).value = 3;
    document.getElementById('val-'+k).textContent = '3';
  });
  window.scrollTo({top: document.querySelector('.main-grid').offsetTop, behavior: 'smooth'});
}

function renderTrend() {
  const svg = document.getElementById('trend-svg');
  const entries = [...appData.entries].sort((a,b) => a.date.localeCompare(b.date)).slice(-14);
  if (entries.length < 2) { svg.innerHTML = '<text x="300" y="100" fill="#8899aa" text-anchor="middle" font-size="14">Need 2+ entries for trend</text>'; return; }

  const W = 600, H = 200, PAD = 40;
  const xStep = (W - PAD * 2) / (entries.length - 1);
  let html = '';

  // Grid lines
  for (let s = 1; s <= 5; s++) {
    const y = PAD + (5 - s) * ((H - PAD * 2) / 4);
    html += `<line x1="${PAD}" y1="${y}" x2="${W-PAD}" y2="${y}" stroke="#1e3050" stroke-width="1"/>`;
    html += `<text x="${PAD-8}" y="${y+4}" fill="#8899aa" font-size="11" text-anchor="end">${s}</text>`;
  }

  // Category lines
  const catColors = {overall:'#fff',emotional:'#e74c3c',energy:'#f1c40f',self_care:'#2ecc71',social:'#3498db',purpose:'#a78bfa'};
  ['overall',...CATEGORIES].forEach(cat => {
    const points = entries.map((e, i) => {
      const x = PAD + i * xStep;
      const y = PAD + (5 - (e[cat] || 3)) * ((H - PAD * 2) / 4);
      return `${x},${y}`;
    });
    const opacity = cat === 'overall' ? 1 : 0.5;
    const width = cat === 'overall' ? 3 : 1.5;
    html += `<polyline points="${points.join(' ')}" fill="none" stroke="${catColors[cat]}" stroke-width="${width}" opacity="${opacity}"/>`;
  });

  // Dots for overall
  entries.forEach((e, i) => {
    const x = PAD + i * xStep;
    const y = PAD + (5 - e.overall) * ((H - PAD * 2) / 4);
    html += `<circle cx="${x}" cy="${y}" r="4" fill="${getColor(e.overall)}" stroke="#1a1a2e" stroke-width="2"/>`;
    // Date labels (every other)
    if (i % 2 === 0 || i === entries.length - 1) {
      const d = new Date(e.date + 'T00:00:00');
      html += `<text x="${x}" y="${H-8}" fill="#8899aa" font-size="10" text-anchor="middle">${d.getDate()}/${d.getMonth()+1}</text>`;
    }
  });

  // Legend
  const legendItems = [{k:'overall',l:'Overall'},{k:'emotional',l:'Emo'},{k:'energy',l:'Enrgy'},{k:'self_care',l:'Care'},{k:'social',l:'Socl'},{k:'purpose',l:'Purp'}];
  legendItems.forEach((item, i) => {
    const x = PAD + i * 90;
    html += `<rect x="${x}" y="2" width="10" height="10" rx="2" fill="${catColors[item.k]}" opacity="${item.k==='overall'?1:0.5}"/>`;
    html += `<text x="${x+14}" y="11" fill="#8899aa" font-size="10">${item.l}</text>`;
  });

  svg.innerHTML = html;
}

function renderHistory() {
  const list = document.getElementById('history-list');
  const sorted = [...appData.entries].sort((a,b) => b.date.localeCompare(a.date)).slice(0, 10);
  if (!sorted.length) { list.innerHTML = '<div style="color:var(--text-muted);font-size:13px">No entries yet.</div>'; return; }

  list.innerHTML = sorted.map(e => {
    const d = new Date(e.date + 'T00:00:00');
    const dateLabel = d.toLocaleDateString('en-US', {weekday:'short', month:'short', day:'numeric'});
    return `<div class="history-item" style="border-left-color:${getColor(e.overall)}">
      <span class="date" style="color:${getColor(e.overall)}">${dateLabel}</span>
      <span style="margin-left:8px;font-weight:700">${e.overall}/5</span> ${getEmoji(e.overall)}
      <div class="sub-scores">
        ${CATEGORIES.map(c => `<span class="sub-score">${CAT_LABELS[c]}: ${e[c] != null ? e[c] : '—'}</span>`).join('')}
      </div>
      ${e.primary_driver ? `<div class="meta">${e.primary_driver}</div>` : ''}
      <div class="actions">
        <button onclick="editEntry('${e.date}')">Edit</button>
        <button class="delete-btn" onclick="deleteEntry('${e.date}')">Delete</button>
      </div>
    </div>`;
  }).join('');
}

function renderWeeklies() {
  const list = document.getElementById('weekly-list');
  const summaries = [...(appData.weekly_summaries || [])].sort((a,b) => b.week_start.localeCompare(a.week_start));
  if (!summaries.length) { list.innerHTML = '<div style="color:var(--text-muted);font-size:13px">No weekly summaries yet.</div>'; return; }

  list.innerHTML = summaries.map(s => {
    const ws = new Date(s.week_start + 'T00:00:00');
    const we = new Date(s.week_end + 'T00:00:00');
    const range = `${ws.toLocaleDateString('en-US',{month:'short',day:'numeric'})} – ${we.toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'})}`;
    const trend = s.trend === 'up' ? ' \u2191' : s.trend === 'down' ? ' \u2193' : s.trend === 'flat' ? ' \u2192' : '';

    let barsHtml = '';
    CATEGORIES.forEach(cat => {
      const v = s[cat];
      if (v != null) {
        const pct = (v / 5) * 100;
        barsHtml += `<div class="cat-bar"><span class="cat-label">${CAT_LABELS[cat]}</span><div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:${getColor(v)}"></div></div><span class="bar-val">${v}</span></div>`;
      }
    });

    return `<div class="weekly-card">
      <div class="week-header">
        <span class="week-range">${range}</span>
        <span class="week-score" style="color:${getColor(s.overall)}">${s.overall}/5${trend}</span>
      </div>
      <div class="cat-bars">${barsHtml}</div>
      ${s.narrative ? `<div class="narrative">${s.narrative}</div>` : ''}
      <div class="narrative-edit">
        <textarea id="narrative-${s.week_start}" placeholder="Add weekly narrative...">${s.narrative || ''}</textarea>
        <button class="btn btn-secondary" style="margin-top:4px;width:auto;padding:6px 16px;font-size:12px" onclick="saveNarrative('${s.week_start}')">Save Narrative</button>
      </div>
    </div>`;
  }).join('');
}

function renderFlagChips() {
  const container = document.getElementById('flag-chips');
  container.innerHTML = FLAGS.map(f =>
    `<div class="chip" data-flag="${f}" onclick="toggleChip(this)">${f.replace(/_/g,' ')}</div>`
  ).join('');
}

// ─── Actions ──────────────────────────────────────────────────────────────
function updateSlider(cat, val) {
  document.getElementById('val-' + cat).textContent = val;
  document.getElementById('val-' + cat).style.color = getColor(parseFloat(val));
}

async function saveEntry() {
  const date = document.getElementById('entry-date').value;
  if (!date) return alert('Please select a date');

  const body = { date };
  ['overall',...CATEGORIES].forEach(k => {
    body[k] = parseFloat(document.getElementById('range-' + k).value);
  });
  body.primary_driver = document.getElementById('entry-driver').value;
  body.notes = document.getElementById('entry-notes').value;
  body.flags = Array.from(document.querySelectorAll('#flag-chips .chip.selected')).map(c => c.dataset.flag);

  await fetch(API + '/api/entries', {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
  });

  // Reset form
  document.getElementById('entry-driver').value = '';
  document.getElementById('entry-notes').value = '';
  document.querySelectorAll('#flag-chips .chip.selected').forEach(c => c.classList.remove('selected'));
  await fetchData();
}

async function deleteEntry(date) {
  const d = new Date(date + 'T00:00:00');
  if (!confirm(`Delete entry for ${d.toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'})}?`)) return;
  await fetch(API + `/api/entries?date=${date}`, {method: 'DELETE'});
  await fetchData();
}

function editEntry(date) {
  const entry = appData.entries.find(e => e.date === date);
  if (!entry) return;

  document.getElementById('edit-orig-date').value = date;
  document.getElementById('edit-date').value = date;
  document.getElementById('edit-driver').value = entry.primary_driver || '';
  document.getElementById('edit-notes').value = entry.notes || '';

  // Build sliders
  const container = document.getElementById('edit-sliders');
  container.innerHTML = ['overall',...CATEGORIES].map(k => {
    const label = k === 'overall' ? 'Overall' : CAT_LABELS[k];
    const val = entry[k] != null ? entry[k] : 3;
    return `<div class="score-slider">
      <div class="slider-header">
        <span class="cat-name">${label}</span>
        <span class="score-display" id="edit-val-${k}" style="color:${getColor(val)}">${val}</span>
      </div>
      <input type="range" min="1" max="5" step="0.5" value="${val}" id="edit-range-${k}"
             oninput="document.getElementById('edit-val-${k}').textContent=this.value;document.getElementById('edit-val-${k}').style.color=getColor(parseFloat(this.value))">
    </div>`;
  }).join('');

  // Flags
  const flagContainer = document.getElementById('edit-flag-chips');
  flagContainer.innerHTML = FLAGS.map(f =>
    `<div class="chip ${(entry.flags||[]).includes(f)?'selected':''}" data-flag="${f}" onclick="toggleChip(this)">${f.replace(/_/g,' ')}</div>`
  ).join('');

  document.getElementById('edit-modal').classList.add('visible');
}

async function saveEdit() {
  const origDate = document.getElementById('edit-orig-date').value;
  const newDate = document.getElementById('edit-date').value;

  // Delete old if date changed
  if (origDate !== newDate) {
    await fetch(API + `/api/entries?date=${origDate}`, {method: 'DELETE'});
  }

  const body = { date: newDate };
  ['overall',...CATEGORIES].forEach(k => {
    body[k] = parseFloat(document.getElementById('edit-range-' + k).value);
  });
  body.primary_driver = document.getElementById('edit-driver').value;
  body.notes = document.getElementById('edit-notes').value;
  body.flags = Array.from(document.querySelectorAll('#edit-flag-chips .chip.selected')).map(c => c.dataset.flag);

  await fetch(API + '/api/entries', {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
  });

  closeModal();
  await fetchData();
}

async function saveNarrative(weekStart) {
  const narrative = document.getElementById('narrative-' + weekStart).value;
  await fetch(API + '/api/weekly-narrative', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({week_start: weekStart, narrative})
  });
  await fetchData();
}

function closeModal() { document.getElementById('edit-modal').classList.remove('visible'); }
document.getElementById('edit-modal').addEventListener('click', e => { if (e.target.id === 'edit-modal') closeModal(); });

// ─── UI Helpers ──────────────────────────────────────────────────────────
function changeMonth(delta) {
  currentMonth += delta;
  if (currentMonth > 11) { currentMonth = 0; currentYear++; }
  if (currentMonth < 0) { currentMonth = 11; currentYear--; }
  renderCalendar();
}

function toggleChip(el) { el.classList.toggle('selected'); }

function switchTab(name, btn) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
}

// Set default date
document.getElementById('entry-date').valueAsDate = new Date();

// Init
fetchData();
</script>
</body>
</html>"""


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sync":
        data = load_data()
        sync_obsidian(data)
        print("Synced to Obsidian.")
        sys.exit(0)

    print(f"\n  Mood Tracker running at http://localhost:{PORT}")
    print(f"  Data file: {DATA_FILE}")
    print(f"  Press Ctrl+C to stop\n")

    server = HTTPServer(("127.0.0.1", PORT), MoodTrackerHandler)
    webbrowser.open(f"http://localhost:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
        server.server_close()
