---
name: weekly-review
description: Comprehensive GTD-style weekly review. Scans email, calendar, notes, Things 3, and Supernote to synthesize the past week and plan the next. Use when the user says "weekly review", "week in review", "reflect on the week", or when triggered by the Sunday scheduled task.
---

# Weekly Review

Claude checks everything it can automatically, then generates a manual checklist for items only Alex can check.

## Automated Checks

### 1. Email scan
Use Gmail MCP (`gmail_search_messages`) to scan the past week's emails.
- Flag anything needing follow-up
- Create Things 3 tasks for actionable items
- Note important threads

### 2. Calendar review
Use `gcal_list_events` for:
- **Past 2 weeks**: What happened? Generate follow-up tasks from past meetings. This is a networking superpower — identify people Alex met and suggest follow-up actions (thank-you notes, shared resources, scheduling next meeting).
- **Next 4 weeks**: What's coming? Flag events needing preparation, deadlines approaching, and gaps that could be used for priority work.

### 3. Obsidian notes review
Read the past 7 daily notes from `/Users/alexhedtke/My Drive/Alex's Exobrain/Daily notes/`.
- Surface unresolved items, open questions, and incomplete threads
- Note patterns or recurring themes

### 4. Things 3 — Inbox
Use `get_inbox`. Every item should be associated with an area of responsibility or an active project if possible. Suggest assignments for each.

### 5. Things 3 — Anytime & Upcoming
Check for:
- Any deadlines this week?
- Anything that's been procrastinated on? (Flag constructively)

### 6. Things 3 — Someday
Review the someday list. Recommend at least 1 item to promote to "anytime" this week. Pick something aligned with current priorities.

### 7. Active Projects
Use `get_projects`. For each active project, suggest one concrete, achievable task to complete this week.

### 8. Supernote OCR
Run `/process-supernote` for any Supernote files modified in the past week. Include extracted text in the review.

### 9. Health trends
Pull 7-day Fitbit data (steps, sleep, zone minutes) and any Withings data (weight, BP). Summarize trends and flag concerns.

### 10. Processing log
Read `processing-log.json`. Summarize how many transcripts and Supernote pages were processed this week.

## Manual Checklist
Generate this for Alex to complete:
- [ ] Check Apple Notes for anything to capture
- [ ] Check physical inbox (mail, papers, etc.)
- [ ] Review computer files/downloads for anything to file or act on

*(BuJo and Supernote are auto-processed via OCR)*

## Output

Write `## Weekly Review` section in Sunday's daily note containing:

1. **Week summary**: What was accomplished, key meetings, completed tasks
2. **Email follow-ups**: Tasks created from email scan
3. **Calendar insights**: Follow-up tasks from past meetings, upcoming prep needed
4. **Inbox triage**: Suggested assignments for inbox items
5. **Procrastination flags**: Items that keep getting pushed back
6. **Someday promotion**: Item(s) suggested for this week
7. **Project next actions**: One task per active project
8. **Health snapshot**: 7-day trends with recommendations
9. **Priority alignment**: Are daily activities matching stated priorities? Flag misalignment.
10. **Manual checklist**: Items for Alex to check himself
11. **Proactive observations**: Patterns, efficiency suggestions, time-waste flags

### Notify
```bash
osascript -e 'display notification "Your weekly review is ready — check Sunday'\''s daily note" with title "Exobrain" sound name "Purr"'
```

Also send a Discord notification via `reply` to chat_id `1486464885784182834` with a summary:
> 📋 **Weekly Review ready** — [X] tasks created, [Y] overdue items flagged. Top flags: [1-2 sentence highlights]. Full review in Sunday's daily note.
