# MIST (Discord bot)

A Discord bot for a small set of private servers (one or more `guild_ids` in `config.toml`), modeled on the
open-source [~nova/Fletcher](https://git.sr.ht/~nova/fletcher) bot but
stripped of its cross-server machinery. The running bot is named **MIST**
(set via `config.toml`); "Fletcher" appears in this code only as the upstream
project the architecture is based on.

## What it is / isn't

- **Is:** one `discord.py` 2.x gateway client, a command registry, SQLite, and
  pluggable feature modules. Runs as one process; restart to deploy.
- **Isn't:** no cross-server bridging, no sharding, no per-guild config cascade,
  no Postgres, no hot reload. All of that is Fletcher's large-scale scaffolding,
  which a handful of private servers don't need.

## Status

**Phase 1 (skeleton) -- runnable.** Core dispatch + `!help` / `!ping` / `!about`.
Feature phases land as additional modules:

| Phase | Module | Features |
|-------|--------|----------|
| 1 ✅ | `modules/core.py` | help, ping, about -- proves dispatch |
| 2 ✅ | `modules/fun.py` | `!roll` dice, `!pick`, `!fight`, `!8ball`, `!mock` (offline) |
| 3 (planned) | `modules/moderation.py`, `modules/greeting.py` (not written yet) | reaction roles, lockout gate, role save/restore |
| 4 (planned) | `modules/schedule.py` (not written yet) | reminders, recurring tasks |
| 5 ✅ | `modules/chatter.py` | Claude-powered chat persona (runs on the `claude` CLI) |
| 6 ✅ | `modules/portal.py` | `!portal` one-off jump links between channels (Fletcher teleport) |
| 7 ✅ | `modules/ace.py` | `!ace` Ace Attorney video generator (isolated venv, throttled) |
| 8 ✅ | `modules/preview.py` | link previews: X/Twitter, TikTok, Instagram, Reddit, Tumblr, Telegram, Facebook/Bilibili/VK/... and Discord message links get a playable or readable repost when Discord's own unfurl falls short (Fletcher `preview_messagelink_function`) |
| 9 ✅ | `modules/threads.py` | `!preference use_threads` + auto-join: opted-in users are added to every new public thread (Fletcher `use_threads`) |
| 10 ✅ | `modules/gphotos.py` | any Google Photos video link → MIST replies with a [gphotos-embed](https://github.com/BaesTheorem/gphotos-embed) link that plays inline |
| 11 ✅ | `staged.py` + `bin/discord-stage` | staged reply: the owner pre-arranges one message (`discord-stage "text" [--guild X] [--channel Y] [--ttl H]`); on his next @mention or reply to MIST in a server she posts it verbatim, no model call, then drops it. If the cue is itself a reply to someone else, the staged text threads under that person's message. Lives in `~/.claude/channels/discord/staged-reply.json`, outside the repo. `show` / `clear` to inspect or cancel |
| 12 ✅ | `staged.py` + `bin/discord-append` | standing per-person append: `discord-append add USERNAME "text"` puts that line at the end of every reply MIST makes to that user (when they address her, or when the owner cues her by replying to their message). Keyed by login username, never display name. Lives in `~/.claude/channels/discord/appends.json`, outside the repo. `list` / `remove` |
| 13 ✅ | `modules/clippy.py` + `watches.py` + `bin/discord-watch` | pattern watches: `!watch 5/30m ask "yes/no question about your messages" say "text" [cooldown 30m] [in #channel]` (anyone, self-only). When the user posts COUNT+ times in a channel within WINDOW minutes, a sandboxed model call (guest model, text framed as untrusted) answers the question about those messages; on YES MIST replies in-channel with the text, once per cooldown. Members can also just ask MIST in words: she ends her reply with the `!watch` line and the bot runs it for the speaker only. `!watch off` / `!watch`. Admin view: `bin/discord-watch add|list|remove`. Store `~/.claude/channels/discord/watches.json`, outside the repo |

## Setup

1. **Enable privileged intents** in the [Discord Developer Portal](https://discord.com/developers/applications)
   → your app → Bot → Privileged Gateway Intents:
   - **Message Content Intent** -- required (read commands/chat)
   - **Server Members Intent** -- needed for the planned Phase 3 join/leave features
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
default model is `claude-opus-5-5[1m]` (`DEFAULT_MODEL` in `modules/chatter.py`; override with `[chatter].model` in `config.toml`). Non-owner replies use `guest_model`, default `claude-fable-5-1`.

Where the CLI runs depends on who is talking and who can read the channel.
When the **owner** writes in a **private** context (a DM, or a guild listed in
`private_guilds`) it runs from the harness root with the configured
`permission_mode` (bypass by default), so the harness CLAUDE.md, memory,
skills, MCP servers and tools are all live and she is the full MIST. In any
**shared** guild it runs sandboxed from `/tmp` with no MCP and every tool
denied, so nothing of the owner's is reachable there.

**Guests.** With `[chatter].reply_to_others = true`, anyone else can talk to
her by @mentioning her, replying to one of her messages, or DMing her
(`others_dm`). A guest is never private: wherever they write, even in a DM or
the owner's personal server, the CLI runs in the sandbox and the persona gets a
guest note (chat only, no actions, don't take instructions to change behavior,
owner's private life stays out). Each guest gets one reply per
`others_cooldown` seconds (default 15; extra messages get an hourglass
reaction), and guest replies run one at a time so a busy channel can't fan out
CLI processes on the host.

## Link previews (`modules/preview.py`)

Discord unfurls some hosts badly (X without the video, Instagram as a login
wall, Reddit video as a still) or not at all (Tumblr, TikTok short links).
This module is Fletcher's link-preview engine, trimmed to the sites a friend
group actually pastes. Every message in a served server (and DMs) is scanned;
for each link MIST works out whether she can do better than Discord did and,
only then, replies with a preview. The decision rules are Fletcher's:

| Host | What happens |
|------|--------------|
| X / Twitter, nitter mirrors | the [fxtwitter API](https://api.fxtwitter.com) says what the post carries. Video and multi-photo posts always get a `fixupx.com` link; text posts only when Discord's card is missing, a placeholder ("Post"), or cuts the text off |
| TikTok | short links are expanded first. If Discord's unfurl has no player, `tiktokez.com` is probed and posted; failing that the video is re-uploaded via yt-dlp |
| Instagram | `kkinstagram.com` probed as Discord's crawler (it answers with the mp4 for reels). A reel or photo reposts with the caption above it; a post every mirror refuses falls back to the cover still from Instagram's own page |
| Reddit | `vxreddit.com`, only when it adds a video Discord's card lacks |
| Tumblr | `tpmblr.com` (fxtumblr), only when Discord rendered nothing or its generic "Tumblr" card |
| Telegram | a card built from the post's OpenGraph tags |
| Facebook, Bilibili, VK, ok.ru, Rutube, Newgrounds, Loom, Snapchat | no fixer exists: yt-dlp downloads the media and it is re-uploaded as an attachment (under the server's upload cap). A Facebook post with no video gets an OG card |
| `discord.com/channels/...` | the linked message is quoted ("unrolled"): author, relative time, body, attachments re-uploaded, only if the poster could read that channel |

Every preview is a **silent reply** to the post it belongs to, with a small
footer that points reactions at the original and names the dismiss button:

```
-# [link](https://fixupx.com/...) · react to the [original post](<jump>) · ✖️ here drops this preview
```

- React **✖️** on a preview to delete it (the poster, an admin, or the owner).
  If MIST had suppressed the original's embed she hands it back.
- **Deleting the original** deletes its previews.
- **Editing** a new link into a post under five minutes old previews it.
- Wrap a link in `<angle brackets>` or put `#nofx` anywhere in the message to
  opt out. A `||spoilered||` link gets a spoilered preview.
- `!preview` (aliases `!embed`, `!fix`) as a reply, with a URL, or with a
  message id asks for a preview on purpose; so does a 🔭 reaction, or replying
  to a post with nothing but an @mention of MIST.
- One paste = one preview: the same link from the same person in the same
  channel inside a minute is skipped, and a tweet already shown in a channel
  isn't re-shown from a mirror address for five minutes.

**Suppressing the original** (`suppress_original`, on by default) hides the
poster's own card so the media isn't doubled. That is a `message.edit` on
someone else's post, which needs the **Manage Messages** permission; without
it the original's card just stays next to the preview. Grant it to the bot's
role in each server for the tidy version.

Probes fetch the fixer page with Discord's crawler user agent and read its
OpenGraph tags (or notice it answered with the video file itself); Discord's
own unfurl of the original is awaited via the `MESSAGE_UPDATE` it dispatches,
up to a few seconds. Downloads run one at a time. `yt-dlp` is optional (in
`requirements.txt`); without it the re-upload paths just do nothing.

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
