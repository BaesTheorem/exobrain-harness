---
name: local-events
description: Discover upcoming Kansas City events Alex would enjoy. Searches Meetup, venue calendars, and library listings. Highlights favorite artists, tech/AI meetups, live music, and social opportunities. Use when the user asks "what's going on in KC", "any events coming up", "things to do this weekend", "local events", "concerts near me", or when triggered by the weekly review on Sundays.
---

# Local Events

Scans multiple sources for Kansas City events in the next 30 days, filtered for Alex's evolving interests. Runs weekly on Sundays and writes picks to the daily note.

## Evolving Preferences

**Preferences file**: `/Users/alexhedtke/Documents/Exobrain harness/local-events/local-events-prefs.json`

This file is the source of truth for what Alex likes, dislikes, and how to prioritize events. It contains:
- `favoriteArtists` -- always surface these, send urgent notifications
- `highInterest` / `mediumInterest` / `lowInterest` -- topic keywords for scoring
- `skip` -- never surface these
- `preferredVenues` -- boost events at these locations
- `antiVenues` -- never surface events held at these venues, regardless of topic score. Animal-welfare motivated: captive-animal entertainment (zoos, aquariums, petting zoos, animal circuses, marine parks) is blocked as a category via `skip` keywords too. Wildlife sanctuaries, rehab centers, and conservation events stay allowed, and an event that merely has animals present (Renfest falconry) is not blocked.
- `constraints` -- work schedule awareness, budget sensitivity, max drive time
- `feedback` -- running log of Alex's reactions to surfaced events

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
| Favorite artist | -- | Auto-10, always surface regardless of other factors |
| Venue | 1x | Preferred venue = 8, Known good venue = 5, Unknown = 3 |
| Cost | 1x | Free = 10, < $20 = 7, < $50 = 5, > $50 = 3 |
| Calendar fit | 2x | No conflict = 10, Tight but doable = 5, Direct conflict = 2 |
| Accessibility | 3x | Within 10-min walk of KC Streetcar = 10, Walkable/bikeable = 7, <10 min drive = 5, >10 min drive = 2 |
| Social potential | 1x | Group-friendly / could invite people = 8, Solo = 5 |

**Transit note**: Alex does not have a car. Events on or near the KC Streetcar line are strongly preferred. Events >10 min drive away require rideshare/bus/borrowing a car -- flag the transit challenge in the "Why" line and factor it into scoring. The Streetcar runs from River Market through downtown, Union Station, Crown Center, and to UMKC. Venues near this corridor (The Midland, Sprint Center/T-Mobile Center, Union Station, Screenland Armour in North KC) get a big accessibility boost.

Only surface events scoring 5+ (weighted average). Always surface favorite artists and high-interest matches regardless of score.

## Sources

Search these sources in parallel where possible.

### 1. Meetup.com (via the `meetup` CLI)
Meetup is read through the harness's own CLI (`/meetup` skill, `meetup/README.md`), not WebSearch. It hits the site's GraphQL endpoint directly, needs no login, and returns normalized JSON:

```bash
meetup/bin/meetup events --days 30 --type physical --limit 0 --json     # the whole in-person feed near KC
meetup/bin/meetup search "<keyword>" --days 30 --limit 15 --json         # per interest keyword, relevance-ranked
```

Run `events` once for the full window (it is the same feed the site shows for KC) and score every record against the preferences file. Then run `search` for the high-interest keywords (AI, cybersecurity, board games, D&D, effective altruism, rationality, philosophy) to catch anything the feed ranked low. Meetup's keyword search is fuzzy and semantic, so read titles before trusting a hit, and prefer the default relevance sort over `--sort date` for keywords.

Record mapping: id `meetup-{id}`, name = `title`, date = `start[:10]`, time from `start`/`end`, venue = `venue.name` + `venue.address`, `url` as the link. `going` is Yes RSVPs (social proof). `online: true` events have no venue and pass every radius filter; skip them unless the preferences ask for online events. `free` means no fee collected through Meetup, so events with external tickets still read as free. For a description or "how to find us" before deciding, `meetup/bin/meetup event <id>`.

### 2. KC Venue Calendars (via Defuddle)
Check major venue calendars for upcoming shows:
- Starlight Theatre: `https://www.kcstarlight.com/events`
- Knuckleheads: `https://www.knuckleheadskc.com/events`
- The Truman: `https://www.thetrumankc.com/events`
- Uptown Theater: `https://www.uptowntheater.com/events`
- recordBar: `https://www.therecordbar.com/events`
- T-Mobile Center: `https://www.t-mobilecenter.com/events`

For each venue, use `defuddle parse "[URL]" -m` (via Bash) to extract clean content from the events page -- this strips navigation, ads, and boilerplate, saving 60-80% of tokens vs raw WebFetch. Only fall back to WebFetch if defuddle fails. Extract shows in the next 30 days and cross-reference artist names against the `favoriteArtists` list from the preferences file.

### 3. KC Library Events
- Kansas City Public Library: `https://kclibrary.org/events`
- Johnson County Library: `https://www.jocolibrary.org/events`
- Use Defuddle (`defuddle parse "[URL]" -m`) to fetch and filter for: author talks, tech workshops, maker events, book clubs for genres Alex reads. Fall back to WebFetch only if defuddle fails.

### 4. r/kansascity Subreddit
The KC subreddit surfaces peer-chatter events (pop-ups, festivals, word-of-mouth plans) that venue calendars and Meetup structurally cannot carry. Direct reddit.com `.json`/`.rss` access is dead (unauth 403 since mid-2026; NEVER retry RSS, a burst causes a durable edge block). The transport is the Arctic Shift archive API via the owning module:

