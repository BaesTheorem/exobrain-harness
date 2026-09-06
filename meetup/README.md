# meetup

Unofficial command-line client for **meetup.com**. Search events by keyword, browse what is
on near a place, read an event or a group in full, and, with a login cookie, list your
RSVPs and groups or RSVP from the terminal.

Meetup's documented API (`api.meetup.com/gql-ext`) is OAuth-only, and the OAuth consumer
keys behind it come with paid plans. The website itself talks to a second GraphQL endpoint,
`https://www.meetup.com/gql2`, that answers anonymous requests for search, events, groups,
and locations, and reads the browser's session cookie for anything personal. This CLI speaks
to that endpoint. Nothing here is official; Meetup can change it at any time. Introspection
is enabled on it, which is where the field names came from.

## Install / invoke

`bin/meetup` is a stdlib-only Python 3.11+ script: no venv, no dependencies. It registers
itself with the tools registry through the `bin/` scan.

```sh
"meetup/bin/meetup" -h
"meetup/bin/meetup" search -h      # flags for one command
```

## Quick tour

```sh
meetup search "board games" --days 14                  # keyword search near home, next two weeks
meetup search AI --near "Lawrence, KS" --radius 10 --type physical
meetup events --days 3 --free                          # what is on, no keyword needed
meetup event 316119292                                 # full details; an event URL works too
meetup event 316119292 --similar 5                     # plus five similar events
meetup group pythonkc                                  # profile, ratings, next events, last event
meetup group-events pythonkc --past --limit 10
meetup groups "effective altruism"                     # group search near home
meetup locations "Overland Park"                       # what --near resolves to
meetup home                                            # default location and timezone

meetup auth set                                        # paste a browser cookie header (see below)
meetup whoami
meetup my-events                                       # your upcoming RSVPs (--past for history)
meetup my-groups
meetup rsvp 316119292 yes                              # asks first; --yes to skip; --guests N
meetup save 316119292                                  # bookmark; --unsave to undo
meetup raw '{ locationSearch(query: "Lawrence, KS") { name lat lon } }'
```

Everything above the `auth` line works **without an account**. Add `--json` to any command to
get the CLI's normalized records instead of text; `raw` prints the server's `data` verbatim.

## Location and time

- **Home** is Kansas City, MO (`39.0999,-94.5999`, `America/Chicago`). Override with
  `MEETUP_HOME='lat,lon,label'` and `MEETUP_TZ` in the environment or the harness `.env`.
- `--near PLACE` runs Meetup's own location search and takes the first hit; `meetup locations`
  shows what it would pick. `--lat`/`--lon` skip the lookup.
- `--radius` is in **miles**. Online events carry no location and pass every radius; add
  `--type physical` when distance matters.
- `--days N` means from now through the end of the Nth day. `--from`/`--to` accept
  `YYYY-MM-DD`, `'YYYY-MM-DD HH:MM'`, `today`, `tomorrow`, or `+Nd`; a bare date in `--to`
  means the end of that day. Times are interpreted in the home timezone. `events` defaults
  to the next 7 days; `search` defaults to everything upcoming.
- Event times print in the event's own local time, as Meetup returns them.

## Search versus browse

`search` is Meetup's keyword search. Its relevance ranking is fuzzy and semantic, so the top
results for "AI" are AI talks but the tail is anything loosely related; with `--sort date`
that tail is interleaved with the good matches. Use relevance (the default) and take the top
few, or use `events` for the whole feed and filter yourself. `events` is the same
recommendation feed the site's "find events" page shows for a location, sorted by date.

## JSON records

Event records (`search`, `events`, `event`, `group-events`, `my-events`, `--similar`):

| Field | Meaning |
| --- | --- |
| `id`, `title`, `url` | Event id, title, page URL |
| `start`, `end`, `duration` | ISO-8601 in the event's local offset; `duration` is ISO-8601 (`PT2H`) |
| `type`, `online` | `physical`, `online`, or `hybrid`; `online` is true when there is no venue to go to |
| `venue` | `{name, address, city, state, postalCode, country, lat, lon}`, or `null` for online events |
| `group` | `{id, name, urlname, url}` |
| `going`, `waitlist`, `maxTickets` | Yes RSVPs, waitlist size (detail only), capacity (`null` = unlimited) |
| `fee`, `free` | `{amount, currency}` when Meetup collects a fee; `free` is true when it does not (external tickets are invisible here) |
| `status`, `rsvpState` | `ACTIVE`, `PAST`, `CANCELLED`...; `JOIN_OPEN`, `CLOSED`, `FULL`... |
| `isAttending`, `isSaved`, `myRsvp` | Only meaningful with a cookie |
| `description`, `howToFindUs`, `hosts`, `topics`, `series` | Detail commands only |

