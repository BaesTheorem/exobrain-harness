---
name: discord-digest
description: Scan Alex's friend group Discord server for events, plans, and activity. Summarizes what happened and what's coming up. Used by daily briefing for the Discord recap section, and can be run standalone. Use when the user asks about Discord, the friend group, "what are my friends up to", "anything on Discord", "check the group chat", "what did I miss", "any plans with friends", "what's the group doing", or when triggered by the daily briefing.
---

# Discord Digest

Scans Alex's friend group Discord server and summarizes activity so nothing falls through the cracks.

## Friend Group Server — Username Mapping

The username-to-real-name mapping lives in `discord/discord-digest-fetch.py` (gitignored — contains real names). To resolve Discord usernames to real names at runtime:

1. Read the `USERNAME_MAP` dict from `discord/discord-digest-fetch.py`
2. Replace all Discord usernames with real names in output
3. Skip messages from Alex's own username
4. Cross-reference names with People/ notes in the Obsidian vault — every friend group member should have one

If the mapping file is missing, fall back to Discord display names from the API response and flag unresolved usernames for Alex to map.

## Channels Monitored (read-only)

Read channel IDs from `.env` in the harness root:
- **General**: `DISCORD_CHANNEL_GENERAL`
- **Musings and advice**: `DISCORD_CHANNEL_MUSINGS`
- **Hangouts**: `DISCORD_CHANNEL_HANGOUTS`

All channels are set to `requireMention: true` with empty `allowFrom` — the bot reads but never responds.

## How to Scan

1. Read `discord/discord-digest.json` — this is populated by `discord-digest-fetch.py` every 4 hours via launchd. It contains recent messages from all channels with metadata.
2. Filter to messages from the past 24 hours (for daily briefing) or past 7 days (for weekly/standalone)
3. **Always replace Discord usernames with real names** using the `USERNAME_MAP` in `discord/discord-digest-fetch.py`
4. Skip Alex's messages — he already knows what he said
6. **Always cross-reference scheduling discussions with Alex's Google Calendar and Things 3** — flag conflicts, don't assume availability

## What to Extract

### Events & Plans
- Any message mentioning a date, time, or place for a group activity
- RSVPs and ticket purchases (who's going, who's on the fence)
- Venue details, costs, logistics
- Create a Things 3 task or calendar event for anything Alex hasn't responded to yet

### Questions & Mentions
- Direct @mentions of Alex (username from `DISCORD_ALEX_USERNAME` in `.env`, or his Discord user ID)
- Questions asked to the group that Alex hasn't answered
- Plans that need an RSVP from Alex

### Social Context
- Who's been active (helps with CRM — these are Alex's closest friends)
- Relationship updates, life events mentioned casually
- Recurring events (Sunday coffee at Messenger Crossroads, weekly drag show at Missie's, etc.)

## Output Format (for daily briefing integration)

```markdown
## Discord

**Hangouts:**
- [Event name] — [date/time] at [location]. [Who's going]. [Does Alex need to act?]
- [Any open questions or mentions Alex should respond to]

**General:**
- [Notable conversations or topics worth knowing about]

**Musings:**
- [Anything interesting shared]
```

Keep it concise — 3-5 bullet points max unless there's a lot of activity. If nothing notable happened, just say "Quiet day on Discord."

## Integration

- **`/daily-briefing`**: Calls this skill to generate the Discord section of the morning briefing
- **`/weekly-review`**: Pulls 7-day Discord activity for the social/community section
- **`/crm`**: Cross-references Discord usernames with People/ notes — these friends should all have People notes
- Ad-hoc questions like "what did I miss on Discord?" can be answered by reading the digest

## Network CRM Integration

All friend group members should have People/ notes. When Discord activity reveals ANY new information about a person, update their People/ note. This includes but isn't limited to:
- A new person joining the group (new username) → create People/ note
- Someone organizing an event → update their People/ note with the mention
- Opinions, interests, hobbies, preferences expressed in conversation
- Plans they're making (trips, purchases, moves, career changes)
- Recommendations they give or ask for
- Relationship updates (new partner, breakup, family news)
- Work/career mentions (new job, project, complaint, win)
- Health or life circumstance updates
- Inside jokes or recurring topics associated with them
- Anything that would help Alex be a better, more attentive friend

### Personality & Social Dynamics

Follow the `/crm` skill's mode 9 (Continuous Integration) protocol — enrich `## Context`, `## Connections`, and `## Personality & Dynamics` sections with observations from Discord messages. Use specific examples, not vague labels.
