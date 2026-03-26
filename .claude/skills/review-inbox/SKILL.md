---
name: review-inbox
description: Review and triage the Things 3 inbox, cross-referencing with calendar and Obsidian. Suggests organization for each item. Use when the user says "review inbox", "organize tasks", "triage", "inbox zero", or when triggered by the evening scheduled task.
---

# Review Inbox

## Steps

### 1. Get inbox contents
Use `get_inbox` to retrieve all Things 3 inbox items.

If inbox is empty, notify and stop.

### 2. Get context
- `gcal_list_events` for next 14 days
- `get_projects` and `get_areas` for available destinations
- List files in Obsidian vault root for related notes

### 3. For each inbox item, suggest:
- **Project/Area assignment**: Which project or area does this belong to?
- **Deadline**: Is this calendar-related? Should it have a due date?
- **Obsidian link**: Is there a related note in the vault?
- **Priority**: Is this related to a current priority from Dashboard.md?
- **Action**: Move to project, set deadline, delete if duplicate/stale, or leave in inbox if unclear

### 4. Present suggestions to user
Format as a clear list:
```
📥 Things 3 Inbox Review (N items)

1. "Buy groceries"
   → Suggest: Move to area "Personal", no deadline

2. "Follow up with Sarah re: job referral"
   → Suggest: Move to project "Job hunting", deadline: Friday
   → Related: [[Sarah meeting notes]]

3. "Review: Team offsite March 30"
   → Suggest: Create calendar event, then complete this task
```

### 5. If running unattended (scheduled task)
Don't present interactive suggestions. Instead:
- If inbox has > 5 items, send notification:
```bash
osascript -e 'display notification "You have N items in your Things inbox — time to triage" with title "Exobrain" sound name "Purr"'
```
- If any inbox items mention dates in the next 3 days, send urgent notification:
```bash
osascript -e 'display notification "Inbox item with upcoming deadline: [title]" with title "Exobrain URGENT" sound name "Basso"'
```

Also send a Discord notification via `reply` to chat_id `1486464885784182834`:
- If inbox > 5 items: > 📥 **Inbox check**: You have N items in your Things inbox — time to triage.
- If inbox has urgent items: > 🚨 **Inbox URGENT**: [title] has a deadline in the next 3 days.
- If inbox is empty: > ✅ **Inbox zero** — nothing to triage.
