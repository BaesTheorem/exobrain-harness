# Fletcher Discord Bot — Deep-Dive for Replication

> Research artifact. Target: **~nova/Fletcher** (Noble Jury Software / Novalinium), AGPL-3.0.
> Source: `https://git.sr.ht/~nova/fletcher` · Hosted: `https://fletcher.fun` · Docs: `https://man.sr.ht/~nova/fletcher`
> Analyzed at commit `af13134`. This is a **partial source release** (core modules only; no SystemD units, DB schema files, or test harness shipped — but the schema is recoverable, see below).

---

## 0. TL;DR — What Fletcher actually is

Fletcher brands itself a "Discord moderation bot," but the codebase is a **44,000-line monolithic async Python bot** that is really three things stacked together:

1. **A cross-channel / cross-server message *bridge* and *teleport* engine** (its actual differentiator — most "Fletcher" clones are really clones of *this*).
2. **A moderation + member-management + self-service-roles toolkit** (`janissary`, `greeting`, `sentinel`).
3. **A giant grab-bag of ~150 fun/utility commands** (`swag`, `text_manipulators`) plus an **LLM chat persona** (`chatter`) and protocol bridges (Matrix, IRC, Minecraft).

It runs as a single process under **systemd**, reloads via **SIGHUP** (hot module reload, no gateway reconnect), is backed by **PostgreSQL**, and is built on a **fork of pycord** (discord.py-family). Config is **INI files** (global `.fletcherrc` + one file per guild), not a database.

**If you want to replicate "Fletcher," decide which of the three you mean.** The bridge engine is the hard, valuable, ~6,000-line core. Everything else is breadth, not depth.

---

## 1. Top-level architecture

### Process & runtime
- **Entry point:** `main.py`. Uses `uvloop` event loop policy, `discord.AutoShardedClient` with `Intents.all()` minus presences, `chunk_guilds_at_startup=False` (lazy member loading + a custom disk member cache).
- **Concurrency:** fully async (`asyncio`). Per-resource rate limiting via `aiolimiter.AsyncLimiter`.
- **Observability:** `sentry_sdk` for error reporting; logs to **systemd journal** via `cysystemd`; **systemd watchdog** pinged every 15s so a frozen loop triggers a restart.
- **Custom gateway resume:** `gateway_resume.py` implements **cross-process RESUME** — it persists the gateway session so a restarted process can RESUME instead of re-IDENTIFY, skipping the expensive READY/guild-cache rebuild. On RESUME, `on_ready` never fires, so `on_resumed` re-runs init and dispatches synthetic `on_guild_join` for guilds added during downtime.
- **Member cache:** `_save_member_cache()` / `_restore_member_cache()` serialize all guild members to `/pub/lin/fletcher/.member_cache.json` for fast restart, then `_background_rechunk()` refreshes from the gateway 5 min after startup.

### The reload model (central to the whole design)
`reload_function()` in `main.py` is the heart of operations:
- Triggered on `on_ready` AND on **SIGHUP** (`utils/reload-fletcher` wrapper sends `systemctl reload`).
- Reconnects Postgres (both **psycopg2 sync** `conn` and **psycopg3 async** `aconn`), then `importlib.reload()`s every feature module in a fixed order and calls each module's `autounload(ch)` then `autoload(ch)`.
- Each module gets globals **injected** at reload time: `module.ch`, `module.client`, `module.config`, `module.conn`, `module.aconn`, `module.sid`, `module.versioninfo`. **This is the dependency-injection mechanism** — modules don't import each other's state, they receive it.
- `commandhandler` is loaded **twice** to bootstrap (it must exist before other modules register commands against it, then re-finalized after).
- After reload, `webhook_sync_registry` (the bridge table) is rebuilt — first from a disk cache (`load_webhooks_from_cache`), falling back to a full Discord API walk (`load_webhooks`, up to 600s for ~120 guilds).
- **`webhooks_loaded` flag** gates all bridge work; until it's true, bridged messages busy-wait. A silent reload failure leaves it `False` and stalls all bridging — the #1 operational gotcha.

