---
name: discord-digest
description: Scan Alex's friend group Discord server for events, plans, and activity. Summarizes what happened and what's coming up. Used by daily briefing for the Discord recap section, and can be run standalone. Use when the user asks about Discord, the friend group, "what are my friends up to", "anything on Discord", "check the group chat", "what did I miss", "any plans with friends", "what's the group doing", or when triggered by the daily briefing.
---

# Discord Digest

Scans Alex's friend group Discord server and summarizes activity so nothing falls through the cracks.

## Friend Group Server — Username Mapping

| Discord Username | Real Name | Notes |
|-----------------|-----------|-------|
| [discord_user] | **Alex Hedtke** | This is Alex himself |
| [discord_user] | [Friend] | |
| [discord_user] | [Friend] | |
| [discord_user] | [Friend] |
| [discord_user] | [Friend] | |
| [discord_user] | Cale | friend |
| [discord_user] | [Friend] | friend's partner |
| [discord_user] | [Friend] | friend |
| [discord_user] | Jesse | Partner is [Friend] |
| [discord_user] | [Friend] | [Friend]' brother |
| [discord_user] | Gabe | |
| [discord_user] | Anish | |
| [discord_user] | Austin | |
| [discord_user] | [Friend] | Venmo: @[Friend]-Antonacci |

## Channels Monitored (read-only)

- **General**: `945577631133351950`
- **Musings and advice**: `945857863090311258`
- **Hangouts**: `945577794732167211`

All channels are set to `requireMention: true` with empty `allowFrom` — the bot reads but never responds.

## How to Scan

1. Use `fetch_messages` on each channel (limit 100 for Hangouts, 50 for General, 30 for Musings)
2. Use `list_threads` on Hangouts to discover active/recent threads, then `fetch_messages` on each thread
3. Filter to messages from the past 24 hours (for daily briefing) or past 7 days (for weekly/standalone)
4. **Always replace Discord usernames with real names** using the mapping above
5. Skip [discord_user] messages — that's Alex, he already knows what he said
6. **Always cross-reference scheduling discussions with Alex's Google Calendar and Things 3** — flag conflicts, don't assume availability

## What to Extract

### Events & Plans
- Any message mentioning a date, time, or place for a group activity
- RSVPs and ticket purchases (who's going, who's on the fence)
- Venue details, costs, logistics
- Create a Things 3 task or calendar event for anything Alex hasn't responded to yet

### Questions & Mentions
- Direct @mentions of Alex ([discord_user] or his Discord user ID)
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
- **`/hey-claude`**: Can answer "what did I miss on Discord?" or "what's the group up to?"

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

Beyond factual updates, pay attention to how people interact in the server and update the `## Personality & Dynamics` section of their People/ note:
- **Communication style**: Shitposter, earnest, devil's advocate, lurker-who-drops-bangers, etc.
- **Social role in the group**: Organizer, hype person, contrarian, mediator, quiet observer
- **Emotional patterns**: How they give feedback, handle disagreement, show enthusiasm or frustration
- **Group dynamics**: Who responds to whom, recurring debates, alliances, friction points
- **Recurring behaviors across sessions**: Always volunteers to organize, tends to bail last-minute, consistently shares niche content, etc.

Use specific examples from messages rather than vague labels. Flag noteworthy dynamics in the digest when relevant (e.g., "[Friend] and [Friend] independently pushing back on the same point — emerging pattern").
