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

### `src/index.ts` (2 lines, plus the headless guard)

Imports and calls `registerWellnessTools`.

Also gates the browser OAuth flow behind `FITBIT_NO_BROWSER_AUTH`. Upstream starts
that flow whenever it boots without a usable token, which is right for a desktop
client and wrong for anything unattended: a scheduled job would pop a Fitbit
consent page in front of whatever Alex is doing, and nobody is there to finish it.

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

A second bug in the same area, fixed 2026-09-10: a failed refresh set both
`accessToken` and `tokenData` to null, and `getAccessToken()` then short-circuited
on that null forever without ever re-reading the file. One lost race left the
instance dark until its whole Claude session restarted, while a sibling wrote a
perfectly good token to disk seconds later. That is the "Fitbit was dark all
morning and fine by the evening" shape in the digests. It now re-reads the token
file before giving up, throttled to once a minute so a genuinely dead chain is not
a disk read per tool call. `src/auth.test.ts` covers it; that test fails against
the old code with `expected null to be 'access-2'`.

## Keeping the token renewed unattended

Everything above renews the token on *use*. Two things it cannot do: renew a token
nothing asks for, and clear a genuinely broken refresh chain, since only Fitbit's
browser consent screen can do that.

- `scripts/token-check.mjs` -- calls the very same `getAccessToken()` the server
  calls, in a process reading the same token file, then fetches the profile. Not an
  out-of-band refresh: the race-safe path applies unchanged. Healthy runs are
  silent; a broken chain fires a notification whose button runs `bin/fitbit-reauth`.
  Exit 0 healthy, 1 re-auth needed, 2 inconclusive (a network blip is never
  reported as a dead token).
- Inconclusive runs are counted in `.fitbit-check-state.json` (gitignored). One is
  a blip and stays silent; **three in a row escalates**, because twelve-plus hours
  of never confirming the token is long enough for a broken chain to be hiding
  behind an outage. That banner offers the log first, not re-auth: inconclusive
  means unknown, not broken. It repeats at most once a day, and any healthy run
  clears the streak and the escalation together.
- `bin/fitbit-reauth` -- runs the consent flow on its own, without starting an MCP
  server, so re-authorizing does not require a Claude session.
- `bin/fitbit-token-check` -- manual wrapper around the check.
- `com.exobrain.fitbit-token.plist` -- runs the check every six hours against an
  eight-hour token.

**The plist runs `node` directly, with no shell wrapper, and it must stay that
way.** A bash script that execs Homebrew's node is denied by TCC's `~/Documents`
gate: node dies with `EPERM` opening `build/index.js` before it runs a line, while
the identical command works from a terminal. Verified 2026-09-10 by bisecting a job
that failed only under launchd. This is why the wait-for-network gate lives inside
`token-check.mjs` instead of in a wrapper script.

## Layout

- `bin/fitbit-mcp` -- the registered entry point. Sources the gitignored harness
  `.env` for `FITBIT_CLIENT_ID` / `FITBIT_CLIENT_SECRET`, resolves `node`, execs
  `build/index.js`. Registered at both user scope and in the harness `.mcp.json`,
  pointing at this same launcher.
- `.fitbit-token.json` -- OAuth token, written by the server, gitignored. Resolved
  relative to the package root, so it travels with the directory.
- `build/` -- generated, gitignored. Rebuild with `npm ci && npm run build`.
- `scripts/` -- the unattended token-keepalive and re-auth entry points, described
  above. Both import from `build/`, so they need the build too.

## Rebuilding after a pull

```sh
npm ci && npm run build
```

The launcher exits with a clear message if `build/` is missing.

## If you ever rebase onto upstream

`auth.ts` is the only file that will fight you; the rest are additive. Upstream has
moved past v1.0.1 (v1.0.2 exists) and has no wellness module, so a straight
overwrite would silently drop four tools the health pipeline depends on.