### Module load order (from `reload_function`)
`commandhandler` → `versionutils` → `text_manipulators` → `schedule` → `greeting` → `sentinel` → `messagefuncs` → `chatter` → `mathemagical` → `janissary` → `minedcraft` → `swag` → `pinterest` → `googlephotos` → `danbooru` → `sheetsjournal` → `github` → `chronos` → `matrixbridge` → (re-finalize `commandhandler`).

### File inventory (by size = by importance)
| File | Lines | Role |
|---|---|---|
| `commandhandler.py` | 8,310 | **Command dispatch + bridge engine** (the core) |
| `swag.py` | 7,400 | ~80 fun/utility commands |
| `janissary.py` | 5,319 | Moderation, access control, self-service roles/channels, chanlog→Notion |
| `text_manipulators.py` | 4,937 | Spoilers (ROT13/memfrob), image scramble, ~20 text effects |
| `messagefuncs.py` | 3,439 | Teleport, message preview/unfurl, bookmark, `sendWrappedMessage` |
| `chatter.py` | 2,450 | Claude-powered LLM chat persona in threads |
| `schedule.py` | 1,776 | Reminders, recurring tasks, RSS/feed polling, outage alerts |
| `matrixbridge.py` | 1,743 | Discord↔Matrix bridge (mautrix) |
| `greeting.py` | 1,229 | Member join/leave: role save/restore, lockout gate, randomize |
| `main.py` | 1,212 | Event loop, reload, Discord event handlers |
| `gateway_resume.py` | 633 | Cross-process gateway RESUME |
| `sheetsjournal.py` | 638 | Discord→Google Sheets logging bridge |
| `load_config.py` | 555 | Hierarchical INI config system |
| `minedcraft.py` | 485 | Linode-provisioned Minecraft servers + RCON |
| `sentinel.py` | 373 | "Collective action" pledge/defect mechanic |
| `chronos.py` | 282 | Time parsing + timezone resolution |
| smaller | — | `github`, `googlephotos`, `mathemagical`, `danbooru`, `derpibooru`, `pinterest`, `netcode`, `config_watcher`, `versionutils`, `exceptions` |

---

## 2. The CommandHandler (commandhandler.py)

### Command model
- **`CommandHandler`** class is a singleton (`ch`) holding `self.commands` — a **list of plain dicts** (not objects, for hot-reload compatibility).
- Modules register via **`ch.add_command({...})`** at their module scope inside `autoload(ch)`. There is **no decorator/auto-discovery**; registration is explicit and imperative.
- A command dict schema:
  ```python
  {
    "trigger": ("!foo", "!bar"),     # tuple of trigger strings or emoji
    "function": handler,             # (message, client, args) -> response | async
    "async": True,
    "args_num": 1, "args_min": 0,    # arg-count gating
    "args_name": ["query"],
    "description": "...",
    "admin": False,                  # permission level (see below)
    "hidden": False, "long_run": False,
    "rate_limit": (1, 30),           # AsyncLimiter(count, seconds)
    "editable": True,                # response edits when source edits
    "whitelist_guild": [...], "blacklist_guild": [...], "blacklist_channel": [...],
    "slash_command": False, "message_command": False,  # optional Discord app-command sync
  }
  ```
- Separate handler registries beyond text commands: `join_handlers`, `remove_handlers`, `reload_handlers`, `message_reaction_handlers` (per-message), `message_reply_handlers`, plus reaction-remove handlers. Modules register into these for event-driven behavior.

