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
  lineup routine.
- **left_roster / joined_roster / other.** Log it.

Finish with one Season log line per incident and one notification to Alex
summarizing what you did, linked to the roster page.
