# Tuesday routine (6:00 PM CT): review, recap, ledger, waivers, trades, tendencies, forecast

Follow `fantasy/routines/COMMON.md` first. If today is not Tuesday, stop.

0. **Settle last week's forecast and write the review** (Alex's standing
   instruction, 2026-09-17; the playbook's *Weekly forecast and review*
   section is the rule). `fantasy/bin/forecast settle` scores MIST's 50% and
   90% intervals and the mechanical baseline against the week's actuals;
   `fantasy/bin/forecast history` gives the season coverage and, from week 3,
   the per-source error ranking (which of ESPN, Sleeper, CBS, FantasyPros,
   FFToday, the market and the consensus ran hot, by MAE); note it. Do not
   reweight sources by hand: the consensus is an equal-weight mean, and hand
   moves off it are on probation (playbook, 2026-10-15). It also prints the weighted interval score (MIST against the
   baseline on the same lines), where results landed in six slices of each
   forecast, and the closing line value of MIST's leans off the market;
   quote all three in the review. A landing row with more than 30% in one
   middle slice, or a lean that keeps pointing against the line's later
   move, is a reasoning signal even when coverage looks right (these alarm
   thresholds are being tested for false alarms, rule inventory R88). Then judge each
   miss: was it variance inside a well-shaped band (log it, change nothing)
   or a reasoning error (a role read that was wrong, a source weighted
   wrongly, a band too narrow for the position)? Write the coverage numbers,
   the reasoning misses, and any rule change as the week's judgment:
   `fantasy/bin/forecast note --week <last week> --review "<text>"` renders
   it into that week's Review block at the top of its Season log section
   (the scorecard table above it is generated; never edit inside the
   markers), and a dated Season log bullet under the current week's header
   carries the same conclusions. A strategy change needs a failed reason, not a
   number outside a band; three weeks of 50% coverage under 0.35 or over
   0.65 is the signal the band widths are wrong. If `settle` says the week is
   not over, stop this step and say so.
1. **Recap.** `fantasy/bin/espn matchup --week <last week> --json`,
   `fantasy/bin/espn scoreboard --json`, `fantasy/bin/espn teams --json`
   (record, points for, and WAIVER PRIORITY, which resets weekly by reverse
   standings). Season log line (dated bullets go under the current `###
   Week N` header, below the generated Forecast and Review blocks;
   `forecast playbook` regroups any that land elsewhere): score, opponent,
   record, points-for rank,
   waiver priority, and one sentence on what decided it, judged as process.
   Then the bye race, which is the season's actual objective (a top-2 seed
   skips a single-week round; for us it is worth about 13 points of title
   odds, measured by `season_sim.py --leverage`; quote it in points): `fantasy/bin/ff standings` shows the cutline; log games and
   points ahead of or behind the #2 seed, and name the teams we are racing.
   **Then the bye odds themselves**: `python3 fantasy/season_sim.py --sims
   20000 --json` folds the results so far into the simulation and prints
   our `bye`, `playoffs`, `champ` and `seed1` probabilities; log them every
   week beside last week's, so the objective has a number and a trend.
   **Then the levers**: `python3 fantasy/season_sim.py --leverage --sims
   40000` prints what a win is worth each remaining week, the projected
   points worth 1% of win probability, and the per-week weights (weeks
   16-17 against a regular-season week). Log the exchange rate and the
   week 16/17 weights; *The strategic thesis* rules 2 and 4 read them.
   **Run `fantasy/bin/volume build --fresh` here** (nflverse posts the
   week's stats by Tuesday) so every scan below reads this week's volume.
2. **Ledger.** `python3 fantasy/ledger.py settle`; note the running score in
   the Season log. Only settled ledger results may change how the board is
   built next year.
3. **Waivers.** Priority resets weekly, so never hoard it; but a claim still
   has to clear the gate. **Start with `fantasy/bin/swap-scan`**
   (Alex, 2026-09-20: actively monitor for these): it prices every
   bench-for-wire swap as `(add - drop) x horizon` (the regular-season weeks
   left plus weeks 15-17 at their `--leverage` weight, about 24 more) against
   a gate of 2.5 points a game, and marks the ones that clear it, with position maximums
   applied (WR sits at 8/8 since the Bateman add, so a WR add needs a WR
   drop), never a second QB or TE, with Sleeper's 24-hour adds (`heat`, the
   national wire) and the volume flags beside each candidate, and the bye
   holes two weeks out with the bench cover for each. A PASS is a candidate,
   not a verdict: check the role evidence before filing, and a swap that
   fails the gate on points can still clear it on the role condition (a
   `ROLE` mark: BUY or ROLE-UP from the volume feed). **Then
   `fantasy/bin/stream-scan`**: the D/ST and K thresholds; a STREAM there is
   a candidate under the same drop rules. **Then, from week 9 or whenever our
   IR slot is empty, `fantasy/bin/stash-scan --banner`** (Alex, 2026-10-14):
   injured free agents priced as playoff stashes, `0.53 x (rate x return
   factor - the starter he would replace) x the --leverage weights from his
   return week`, gate +20. It banners Alex once for a PASS that fits the open
   IR slot; a PASS that needs a bench spot is logged for his decision, never
   filed. Then `fantasy/bin/volume fa --pos
   RB` (the same for WR and TE; `--sort trend` for risers): targets, target
   share, WOPR, snap share, last week's role move, and the BUY/SELL/ROLE-UP
   flags, which is what "rank by opportunity" means from now on; `espn fa
   --sort proj` for the projections, `fantasy/bin/espn injuries`, and the
   bench in `espn team --json`. Rank by opportunity (targets, touches, snap
   share; `volume player <name>` shows the weekly log), never by last week's points; committee backs who already
   have touches beat clean handcuffs; touchdowns on thin volume are a sell,
   heavy volume with bad touchdown luck is a buy. No second QB or TE. Drop the
   bench player `swap-scan` names for the swap (the lowest `ros_rate` that
   fits the position limits); never drop a starter. From week 5 on, value every player on
   `ros_rate`: 0.45 weekly projection, 0.35 prior, 0.20 season points per
   game (backtest, 2026-10-15: better than the old 50/50 of prior and PPG in
   all 12 held-out season-weeks), weighting each week by its `--leverage`
   weight: weeks 16 and 17 about 11 regular-season weeks each, week 15 about
   2 (*The strategic thesis* rule 4, 2026-10-14; it was weeks 15-17 at half),
   never by one input alone. File up to two claims, best first:
   `fantasy/bin/espn-tx claim "<name>" --drop "<bench player>"` (no `--drop`
   when a slot is open), confirming `"verified": true`. If nothing beats the
   bench, say so and file nothing.

   **File in value order the first time. There is no undo.** ESPN's API does
   not expose claim order and has no working cancel route, so a mis-ordered
   list can only be repaired by Alex in the web UI. Two consequences, both
   learned the hard way on 2026-09-08:
   - **Never file a second claim for the same player as a hedge**, and never
     attach a drop to a claim as insurance against your own earlier one. It
     is dominated when the order is right and destructive when it is wrong.
     With one open bench spot, the hedge let a worse player land *and* cost
     the drop.
   - **Count open bench spots before deciding on `--drop`.** Only attach a
     drop when the roster is genuinely full after every earlier claim in the
     list has landed. If an earlier claim fills the last spot, the later one
     should have the drop; if it does not, the later claim just fails, which
     is the safe failure.
   If you find you have already filed in the wrong order, do not file another
   claim to compensate. Say so in the summary and hand Alex the exact cancel
   and reorder to make in the web UI.
