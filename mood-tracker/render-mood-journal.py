#!/usr/bin/env python3
"""Render Mood Journal.md from daily-note YAML frontmatter.

Frontmatter is the source of truth. This script walks Daily notes/*.md, reads
each note's mood_score + the 5 facets, and regenerates
~/Exobrain/Mood Journal.md from scratch.

Sections:
  1. Calendar heatmaps (one per month with data)
  2. Legend
  3. Weekly summaries (computed averages, table per week)
  4. Daily log (wikilinks + scores; narrative prose lives in each daily note)

Usage:
    python3 render-mood-journal.py

Stdlib only.
"""

import calendar
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

VAULT = Path.home() / "Exobrain"
DAILY_NOTES_DIR = VAULT / "Daily notes"
MOOD_JOURNAL = VAULT / "Mood Journal.md"

SCORE_COLORS = {
    1: "#e74c3c", 1.5: "#e25b2c",
    2: "#e67e22", 2.5: "#ea9a1e",
    3: "#f1c40f", 3.5: "#9bce3f",
    4: "#2ecc71", 4.5: "#2db4c7",
    5: "#3498db",
}
SCORE_EMOJI = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢", 5: "🔵"}

FACETS = [
    ("mood_emotional", "Emotional"),
    ("mood_energy", "Energy"),
    ("mood_self_care", "Self-Care"),
    ("mood_social", "Social"),
    ("mood_purpose", "Purpose"),
]


def parse_frontmatter(path: Path) -> dict | None:
    text = path.read_text()
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    out: dict = {}
    for line in text[4:end].split("\n"):
        if not line or line.startswith(" ") or line.startswith("-") or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if val == "":
            continue
        try:
            out[key] = float(val) if "." in val else int(val)
        except ValueError:
            out[key] = val
    return out


def get_color(score) -> str:
    if score is None:
        return "#2c2c2c"
    rounded = round(float(score) * 2) / 2
    return SCORE_COLORS.get(rounded, "#2c2c2c")


def get_emoji(score) -> str:
    if score is None:
        return ""
    return SCORE_EMOJI.get(int(round(float(score))), "")


def ordinal_suffix(day: int) -> str:
    if 10 <= day % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def daily_note_link(iso_date: str) -> str:
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    return f"{d.strftime('%A, %B')} {d.day}{ordinal_suffix(d.day)}, {d.year}"


def collect_entries() -> list[dict]:
    """Read every daily note's frontmatter; return entries that have a mood_score."""
    entries = []
    for note in sorted(DAILY_NOTES_DIR.glob("*.md")):
        fm = parse_frontmatter(note)
        if not fm:
            continue
        score = fm.get("mood_score")
        iso = fm.get("date")
        if not iso or score in (None, ""):
            continue
        entries.append({
            "date": iso,
            "overall": float(score),
            "emotional": fm.get("mood_emotional"),
            "energy": fm.get("mood_energy"),
            "self_care": fm.get("mood_self_care"),
            "social": fm.get("mood_social"),
            "purpose": fm.get("mood_purpose"),
        })
    return entries


def fmt_score(v) -> str:
    if v is None:
        return "—"
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def render_heatmap(entries: list[dict]) -> list[str]:
    scores_by_month: dict = {}
    for e in entries:
        dt = datetime.strptime(e["date"], "%Y-%m-%d")
        scores_by_month.setdefault((dt.year, dt.month), {})[dt.day] = e["overall"]

    now = datetime.now()
    scores_by_month.setdefault((now.year, now.month), {})

    lines: list[str] = []
    for (year, month) in sorted(scores_by_month.keys(), reverse=True):
        scores = scores_by_month[(year, month)]
        month_name = datetime(year, month, 1).strftime("%B %Y")
        lines.append('<div style="margin-bottom: 20px;">')
        lines.append('<table style="border-collapse: separate; border-spacing: 3px; font-family: monospace; font-size: 12px;">')
        lines.append(f'<caption style="font-weight: bold; margin-bottom: 4px; font-size: 14px;">{month_name}</caption>')
        lines.append("<tr>")
        for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
            lines.append(f'<th style="padding: 4px 8px;">{d}</th>')
        lines.append("</tr>")
        for week in calendar.monthcalendar(year, month):
            lines.append("<tr>")
            for day in week:
                if day == 0:
                    lines.append('<td style="padding: 6px 8px; background-color: transparent; text-align: center;"></td>')
                    continue
                score = scores.get(day)
                bg = get_color(score)
                if score is not None:
                    dt = datetime(year, month, day)
                    title = f' title="{dt.strftime("%b %d")} — {fmt_score(score)}/5"'
                    color = "white"
                else:
                    title = ""
                    color = "#555"
                lines.append(f'<td style="padding: 6px 8px; background-color: {bg}; color: {color}; text-align: center; border-radius: 4px;"{title}>{day}</td>')
            lines.append("</tr>")
        lines.append("</table>")
        lines.append("</div>")
        lines.append("")
    return lines


