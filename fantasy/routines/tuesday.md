# Tuesday routine (6:00 PM CT): review, recap, ledger, waivers, trades, tendencies, forecast

Follow `fantasy/routines/COMMON.md` first. If today is not Tuesday, stop.

0. **Settle last week's forecast and write the review** (Alex's standing
   instruction, 2026-09-17; the playbook's *Weekly forecast and review*
   section is the rule). `fantasy/bin/forecast settle` scores MIST's 50% and
   90% intervals and the mechanical baseline against the week's actuals;
   `fantasy/bin/forecast history` gives the season coverage and, from week 3,
   the per-source error ranking (which of ESPN, Sleeper, CBS, FantasyPros,
   FFToday and the consensus ran hot, by MAE); note it, and weight a source
   down in your own judgment only after three weeks of it losing. Then judge each
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
   skips a single-week round and is worth about 1.9x the title odds of a
   3-6 seed): `fantasy/bin/ff standings` shows the cutline; log games and
   points ahead of or behind the #2 seed, and name the teams we are racing.
   **Then the bye odds themselves**: `python3 fantasy/season_sim.py --sims
   20000 --json` folds the results so far into the simulation and prints
   our `bye`, `playoffs`, `champ` and `seed1` probabilities; log them every
   week beside last week's, so the objective has a number and a trend.
   **Run `fantasy/bin/volume build --fresh` here** (nflverse posts the
   week's stats by Tuesday) so every scan below reads this week's volume.
2. **Ledger.** `python3 fantasy/ledger.py settle`; note the running score in
   the Season log. Only settled ledger results may change how the board is
   built next year.
3. **Waivers.** Claiming costs nothing here (priority resets weekly), so claim
   whenever the wire beats the bench. **Start with `fantasy/bin/swap-scan`**
   (Alex, 2026-09-20: actively monitor for these): it prices every
   bench-for-wire swap as `(add - drop) x weeks left` against the playbook's
   20-point gate and marks the ones that clear it, with position maximums
   applied (WR sits at 8/8 since the Bateman add, so a WR add needs a WR
   drop), never a second QB or TE, with Sleeper's 24-hour adds (`heat`, the
   national wire) and the volume flags beside each candidate, and the bye
   holes two weeks out with the bench cover for each. A PASS is a candidate,
   not a verdict: check the role evidence before filing, and a swap that
   fails the gate on points can still clear it on the role condition (a
   `ROLE` mark: BUY or ROLE-UP from the volume feed). **Then
   `fantasy/bin/stream-scan`**: the D/ST and K thresholds; a STREAM there is
   a candidate under the same drop rules. Then `fantasy/bin/volume fa --pos
   RB` (the same for WR and TE; `--sort trend` for risers): targets, target
   share, WOPR, snap share, last week's role move, and the BUY/SELL/ROLE-UP
   flags, which is what "rank by opportunity" means from now on; `espn fa
   --sort proj` for the projections, `fantasy/bin/espn injuries`, and the
   bench in `espn team --json`. Rank by opportunity (targets, touches, snap
   share; `volume player <name>` shows the weekly log), never by last week's points; committee backs who already
   have touches beat clean handcuffs; touchdowns on thin volume are a sell,
   heavy volume with bad touchdown luck is a buy. No second QB or TE. Drop the
   lowest-value bench player (role first, then season projection) to make
   room; never drop a starter. From week 5 on, value every player by a 50/50
   blend of his preseason projection and his season-to-date points per game,
   weighting weeks 1-14 fully and weeks 15-17 at half (the bye is earned in
   the regular season, so a player who only returns for the playoffs is a
   half-value asset)
   (Harstad: that naive blend beat either input alone in 4 of 5 position
   buckets), not by either one by itself. File up to two claims, best first:
   `fantasy/bin/espn-tx claim "<name>" --drop "<bench player>"` (no `--drop`
   when a slot is open), confirming `"verified": true`. If nothing beats the
   bench, say so and file nothing. Week 7 is Daniels' bye: that week, claim a
   streaming QB instead (the IR slot and a drop make room).

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
4. **Trades, from week 3 on.** The edge is a leaguemate's recency and
   endowment bias, so timing is the input: buy a volume player after a bad
   week or two, sell a thin-volume touchdown scorer after a big one. Start
   with `fantasy/bin/volume league --flag BUY` (rival players whose volume
   rank beats their points rank: the buy-low list) and `--flag SELL` (ours
   riding touchdowns on thin usage: the sell-high list), then `python3
   fantasy/trade_scan.py --json --min-gain 10` for every 1-for-1 and 2-for-1
   the other side does not lose on its own screen, priced in title and bye
   odds through the season simulation, and `fantasy/bin/league-scan` for
   who answers offers (a manager whose received offers all expired is not a
   negotiation, he is a two-day wait). Write up to
   two concrete proposals to the Season log with the volume evidence, then put
   them to Alex as a `mist-notify` banner with Send / Skip buttons, built the
   way COMMON.md rule 3 describes. **Not `mist-ask`**: it needs a Console
   session the routine runner does not provide, so it exits nonzero here
   (found 2026-09-16). Never send an offer yourself. Incoming offers are the incident routine's.
   **Standing offer (from 2026-09-07):** Watson + Nailor for George Pickens
   to Ayahuasca Rodgers. ESPN offers expire after two days. If it is no longer
   pending (`fantasy/bin/espn-tx pending` shows no TRADE_PROPOSAL from us) and
   both Watson and Nailor are still ours and Pickens is still theirs, re-send
   it: `fantasy/bin/espn-tx trade "Christian Watson" "Jalen Nailor" --for
   "George Pickens" --with "Ayahuasca Rodgers"`. This one re-send is the only
   offer you send without asking; Alex approved it on 2026-09-07. Stop if the
   playbook's Season log says he withdrew it.
   **Watch list.** `fantasy/watchlist.json` is the set of players and teams
   roster-watch tracks between runs, each with a `why` and a `trigger`.
   Review it: act on any trigger that has fired (the incidents file shows
   watch events), remove entries that no longer matter, add the week's new
   buy-low and sell-high candidates with their triggers, and bump `updated`.
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
   projection sources unit-normalized per position, consensus and spread,
   season logs, injuries, Vegas totals, the historical error distribution by
   position and projection tier, and a mechanical baseline for comparison).
   Read it, then write a JSON forecast with, for every rostered player, a
   median, `p50`, `p90` and a one-sentence `why`; a `team_total` and
   `opp_total` with the same shape; `win_prob`; and a `standing` block
   (`median`, `p50`, `p90` on our rank after the week, `p_first`, `p_top2`,
   `why`). ESPN is one vote; move off the consensus whenever you have a
   reason the sources do not (a role change, weather, a questionable tag,
   week-1 touchdowns on thin volume) and say the reason. Anchor widths on
   the tier quantiles in the pack (starter-tier q25-q75 is roughly 0.6x to
   1.25x the projection) and remember the median actual runs about 0.85x
   projection. File it with `fantasy/bin/forecast record /tmp/fc-mist.json
   --dossier /tmp/fc-dossier.json`; it refuses a 50 outside its 90, a missing
   player, or a probability of 0 or 1, and it regenerates the playbook's
   Season log so the new week's Forecast table sits at the top of its
   section. Pending claims are not on the roster yet, so they are not in the
   forecast; say so with `fantasy/bin/forecast note --week <week> --forecast
   "<text>"`, which renders under the table.