### Dispatch lifecycle (`command_handler` → `get_command` → `run_command`)
1. **Prefix normalization:** unicode-whitespace normalize; per-guild prefix substitution; bot @mention → `!`; collapse `!!` → `!`; "Oh Fletcher …" natural-language → `!help` via regex.
2. **Pre-hooks:** regex content filters (`greeting.regex_filter`), reply-handler dispatch if the message is a reply, optional sticker-killing.
3. **Command discovery (`get_command`):** filter to `accessible_commands()` for this user, then match `trigger` via one of four modes — `keyword_trie` (prefix match, the primary mode), `exact`, `keyword` (substring), `description`. Gate by `args_min ≤ argc ≤ args_max`.
4. **Execution (`run_command`):** permission/blacklist/stranger-role checks → per-command `AsyncLimiter` → invoke handler → auto-wrap sync responses → if `editable`, persist source→response mapping in `command_responses` for later edit propagation.
5. **Post-hooks:** hotword scanning (`_check_hotwords`), post-command regex filters.

### Permissions model (`is_admin`, `allowCommand`, `accessible_commands`)
- Three tiers from `is_admin()`: **global** (user id == `discord.globalAdmin`), **server** (global OR `manage_webhooks` in guild), **channel** (server OR `manage_webhooks` in channel).
- `command["admin"]` accepts: `False` (everyone), `True`/`"server"`/`"channel"` (any admin at that scope), `"global"`, or scoped allowlists `"server:id1,id2"` / `"channel:id1,id2"`.
- **`stranger_role`**: a guild role that, if held, returns zero accessible commands (newcomer gate).
- **`!sudo`** (in `janissary`): temporarily grants a configured `wheel-role`, auto-dropped after the first audit-log entry or 10 minutes — a Unix-sudo analogue.

---

## 3. The bridge / teleport engine (the actual core)

This is the part worth replicating carefully. Two distinct features share vocabulary:

### 3a. Teleport (`messagefuncs.teleport_function`) — *ephemeral, manual*
- `!teleport <channel>` (aliases `!portal`, `!tp`). Posts a "portal" message in each of two channels, each linking to the other via a Discord message URL. **No DB, no ongoing relay** — just a pretty bidirectional hyperlink pair, optionally rendered as embeds. Channel resolution supports names, `guild:channel`, `<#id>`, and full Discord URLs (incl. archived threads via `xchannel_async`).

### 3b. Bridging (`commandhandler.bridge_message` + `janissary` `!bridge`) — *persistent, webhook-based*
This is the real engine. **One- or two-way live message mirroring between channels, across servers.**

**Setup:** `!bridge <source>` (in `janissary`) creates a **Discord webhook** on the destination channel whose **name encodes the source**: `"{botNavel} ({fromGuild}:{fromChannel})"` (or a 3-component form `(...:{sourceThreadId})` to pin a thread). On reload, `load_webhooks()` walks every guild's webhooks, parses these names, and builds **`webhook_sync_registry`**: `{"{fromGuild.name}:{fromChannel.id}"}` → **`Bridge`** instance. Two-way = a webhook in each direction.

**`Bridge` dataclass:** `channels[]` (destinations), `webhooks[]`, `threads[]` (pinned destination threads), `source_threads[]` (source-thread filters), plus a per-bridge `AsyncLimiter(1,10)`.

**Relay path (`bridge_message`, ~800 lines):**
1. Skip messages from bridge webhooks (loop prevention).
2. Resolve which bridges apply (static thread config + dynamic `threads` table lookups + sourceless-bridge filtering).
3. Transform content: unwrap forwarded messages (`message_snapshots`), re-resolve user/channel mentions to destination equivalents, spoiler-wrap on NSFW→SFW crossings, resize oversized images with PIL.
4. Send via webhook (`messagefuncs.sendWrappedMessage`) with the original author's name/avatar (member fetch backed by a NotFound backoff cache).
5. Persist `messagemap (fromguild, fromchannel, frommessage, toguild, tochannel, tomessage, reactions[])` — the routing table that makes edits/deletes/reactions propagate.

