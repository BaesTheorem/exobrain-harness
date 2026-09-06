---
name: luma
description: Manage Luma (luma.com) events for the Kansas City EA calendar through the cookie-auth write lane -- create, clone, update, cancel events and read guest lists on the free plan via bin/luma. Use when the user mentions Luma or lu.ma, wants to create/reschedule/cancel an EA event (coffee, coworking, book club), change venues or times on the events calendar, check RSVPs or guests, or automate anything on luma.com.
---

# Luma -- Event Management Reference

Canonical reference for working with Luma. Everything here was verified live against the real API; the executable half is `bin/luma` in this repo.

## The Lane

Luma's official developer API is paywalled (Luma Plus), but the web app itself talks to `api.luma.com` authenticated by nothing more than the browser session cookie. `bin/luma` drives those same endpoints, so full write access works on the free plan.

- **Calendars**: Kansas City Effective Altruism, `cal-fBh86BiGcw6yiHW`, is the CLI's default and the only id named in source. Alex has other calendars (a personal one among them); their ids live in the harness `.env` as `LUMA_CALENDARS=name=cal-xxx,other=cal-yyy` because a bare `cal-` id lets anyone read that calendar's whole event list unauthenticated, and this repo is public. `bin/luma calendars` prints the known names. **Do not assume an event is on the KC EA calendar** -- if a named event isn't there, ask which calendar rather than editing a similarly-named one.
- **Selecting a calendar**: `--calendar` takes a name (`personal`), a `cal-` api id, or any luma.com calendar URL, and works either before or after the subcommand.
- **Auth**: `LUMA_AUTH_SESSION_KEY` in the harness `.env` (gitignored). It is the user's `luma.auth-session-key` browser cookie and grants the whole account -- treat like a password, never commit, never echo into committed files.

## The CLI

```bash
bin/luma whoami                 # cookie health check (run first when anything 401/403s)
bin/luma calendars               # known calendar names (builtins + .env)
bin/luma events [--past] [--limit N] [--calendar NAME|cal-id|URL]
bin/luma create --name X --start "YYYY-MM-DD HH:MM" [--duration 2h] [--desc TEXT] \
    [--venue "Name, Address" | --venue-from EVT] [--venue-note TEXT] \
    [--visibility public|private] [--capacity N] [--cover URL]
bin/luma clone EVT --start "YYYY-MM-DD HH:MM" [--name X] [--visibility V]
bin/luma update EVT [--name] [--start] [--duration] [--desc] [--capacity] [--visibility] \
    [--venue "Name, Address" | --venue-from EVT] [--venue-note TEXT]
bin/luma venue "Name, Address"   # preview how a venue query resolves, no write
bin/luma cancel EVT [--refund]
bin/luma guests EVT
```

Every subcommand accepts `--calendar`; without it they act on KC EA. Times are entered in America/Chicago local ("2026-09-20 11:00"); the CLI converts to the UTC wire format. `EVT` accepts an `evt-` api id, a full luma.com URL, or a bare event slug.

`clone` is the workhorse for recurring-style events: it copies name, venue, duration, cover, timezone, and the rich description from the source event.

**Venues.** `--venue` takes free text ("Crows Coffee, 304 E 51st St, Kansas City, MO 64112") or a raw Google `ChIJ...` place id and resolves it into the block the validator wants. `--venue-from` still copies a block off an existing event. On `update`, a venue move **keeps the event's existing venue note** ("We will have a table sign") unless `--venue-note` replaces it. Always run `bin/luma venue "<query>"` first and check the returned address and coordinates: Google's first match for a chain with several locations is not always the one you meant.

## Operational Rules

1. **Never trigger guest email without explicit per-send approval.** Blast/invite endpoints are deliberately not implemented in the CLI. If they are ever added, each send requires the user's explicit go-ahead for that specific send.
2. **Check guest counts before bulk edits.** Venue/time changes on events that have RSVPs may email those guests. `guests` returning 0 across the board means zero notification risk; otherwise surface it to the user before proceeding.
3. **Test-then-batch.** Any field or endpoint not previously verified gets one test write first (on a private test event, or a single instance of the batch), independently verified, before touching the rest.
4. **Verify writes through the public read side**, not the write response: re-pull `calendar/get-items` (unauthenticated) or the event page and diff the field you wrote. Same-instrument verification proves nothing.
5. **Bulk edits touch future events only.** Past events are records; leave them.
6. **Test events are `--visibility private` and cancelled immediately after.** Creation alone does not email calendar subscribers, and private events never render on the public calendar.

