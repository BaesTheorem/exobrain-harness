---
name: email
description: Best practices and conventions for all Gmail interactions. Canonical reference for email scanning, job alert processing, actionable item extraction, CRM cross-referencing, and draft composition. Referenced by other skills. Use when you need to check email conventions or available MCP tools before interacting with Gmail.
---

# Gmail — Best Practices Reference

This is the canonical reference for how the Exobrain interacts with Gmail. All skills that scan, read, or draft emails MUST follow these conventions.

## MCP Tools

| Tool | Purpose |
|------|---------|
| `gmail_search_messages` | Search emails with Gmail query syntax |
| `gmail_read_message` | Read a specific message by ID |
| `gmail_read_thread` | Read a full email thread |
| `gmail_create_draft` | Create a draft reply or new email |
| `gmail_get_profile` | Get account profile info |
| `gmail_list_labels` | List all Gmail labels |
| `gmail_list_drafts` | List existing drafts |

## Best Practices

### CRITICAL Rules

1. **Date filtering on every scan.** Always use `after:YYYY/MM/DD` in `gmail_search_messages` queries to scope results. Never scan the full inbox without a date bound.

2. **Read FULL email bodies for job alerts.** Subject lines and snippets are insufficient -- job alert emails (especially LinkedIn) contain multiple listings in the body. Always call `gmail_read_message` on job alert emails to extract all roles.

3. **Actionable items become Things 3 tasks.** When an email requires action (reply needed, decision, follow-up):
   - Check Things 3 first (`search_todos`) for existing tasks
   - Create a new task only if no match exists
   - Include email context in the task notes

4. **No em dashes in outward-facing text.** When composing drafts via `gmail_create_draft`, never use em dashes. Use commas, semicolons, periods, or rewrite the sentence. Always humanize content Alex shares with others.

### Important Rules

5. **Concise in briefings.** Email sections in daily briefings and reviews surface only what needs attention. Do not dump the full inbox. Prioritize:
   - Time-sensitive requests
   - Recruiter messages and interview scheduling
   - Messages from People/ contacts (CRM-relevant)
   - Job alerts (see below)

6. **CRM cross-reference.** When scanning emails, check if any senders match People/ notes in the Obsidian vault. If a known contact emailed:
   - Flag for follow-up in the briefing
   - Consider updating their `last_contact` frontmatter
   - Append to their `## Mentions` section with dated context

7. **Job alert deduplication.** The same role often appears across Indeed, LinkedIn, Dice, and ZipRecruiter. When processing job alerts:
   - Extract role title, company, location, and link from each listing
   - Deduplicate across all alert emails
   - Report each unique role once

8. **Job alert categorization.** For each unique role:
   - **Strong Fit**: Closely matches Alex's skills and career direction. Flag prominently, suggest applying today.
   - **Moderate Fit**: Partial match, worth considering. Include with a 1-line fit summary.
   - **Skip**: Poor fit, below compensation floor, or clearly misaligned. Do not surface.
   - Separate tiers: Security roles (aligns with Sec+ direction) vs IT Support (leverages current skills) vs Skip

9. **Stale listing skepticism.** Job boards keep dead listings live indefinitely. Be skeptical of listings older than 60 days. Apply the full verification protocol before reporting a role as open.

10. **Job listing verification.** Before reporting a role as open, triangulate with 2+ independent signals:
    - Check the firm's own careers portal AND the job board listing
    - Test the application form (404 or redirect = dead)
    - LinkedIn job ID age: 37xxxxx = 2023-2024, 41-42xxxxx = late 2025, 43xxxxx+ = 2026. Old IDs are red flags.
    - Cross-reference headcount on LinkedIn/ZoomInfo (if title is already filled, role may be closed)
    - Look for repost dates, "updated" indicators, or recent applicant activity

11. **Flag recruiter outreach separately.** Direct recruiter InMail or email outreach deserves a response even if the role isn't perfect -- these are networking opportunities.

## Job Alert Email Queries

