# Lineup routine (daily 5:30 PM CT, Sunday 10:40 AM and 2:35 PM CT)

Follow `fantasy/routines/COMMON.md` first. (The two Sunday copies of this
routine run only on Sundays; on any other day they stop here. They are timed
after the inactives post: 10:30 for the noon window, about 1:35 and 1:55 for
the 3:05 and 3:25 windows. Before 2026-09-20 the Sunday run fired at 10:15,
fifteen minutes before the reports it existed to read.)

1. `fantasy/bin/espn check --json` and `fantasy/bin/espn team --json`. (A run
   with no starter locking in the next 27 hours never reaches you:
   `bin/routine-guard` runs `bin/lineup-precheck` first. The Wednesday waiver
   result is the incident routine's to log, from roster-watch's
   `waiver_result`.) **Every run, also check `fantasy/bin/espn-tx pending` for a trade of ours
   in review**, and note which of our starters it would send away and when
   that starter locks. `espn check` cannot see this: a trade in review is not
   a lineup problem until the roster moves, so the checklist reads clean right
   up until a starting slot is empty. If one is in review and the starter it
   sends away locks before the next scheduled run, say so in the log and plan
   the replacement now rather than discovering it later.
   **Sunday morning run only:** `python3 -m ffmodel.fpranks snapshot <week>`
   (run from `fantasy/`; it saves MIST's ranks and FantasyPros' consensus
   side by side before the 1 p.m. ET games for the outside accuracy test).
2. Definite problems (OUT, IR, bye, suspension, empty slot) are normally fixed
   by the `lineup-watch` job. If any remain, fix them now:
   `fantasy/bin/espn-tx swap "<bench player>" --for "<starter>"` (or
   `espn-tx move` into an empty slot) and confirm `"verified": true`.
3. QUESTIONABLE starters are priced in `espn check` now (2026-10-15): each
   row carries `practice` (the latest practice line), `p_play` (the share of
   regular contributors with that status and practice who played,
   2016-2025) and `injury_ratio` (what they scored against projection when
   they did), and our starter counts as a mixture with the bench cover that
   kicks off no earlier than he does. The `swaps` list already includes it.
   Read `fantasy/bin/espn news "<name>"` only for what a report cannot hold
   (a ruling, a confirmed role), and quote `p_play` in the log line.
4. The variance rule, as a number (from 2026-09-20). `fantasy/bin/espn
   check --json` (and `matchup`) reports `win` (P(win) with both sides' means
   and spreads: every unlocked starter is a normal around `mean`, 0.75 of
   the betting market's `market` and 0.25 of ESPN's projection when the
   books post a line (ESPN alone otherwise), with a measured spread by
   position and tier, and starters in the same NFL game correlated as
   measured; a locked one is his banked actual) and `swaps`, every legal
   bench-for-starter swap with a positive `d_net`, best first, each with
   `d_p` and `d_proj` (the lineup's expected-points change) so you can see
   whether variance or the mean made the call. **Apply a swap when `d_net`
   is at least +1**: `d_net` is the win probability gained in points plus
   `d_proj` over `points_per_win_pct`, this week's exchange rate from
   `season_sim.py --leverage` (3.6 to 4.2 on 2026-10-15, after the drift).
   Below +1 it is churn.
   The old reading (favorite by 3 = floor, underdog by 3 = ceiling, within 3
   = projection) is what the number encodes, so state which side we are on
   in the log line and cite `win.p` before and after. `margin_source` still
   says whether the margin is pre-game or live; a banked Thursday score can
   flip the side, as 2026-09-19 showed. `win.p` already prices the
   opponent's holes (bye, OUT) and questionable starters at that manager's
   measured fix rate (`opp_fix`: bye holes fixed over faced, shrunk as
   (fixed + 1) / (faced + 2), in code since 2026-10-15). Do not apply the
   rate again. Quote `win.p` and its two ends, `win_if_opp_fixed` and
   `win_if_opp_unfixed`, in the log line; `opp_problems` names the holes.
   **Idle week (week 8), or any week ESPN shows no opponent:** the week is
   worth nothing (idle-week points do not count toward Points For). Fill the
   nine slots by projection, with no variance adjustment, escalation or ping.
   `d_net` applies in every other week, the bye race included (playbook
   *Corrections ledger*, 2026-10-14 (3)).
5. If you changed the lineup or decided anything, write one Season log line:
   date, opponent, `win.p` before and after, what changed and why, and from
   week 9 the bye-race position (games and points ahead of or behind the #2
   line). If nothing changed, write only `fantasy/bin/routine-log lineup
   "<date>: win.p <x>, no change"` and leave the playbook alone (rule
   inventory R158: the Season log is for decisions).
6. Notify Alex only if something changed.