```bash
python3 reddit/arctic-shift-scan.py --sub kansascity --days 7
```

This writes `reddit/data/kc-events-scan.json` (gitignored): **every** post from the window (title, selftext, flair, score, permalink) plus full comment trees for any "What's Happening This Week" megathreads it detects. ~306 posts/week typical.

Judgment happens here, not in the script: read the snapshot and scan **all** posts for potential events, not just "Things To Do 📍" flair (event announcements also hide under Discussion, Bars/Nightlife, Food and Drink). Score candidates through the same rubric.

- **Check `status` first.** `"ok"` = proceed. `"stale"` = Arctic Shift's ingestion has lagged >48h; log it, skip the source this run, notify only if it persists across 2+ runs. `"blocked"` = network/API failure; silent-skip per watcher discipline.
- Reddit posts paraphrase and get details wrong -- verify dates/links against the venue before surfacing, and megathread comments need corroboration before becoming action items (tour-dates rule).
- Background: vault `recon/2026-08-23-reddit-access-paths.md`. Arctic Shift is one volunteer's tolerated archive; if it dies, old.reddit.com HTML (with `--compressed` + browser UA) is the independent fallback surface.

### 5. Web Search Catch-All
Run broader searches to catch anything the other sources miss:
- `WebSearch`: "Kansas City events [current month] [year]"
- `WebSearch`: "Kansas City concerts [current month] [year]"
- `WebSearch`: "Kansas City tech events [current month]"
- `WebSearch`: "things to do Kansas City this weekend"

WebSearch's synthesized answer text is a lead, not a fact. Treat every event/date/tour claim it produces as unverified until you open the actual listing (`WebFetch`/`defuddle`) and read it. See the primary-source rule in **Verification** -- this is doubly true for favorite-artist tour claims.

## Verification

### Favorite-artist tour claims are PRIMARY-SOURCE-ONLY (never from a search summary)

This is the one that has burned us. Any statement about a favorite artist's tour status -- "on tour," "not touring," "coming to KC," "skips KC," "nearest date is [city] [date]," a specific date/venue -- is a factual claim that MUST be confirmed by *opening and reading a primary source*: the artist's official site/tour page, or a real ticketing/venue listing (Ticketmaster/AXS/the venue's own events page) that shows the actual date.

- **A WebSearch "answer" is NOT a source.** The synthesized prose WebSearch returns is a small model summarizing snippets and it hallucinates freely (it once invented a whole Heilung North American tour, dates and venues, that every primary source flatly contradicted). Use WebSearch only to find candidate URLs, then `WebFetch`/`defuddle` the actual page and quote *it*. Aggregator prose (Songkick/Bandsintown/Concertful blurbs) also gets read directly, not trusted second-hand.
- **If you cannot confirm a date on a primary source, do not assert anything about the artist's touring.** The only safe negative is a statement about *your search*, not about the artist: write "no confirmed KC dates found for [artist] this window" -- never "[artist]'s back on tour but skips KC" or "[artist]'s nearest is [city]." Those are affirmative tour claims and require the same primary-source proof.
- **When a direct source (a watcher, an API, the artist's own page) conflicts with a search summary, the direct source wins.** Do not talk yourself out of a correct instrument because a search sounded confident.
- This applies everywhere the claim can land: the daily note, the `Local Events/` notes, the Discord ping, and the macOS notification.

### Every event MUST be verified before being surfaced:
1. **Check the event URL still works** -- use `WebFetch` on the event link to confirm it's not 404/cancelled
2. **Check for cancellation language** -- look for "cancelled", "postponed", "rescheduled" on the page
3. **Cross-reference dates** -- if an event date seems wrong or in the past, verify against the source
4. **Check against Alex's calendar** -- use `gcal_list_events` to check for conflicts at the suggested event time
5. **Deduplicate** -- the same event may appear across Meetup, venue sites, and web search results. Consolidate into one entry with the best link (prefer official venue/ticketing link)

## Output Format

### For daily note (appended under `### Local Events`)

```markdown
### Local Events
*Next 30 days -- updated [today's date]*

#### 🎵 Favorite Artist Alert
- **[Artist] at [Venue]** -- [Date] [Time] | [Link](url)
  *Tickets: [link if available]*

#### This Week
- **[Event Name]** -- [Venue], [Date] [Time] | [Free/$Price] | [Link](url)
  *Why: [1-line reason this matches Alex's interests]*

#### Coming Up
- **[Event Name]** -- [Venue], [Date] [Time] | [Free/$Price] | [Link](url)
  *Why: [1-line reason]*
```

Rules:
- Always include direct links to the event page or ticketing
- **A favorite-artist line may only appear if a primary source confirms the date (see Verification).** No confirmed date = no tour claim; at most write "no confirmed KC dates found for [artist] this window." Never fabricate tour context like "back on tour but skips KC."
- Favorite artist matches go in the Alert section regardless of date
- Sort by date within each section
- Include price if known, "Free" if free, omit if unknown
- Keep the "Why" line short and specific (not "this seems fun" but "cybersec meetup -- good for networking + Sec+ study group potential")
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

- **`/daily-briefing`**: The briefing should reference the most recent Local Events scan if there's anything notable today or this weekend (1-2 line callout). It does NOT need to re-run the full scan -- just read from the events log.
- Ad-hoc questions like "anything fun happening this weekend?" can be answered by reading the events log.
- **`/weekly-review`**: Include a "social/fun" section noting which events Alex attended or skipped, and upcoming highlights for next week.
- **`/capture`**: If Alex mentions wanting to go to something, create a Things 3 task and check if it's already in the events list.