## API Map (for extending beyond the CLI)

Host is **`api.luma.com`**. The legacy `api.lu.ma` host still serves some reads but rejects `event/create` with an error indistinguishable from a payload mistake -- never use it for writes.

| Call | Notes |
|---|---|
| `GET /user` | Auth check; returns the logged-in user |
| `GET /calendar/get-items?calendar_api_id=&period=future\|past&pagination_limit=` | **No auth needed** on public calendars; full event objects incl. venue blocks |
| (none found) | There is no endpoint that lists *your* calendars. `calendar/list`, `user/get-calendars`, `calendar/list-user-calendars`, `home/get-calendars` all 404. Calendar ids have to be supplied by hand, hence `LUMA_CALENDARS`. |
| `GET /calendar/get?api_id=` | Calendar metadata; no auth needed |
| `GET /ics/get?entity=calendar&id=` | iCal feed; no auth needed |
| `POST /event/create` | Whole event in one request; see payload rules below |
| `POST /event/admin/update` | `event_api_id` + only the fields to change; accepts `geo_address_json` + `coordinate` for venue moves |
| `POST /event/admin/cancel-event` | Requires `should_refund` (bool) or it 400s |
| `POST /maps/resolve-place-id` | Body `{"place_id": "ChIJ..."}`. Expands a Google place id into the exact `address_info` + `coordinate` block events store. **POST only** (GET 405s). This is what `--venue` calls |
| `GET /event/admin/get-guests?event_api_id=` | Host-side guest list (`entries[]`, `has_more`); the public `get-guest-list` 403s when the event hides its guest list |
| Event page `luma.com/<slug>` | `__NEXT_DATA__` JSON embeds the full event incl. `guest_count` and `description_mirror`; fetch with the cookie for private events |

**Gotchas (each one cost real debugging):**

- **The validator is silent.** Every create/update rejection is the same bare `400 {"message":"Invalid request."}` with no field detail. For `create`, always send the full known-good template in `bin/luma` and vary values only. When probing, a 404 means wrong path; a bare 400 means the path exists and the payload is wrong.
- **Descriptions are ProseMirror.** Rich text lives in `description_mirror` (TipTap/ProseMirror doc JSON). The plain `description` field is write-nothing/read-null.
- **`start_at` is always UTC** (`...T16:00:00.000Z`); the event's display timezone is the separate `timezone` field.
- **Venues need a fully resolved Google Places block** in `geo_address_json` (place_id, full_address, city/region/country fields, `place_coordinate`) plus a top-level `coordinate`. Plain address strings are rejected. Use `--venue` (which resolves one) or lift a block from an existing event. The venue note ("we'll have a table sign") is the `description` key **inside** `geo_address_json`.
- **Getting a Google place id without a Google key.** Luma's web venue picker uses the Places JS SDK behind a referrer-restricted browser key, so there is nothing to borrow, and there is no Luma endpoint that searches places by text (only `resolve-place-id`, which needs the id you don't have yet). Google Maps' own **embed** serves the id in plain HTML: `https://maps.google.com/maps?output=embed&q=<address>`, then grep `ChIJ[A-Za-z0-9_-]+`. The main Maps page is JS-rendered and has nothing to grep. `google_place_id()` in `bin/luma` does this.
- **Cross-check the geocode.** Nominatim (`nominatim.openstreetmap.org/search?format=jsonv2`) is a free second opinion on the coordinates before a bulk venue move. Its business search is weak, so query the bare street address.
- **Cloudflare blocks non-browser user agents** (error 1010 on python-urllib's default). Send a browser UA on every request.
- **Cookie lifecycle**: the session key dies when the user logs out of that browser session. `401`, or `403` mentioning code 1010, means re-copy it: DevTools > Application > Cookies > luma.com > `luma.auth-session-key`, paste into `.env`.

## If Official Access Is Ever Wanted

The sanctioned API needs a Luma Plus subscription: per-calendar keys created in calendar settings, sent as `x-luma-api-key` to `public-api.luma.com` (docs at docs.luma.com, OpenAPI spec at `public-api.luma.com/openapi.json`). Same data model, so the CLI's payload knowledge transfers.
