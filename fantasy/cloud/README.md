# Fantasy cloud fallback

The fantasy watchers and routines run on the Mac. When the Mac is off or
asleep, this fallback runs them in the cloud, so a lineup problem or a
Sunday lineup call does not wait for the laptop.

## Parts

| Part | Where | What it does |
| --- | --- | --- |
| `worker.js` | Cloudflare Worker `fantasy-hub` | Keeps the Mac heartbeat in KV. Every 15 minutes its cron examines the heartbeat. If the heartbeat is older than 35 minutes, it starts the GitHub workflow and sends one Discord DM ("cloud fallback is on"). It also holds the ESPN cookies, the playbook and skill copies, and the edits that cloud runs send back. |
| `deploy` | Mac | Uploads the Worker, its secrets and its cron through the Cloudflare API. Writes the gitignored `hub.json` (URL and bearer token). |
| `../bin/cloud-sync` | Mac, from `lineup-watch` every 15 minutes | Sends the heartbeat, uploads the playbook, skill and watchlist when they change, and takes back the cloud edits. |
| `watch.yml` | private repo `BaesTheorem/fantasy-cloud` | GitHub Actions runs `lineup-watch --fix` and `roster-watch --no-routine` on a clone of this repo. Notifications become Discord DMs. Watcher state persists in the Actions cache. |
| `cloud-run` | cloud Claude session | `start` gates the run (Mac up, local time slot, once a day) and puts the Mac files in place. `finish` sends the edits back. |
| `../routines/CLOUD.md` | cloud Claude session | The differences between a cloud run and a Mac run. |

The workflow lives in a private repo because Actions logs on a public repo are
public, and the logs show the roster.

## How the two sides stay apart

- A cloud run does work only when the Mac heartbeat is stale. The cloud copy of
  `lineup-watch` sets `FANTASY_CLOUD=1` and never sends a heartbeat.
- A cloud routine sends each changed file with the sha256 of the text it
  started from. `cloud-sync` writes the file only when the Mac copy still has
  that sha256. In all other cases it writes `<name>.cloud.<ext>` next to the
  file and sends a DM, so an edit on the Mac is never overwritten.
- The Mac heartbeat does not replace the hub's playbook copy while cloud edits
  wait to be taken back.

## Cloud routines

Four routines at claude.ai/code/routines, model Fable, one for each Mac
routine: `fantasy-lineup` (daily 5:30 PM CT), `fantasy-lineup-sunday`
(10:40 AM), `fantasy-lineup-sunday-pm` (2:35 PM) and `fantasy-tuesday`
(6:00 PM). Routine cron is in UTC, so each one fires at both UTC offsets
(CDT and CST). `cloud-run start --days --window` lets only the fire inside the
local slot continue.

## Limits

- `ff refresh` reads the cookies from Chrome on the Mac. After a refresh, run
  `fantasy/cloud/deploy` again, because the cloud copy is a Worker secret.
- The incident routine and `chat-watch` are not in the cloud. `roster-watch`
  sends the incident as a DM, and the judgment waits for the Mac.
- A cloud clone has no `fantasy/.cache/`. Tools that read cached models
  (the forecast residual library, `leverage.json`) run with their defaults or
  rebuild the data.
- The hub token is in the routine prompts, because routines do not accept
  environment variables. Rotate it with a new `hub.json` token, `deploy`,
  `gh secret set HUB_TOKEN -R BaesTheorem/fantasy-cloud`, and an update to the
  four prompts.

## Test it

    curl -s -A x https://fantasy-hub.alex-hedtke.workers.dev/status
    gh workflow run watch.yml -R BaesTheorem/fantasy-cloud -f force=true
