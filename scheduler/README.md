# Group Scheduler

Runtime home for the `/group-scheduler` skill: MIST as the friend-group event
scheduler. Instead of a "whenisgood" poll, the skill reasons over everyone's
known constraints and proposes concrete times. See
`.claude/skills/group-scheduler/SKILL.md` for the full workflow.

## What lives here

| File | Tracked? | Purpose |
|---|---|---|
| `ics_freebusy.py` | yes | Fetches opt-in calendar feeds (ICS), caches **busy intervals only** |
| `feeds.example.json` | yes | Template for the feeds config |
| `feeds.json` | no (gitignored) | Real people + their secret ICS URLs |
| `freebusy-cache.json` | no (gitignored) | Cached busy blocks per person |
| `events/` | no (gitignored) | One JSON per in-flight event (candidates, RSVPs, status) |

## Rebuilding the gitignored parts

- `feeds.json`: copy `feeds.example.json`, add one entry per friend who has
  shared a calendar feed. Google: Settings for the calendar, "Secret address
  in iCal format". Apple: public calendar link (`webcal://`). Keys must match
  the person's People-note filename in the Obsidian vault.
- `freebusy-cache.json`: regenerated any time by `python3 ics_freebusy.py`.
- `events/`: recreated by the skill as events are planned. Losing it loses
  in-flight proposal state only, never availability data (that lives in
  People notes and the feeds).

## Privacy contract

`ics_freebusy.py` discards event titles, descriptions, locations, and
attendees at parse time; only `[start, end]` busy pairs are written anywhere.
Events marked free (`TRANSP:TRANSPARENT`, e.g. Google all-day defaults) and
cancelled events never count as busy. Constraints learned from a private feed
are used to rank candidate times but are never attributed publicly (the skill
never posts "X is busy Tuesday" from feed data).

Manually stated availability lives in each person's People note under
`## Availability` (see the People Note Schema note in the vault), not here.

Tests: `tests/test_ics_freebusy.py`.
