# salon-ramon

Book a haircut at Salon Ramón (Brookside, Kansas City) from the terminal.

The salon runs on **Rosy Salon Software** (`online.rosysalonsoftware.com`,
salon id 41947). Rosy's booking widget is a Backbone app that computes
availability in the browser; this is the same job done from the command line,
against the same API the widget uses.

```
bin/ramon login                      # lift the signed-in session out of Chrome
bin/ramon whoami                     # salon rules: lead time, horizon, cancel window
bin/ramon providers                  # who takes online bookings, and which days
bin/ramon services --provider Ramon  # his menu, with his duration and price
bin/ramon slots --days 45            # open Men's Haircut times with Ramon
bin/ramon book --at "2026-09-30 15:30" --confirm
bin/ramon appointments               # what the server says I have booked
bin/ramon cancel --confirm           # the next one, unless --force is needed
```

`book` and `cancel` are dry runs unless you pass `--confirm`. Defaults
(provider, service, how far to search, preferred hours) live in `config.json`.

## The 6-week cadence

`schedule.py` owns the clock and `state.json` is the record. launchd
(`com.exobrain.haircut-check`, daily at 10:00) runs `run-haircut-check.sh`,
which almost always exits in a second: it only acts when a cut is due and no
appointment is already lined up. When it does act it hands off to a headless
MIST run, because that is the only piece that can read Google Calendar and so
the only piece that can honour "fit it wherever I am open".

```
python3 schedule.py status                                    # where the cycle stands
python3 schedule.py pending --date 2026-10-13 --provider "Ramon Walker"
python3 schedule.py record  --date 2026-10-13 --provider "Ramon Walker"
```

Two rules worth keeping straight: the clock runs from the last **completed**
cut, never the last nudge, and **no booking system can tell you a haircut
happened**. Booksy filed a sat-through appointment under the same status letter
as a cancellation and Rosy has no such flag either, so `state.json` is the only
evidence. A `pending` appointment whose date has passed is recorded as
completed (flagged `assumed`) and Alex is asked to confirm: a late nudge costs
one sentence, a wrong "he did not go" books a second appointment.

This replaced the Booksy/Rich Forever tool (`barber/`) on 2026-09-10; the
cadence tracker and its history moved across unchanged, since none of it
depended on the venue. One venue and one stylist means the deposit-ranking
logic that job carried is simply gone.

## Auth

Rosy is a Spring app behind a `JSESSIONID`, and Alex signs in with Google. The
login page is guarded by reCAPTCHA, so nothing here attempts to log in: `ramon
login` lifts the session he already has out of Chrome's cookie store, the same
approach the Booksy tool uses for the barber.

The cookie is not the API credential. Every signed-in page embeds a
**30-minute JWT** plus the `customerId`, and `/api/v2` authenticates on
`Authorization: Bearer <that JWT>`. So each run re-scrapes `/appointments` for
a fresh token rather than caching one. `.rosy-session.json` (gitignored, 0600)
holds only the cookies.

Three response codes worth knowing, because they distinguish the failure modes:
a customer token reaches the controller (`400` on a bad body), the page's
**anonymous** token gets `403` on any write, and no token at all gets `401`.
The anonymous token can read the whole catalogue, which is why `context()`
refuses to hand one back: a silent downgrade to anon looks perfectly healthy
until a booking POST returns 403.

Needs `cryptography` (Chrome's cookie store) on the interpreter that runs
`ramon login`. Everything else is stdlib.

## Salon rules the code enforces

Read from the salon record at runtime, not hardcoded:

| Rule | Value here |
| --- | --- |
| Lead time (`onlineHoursInAdvanceToSchedule`) | 2 hours |
| Booking horizon (`scheduleDaysOut`) | 180 days |
| Online cancel window (`onlnCancelTimeframe`) | 1 day |
| Late-cancel charge (`cancelChargePercent`) | 50% |
| Deposit (`deposit-salon-settings`) | 50%, **new customers only** |
| Grid | 15 minutes |

Alex is an existing customer with a card on file, so the deposit branch does
not apply; `book` never touches the payment path. `cancel` refuses to act
inside the 1-day window unless you pass `--force`, because that is where the
50% charge lives.

## Gotchas that cost real time

- **Schedules are indexed Sunday=0** (JavaScript `getDay()`), while Python's
  `weekday()` is Monday=0. Off by one shifts every provider's week by a day and
  the output still looks entirely plausible.
- **"Cancelled" is `cancellationId > 0`**, not the `status` string. Live data
  carries `status: "CANCELED"` rows; filtering on status leaves cancelled
  appointments blocking open chairs forever.
- **Time-on timesheets belong to their own date.** Passing a multi-day fetch
  into one day's search let a single `06:15-20:00` row three weeks out stretch
  every day's window across the whole range: 18 real slots reported as 53,800.
  The date filter now lives inside `slots.py`, not in the caller.
- **Some timesheet rows end before they start** (`18:00 -> 11:30`). The site's
  overlap test never matches them, so neither does ours. Swapping the ends to
  "fix" the row would invent seven hours of unavailability.
- **Process time holds the chair** past the end of the service, so a slot needs
  `duration + processTime` to fit.
- **A customer cannot be double-booked with themselves** anywhere in the salon,
  not just with the provider being searched.
- **Prices on a provider's menu can be `0.00`**, meaning unset; the salon's
  default price applies (Men's Haircut with Ramon reads `0.00` and falls back
  to $40).

## Not modelled

Resource-bound services (rooms, equipment) and chained primary/secondary
service pairs. This salon's menu has neither, and `ramon` refuses the service
rather than guessing if that ever changes.

## Verification

Availability is arithmetic over other people's calendars, so it is checked two
ways. `tests/test_rosy_slots.py` covers the rules above, including the
53,800-slot regression. Against live data, the engine was hand-checked on two
days: Sep 30 has exactly one 60-minute gap (15:30-16:30) and the tool offers
15:30 and 15:45; Oct 13's 13:00-14:00 gap yields 13:00 and 13:15.

Writes are never trusted on their own response. `book` re-reads the customer's
appointments and reports the server's answer; `cancel` confirms the
appointment is no longer active. A POST that returns 200 is a claim, not a
booking.
