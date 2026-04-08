---
name: things3
description: Best practices and conventions for all Things 3 interactions. Canonical reference for task creation, deduplication, project backlinks, and task formatting. Referenced by other skills. Use when you need to check Things 3 conventions, task formatting rules, or available MCP tools before interacting with Things 3.
---

# Things 3 — Best Practices Reference

This is the canonical reference for how the Exobrain interacts with Things 3. All skills that create, update, or query tasks MUST follow these conventions.

## MCP Tools

| Tool | Purpose |
|------|---------|
| `search_todos` | Search tasks by keyword. **Use before every `add_todo`** |
| `add_todo` | Create a new task |
| `update_todo` | Update an existing task (append notes, change fields) |
| `get_inbox` | Retrieve all inbox items |
| `get_today` | Today's tasks |
| `get_upcoming` | Next 3 days of tasks |
| `get_projects` | All active projects |
| `get_anytime` | Tasks with "anytime" scheduling |
| `get_someday` | Someday/maybe items |
| `get_areas` | All areas of responsibility |
| `update_project` | Update project fields (notes, etc.) |
| `get_logbook` | Completed tasks |
| `search_advanced` | Advanced search with filters |
| `get_tagged_items` | Filter tasks by tag |
| `show_item` | Retrieve a specific item by ID |
| `add_project` | Create a new project |
| `get_headings` | Get headings within a project |
| `get_tags` | List all tags |

## Best Practices

### CRITICAL Rules

1. **Duplicate check before every add.** Always call `search_todos` before `add_todo`. If a matching task exists, use `update_todo` to append new context to its notes instead of creating a duplicate. No exceptions.

2. **Inbox is ALWAYS the destination.** Every task created by the Exobrain goes to the Inbox — no exceptions. Alex sorts and prioritizes manually.
   - **Omit `when` entirely.** Do not pass any value — not `today`, `tomorrow`, `anytime`, `someday`, or any date. ANY value moves the task out of the Inbox.
   - **Omit `list_title` and `list_id` entirely.** Setting these to a project or area also moves the task out of the Inbox.
   - **The API cannot move tasks back to Inbox.** If a task lands outside Inbox by mistake, the only fix is to cancel it and recreate it with no `when`/`list` params.
   - Always include the source (which skill, transcript, email, etc.) and all relevant context in the `notes` field.

3. **Project backlinks are mandatory.** Every Things 3 project MUST have an Obsidian backlink in its notes field:
   ```
   obsidian://open?vault=Exobrain&file=Projects/[Project%20Name]/[Project%20Name]
   ```
   When creating a project or encountering one without a backlink, add it via `update_project`. Also ensure the corresponding Obsidian project folder and note exist at `/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Projects/[Project Name]/[Project Name].md`.

4. **Sanitize all text.** Task titles and notes must be clean plaintext. No URL encoding (`%20`, `+` for spaces), no stray HTML entities. Decode before writing.

5. **Deep links in daily notes.** When referencing a task in an Obsidian daily note, always use:
   ```markdown
   - [ ] [Task name](things:///show?id=UUID)
   ```
   Capture the UUID after task creation so you can embed the link.

### Important Rules

6. **Ambiguous events become review tasks.** If a transcript or input mentions an event without a clear date/time, create a task titled `Review: [event description]` in the Inbox. Do not guess at calendar placement.

7. **Append context, don't duplicate.** When a transcript or input mentions something that matches an existing task, call `update_todo` to add the new information as a note. The task accumulates context over time.

8. **Networking task format.** Outreach tasks surfaced by the CRM use this pattern:
   - Title: `Reach out to [Name]`
   - Tags: `["networking"]`
   - Notes: Include platform, last interaction context, and People note deep link (`obsidian://open?vault=Exobrain&file=People/[Name]`)

9. **No speculative outreach tasks.** Do not create tasks for potential contacts outside the weekly review's "1 potential per week" pick. Let the CRM surface them naturally. Only create outreach tasks when there is a time-sensitive reason indicated by context.

10. **Use checklist items for discrete sub-steps.** When a task has multiple concrete actions (e.g., a list of recommendations to review, steps to complete a process), pass them as `checklist_items` rather than embedding them in the `notes` field. Reserve `notes` for context, sources, and backlinks. This makes sub-steps individually checkable in Things 3.

## Task Properties

| Property | Values / Format |
|----------|----------------|
| `title` | Clean plaintext, concise, action-oriented |
| `list` | Always omit (Inbox). Setting any value moves task out of Inbox. |
| `when` | Always omit. ANY value (`today`, `tomorrow`, `anytime`, `someday`, dates) moves task out of Inbox. |
| `deadline` | `YYYY-MM-DD` (distinct from `when`) |
| `notes` | Additional context, deep links, backlinks |
| `tags` | Array of strings, e.g. `["networking"]` |
| `checklist_items` | Array of strings for sub-tasks |

## Areas of Responsibility

Morning, Exobrain, Relationships & Community, Health & Fitness, Values & Purpose, Cognition & Learning, Emotions & Wellbeing, Location & Tangibles, Money & Finances, Adventure & Creativity, Contribution & Impact, Work & Career, Evening

## Examples

**Creating a task from a transcript:**
```
1. search_todos("dentist appointment")
2. No match found
3. add_todo(
     title: "Schedule dentist appointment",
     notes: "Source: Transcript #41 (2026-04-05)\nAlex mentioned he hasn't been to the dentist in 6 months.\nRecommendation: Schedule before the DC trip on Apr 12."
   )
4. Record UUID, embed things:///show?id=UUID in daily note
```

**Appending context to an existing task:**
```
1. search_todos("cover letter Acme")
2. Match found: UUID abc-123
3. update_todo(id: "abc-123", notes: "Source: Transcript #42 (2026-04-05)\nAlex mentioned tailoring for their cloud migration focus. Strong Fit role per job audit.")
```

**Creating a networking outreach task (CRM-surfaced):**
```
1. search_todos("Reach out to Sarah")
2. No match found
3. add_todo(
     title: "Reach out to Sarah",
     tags: ["networking"],
     notes: "Source: CRM daily briefing (2026-04-05)\nOverdue by 7 days (Cat B, 21-day frequency). Last contact: 3 weeks ago via Signal.\nContext: Discuss AI safety reading group.\nobsidian://open?vault=Exobrain&file=People/Sarah"
   )
```
