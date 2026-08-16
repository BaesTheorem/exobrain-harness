# Haircut booking — Rich Forever Barbershop

Keeps Alex on a 6-week haircut cadence at Rich Forever Midtown (3845 Main St,
Kansas City) without him having to remember it. Standing order:

> 2 faded to 3 on sides and back, scissors on top

## How the shop is actually shaped

This is the thing that makes the integration non-obvious. Rich Forever Midtown
is an **umbrella venue** — a booth-rental shop. The shop's own Booksy listing
(`business_id 1096259`) has `is_renting_venue: true`, no staff, no services and
no hours. There is nothing to book on it.

Each barber is a **separate Booksy business** with their own menu, prices and
calendar. `config.json` lists the five who work the Midtown chairs and the
basic-men's-haircut service id for each. Prices run $35–40; the $30 "Classic
Cut" on richforeverbarber.com is marketing copy and does not match any barber's
actual Booksy menu.

## What runs

| Piece | Does |
|---|---|
| `booksy.py` | Reads live availability from Booksy (read-only) |
| `schedule.py` | Owns the 6-week cadence and `state.json`; gates the job |
| `run-haircut-check.sh` | launchd entry; hands off to a headless MIST run |
| `com.exobrain.haircut-check.plist` | Daily at 10:00 |

The daily job is almost always a no-op. When `schedule.py check` says a cut is
due (12 days out), the shell runner starts a headless MIST run, because MIST is
the only piece with the Google Calendar MCP and therefore the only piece that
can honour "fit it wherever I'm open". MIST picks a slot, files a Things task,
and sends a notification that deep-links to the barber's Booksy page.

## Which barber gets picked

Alex's rule: **the highest-rated barber available in the window**, not the
earliest opening. Every Midtown barber sits at a flat 5.0, so stars alone
cannot separate them — review count is what actually decides, and ranking on
stars alone would silently fall back to config order while looking like it
ranked. `booksy.best_slot()` sorts by barber first and time second.

Current order: Dmilly Cutz (82) → Troy (35) → Fully Blendz (22) → Razor Nick
(14) → Xay (1). Refresh the counts in `config.json` when they drift.

## Auth: a saved session, not stored credentials

Booksy has no public auth API, and its login runs in an isolated microfrontend
iframe that can demand an SMS code. Rather than scrape a bearer token or store
a password, `login.py` opens a real browser window once, Alex logs in by hand,
and the session persists in a gitignored Chromium profile
(`.booksy-profile/`). Every later booking reuses it.

No password, token, or SMS code is ever read, stored, or logged by this repo.

```bash
python3 login.py            # one time; log in when the window opens
python3 login.py --check    # is the saved session still good?
```

When the session lapses, `book.py` fails with "session expired" and the fix is
to re-run `login.py`.

## Booking

```bash
python3 book.py --barber 1159975 --at "2026-08-29 11:00"            # dry run
python3 book.py --barber 1159975 --at "2026-08-29 11:00" --confirm  # real
```

Dry run is the default because confirming spends real money. Before it clicks
confirm, `book.py` re-reads the on-screen summary and matches the time, day,
and price against what was asked for — if Booksy shifted the slot (someone took
it between draft and confirm), it aborts rather than buying the wrong
appointment. Every run drops screenshots in `steps/`.

Booking drives the real UI rather than a guessed confirm endpoint: it is the
path Booksy actually supports, and it carries whatever prepayment or policy
step a given barber has enabled. Cancellation is free up to an hour before, so
an auto-booked slot is cheap to move.

## Booksy API notes

Undocumented, driven by the public web widget. No account needed to read:

```
POST /core/v2/customer_api/drafts/create
     {"staffer_id": -1, "business_id": N, "service_variant_id": N, "meta": {...}}
  -> {"appointment": {"id": "<uuid>", ...}}

POST /core/v2/customer_api/drafts/{uuid}/calendar    {"start": "...", "end": "..."}
POST /core/v2/customer_api/drafts/{uuid}/timeslots   {"start": "...", "end": "..."}
```

A draft is a scratch object; creating one reserves nothing. Requests need the
widget's `x-api-key` (in `booksy.py`, not a secret) and a random
`x-fingerprint`. Booking window caps at 90 days ahead.

Being undocumented, this can break without warning. When it does, the failure
is loud: `booksy.py` separates "no slots" from "could not reach Booksy" and the
runner is told never to conflate them.

## Usage

```bash
python3 booksy.py calendar --days 30              # who works which days
python3 booksy.py slots --date 2026-08-29         # open times that day
python3 booksy.py slots --from A --to B --json    # machine-readable

python3 schedule.py status                        # where the cadence stands
python3 schedule.py pending --date 2026-08-29 --barber "Razor Nick"
python3 schedule.py record  --date 2026-08-29 --barber "Razor Nick"
```

`pending` marks an appointment as lined up and silences the daily job until the
day after it happens — otherwise, with nothing on record, the job would nudge
every single morning about a haircut that is already on the calendar.

`record` is the one to run after each cut — it resets the 6-week clock and
re-arms the nudge. The clock runs from the last *completed* haircut, not the
last notification, so ignoring a nudge never silently stretches the interval.

`state.json` holds the haircut history and is gitignored as a personal log. It
is not needed to rebuild anything: run `record` once with the last cut's date
and the cadence picks up from there.

## Install

```bash
cp com.exobrain.haircut-check.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.exobrain.haircut-check.plist
```

The plist is copied, not symlinked — launchd refuses symlinks into
`~/Documents/`. Logs land in `~/Library/Logs/exobrain/haircut-check.log`.

## Tests

`tests/test_barber_schedule.py` covers the cadence gate: the lead window,
once-per-cycle nudging, that an ignored nudge doesn't slide the schedule, and
that an overdue cut still produces a forward-facing search window.