def week_bounds(d: date) -> tuple[date, date]:
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def render_weekly_summaries(entries: list[dict]) -> list[str]:
    by_week: dict[date, list[dict]] = {}
    for e in entries:
        d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        ws, _ = week_bounds(d)
        by_week.setdefault(ws, []).append(e)

    lines: list[str] = ["## Weekly Summaries", ""]
    for ws in sorted(by_week.keys(), reverse=True):
        week_entries = by_week[ws]
        we = ws + timedelta(days=6)
        label = f"{ws.strftime('%B %d')}–{we.strftime('%d, %Y')}"

        overall_avg = round(sum(e["overall"] for e in week_entries) / len(week_entries), 1)
        emoji = get_emoji(overall_avg)
        lines.append(f"### Week of {label}")
        lines.append(f"**Overall: {fmt_score(overall_avg)}/5** {emoji}")

        day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        lines.append(f"| Category | {' | '.join(day_labels)} | Avg |")
        lines.append("|" + "|".join(["----------"] + ["-----"] * 7 + ["-----"]) + "|")

        def cell(day_offset: int, key: str) -> str:
            target_iso = (ws + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            for e in week_entries:
                if e["date"] == target_iso:
                    return fmt_score(e.get(key))
            return "—"

        for fm_key, label_name in FACETS:
            json_key = fm_key.replace("mood_", "")
            row = [label_name] + [cell(i, json_key) for i in range(7)]
            vals = [e.get(json_key) for e in week_entries if e.get(json_key) is not None]
            row.append(fmt_score(round(sum(vals) / len(vals), 1)) if vals else "—")
            lines.append("| " + " | ".join(row) + " |")

        overall_row = ["**Overall**"] + [f"**{cell(i, 'overall')}**" for i in range(7)]
        overall_row.append(f"**{fmt_score(overall_avg)}**")
        lines.append("| " + " | ".join(overall_row) + " |")
        lines.append("")
        lines.append("---")
        lines.append("")
    return lines


def render_daily_log(entries: list[dict]) -> list[str]:
    lines = ["## Daily Log", ""]
    for e in sorted(entries, key=lambda x: x["date"], reverse=True):
        link = daily_note_link(e["date"])
        emoji = get_emoji(e["overall"])
        lines.append(f"### [[{link}]]")
        lines.append(f"**Overall: {fmt_score(e['overall'])}/5** {emoji}")
        parts = []
        for fm_key, label in FACETS:
            v = e.get(fm_key.replace("mood_", ""))
            if v is not None:
                parts.append(f"{label} {fmt_score(v)}")
        if parts:
            lines.append(" · ".join(parts))
        lines.append("")
        lines.append("---")
        lines.append("")
    return lines


def main() -> int:
    entries = collect_entries()
    if not entries:
        print("No daily notes with mood_score frontmatter found.")
        return 0

    lines: list[str] = ["<< [[Dashboard]] >>", ""]
    lines.extend(render_heatmap(entries))
    lines.append("**Legend:** 🔵 5 Thriving | 🟢 4 Good | 🟡 3 Neutral | 🟠 2 Low | 🔴 1 Struggling")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.extend(render_weekly_summaries(entries))
    lines.extend(render_daily_log(entries))

    MOOD_JOURNAL.write_text("\n".join(lines))
    print(f"Rendered Mood Journal from {len(entries)} daily notes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
