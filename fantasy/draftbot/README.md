# draftbot

Drafts a fantasy football team in the ESPN draft room, autonomously, against a
value-over-replacement board. Built for Alex's 13-team full-PPR league; the
strategy behind the rankings lives in the `/fantasy-football` skill and the vault
playbook.

Unlike `../bin/ff`, which is read-only by invariant, this **writes**: it clicks
the draft button. Keep the two separate.

## Why an in-page agent

The pick clock is 30 seconds in mocks and 90 live, and bot teams pick in about a
second. A round trip out to an assistant costs 20-60 seconds, so anything that
waits on one is structurally too slow. The agent runs inside the ESPN page on a
250ms timer and picks in a few seconds; supervision happens between picks.

## Parts

| File | Role |
|---|---|
| `../vor.py` | Builds `vor.json`: ESPN 2026 projections + The Ringer's positional ranks -> value over replacement |
| `driver.py` | Holds one Playwright browser in a persistent profile. Talks over `cmd.json` / `result.json`, publishes `state.json` every 1.5s; `shot.png` only on the `shot` op (capturing a headful window makes it flash) |
| `autopilot.js` | Runs in the page. Scans the board, scores, clicks, verifies |
| `arm.py` | Deploys the autopilot, fills the queue, reports status |
| `watch.py` | Streams new pick events, one per stdout line |
| `peek.py` | Reads the roster panel. Safe to run while a pick is in flight |

## Use

```sh
python3 driver.py &                 # reads url.txt; log in by hand once
python3 arm.py board                # rebuild vor.json (do this on draft morning)
python3 arm.py arm                  # inject and start
python3 arm.py status               # roster counts, picks, recent log
python3 peek.py                     # the actual roster, with byes
python3 arm.py off                  # stop picking, leave the queue in place
```

`arm.py` and `watch.py` share one command channel. **Do not run them at the same
time** or they will race on `result.json`.

## Scoring: value over replacement

Overall board rank is the wrong yardstick. Rank compares a player to the whole
field, but a pick is decided by how much better he is than the man you could have
at that position anyway. Ranking on the field is why the first two mocks took a
QB in round 4 and never took a tight end at all.

`vor.py` splits the job between the two sources by what each is good at:

- **The Ringer** decides *who* is the best player at a position. It is the board
  Alex chose and a projection cannot replace editorial judgment.
- **ESPN's own 2026 projections** decide *how much* a WR3 is worth against an
  RB5. They come back already scored in this league's full-PPR settings, which
  makes them the only cross-positional common scale available.

Value is `curve[pos][his positional rank] - curve[pos][replacement]`. Replacement
is the 13th QB, 30th RB, 34th WR, 14th TE (starters, with the flex weighted
toward WR because full PPR is the receiver-friendly extreme).

This reproduces the playbook's positional rules without hand-tuned constants.
The QB curve is a cliff at Josh Allen and then nearly flat -- QB2 to QB10 spans
only 30 points across a season -- so VOR waits on QB by itself. Elite TEs price
at 83 VOR against a 14th TE who is dreadful, so a tight end finally competes for
a real pick instead of being an afterthought in round 14.

Byes are a tiebreak only, never a reason to reach: a small penalty for stacking a
week already on the roster, and a small bonus for Week 8, which is free because
the league has 13 teams and Alex's idle week is 8.

## The list is windowed, and that was the whole bug

ESPN's player table keeps roughly 32 rows in the DOM at a time out of ~190
available, and the window follows the scroll position. Two consequences that cost
most of a mock each:

- **`innerText` returns '' for any element without a layout box.** Reading it
  made the bot score a pool of 1 to 19 players and treat that as the board. It
  took the only candidate it could see at 1.01 and spent round 6 on a 19-VOR
  receiver. Use `textContent`, which does not care about layout.
- **Scoring the window can never see a kicker.** Kickers rank past 200, so they
  are never in a window anchored anywhere near the top, and the last round finds
  no candidate.

The fix for both is ESPN's own position filter. Each pick sweeps the positions
still legal to draft, filtering to one at a time and scrolling to the top, which
puts that position's best available players inside the window by construction. A
full sweep costs about 1.8 seconds against a 30-second clock.

Buttons go stale when the window recycles rows, so the winner chosen during a
sweep is re-found by name before being clicked.

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
- **A practice draft has a RESUME button** on the League Manager tab, so a mock
  can be paused to fix something and picked back up. The live draft will not wait.
- **Re-arming mid-draft wipes the in-page log and pick list.** The roster is read
  from the page so nothing is lost, but the diagnostic history is. Prefer arming
  once, before the room opens.

## Verifying, not assuming

Two bugs shipped because success was measured at the wrong layer: a pick logged
"Mike Evans" while drafting Jaylen Warren, and a queue filler reported 21 adds
when ESPN had accepted zero. Both reported *intent*.

So every pick checks that the roster count actually grew, and the queue filler
reports what landed. Names now come straight off each row's own player anchor
rather than by scanning a blob of page text, which removes the class of bug where
a row resolves to a player standing next to it.

Every pick also logs `board=N`, the number of players actually scored. That one
number would have exposed the windowing bug on the first pick instead of the
third mock.

When a check's failure mode is a quiet zero, run a known-good fixture through it.
That is how the `K1/3` parse bug surfaced -- there is no word boundary between
the `3` of `TE2/3` and the `K`, so the kicker count silently read 0 forever --
and it is why the bye parser is tested against a fixture with known byes.

## Still open

- **Tier awareness.** VOR ranks players; it does not notice when the last member
  of a tier is about to leave the board before the next turn. (The former
  "dynamic VOR" item is closed: the VONA floor now follows the board below
  replacement instead of clamping at zero, swept 2026-08-24, worst seat 6 -> 4.)
- **The opponent model is ADP, nothing richer.** VONA asks whether a player
  survives to the next turn using ESPN's crowd ADP as the survival estimate.
  That models a room of average drafters; it does not model *this* room's
  tendencies (a leaguemate who reaches for QBs, a run that starts early). A
  richer version would learn from the live pick log. It does not reason about what will still be there at the
  next pick, which is the other half of a snake draft.

## Not committed

`profile/` (a logged-in Chrome profile with live ESPN session cookies),
`url.txt` (carries a memberId GUID), `vor.json` and `board_ranks.json` (derived
from The Ringer's rankings and ESPN projections), and the runtime scratch files.
See the repo `.gitignore`. Rebuild the board with `arm.py board`, and log in by
hand once to recreate `profile/`.
