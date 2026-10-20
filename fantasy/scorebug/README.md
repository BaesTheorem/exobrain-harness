# Scorebug

The live fantasy dashboard, served from a Cloudflare Worker so that it runs
with the Mac off. The page is `fantasy/dashboard/index.html` (design in
`fantasy/dashboard/DESIGN.md`).

## How it works

The win probability has two parts.

1. **The model inputs.** Each starter's mean (ESPN projection blended with the
   betting market), spread, pregame mixture (a questionable player or an empty
   slot with the bench cover), and the same-game correlations. These need the
   full Python model, so `snapshot.py` computes them and posts them to the
   Worker. After kickoff they do not change.
2. **The live part.** ESPN's live fantasy points and the NFL game clocks. The
   Worker reads these itself, at most every 8 s, and `model.js` combines them
   with the snapshot exactly as `espncli.value.win_prob` does.

So the dashboard stays live with no Mac. Only a new snapshot needs Python, and
only before a game locks.

| Part | Where | What it does |
| --- | --- | --- |
| `snapshot.py` | Mac (`ff-dash`, launchd `com.exobrain.ff-dash`) or GitHub Actions | Runs the model for all six games and posts it to `/ingest`. The Mac posts every 2 minutes on game days and every 30 minutes on other days. |
| `worker.js` + `model.js` | Cloudflare Worker `scorebug` | Serves the page, `/api/state` and `/logo/<id>`. A cron each minute saves the history every 2 minutes while a game is on. When the snapshot is old (20 minutes while kickoffs are near, 6 hours otherwise) or a lineup changed, it dispatches `scorebug.yml` in `BaesTheorem/fantasy-cloud`. |
| `deploy` | Mac | Uploads the Worker, the model and the page, with the KV binding, secrets and cron. `bin/cloud-sync` runs it when the ESPN cookies change. |
| `/api/summary`, `/la/register` | Worker | The short summary that the iPhone widget reads, and the Live Activity push tokens. On the same 2-minute cadence the cron starts the Live Activity by push when one of our starters' games is on, updates it, and ends it when nothing of ours is live or due within 4 hours. The pushes use the team APNs key (the one MIST Alarms uses). |
| `icon/make_icon.py` | Mac | The app icon: the Material Symbols "scoreboard" glyph on the score bug red. Writes the iOS PNG and the macOS `.icns`. |
| `/Applications/Scorebug.app` | Mac | The desktop app: `app-shell/build-app.sh "Scorebug" scorebug "$(fantasy/scorebug/deploy --print)" "" --icon fantasy/scorebug/icon/Scorebug.icns --bundle-id com.exobrain.scorebug`. |
| iPhone app | private repo `BaesTheorem/scorebug` (`~/Documents/scorebug`) | The page in a native web view, a home and lock screen widget, and the Live Activity. |
| `test_model.py` | Mac | Compares `model.js` with the Python `win_prob` on random game clocks. It must print PASS after any edit to either side. |

## Access

The page and the API need the view key. Open the link that `deploy --print`
shows once; the Worker then keeps the key in a cookie for a year. The native
apps send it as a bearer token. The key, the ingest token, the URL and the
KV namespace id are in the gitignored `scorebug.json`.

## Limits

- KV on the free plan allows 1000 writes a day. The history writes once each
  2 minutes during games (about 300 on a full Sunday), and the snapshot
  writes only when it changed, at most once each 3 minutes.
- The season odds come from `season_sim` on the Mac. A cloud snapshot keeps
  the last odds that the Mac sent.
- A player in a live game keeps his projected scoring rate for the share of
  the game that is left (the same limit as `espn check`).
