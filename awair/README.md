# Awair Element — CO2 watcher + air-quality logger

Polls the Awair Element's local API every 5 minutes via launchd and fires a
macOS notification **and a Discord DM** when CO2 crosses thresholds during
active hours (default 7am–11pm). Every successful reading is also appended to
`air-log.csv`, which a nightly rollup summarizes into an **Air Quality Log**
note in the vault (CO2 + humidity averages, peaks, and time-in-range).

## Resilience

The watcher resolves `AWAIR_HOST` to an IP and caches the last-known-good IP in
`state.json`. mDNS `.local` names often fail to resolve from a launchd context
(works fine interactively), so when resolution fails it falls back to the cached
IP. This keeps the watcher from going silently blind when mDNS flakes out. Set a
DHCP reservation on the router so the cached IP stays valid long-term.

## Setup

1. Enable Local API in the Awair phone app: tap device → gear icon → Awair API
   section → toggle **Awair Local API** on.
2. Find the device on the LAN:
   ```
   dns-sd -B _http._tcp local
   ```
   Look for an `AWAIR-ELEM-XXXXXX` entry. Resolve to confirm:
   ```
   dns-sd -G v4 AWAIR-ELEM-XXXXXX.local
   ```
3. Add the hostname to `.env` at the harness root:
   ```
   AWAIR_HOST=AWAIR-ELEM-XXXXXX.local
   ```
4. (Discord) The watcher DMs Alex via the MIST bot. Two values are needed:
   - `DISCORD_NOTIFY_CHAT_ID` in the harness `.env` — the bot↔Alex DM channel id.
   - `DISCORD_BOT_TOKEN` in `~/.claude/channels/discord/.env` (shared with the
     digest fetcher). If either is missing the watcher logs a skip and still
     fires the macOS notification.
5. Load the launchd agents (real file copies, not symlinks — see
   `feedback_launchd_symlinks`):
   ```
   cp com.exobrain.awair-co2-watcher.plist ~/Library/LaunchAgents/
   cp com.exobrain.awair-rollup.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.exobrain.awair-co2-watcher.plist
   launchctl load ~/Library/LaunchAgents/com.exobrain.awair-rollup.plist
   ```

## Thresholds

Edit constants at the top of `awair-co2-watcher.py`:

| Constant            | Default | Meaning                                 |
|---------------------|---------|-----------------------------------------|
| `CO2_WARN`          | 1000    | Standard ventilation alert (ppm)        |
| `CO2_URGENT`        | 1500    | Urgent alert with Basso sound (ppm)     |
| `HYSTERESIS_MIN`    | 30      | Min minutes between same-tier alerts    |
| `ACTIVE_HOUR_START` | 7       | Earliest hour to send alerts (local)    |
| `ACTIVE_HOUR_END`   | 23      | Latest hour (exclusive)                 |

## Files

- `awair-co2-watcher.py` — the polling/alerting script; also appends each reading to `air-log.csv`
- `awair-rollup.py` — nightly summarizer → `Areas/Health & Fitness/Air Quality Log.md` (rewrites only the `AIR:AUTO` block)
- `awair-oauth.py` — one-time OAuth login for the Awair *cloud* API (only needed for historical backfill; the local poller needs no token). Reads `AWAIR_CLIENT_ID`, `AWAIR_CLIENT_SECRET`, and optional `AWAIR_REDIRECT_URI` (default `http://localhost:8128/callback`) from the harness `.env`, then writes back `AWAIR_ACCESS_TOKEN` plus `AWAIR_REFRESH_TOKEN` / `AWAIR_TOKEN_EXPIRES_IN` when the server returns them
- `com.exobrain.awair-co2-watcher.plist` — 5-min poller
- `com.exobrain.awair-rollup.plist` — nightly rollup (23:55) + RunAtLoad
- `state.json` — last-notified timestamps + cached `last_ip` (gitignored)
- `air-log.csv` — per-reading time series, source of truth for the rollup (gitignored: reveals presence patterns)
- Logs: `~/.claude/channels/awair/co2-watcher.log`, `rollup.std{out,err}.log`
