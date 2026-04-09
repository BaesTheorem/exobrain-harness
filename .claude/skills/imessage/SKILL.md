---
name: imessage
description: Read and search iMessages. Use when the user asks about texts, iMessages, wants to check messages, asks "who texted me", "any texts", "check my messages", "what did [person] say", "search texts for [keyword]", "unread messages", "unanswered texts", or wants to look up a conversation.
---

# iMessage Reader

Reads iMessages from macOS chat.db via the `imessage-reader.py` script. Requires Full Disk Access granted to the Claude Code binary.

**Script location**: `/Users/alexhedtke/Documents/Exobrain harness/imessage/imessage-reader.py`

## Commands

### List recent chats
```bash
python3 "/Users/alexhedtke/Documents/Exobrain harness/imessage/imessage-reader.py" list [--limit N]
```
Shows recent chats with last message date and message count. Default limit 30.

### Recent messages (all chats)
```bash
python3 "/Users/alexhedtke/Documents/Exobrain harness/imessage/imessage-reader.py" recent [--hours N] [--limit N]
```
Messages from the last N hours (default 24) across all chats.

### Read a specific chat
```bash
python3 "/Users/alexhedtke/Documents/Exobrain harness/imessage/imessage-reader.py" chat "Name or Phone" [--days N] [--limit N]
```
Messages from a specific person or group chat. Searches display name, chat identifier, and handle.

### Search messages
```bash
python3 "/Users/alexhedtke/Documents/Exobrain harness/imessage/imessage-reader.py" search "keyword" [--days N]
```
Full-text search across all messages in the last N days (default 30).

### Unanswered messages
```bash
python3 "/Users/alexhedtke/Documents/Exobrain harness/imessage/imessage-reader.py" unread
```
Chats where the last message (within 48h) is not from Alex. Shows sender, timestamp, and preview.

## Handling Requests

- **"Who texted me?" / "Any unread texts?"** → Run `unread` command
- **"What did [person] say?"** → Run `chat "[person]"` command
- **"Check my messages"** → Run `recent --hours 12` for a quick catch-up, or `unread` if they want actionable items
- **"Search texts for [keyword]"** → Run `search "[keyword]"`
- **"Show my recent chats"** → Run `list`

## Output Formatting

When presenting iMessage results to the user:
- Group messages by chat/conversation
- Show contact names (the script resolves phone numbers automatically)
- For unanswered messages, highlight who's waiting and how long
- If any unanswered messages relate to priorities (job hunting, PauseAI, etc.), flag them
- For CRM-relevant contacts, note if a People note exists and suggest updates

## Personality & Social Dynamics

Follow the `/crm` skill's mode 9 (Continuous Integration) protocol — enrich `## Context`, `## Connections`, and `## Personality & Dynamics` sections with observations from iMessages. Use specific examples, not vague labels.

## Daily Briefing

When called as part of the daily briefing (produces no briefing output — purely CRM maintenance and action routing):

1. **Scan last 24h**: `python3 "/Users/alexhedtke/Documents/Exobrain harness/imessage/imessage-reader.py" recent --hours 24 --limit 100`
2. **CRM last_contact**: For outgoing messages to anyone with a People/ note, update `last_contact` in frontmatter.
3. **CRM enrichment**: If any thread contains substantive new info (plans, life updates, mentions of other people), enrich the People note per `/crm` mode 9. For brief/routine texts ("omw", "sounds good"), just update `last_contact`.
4. **Route actionable items**: Extract tasks, events, and follow-ups. Route per standard conventions (Things 3 for tasks, Calendar for clear events, Things 3 inbox for ambiguous events).
5. **Do NOT list iMessages in the briefing.** This step is silent.

## Integration Notes

- Contact names are resolved from macOS AddressBook databases automatically
- Phone numbers are normalized to +1XXXXXXXXXX format for matching
- The script filters out tapbacks/reactions (associated_message_type = 0)
- Both `text` and `attributedBody` columns are checked (recent macOS stores text in binary blobs)
- If Full Disk Access is denied, the script will print a clear error message