**Edit / delete / reaction propagation:** `edit_handler`, `deletion_handler`, `reaction_handler` look up `messagemap` and apply the same change to the mirrored copy. **Custom-emoji reactions** are mapped across guilds by MD5-hashing the emoji image and caching/recreating it on the destination.

**The race condition that dominates the design — `bridge_pending`:** an edit or delete can arrive *before* the original message has been written to `messagemap`. The handlers then write a **tombstone** into `bridge_pending (fromguild, fromchannel, frommessage, action, payload jsonb, created_at)`; `bridge_message` consumes pending tombstones right after it inserts the messagemap row. A background sweep (`BRIDGE_PENDING_TTL_SEC = 300`) deletes stale tombstones. **Any replication that skips this will silently drop fast edits/deletes.**

> **Replication priority order for the bridge:** (1) webhook-name-encoded registry + reload rebuild, (2) `messagemap` for edit/delete/react, (3) loop prevention, (4) `bridge_pending` race handling, (5) thread routing, (6) cross-guild custom-emoji remap. Items 4–6 are where naive clones break.

---

## 4. Config system (load_config.py) — the seam everything uses

- **INI-based, file-backed (no DB).** A global `.fletcherrc` plus one numerically-named file per guild in `rc-path` (`.fletcher.d/<guild_id>`). Guild files have sections; a channel-specific section is `[<channel_id>]`, and `SECTION_x_key` syntax nests subsections.
- **`config.get(key=, section=, guild=, channel=, default=)`** is *the* universal accessor, called everywhere. It implements a **scope cascade**: channel → category → guild → channel_defaults → guild_defaults → hardcoded defaults. `guild`/`channel` accept Discord objects or ids and are normalized.
- **Value normalization:** booleans (`on/true/yes`), numbers, and any key containing `"list"` is auto-split into an array.
- **Hot-reload of config:** `config_watcher.py` watches the rc files and calls back into `reparse_guild_file()` + re-registers guild role-message handlers, so per-guild config edits apply **without** a full SIGHUP reload. `write_guild_key()` does atomic text-preserving edits so the bot can persist settings itself.

**Replication note:** this hierarchical, object-aware config accessor is small but load-bearing — replicate its scope-cascade semantics faithfully or per-channel overrides silently won't resolve. A modern rebuild would likely back this with a DB table keyed by `(guild, channel, section, key)` plus the same cascade.

---

## 5. PostgreSQL schema (recovered from main.py header + module queries)

The release omits schema files, but `main.py` embeds `\d` dumps. Core tables:

```
attributions(added, author_id, from_message, from_channel, from_guild, message, channel, guild)
    -- maps a bridged/relayed message back to its real author

messagemap(fromguild, toguild, fromchannel, tochannel, frommessage, tomessage, reactions bigint[])
    -- bridge routing table; INDEX (fromguild, fromchannel, frommessage)

bridge_pending(fromguild, fromchannel, frommessage, action, payload jsonb, created_at)
    -- PK (fromguild, fromchannel, frommessage, action); queued edits/deletes pre-messagemap

threads(source bigint, target bigint[])        -- thread↔thread bridge routing

permaroles(userid, guild, roles bigint[], updated, nickname)  -- role save/restore; INDEX (userid, guild)

reminders(userid, guild, channel, message, content, created, scheduled, trigger_type)
    -- scheduler polls WHERE scheduled < NOW(); trigger_type selects handler

sentinel(id, name UNIQUE, description, lastmodified, subscribers bigint[], triggercount, created, triggered)
parlay(id, name, description, lastmodified, members bigint[], channel, guild, created, ttl interval)
    -- (sentinel = global pledge; parlay = guild-scoped variant)

qdb(user_id, guild_id, quote_id, key, value)   -- quote database (!quoteadd/get/search)

chatter_messages(id, user_id, guild_id, thread_id, role, content, created_at,
                 content_tsv tsvector GENERATED)  -- LLM history w/ full-text search (GIN index)

user_preferences(user_id, guild_id, key, value)  -- generic per-user KV (hotwords, OAuth tokens,
                                                  -- pending confirmations, sheet bridges, etc.)
```
Matrix bridge adds `matrix_guilds`, `matrix_portals`, `matrix_puppets`, `matrix_messages`.