| Source | Gmail query |
|--------|------------|
| Indeed (alerts) | `from:jobalerts@indeed.com` |
| Indeed (other) | `from:alert@indeed.com` |
| LinkedIn | `from:noreply@linkedin.com subject:job` |
| Dice | `from:dice.com` |
| ZipRecruiter | `from:ziprecruiter.com` |

## Email-to-Action Pipeline

Standard flow when scanning emails produces actionable items:

1. Scan emails with `gmail_search_messages` (date-filtered)
2. Read full bodies of relevant messages with `gmail_read_message`
3. Identify actionable items (replies needed, decisions, follow-ups)
4. **Route events to Google Calendar FIRST.** Any email containing a specific date/time for a meeting, call, appointment, or event → create via `gcal_create_event` immediately (check for duplicates first). This is the #1 most commonly missed routing step. Ambiguous timing → Things 3 inbox task `Review: [event]`
5. Check Things 3 for existing tasks (`search_todos`)
6. Create tasks for genuinely new action items (`add_todo`)
7. For job-related items, log to Job Applications tracker (`/Users/alexhedtke/Documents/Exobrain/Projects/Job Search/Job Applications.md`)
8. For CRM-relevant contacts, update People/ notes

## Email Scan Patterns by Skill

| Skill | Scope | Focus |
|-------|-------|-------|
| Daily briefing | Past 24 hours | Actionable items, important threads, CRM contacts, job alerts |
| Evening winddown | Since morning briefing | New actionable items, events, CRM updates (lightweight catch-up) |
| Weekly review | Past 7 days | Full follow-up scan, task creation, thread resolution |
| Job search | Variable | Application confirmations, rejection emails, interview invitations |

## Daily Briefing

When called as part of the daily briefing:

1. **Scan last 24h**: `gmail_search_messages` with `after:` yesterday's date. Surface actionable items, important threads, recruiter messages, and messages from People/ contacts.
2. **Route events**: Any email with a specific date/time → `gcal_create_event` (check duplicates). Vague timing → Things 3 inbox task `Review: [event]`. This is the #1 most commonly missed routing — scan email bodies for dates/times, not just subject lines.
3. **Route tasks**: Actionable items → Things 3 (check for existing tasks first).
4. **Job alerts**: Search for job alert emails (Indeed, LinkedIn, Dice, ZipRecruiter). Read full bodies, deduplicate, categorize as Strong/Moderate/Skip per the `/job-search` skill's audit logic. For Strong/Moderate fits: create Things 3 task, create Obsidian note, append to job hub. Do NOT include job alerts in briefing output unless an exceptional fit.
5. **CRM enrichment** (outgoing emails): Search `from:me` for last 24h. For outgoing emails to People/ contacts, update `last_contact`. If substantive new info, enrich the People note per `/crm` mode 9 (Continuous integration). For incoming from contacts, also scan for enrichment signals.
6. **Return**: Concise list of what needs attention for the briefing. Only surface what's actionable — not a full inbox dump.

## Evening Winddown

When called as part of the evening winddown (lightweight catch-up since morning):

1. **Scan since morning**: `gmail_search_messages` with `after:` today's date. Only surface what's new since the daily briefing.
2. **Route events and tasks**: Same pipeline as daily briefing (events → Calendar, tasks → Things 3), but skip job alerts — those are a morning-only scan.
3. **CRM updates**: Check outgoing emails (`from:me`) since morning. Update `last_contact` for People/ contacts. Enrich People notes for substantive correspondence per `/crm` mode 9.
4. **Keep it lightweight**: This is a catch-up, not a full scan. Only flag items that need attention tonight or tomorrow.

## Draft Composition Rules

When creating drafts via `gmail_create_draft`:
- No em dashes (use commas, semicolons, or restructure)
- Run through de-AI conventions if the text will be sent externally
- Keep professional emails concise and direct
- Match tone to the relationship (recruiter = professional, friend = casual)
- Network outreach messages must include an offer to help (see CRM skill outreach rules)
