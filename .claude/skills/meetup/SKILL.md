---
name: meetup
description: "Search and read meetup.com from the command line via the meetup CLI -- find events by keyword or browse what's on near a place, read an event or group in full, and (with Alex's login cookie) list his RSVPs and groups or RSVP for him. Use when Alex mentions Meetup or meetup.com, asks what meetups are coming up, 'any meetups this week', names a Meetup group, asks who's going to an event, wants to RSVP, or pastes a meetup.com link. Also the Meetup source for /local-events."
metadata:
  tool: "/Users/alexhedtke/Documents/Exobrain harness/meetup"
  memory: "[[project_meetup_cli]]"
---

# /meetup

Read meetup.com through `meetup/bin/meetup`, an unofficial stdlib-only CLI in this harness
that talks to the website's own GraphQL endpoint. Read this and [[project_meetup_cli]] before
deep work so you don't re-learn the wire quirks. Full command surface, JSON shape, and
endpoint notes: `meetup/README.md`.

## The CLI

```sh
meetup/bin/meetup -h                 # every command
meetup/bin/meetup <cmd> -h           # flags for one command
```

Add `--json` to any command for normalized records (what you want when scanning for Alex).
`raw` runs any GraphQL operation when a named command doesn't cover it.

## Reads need no login

Search, browse, event detail, group detail, and location lookup are anonymous. Answer
"what's on Meetup this week" immediately, no auth.

```sh
meetup/bin/meetup events --days 7 --type physical --limit 0 --json     # everything in-person near KC
meetup/bin/meetup search "board games" --days 14                       # keyword search, relevance-ranked
meetup/bin/meetup search AI --sort date --days 30 --json               # date order (see note below)
meetup/bin/meetup event 316119292 --similar 5                          # full detail; URLs work as refs
meetup/bin/meetup group pythonkc                                        # profile, next events, last met
meetup/bin/meetup group-events Kansas-City-Boardgames --past --limit 5 # is the group still active?
meetup/bin/meetup groups "effective altruism" --limit 10
meetup/bin/meetup locations "Overland Park"                             # what --near will resolve to
```

Home is Kansas City, MO; `--near PLACE`, `--lat/--lon`, and `--radius MILES` move it.
`--days N`, `--from`, `--to` set the window (`today`, `tomorrow`, `+Nd`, or dates).

## Rules that matter

- **`search` is fuzzy.** Meetup's keyword search is semantic: the top relevance hits are
  right, the tail is anything loosely related, and `--sort date` interleaves the tail with
  the good matches. Read titles before repeating a claim. For "everything near X in the
  window," use `events` (the site's own feed) and filter yourself.
- **Online events ignore `--radius`.** They have no venue, so they pass every distance
  filter. Add `--type physical` when distance matters, or check `online` in the JSON.
- **`free` means no fee collected through Meetup.** Events with external tickets read as
  free. Say "no Meetup fee" rather than "free" when the description mentions tickets.
- **Listing fields are primary-source data.** Time, venue, counts, and status come from the
  same store the event page renders, so cite them directly. Description text is the
  organizer's own prose (a venue change, a cancellation note): quote it as the organizer's
  claim.
- **Counts:** `going` is Yes RSVPs, a social-proof signal; `maxTickets` null means no cap.
- **Group refs** are the urlname in the URL (`meetup.com/pythonkc/` -> `pythonkc`), case as
  Meetup prints it. PyKC is `pythonkc`, not `pykc`.

## Login lane (cookie)

`whoami`, `my-events`, `my-groups`, `rsvp`, and `save` need Alex's browser cookie, stored via
`meetup auth set` (steps in `meetup/secrets/README.md`). Exit status 3 means no cookie or a
rejected one; tell Alex to re-copy it, don't retry.

- **Never RSVP, save, or join on Alex's behalf unless he asked for that specific action** in
  this conversation. `rsvp` asks for confirmation and refuses non-interactive runs without
  `--yes`; pass `--yes` only after his explicit go-ahead.
- **As of 2026-09-06 the cookie lane is unverified**: no cookie has been provided, so those
  commands are written from the schema and untested. First real use is a test: `whoami`,
  then `my-events`, then an `rsvp` on something he'd attend anyway. Record what you learn in
  [[project_meetup_cli]].
- Alex organizes **KC Rationality and Effective Altruism** (`kc_rat_ea`, private, no
  upcoming events as of 2026-09-06) and pays for a Meetup organizer plan. Organizer-side
  mutations (`createEvent`, `editEvent`, `announceEvent`) exist on the endpoint and are
  **not built**; if he wants Meetup events created from the terminal, that is the next
  piece, and `announceEvent` emails members, so it needs the same per-send approval rule as
  Luma blasts.

## Feeding /local-events

The local-events skill uses this CLI as its Meetup source. `--json` event records map onto
its log: id `meetup-{id}`, `name` = `title`, `date` = `start[:10]`, time from `start`/`end`,
venue = `venue.name` + `venue.address`, `url`, and `going` as social proof. Score them with
the skill's rubric; the CLI does not judge fit.
