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

`whoami`, `my-events`, `my-calendar`, `my-groups`, `rsvp`, and `save` use Alex's browser
cookie. `meetup auth import` pulls it out of Chrome through yt-dlp (no Keychain prompt on this
machine; verified 2026-09-07). `meetup auth set` takes a pasted header instead. Exit status 3
means no cookie or a rejected one: re-run `auth import`, don't retry the command.

- **`my-events` is what he RSVP'd to** (yes or waitlist); `--past` is what he went to.
  **`my-calendar` is every upcoming event in his groups**, RSVP or not (the site's "your
  groups" view). Never present a calendar row as a plan he made.
- `my-groups` shows active memberships; `--all` adds dead and blocked ones. His organizer
  role shows on `kc_rat_ea`.
- **Never RSVP, save, or join on Alex's behalf unless he asked for that specific action** in
  this conversation. `rsvp` asks for confirmation and refuses non-interactive runs without
  `--yes`; pass `--yes` only after his explicit go-ahead.
- `rsvp` and `save` have not been run on a real event yet (as of 2026-09-07). First real use
  is a test on something he'd attend anyway; record what you learn in [[project_meetup_cli]].
- Alex organizes **KC Rationality and Effective Altruism** (`kc_rat_ea`, private, 622
  members) and pays for a Meetup organizer plan.

## Organizer writes

`create-event`, `publish`, `create-venue`, `delete-event`, and `venues` cover the organizer
lane. `create-event` makes a **draft** unless `--publish`; publishing is its own prompted
step. `announceEvent` emails the whole group and is deliberately not implemented, same
per-send approval rule as Luma blasts.

- **Publishing is the gate, drafting is not.** A draft reaches no member, no group page, and
  no mail, so drafting a batch and reading it back costs nothing. Publishing is visible to
  all 622 members at once and cannot be unsent, so it needs Alex's explicit go-ahead.
- **A draft is unannounced, not private.** Anyone querying the group for `status: DRAFT` by
  name gets the id and title back (`venue` comes back null). Fine for mirroring listings
  already public elsewhere; not a place to park anything private.
- **Never take a venue from search without checking its address.** `venues` ranks by fuzzy
  name over distance, and its records are member-entered and go stale. Both bit on the KC EA
  calendar: the KC `Minskys Pizza` is the third hit behind Lenexa and Overland Park, and the
  first `Pawn and Pint` hit still carries the Southwest Blvd address the venue moved away
  from. Search the short distinctive word (`Pawn`, not `Pawn and Pint`) since punctuation in
  the stored name (`Pawn & Pint`) hides better records, and confirm the street address
  against Google before using an id.

## Mirroring Luma onto Meetup

`bin/luma-to-meetup` (harness root) syncs the KC EA Luma calendar to `kc_rat_ea`. Luma is the
source of truth; the script only creates, never edits or deletes, so hand edits on the Meetup
side survive. Each listing opens with a link back to its Luma page. Runs are idempotent
(matching spans drafts and published alike) and drafts unless `--publish`; `--dry-run` and
`--until` bound a run. Venues live in a checked lookup table in the script, and an
unrecognized venue stops the run rather than guessing an address members would drive to.

## Feeding /local-events

The local-events skill uses this CLI as its Meetup source. `--json` event records map onto
its log: id `meetup-{id}`, `name` = `title`, `date` = `start[:10]`, time from `start`/`end`,
venue = `venue.name` + `venue.address`, `url`, and `going` as social proof. Score them with
the skill's rubric; the CLI does not judge fit.
