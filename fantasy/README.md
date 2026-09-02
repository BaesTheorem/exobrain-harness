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

## Tool

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
