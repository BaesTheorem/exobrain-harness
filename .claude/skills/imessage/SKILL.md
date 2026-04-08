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

When reading messages, pay attention to how people communicate — not just what they say. Note patterns and update the `## Personality & Dynamics` section of their People/ note:
- **Communication style**: Direct, passive, emoji-heavy, long-form, terse, uses humor to deflect, etc.
- **Responsiveness patterns**: Quick replies, delayed but thoughtful, leaves things on read, double-texts
- **Emotional patterns**: How they handle conflict, give feedback, express care or frustration
- **Relationship dynamic with Alex**: Initiator vs. responder, advice-giver vs. advice-seeker, emotional support patterns
- **Recurring behaviors**: Always cancels last minute, tends to over-commit, consistently checks in, etc.

Use specific examples from messages rather than vague labels. Flag noteworthy dynamics to Alex when relevant (e.g., "[Friend] has texted twice this week without a reply — she may be feeling ghosted").

## Integration Notes

- Contact names are resolved from macOS AddressBook databases automatically
- Phone numbers are normalized to +1XXXXXXXXXX format for matching
- The script filters out tapbacks/reactions (associated_message_type = 0)
- Both `text` and `attributedBody` columns are checked (recent macOS stores text in binary blobs)
- If Full Disk Access is denied, the script will print a clear error message
