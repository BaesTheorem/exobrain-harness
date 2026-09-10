# Incident routine (started by roster-watch; not on a schedule)

Follow `fantasy/routines/COMMON.md` first.

Read `fantasy/.cache/incidents.jsonl`. Handle every line whose `"handled"` is
false, oldest first, then rewrite the file with those lines marked
`"handled": true` (keep every line; the file is the audit trail).

- **status** (a rostered player's injury status changed). Starter now OUT,
  DOUBTFUL, or SUSPENSION: swap the best bench option in now
  (`fantasy/bin/espn-tx swap`), unless his kickoff has passed. Any player now
  INJURY_RESERVE: `fantasy/bin/espn-tx ir "<name>"` if the IR slot is free,
  then, if that opened a roster spot, file a claim under the Tuesday waiver
  rules when someone on the wire is clearly worth it. QUESTIONABLE: no action;
  the lineup routine and lineup-watch handle it. Healthy again: note it.
- **trade_offer.** Evaluate with the skill's trade rules: volume beats points,
  touchdown luck, positional value in full PPR, the effect on our starting
  nine, and why the other manager wants it. Write the evaluation to the
  Season log. Then ask Alex and stop:
  `mist-voice/bin/mist-ask "Trade offer from <team>: they get <X>, we get <Y>.
  My read: <one line>." "Accept=accept the trade" "Reject=reject the trade"
  "Counter=counter it"`. Never accept or reject yourself.
- **waiver_result.** Log the outcome (`fantasy/bin/ff roster`,
  `fantasy/bin/espn activity --json`). If the new player should start this
  week and a lock is within 6 hours, set him now; otherwise leave it for the
  lineup routine. If every claim failed and a roster spot is still open, the
  wire is now first-come: add the best remaining player by the Tuesday rules
  with `fantasy/bin/espn-tx claim "<name>" --fa` (no drop needed for an open
  spot) and log who else was considered.
- **trade_resolved** (an offer we sent left the pending list). Read
  `fantasy/bin/espn raw --views mTransactions2 --json --limit 0`: a row with
  `memberId` `TradeTaskProcessor`, `executionType` `CANCEL`, and
  `relatedTransactionId` pointing at ours means it expired unanswered (the
  original keeps `status: PENDING`); otherwise the roster diff says whether
  it went through. Log it, and if it expired put the re-send to Alex with
  `mist-ask` (Re-send now / Wait for Tuesday / Drop it). Never re-send on
  your own.
  **If it went through, refill the slot it emptied, immediately and without
  asking** (standing authorization, 2026-09-10). An accepted trade that sends
  away a starter leaves a hole that scores zero, and Lineup Protection is OFF.
  Put the acquired player into the vacated slot with `fantasy/bin/espn-tx
  swap` / `move` and confirm `"verified": true`; if the acquired player is not
  startable there, fill it with the best bench option by the lineup routine's
  step 4 rules. Do this before that slot's kickoff and do not wait for the
  next scheduled run, since a trade in review is invisible to `espn check`
  until the roster actually moves. **The boundary: accepting, rejecting, and
  sending trades stay Alex's tap. Executing the lineup consequence of a trade
  he already approved is not a trade decision, it is the empty-slot repair
  `lineup-watch` already does on sight.**
- **left_roster / joined_roster / other.** Log it.

Finish with one Season log line per incident and one notification to Alex
summarizing what you did, linked to the roster page.
