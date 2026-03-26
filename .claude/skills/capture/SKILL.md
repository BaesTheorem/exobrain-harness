---
name: capture
description: Quick-capture a thought, task, note, or event. Routes to the right destination (Things 3, Obsidian daily note, or Google Calendar). Use when the user says "capture", "add a task", "remember this", "note this", "quick capture", or provides a brief item to save.
---

# Quick Capture

## Behavior

When invoked with user input, determine the type:

### Task
Keywords: "need to", "should", "have to", "don't forget", "remind me", "todo", "buy", "call", "email", "follow up"

Action:
1. `search_todos` to check for duplicates
2. `add_todo` to Things 3 Inbox
3. Confirm: "Added task '[title]' to Things 3 Inbox"

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
