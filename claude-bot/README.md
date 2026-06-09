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
| 2 | `modules/fun.py` | dice, pick, spoilers, text effects, sentinel pledge |
| 3 | `modules/moderation.py`, `modules/greeting.py` | reaction roles, lockout gate, role save/restore |
| 4 | `modules/schedule.py` | reminders, recurring tasks |
| 5 | `modules/chatter.py` | Claude-powered chat persona (current Anthropic SDK, native tool-use) |

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

## Files

| File | Role |
|------|------|
| `bot.py` | entry point: client, intents, event wiring, module loader |
| `handler.py` | command registry + dispatch + permissions + cooldown |
| `config.py` | token loading + flat single-guild config |
| `db.py` | SQLite schema + helpers |
| `modules/` | feature modules, each with `setup(ctx)` |

## Privacy

Per the Exobrain repo conventions: bot **code** is tracked (generic/sharable),
but `config.toml` (guild ID, channel IDs, any name maps) and `claudebot.db`
(message/user data) are **gitignored**. Never commit real IDs or tokens.
