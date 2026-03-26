---
name: process-transcript
description: Process Plaud Note transcripts from the Plaud/ folder in the Obsidian vault. Extracts tasks, events, notes, and insights, routing them to Things 3, Google Calendar, and the daily note. Use when the user says "process transcript", "new transcript", "check for transcripts", or when triggered by a scheduled task.
---

# Process Transcript

## Steps

### 1. Find unprocessed transcripts
- List all `.md` files in `/Users/alexhedtke/My Drive/Alex's Exobrain/Plaud/`
- Read `/Users/alexhedtke/Documents/Exobrain harness/processing-log.json`
- Identify files not yet in the log
- If no unprocessed files, notify and stop

### 2. For each unprocessed transcript, read and analyze

Extract these categories from the transcript content:

**Tasks**: Action items, to-dos, commitments, follow-ups, things to buy/research/contact
**Events**: Meetings, appointments, deadlines with dates/times
**Notes**: Ideas, reflections, information worth remembering, key decisions
**Insights**: Connections to existing knowledge, patterns, recommendations

### 3. Route tasks to Things 3
For each task:
1. **Sanitize text**: Ensure task titles and notes are clean plaintext — no URL encoding (`+` for spaces, `%20`, etc.). If the transcript JSON contains URL-encoded strings, decode them first.
2. Use `search_todos` to check if a similar task already exists
3. If exists → `update_todo` to append new context as a note
4. If new → `add_todo` to Inbox (or to a specific project if clearly matching)
5. After creating each task, note its UUID so you can include a `things:///show?id=UUID` deep link in the daily note

### 4. Route events
- **Clear date/time** → `gcal_create_event` directly
- **Ambiguous** → `add_todo` to Things 3 Inbox as "Review: [event description]" with details in notes

### 5. Write to daily note
Determine today's date and format the daily note filename (e.g., `Wednesday, March 25th, 2026`).

Read the existing daily note. If it doesn't exist, create it with:
```
<< [[Yesterday Name|Yesterday]] | [[Tomorrow Name|Tomorrow]] >>
```

Append a section for the transcript:
```markdown
## Transcript: [filename or topic]
- **Summary**: Brief overview of the conversation/recording
- **People**: Who was involved
- **Key topics**: Main subjects discussed
- **Open questions**: Unresolved items that came up
- **Tasks created**: Links to Things 3 tasks created
- **Recommendations**: Your suggestions for new tasks/events/follow-ups
- **Connections**: Links to related [[existing notes]] in the vault
```

Before adding wikilinks, check that the target note exists by listing files in the vault.

### 6. Flag proactive observations
- If anything sounds like procrastination on a priority item, note it
- If something could be done more efficiently, suggest it
- If a task relates to current priorities (from Dashboard.md), highlight the connection

### 7. Update processing log
Append to `processing-log.json`:
```json
{
  "id": "filename.md",
  "processedAt": "ISO-8601 timestamp",
  "source": "plaud",
  "itemsCreated": { "tasks": N, "notes": N, "events": N }
}
```

### 8. Notify
```bash
osascript -e 'display notification "Processed: X tasks, Y notes, Z events from [filename]" with title "Exobrain" sound name "Purr"'
```

Also send a Discord notification via `reply` to chat_id `1486464885784182834`:
> 📝 **Transcript processed**: [filename] — X tasks, Y notes, Z events created. [1-sentence summary of content]
