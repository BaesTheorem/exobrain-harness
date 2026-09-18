# MIST (Discord bot)

A single-server Discord bot for one private server, modeled on the
open-source [~nova/Fletcher](https://git.sr.ht/~nova/fletcher) bot but
stripped of its cross-server machinery. The running bot is named **MIST**
(set via `config.toml`); "Fletcher" appears in this code only as the upstream
project the architecture is based on.

## What it is / isn't

- **Is:** one `discord.py` 2.x gateway client, a command registry, SQLite, and
  pluggable feature modules. Runs as one process; restart to deploy.
- **Isn't:** no cross-server bridging, no sharding, no per-guild config cascade,
  no Postgres, no hot reload. All of that is Fletcher's multi-server scaffolding,
  which a single private server doesn't need.

## Status

**Phase 1 (skeleton) -- runnable.** Core dispatch + `!help` / `!ping` / `!about`.
Feature phases land as additional modules:

| Phase | Module | Features |
|-------|--------|----------|
| 1 ✅ | `modules/core.py` | help, ping, about -- proves dispatch |
| 2 ✅ | `modules/fun.py` | `!roll` dice, `!pick`, `!fight`, `!8ball`, `!mock` (offline) |
| 3 | `modules/moderation.py`, `modules/greeting.py` | reaction roles, lockout gate, role save/restore |
| 4 | `modules/schedule.py` | reminders, recurring tasks |
| 5 ✅ | `modules/chatter.py` | Claude-powered chat persona (runs on the `claude` CLI) |
| 6 ✅ | `modules/portal.py` | `!portal` one-off jump links between channels (Fletcher teleport) |
| 7 ✅ | `modules/ace.py` | `!ace` Ace Attorney video generator (isolated venv, throttled) |
| 8 ✅ | `modules/instagram.py` | reply to an Instagram link + @mention MIST → reel embeds as inline video (Fletcher kkinstagram fix) |
| 9 ✅ | `modules/threads.py` | `!preference use_threads` + auto-join: opted-in users are added to every new public thread (Fletcher `use_threads`) |

## Setup

1. **Enable privileged intents** in the [Discord Developer Portal](https://discord.com/developers/applications)
   → your app → Bot → Privileged Gateway Intents:
   - **Message Content Intent** -- required (read commands/chat)
   - **Server Members Intent** -- required for Phase 3 join/leave features
   - Presence Intent -- leave off
2. **Token:** already read from the shared Exobrain env file
   `~/.claude/channels/discord/.env` (`DISCORD_BOT_TOKEN`) -- the same token the
   `discord/` digest fetcher uses. The two coexist: the fetcher is REST-only,
   this bot opens the single allowed gateway connection. No change needed.
3. **Config:** `cp config.example.toml config.toml` and fill in `guild_id` and
   your `admin_ids`. (`config.toml` is gitignored -- it holds private IDs.)
4. **Install & run:**
   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   .venv/bin/python bot.py
   ```

## Running as a service (launchd)

For always-on operation, it runs as a LaunchAgent (`com.exobrain.claude-bot`,
`RunAtLoad` + `KeepAlive` -- starts at login, restarts on crash). A copy of the
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

## Chatter: model and thinking depth

`modules/chatter.py` runs replies through the `claude` CLI on the owner's
subscription. The model and effort level are switchable at runtime and persist
in the SQLite `settings` table, so a restart keeps the last choice:

```
!model                 show current model + effort, and what's selectable
!model opus            switch (aliases fable/opus/sonnet/haiku, or a full id
                       like claude-opus-5; add [1m] for the 1M-context variant)
!effort xhigh          thinking depth: low | medium | high | xhigh | max | default
/model  /effort        the same as slash commands, with a picker
```

Owner only (gated on Discord username, not `admin_ids`), and the prefix forms
work in a DM too. The selectable model list is discovered from the installed
`claude` binary (`models.py`), so a CLI update is all a new model needs. The
default model is `claude-opus-5` (`[chatter].model` in `config.toml`).

Where the CLI runs depends on who can read the channel. In a **private**
context (a DM, or a guild listed in `private_guilds`) it runs from the harness
root with the configured `permission_mode` (bypass by default), so the harness
CLAUDE.md, memory, skills, MCP servers and tools are all live and she is the
full MIST. In any **shared** guild it runs sandboxed from `/tmp` with no MCP
and every tool denied, so nothing of the owner's is reachable there.

## Portals (one-off jump links)

`modules/portal.py` mirrors Fletcher's `!teleport`/`!portal`: a **portal** is
NOT a channel mirror, it's a pair of cross-linked jump messages. You drop one to
carry a conversation into another channel without losing stride. It posts a
"jump over" link in the current channel pointing at the other, and a "jump back"
link in the other pointing home. Clicking either jumps you there. Nothing is
relayed or bridged, so there's no state and nothing to close, just delete the
messages if you want them gone.

Anyone can use it (no admin), as a slash command or a prefix command:

```
/portal channel:#other     |   !portal #other   (aliases: !teleport, !tp)
```

Channels resolve from a `#mention`, raw id, channel name (searched across every
server the bot is in), or a Discord URL, and may cross servers. The bot only
needs **Send Messages** + **Embed Links** in both channels. Slash commands sync
per-guild on connect (needs the `applications.commands` invite scope).

> An earlier version implemented portals as a persistent webhook *mirror*
> (Fletcher's `!bridge`). That was the wrong feature and was removed; the
> `bridges` / `bridge_messagemap` / `bridge_pending` tables are dropped on boot.

## Thread auto-join (`!preference use_threads`)

Discord only shows a thread in your sidebar once you're a member of it, so new
threads in a busy server are easy to miss. `modules/threads.py` ports Fletcher's
`use_threads` preference: opt in once and MIST adds you to every new public
thread as it appears.

```
!preference use_threads true              every new thread in this server
!preference use_threads #general, Events  only threads under those channels/categories
!preference use_threads false             opt out
!preference use_threads null              delete the row
!preference use_threads                   show the current value
```

Also `/preference key:use_threads value:true`. From a DM, `!preference
<guild_id>:use_threads true` targets one server; a bare DM setting is global
and a per-server row overrides it. Category and channel names are checked
against the server, with a "did you mean" on typos.

**On behalf of someone else** (owner or admin only):
`!preference @user use_threads true`, or `/preference ... user:@user`.

How the summon works: `thread.add_user()` posts a visible "X was added" system
message per person, so instead MIST sends a silent placeholder in the thread,
edits the user mentions into it (edits never notify, and mentions add members),
then deletes it. Membership survives the delete. Each thread is summoned once
(`thread_summoned` table), threads older than five minutes are skipped, private
threads are never touched, and users who can't read the parent channel are
never added. `[threads].default_on` lists user IDs treated as `true` unless
they opt out (Fletcher gives this to its mod list).

## Ace Attorney video generator (`!ace`)

`modules/ace.py` renders the last few messages as a Phoenix-Wright courtroom
video (`!ace [count]`, default 6 messages, or `!objection`). It uses the
[`objection_engine`](https://pypi.org/project/objection_engine/) library, which
pins old, heavy deps (Pillow 9.5, moviepy, spaCy) that can't share the bot's
main venv, so it lives in a **separate `.ace-venv`** that the bot invokes as a
subprocess (`ace_render.py`) off the gateway loop.

Because each render is a real CPU+ffmpeg load on the host, it's guarded: **one
render at a time**, and a global throttle of **5 renders per 10 minutes** that
trips a **30-minute lockout** so it can't be used to spam-load the machine. The
module disables itself cleanly if `.ace-venv` isn't built.

Building the renderer venv (Apple Silicon; needs `ffmpeg` on PATH and a
Python 3.12, since `objection_engine` won't build on 3.14):

```bash
python3.12 -m venv .ace-venv
.ace-venv/bin/pip install objection_engine
# objection_engine pins Pillow 9.5.0, whose cached wheel can be the wrong arch;
# rebuild it natively, and pin setuptools so google-cloud-translate keeps pkg_resources:
ARCHFLAGS="-arch arm64" .ace-venv/bin/pip install --no-cache-dir --force-reinstall --no-binary :all: "Pillow==9.5.0"
.ace-venv/bin/pip install "setuptools<80"
```

First render downloads the sprite/music assets into the venv (one-time, ~80s).
`.ace-venv` is gitignored.

## Privacy

Per the Exobrain repo conventions: bot **code** is tracked (generic/sharable),
but `config.toml` (guild ID, channel IDs, any name maps) and `claudebot.db`
(message/user data) are **gitignored**. Never commit real IDs or tokens.
