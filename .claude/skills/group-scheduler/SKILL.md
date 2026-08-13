---
name: group-scheduler
description: MIST as the friend-group event scheduler -- reasons over everyone's known constraints and proposes concrete times instead of running a "whenisgood" poll. Plans events, logs friends' availability into People notes, ingests opt-in calendar free/busy feeds, learns availability from Discord conversations, posts proposals to the friend group server, and tallies RSVPs. Use when the user says "schedule a hangout", "plan game night", "find a time for", "when can we all", "who's free", "log [name]'s availability", "[name] is out of town", "onboard [name] to the scheduler", "any RSVPs", "how's the [event] proposal doing", or wants to finalize a group event.
---

# Group Scheduler

MIST is the scheduler. Gather every constraint already known, propose the
2-3 best concrete times with the reasoning shown, and only then ask humans
to react. A poll is the fallback when reasoning runs out of data, never the
opening move.

Runtime data lives in `scheduler/` (see its README). Availability facts live
in People notes under `## Availability` (format: `[[People Note Schema]]` in
the vault).

## Data sources, in precedence order

When constraints conflict, higher wins. A person's own recent words beat
anything inferred.

1. **People note `## Availability`** -- stated constraints with provenance.
   Alex-editable; always read fresh, never cache.
2. **Free/busy cache** (`scheduler/freebusy-cache.json`) -- for friends who
   opted in with a calendar feed. If `generated_at` is older than 24h, run
   `python3 scheduler/ics_freebusy.py` first (wrap in `mist-progress run`
   when interactive). Per-person `error` fields mean stale data: say so.
3. **Discord digest** (`discord/discord-digest.json`) -- availability
   statements from the last 7 days that may not be integrated yet.
4. **Claude Bus** (`/claude-bus`) -- for friends whose Claudes are on the
   bus: ask in a `scheduling` thread. Bus protocol already permits coarse
   availability ("free after 6 most weeknights") without human approval;
   never ask a friend's Claude for calendar contents.
5. **Alex himself** -- Google Calendar MCP (camelCase params, see
   `/calendar`) plus Things 3 deadlines. Alex is always a must-have.

## Privacy rules (hard)

- Free/busy only, ever. `ics_freebusy.py` discards titles at parse time; the
  skill never requests or stores what anyone is *doing*.
- **Source sensitivity**: a conflict learned from a calendar feed or DM is
  used silently to rank candidates. Only conflicts the person stated in the
  same public channel may be cited in a public proposal. "Thursday scored
  lower" is fine to post; "Heidi's calendar shows busy Thursday" is not.
- `feeds.json`, `freebusy-cache.json`, and `events/` are gitignored. No
  friend names or URLs in tracked files, ever.

## Modes

### 1. Plan -- `/group-scheduler plan <event> [window] [people]`

1. **Roster.** Infer or ask: who's invited, who is must-have vs nice-to-have,
   minimum viable headcount. Resolve names against People notes (Discord
   handles via `USERNAME_MAP` in `discord/discord-digest-fetch.py`,
   gitignored, read at runtime).
2. **Gather.** For each person, pull all five sources above. Note what is
   *unknown* -- an empty Availability section is not "always free".
3. **Generate candidates.** Slots in the window that fit the event's shape
   (evening vs afternoon, duration, venue hours if known).
4. **Score.** Hard blocks first (must-have conflicts, Alex's calendar,
   one-off windows), then soft: stated preferences, notice period ("needs a
   week"), fairness (check `scheduler/events/` history -- who got skipped or
   outvoted last time), observed patterns (game nights land on Saturdays).
5. **Output.** Top 2-3 candidates with a per-person status line
   (✅ free / ⚠ soft conflict / ❌ hard conflict / ❓ unknown) and the
   reasoning, plus a recommendation. Save a draft event file to
   `scheduler/events/<slug>.json` (schema below).

### 2. Propose -- post to Discord

Draft a short post for the Hangouts channel: the event, the top candidates,
one line of reasoning, and "reply here with what works". Friends cannot
converse with the bot (owner-only invariant in `claude-bot/` -- do not work
around it), so the post must ask for plain replies, not commands.

This is an outward-facing send: ask Alex in chat AND fire a `mist-notify`
banner with Approve/Deny buttons (Notification Policy in CLAUDE.md), then
wait. On approval:

```bash
python3 discord/discord-send.py "$DISCORD_CHANNEL_HANGOUTS" --file /tmp/proposal.txt
```

Update the event file: `status: proposed`, `proposal.posted_at`, and the
candidate list as posted.

