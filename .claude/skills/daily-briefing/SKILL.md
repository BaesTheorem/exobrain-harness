---
name: daily-briefing
description: Generate a morning briefing with weather, health data, calendar, tasks, and priorities. Writes to today's Obsidian daily note. Use when the user asks about their day, wants a summary, says good morning, asks what's going on today, wants to know their schedule, asks "what do I have today", "anything I should know", "catch me up", "how's my day look", "morning", "briefing", "today's plan", or when triggered by the morning scheduled task.
---

# Daily Briefing

Lightweight orchestrator that assembles a morning briefing by running domain-specific skills. Each skill owns its own logic — the briefing just sequences them and assembles the output.

Run steps in parallel where there are no dependencies (health + weather + calendar can all run simultaneously, for example).

## Steps

### 1. Weather (inline)
Use the Weather MCP to get current conditions and forecast for Kansas City, MO (latitude 39.10, longitude -94.58). If unavailable, fall back to `python3 "/Users/alexhedtke/Documents/Exobrain harness/weather/get-weather.py"`. Prepare:
- Current temperature, conditions, humidity, wind
- High/low, chance of rain (flag if > 30%), UV index (flag if > 7)
- Clothing recommendation (jacket? umbrella? sunglasses? layers?)
- Flag big temperature swings in the next few days

### 2. Health
Follow the `/health` skill's **Morning Snapshot** section. Pull yesterday's Fitbit + Withings data, write the Health Log note, and prepare the `#### Health` summary for the daily note.

### 3. Calendar
Follow the `/calendar` skill's **Daily Briefing** section. List today's events and check flight buffers for the next 14 days.

### 4. Tasks
Check Things 3 (`get_today` and `get_upcoming` for next 3 days) but do NOT list them in the briefing by default. Only mention a task if:
- It was **newly created** during this briefing run
- You have **new context** to add (from email, transcript, etc.)
- You spot **procrastination** or a **deadline risk**
Trust Things 3 to surface tasks on its own — Alex checks it independently.

### 5. Priorities
Read `/Users/alexhedtke/Documents/Exobrain/Dashboard.md`. Note which tasks/events align with priorities. Flag if any priority area has no activity scheduled today.

### 6. Email
Follow the `/email` skill's **Daily Briefing** section. Scan last 24h, route actionable items, process job alerts, and run CRM enrichment on outgoing emails.

### 7. iMessage
Follow the `/imessage` skill's **Daily Briefing** section. Scan last 24h for CRM updates and task routing. This step produces no briefing output — it's purely CRM maintenance and action routing.

### 8. Mood
Follow the `/mood` skill's **Daily Briefing** section. Score yesterday, write the full sub-score breakdown to yesterday's daily note, and return the 1-line summary + mood boost recommendation for today's briefing.

### 9. Job Search
Follow the `/job-search` skill's **Daily Briefing** section. If it's a weekday, run tracker maintenance and return the pace check.

### 10. CRM
Follow the `/crm` skill's **Network scan** mode (mode 8). Create Things 3 tasks for overdue contacts. Do NOT list overdue contacts in the briefing — Things 3 tasks are sufficient. Only mention a contact if you have new context from email/transcript/calendar.

### 11. News
Check if `/Users/alexhedtke/Documents/Exobrain/News Briefings/YYYY-MM-DD.md` exists for today.
- **Does not exist**: Run the full `/news-briefing` skill (all phases).
- **Already exists**: Read the existing note.

Either way, prepare a 3-5 line summary for the daily note under `#### News`.

### 12. Local Events (read-only)
Do NOT run `/local-events` here — the full scan runs as part of the weekly review on Sundays.
Read `/Users/alexhedtke/Documents/Exobrain harness/local-events/local-events-log.json` and surface:
- Events happening **today** or **this weekend** with status "active" (1-3 lines max)
- **Favorite Artist Alerts** (always surface these prominently)
- If nothing upcoming, skip this section entirely.

### 13. Write to daily note
Create or append to today's daily note. If it doesn't exist, create it with the nav header first.

Weather goes FIRST (outside the briefing heading), then content under `### Morning briefing`:

```markdown
**Weather**: ☀️ 72°F, sunny, high of 78. No rain expected. Light layers.

### Morning briefing
#### Health
- Steps: 14,200 yesterday (✓ goal) | 7-day avg: 13,100
- [sample health data]
- Active Zone Minutes: 45 yesterday | 7-day total: 210
- Weight: 137.1 lbs | Fat: 10.5% | Muscle: 116.4 lbs (84.9%)
- Visceral fat: 1.3 | Bone: 6.2 lbs | Hydration: 41.5%
- *Recommendation: You're trending below step goal this week. 30-min walk during your lunch gap would help.*
- Full data: [[Health Log/YYYY-MM-DD|Health Log]]

**Mood yesterday**: 3/5 🟡 — steady day, self-care dipped
**🎯 Mood boost**: [specific recommendation tied to today's schedule]

#### Today
- 9:00 AM — Team standup (Zoom)
- 11:00 AM — 1:1 with Sarah
- 2:00 PM — Free block
...

#### New tasks created
- [task name] [things:///show?id=ID]
- ...
(Only list tasks created during this briefing run. Omit section if none.)

#### News
*Full briefing: [[News Briefings/YYYY-MM-DD|Today's news briefing]]*
- [Top headline — 1 sentence]
- [Second headline — 1 sentence]
- [Interest area highlight — 1 sentence]
(3-5 lines max.)

#### Flags
(Only if something worth flagging: procrastination, deadline risk, new context, exceptional job posting. Omit if nothing to flag.)
```

All briefing subsections use H4 (`####`) to nest under the H3. Do NOT include standalone "Tasks Due", "Upcoming", or "Overdue Contacts" sections.

### 14. Notify
```bash
osascript -e 'display notification "Your daily briefing is ready in today'\''s note" with title "Exobrain" sound name "Purr"'
```

Also send a Discord notification via `reply` to the chat_id from `DISCORD_NOTIFY_CHAT_ID` in `.env`:
> ☀️ **Morning Briefing** — [weather summary]. [step count vs goal]. [number] events today, [number] tasks due. [top priority or flag for the day]
