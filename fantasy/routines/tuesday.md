# Tuesday routine (6:00 PM CT): recap, ledger, waivers, trades, tendencies

Follow `fantasy/routines/COMMON.md` first. If today is not Tuesday, stop.

1. **Recap.** `fantasy/bin/espn matchup --week <last week> --json`,
   `fantasy/bin/espn scoreboard --json`, `fantasy/bin/espn teams --json`
   (record, points for, and WAIVER PRIORITY, which resets weekly by reverse
   standings). Season log line: score, opponent, record, points-for rank,
   waiver priority, and one sentence on what decided it, judged as process.
   Then the bye race, which is the season's actual objective (a top-2 seed
   skips a single-week round and is worth about 1.9x the title odds of a
   3-6 seed): `fantasy/bin/ff standings` shows the cutline; log games and
   points ahead of or behind the #2 seed, and name the teams we are racing.
2. **Ledger.** `python3 fantasy/ledger.py settle`; note the running score in
   the Season log. Only settled ledger results may change how the board is
   built next year.
3. **Waivers.** Claiming costs nothing here (priority resets weekly), so claim
   whenever the wire beats the bench. Look at `fantasy/bin/espn fa --pos RB
   --sort proj`, the same for WR and TE, `--sort trend` for risers,
   `fantasy/bin/espn injuries`, and the bench in `espn team --json`. Rank by
   opportunity (targets, touches, snap share; `espn player <name>` shows the
   weekly log), never by last week's points; committee backs who already
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
   week or two, sell a thin-volume touchdown scorer after a big one. Scan
   rival rosters (`fantasy/bin/espn team
   --team "<name>" --json`) for buy-low targets (heavy volume, bad touchdown
   luck) and our sell-high candidates (touchdowns on thin volume). Write up to
   two concrete proposals to the Season log with the volume evidence, then put
   them to Alex: `mist-voice/bin/mist-ask "Trade idea: <give> for <get> with
   <team>. <one-line why>. Send it?" "Send=send this offer" "Skip=skip"`.
   Never send an offer yourself. Incoming offers are the incident routine's.
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
5. **Tendencies.** `fantasy/bin/espn activity --json` since last Tuesday: who
   is active, who never touches an autopicked roster (that roster is the
   wire's feeder). Update the playbook's league observations, not just the log.
6. Notify Alex with a compact summary (result, record, claims filed, priority),
   linked to the league page.
