---
name: daily-briefing
description: Generate a morning briefing with weather, health data, calendar, tasks, and priorities. Writes to today's Obsidian daily note. Use when the user asks about their day, wants a summary, says good morning, asks what's going on today, wants to know their schedule, asks "what do I have today", "anything I should know", "catch me up", "how's my day look", "morning", "briefing", "today's plan", or when triggered by the morning scheduled task.
---

# Daily Briefing

## Steps

### 1. Weather
Use the Weather MCP server to get current conditions and forecast for Kansas City, MO (latitude 39.10, longitude -94.58). If the Weather MCP is unavailable, fall back to running `python3 "/Users/alexhedtke/Documents/Exobrain harness/weather/get-weather.py"`. From the output, prepare:
- Current temperature, conditions, humidity, wind
- High/low for today
- Chance of rain (flag if > 30%)
- UV index (flag if > 7)
- Clothing recommendation (jacket? umbrella? sunglasses? layers?)
- Flag any big temperature swings in the next few days

### 2. Health snapshot (yesterday's data)
**From Fitbit** (steps, HR, sleep, activity — NOT weight):
- Steps (vs 15,000 goal) — use `get_daily_activity_summary` for yesterday
- Resting heart rate — use `get_heart_rate` for yesterday
- Active Zone Minutes — use `get_azm_timeseries` for past 7 days
- Sleep score/duration — use `get_sleep_by_date_range` for last night
- Calories burned

**From Withings** (weight and body composition exclusively):
- Weight — use `withings_get_weight` (imperial)
- Body composition — use `withings_get_body_composition` (imperial): fat %, muscle mass, bone mass, hydration %, visceral fat index
- Blood pressure (if measured)
- Note: Alex weighs in the morning before drinking water, so hydration % reads low (~41%) by design — not a concern

**Trend analysis:**
- Use `get_activity_timeseries` for past 7 days of steps
- Compare yesterday to weekly average
- Flag improvements or concerns
- Make a specific recommendation tied to today's schedule (e.g., "You're 2k steps below average this week — your calendar is clear from 12-1pm, good time for a walk")

**Health Log persistence:**
After pulling health data from Fitbit and Withings, write a dedicated Health Log note at:
`/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Health Log/YYYY-MM-DD.md`

Use yesterday's date (since the briefing reports on yesterday's data). The note uses YAML frontmatter with numeric properties queryable by Obsidian Bases:

```markdown
---
date: YYYY-MM-DD
steps: 14200
step_goal: 15000
resting_hr: 68
sleep_hours: 7.2
sleep_score: 82
azm: 45
calories_burned: 2450
weight_lbs: 137.1
body_fat_pct: 10.5
muscle_mass_lbs: 116.4
bone_mass_lbs: 6.2
hydration_pct: 41.5
visceral_fat: 1.3
bp_systolic:
bp_diastolic:
pulled_at: "YYYY-MM-DDTHH:MM:SS-05:00"
---
#### Notes
- [any trend observations, flags, or recommendations]
- [link to daily note: [[Daily notes/day name|date]]]
```

