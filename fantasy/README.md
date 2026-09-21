# fantasy

Tooling for Alex's ESPN fantasy league **"Roll for First Down"** (his team:
**Chaos Legion**, abbrev **LMAO**). Strategy lives in the `/fantasy-football`
skill and the vault playbook; this dir is the data layer, the draft board, and
the audits that keep the board honest.

## Map

Draft-morning pipeline, in the order `bin/draft-morning` runs it:

| Script | Reads | Writes | Job |
|---|---|---|---|
| `bin/ff draft`, `bin/ff schedule` | ESPN | stdout | Draft date/status; idle week per team (13 teams, one sits weekly) |
| `ringer_board.py` | The Ringer | `ringer_board.json` | Editorial positional ranks (who is best at a position) |
| `examiner.py --refresh` | FantasyPros | `draftbot/ecr.json` | Expert consensus ranks, the outside yardstick |
| `opportunity.py` | nflreadpy (2025) | `draftbot/opportunity.json` | Volume metrics and TD-regression BUY/SELL flags |
| `vor.py` | ESPN + Sleeper projections, Ringer, overrides | `draftbot/vor.json` | The board: value over replacement on this league's scoring |
| `signoff.py status` | board, ECR, `board-overrides.json` | exit code | **The gate.** Unsigned board-vs-consensus divergences block the draft |
| `tier_sheet.py` | board, opportunity | `draft-sheet.html` | Printable tiers (exact 1-D k-means on value) with flags |
| `consensus.py` | CBS + FFToday | `draftbot/consensus.json` | Independent judge for post-draft grading. **Never read by `vor.py`** |

Around the draft: `sim.py` (offline 13-seat simulator, mirrors the autopilot's
scoring), `ledger.py` (board-vs-consensus bets, settled with real season
points), and `draftbot/` (the autopilot itself, the only thing here that
**writes** to ESPN; see its README).

## Tool 1: `bin/ff`

`bin/ff` -- Python, stdlib + `cryptography` (already on the system python). Runs
against the ESPN Fantasy v3 read API. **Read-only by invariant**: it never sets a
lineup, makes a claim, or proposes a trade. It surfaces numbers; decisions stay
with Alex.

```
ff standings     # league table with bye (top 2) and playoff (top 6) cutlines
ff roster        # Chaos Legion's current roster
ff draft         # draft date, clock, order rule, teams joined, started/done
ff schedule      # idle week per team; warns if Alex's is not week 8
ff refresh       # re-pull ESPN cookies from Chrome (when auth expires)
ff raw --views mMatchup,mRoster --limit 0   # raw API dump (default limit 4000 chars, truncated JSON warns on stderr)
```

## Tool 2: `bin/espn`

The in-season sibling of `ff`, built 2026-09-07. Same credential file, same
read-only invariant, plus the cookie-free public NFL API for the slate. Every
subcommand takes `--json` (for other scripts) and `--fresh` (bypass the caches
in gitignored `.cache/`: NFL schedule and the player index for a day, the 9 MB
injury report for 30 minutes).

```
espn teams                 # every team: record, owner initials, WAIVER PRIORITY, moves
espn team [--team X]       # a roster with opponent, kickoff, status, weekly projection
espn matchup [--week N]    # both lineups, the margin (live once anyone has locked), and the variance rule
espn check                 # pre-kickoff checklist: OUT/bye/empty slots, bench upgrades, lock order
espn scoreboard            # every matchup this week, projected and actual
espn fa --pos RB           # free agents + waivers: projection, %owned, 7-day trend, ADP
espn player <name|id>      # card: status, ownership, projections, weekly log, news
espn news <name>           # the player's news feed (Rotowire via ESPN)
espn activity [--pending]  # adds/drops/waivers/trades; pending claims
espn draft [--picks|--mine]  # order, status, every pick as it happens
espn schedule              # a team's H2H schedule and results (ff schedule = idle weeks)
espn settings              # scoring table by stat, lineup, waivers, playoffs, trades
espn nfl [--week N]        # NFL slate: kickoffs (CT), lines, implied totals, weather, TV
espn injuries [--all|--team KC|--pos RB]   # injury report, default scoped to the roster
espn stream --pos DST|K    # streamers with opponent/own implied totals and weather
espn raw --views mMatchup --period 3 --filter '{...}'   # any view, any filter
```