### 3. Track / finalize -- `/group-scheduler status [event]`

1. Read open event files, then scan the digest for replies newer than
   `proposal.posted_at`. Digest refreshes every 4h; for a fresh tally run
   `python3 discord/discord-digest-fetch.py --hours 6` first.
2. Tally per candidate. Route any *general* availability statements found
   along the way to People notes (mode 4).
3. When a candidate has quorum and no must-have conflicts, recommend
   finalizing. On Alex's go: create the calendar event (dup-check first, per
   `/calendar`), append to today's daily note, create a Things 3 prep task
   if needed (no `when` date), and post a confirmation to Discord (approval
   banner again). Set `status: confirmed`.
4. Events with no traction after ~5 days: surface in the daily briefing as
   stalled; suggest a nudge or `status: abandoned`.

### 4. Log availability -- `/group-scheduler avail <person> <fact>`

Also invoked by `/discord-digest` when conversations reveal availability.

1. Read the person's full People note (crm mode 9 discipline).
2. Classify: **Persistent** (standing rule), **One-off** (dated window),
   **Prefers** (soft signal). Write to `## Availability` per the format in
   `[[People Note Schema]]` -- create the section after `## Follow-ups` if
   missing. Every line gets `(source, YYYY-MM-DD)` provenance.
3. Recency wins: a new fact that contradicts an old line replaces it.
4. Prune One-off lines whose window has passed while you're in the file.

### 5. Refresh feeds -- `/group-scheduler refresh`

Run `python3 scheduler/ics_freebusy.py` (add `--person NAME` for one
person). Report per-person block counts, warnings, and errors. A feed that
has failed for over a week: flag to Alex, the friend may have revoked or
rotated the URL.

### 6. Onboard a friend -- `/group-scheduler onboard <person>`

Three tiers; the friend picks, least-data-wins. Draft any message to the
friend in Alex's plain voice (run `/de-ai`), for Alex to send himself.

- **Tier 0, nothing**: no setup. Availability comes from what they say on
  Discord and what Alex logs manually. This is the default for everyone.
- **Tier 1, calendar free/busy**: friend shares a read-only feed.
  - Google: calendar Settings -> "Secret address in iCal format" -> send the
    URL to Alex. Alternative: share the calendar with alex.hedtke@gmail.com
    as "See only free/busy", which shows up via the Calendar MCP instead of
    a feed; note it in their People note if so.
  - Apple: public calendar link (`webcal://`).
  - Add to `scheduler/feeds.json` (key = People-note filename), run a
    refresh to verify, add a `- **Calendar**: free/busy feed connected
    YYYY-MM-DD` line to their `## Availability`.
- **Tier 2, Claude Bus**: for friends who run Claude. Mint a bus invite
  (`/claude-bus`), and their Claude answers availability asks in the
  `scheduling` thread at whatever grain the friend allows.

## Event file schema -- `scheduler/events/<slug>.json`

```json
{
  "name": "Game night",
  "created": "2026-08-12",
  "window": {"start": "2026-08-14", "end": "2026-08-30"},
  "quorum": 4,
  "roster": {
    "[Name]": {"required": true, "rsvp": null, "source": null}
  },
  "candidates": [
    {"start": "2026-08-22T18:00:00-05:00", "end": "2026-08-22T22:00:00-05:00",
     "yes": [], "no": [], "maybe": []}
  ],
  "proposal": {"posted_at": null, "channel": "hangouts"},
  "status": "draft",
  "final": null
}
```

`status`: draft -> proposed -> confirmed | abandoned. Keep confirmed and
abandoned files around; they are the fairness history mode 1 reads.

## Gotchas

- The bot never replies to friends in KC Coven; all friend interaction is
  passive (they reply, the digest carries it back). Expect up to 4h latency
  unless you fetch manually.
- An unknown person in a reply thread: resolve via `USERNAME_MAP`; if
  unresolved, flag to Alex rather than guessing.
- Do not calendar ambiguous outcomes ("sometime next weekend") -- that is
  the `/calendar` rule: clear date AND time or it stays a Things task.
- Never set `when` on Things tasks (Alex schedules his own).

## Integration

- **`/discord-digest`** routes availability signals here (mode 4) and feeds
  RSVP replies to mode 3.
- **`/daily-briefing`** includes open proposals: tally so far, stalled flags.
- **`/crm`** owns the People-note discipline; `## Availability` rules live
  in `[[People Note Schema]]`.
- **`/claude-bus`** is the opt-in lane for friends' Claudes (tier 2).
