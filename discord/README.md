# Discord Integration

Fetches messages from a friend group Discord server for daily briefing consumption.

## Gitignored Files

### `discord-digest-fetch.py`
Python script that fetches recent messages from Discord channels via REST API. Gitignored because it contains a hardcoded username-to-real-name mapping for the friend group.

**To rebuild**: Create a Python script (stdlib only, `urllib.request`) that:
1. Reads `DISCORD_BOT_TOKEN` from `~/.claude/channels/discord/.env` (a `KEY=value` file; the same token `claude-bot/` and `discord-send.py` use). It does not read the process environment, so the plist needs no token.
2. Fetches messages from a `CHANNELS` dict mapping channel IDs to `{"name": "..."}`, paginating back `--hours N` (default 24). For the channel named `Hangouts` it also fetches recent threads.
3. Maps Discord user IDs/usernames to real names via a `USERNAME_MAP` dict (the reason the script is gitignored).
4. Writes `discord/discord-digest.json` with this shape, plus a timestamped copy to `~/My Drive/Discord/`:
   ```json
   {
     "last_attempted_fetch": "ISO-8601",
     "last_successful_fetch": "ISO-8601",
     "generated_at": "ISO-8601",
     "hours_back": 24,
     "channels": {
       "<channel_id>": {
         "name": "General",
         "message_count": 3,
         "messages": [
           {"id": "...", "author": "Real Name", "author_id": "...", "is_alex": false,
            "content": "message text", "timestamp": "ISO-8601", "attachments": 0,
            "mentions_alex": false, "reply_to": null}
         ],
         "threads": [{"id": "...", "name": "...", "messages": []}]
       }
     }
   }
   ```

### `discord-digest.json`
Fetched Discord messages (already gitignored). Contains private group conversation data.

**Required top-level fields** (read by `.claude/hooks/session-start.sh` for freshness check):
- `last_attempted_fetch`: ISO-8601 timestamp written at the start of every fetch attempt, regardless of outcome.
- `last_successful_fetch`: ISO-8601 timestamp written only after a fetch completes without error.

The hook uses `last_successful_fetch` (not file mtime) to detect stale digests -- that way a failed fetch that rewrites the file with old data still surfaces as stale. Rebuild the script to write both fields; on success update both, on failure update only `last_attempted_fetch`.

## Tracked Files

| File | Purpose |
|------|---------|
| `discord-send.py` | Post a message to a channel as MIST (outbound half of the digest fetcher) |
| `run-discord-digest.sh` | launchd wrapper for discord-digest-fetch.py |
| `com.exobrain.discord-digest.plist` | launchd timer for the digest fetcher (runs every 4 hours) |
| `README.md` | This file |

### `discord-send.py`

The digest fetcher only reads. This is the write path, used by routines that
deliver to a channel instead of a notification banner (the evening wind-down
recap and its mood question, for example).

```bash
python3 discord/discord-send.py <channel_id> "message text"
python3 discord/discord-send.py <channel_id> --file path/to/message.txt
```

REST-only, like the fetcher, so it does not compete for the single gateway
connection `claude-bot/` holds open. It reads the token from
`~/.claude/channels/discord/.env` directly rather than the environment, so it
works from a plain shell with no launchd plumbing. Input over Discord's 2000
character cap is split on paragraph boundaries and sent as consecutive messages.

## `DISCORD_BOT_TOKEN`

Every Discord script here reads the token from one file, `~/.claude/channels/discord/.env`, as a line `DISCORD_BOT_TOKEN=...`. Nothing reads it from the environment, and no plist carries it. Create the directory and file before loading the job (`mkdir -p ~/.claude/channels/discord`); the digest plist also logs into that directory (`digest-fetch.log`). If the digest comes back empty or the job exits 1 with "Token file not found", check that file first.

## Install

Copy plist into `~/Library/LaunchAgents/` as a real file, NOT a symlink (TCC blocks login-time loading of symlinks into `~/Documents/`):

```bash
cp com.exobrain.discord-digest.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.exobrain.discord-digest.plist
```
