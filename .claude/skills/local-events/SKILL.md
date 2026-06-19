---
name: local-events
description: Discover upcoming Kansas City events Alex would enjoy. Searches Meetup, venue calendars, and library listings. Highlights favorite artists, tech/AI meetups, live music, and social opportunities. Use when the user asks "what's going on in KC", "any events coming up", "things to do this weekend", "local events", "concerts near me", or when triggered by the weekly review on Sundays.
---

# Local Events

Scans multiple sources for Kansas City events in the next 30 days, filtered for Alex's evolving interests. Runs weekly on Sundays and writes picks to the daily note.

## Evolving Preferences

**Preferences file**: `/Users/alexhedtke/Documents/Exobrain harness/local-events/local-events-prefs.json`

This file is the source of truth for what Alex likes, dislikes, and how to prioritize events. It contains:
- `favoriteArtists` — always surface these, send urgent notifications
- `highInterest` / `mediumInterest` / `lowInterest` — topic keywords for scoring
- `skip` — never surface these
- `preferredVenues` — boost events at these locations
- `constraints` — work schedule awareness, budget sensitivity, max drive time
- `feedback` — running log of Alex's reactions to surfaced events

**Learning loop**: After each run, update the preferences file:
1. If Alex attended an event (check calendar or transcripts), note it in `feedback` and consider boosting similar events
2. If Alex explicitly said they didn't like an event type, add it to `skip` or downgrade its interest tier
3. If Alex mentions a new artist, genre, hobby, or interest, add it to the appropriate tier
4. If a new venue gets repeated positive reactions, add it to `preferredVenues`
5. Keep `feedback` trimmed to the last 20 entries (oldest roll off)

Also read `[[Favorite artists]]` from the vault each run to catch any manual additions Alex makes there.

## Events Log

**Path**: `/Users/alexhedtke/Documents/Exobrain harness/local-events/local-events-log.json`

This JSON file tracks every event previously surfaced, so the same event is not shown twice across runs.

**Format**:
```json
[
  {
    "id": "fb-2118178645636758",
    "name": "BSidesKC 2026",
    "date": "2026-04-25",
    "time": "9:00 AM - 7:00 PM",
    "venue": "Kansas City Kansas Community College",
    "address": "7250 State Ave, Kansas City, KS 66112",
    "url": "https://bsideskc.org/",
    "source": "web",
    "firstSeen": "2026-04-02",
    "lastSurfaced": "2026-04-06",
    "priority": "high",
    "status": "active",
    "notes": "Description and fit rationale"
  }
]
```

**ID generation**: Use source prefix + unique identifier:
- Meetup: `meetup-{event_id or slug}`
- Venue calendar: `venue-{venue_slug}-{date}-{sanitized_name}`
- Library: `lib-{library_slug}-{date}-{sanitized_name}`
- Web search: `web-{date}-{sanitized_name}`

