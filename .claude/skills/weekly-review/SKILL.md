---
name: weekly-review
description: Comprehensive GTD-style weekly review. Scans email, calendar, notes, Things 3, and Supernote to synthesize the past week and plan the next. Use when the user wants to reflect on or review the week, plan next week, asks "how did my week go", "what happened this week", "weekly recap", "let's do a review", "week summary", "wrap up the week", or when triggered by the Sunday scheduled task.
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
- Verify the project has an Obsidian backlink in its notes field (`obsidian://open?vault=Alex's%20Exobrain&file=Projects/...`). If missing, add it via `update_project` and create the corresponding Obsidian note if needed

### 7b. Job Search Weekly Summary
Run `/job-search status` logic to compile the week's application count and pace. Also summarize:
- Applications submitted (count, companies, roles)
- Upskilling progress (cert study sessions, training attended, exams)
- Interview activity (scheduled, completed, outcomes)
- Networking for job search (outreach sent, intros made)
Append a dated `Applications` entry to the job hub note (`/Users/alexhedtke/Documents/Exobrain/Projects/Get new job.md`) under `## Job Search Log`.

### 8. Health trends
Pull 7-day Fitbit data (steps, sleep, zone minutes) — do NOT use Fitbit for weight. Pull Withings data separately: body composition (`withings_get_body_composition` imperial) for latest snapshot, plus `withings_get_measurements` for 7-day weight/body comp trends, and blood pressure if available. Summarize trends and flag concerns.

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

### 10. Network CRM — weekly outreach pick
Surface 1 potential contact for Alex to initiate with this week:
1. Scan People/ notes with `category: potential` and `reached_out: false`
2. Pick **1 potential contact** to recommend, prioritizing those most relevant to current priorities (job search, AI safety network, local KC connections)
3. For the selected contact, include in the review:
   - Name, why they're interesting (`why_interesting` from frontmatter)
   - Suggested outreach angle (with a concrete offer to help)
   - Platform to use (or suggest one based on available info)
4. Create a Things 3 task `Reach out to [Name]` (when: anytime, tag: networking, notes: context + People note deep link). Search Things 3 first to avoid duplicates.
5. Also include a brief CRM health summary: total categorized contacts, number overdue, category distribution.

Note: Overdue active contacts are already surfaced daily in the morning briefing. The weekly review's CRM role is expanding the network via potential contacts.

### 11. Interaction highlights
Read this week's daily notes and processing log. Compile a single list of notable interaction highlights from all processed transcripts, Supernote pages, iMessages, Discord, and calendar events. Focus on things Alex might want to reflect on or act on during the review — key conversations, commitments made, interesting ideas discussed, relationship moments, unresolved threads.

### 12. Deep Recon — weekly vault reconnaissance
After completing all automated checks above, run the `/deep-recon` skill in autonomous, vault-only mode on the week's most prominent theme or open question.

**How to pick the topic:**
1. Review the week's daily notes, interaction highlights, and open questions surfaced in steps 1-11
2. Identify the thread that appeared most often OR the biggest unresolved question
3. Frame it as a research question (e.g., "How does Alex's AI governance work connect to the job search?" or "What patterns exist across this month's networking conversations?")

**Invocation:** Run `/deep-recon --autonomous --vault-only --output recon/weekly/` with the chosen topic. This dispatches 4 parallel agents (Explorer, Associator, Critic, Synthesizer) to find connections across the vault that Alex hasn't noticed.

**Cost note:** ~800k-1M tokens, 20-30 minutes. This runs after all other review steps are complete so it doesn't block the rest of the review.

**Output:** The recon document lands in `/Users/alexhedtke/Documents/Exobrain/recon/weekly/`. Include a link in the weekly review output:
> **Deep Recon**: [[recon/weekly/YYYY-MM-DD-topic-slug|This week's vault recon]] — [1-sentence summary of the most surprising finding]

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
8. **Health snapshot**: 7-day trends with recommendations
9. **Priority alignment**: Are daily activities matching stated priorities? Flag misalignment.
10. **Mood summary**: Week's mood trajectory, sub-category trends, comparison to prior week, pattern flags
11. **Network CRM**: CRM health summary + 1 recommended outreach for the week (with context and suggested angle)
12. **Interaction highlights**: Key conversations, commitments, relationship moments from the week
13. **Deep Recon**: Link to this week's vault reconnaissance document + 1-sentence highlight
14. **Manual checklist**: Items for Alex to check himself
15. **Proactive observations**: Patterns, efficiency suggestions, time-waste flags

### Notify
```bash
osascript -e 'display notification "Your weekly review is ready — check Sunday'\''s daily note" with title "Exobrain" sound name "Purr"'
```

Also send a Discord notification via `reply` to chat_id `1486464885784182834` with a summary:
> 📋 **Weekly Review ready** — [X] tasks created, [Y] overdue items flagged. Top flags: [1-2 sentence highlights]. Full review in Sunday's daily note.
