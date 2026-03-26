---
name: daily-briefing
description: Generate a morning briefing with weather, health data, calendar, tasks, and priorities. Writes to today's Obsidian daily note. Use when the user says "briefing", "what's on today", "morning summary", "good morning", or when triggered by the morning scheduled task.
---

# Daily Briefing

## Steps

### 1. Weather (via Open-Meteo)
Run the weather script:
```bash
python3 "/Users/alexhedtke/Documents/Exobrain harness/get-weather.py"
```
This returns JSON with current conditions and a 7-day forecast for Kansas City. From the output, prepare:
- Current temperature, conditions, humidity, wind
- High/low for today
- Chance of rain (flag if > 30%)
- UV index (flag if > 7)
- Clothing recommendation (jacket? umbrella? sunglasses? layers?)
- Flag any big temperature swings in the next few days

### 2. Health snapshot (yesterday's data)
**From Fitbit:**
- Steps (vs 15,000 goal) — use `get_daily_activity_summary` for yesterday
- Resting heart rate — use `get_heart_rate` for yesterday
- Active Zone Minutes — use `get_azm_timeseries` for past 7 days
- Sleep score/duration — use `get_sleep_by_date_range` for last night
- Calories burned

**From Withings** (when available):
- Weight (morning measurement)
- Blood pressure (if measured)

**Trend analysis:**
- Use `get_activity_timeseries` for past 7 days of steps
- Compare yesterday to weekly average
- Flag improvements or concerns
- Make a specific recommendation tied to today's schedule (e.g., "You're 2k steps below average this week — your calendar is clear from 12-1pm, good time for a walk")

### 3. Calendar
Use `gcal_list_events` for today's events across all calendars. List each event with time and location.

### 4. Tasks
- `get_today` for today's Things 3 tasks
- `get_upcoming` for next 3 days
- Flag any deadlines

### 5. Priorities check
Read `/Users/alexhedtke/My Drive/Alex's Exobrain/Dashboard.md` for current priorities. Note which of today's tasks/events align with priorities. Flag if any priority area has no activity scheduled.

### 6. Unprocessed items
- Check `/Users/alexhedtke/My Drive/Alex's Exobrain/Plaud/` for unprocessed transcripts
- Check Supernote for recently modified files

### 7. Write to daily note
Create or append to today's daily note (`/Users/alexhedtke/My Drive/Alex's Exobrain/Daily notes/[day name].md`).

If the note doesn't exist, create it with the nav header first.

Write the briefing at the top (after nav header):

```markdown
**Weather**: ☀️ 72°F, sunny, high of 78. No rain expected. Light layers.

## Health
- Steps: 14,200 yesterday (✓ goal) | 7-day avg: 13,100
- [sample health data]
- Active Zone Minutes: 45 yesterday | 7-day total: 210
- Weight: 185.2 lbs (↓0.4 from last week)
- *Recommendation: You're trending below step goal this week. 30-min walk during your lunch gap would help.*

## Today
- 9:00 AM — Team standup (Zoom)
- 11:00 AM — 1:1 with Sarah
- 2:00 PM — Free block
...

## Tasks Due
- [ ] Complete Sec+ practice exam
- [ ] Review job posting from recruiter
...

## Upcoming (next 3 days)
...

## Unprocessed
- 2 Plaud transcripts waiting
```

### 8. Notify
```bash
osascript -e 'display notification "Your daily briefing is ready in today'\''s note" with title "Exobrain" sound name "Purr"'
```

Also send a Discord notification via `reply` to chat_id `1486464885784182834` with a concise briefing summary:
> ☀️ **Morning Briefing** — [weather summary]. [step count vs goal]. [number] events today, [number] tasks due. [top priority or flag for the day]
