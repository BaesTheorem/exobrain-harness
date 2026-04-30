---
name: evening-winddown
description: Evening wind-down routine that recaps today, scores mood, and prioritizes tomorrow. Use when the user says "wind down", "end of day", "wrap up my day", "what happened today", "plan tomorrow", "evening review", "bedtime", "ready for bed", or when triggered by the 11:59 PM scheduled task.
---

# Evening Wind-Down

## Date Handling — CRITICAL

**Step 0:** Run `date` and lock the target date at the start. If current time is before 2:00 AM, target = previous calendar day; otherwise target = current calendar day. Resolve the daily note filename (e.g., `Wednesday, April 1st, 2026`) once and use it for everything — do NOT re-check the clock if execution crosses midnight.

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

### 1c. Plaud + Supernote Processing (MANDATORY)

Run `/process-transcript` and `/process-supernote` for any unprocessed files. The wind-down is the catch-all — never defer to "tomorrow."

### 1e. Obsidian Vault Scan (MANDATORY)

Alex writes directly in Obsidian throughout the day. Scan for notes created or modified today that haven't been processed by other steps.

1. Find Obsidian notes modified today: `find "/Users/alexhedtke/Documents/Exobrain" -name "*.md" -newermt "YYYY-MM-DD 08:00"` (use target date)
2. Filter out notes already handled by other wind-down steps (Daily notes/, Areas/Health & Fitness/Health Log/, People/, Media/, DnD/, .obsidian/, Audits/, News Briefings/, Mood Journal, Areas/)
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

**Wait for Alex's response.**

If Alex provides a score:
- Defer to the `/mood` skill for scoring methodology (the `mood` skill is canonical: Alex's self-report anchors Emotional, indirect signals fill in the others, overall is weighted toward the lowest sub-score). Update the Mood Journal and write the mood line into the wind-down section of the locked target daily note.
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

### 5. Things 3 ↔ Obsidian Project Sync (silent)

Run this silently — no output to Alex unless something needs attention.

**5a. Run the sync watcher manually** as a catch-all:
```bash
python3 "/Users/alexhedtke/Documents/Exobrain harness/things3-sync/things3-obsidian-sync.py"
```
This syncs project status (active/someday/archive), area assignments, and folder placement between Things 3 and Obsidian. It also creates notes for new Things 3 projects. The launchd watcher (`com.exobrain.things3-sync`) runs this every 15 minutes, but the wind-down is the belt-and-suspenders fallback.

**5b. Ensure Things projects have Obsidian backlinks**:
Scan Things 3 projects (`get_projects`) and for each:
1. Check if the project's notes field contains an `obsidian://` backlink
2. If missing, find the Obsidian note by scanning `Projects/` for a note with matching `things_id` in frontmatter
3. If no note exists, the sync script (5a) should have created one — log a warning if it didn't
4. Update the Things project's notes field via `update_project` to include the backlink (URL-encode the file path)

**5c. Verify area assignments**:
Every active/someday project (except Shopping List) should have an `area` property in frontmatter linking to an `Areas/` note. Flag any that are missing.

This is housekeeping — don't mention it in the wind-down output or daily note unless something failed.

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

2. **Exposure audit (Mode 2 of cybersecurity-bodyguard)**: After staging, run the pre-commit PII check:
   ```bash
   git add -A
   python3 .claude/skills/cybersecurity-bodyguard/scripts/exposure_audit.py --staged
   ```
   Interpret the exit code:
   - **0** (no findings): proceed to commit
   - **1** (MED only — employer/username/alias match): show findings to Alex in the wind-down output, ask "Proceed with commit? (y/n)"
   - **2** (HIGH — real name, email, phone, partner info, secret, SSN/CC shape): **block the commit**. Print findings, surface as URGENT notification, create Things 3 task `SECURITY: review exposure before next commit`. Do NOT push. Exit the wind-down with the commit still staged so Alex can investigate in the morning.
   
   If `targets.json` doesn't exist yet, the script still runs generic secret/PII shape detection — do not skip this step on that basis.

3. **Commit and push**:
```bash
cd "/Users/alexhedtke/Documents/Exobrain harness"
git diff --cached --quiet || git commit -m "Auto-commit: evening wind-down $(date +%Y-%m-%d)"
git push
```

This is silent housekeeping — don't mention it in the wind-down output unless something was added to .gitignore, an exposure audit finding was surfaced, or the push fails.

### 8. Notify

```bash
osascript -e 'display notification "Evening wind-down ready — tomorrow is planned" with title "Exobrain" sound name "Purr"'
```

## Interaction Style

- **Warm and brief**. Alex is winding down — don't overwhelm.
- Lead with the recap, then mood check, then tomorrow. Natural flow.
- Don't lecture about missed goals at bedtime. Acknowledge and move on.
- If something is genuinely urgent for tomorrow, flag it clearly but calmly.
- Total output should be SHORT — this is a 3-minute check-in, not a weekly review.