Code lives in `espncli/` (`client.py` transport + helpers, `cli.py` commands,
`statmap.py` stat ids). Tests: `pytest tests/test_espncli.py` (fixture-driven,
no network; the lineup check is tested against a planted-bad roster because
its failure mode is a quiet "all OK").

## Tool 3: `bin/espn-tx` (the one that writes)

Lineup moves and waiver claims over ESPN's transactions endpoint, added
2026-09-07 to put Jordyn Tyson on IR and file the first two waiver claims.
`ff` and `espn` stay read-only by invariant; `espncli/tx.py` is the only module
that POSTs and this is the only command that imports it. Every write verifies
the result with a read (the roster slot changed, the claim is listed as
pending) and exits nonzero if the read-back disagrees.

```
espn-tx ir "Jordyn Tyson"                 # bench -> IR slot
espn-tx move "Player" --to BE|IR|FLEX|RB  # any slot move
espn-tx claim "Chris Brooks" [--drop "X"] # waiver claim; --fa for a free-agent add
espn-tx pending                           # this team's pending claims
espn-tx cancel <transaction id>
espn-tx --dry-run ...                     # print the payload, send nothing
```

The payload shape ESPN's web client uses is documented at the top of
`espncli/tx.py`. Writes go to `lm-api-writes.fantasy.espn.com` (the reads host
is a different hostname); the same `espn_s2` + `SWID` cookies authorize both.

## Tool 4: `bin/lineup-watch` (launchd, pings only on a problem)

`com.exobrain.lineup-watch` runs `bin/lineup-watch` every 15 minutes. It asks
`espn check --json` for the week's lineup problems and lock order, and sends a
banner (clickable to the ESPN roster page, with an "Ask MIST" button) only
when a problem's starter locks within 75 minutes, once at the edge of the
window and once as a final call at 20 minutes. Definite problems (OUT, empty
slot, IR, suspension, bye) are announced the first time they appear regardless
of the clock. A clean lineup writes one log line and nothing else. State in
`.cache/lineup-watch.json` keeps a problem from being re-announced every run.

```
bin/lineup-watch --dry-run                # what it would do right now
bin/lineup-watch --dry-run --window 9999  # treat every lock as imminent
bin/lineup-watch --force                  # one real banner per current problem (test)
```

Install or reinstall: copy `com.exobrain.lineup-watch.plist` to
`~/Library/LaunchAgents/` (a real copy, not a symlink) and `launchctl bootstrap
gui/$(id -u)` it. Logs: `~/Library/Logs/exobrain/lineup-watch.log`.

## Tool 5: `bin/roster-watch` (launchd, every 30 minutes)

Diffs the roster's injury statuses, our pending claims, and pending
transactions aimed at the team against the last run. New events go to
`.cache/incidents.jsonl`, a banner, and (when judgment is needed) the
`fantasy-incident` routine via the Console's `run-routine.sh`. Install like
`lineup-watch` with `com.exobrain.roster-watch.plist`.

## Tool 6: `bin/forecast` (the weekly prediction-and-review loop)

Alex's standing instruction from 2026-09-17: every week opens with MIST's own
50% and 90% intervals on every rostered player, both team totals, the win
probability and the league standing after the week, and closes with a review
of where reality landed. ESPN is one input among five, and the intervals are
MIST's judgment, so this tool never predicts. It:

- `forecast dossier --week N --save f.json` builds the evidence pack: weekly
  projections from ESPN, Sleeper, CBS, FantasyPros and FFToday, unit-normalized
  per position (CBS and FFToday score a passing touchdown 6, not 4; the factors
  print at the top), the consensus and spread, each player's season log against
  ESPN's number, injury status, the Vegas line and implied total, the historical
  actual/projection ratio quantiles by position and projection tier, and a
  mechanical baseline (consensus times bootstrapped ratio, every matchup
  simulated 5,000 times) that the review uses as a yardstick.
