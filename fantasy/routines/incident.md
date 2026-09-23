# Incident routine (started by roster-watch; not on a schedule)

Follow `fantasy/routines/COMMON.md` first.

**Asking Alex from a routine: not `mist-ask` (found 2026-09-16).** Every "put it
to Alex" below used to name `mist-ask`, which needs `$MIST_CONSOLE_SESSION` and
exits nonzero without it. `run-routine.sh` does not set that variable, so
**`mist-ask` fails in every routine run**, this one included. Use
`mist-voice/bin/mist-notify` with `--action` buttons instead, each button a
`cmd:` curl that POSTs the reply into the Console with no session id:

```
--action "Label=cmd:/usr/bin/curl -sS -X POST http://127.0.0.1:5014/notify-reply \
  -H 'Content-Type: application/json' -d '{"text": "the reply Alex is sending"}'"
```

Then verify the banner actually carried the buttons by reading the last row of
`~/Library/Logs/exobrain/notifications-history.jsonl` and checking its
`actions` list, because a notification that silently lost its buttons looks
identical to one that kept them. Measure the result, not the call.

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
  a `mist-notify` banner carrying Accept / Reject / Counter buttons built the
  way the note at the top of this file describes. Never accept or reject
  yourself.
- **waiver_result.** Log the outcome (`fantasy/bin/ff roster`,
  `fantasy/bin/espn activity --json`). If the new player should start this
  week and a lock is within 6 hours, set him now; otherwise leave it for the
  lineup routine. If every claim failed and a roster spot is still open, the
  wire is now first-come: add the best remaining player by the Tuesday rules
  with `fantasy/bin/espn-tx claim "<name>" --fa` (no drop needed for an open
  spot) and log who else was considered.
  **Then check the depth at one-slot positions (QB, TE, K, D/ST).** Claims are
  filed in branches on purpose, and a backstop that was supposed to be
  mutually exclusive can land anyway. Sharing a drop player between two claims
  does make the second conditional: ESPN rejects a claim whose drop is already
  gone with `FAILED_PLAYERALREADYDROPPED` on the same processing tick (verified
  2026-09-23, Geno for Noel behind Young for Noel). A claim filed against a
  *different* drop is not conditional on anything, so the count still has to
  be read off the roster. Two deep at a one-slot position is a dead
  roster spot on a full roster, so drop the worse one on the playbook's value
  rule and log both. Never assume the branch resolved the way it was designed
  to; read the roster back and count.
  **The playbook's Season log may carry a named branch for the week** (which
  add closes out a trade negotiation, which reopens it). Apply it if present,
  and mark it resolved there when you do.
- **trade_resolved** (an offer we sent left the pending list). Read
  `fantasy/bin/espn raw --views mTransactions2 --json --limit 0`: a row with
  `memberId` `TradeTaskProcessor`, `executionType` `CANCEL`, and
  `relatedTransactionId` pointing at ours means it expired unanswered (the
  original keeps `status: PENDING`); otherwise the roster diff says whether
  it went through. Log it, and if it expired put the re-send to Alex with
  buttons (Re-send now / Wait for Tuesday / Drop it), built the way the
  note at the top of this file describes. Never re-send on
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