`user_preferences` is the catch-all KV store — hotword configs (JSON), OAuth tokens, `pending_confirm-<msgid>` / `pending_chanlog-<msgid>` resumable-task state, sheet-bridge configs, and more all live here as `(user_id, guild_id, key, value)` rows.

---

## 6. Feature modules (replication-oriented summary)

### `janissary.py` — moderation & access control (45+ commands)
Roles (`!roleadd/del`, `!assign/revoke`, `!rolecolor`, `!createcategory`), access (`!part/optout`, `!snooze` with DB-backed auto-restore, `!voiceoptout`, `!invite`, `!openchannel`), moderation (`!kick`, `!lockout`, `!modreport`/👁‍🗨, `!modping` to ping an unpingable role with reaction approval, `!sudo`), bridge admin (`!bridge`, `!demolish`, `!bridges`, `!resync-threads`), and **reaction-based self-service** for roles/channels/threads (IDs persisted, reloaded at startup, handled via reaction add/remove). `!chanlog` exports channel history, summarizes it with **Claude (`claude-3-7-sonnet-latest`)**, and writes to **Notion** — with a resumable worker that survives reloads via `pending_chanlog-*` state. **Patterns to copy:** DB-persisted confirmation gates with timeout+restart recovery; resumable long-running async workers.

### `greeting.py` — member lifecycle
- **Lockout gate:** on join, strip read perms from every category, DM the rules, wait for an exact `"I agree"` DM (`client.wait_for`), restore perms or kick on timeout.
- **Role save/restore:** on leave, persist roles+nickname to `permaroles`; on rejoin, restore by user-id (fallback by nickname), then delete the record. `!populatepermaroles` bulk-imports from CSV/TSV.
- **Randomize role**, **greet DM**, **Airtable signup sync**, **chanban**. Handlers register into `ch.join_handlers` / `ch.remove_handlers`.

### `sentinel.py` — collective-action mechanic
Threshold-commitment social tool. `!assemble <count> <name>` creates a "banner" needing N pledges; `!pledge` joins (array_append to `subscribers`), and when `len(subscribers) == triggercount` it fires and @pings everyone; `!defect` leaves but is **blocked once triggered**; `!banners` lists active ones (30-day window). All state in the `sentinel` table (Postgres arrays). Clean, small, self-contained — a good first module to replicate.

