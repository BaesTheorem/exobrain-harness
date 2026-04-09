---
name: evening-winddown
description: Evening wind-down routine that recaps today, scores mood, and prioritizes tomorrow. Use when the user says "wind down", "end of day", "wrap up my day", "what happened today", "plan tomorrow", "evening review", "bedtime", "ready for bed", or when triggered by the 11:59 PM scheduled task.
---

# Evening Wind-Down

## Date Handling — CRITICAL

Alex often stays up past midnight. **The day is not over until Alex goes to bed.** The wind-down ALWAYS belongs in the day being wound down, never the next day.

**Step 0 (do this FIRST, before anything else):** Run `date` to get the current time, then compute and lock the target date:

- If current time is **before 2:00 AM**: the target date is the **PREVIOUS calendar day**. "Tomorrow" = current calendar day.
- If current time is **2:00 AM or later**: the target date is the **current calendar day**. "Tomorrow" = next calendar day.

**Immediately resolve the target daily note filename** (e.g., `Wednesday, April 1st, 2026`) and store it. Use ONLY this pre-resolved filename for all daily note operations. Do NOT re-check the clock later — the date is locked at the start, even if the clock crosses midnight during execution.

This applies to ALL purposes: daily note, calendar events, Fitbit data, task completion, mood scoring, and tomorrow planning.

## Steps

Gather all data in parallel where possible, then present conversationally.

### 1. Day Recap

