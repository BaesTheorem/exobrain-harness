# draftbot

Drafts a fantasy football team in the ESPN draft room, autonomously, against a
ranked board. Built for Alex's 13-team full-PPR league; the strategy behind the
rankings lives in the `/fantasy-football` skill and the vault playbook.

Unlike `../bin/ff`, which is read-only by invariant, this **writes**: it clicks
the draft button. Keep the two separate.

## Why an in-page agent

The pick clock is 30 seconds in mocks and 90 live, and bot teams pick in about a
second. A round trip out to an assistant costs 20-60 seconds, so anything that
waits on one is structurally too slow. The agent runs inside the ESPN page on a
250ms timer and picks in milliseconds; supervision happens between picks.

## Parts

| File | Role |
|---|---|
| `driver.py` | Holds one Playwright browser in a persistent profile. Talks over `cmd.json` / `result.json`, publishes `state.json` + `shot.png` |
| `autopilot.js` | Runs in the page. Reads the board, scores candidates, clicks, verifies |
| `arm.py` | Deploys the autopilot, fills the queue, reports status |
| `watch.py` | Streams new pick events, one per stdout line |

## Use

```sh
python3 driver.py &                 # reads url.txt; log in by hand once
python3 arm.py board                # rebuild ranks from ../ringer_board.json
python3 arm.py arm                  # inject and start
python3 arm.py status               # roster counts, picks, recent log
python3 arm.py off                  # stop picking, leave the queue in place
python3 watch.py                    # stream picks
```

`arm.py` and `watch.py` share one command channel. **Do not run them at the same
time** or they will race on `result.json`.

## Draft-day rules, learned the hard way

- **Be in the room before it opens.** ESPN drafted 73 picks in ~90 seconds on
  2026-08-24 because every team was flagged AUTO. Entering clears the flag on
  upcoming picks; picks already made are gone.
- **One connection per team.** If the bot is driving, nobody opens the draft room
  in another browser, or ESPN bumps one session with "Duplicate Connection" and
  the bot goes blind against a frozen board.
- **The queue cannot be preloaded.** ESPN silently ignores queue clicks before the
  draft starts. The autopilot fills it in the first seconds after the clock
  starts, and only while not on the clock.

## Verifying, not assuming

Two bugs shipped because success was measured at the wrong layer: a pick logged
"Mike Evans" while drafting Jaylen Warren, and a queue filler reported 21 adds
when ESPN had accepted zero. Both reported *intent*.

So every pick now checks that the roster count actually grew, and the queue
filler reports what landed. Rows are identified as the largest ancestor of an
action button that still contains exactly one action button, which does not care
how many wrapper divs ESPN adds. Earlier code walked a fixed number of parents
and parsed by field position; both broke.

When a check's failure mode is a quiet zero, run a known-good fixture through it.
That is how the `K1/3` parse bug surfaced: there is no word boundary between the
`3` of `TE2/3` and the `K`, so the kicker count silently read 0 forever.

## Known flaws

Scoring uses **raw overall board rank**, which is wrong in three ways: it takes a
QB too early for a one-QB league, never selects a tight end until a reservation
rule forces one in the last rounds, and ignores bye weeks entirely (the
2026-08-24 roster had three starters on the Week 10 bye).

All three want the same fix: **value over replacement** at each position instead
of overall rank, plus bye spreading as a tiebreak.

## Not committed

`profile/` (a logged-in Chrome profile with live ESPN session cookies),
`url.txt` (carries a memberId GUID), `board_ranks.json` (derived from The
Ringer's rankings), and the runtime scratch files. See the repo `.gitignore`.
Rebuild ranks with `arm.py board`, and log in by hand once to recreate `profile/`.
