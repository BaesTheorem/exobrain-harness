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
espn matchup [--week N]    # both lineups, projected margin, and the variance rule
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