**Calendar**: Use `gcal_list_events` for today. List what happened:
- Events attended (note if any were skipped or cancelled)
- How the day actually played out vs the morning briefing plan (read today's daily note for the briefing)

**Tasks**:
- `get_today` — what's still on today's list? What got completed?
- Check today's daily note for any tasks that were added during the day
- Flag anything that rolled over (didn't get done and should be rescheduled)

**Health so far**:
Follow the `/health` skill's **Evening Update** section. Pull today's final Fitbit activity totals and update the Health Log note. Steps vs 15,000 goal — note the gap but don't nag (it's bedtime).

**Communication**:
- `python3 "/Users/alexhedtke/Documents/Exobrain harness/imessage/imessage-reader.py" unread` — any unanswered messages to flag for tomorrow
- `python3 "/Users/alexhedtke/Documents/Exobrain harness/imessage/imessage-reader.py" recent --hours 24 --limit 100` — scan today's messages for actionable items
- Discord scan (last 12 hours)

**Email scan**:
Follow the `/email` skill's **Evening Winddown** section. Lightweight catch-up since the morning briefing — route new events/tasks, update CRM, skip job alerts.

**Route actionable items from iMessage, Discord, Plaud transcripts, Supernote data, and email**:
- **Tasks**: If a message mentions something Alex needs to do, create a Things 3 task (check for duplicates first). Include context about who asked and when.
- **Events**: If a message mentions plans with a specific date/time, create a Google Calendar event (clear) or Things inbox task `Review: [event]` (ambiguous).
- **People notes**: Update People/ notes for anyone mentioned with dated context. Create new People notes for new contacts.
- **CRM follow-ups**: If someone asked Alex something he hasn't replied to, flag it for tomorrow.
- **CRM last_contact updates**: For any outgoing iMessages or emails Alex sent today, update `last_contact` in the corresponding People/ note frontmatter to today's date. This is critical for keeping the Network CRM accurate — outgoing communication resets the contact timer.

### 1b. Cycle Tracker Check

Run the `/cycle-tracker` skill to check current phase status:
1. Read `cycle-data.json` and calculate current phase, day of cycle, and next predicted period
2. Update the `## Cycle Tracking` section in partner's People note with current phase, cycle day, average length, next predicted date, any recent symptoms, and set `**Last synced**` to today's date
3. If the period is predicted within 2 days, or currently in PMS/menstrual phase, note it briefly in the wind-down output
4. If Alex mentioned any cycle-related observations during the day (from transcripts, notes, or direct input), log them to `cycle-data.json`

This is silent housekeeping unless there's something worth flagging. The People note update ensures the CRM stays current.

### 1c. Plaud Transcript Processing (MANDATORY)

This is not optional. Process all unprocessed Plaud transcripts before continuing the wind-down.

1. Check the processing log for already-processed files (source: `"plaud"`)
2. List recent Plaud files: `ls -lt "/Users/alexhedtke/My Drive/Plaud/" | head -15`
3. For every unprocessed transcript, run `/process-transcript` — extract content, route items:
   - Tasks to Things 3 (per `/things3` conventions)
   - Events to Google Calendar (clear) or Things 3 inbox (ambiguous)
   - Notes/context to today's daily note
   - People mentions to People/ notes
   - Media mentions to individual `Media/[Title].md` notes (see CLAUDE.md schema)
4. Update the processing log for each file processed
5. Never defer transcript processing to "tomorrow" — the wind-down is the catch-all

### 1d. Supernote Processing

This is not optional. Process all unprocessed Supernote files before continuing the wind-down.

1. Check the processing log (`/Users/alexhedtke/Documents/Exobrain harness/processing-log.json`) for already-processed files
2. Check for Supernote files modified today or unprocessed: `ls -lt "/Users/alexhedtke/My Drive/Supernote/Note/" | head -10`
3. For every unprocessed file, run `/process-supernote` — OCR, extract content, route items:
   - Tasks to Things 3 (per `/things3` conventions)
   - Events to Google Calendar (clear) or Things 3 inbox (ambiguous)
   - Notes/context to today's daily note
   - People mentions to People/ notes
   - Media mentions to individual `Media/[Title].md` notes (see CLAUDE.md schema)
4. Update the processing log for each file processed
5. Never defer Supernote processing to "tomorrow" — the wind-down is the catch-all

### 1e. Apple Notes Processing

Process any unprocessed notes in the Apple Notes dump. Notes land here via `apple-notes-sync.py` every 15 minutes, but nothing extracts actionable content from them — this step closes that gap.

1. Glob `/Users/alexhedtke/My Drive/Apple Notes/*.md`
2. Check the processing log for already-processed files (source: `"apple-notes"`)
3. For every unprocessed note, read it and extract:
   - Tasks → Things 3 (per `/things3` conventions)
   - Events → Google Calendar (clear) or Things 3 inbox (ambiguous)
   - People mentions → People/ notes (create or update)
   - Media mentions → individual `Media/[Title].md` notes (see CLAUDE.md schema)
   - Notes/context → today's daily note
4. Update the processing log for each note processed
5. If a note is purely informational (no actionable items), still log it as processed so it isn't re-scanned tomorrow
6. If the inbox is empty, skip silently

This mirrors step 1d (Supernote) — the wind-down is the catch-all for all input sources.

### 1f. Obsidian Vault Scan (MANDATORY)

Alex writes directly in Obsidian throughout the day. Scan for notes created or modified today that haven't been processed by other steps.

1. Find Obsidian notes modified today: `find "/Users/alexhedtke/Documents/Exobrain" -name "*.md" -newermt "YYYY-MM-DD 08:00"` (use target date)
2. Filter out notes already handled by other wind-down steps (Daily notes/, Health Log/, People/, Media/, DnD/, .obsidian/, Audits/, News Briefings/, Mood Journal)
3. For each remaining note, read it and check for:
   - **Actionable items**: Tasks, events, follow-ups → route to Things 3 / Google Calendar
   - **People mentions**: Update or create People/ notes
   - **Media mentions**: Create Media/ notes per CLAUDE.md schema
   - **Health/medical info**: Cross-reference with Health Log, flag discrepancies or new data
   - **Context for existing projects**: Note connections to active priorities (Dashboard.md)
4. Summarize what was found in the wind-down output (e.g., "Found 2 user-edited notes: Dr. Appt prep, Supplements update")
5. If a note is purely reference/study material (e.g., BlueDot reading notes), acknowledge the count but don't process individually

This catches everything Alex writes in Obsidian that isn't captured by Plaud, Supernote, Apple Notes, or other input pipelines.

### 2. Mood Self-Report

Ask Alex directly for a mood score. Keep it lightweight:

> **How was today?** Quick 1-5 + one word for what drove it.
> (e.g., "4 — productive" or "2 — exhausted")

**Wait for Alex's response.** If running as a scheduled task via Discord, send this as a Discord message and note that the daily briefing will pick up his reply tomorrow.

If Alex provides a score:
- Record it using the `/mood` skill methodology:
  - Use Alex's self-report as the primary signal
  - Supplement with indirect signals from the data already gathered (steps, sleep time, calendar density, social activity)
  - Score sub-categories (Emotional, Energy, Self-Care, Social, Purpose)
  - Update Mood Journal with daily log entry and heatmap
  - **Also write the mood entry to today's daily note** (see step 5 — the `## Evening Wind-Down` section includes the day score, but if mood was scored, also add the full sub-scores inline under the `### Evening Wind-Down` heading)
- Confirm with a one-liner: "Logged: 4/5 🟢 — productive. Self-Care flagged (only 8k steps)."

If Alex doesn't respond (scheduled task mode):
- Don't score. Leave it for the morning briefing to infer from signals.

### 2b. Health Concern Check-In

Read the health concerns config at `.claude/skills/health/health-concerns-config.md` for the current list of tracked concerns and their properties. Prompt Alex for today's scores (keep it to one line), write them to today's Health Log frontmatter, and flag any key correlations defined in the config.

### 3. Tomorrow Preview

**Calendar**: Use `gcal_list_events` for tomorrow.
- List events with times
- Flag early morning events (anything before 9 AM — "alarm recommendation")
- Flag back-to-back meetings with no breaks
- Flag travel time needed for in-person events
- Note open blocks that could be used for priority work

**Tasks**:
- `get_upcoming` filtered to tomorrow
- `get_today` to see what's still there (rollovers)

**Priority alignment**: Read Dashboard.md priorities. For tomorrow:
- Which scheduled events/tasks map to priorities?
- Are any priority areas completely unrepresented? Suggest a small action to fill the gap.
- If tomorrow looks overstuffed, flag it (per the overbooking feedback memory)

**Suggest top 3 priorities for tomorrow**: Based on deadlines, priority alignment, and what got deferred today. Frame as:
> **Tomorrow's top 3:**
> 1. [Most important/urgent thing]
> 2. [Priority-aligned task]
> 3. [Quick win or relationship maintenance]

### 4. Rollover & Cleanup

- Any tasks from today that didn't get done — suggest whether to:
  - **Reschedule** to tomorrow (if still relevant and doable)
  - **Defer** to later this week (if not urgent)
  - **Drop** (if it's been rolling over repeatedly — flag the pattern)
- If Alex has inbox items that relate to tomorrow's events, surface them

### 4b. Task Creation for All Actionable Discoveries

Throughout the wind-down, **any actionable item discovered from any source** must get a Things 3 task. Follow the `/things3` skill conventions:
1. `search_todos` first to avoid duplicates
2. If a match exists, `update_todo` to append new context
3. If no match, `add_todo` to Inbox with source context and recommendations in the notes field
4. Record the UUID and embed `things:///show?id=UUID` in the daily note

This applies to all sources: iMessages, Discord, Supernote, calendar follow-ups, priority gaps identified in the tomorrow preview, rollover decisions, unanswered messages flagged for tomorrow, and anything else actionable. If it needs doing, it gets a task.

### 5. Ensure Things projects have Obsidian backlinks (silent)

Run this silently — no output to Alex. Scan Things 3 projects (`get_projects`) and for each:
1. Check if the project's notes field contains an `obsidian://` backlink
2. If missing, check if an Obsidian note exists at `/Users/alexhedtke/Documents/Exobrain/Projects/[Project Name].md`
3. If no note exists, create one:
   ```markdown
   ## Overview
   - **Things project**: [things:///show?id=PROJECT_UUID]
   - **Created**: [today's date]
   ```
4. Update the Things project's notes field via `update_project` to include: `obsidian://open?vault=Exobrain&file=Projects/Project%20Name` (URL-encode the file path)

This is housekeeping — don't mention it in the wind-down output or daily note.

### 6. Write to Daily Note

Append to the **pre-resolved target daily note filename from Step 0**. Do NOT re-derive the date here — use the filename you locked at the start. If the clock has crossed midnight during execution, this is expected; the locked date is correct.

```markdown
### Evening Wind-Down
**Day score**: [mood score if provided] [emoji] — [one word]
- Emotional: [score] | Energy: [score] | Self-Care: [score] | Social: [score] | Purpose: [score]

**Completed**: [count] tasks, [count] events attended
**Rolled over**: [list any deferred tasks with brief reason]
**Steps**: [count] ([% of goal])

**Unanswered**: [any messages to handle tomorrow]
**Routed today**: [X] tasks created, [Y] events created, [Z] People notes updated (from iMessage/Discord/Supernote)

**Tomorrow's top 3**:
1. [priority 1]
2. [priority 2]
3. [priority 3]

**Tomorrow's schedule**: [count] events, first at [time]
[alarm recommendation if early start]
```

Keep it SHORT. This is a wind-down, not a briefing. Alex is going to bed.

### 7. Git Auto-Commit

Commit and push any changes to the Exobrain harness repo:

1. **Gitignore audit**: Run `git status --short` and review any new untracked files (`??`). Flag anything that looks like it should be gitignored:
   - Files containing secrets, tokens, or credentials (`.env`, `*-token*`, `*secret*`)
   - Runtime state or cache files (`*.json` logs, `*-state.json`, `*.db`, `*.sqlite`)
   - Personal data dumps (message exports, health data exports, transcript raw files)
   - OS/editor junk (`.DS_Store`, `*.swp`, `Thumbs.db`)
   - Large binary files (images, audio, video) that don't belong in version control
   
   If anything should be ignored, add it to `.gitignore` before committing. If uncertain, mention it to Alex briefly (e.g., "Added `foo.db` to .gitignore — looked like runtime state").

2. **Commit and push**:
```bash
cd "/Users/alexhedtke/Documents/Exobrain harness"
git add -A
git diff --cached --quiet || git commit -m "Auto-commit: evening wind-down $(date +%Y-%m-%d)"
git push
```

This is silent housekeeping — don't mention it in the wind-down output unless something was added to .gitignore or the push fails.

### 8. Notify

```bash
osascript -e 'display notification "Evening wind-down ready — tomorrow is planned" with title "Exobrain" sound name "Purr"'
```

If running as scheduled task, also send Discord message to the chat_id from `DISCORD_NOTIFY_CHAT_ID` in `.env`:
> 🌙 **Wind-down** — [1-line day summary]. Tomorrow: [count] events, top priority: [#1 priority].
>
> How was today? Quick 1-5 + one word.

## Interaction Style

- **Warm and brief**. Alex is winding down — don't overwhelm.
- Lead with the recap, then mood check, then tomorrow. Natural flow.
- Don't lecture about missed goals at bedtime. Acknowledge and move on.
- If something is genuinely urgent for tomorrow, flag it clearly but calmly.
- Total output should be SHORT — this is a 3-minute check-in, not a weekly review.