### `text_manipulators.py` — spoilers + text effects
- **Spoilers:** `!rot13` (codecs rot_13) and `!spoiler`/`!memfrob` (XOR each byte with `0x2A` after case-swap; `rot32768` for non-ASCII). Both **delete the original** and post the scrambled version with a reaction; reacting DMs the decoded text. Reaction wait is 100 min.
- **Image scramble** (`!scramble`): PIL pixel-shuffle seeded by **image dimensions** (so it's reversible/deterministic); deep-fry/flip variants; GIF frame handling.
- **~20 reversible text codecs** exposed both as commands and as importable helpers (used by `sentinel`): `smallcaps`, `smoltext`, `fraktur`, Standard Galactic Alphabet, Ranboo "endertext", morse, zalgo, swapcase. All built on `str.maketrans`.
- Misc: `!md5`, `!ocr`, `!watchword`, `!ready`/`!countdown`, cross-server `!react`/`!flip`.

### `swag.py` — the grab-bag (~80 commands)
Dice (`!roll 2d6+5`, `dnd`), `!pick`, animal-photo APIs (dog/duck/fox/bunny/lizard/waifu), knowledge/search (`!scp`, `!wiki`, `!onthisday`, LessWrong/EA-Forum/Metaforecast/SSC search), generators (`!fight` "They Fight Crime!", `!tmnt` with NLTK prosody detection, `!ace`, `!inspire`, `!amulet`, kaomoji), media (`!tiktok`/`!vine` via yt-dlp, `!audioconv` via ffmpeg, `!transcribe` via Gemini), integrations (Trello, Complice, Thingiverse, LIFX, Twilio `!callme`, Pexels), and `!shindan` (ShindanMaker scrape). **`!retrowave` is disabled (DMCA).** Mostly independent REST/scrape wrappers with TTL caches — replicate à la carte. **Many embed third-party API keys in source.**

### `chatter.py` — LLM chat persona
- Claude chat that lives in Discord **threads** (or via mention). Uses `anthropic.AsyncAnthropic`, model from config section `[sparrow] model`, `max_tokens=2000`, streaming. Translation helper uses **`claude-haiku-4-5`**.
- **Persona is configurable** per guild/user: `sonnet-name`, `sonnet-avatar`, `sonnet-system` (replaces the whole system prompt). System prompt hardcodes a "knowledge cutoff Mar 2025" Anthropic-style preamble + a `<tool_instructions>` block teaching the model to emit **XML tags** (not native tool-use): `<antReactions>`, `<antImage image_size=...>`, `<search_history>`, `<search_server>`. A `FlexibleXMLParser` extracts these to drive reactions, image generation (FAL Flux Pro or Gemini), and full-text history search over `chatter_messages`.
- Conversation history is rebuilt from the Discord thread, coalesced into Claude message blocks (text + base64 images/docs), with optional per-link content fetching (user opt-in) and **Obsidian-style "skills"** loaded from `SKILL.md` files in a configured channel.
- **Modernization for replication:** swap the config-named `sparrow` model for a current id (e.g. `claude-opus-4-8` / `claude-sonnet-4-6`); the XML-tag pattern still works but native tool-use is now the cleaner path; fix Python-2 `except A, B:` syntax that appears in several files.

### `schedule.py` + `chronos.py` — reminders & cron
11-second polling loop over `reminders WHERE scheduled < NOW()`. NL time parsing via `dateparser`; intervals + `every N units` recurrence via `chronos` regex; timezone resolution (`pytz` + geopy geocoding) scoped per user/guild/channel; probability reminders (`p=0.5`); Claude-enhanced reminder bodies (prefix `?`); plus RSS/Atom feed polling and California power-outage alerts (ArcGIS + haversine). `!ical_enable` exports a calendar URL.

### Bridges & integrations
- **`matrixbridge.py`** — bidirectional Discord↔Matrix via `mautrix`, two modes (bot account, or full **appservice** with `@_discord_*` puppets under a Matrix Space). Echo-suppression + message-id mapping tables. High-effort to replicate.
- **`minedcraft.py`** — provisions ephemeral Minecraft servers on **Linode** from StackScripts; RCON via `mcipc`.
- **`sheetsjournal.py`** — mirrors a channel into a **Google Sheets** cell with daily row rotation (timezone-aware midnight).
- **`github.py`** — `!ghsearch` / `!ghreport` issue search & creation (trivial REST wrapper).
- **`googlephotos.py`** — random images from Google Photos albums / local dirs.
- **`mathemagical.py`** — `!math`/`!latex` → PNG via matplotlib+pdflatex with a **security-critical** TeX-primitive blocklist (never echoes TeX errors, to prevent file exfiltration); `!tengwar`.
- **`danbooru` / `derpibooru` / `pinterest`** — image-board search with NSFW-aware tag filtering and TTL caches.
- **`utils/`** — out-of-process bridges: `ircbridge.py`, `mcbridge.py`/`rabbitmc.py` (Minecraft via RabbitMQ), `smsbridge.py`, `redditlive.py`, `inbox2discord.py`/`glowficinbox2discord.py`, plus `fetchmsg.py` and `reload-fletcher` tooling.

---

## 7. Dependencies snapshot
Runtime targets **Python ≥ 3.14**. Key deps: a **pycord fork** (vendored, editable), **yt-dlp fork** (vendored), `psycopg`+`psycopg2` (async+sync), `anthropic`, `aiohttp`, `aiolimiter`, `uvloop`, `quart` (embedded web for OAuth callbacks / image server), `mautrix`, `Pillow`, `matplotlib`, `nltk` (VADER sentiment + CMU dict), `dateparser`, `pytz`/`tzwhere`/`geopy`, `cloudscraper`, `lxml`, `sentry-sdk`, `cysystemd`, `twilio`, `boto3`, Google API clients, `ephem`. Optional extras: `bridge` (aio-pika/asyncirc/asyncpraw/mcrcon/pika), `vision` (opencv), `reddit`. The shipped `freeze.txt` pins an *older* deployment (discord.py 1.5.1, Django 3.1) — i.e. the freeze is stale vs. the pyproject; trust `pyproject.toml`/`requirements.txt`.

---

## 8. A pragmatic replication blueprint

**Don't clone 44k lines.** Rebuild the spine, then add features as plugins.

**Phase 0 — skeleton (modern stack).** `discord.py` 2.x (or pycord), Postgres, a `CommandHandler` with dict-or-decorator command registry, the `config.get(key, section, guild, channel)` scope-cascade accessor, and the inject-globals `autoload(ch)`/`autounload(ch)` reload pattern (or just process-restart if you don't need hot reload).

**Phase 1 — the bridge (the actual product).** Webhook-name-encoded `webhook_sync_registry` rebuilt on startup; `bridge_message` relay with author spoofing; `messagemap` for edit/delete/react propagation; loop prevention; **then** `bridge_pending` race handling, thread routing, and cross-guild emoji remap. Budget most of your effort here.

**Phase 2 — moderation & members.** `permaroles` save/restore, lockout gate, self-service reaction roles, `!sudo`/`!modping`/`!modreport`. Copy janissary's DB-persisted confirmation + resumable-worker patterns.

**Phase 3 — pick your fun.** `sentinel` (easy, self-contained), the `text_manipulators` codecs, and whichever `swag` commands you actually want — each is an independent REST/scrape wrapper.

**Phase 4 — LLM persona (optional).** `chatter` with the current Anthropic SDK and native tool-use instead of XML tags; per-guild persona config; `chatter_messages` + tsvector history search.

**Phase 5 — protocol bridges (optional, high effort).** Matrix/IRC/Minecraft only if you need them.

### Things naive clones get wrong
1. Skipping `bridge_pending` → lost fast edits/deletes.
2. Treating teleport == bridging (they're different features).
3. Ignoring the config scope-cascade → per-channel overrides silently fail.
4. Forgetting loop-prevention → webhook→webhook infinite mirror.
5. Not rebuilding the registry on restart → bridges vanish after deploy.
6. Cross-guild custom-emoji reactions need image-hash remap, not id copy.
7. Python-2 `except A, B:` and config-named model ids must be modernized.

---

## 9. Provenance & caveats
- All findings are grounded in reading the source at commit `af13134` (cloned from sourcehut), cross-checked against the README, `controlflow.dot`, the in-repo `CLAUDE.md`, and the embedded schema dumps in `main.py`. The bot's own dev `CLAUDE.md` confirms: config at `/pub/lin/.fletcherrc` + `/pub/lin/.fletcher.d/<guild_id>`, deploy via `utils/reload-fletcher` (SIGHUP, never restart), source in `/home/lin/fletcher` deploying to `/pub/lin/fletcher`.
- **License: AGPL-3.0.** A network-deployed derivative must offer its source to users. The author offers relicensing on request.
- This is a **partial** release: no systemd units, no schema DDL files, no test harness, no optional/ancillary modules. The DB schema above is reconstructed and should be validated before use.
- Author contact for self-hosting / announcements Discord: `fletcher@noblejury.com`. Hosted add link: `https://fletcher.fun/add`.
