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

## The one thing that is not automated, and why

**MIST cannot complete the booking.** Booksy requires a customer account with a
verified phone number to confirm an appointment, and there isn't one. Some
barbers also have prepayment enabled. So the automation runs right up to the
confirmation screen and hands over a one-tap link. The last tap is Alex's.

This is a smaller loss than it sounds: availability here is not scarce. A
sample of the Aug 28–Sep 2 window returned **642 open slots** across five
barbers, most days open 9:00–18:30. There is no race to win, so nothing is lost
by a human confirming.

If Alex creates a Booksy account and wants full unattended booking, the flow to
extend is `POST /drafts/create` → `POST /drafts/{uuid}/timeslots` → confirm,
with an authenticated session. `booksy.py` deliberately stops before that step.

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
python3 schedule.py record --date 2026-08-29 --barber "Razor Nick"
```

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
