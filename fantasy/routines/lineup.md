# Lineup routine (daily 5:30 PM CT, Sunday 10:40 AM and 2:35 PM CT)

Follow `fantasy/routines/COMMON.md` first. (The two Sunday copies of this
routine run only on Sundays; on any other day they stop here. They are timed
after the inactives post: 10:30 for the noon window, about 1:35 and 1:55 for
the 3:05 and 3:25 windows. Before 2026-09-20 the Sunday run fired at 10:15,
fifteen minutes before the reports it existed to read.)

1. `fantasy/bin/espn check --json` and `fantasy/bin/espn team --json`. If no
   starter locks within the next 27 hours, print "nothing locks before <time>"
   and stop. On Wednesdays, before anything else, log what the waiver claims
   did: `fantasy/bin/espn-tx pending`, `fantasy/bin/ff roster`, and
   `fantasy/bin/espn activity --json`; write the outcome to the Season log.
   **Every run, also check `fantasy/bin/espn-tx pending` for a trade of ours
   in review**, and note which of our starters it would send away and when
   that starter locks. `espn check` cannot see this: a trade in review is not
   a lineup problem until the roster moves, so the checklist reads clean right
   up until a starting slot is empty. If one is in review and the starter it
   sends away locks before the next scheduled run, say so in the log and plan
   the replacement now rather than discovering it later.
2. Definite problems (OUT, IR, bye, suspension, empty slot) are normally fixed
   by the `lineup-watch` job. If any remain, fix them now:
   `fantasy/bin/espn-tx swap "<bench player>" --for "<starter>"` (or
   `espn-tx move` into an empty slot) and confirm `"verified": true`.
3. QUESTIONABLE starters: `fantasy/bin/espn news "<name>"`. Swap in the best
   bench option only if the latest item says he is not expected to play, or he
   is a true game-time decision whose bench alternative projects within ~3
   points and kicks off earlier or at the same time. Otherwise keep him and
   let `lineup-watch` handle a late zeroed projection. One line of reasoning.
4. The variance rule, as a number (from 2026-09-20). `fantasy/bin/espn
   check --json` (and `matchup`) reports `win` (P(win) with both sides' means
   and spreads: every unlocked starter is a normal around his projection
   with a measured, tiered, per-player spread; a locked one is his banked
   actual) and `swaps`, every single bench-for-starter swap that raises P(win),
   best first, each with `d_p` and the projection-only `d_proj` so you can
   see whether variance or the mean made the call. **Apply a swap when
   `d_p` is at least +1 point of win probability**; below that it is churn.
   The old reading (favorite by 3 = floor, underdog by 3 = ceiling, within 3
   = projection) is what the number encodes, so state which side we are on
   in the log line and cite `win.p` before and after. `margin_source` still
   says whether the margin is pre-game or live; a banked Thursday score can
   flip the side, as 2026-09-19 showed. Also read `opp_problems` and
   `win_if_opp_unfixed`: an OUT or bye starter on their side is a hole, and
   `fantasy/bin/league-scan` says whether that manager historically fixes
   holes (zeros started, bench points left). Count on the hole only for a
   manager with a record of leaving them.
   **Idle week (week 8), or any week ESPN shows no opponent:** there is no
   game to win, only Points For (the seeding tiebreak) to bank. Start the
   highest-projection lineup with no variance adjustment.
   **The bye race, from week 9:** `fantasy/bin/ff standings` marks the top-2
   cutline. If we are tied in record with the #2 seed, or within one game of
   it, Points For is the likely decider, so weight expected points over the
   variance rule: take the variance trade only when the win-probability gain
   is clearly larger than the projected points it costs. If we hold a top-2
   seed by more than a game with two weeks left, floor everywhere.
5. Write one Season log line: date, opponent, projected margin and `win.p`,
   what changed and why ("no changes" is a valid entry), and from week 9 the
   bye-race position (games and points ahead of or behind the #2 line).
6. Notify Alex only if something changed.
