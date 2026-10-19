# Cloud fallback: how a fantasy routine runs when the Mac is away

A cloud Claude routine (claude.ai/code/routines) uses this file. It fires at
the same times as the Mac's launchd routine and does the work only when the
Mac heartbeat is stale, so the two never run the same routine. The design is
in `fantasy/cloud/README.md`.

The session starts on a fresh clone of the public harness at
`/home/user/exobrain-harness` (or wherever the clone is; run from its root).
Nothing from the Mac is on disk until step 1 puts it there.

1. Run `python3 fantasy/cloud/cloud-run start <routine>` with
   `FANTASY_HUB_TOKEN` exported (the routine prompt gives the value).
   - If it exits 3 and prints `MAC_UP`, **stop at once**. The Mac runs this
     routine. Write nothing and send nothing.
   - If it prints `READY`, the ESPN cookies, the playbook, the skill and the
     watchlist are now at their Mac paths under `$HOME`, and
     `mist-voice/bin/mist-notify` sends a Discord DM to Alex.
2. Read `$HOME/.claude/skills/fantasy-football/SKILL.md` with the Read tool.
   It is the fantasy-football skill: the Skill tool cannot load it in this
   session, so reading the file is how you invoke it.
3. Follow `fantasy/routines/COMMON.md` and then the routine file
   (`lineup.md`, `tuesday.md`), with the differences below. Where they
   disagree, this file wins.
4. Run `python3 fantasy/cloud/cloud-run finish <routine>`. It sends the
   changed playbook and the changed tracked files to the hub, and the Mac
   takes them back when it is up. Do this even when the run failed partway,
   so that the playbook edits you made are not lost.

## Differences from the Mac run

- **No `bin/routine-guard`.** Do the weekday check yourself: the Sunday
  lineup routines run only on a Sunday, the Tuesday routine only on a Tuesday
  (America/Chicago). On another day, stop after step 1 and run step 4.
- **The lineup precheck**: run `python3 fantasy/bin/lineup-precheck`. If it
  exits 3 (no starter locks in the next 27 hours), write
  `fantasy/bin/routine-log lineup "precheck: no starter locks within 27 hours; run skipped"`,
  run step 4 and stop.
- **Notifications** go to Discord only. `mist-voice/bin/mist-notify` takes
  the same arguments as on the Mac, but it ignores `--action` buttons,
  `--reply` and the Console. A choice that needs Alex (a trade offer, a drop
  that is his tap) goes out as one DM with your recommendation and the exact
  reply he can type in a Console chat later. Never act on it yourself.
  `mist-ask` and `http://127.0.0.1:5014` do not exist here.
- **No commits.** Do not run `bin/harness-commit`, `git commit` or
  `git push`. The Mac commits what `cloud-run finish` sends back.
- **ESPN auth**: `ff refresh` cannot run here (it reads Chrome). If a tool
  reports "rejected the cookies", send one DM that says the cloud copy of the
  ESPN cookies expired and that `ff refresh` on the Mac fixes it (cloud-sync then redeploys the hub),
  then run step 4 and stop.
- **Data a cloud clone lacks**: `fantasy/.cache/` is empty, so the residual
  library, `leverage.json` and the volume file are not there at the start.
  `volume build --fresh` downloads nflverse data; if the download fails,
  say so in the log line and decide without the volume flags. Do not invent
  a number a tool did not give you.
- **The playbook** is a copy. Edit it at its `$HOME` path exactly as the Mac
  run edits the real one (Season log under the current week, `updated:`
  field). Step 4 sends it back.
- Write log lines with `fantasy/bin/routine-log` as usual. Step 4 sends them.
- Start the Season log line of every cloud run with `(cloud)` so Alex can see
  which runs the Mac did not do.