Group records add `members`, `rating`, `ratings`, `category`, `private`, `joinMode`,
`founded`, `organizer`, `topics`, `upcomingCount`, `pastCount`, and `lastEvent`.

## Login (the cookie lane)

Personal commands send your browser's `Cookie` header. Copy it from any request to
`www.meetup.com/gql2` in DevTools (Network tab, Request Headers) after logging in, then run
`meetup auth set` and paste. It is stored in `secrets/cookie.txt` (mode `0600`, gitignored);
`MEETUP_COOKIE` in the environment or the harness `.env` overrides the file. Logging out of
that browser session kills it; `meetup auth status` tells you when it has died. Details in
`secrets/README.md`.

A rejected cookie does not error on the wire: Meetup answers `self: null`. The CLI turns that
into exit status 3 with a message to refresh the cookie.

`rsvp` is the only command that changes anything on your account. It prints the event, asks
for confirmation, and refuses to run non-interactively without `--yes`.

**Status:** every read command above was verified live against meetup.com on 2026-09-06.
The cookie lane (`whoami`, `my-events`, `my-groups`, `rsvp`, `save`) is written straight from
the endpoint's schema but has not yet been run with a real session, so treat its first use as
a test: `whoami` first, then `my-events`, then a `rsvp` on an event you would attend anyway.

## Wire notes (for extending beyond the CLI)

| | |
| --- | --- |
| Endpoint | `POST https://www.meetup.com/gql2`, JSON `{query, variables}`, HTTP 200 even on GraphQL errors |
| Auth | Cookie header; no CSRF token was needed for anonymous reads |
| Introspection | On. `meetup raw '{ __schema { queryType { fields { name } } } }'` lists 90+ root fields; `eventSearch`, `recommendedEvents`, `groupByUrlname`, `groupSearch`, `event`, `events(where: {ids})`, `similarEvents`, `locationSearch`, `self` are the ones used here |
| `eventSearch` | Needs a non-empty `query`; an empty one returns nothing. `filter: {query, lat, lon, radius, startDateRange, endDateRange, eventType}`, `sort: {sortField: RELEVANCE\|DATETIME}` |
| `recommendedEvents` | Keyword-less browse. Same filter fields (dates are strings there); `sort: {sortField: DATETIME\|RELEVANCE}` |
| `totalCount` on search connections | Offset plus rows returned so far. Do not read it as a result-set size; `pageInfo.hasNextPage` is the only end signal, and `endCursor` is a base64 offset |
| `first` | Approximate: the server pads a few extra rows. The client truncates to the requested limit |
| Dates | ISO-8601 with an explicit offset works (`2026-09-06T00:00:00-05:00`); the site itself sends a zoned form (`...-04:00[US/Eastern]`), which also works |
| Radius | Miles. Checked by measuring returned venues: `radius: 2` kept everything within 1.2 mi |
| `Event.rsvps` | Filter by status for counts: `rsvps(filter: {rsvpStatus: [YES]}) { totalCount }`; aliases work |
| `Group.events` | `status: ACTIVE\|PAST`, `sort: ASC\|DESC`, optional `filter: {afterDateTime, beforeDateTime}`; `totalCount` here is real |
| `feeSettings` | `null` means free through Meetup; `maxTickets: 0` means unlimited |
| Private groups | `groupByUrlname` still answers with public fields; member counts read 0 |
| Mutations | `rsvp(input: {eventId, response: YES\|NO, guestsCount})`, `saveEvent`, `unsaveEvent`, `joinGroup`; organizer-side `createEvent`, `editEvent`, `announceEvent`, `deleteEvent` exist and are not built |

## Tests

```sh
pytest tests/test_meetupcli.py
```

They drive the client through a fake transport, so nothing touches the network: ref parsing,
date windows, request shapes, pagination, error handling, normalization, and the cookie store.
