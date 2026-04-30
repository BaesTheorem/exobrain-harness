---
name: weekly-review
description: Comprehensive GTD-style weekly review. Scans email, calendar, notes, Things 3, and Supernote to synthesize the past week and plan the next. Use when the user wants to reflect on or review the week, plan next week, asks "how did my week go", "what happened this week", "weekly recap", "let's do a review", "week summary", "wrap up the week", or when triggered by the Sunday scheduled task.
---

# Weekly Review

Claude checks everything it can automatically, then generates a manual checklist for items only Alex can check.

## Time window (CRITICAL)

**Weekly reviews always target the previous calendar week — Sunday through Saturday — not the trailing 7 days.**

- If today is Sunday, "previous calendar week" = the Sun-Sat that just ended yesterday (i.e., 8 days ago through yesterday).
- If today is any other day (Mon-Sat), "previous calendar week" = the most recent fully-completed Sun-Sat block, which ended last Saturday. Do NOT include any days from the currently-in-progress week.
- Compute the window explicitly at the start of the review and state the date range in the output header (e.g., "Week of April 5 – April 11, 2026").
- Apply this window consistently across every step: email scan, calendar review (past leg), daily notes, health trends, mood summary, interaction highlights, and Things 3 completions.
- Exception: the calendar *forward* leg still looks at "next 4 weeks" from today, and Someday/Anytime/Inbox Things 3 views are evaluated as of now.

## Automated Checks

### 1. Email scan
Use Gmail MCP (`gmail_search_messages`) to scan the past week's emails.
- Flag anything needing follow-up
- Create Things 3 tasks for actionable items
- Note important threads

### 2. Calendar review
Use `gcal_list_events` for:
- **Past leg — the locked Sun-Sat window from above**: What happened? Generate follow-up tasks from past meetings. This is a networking superpower — identify people Alex met and suggest follow-up actions (thank-you notes, shared resources, scheduling next meeting).
- **Forward leg — next 4 weeks from today**: What's coming? Flag events needing preparation, deadlines approaching, and gaps that could be used for priority work.

### 3. Obsidian notes review
Read the past 7 daily notes from `/Users/alexhedtke/Documents/Exobrain/Daily notes/`.
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
Use `get_projects`. For each active project:
- Suggest one concrete, achievable task to complete this week
- Verify the project has an Obsidian backlink in its notes field (`obsidian://open?vault=Exobrain&file=Projects/...`). If missing, add it via `update_project` and create the corresponding Obsidian note if needed

### 7b. Job Search Weekly Summary
Run `/job-search status` logic to compile the week's application count and pace. Also summarize:
- Applications submitted (count, companies, roles)
- Upskilling progress (cert study sessions, training attended, exams)
- Interview activity (scheduled, completed, outcomes)
- Networking for job search (outreach sent, intros made)
Append a dated `Applications` entry to the job hub note (`/Users/alexhedtke/Documents/Exobrain/Projects/Get new job.md`) under `## Job Search Log`.

### 8. Health trends
Pull 7-day Fitbit data (steps, sleep, zone minutes) — do NOT use Fitbit for weight. Pull Withings data separately: body composition (`withings_get_body_composition` imperial) for latest snapshot, plus `withings_get_measurements` for 7-day weight/body comp trends, and blood pressure if available. Summarize trends and flag concerns.

### 8b. Health concerns — weekly pattern check
Read the concern dossier notes in `Areas/Health & Fitness/Concerns/` for the list of tracked properties, what to watch for, correlations to flag, and any active experiments or provider recommendations. Then read the past 7 Health Log notes and analyze accordingly. Compare to prior week if data exists (trend arrows). Update the dossier notes with any new findings or experiment results.

### 9. Mood Journal — weekly summary
Read `/Users/alexhedtke/Documents/Exobrain/Mood Journal.md` and generate the weekly summary:
1. Compile daily scores for Mon-Sun (score any unscored days using available data)
2. Calculate sub-category averages and overall week score
3. Write a 2-3 sentence weekly narrative: what drove the mood, key events, patterns
4. Compare to prior week (trend arrow: up/down/flat) if data exists
5. Update the Mood Journal with the weekly summary entry
6. Flag any concerning patterns:
   - 3+ days at 2 or below
   - Consistent sub-category weakness (e.g., Self-Care always lowest)
   - Declining trend vs. prior week(s)
   - Social overload → crash pattern
   - Purpose score chronically low (procrastination/drift signal)

### 10. Network CRM — weekly outreach pick + integration audit

