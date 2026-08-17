# fantasy

Read-only client for Alex's ESPN fantasy league **"Roll for First Down"** (his
team: **Chaos Legion**, abbrev **LMAO**). Strategy lives in the
`/fantasy-football` skill and the vault playbook; this dir is just the data
access layer.

## Tool

`bin/ff` -- Python, stdlib + `cryptography` (already on the system python). Runs
against the ESPN Fantasy v3 read API. **Read-only by invariant**: it never sets a
lineup, makes a claim, or proposes a trade. It surfaces numbers; decisions stay
with Alex.

```
ff standings     # league table with bye (top 2) and playoff (top 6) cutlines
ff roster        # Chaos Legion's current roster
ff refresh       # re-pull ESPN cookies from Chrome (when auth expires)
ff raw --views mMatchup,mRoster   # raw API dump for building new subcommands
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

## Known league quirk

Alex's SWID owns **two** teams in this league: id 8 "Alex's Awesome Team" (the
ESPN default name) and id 12 "Chaos Legion" (the one he named). This is unusual
-- normally one account owns one team -- and is probably a mid-setup artifact of
a league still filling its 12 slots (only ~4 human accounts joined as of
2026-08-16). `team_id` is pinned to 12 so the tool always means Chaos Legion. If
the duplicate gets cleaned up, this note and the pin can go.

## Privacy

No real names anywhere in this dir or the tool output (output redacts league
members to initials). The credential file and the other managers' SWIDs are
opaque GUIDs in the gitignored file only. Nothing here is committed.
