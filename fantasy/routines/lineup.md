# Lineup routine (daily 5:30 PM CT and Sunday 10:15 AM CT)

Follow `fantasy/routines/COMMON.md` first. (The Sunday 10:15 AM copy of this
routine runs only on Sundays; on any other day it stops here.)

1. `fantasy/bin/espn check --json` and `fantasy/bin/espn team --json`. If no
   starter locks within the next 27 hours, print "nothing locks before <time>"
   and stop. On Wednesdays, before anything else, log what the waiver claims
   did: `fantasy/bin/espn-tx pending`, `fantasy/bin/ff roster`, and
   `fantasy/bin/espn activity --json`; write the outcome to the Season log.
2. Definite problems (OUT, IR, bye, suspension, empty slot) are normally fixed
   by the `lineup-watch` job. If any remain, fix them now:
   `fantasy/bin/espn-tx swap "<bench player>" --for "<starter>"` (or
   `espn-tx move` into an empty slot) and confirm `"verified": true`.
3. QUESTIONABLE starters: `fantasy/bin/espn news "<name>"`. Swap in the best
   bench option only if the latest item says he is not expected to play, or he
   is a true game-time decision whose bench alternative projects within ~3
   points and kicks off earlier or at the same time. Otherwise keep him and
   let `lineup-watch` handle a late zeroed projection. One line of reasoning.
4. The variance rule, from `fantasy/bin/espn matchup --json` (projected
   margin). Favorite by more than 3: prefer floor in FLEX and WR2 (high target
   share, steady weekly scores). Underdog by more than 3: prefer ceiling
   (deep-threat receivers, big-play backs). Within 3 points either way, the
   higher projection starts. Swap only when the projection gap is under 3 and
   the variance profiles clearly differ; do not churn.
   **Idle week (week 8), or any week ESPN shows no opponent:** there is no
   game to win, only Points For (the seeding tiebreak) to bank. Start the
   highest-projection lineup with no variance adjustment.
   **The bye race, from week 9:** `fantasy/bin/ff standings` marks the top-2
   cutline. If we are tied in record with the #2 seed, or within one game of
   it, Points For is the likely decider, so weight expected points over the
   variance rule: take the variance trade only when the win-probability gain
   is clearly larger than the projected points it costs. If we hold a top-2
   seed by more than a game with two weeks left, floor everywhere.
5. Write one Season log line: date, opponent, projected margin, what changed
   and why ("no changes" is a valid entry), and from week 9 the bye-race
   position (games and points ahead of or behind the #2 line).
6. Notify Alex only if something changed.
