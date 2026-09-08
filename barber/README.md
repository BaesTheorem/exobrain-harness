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

Two rules, in order.

**1. Never a barber who takes a deposit.** A deposit means Booksy shows
"Add card" where "Confirm & Book" belongs, and this package stores no card, so
booking one is not a worse booking, it is no booking at all. Deposits are set
per *service variant*, not per business (Dmilly charges $20 on a haircut and
$85 on a colour, and every barber carries the same boilerplate cancellation
policy at the business level), so the only thing that answers the question is
the variant in `config.json`.

```
python3 booksy.py deposits            # who is eligible, from cached config
python3 booksy.py deposits --update   # re-read from Booksy and save
```

As of 2026-09-08 only **Troy Richforever** qualifies: Dmilly $20, Razor Nick
$15, Fully Blendz $12, and Xay's business now 404s so his deposit is unknown.
**Unknown counts as requiring one.** Guessing wrong in the other direction
costs a run.

**2. Among those, the highest rated in the window,** not the earliest opening.
Everyone sits at a flat 5.0, so review count is what actually decides, and
ranking on stars alone would fall back to config order while looking like it
ranked. `booksy.best_slot()` applies both rules, filter first.

Reviews: Dmilly (82), Troy (35), Fully Blendz (22), Razor Nick (14), Xay (1).
Refresh the counts in `config.json` when they drift.

This ordering was learned the hard way. Ranking on reviews alone put Dmilly
first every cycle, so every cycle the run walked the entire booking flow and
died at her card prompt, having reserved nothing. `book.py` now enforces the
rule itself via `refuse_if_deposit()`, reading the deposit live rather than
trusting config, because ranking only governs the barber the routine *picks*.
A hand-typed `--barber`, a stale config, or a barber who turns deposits on next
month all route around the ranking and land on the gate instead.

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

`--check` tests the token in `.booksy-session.json` first, because that is
what `book.py` and `cancel.py` actually authenticate with — the browser
profile is never logged in by design, and an earlier version that probed only
the profile reported "not logged in" while bookings worked fine. Only if the
session file is dead does it fall back to probing the profile.

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

## Cancelling

```bash
python3 cancel.py --barber 1335772 --at "2026-08-29 11:00"            # dry run
python3 cancel.py --barber 1335772 --at "2026-08-29 11:00" --confirm  # real
```

Same philosophy as booking: drive the real UI, verify against the server. The
appointment page (`/account/appointment/{uid}`) lives on the main frame — no
widget iframe — but the flow is three screens deep and only the last one acts:
CANCEL opens a reason survey, submitting that opens a "Prefer to reschedule?"
retention modal, and its "Cancel appointment" button is what actually cancels.
The first live run stopped at the retention modal and the server check
correctly reported nothing had been cancelled — page text is not evidence for
cancellation either. Success means the booking no longer shows an active
status in `/me/bookings`.

To reschedule: book the new slot first, then cancel the old one, so there is
never a moment with zero appointments. Then update the calendar event and
`schedule.py pending --date <new>`.

## Closing the loop: what counts as a completed haircut

`state.json` is the only record that a haircut *happened*. Booksy will not tell
you: the Sep 1 2026 cut Alex actually sat through reports `status: "C"`,
`active: false` in `/me/bookings`, the same shape as an appointment that was
cancelled, with no field that separates the two. So the server is authoritative
for "was this booking created" (that is what `book.py` verifies against) and
useless for "did he get his hair cut".

That gap bit once. The Sep 1 appointment lapsed without anyone running
`schedule.py record`, `pending` merely stopped suppressing the job, and the
next run read "no haircut on record yet" -- the one state that makes it act
immediately -- and went hunting three weeks early.

`schedule.py reconcile` now runs first in the daily job and closes out any
appointment whose date has passed, recording it as completed and flagged
`"assumed": true`, then notifying Alex to confirm. Assuming he went is
deliberately the cheaper error: guess wrong that way and the next nudge is
late, which one sentence fixes; guess the other way and the job books a second
appointment on top of one he already has.

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
python3 booksy.py deposits                       # who may be auto-booked
python3 booksy.py deposits --update              # re-read deposits from Booksy

python3 schedule.py status                        # where the cadence stands
python3 schedule.py reconcile                     # close out a passed appointment
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
