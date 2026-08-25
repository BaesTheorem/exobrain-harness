# Fork notes

This is a vendored fork of [TheDigitalNinja/mcp-fitbit](https://github.com/TheDigitalNinja/mcp-fitbit)
at **v1.0.1**, with local changes that have never been upstreamed. It is the live
Fitbit MCP server for this harness: the `/health` skill, the daily briefing, the
evening winddown, and the mood scoring all read through it.

It used to live in `~/Documents/Claude Code/mcp-fitbit-main` as a loose unzipped
download with no version control, which meant the changes below existed in exactly
one place on disk and nowhere else. That is why it moved here.

## What diverges from upstream v1.0.1

Diffed against the upstream tag, not inferred:

### `src/wellness.ts` (new file, 108 lines)

Does not exist in any upstream commit. Registers four tools upstream has no
equivalent for:

- `get_hrv_by_date_range`
- `get_spo2_by_date_range`
- `get_breathing_rate_by_date_range`
- `get_temp_skin_by_date_range`

### `src/config.ts` (+4 OAuth scopes)

Adds `temperature`, `respiratory_rate`, `oxygen_saturation`, and `cardio_fitness`
to `FITBIT_OAUTH_CONFIG.SCOPES`, which is what makes the wellness endpoints
authorize at all. **Changing this list invalidates the stored token** and forces a
re-auth through the OAuth callback on `localhost:3000`.

### `src/index.ts` (2 lines)

Imports and calls `registerWellnessTools`.

### `src/auth.ts` (~123 changed lines) -- the refresh-token race fix

Fitbit refresh tokens are single-use: refreshing returns a new one and burns the
old, and the only grace is that identical retries inside a two-minute window get
the same response. Several instances of this server run at once on this machine
(one per Claude session, plus whatever the launchd routines start) and they all
boot from the same `.fitbit-token.json`. A naive refresh has them racing to spend
the same single-use token: first one wins, the losers null out their auth and stay
dead until their session restarts.

The fix re-reads the token file both before and after refreshing, and adopts
another instance's freshly rotated token instead of spending one that is already
gone. It also refreshes on a 5-minute skew *before* expiry rather than after.

Practical consequence: **never refresh the Fitbit token out of band.** Let the
server do it. Hand-refreshing from a script burns the token every other instance
is about to use.

## Layout

- `bin/fitbit-mcp` -- the registered entry point. Sources the gitignored harness
  `.env` for `FITBIT_CLIENT_ID` / `FITBIT_CLIENT_SECRET`, resolves `node`, execs
  `build/index.js`. Registered at both user scope and in the harness `.mcp.json`,
  pointing at this same launcher.
- `.fitbit-token.json` -- OAuth token, written by the server, gitignored. Resolved
  relative to the package root, so it travels with the directory.
- `build/` -- generated, gitignored. Rebuild with `npm ci && npm run build`.

## Rebuilding after a pull

```sh
npm ci && npm run build
```

The launcher exits with a clear message if `build/` is missing.

## If you ever rebase onto upstream

`auth.ts` is the only file that will fight you; the rest are additive. Upstream has
moved past v1.0.1 (v1.0.2 exists) and has no wellness module, so a straight
overwrite would silently drop four tools the health pipeline depends on.