**Outreach pick** (1 potential contact):
1. Scan People/ notes with `category: potential` and `reached_out: false`
2. Pick **1 potential contact** to recommend, prioritizing those most relevant to current priorities (job search, AI safety network, local KC connections)
3. For the selected contact, include in the review:
   - Name, why they're interesting (`why_interesting` from frontmatter)
   - Suggested outreach angle (with a concrete offer to help)
   - Platform to use (or suggest one based on available info)
4. Create a Things 3 task `Reach out to [Name]` (when: anytime, tag: networking, notes: context + People note deep link). Search Things 3 first to avoid duplicates.

**CRM health summary**: total categorized contacts, number overdue, category distribution.

**Integration audit (Karpathy wiki maintenance — `/crm` mode 11)**:
1. Score every active People note against the compaction triggers in [[People Note Schema]]:
   - Mentions count (>30 = signal)
   - Days since oldest unintegrated Mention
   - Duplicate section headers
   - ✅ closed Follow-ups older than 30 days
   - Section order out of canonical sequence
2. Surface the top **3-5 People notes** most in need of compaction.
3. For each, name the specific issue ("18 Mentions, 6 from before Mar 26 not lifted into Context") and recommend `/crm integrate [Name]`.
4. This is the maintenance pass that keeps the wiki actually compounding — without it, notes degrade into append-only logs.

Note: Overdue active contacts are surfaced daily in the morning briefing. The weekly review's CRM role is (a) expanding the network via potential contacts, and (b) maintaining the wiki integrity of existing notes.

### 11. Interaction highlights
Read this week's daily notes and processing log. Compile a single list of notable interaction highlights from all processed transcripts, Supernote pages, iMessages, Discord, and calendar events. Focus on things Alex might want to reflect on or act on during the review — key conversations, commitments made, interesting ideas discussed, relationship moments, unresolved threads.

### 12. Local Events — weekly scan
Run `/local-events` (full scan mode) to refresh the events log with upcoming KC events. This is the primary trigger for the local-events skill — there is no separate scheduled task. The daily briefing reads from the log this produces.

### 13. Exobrain Audit — weekly harness check
After completing all automated checks above, run the `/exobrain-audit` skill to audit the harness itself: privacy/legibility scan of tracked files, architecture recon, and AI productivity research.

**Invocation:** Invoke the `exobrain-audit` skill. It runs its three phases (Privacy & Legibility, Architecture Recon, AI Productivity Research) and produces a structured findings list.

**Cost note:** Heavy — runs multiple parallel subagents. This runs after all other review steps are complete so it doesn't block the rest of the review.

**Output:** Surface the audit findings in the weekly review output. Do NOT auto-apply fixes — present them for Alex to review first. Include a section in the weekly review:
> **Exobrain Audit**: [N] privacy findings, [N] legibility gaps, [N] architecture/efficiency suggestions. See findings below.

## Manual Checklist
Generate this for Alex to complete:
- [ ] Check Apple Notes for anything to capture
- [ ] Check physical inbox (mail, papers, etc.)
- [ ] Review computer files/downloads for anything to file or act on

*(BuJo and Supernote are auto-processed via OCR)*

## Output

Write `### Weekly Review` section in Sunday's daily note containing:

1. **Week summary**: What was accomplished, key meetings, completed tasks
2. **Email follow-ups**: Tasks created from email scan
3. **Calendar insights**: Follow-up tasks from past meetings, upcoming prep needed
4. **Inbox triage**: Suggested assignments for inbox items
5. **Procrastination flags**: Items that keep getting pushed back
6. **Someday promotion**: Item(s) suggested for this week
7. **Project next actions**: One task per active project
8. **Health snapshot**: 7-day trends with recommendations + health concern patterns (drowsiness, anxiety, panic, caffeine correlations)
9. **Priority alignment**: Are daily activities matching stated priorities? Flag misalignment.
10. **Mood summary**: Week's mood trajectory, sub-category trends, comparison to prior week, pattern flags
11. **Network CRM**: CRM health summary + 1 recommended outreach for the week (with context and suggested angle)
12. **Interaction highlights**: Key conversations, commitments, relationship moments from the week
13. **Exobrain Audit**: Privacy/legibility findings, architecture recon, and productivity research from `/exobrain-audit` (present for review, don't auto-fix)
14. **Manual checklist**: Items for Alex to check himself
15. **Proactive observations**: Patterns, efficiency suggestions, time-waste flags

### Notify
```bash
osascript -e 'display notification "Your weekly review is ready — check Sunday'\''s daily note" with title "Exobrain" sound name "Purr"'
```

