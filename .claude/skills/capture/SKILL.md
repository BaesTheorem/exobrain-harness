---
name: capture
description: Quick-capture a thought, task, note, or event. Routes to the right destination (Things 3, Obsidian daily note, or Google Calendar). Use when the user wants to jot something down, add a task or reminder, save a thought, "remind me to", "add to my list", "put this on my calendar", "I need to", "don't let me forget", "save this", or provides a brief item to save.
---

# Quick Capture

## Behavior

When invoked with user input, determine the type:

### Task
Keywords: "need to", "should", "have to", "don't forget", "remind me", "todo", "buy", "call", "email", "follow up"

Action:
1. `search_todos` to check for duplicates
2. `add_todo` to Things 3 Inbox (or to a matching project if obvious)
3. If routing to a project, verify the project has an Obsidian backlink in its notes field (`obsidian://open?vault=Alex's%20Exobrain&file=Projects/...`). If missing, add it via `update_project`.
4. Confirm: "Added task '[title]' to Things 3 Inbox"

### Event
Keywords: "meeting", "appointment", "on [day]", "at [time]", specific dates/times mentioned

Action:
- **Clear date/time** → `gcal_create_event`, confirm with details
- **Vague timing** → `add_todo` as "Review: [event]" in Things 3 Inbox

### Note / Thought
Keywords: "idea", "thought", "note", "remember", or anything that doesn't fit task/event

Action:
1. Append to today's daily note as a bullet point
2. If it relates to an existing Obsidian note, add a `[[wikilink]]`
3. Confirm: "Added note to today's daily note"

### Ambiguous
If unclear, default to adding as both:
- A Things 3 Inbox task
- A bullet in today's daily note

Always confirm what was captured and where it went.
