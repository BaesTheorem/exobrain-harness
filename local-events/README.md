# Local Events

Discovers upcoming Kansas City events the user would enjoy. Searches Facebook events, Meetup, venue calendars, and library listings.

## Gitignored Files

### `local-events-log.json`
Log of previously surfaced events with status tracking (active, attended, skipped). Gitignored because it reveals personal interests, attendance patterns, and location details.

**To initialize**: Create an empty file:
```json
[]
```

The `/local-events` skill populates entries. Each entry includes:
- Event name, date, venue, link, category
- Status (active/attended/skipped), personal notes, how it was surfaced

### `local-events-prefs.json`
User preference profile including favorite artists, interest categories (high/medium/low), venue preferences, accessibility constraints, and budget sensitivity. Gitignored because it contains detailed personal preferences and accessibility needs.

**To initialize**: Create a preferences file with your interests:
```json
{
  "favorite_artists": [],
  "interests": {
    "high": [],
    "medium": [],
    "low": []
  },
  "constraints": {},
  "preferred_venues": [],
  "feedback": []
}
```

The `/local-events` skill refines preferences over time based on feedback.

## Tracked Files

None currently -- this directory only contains data files and this README.