- `forecast record mist.json --dossier f.json` validates MIST's forecast (the
  50 inside the 90, every player present, no probability of 0 or 1) and files
  `forecasts/<season>-wNN.json`, committed.
- `forecast settle` scores the finished week for MIST and the baseline;
  `forecast history` is the season coverage table.
- `forecast calibrate --seasons 2025,2026` rebuilds `.cache/residuals.json`
  from Sleeper's weekly projections and actuals (gitignored; about 5,500
  player-weeks).

- `forecast playbook` rewrites the playbook's Season log grouped by
  `### Week N` headers (newest first), each week opening with its Forecast
  table and Review scorecard rendered from the JSON; every dated bullet is
  kept verbatim. `record`, `settle` and `note` run it automatically.
  `forecast note --week N --review "..."` (or `--forecast`) attaches MIST's
  commentary so it renders inside the block.

The Tuesday routine runs `settle` first and the new week's forecast last. The
JSON schema MIST writes is spelled out in `routines/tuesday.md` step 7.

## Tool 7: `bin/chat-watch` (launchd, every 10 minutes)

`com.exobrain.chat-watch` asks `espn chat --unanswered` which threads end with
somebody else's message, drops the ones already handled by message id, and
splits what is left two ways.

- **League-wide threads** (`CHAT`, `CHAT_ALL_MEMBERS`) go to a headless Claude
  on `routines/chat.md`, which writes a draft through `bin/chat-draft` and
  never posts. Six drafts a day, enforced in the watcher rather than the
  prompt: a prompt is a request, a counter is a limit.
- **Direct messages** (`CHAT_DIRECT_MESSAGE`) are escalated to Alex instead,
  never answered unattended (his instruction, 2026-09-20). So is anything from
  a manager we have a trade in flight with, whatever thread it arrived in.

An escalation is three deliveries, grouped per thread: a Discord DM from the
bot to Alex's own DM channel (`DISCORD_NOTIFY_CHAT_ID` in the harness `.env`,
so a leaguemate's message never reaches a channel the friend group can read),
a `mist-notify` banner linking straight to the chat, and a new MIST Console
chat titled `Fantasy DM: <team>` and seeded with the thread plus the standing
"draft it, do not send it" instruction. It uses `POST /sessions` rather than
`/quick-new` on purpose: `/quick-new` also makes the main window jump to the
new chat, and yanking Alex out of what he is typing costs more than a chat he
finds when he looks.

The three paths fail independently (bot token, Console not running, notifier
permissions), so the message id is burned only when **at least one** landed.
All three failing while the id is marked handled anyway is how a DM would
disappear without anybody noticing.

```
bin/chat-watch --dry-run --force     # classify everything waiting, send nothing
bin/chat-watch --self-test           # exercise the Fable -> Opus fallback chain
```

Logs: `~/Library/Logs/exobrain/chat-watch.log`. State (handled ids, drafts per
day): `.cache/chat-watch.json`.

## The scans (2026-09-20): `bin/volume`, `bin/swap-scan`, `bin/stream-scan`, `bin/league-scan`

All read-only, all `--json`, all built the night Alex asked what else would
raise the odds. The shared pieces live in `espncli/value.py`: `ros_rate`
(the one in-season currency: half ESPN's static preseason `season_proj`,
half the live weekly projection, season PPG from week 5) and the spread model
(`player_sd`, `win_prob`, `best_swaps`, `best_fill`) that turns the playbook's
variance rule into a number in `espn check` and `espn matchup`.

| Tool | Reads | Says |
|---|---|---|
| `volume roster/fa/league/player` | nflreadpy weekly stats + snap counts, ESPN rosters | targets, target share, WOPR, snaps, BUY/SELL/ROLE flags; writes `.cache/player-sd.json` |
| `swap-scan` | roster, wire, settings, Sleeper trending, the volume cache, the pending list | every bench-for-wire swap vs the +20 gate; never a second QB/TE; a drop already spent in a pending claim is marked `pending_drop` and roster-watch skips it; bye holes |
| `stream-scan` | `espn team/nfl/stream` | the K and D/ST thresholds, byes two weeks out |
| `league-scan` | every closed week's lineups, every period's transactions | zeros started, bench points left, offers answered, per manager |
| `trade_scan.py --json` | rosters on `ros_rate`, the season sim | 1-for-1 and 2-for-1 proposals priced in title and bye odds |
| `season_sim.py --json` | rosters on `ros_rate`, results so far | bye/playoff/title odds for the Tuesday log |