4. **Trades: do not plan on them (Alex, 2026-10-11).** The league has made
   0 trades and accepted 0 of our 11 offers, so **write no new proposals and
   send no banner for one**. Plan every roster move on the roster we hold.
   An offer still pending stays up; incoming offers are the incident
   routine's. The BUY and SELL flags (`fantasy/bin/volume league --flag
   BUY|SELL`) still feed the watch list and the waiver and lineup calls. (The
   old proposal procedure and the *Standing offers* list are in the
   playbook's *Corrections ledger*, 2026-10-11, and its archive.)
   **Watch list.** `fantasy/watchlist.json` is the set of players
   roster-watch tracks between runs, each with a `why` and a `trigger`. Keep
   only entries whose trigger can change a decision of ours: our own players'
   roles and returns, a waiver target's role, a backup whose starter is
   hurt. Trade targets are retired with the trade lane (rule inventory R141,
   2026-10-15: none of the 9 watch-list incidents since 09-22 changed a
   roster decision). Act on fired triggers, prune the rest, bump `updated`.
5. **Tendencies.** `fantasy/bin/league-scan` (zeros started, bench points
   left per week, adds, offers sent and received and how they ended, per
   manager, from every closed week) and `fantasy/bin/espn activity --json`
   since last Tuesday: who is active, who leaves holes (the opponent model
   in the lineup routine counts on a hole only for a manager with a record
   of them), who answers offers. Update the playbook's league observations
   from the numbers, not just the log.
6. Notify Alex with a compact summary (result, record, claims filed, priority,
   last week's coverage, this week's win probability), linked to the league
   page.
7. **Forecast the new week, last, on the roster as it stands.** This is
   MIST's judgment call, not a script's number: `fantasy/bin/forecast
   dossier --save /tmp/fc-dossier.json` assembles the evidence (five
   projection sources unit-normalized per position plus the betting market's
   prop-implied points, consensus and spread,
   season logs, injuries, Vegas totals, the historical error distribution by
   position and projection tier, and a mechanical baseline for comparison).
   Read it, then write a JSON forecast with, for every rostered player, a
   median, `p50`, `p90` and a one-sentence `why`; a `team_total` and
   `opp_total` with the same shape; `win_prob`; and a `standing` block
   (`median`, `p50`, `p90` on our rank after the week, `p_first`, `p_top2`,
   `why`). ESPN is one vote; move off the consensus whenever you have a
   reason the lines could not price when they were set (news after the line
   moved, a role change confirmed by two weeks of volume) and say the reason
   (the playbook's probation rule, 2026-10-15: on weeks 2-5 hand moves lost
   to the consensus and the market). Anchor medians and widths on the tier
   quantiles in the pack (`settle` rebuilds them each week). File it with `fantasy/bin/forecast record /tmp/fc-mist.json
   --dossier /tmp/fc-dossier.json`; it refuses a 50 outside its 90, a missing
   player, or a probability of 0 or 1, and it regenerates the playbook's
   Season log so the new week's Forecast table sits at the top of its
   section. Pending claims are not on the roster yet, so they are not in the
   forecast; say so with `fantasy/bin/forecast note --week <week> --forecast
   "<text>"`, which renders under the table.
