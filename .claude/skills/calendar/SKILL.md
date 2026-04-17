---
name: calendar
description: Best practices and conventions for all Google Calendar interactions. Canonical reference for event creation, flight buffers, overbooking detection, late-night date handling, and calendar verification. Referenced by other skills. Use when you need to check calendar conventions or available MCP tools before interacting with Google Calendar.
---

# Google Calendar — Best Practices Reference

This is the canonical reference for how the Exobrain interacts with Google Calendar. All skills that create, query, or reason about calendar events MUST follow these conventions.

## MCP Tools

Google Calendar is served by a hosted Claude.com connector (UUID prefix `mcp__32ab4f7e-f9e7-4457-9cb0-d1d0b280c571__`). The short aliases in this table are for documentation readability — call the actual UUID-prefixed tool names.

| Doc alias | Actual tool name | Purpose |
|-----------|------------------|---------|
| `gcal_list_events` | `mcp__32ab4f7e-...__list_events` | List events for a date or date range |
| `gcal_create_event` | `mcp__32ab4f7e-...__create_event` | Create a new event |
| `gcal_update_event` | `mcp__32ab4f7e-...__update_event` | Update an existing event |
| `gcal_delete_event` | `mcp__32ab4f7e-...__delete_event` | Delete an event |
| `gcal_get_event` | `mcp__32ab4f7e-...__get_event` | Get a specific event by ID |
| `gcal_suggest_time` | `mcp__32ab4f7e-...__suggest_time` | Suggest free slots |
| `gcal_list_calendars` | `mcp__32ab4f7e-...__list_calendars` | List all calendars |
| `gcal_respond_to_event` | `mcp__32ab4f7e-...__respond_to_event` | RSVP to an event |

### ⚠️ Parameter names (the trap)

The connector uses **camelCase** parameters, NOT the Google Calendar REST API names (`timeMin`/`timeMax`) and NOT snake_case (`start_time`/`end_time`). Unknown-param calls fail silently with `Tool execution failed. You can try again.` — there is no "unknown field" error.

Canonical `list_events` shape:

```
list_events(
  startTime: "2026-04-05T00:00:00-05:00",   # NOT time_min, NOT start_time, NOT timeMin
  endTime:   "2026-04-12T00:00:00-05:00",   # NOT time_max, NOT end_time, NOT timeMax
  pageSize: 50,                              # default 250, max 2500
  orderBy: "startTime",                      # optional: default | startTime | startTimeDesc | lastModified
  fullText: "optional keyword",              # free-form search across title/desc/location/attendees
  eventTypeFilter: ["default", "focusTime"], # optional array
  timeZone: "America/Chicago"                # optional
)
```

Canonical `create_event` / `update_event`: use `startTime` and `endTime` the same way.

If a `list_events` call fails opaquely, **first suspect**: param-name drift. Call `ToolSearch` with `select:mcp__32ab4f7e-f9e7-4457-9cb0-d1d0b280c571__list_events` to re-verify the live schema.

## Best Practices

### CRITICAL Rules

1. **Clear vs. ambiguous event routing.** This is the fundamental decision:
   - **Clear events** (specific date AND time mentioned): Create directly via `gcal_create_event`
   - **Ambiguous events** (vague timing, needs confirmation, no specific time): Create a Things 3 inbox task titled `Review: [event description]` with details in notes. Do NOT put uncertain events on the calendar.

2. **Late-night date handling.** See the Obsidian skill (rule #4) for the canonical rule. In short: before 2:00 AM = previous calendar day; 2:00 AM or later = current calendar day. Lock the target date at the start and never re-derive mid-execution.

3. **Flight buffer auto-creation.** When any flight event is detected (keywords: flight, airline names, airport codes, "depart", "fly to"), verify that two buffer events exist:
   - **"Be at airport"** -- 2 hours before departure
   - **"Travel to airport"** -- before "Be at airport", default 1 hour travel time
   Adjustments:
   - KC home to MCI is 45 minutes
   - Include departing airport address in the "Travel to airport" event location
   - Check for existing buffer events before creating to avoid duplicates
   - Daily briefing scans the next 14 days for flights

4. **Ignore Guild events.** Filter out entirely -- do not surface, do not count toward overbooking:
   - "Guild Consulate mtg"
   - "Council Mtg"
   - Any event from `council@guildoftherose.org`
   - Any event with "Guild" in the name

### Important Rules

5. **Calendar events are aspirational, not factual.** A calendar event does not prove something happened or will happen. When reviewing past events:
   - Cross-reference with Plaud transcripts (did a meeting actually occur?)
   - Cross-reference with Fitbit data (did exercise/walks actually happen? Check step counts and active zone minutes for those time windows)
   - Cross-reference with iMessages and Discord
   - Flag discrepancies constructively: "Your calendar showed a walk at 12:30 but Fitbit shows 200 steps during that window."

6. **Overbooking detection.** When previewing the next day (evening winddown, daily briefing):
   - Compare event count + task count against reasonable thresholds
   - Flag back-to-back meetings with no breaks
   - Warn Alex if the day is overstuffed
   - Suggest what to defer or cancel

7. **Duplicate check before creating.** Before `gcal_create_event`, check `gcal_list_events` for the target date to ensure a similar event doesn't already exist.

8. **Health recommendations tied to calendar gaps.** When step count is below goal, identify free blocks in the calendar and suggest specific walk times: "You're 2k steps below average -- your calendar is clear from 12-1pm, good time for a walk."

## Calendar Review Patterns by Skill

| Skill | Past window | Future window | Purpose |
|-------|------------|---------------|---------|
| Daily briefing | Today | Today + 14 days (flights) | Schedule overview, flight buffer check |
| Weekly review | Past 2 weeks | Next 4 weeks | Follow-up tasks from meetings, prep needed |
| Evening winddown | Today (recap) | Tomorrow (preview) | What happened, what's next |
| CRM lookup | Past 30 days | -- | Recent meetings with a specific person |

## Daily Briefing

When called as part of the daily briefing:

1. **Today's events**: `gcal_list_events` for today across all calendars. List each event with time and location. Filter out Guild events (per rule 4).
2. **Flight buffer check**: Scan the next 14 days for flight events (keywords: flight, airline names, airport codes, "depart", "fly to"). For any flight found, verify that "Be at airport" (2hr before) and "Travel to airport" (1hr before, adjustable) buffer events exist. Create missing buffers via `gcal_create_event` — check for duplicates first.
3. **Overbooking check**: Flag back-to-back meetings, no-break stretches, or overstuffed days.
4. **Return**: Formatted event list for the daily note under `#### Today`.

## Examples

**Creating a clear event:**
```
gcal_create_event(
  summary: "Coffee with [Name]",
  start: "2026-04-07T10:00:00",
  end: "2026-04-07T11:00:00",
  location: "Messenger Coffee, KC"
)
```

**Routing an ambiguous event to Things 3:**
```
add_todo(
  title: "Review: dinner with Sarah sometime next week",
  notes: "From 04-05 transcript. Sarah suggested dinner but no date/time set."
)
```

**Flight buffer creation:**
```
1. gcal_list_events for April 15 -- find "Flight: MCI -> SFO, departs 2:00 PM"
2. Check for existing "Be at airport" event around 12:00 PM -- none found
3. gcal_create_event("Be at airport", 12:00 PM - 2:00 PM, location: "MCI")
4. gcal_create_event("Travel to airport", 11:15 AM - 12:00 PM,
     location: "Kansas City International Airport, 1 Kansas City Blvd, Kansas City, MO 64153")
```