Tests: `tests/test_fantasy_value.py` (both sides of the variance rule with
planted lineups), `tests/test_swap_scan.py` (the gate's positive control and
the second-TE rule), and the opponent-hole case in `tests/test_espncli.py`.

## The season on autopilot: `routines/`

`routines/COMMON.md` plus `lineup.md`, `tuesday.md`, and `incident.md` are
the prompts for the headless Claude runs (Fable, via the MIST Console's
routine runner; the scheduled `~/.claude/scheduled-tasks/fantasy-*` notes
only point at these files, so the prompts are versioned here). `lineup-watch
--fix` and `roster-watch` are the deterministic layer underneath. The whole
arrangement, with its standing limits, is written up in the playbook's
"Season operations" section.

### What happens when the Mac is off

- The two watchers are `StartInterval` jobs with `RunAtLoad`: they run at
  login or boot and then on their interval. Missed intervals are not replayed,
  and they do not need to be: each run reads the current state, so the first
  run after boot repairs anything still repairable. A lock that passed while
  the Mac was off is gone.
- The scheduled routines are hand-managed plists in `launchd/` (copied, never
  symlinked, into `~/Library/LaunchAgents`; the Console's routine editor does
  not own them, which is why they have no `routines-meta` entry). Each goes
  through `bin/routine-guard` (run with `/bin/bash`, not `/bin/sh`, which
  exits 126 under launchd here; weekday check: the Console's on-time wrapper
  checks time of day only, and a RunAtLoad on a Monday evening ran the
  Tuesday routine once) and then the Console's `run-routine-ontime.sh` with a
  window and retry slots: lineup 17:30-23:30 daily (fires 17:30, 19:30,
  22:05), Sunday lineup 10:35-11:50 (10:40, 11:10; after the noon window's
  10:30 inactives) and 14:30-15:20 (14:35, 14:55; the 3:05/3:25 window),
  Tuesday 18:00-23:30 (18:00, 20:00, 22:05). One completed run per day per routine; a transient
  failure leaves the day unstamped so the next slot retries; a boot inside
  the window runs it. The Mac's nightly 9:58 PM `wakepoweron` (pmset) means a
  Mac shut down all day still gets the 22:05 slots.
- The Mac has system sleep disabled (`pmset SleepDisabled 1`), so "asleep" is
  not a case; only powered off or dead battery. The one uncovered hole is a
  Mac that is off across Sunday late morning: the noon-lock repairs then wait
  for boot. `bin/sunday-poweron` plus `launchd/com.exobrain.sunday-poweron.plist`
  (a root LaunchDaemon; install commands in the script header) arm a
  Sunday 10:20 power-on each Monday; pmset holds only one repeating wake and
  the nightly one has it, so this is a weekly one-off.

### API facts that cost time to learn (2026-09-07)

- **`site.api.espn.com` answers 403 to non-browser clients** (Akamai).
  `site.web.api.espn.com` serves the same routes and does not. The fantasy
  host `lm-api-reads` is unaffected.
- **Fetching players by id needs `view=kona_playercard`.** `kona_player_info`
  returns HTTP 400 for `filterIds`, and the `/players` path ignores the
  filter entirely and returns the whole pool.
- **`sortAppliedStatTotalForScoringPeriodId` is ignored**, so `fa` pulls a
  pool sorted by ownership and sorts client-side.
- **Weekly projections exist only for the current scoring period.** A future
  `--week` shows the roster with no projections; that is ESPN, not a bug.
- **`rosterForCurrentScoringPeriod` is keyed to the requested period**, so a
  past week's matchup shows the lineup that actually played.
- **The injury report is ~9 MB** and the edge cuts it off mid-body about one
  time in three; the client retries and caches it for 30 minutes.
