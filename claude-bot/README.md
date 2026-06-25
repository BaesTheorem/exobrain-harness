# MIST (Discord bot)

A single-server Discord bot for one private server, modeled on the
open-source [~nova/Fletcher](https://git.sr.ht/~nova/fletcher) bot but
stripped of its cross-server machinery. The running bot is named **MIST**
(set via `config.toml`); "Fletcher" appears in this code only as the upstream
project the architecture is based on. See `../fletcher-replication/FLETCHER-DEEP-DIVE.md`
for the full analysis of the original.

## What it is / isn't

- **Is:** one `discord.py` 2.x gateway client, a command registry, SQLite, and
  pluggable feature modules. Runs as one process; restart to deploy.
- **Isn't:** no cross-server bridging, no sharding, no per-guild config cascade,
  no Postgres, no hot reload. All of that is Fletcher's multi-server scaffolding,
  which a single private server doesn't need.

## Status

**Phase 1 (skeleton) — runnable.** Core dispatch + `!help` / `!ping` / `!about`.
Feature phases land as additional modules:

| Phase | Module | Features |
|-------|--------|----------|
| 1 ✅ | `modules/core.py` | help, ping, about — proves dispatch |
| 2 ✅ | `modules/fun.py` | `!roll` dice, `!pick`, `!fight`, `!8ball`, `!mock` (offline) |
| 3 | `modules/moderation.py`, `modules/greeting.py` | reaction roles, lockout gate, role save/restore |
| 4 | `modules/schedule.py` | reminders, recurring tasks |
| 5 ✅ | `modules/chatter.py` | Claude-powered chat persona (runs on the `claude` CLI) |
| 6 ✅ | `modules/bridge.py` | live two-way channel **portals** (webhook bridge) |

## Setup

1. **Enable privileged intents** in the [Discord Developer Portal](https://discord.com/developers/applications)
   → your app → Bot → Privileged Gateway Intents:
   - **Message Content Intent** — required (read commands/chat)
   - **Server Members Intent** — required for Phase 3 join/leave features
   - Presence Intent — leave off
2. **Token:** already read from the shared Exobrain env file
   `~/.claude/channels/discord/.env` (`DISCORD_BOT_TOKEN`) — the same token the
   `discord/` digest fetcher uses. The two coexist: the fetcher is REST-only,
   this bot opens the single allowed gateway connection. No change needed.
3. **Config:** `cp config.example.toml config.toml` and fill in `guild_id` and
   your `admin_ids`. (`config.toml` is gitignored — it holds private IDs.)
4. **Install & run:**
   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   .venv/bin/python bot.py
   ```

## Running as a service (launchd)

For always-on operation, it runs as a LaunchAgent (`com.exobrain.claude-bot`,
`RunAtLoad` + `KeepAlive` — starts at login, restarts on crash). A copy of the
plist lives here (`com.exobrain.claude-bot.plist`); the live one is in
`~/Library/LaunchAgents/` (a real copy, not a symlink).

```bash
cp com.exobrain.claude-bot.plist ~/Library/LaunchAgents/   # edit the paths if not Alex's machine
launchctl load   ~/Library/LaunchAgents/com.exobrain.claude-bot.plist   # start / restart
launchctl unload ~/Library/LaunchAgents/com.exobrain.claude-bot.plist   # stop
```

Logs: `~/.claude/channels/discord/claude-bot.log`. Only one gateway connection
is allowed per token, so stop the launchd job before running `bot.py` by hand.

## Files

| File | Role |
|------|------|
| `bot.py` | entry point: client, intents, event wiring, module loader |
| `handler.py` | command registry + dispatch + permissions + cooldown |
| `config.py` | token loading + flat single-guild config |
| `db.py` | SQLite schema + helpers |
| `modules/` | feature modules, each with `setup(ctx)` |

## Portals (two-way channel bridges)

`modules/bridge.py` is the modern single-bot rebuild of Fletcher's webhook
bridge: a **portal** is a persistent, two-way mirror between two text channels
(optionally in different servers). Messages, edits, deletes and reactions in one
side appear in the other, posted under the original author's name and avatar.

Admin commands, as **slash commands** (gated in Discord's UI to members who can
Manage Webhooks) and as classic prefix commands:

```
/portal open  channel:#other     |   !portal #other-channel
/portal close channel:#other     |   !portal close #other-channel
/portal list                     |   !portal list
```

Slash commands are registered per-guild and synced on connect, so they appear
instantly (the bot must have been invited with the `applications.commands`
scope; if `/portal` is missing, re-invite it with that scope). `!bridge` is an
alias for the prefix form, and its channels resolve from a `#mention`, raw id,
channel name (searched across every server the bot is in), or a Discord URL. The
bot needs the **Manage Webhooks** permission in both channels.

How it stays correct (the parts naive clones drop): a DB `bridges` registry that
survives restart; a `bridge_messagemap` so edits/deletes/reactions find their
mirrored copy; loop prevention (webhook/bot messages are never relayed); and a
`bridge_pending` race buffer for edits/deletes that arrive before the original
finishes mirroring. Known limits: only human messages relay, content is capped
at 2000 chars, cross-server *custom* emoji reactions only mirror when the
destination can already use the emoji, and reaction removes are best-effort.

## Privacy

Per the Exobrain repo conventions: bot **code** is tracked (generic/sharable),
but `config.toml` (guild ID, channel IDs, any name maps) and `claudebot.db`
(message/user data) are **gitignored**. Never commit real IDs or tokens.