**Workflow**:
1. **Before surfacing**: Read the log. For each discovered event, check if an entry with a matching `id` or matching `name` + `date` already exists.
2. **If already logged with status "active"**: Skip (don't re-surface). Exception: if key details changed (date, venue, time, cancellation), update the log entry, set `status` to `"updated"`, and re-surface with a note about what changed.
3. **If already logged with status "surfaced-passed"**: Skip (event date has passed).
4. **If new**: Add to the log with `firstSeen` and `lastSurfaced` set to today, then surface it.
5. **Cleanup**: On each run, set `status` to `"surfaced-passed"` for any events whose `date` is before today.
6. **If already logged with status "updated"**: Surface once to show the change, then set status back to `"active"`.
7. **Sync to vault (always, at the end of every run)**: After the log is updated, run `python3 local-events/sync-to-vault.py`. This projects the log into one note per event under the vault's `Local Events/` folder, which the **`Local Events.base`** renders (views: This Week, Upcoming, Favorite Artists, Free, Passed, All). The log JSON stays the canonical store; the notes are a disposable projection (the folder is wiped and rewritten each run), so never hand-edit them. This is what keeps the vault view from going stale.

## Scoring Events

Score each discovered event 1-10 using these factors:

| Factor | Weight | How to score |
|--------|--------|-------------|
| Interest match | 3x | High interest keyword = 10, Medium = 6, Low = 3, Skip = 0 (discard) |
| Favorite artist | — | Auto-10, always surface regardless of other factors |
| Venue | 1x | Preferred venue = 8, Known good venue = 5, Unknown = 3 |
| Cost | 1x | Free = 10, < $20 = 7, < $50 = 5, > $50 = 3 |
| Calendar fit | 2x | No conflict = 10, Tight but doable = 5, Direct conflict = 2 |
| Accessibility | 3x | Within 10-min walk of KC Streetcar = 10, Walkable/bikeable = 7, <10 min drive = 5, >10 min drive = 2 |
| Social potential | 1x | Group-friendly / could invite people = 8, Solo = 5 |

**Transit note**: Alex does not have a car. Events on or near the KC Streetcar line are strongly preferred. Events >10 min drive away require rideshare/bus/borrowing a car — flag the transit challenge in the "Why" line and factor it into scoring. The Streetcar runs from River Market through downtown, Union Station, Crown Center, and to UMKC. Venues near this corridor (The Midland, Sprint Center/T-Mobile Center, Union Station, Screenland Armour in North KC) get a big accessibility boost.

Only surface events scoring 5+ (weighted average). Always surface favorite artists and high-interest matches regardless of score.

## Sources

Search these sources in parallel where possible.

### 1. Meetup.com (via web search)
Search for upcoming KC meetups matching interests:
- `WebSearch`: "site:meetup.com Kansas City AI" / "cybersecurity" / "tech" / "board games" / "DnD"
- Also search: "meetup.com Kansas City events this month"

### 2. KC Venue Calendars (via Defuddle)
Check major venue calendars for upcoming shows:
- Starlight Theatre: `https://www.kcstarlight.com/events`
- Knuckleheads: `https://www.knuckleheadskc.com/events`
- The Truman: `https://www.thetrumankc.com/events`
- Uptown Theater: `https://www.uptowntheater.com/events`
- recordBar: `https://www.therecordbar.com/events`
- T-Mobile Center: `https://www.t-mobilecenter.com/events`

For each venue, use `defuddle parse "[URL]" -m` (via Bash) to extract clean content from the events page — this strips navigation, ads, and boilerplate, saving 60-80% of tokens vs raw WebFetch. Only fall back to WebFetch if defuddle fails. Extract shows in the next 30 days and cross-reference artist names against the `favoriteArtists` list from the preferences file.

### 3. KC Library Events
- Kansas City Public Library: `https://kclibrary.org/events`
- Johnson County Library: `https://www.jocolibrary.org/events`
- Use Defuddle (`defuddle parse "[URL]" -m`) to fetch and filter for: author talks, tech workshops, maker events, book clubs for genres Alex reads. Fall back to WebFetch only if defuddle fails.

### 4. r/kansascity Subreddit
The KC subreddit is a high-signal source — locals post events, festivals, pop-ups, and meetups that don't show up on venue calendars. There's almost always a pinned/recent **"What's Happening This Week [date]"** megathread.

- **Megathread**: WebFetch on reddit.com is blocked. Use `curl -sL -A "Mozilla/5.0" "https://www.reddit.com/r/kansascity/search.json?q=%22What%27s%20Happening%20This%20Week%22&restrict_sr=on&sort=new&limit=5"` + jq to find this week's thread URL, then fetch `https://reddit.com/r/kansascity/comments/<id>.json?limit=300&sort=top` and extract body (`.[0].data.children[0].data.selftext`) + comments (`.[1].data.children[] | select(.kind=="t1") | .data.body`).
- **General sweep**: `curl -sL -A "Mozilla/5.0" "https://www.reddit.com/r/kansascity/new.json?limit=60"` then jq for "Things To Do 📍" flair — catches one-off event posts outside the megathread. Fetch interesting posts via `https://reddit.com/r/kansascity/comments/<id>.json` for body details.

Extract events from the megathread comments + body, score them through the same rubric, and verify dates/links against the original venue before surfacing. Reddit posts often paraphrase or get details slightly wrong — always click through to confirm.

### 5. Web Search Catch-All
Run broader searches to catch anything the other sources miss:
- `WebSearch`: "Kansas City events [current month] [year]"
- `WebSearch`: "Kansas City concerts [current month] [year]"
- `WebSearch`: "Kansas City tech events [current month]"
- `WebSearch`: "things to do Kansas City this weekend"

## Verification

Every event MUST be verified before being surfaced:
1. **Check the event URL still works** — use `WebFetch` on the event link to confirm it's not 404/cancelled
2. **Check for cancellation language** — look for "cancelled", "postponed", "rescheduled" on the page
3. **Cross-reference dates** — if an event date seems wrong or in the past, verify against the source
4. **Check against Alex's calendar** — use `gcal_list_events` to check for conflicts at the suggested event time
5. **Deduplicate** — the same event may appear across Meetup, venue sites, and web search results. Consolidate into one entry with the best link (prefer official venue/ticketing link)

## Output Format

### For daily note (appended under `### Local Events`)

```markdown
### Local Events
*Next 30 days — updated [today's date]*

#### 🎵 Favorite Artist Alert
- **[Artist] at [Venue]** — [Date] [Time] | [Link](url)
  *Tickets: [link if available]*

#### This Week
- **[Event Name]** — [Venue], [Date] [Time] | [Free/$Price] | [Link](url)
  *Why: [1-line reason this matches Alex's interests]*

#### Coming Up
- **[Event Name]** — [Venue], [Date] [Time] | [Free/$Price] | [Link](url)
  *Why: [1-line reason]*
```

Rules:
- Always include direct links to the event page or ticketing
- Favorite artist matches go in the Alert section regardless of date
- Sort by date within each section
- Include price if known, "Free" if free, omit if unknown
- Keep the "Why" line short and specific (not "this seems fun" but "cybersec meetup — good for networking + Sec+ study group potential")
- Maximum 15 events per update (quality over quantity)
- If no events match high/medium priority, say so (don't pad with low-priority filler)

## Modes

### 1. Full scan: `/local-events` (default, also triggered by Sunday weekly review)
Run all sources, verify, deduplicate, write to daily note, update preferences.

### 2. Weekend: `/local-events weekend`
Focus on Friday-Sunday events only. Quick weekend planning.

### 3. Artist watch: `/local-events artists`
Only search for favorite artists coming to KC. Check all venue calendars + web search for each artist.

### 4. Tonight: `/local-events tonight`
What's happening tonight in KC? Quick search focused on today's date only.

## Notifications

After the scan completes:

**Always**:
```bash
osascript -e 'display notification "[N] new events found for the next 30 days" with title "Exobrain" sound name "Purr"'
```

**Favorite artist alert** (urgent):
```bash
osascript -e 'display notification "[Artist] is coming to KC on [date]!" with title "Exobrain URGENT" sound name "Basso"'
```

## Integration with Other Skills

- **`/daily-briefing`**: The briefing should reference the most recent Local Events scan if there's anything notable today or this weekend (1-2 line callout). It does NOT need to re-run the full scan — just read from the events log.
- Ad-hoc questions like "anything fun happening this weekend?" can be answered by reading the events log.
- **`/weekly-review`**: Include a "social/fun" section noting which events Alex attended or skipped, and upcoming highlights for next week.
- **`/capture`**: If Alex mentions wanting to go to something, create a Things 3 task and check if it's already in the events list.