- **`X-Fantasy-Filter` stat trimming** (`filterStatsForTopScoringPeriodIds`)
  works and is what keeps the wire query small. Codes: `00S` season actual,
  `10S` season projection, `11SW` week projection, `01SW` week actual.
- **Activity feed semantics are unverified.** The league had no transactions
  when this was built; the message-field mapping (178/180 add, 179/239 drop,
  181/244 trade) follows the espn-api package. Check it against the first
  real move.
- **`fan.api.espn.com/apis/v2/fans/<SWID>` needs the braces percent-encoded**
  (`%7B...%7D`). Raw braces return `{"message":"fan not found"}` for *every*
  SWID including a made-up one, so the error reads like a missing account and
  is really a URL parse failure. Encoded, it returns the account's My Teams
  record, which is where the fantasy team shows up on espn.com and in the app.
  Always run the bogus-SWID control before believing a "not found" here.

## Which ESPN account owns the team

Two places on this Mac answer "which login is Chaos Legion under", and both
beat guessing from a display name (ESPN auto-assigns `ESPNFANnnnnnnnn` to
accounts that never set one, so it is not a sign of a throwaway account):

- Chrome local storage key `FAN_EMAIL_PROFILE_<SWID>` holds the email ESPN has
  on file for that SWID.
- The `ESPN-ONESITE.WEB-PROD.token` cookie is a Disney ID JWT; its middle
  segment carries `sub` (the SWID), `email`, `identity_id`, and `nbf` (when
  the identity was created). Decrypt it with the same Chrome Safe Storage key
  `ff refresh` uses. Its second base64 segment needs `=` padding.

A login that shows no leagues is almost always a different session, not a
different account: check the SWID on the device that is missing them against
the one in `espn-credentials.json`.

## Credentials (gitignored, not in the repo)

`espn-credentials.json` holds the ESPN session and is **gitignored** (see the
repo `.gitignore`, "Fantasy football" block). It is `chmod 600`. Shape:

```json
{
  "league_id": 45635023,
  "season": 2026,
  "espn_s2": "<long URL-encoded session cookie>",
  "SWID": "{GUID}",
  "team_id": 12,
  "team_name": "Chaos Legion"
}
```

`espn_s2` and `SWID` are **ESPN account session cookies**, not a scoped API key.
Treat them like a password: they authorize reads of any private league the
account can see. That is exactly why this stays local and never touches a
third-party MCP server.

### Rebuilding the credentials

The cookies were pulled from Chrome's cookie store (Alex is logged into
espn.com there). To rebuild or refresh:

- **Automatic:** `ff refresh` copies Chrome's cookie DB, decrypts the ESPN
  cookies with the "Chrome Safe Storage" key from Keychain (triggers a one-time
  macOS Keychain prompt -- click Allow), and rewrites the file. Requires being
  logged into espn.com in Chrome.
- **Manual:** in a browser logged into ESPN, DevTools -> Application -> Cookies
  -> `espn.com`, copy `espn_s2` and `SWID` into the JSON above.

ESPN cookies last roughly a year but rotate on password change or logout. When
`ff` reports auth rejected (HTTP 401/403), run `ff refresh`.

## Known league quirks

**Duplicate team: resolved 2026-08-23.** Alex's SWID briefly owned two teams here,
id 8 "Alex's Awesome Team" (the ESPN default name) and id 12 "Chaos Legion". Id 8
has since been deleted. The `team_id` pin in the credential file still resolves
to 12 and is harmless, so it stays as belt-and-braces against the default team
reappearing.

**Odd league size.** The league grew to **13 teams** on/around 2026-08-23, so
ESPN's generated schedule carries 14 slots per week and one team has no opponent
each week. In the raw `mMatchup` view that shows up as a matchup with `home` set
and `away` absent, which is a real bye and not a parsing error. Anything that
walks the schedule has to tolerate a missing side.

## Privacy

No real names anywhere in this dir or the tool output (output redacts league
members to initials). The credential file and the other managers' SWIDs are
opaque GUIDs in the gitignored file only. Nothing here is committed.
