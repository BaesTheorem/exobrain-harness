# kcurbex

Indexes site reports from the [Kansas City Urban Explorers](https://www.kcurbex.org/)
forum into Obsidian, and syncs the board's meetups to Google Calendar.

## The access ceiling (read this first)

The board is tiered, and Alex's account sits at **Tier 1**. That is not a tooling
limit and no amount of scraping changes it:

- Tier 1 sees six forums. Site reports live in **Share Your Adventure!** (f=30);
  meetups in **Meetups!** (f=109). Everything else is invisible.
- The board's calendar extension renders its month grid for Tier 1 but every event
  cell comes back empty, so meetups are parsed from threads instead.
- The archive holding older and more sensitive locations is gated. The admins say
  plainly why: threads leave the public area after 60 days so that sensitive locations
  posted there do not stay exposed.

Tier 2 is granted socially, by being vouched for in person. The pinned newbie thread
(t=5652) says to attend a public meetup or ask an established member to go explore.
**That is what the meetup sync is for.** It is the unlock for the rest.

Nothing here tries to route around the tiering. It reads what the account is granted.

## Commands

    bin/kcurbex whoami          # which forum account the stored session belongs to
    bin/kcurbex scan            # fetch the last year of site reports -> data/reports.json
    bin/kcurbex geocode-prep    # write un-located reports to data/to_geocode.json
    bin/kcurbex geocode-apply   # fold data/geocoded.json back in, rebuild the vault
    bin/kcurbex vault           # re-project reports to Obsidian (notes + .base)
    bin/kcurbex meetups         # list parsed meetup threads
    bin/kcurbex auth-calendar   # one-time Google Calendar consent
    bin/kcurbex sync-calendar   # push upcoming meetups to Google Calendar
    bin/kcurbex watch           # the unattended pass (what launchd runs)

## Geocoding

Reports are deliberately vague, so locating them is a judgement task, not a lookup.
`geocode-prep` writes the pending reports out; a model reads them, identifies what it
can from landmarks and quoted news stories, and writes `data/geocoded.json`.
`geocode-apply` folds that back in. Unattended runs do the same step through
`claude --print`.

Every geocode carries a confidence: `exact`, `block`, `neighborhood`, `region`,
`unknown`.

**`region` means the metro centroid, not the site.** Distance is therefore only
computed for `exact`/`block`/`neighborhood`. Without that rule every unidentified KC
report lands 2.44 mi from home and sails through a 3-mile filter as a false hit. The
vault marks those `proximity: unplaceable` with a null distance, and they collect in
the database's "Needs locating" view.

## Obsidian output

- `Areas/Adventure & Creativity/Urbex/Sites/<title> (<topic id>).md` -- one note per report
- `Areas/Adventure & Creativity/Urbex/KC Urbex Sites.base` -- views: Within 3 miles,
  All sites by distance, Newest first, Needs locating

Notes are a projection of `data/reports.json`. Anything written below the `## Notes`
marker is preserved across regeneration; everything above it is rewritten.

## The watcher

`com.exobrain.kcurbex-watch` runs `run-watch.sh` every 12 hours: scan, geocode
anything new, re-project the vault, sync upcoming meetups, notify. Logs to
`~/.claude/channels/kcurbex/watch.log`. A failed pass raises a banner, because a
watcher going quiet looks exactly like "no new sites" from outside.

## Etiquette

This is a small volunteer forum on shared hosting. The client sleeps 2.5s between
requests and the watcher runs twice a day. Do not raise either. Everything here is
read-only: it never posts, replies, PMs, or edits.
