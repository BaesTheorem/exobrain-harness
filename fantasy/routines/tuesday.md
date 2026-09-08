# Tuesday routine (6:00 PM CT): recap, ledger, waivers, trades, tendencies

Follow `fantasy/routines/COMMON.md` first.

1. **Recap.** `fantasy/bin/espn matchup --week <last week> --json`,
   `fantasy/bin/espn scoreboard --json`, `fantasy/bin/espn teams --json`
   (record, points for, and WAIVER PRIORITY, which resets weekly by reverse
   standings). Season log line: score, opponent, record, points-for rank,
   waiver priority, and one sentence on what decided it, judged as process.
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
   room; never drop a starter. File up to two claims, best first:
   `fantasy/bin/espn-tx claim "<name>" --drop "<bench player>"` (no `--drop`
   when a slot is open), confirming `"verified": true`. If nothing beats the
   bench, say so and file nothing. Week 7 is Daniels' bye: that week, claim a
   streaming QB instead (the IR slot and a drop make room).
4. **Trades, from week 3 on.** Scan rival rosters (`fantasy/bin/espn team
   --team "<name>" --json`) for buy-low targets (heavy volume, bad touchdown
   luck) and our sell-high candidates (touchdowns on thin volume). Write up to
   two concrete proposals to the Season log with the volume evidence, then put
   them to Alex: `mist-voice/bin/mist-ask "Trade idea: <give> for <get> with
   <team>. <one-line why>. Send it?" "Send=send this offer" "Skip=skip"`.
   Never send an offer yourself. Incoming offers are the incident routine's.
5. **Tendencies.** `fantasy/bin/espn activity --json` since last Tuesday: who
   is active, who never touches an autopicked roster (that roster is the
   wire's feeder). Update the playbook's league observations, not just the log.
6. Notify Alex with a compact summary (result, record, claims filed, priority),
   linked to the league page.
