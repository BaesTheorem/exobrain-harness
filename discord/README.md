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

## Tracked Files

| File | Purpose |
|------|---------|
| `discord-bot.sh` | Launches Claude CLI as persistent Discord bot |
| `run-discord-digest.sh` | launchd wrapper for discord-digest-fetch.py |
| `com.exobrain.discord-digest.plist` | launchd timer (runs every 4 hours) |
| `README.md` | This file |
