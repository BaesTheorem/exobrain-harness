---
name: calendar
description: Best practices and conventions for all Google Calendar interactions. Canonical reference for event creation, flight buffers, overbooking detection, late-night date handling, and calendar verification. Referenced by other skills. Use when you need to check calendar conventions or available MCP tools before interacting with Google Calendar.
---

# Google Calendar — Best Practices Reference

This is the canonical reference for how the Exobrain interacts with Google Calendar. All skills that create, query, or reason about calendar events MUST follow these conventions.

## MCP Tools

| Tool | Purpose |
|------|---------|
| `gcal_list_events` | List events for a date or date range |
| `gcal_create_event` | Create a new event |
| `gcal_update_event` | Update an existing event |
| `gcal_delete_event` | Delete an event |
| `gcal_get_event` | Get a specific event by ID |
| `gcal_find_meeting_times` | Find mutual free times with others |
| `gcal_find_my_free_time` | Find Alex's available slots |
| `gcal_list_calendars` | List all calendars |
| `gcal_respond_to_event` | RSVP to an event |

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
