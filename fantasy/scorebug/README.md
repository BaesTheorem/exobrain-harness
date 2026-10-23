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
| `/api/chat`, `/api/chat/send`, `/api/chat/open` | Worker | ESPN Fantasy Chat in the app: the league threads and the DMs (read every 10 s), a send, and a new DM. A send is always Alex's own tap. It is split at 240 characters and checked by a read-back, as `espn-tx chat` does (`espncli/chat.py`, `espncli/tx.py`). People show by team name, never a real name. App sends do not count toward the Mac's six-a-day cap, because that cap is for messages MIST starts. |
| Chat alerts | Worker cron | Each minute the cron reads the chat. Any message from someone else newer than the `chat:last` mark goes to the phone as one alert, or one digest when several arrived together. KV is written only when a message arrived. A tap opens the thread (`#v=chat&t=<topic>`). The app registers its device token as kind `device`. |
| Website icons | Worker | `/favicon.png`, `/apple-touch-icon.png`, `/icon-192.png` and `/manifest.webmanifest`, all from `icon/make_icon.py`, served without the key. |
| `test_model.py` | Mac | Compares `model.js` with the Python `win_prob` on random game clocks. It must print PASS after any edit to either side. |
| `/api/wire`, `wire.js` | Worker | The WIRE tab: every team's adds, drops, claims (won, lost, canceled), trades, votes and offers, our pending moves, and other teams' trades in their veto review. The Worker reads the activity feed, the last two weeks of `mTransactions2` and the pending rows itself (60 s memo) and normalizes them with `wire.js`, the twin of `espncli/league_log.py`. Lineup moves come only with `?lineups=1`. |
| `/ingest/wire` | Mac (`snapshot.py --post`) | The rival analysis from `espncli/rivals.py` (`fantasy/bin/rival-scan`): each team's needs, behavior, the wire's claim odds, the opponent, the brief, the names, and the claims and votes of older weeks. The Mac rebuilds it at most hourly; the Worker stores it only when it changed, at most every 15 minutes. |
| Trade alerts | Worker cron | Each 5 minutes: a trade that two other teams accepted shows while it waits out the veto review. A new one goes to the phone once (KV `wire:alerted`), and the tap opens the WIRE tab (the app sends `#v=chat&t=wire`, which the page routes). |
| `test_wire.py` | Mac | Runs `wire.js` and `league_log.normalize` on one live fetch and compares every event and pending row. It must print PASS after any edit to either side. `tests/test_league_log.py` does the same offline on a fixture. |
| `/api/state` `standings`, `season.js` | Worker | The STANDINGS tab: every team's W-L, PF and seed from ESPN `mTeam` (5-minute memo), this week's live win chance, and the bye, playoff and title odds. `season.js` mixes the outcome table at the live win chances of this week's games on every request, so the odds move with the scores with the Mac asleep. The small number beside each odd is the change since the week's first table. Each team shows its owner's name in parentheses, read from ESPN's member records on each request; the repo holds no names. IN and OUT are clinches and eliminations from wins alone (`season_sim._locks`): they can be late but never early. |
| `season_sim.py --table` | Mac (`snapshot.py`, at most every 30 minutes, about 15 s) | The outcome table: for each of the 2^G results of this week's G games, every team's odds from 4,000 seasons with those games forced, all on one seed. It rides in the snapshot as `season_table`; a cloud snapshot keeps the last one. The cache is `dashboard/cache/season_table.json`, and it keeps the week's first pregame chances (`pre`) as the reference for the change. |
| `test_season.py` | Mac | Builds a table and checks `season.js` against a Python mix (1e-9), the mix at the pregame chances against the plain run (1.5 points, the positive control), and a decided week against the plain run (it must move, the negative control). It must print PASS after any edit to `season.js` or `outcome_table`. |

## Access

The page and the API need the view key. Open the link that `deploy --print`
shows once; the Worker then keeps the key in a cookie for a year. The native
apps send it as a bearer token. The key, the ingest token, the URL and the
KV namespace id are in the gitignored `scorebug.json`.

## Limits

- KV on the free plan allows 1000 writes a day. The history writes once each
  2 minutes during games (about 300 on a full Sunday), and the snapshot
  writes only when it changed, at most once each 3 minutes. The wire
  analysis writes three keys at most every 15 minutes, in practice hourly.
- ESPN shows no client another team's open waiver claim or open trade offer.
  The WIRE tab shows them once they end (a failed or canceled claim, a
  canceled copy of an offer). A trade two teams accepted is visible during
  its veto review.
- The season odds come from `season_sim` on the Mac. A cloud snapshot keeps
  the last odds that the Mac sent.
- The live season odds treat this week's games as independent. That is
  exact in the simulator (no two games share a team), but real games share
  NFL players, so a big NFL game moves two fantasy games together.
- The table covers the regular season. In the playoff weeks the tab shows
  ESPN's records and the last regular-season odds.
- The bye odds are overconfident at the top end: in the 857-league check a
  predicted 84% happened 65% of the time. The tab says so in its footnote.
- A player in a live game keeps his projected scoring rate for the share of
  the game that is left (the same limit as `espn check`).
