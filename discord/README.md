# Discord Integration

Fetches messages from a friend group Discord server for daily briefing consumption, and runs a persistent Discord bot for notifications.

## Gitignored Files

### `discord-digest-fetch.py`
Python script that fetches recent messages from Discord channels via REST API. Gitignored because it contains a hardcoded username-to-real-name mapping for the friend group.

**To rebuild**: Create a Python script that:
1. Uses `urllib.request` (stdlib only, no dependencies) to call the Discord API
2. Fetches messages from configured channel IDs using a bot token from env var `DISCORD_BOT_TOKEN`
3. Maps Discord usernames to real names via a `USERNAME_MAP` dict
4. Writes output to `discord-digest.json` with structure:
   ```json
   {
     "fetched_at": "ISO-8601 timestamp",
     "channels": {
       "channel-name": [
         {
           "author": "Real Name",
           "username": "discord_handle",
           "content": "message text",
           "timestamp": "ISO-8601",
           "attachments": [],
           "mentions": []
         }
       ]
     }
   }
   ```
5. Accepts `--hours N` flag (default 24) to control lookback window
6. Configure `CHANNELS` dict mapping channel IDs to `{"name": "...", "limit": N}`

### `discord-digest.json`
Fetched Discord messages (already gitignored). Contains private group conversation data.

**Required top-level fields** (read by `.claude/hooks/session-start.sh` for freshness check):
- `last_attempted_fetch`: ISO-8601 timestamp written at the start of every fetch attempt, regardless of outcome.
- `last_successful_fetch`: ISO-8601 timestamp written only after a fetch completes without error.

The hook uses `last_successful_fetch` (not file mtime) to detect stale digests — that way a failed fetch that rewrites the file with old data still surfaces as stale. Rebuild the script to write both fields; on success update both, on failure update only `last_attempted_fetch`.

## Tracked Files

| File | Purpose |
|------|---------|
| `discord-bot.sh` | Launches Claude CLI as persistent Discord bot |
| `run-discord-digest.sh` | launchd wrapper for discord-digest-fetch.py |
| `com.exobrain.discord-bot.plist` | launchd plist for the bot daemon (RunAtLoad, KeepAlive) |
| `com.exobrain.discord-digest.plist` | launchd timer for the digest fetcher (runs every 4 hours) |
| `README.md` | This file |

## `DISCORD_BOT_TOKEN`

The two pieces use the token differently:

- **`discord-bot.sh`** (the daemon) inherits its token from the **Discord plugin's** own configuration, set up via Claude Code's `/discord:configure` skill. The plist does NOT need to inject it.
- **`discord-digest-fetch.py`** reads `DISCORD_BOT_TOKEN` from the **process environment**. For the launchd job to see it, set it in `com.exobrain.discord-digest.plist`'s `EnvironmentVariables` block:
  ```xml
  <key>EnvironmentVariables</key>
  <dict>
      <key>DISCORD_BOT_TOKEN</key>
      <string>your_bot_token_here</string>
  </dict>
  ```
  Or export it via `launchctl setenv` at login. Don't commit either form — the plist with a real token must NOT be checked in. (Currently `com.exobrain.discord-digest.plist` does not inject the token; if the digest is silently empty, this is the first thing to check.)

## Install

Copy plists into `~/Library/LaunchAgents/` as real files, NOT symlinks (TCC blocks login-time loading of symlinks into `~/Documents/`):

```bash
cp com.exobrain.discord-bot.plist ~/Library/LaunchAgents/
cp com.exobrain.discord-digest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.exobrain.discord-bot.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.discord-digest.plist
```