**Rules:**
- If the Health Log note already exists for that date, read it instead of re-querying APIs (idempotent). Only update if new data is available.
- Omit properties that have no data (e.g., no blood pressure reading = omit `bp_systolic`/`bp_diastolic` entirely, don't set to null)
- All numbers are raw numeric values (no units in frontmatter — units go in the daily note summary)
- The `Health Log.base` at the vault root renders all Health Log notes with filterable/sortable views
- Evening winddown, weekly review, mood scoring, and ad-hoc questions should read Health Log notes instead of re-querying APIs

### 3. Calendar
Use `gcal_list_events` for today's events across all calendars. List each event with time and location.

**Flight buffer check:** Also scan the next 14 days for flight events (keywords: flight, airline names, airport codes, "depart", "fly to"). For any flight found, verify that two buffer events exist:
1. **"Be at airport"** — 2 hours before departure
2. **"Travel to airport"** — before "Be at airport", default 1 hour (adjust if you know travel distance — e.g., KC home → MCI is 45 min). Include departing airport address in event location.

If buffer events are missing, create them via `gcal_create_event`. Check before creating to avoid duplicates.

### 4. Tasks
- `get_today` and `get_upcoming` for next 3 days — but do NOT list them in the briefing by default.
- Only mention a task in the briefing if:
  - It was **newly created** during this briefing run (from email, job alerts, CRM, etc.)
  - You have **new context** to add (e.g., something from email or a transcript changes the task)
  - You spot **procrastination** or a pattern worth flagging
  - There's a **deadline risk** that needs attention
- Trust Things 3 to surface tasks on its own — Alex checks it independently.

### 5. Priorities check
Read `/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Dashboard.md` for current priorities. Note which of today's tasks/events align with priorities. Flag if any priority area has no activity scheduled.

### 6. Email scan
Use `gmail_search_messages` to scan emails from the last 24 hours (`after:` yesterday's date). Surface:
- **Actionable items**: Anything needing a reply, a decision, or follow-up. Create Things 3 tasks for clear action items.
- **Important threads**: Recruiter messages, interview scheduling, time-sensitive requests.
- **CRM-relevant**: Messages from People/ contacts — flag for follow-up if needed.

**Job alert audit**: Also search for job alert emails specifically (queries: `from:jobalerts@indeed.com`, `from:alert@indeed.com`, `from:noreply@linkedin.com subject:job`, `from:dice.com`, `from:ziprecruiter.com`, or any other job board alert patterns). For each new job posting surfaced by an alert:
1. Extract the role title, company, location, and link
2. Run a quick fit assessment per `/job-search audit` logic — compare against Alex's resume and background
3. Categorize as **Strong Fit**, **Moderate Fit**, or **Skip**
4. For Strong/Moderate fits:
   a. Create a Things 3 task in Inbox: `Apply: [Role] at [Company]` (tag: job-search, notes: fit summary + link + Obsidian backlink)
   b. Create an Obsidian note at `/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Projects/Job Search/[Company] - [Role].md` with role details, fit assessment, link, and source
   c. Ensure the Things 3 task notes include an Obsidian backlink to that note
5. Append any Strong/Moderate fits to the job hub note (`/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Projects/Get new job.md`) under `## Job Search Log` as a dated `Audit` entry
6. **Do NOT include job alerts in the briefing** unless a posting is an exceptional fit (perfect role match, dream company, or unusually urgent). If you do surface one, keep it to 1 line.

Keep the email section concise in the briefing — only surface what needs attention, not a full inbox dump.

**CRM enrichment from email** (Karpathy wiki pattern): While scanning emails, check for outgoing messages Alex sent in the last 24 hours (use `gmail_search_messages` with `from:me`). For each outgoing email to someone with a People/ note:
- Update `last_contact` in their frontmatter to the email's date
- **If the email contains substantive information** (new job mention, project update, life event, introduction to someone new, interesting topic discussed): enrich the People note per the CRM skill's "Continuous integration" mode (section 9) — update Context, Connections, or expertise as appropriate
- For routine emails (confirmations, brief replies), just update `last_contact` — don't add noise
- For incoming emails from contacts, also scan for new info to integrate (e.g., new email signature = new job, mentioned a colleague = potential Connection update)

### 6b. iMessage scan for CRM
Run `python3 "/Users/alexhedtke/Documents/Exobrain harness/imessage/imessage-reader.py" recent --hours 24 --limit 100` to scan yesterday's iMessages. For each outgoing message to someone with a People/ note, update `last_contact` in their frontmatter. Also extract any actionable items (tasks, events, follow-ups) and route them per standard conventions. Do NOT list iMessages in the briefing — this step is purely for CRM maintenance and task routing.

**CRM enrichment from iMessages** (Karpathy wiki pattern): If any iMessage thread contains substantive new information about a contact (plans, life updates, new interests, mentions of other people, emotional context), enrich their People note per the CRM skill's "Continuous integration" mode (section 9). For brief/routine texts ("omw", "sounds good"), just update `last_contact`.

### 7. Mood Journal — score yesterday
Score yesterday's mood using the `/mood` skill methodology:
1. Gather evidence from all sources already pulled (Fitbit, calendar, email, tasks)
2. Score each sub-category (Emotional, Energy, Self-Care, Social, Purpose) on 1-5 scale
3. Calculate overall score (weighted toward lowest sub-scores)
4. Update `/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Mood Journal.md`:
   - Add daily log entry
   - Update the calendar heatmap cell color
5. **Write mood to yesterday's daily note**: Append a `### Mood` section to YESTERDAY's daily note (not today's) with sub-scores and primary driver:
   ```markdown
   ### Mood
   **Overall**: 3/5 🟡 — steady day, self-care dipped
   - Emotional: 3 | Energy: 2.5 | Self-Care: 2 | Social: 3.5 | Purpose: 3
   - *Primary driver: late bedtime + low steps dragged energy/self-care down*
   ```
   If yesterday's daily note doesn't exist, create it with the nav header first.
6. Include a 1-line mood summary in today's briefing output:
   > **Mood yesterday**: 3/5 🟡 — steady day, self-care dipped (late bedtime, low steps)
7. If a multi-day declining trend is detected, flag it prominently in the briefing
8. **Mood boost recommendation**: Read the week's daily log entries so far. Identify the lowest or most consistently weak sub-category, then generate ONE concrete, actionable recommendation tied to today's schedule that would improve it. Examples:
   - Self-Care lowest → "Your calendar is clear 12–1 PM. A 30-min walk would break the 3-day low-step streak and get you to 10k today."
   - Energy lowest → "You've been past 1 AM every night this week. Set an alarm for 12:30 AM tonight as a wind-down cue."
   - Purpose lowest → "No cert progress in 4 days. Block 45 min before your 2 PM meeting for one AZ-900 practice section — small win, big momentum."
   - Social lowest → "You haven't seen anyone in 3 days. Text a friend about coffee — check CRM for who's overdue."
   - Emotional lowest → "You've been running hard. Journal for 10 min this morning before the day starts — David's 'journal before acting' approach might help."

   Format in the briefing as:
   > **🎯 Mood boost**: [recommendation]

### 8. Mood in yesterday's daily note — CRITICAL
The mood section MUST be written to **yesterday's** daily note, not today's. Today's briefing displays the 1-line summary, but the full sub-score breakdown belongs in the day it describes. If the morning briefing is the first time yesterday's mood is scored (i.e., the evening winddown didn't capture it), the daily briefing is responsible for writing the `### Mood` section to yesterday's note.

### 9. Job search check
If it's a weekday, run a quick application count for the current week (search Gmail for application confirmations since Monday). Include:
- Apps submitted this week so far vs 10-20 goal
- Pace check (on track / behind / ahead)
- If behind mid-week, suggest time blocks from calendar gaps
- Upcoming interviews or job-related events from calendar

If any applications were submitted yesterday, append a brief dated log entry to the job hub note (`/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Projects/Get new job.md`) under `## Job Search Log`.

**Job Applications tracker maintenance** (do this every day):
- Read `[[Job Applications]]` (`/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Projects/Job Search/Job Applications.md`)
- Search Gmail for new application confirmations and rejection emails since the last entry date
- Add any new applications to the table (populate as many fields as possible: title, comp, location, source)
- Update status for any rejections received (change "Applied" to "Rejected" and add rejection date in Notes)
- Update status for any interview invitations (change "Applied" to "Interviewing")
- Update the totals at the bottom of the note

### 10. Network CRM — overdue contacts

**CRITICAL: Get the math right. False positives create clutter and waste Alex's mental bandwidth. False negatives mean dropped relationships. Double-check every calculation.**

Scan People/ notes for overdue contacts using the CRM methodology:
1. Glob `/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/People/*.md` and read frontmatter for notes that have `category` and `last_contact` fields
2. Compute overdue status using this exact formula:
   - `days_since = (today's date) - (last_contact date)` — count calendar days
   - `due_date = last_contact + frequency` — the date contact becomes due
   - `days_overdue = days_since - frequency` — ONLY positive values mean overdue
   - A contact is **overdue** ONLY when `days_since > frequency` (i.e., `days_overdue > 0`)
   - Example: last_contact = Mar 26, freq = 21, today = Apr 6. days_since = 11. 11 < 21. **NOT overdue** (10 days remaining).
   - Example: last_contact = Mar 16, freq = 21, today = Apr 6. days_since = 21. 21 = 21. **Due today** (0 days remaining). Overdue tomorrow.
3. **Verification step**: Before creating any task, re-read the computed values and confirm `days_since > frequency`. If delegating to a subagent, verify its results by spot-checking at least 3 contacts' math before acting on the list. Never blindly trust a subagent's overdue calculations.
4. Sort by urgency (most overdue first, Cat A before Cat B at equal days)
5. For each overdue contact, create a Things 3 task `Reach out to [Name]` (tag: networking, notes: platform + last interaction + People note deep link). Search Things 3 first to avoid duplicates.
6. **Do NOT list overdue contacts in the briefing.** Things 3 tasks are sufficient. Only mention a contact in the briefing if you have new context to add (e.g., you saw their name in an email, transcript, or event that changes the outreach approach).

### 11. News Briefing
Check if `/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/News Briefings/YYYY-MM-DD.md` exists for today.

- **If it does NOT exist**: Run the full `/news-briefing` skill (all phases — gathering, analysis, synthesis). This generates the complete briefing note.
- **If it already exists**: Skip regeneration — just read the existing note.

Either way, write a 3-5 line summary to the daily note under `#### News` (see the news-briefing skill's "Integration > Daily Briefing" section for the exact format). This section goes after Flags in the daily note template.

### 12. Local Events (read-only — full scan runs separately on Sundays)
Do NOT run `/local-events` here. The full scan runs as its own weekly scheduled task on Sundays.
Instead, read `/Users/alexhedtke/Documents/Exobrain harness/local-events/local-events-log.json` and surface:
- Any events happening **today** or **this weekend** with status "active" (1-3 lines max)
- Any **Favorite Artist Alerts** (always surface these prominently)
- If no upcoming events in the log, just skip this section

### 13. Write to daily note
Create or append to today's daily note (`/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Daily notes/[day name].md`).

If the note doesn't exist, create it with the nav header first.

Write the briefing at the top (after nav header). Weather goes FIRST, outside the Morning briefing heading. Then the briefing follows under `### Morning briefing`:

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

#### Today
- 9:00 AM — Team standup (Zoom)
- 11:00 AM — 1:1 with Sarah
- 2:00 PM — Free block
...

#### New tasks created
- [task name] [things:///show?id=ID]
- ...
(Only list tasks created during this briefing run. Omit this section if none were created.)

#### News
*Full briefing: [[News Briefings/YYYY-MM-DD|Today's news briefing]]*
- [Top headline — 1 sentence]
- [Second headline — 1 sentence]
- [Interest area or blind spot highlight — 1 sentence]
(3-5 lines max. Link to the full briefing note for details.)

#### Flags
(Only include if there's something worth flagging: procrastination, deadline risk, new context on existing tasks, exceptional job posting, contact with new info. Omit this section if nothing to flag.)

```

**Important**: All briefing subsections use H4 (`####`) so they nest under the H3. Do NOT include a standalone "Tasks Due", "Upcoming", or "Overdue Contacts" section. Those live in Things 3.

### 14. Notify
```bash
osascript -e 'display notification "Your daily briefing is ready in today'\''s note" with title "Exobrain" sound name "Purr"'
```

Also send a Discord notification via `reply` to chat_id `1486464885784182834` with a concise briefing summary:
> ☀️ **Morning Briefing** — [weather summary]. [step count vs goal]. [number] events today, [number] tasks due. [top priority or flag for the day]
