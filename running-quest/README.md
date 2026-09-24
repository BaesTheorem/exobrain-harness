# Running quest

The Mac side of the Couch to 5K quest in the Exercise Log iPhone app
(`~/Documents/exercise-log`, Quest tab). The phone runs the interval timer
and records each attempt in `exercise-log.json`; this watcher checks those
attempts against Fitbit, awards the XP the phone cannot award itself, and
nudges when a run is due and the weather is good.

| File | Tracked | Purpose |
|---|---|---|
| `quest_watch.py` | yes | The loop: verify, celebrate, nudge |
| `com.exobrain.quest-watch.plist` | yes | launchd, every 30 min (copy to `~/Library/LaunchAgents/` as a real file) |
| `.state.json` | no | Last nudge date and last run |

## What one run does

1. `exercise-log/bin/quest-verify --json` pulls the last 14 days of Fitbit
   activities and matches them to quest attempts by time overlap. A matched
   attempt gets a `verification` block; a run with no attempt becomes a free
   run. Bikes never count. The rules live in `exercise-log/lib/quest.py` and
   are mirrored in the app's `Quest.swift`.
2. Each event becomes a `mist-notify` banner and a Discord message:
   verifications and free runs to Alex's own channel
   (`DISCORD_NOTIFY_CHAT_ID`), level-ups and finished chapters to
   `QUEST_DISCORD_CHANNEL`. Unset, that falls back to his own channel; set it
   to the friends' channel id in the harness `.env` to make progress public.
3. A finished chapter moves `QUEST_LOOT_DOLLARS` from Ready to Assign into
   envelope `QUEST_LOOT_ENVELOPE_ID` in the Envelope Budget app. Both unset
   means no money moves.
4. Between 07:00 and 20:00, if a quest is due (fewer than three this week,
   none today, none completed yesterday) and the next two hours feel like 35
   to 85F with under 30% rain chance and under 20 mph wind in daylight, one
   "go now" banner and Discord DM go out. Once a day at most.

Fitbit intraday (per-minute steps and heart rate) and the TCX export both
return 403 for this app, so verification uses the activity record only:
duration, distance, average heart rate, and Fitbit's fairly/very active
minutes. Good enough to tell a run from a stroll, not enough to check each
60-second interval. Log: `~/Library/Logs/exobrain/quest-watch.log`.

## Manage

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.quest-watch.plist
launchctl kickstart -k gui/$(id -u)/com.exobrain.quest-watch     # run now
launchctl bootout gui/$(id -u)/com.exobrain.quest-watch          # stop
~/Documents/exercise-log/bin/exercise-log quest                  # current state
~/Documents/exercise-log/bin/quest-verify --dry-run              # what would match
```
