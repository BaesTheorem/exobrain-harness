---
name: cycle-tracker-notify
description: Daily check for [Partner]'s upcoming period — notifies Alex 1 day before predicted start
---

Archived definition of the "cycle tracker notify" scheduled routine (formerly a
Claude Code scheduled task / desktop-app routine that ran daily at ~8:00 AM).
Preserved here with the app; not currently scheduled. To reinstate, recreate it
as a scheduled task with the prompt below, or schedule `notify-check.sh` via
launchd. Personal identifiers are placeholdered per the repo's privacy rules —
substitute the real People-note name and Discord channel ID at runtime.

---

Check if [Partner]'s period is predicted to start tomorrow using the cycle tracker data.

1. Read `cycle-tracker/cycle-data.json` (gitignored personal data)
2. Look at the most recent cycle's `start_date` and `settings.average_cycle_length`
3. Calculate the next predicted period start date
4. Compare to tomorrow's date

If the period is predicted within the next 1-2 days:
- Send a macOS notification: `osascript -e 'display notification "[Partner]'\''s period is expected [tomorrow/in 2 days]. Be extra thoughtful." with title "Exobrain — Cycle Tracker" sound name "Purr"'`
- Send a Discord ping to the configured channel (`<discord-channel-id>`) with a brief heads-up

If the period is more than 7 days late (predicted date was 7+ days ago and no new cycle logged):
- Notify Alex that the period appears late and suggest checking in

If no cycle data exists yet, skip silently.
