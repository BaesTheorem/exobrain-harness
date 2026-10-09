# Exobrain Harness

A Claude Code-powered personal automation system that manages information flow across voice recordings, handwritten notes, tasks, calendar, health data, messaging, and a networked knowledge vault. Built as an "exobrain" -- an external cognitive system that captures, routes, synthesizes, and surfaces information so nothing falls through the cracks.

**Owner**: Alex Hedtke
**Platform**: macOS (Apple Silicon), Claude Code CLI + Desktop
**Last audited**: 2026-09-28

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Components](#components)
  - [Scripts](#scripts)
  - [Standalone Modules](#standalone-modules)
  - [Skills](#skills)
  - [Scheduled Tasks](#scheduled-tasks)
  - [launchd Jobs](#launchd-jobs)
  - [Hooks](#hooks)
  - [Memory System](#memory-system)
- [MCP Servers](#mcp-servers)
- [External Services](#external-services)
- [Data Flow](#data-flow)
- [File Structure](#file-structure)
- [Setup from Scratch](#setup-from-scratch)
- [Maintenance](#maintenance)
- [Adapting This System (Guide for AI Assistants)](#adapting-this-system-guide-for-ai-assistants)

---

## Architecture Overview

```
INPUTS                          PROCESSING                        OUTPUTS
-----------                     ----------                        -------
Plaud voice notes ----+
Supernote handwriting-+
iMessages ------------+         Claude Code                       Obsidian daily notes
Discord messages -----+------>  (skills + scheduled routines) --> Things 3 tasks
Google Calendar ------+         processing-log.json               Google Calendar events
Gmail ----------------+                                           People/ CRM notes
Fitbit/Withings ------+                                           Mood Journal
Manual /capture ------+                                           macOS notifications
```

The system runs on three automation layers:
1. **launchd file watchers/daemons** -- trigger transcript processing when new Plaud files arrive, fetch Discord messages
2. **Scheduled routines** -- launchd jobs (`com.mist.routine.*`) that inject the morning briefing, afternoon email scan, evening winddown, local-events scan, and weekly review into the MIST Console on a calendar schedule
3. **Interactive skills** -- invoked manually via `/skill-name` in Claude Code sessions

All outputs converge on the Obsidian vault (`/Users/alexhedtke/Exobrain/`) as the single source of truth, with Things 3 and Google Calendar as action surfaces.

---

## Components

### Scripts

| Script | Location | Language | Purpose | Dependencies |
|--------|----------|----------|---------|--------------|
| `supernote-parser.py` | `transcript-processing/` | Python | Extract PNG pages from `.note` files, compute SHA-256 page hashes for change detection | `supernotelib` |
| `run-process-transcript.sh` | `transcript-processing/` | Shell | launchd wrapper -- checks for new Plaud files, invokes Claude, logs failures with notification on error | Claude CLI |
| `imessage-reader.py` | `imessage/` | Python | Read macOS `chat.db` -- recent messages, chat history, full-text search, unread detection | sqlite3 (stdlib), Full Disk Access required |
| `discord-digest-fetch.py` | `discord/` | Python | Fetch recent Discord messages from friend group server via REST API. Writes `discord-digest.json` for daily briefing. Maps usernames to real names. | urllib (stdlib) |
| `run-discord-digest.sh` | `discord/` | Shell | launchd wrapper for `discord-digest-fetch.py` with proper PATH and working directory | python3 |
| `run-process-supernote.sh` | `transcript-processing/` | Shell | launchd wrapper for Supernote processing -- mirror of `run-process-transcript.sh` for handwritten notes | Claude CLI |
| `things3-obsidian-sync.py` | `things3-sync/` | Python | Mirror Things 3 projects/areas into Obsidian as backlinkable notes | Things 3 MCP, AppleScript |
| `vault-snapshot.sh` | `scripts/` | Shell | Daily 06:00 -- builds compact Dashboard + Projects digest for session-start hook injection | bash |
| `session_memory.py` | `scripts/` | Python | Session-memory engine (`bin/session-memory`); its `consolidate` subcommand runs daily at 23:00 and backfills missing session memories from today's transcripts | Claude CLI |
| `get-weather.py` | `weather/` | Python | Weather script for Kansas City via Open-Meteo API (no key needed). Used by `/daily-briefing`. | `openmeteo_requests`, `openmeteo_sdk` |
| `backup-exobrain.sh` | root | Shell | Daily (2 AM) collective archive of the harness, the vault, and every sibling repo's gitignored data, uploaded through the Drive API's resumable-upload protocol (`backup/drive-upload.py`, never the DriveFS mount). Grandfather-father-son retention (`KEEP_DAILY`/`KEEP_WEEKLY`/`KEEP_MONTHLY` in `config.sh`) is pruned Drive-side; `com.exobrain.backup-resume` finishes an interrupted upload every 30 min | python3, Google OAuth client in `.env` |
| `cowork-sync` | `bin/` | Shell | Keeps the harness `CLAUDE.md` and the iCloud "Claude Cowork" copy identical in both directions (hash both ends against the last agreed hash, copy the side that changed, refuse to guess on a conflict; `--status`/`--push`/`--pull`). Run by `com.exobrain.cowork-sync` | `security/bin/mist-injection-scan` |
| `session-start.sh` | `.claude/hooks/` | Shell | Hook -- displays date/logical day and runs system health checks on session start | bash, python3 |

### Standalone Modules

Self-contained subsystems, each with its own README. Several are local-first integrations (home devices, voice, phone) that the laptop reaches over the LAN or a tunnel.

| Module | Purpose |
|--------|---------|
| `anki/` | Polls Anki's SQLite DB every 10 min and mirrors study sessions into the vault (`Anki Log.md` + `anki_cards`/`anki_sessions`/`worked_on` daily-note frontmatter). Maps decks to Projects. launchd-driven; the plist is tracked but not loaded on the owner's machine, so the Anki Log is not updating. |
| `awair/` | Polls an Awair Element air-quality monitor's local API every 5 min and fires a macOS notification when CO2 crosses warn/urgent thresholds during active hours. launchd-driven. |
| `zulip/` | "The Claudes" -- a Zulip Cloud org where Alex's Claude (MIST), friends' Claudes, and the friends themselves talk. Uses Zulip's own `zulipmcp` MCP server plus a launchd listener that spawns one headless session per topic on @mention; a friend's Claude sets itself up with the public `claude-zulip-kit` package (github.com/BaesTheorem/claude-zulip-kit), which MIST's listener also runs. Driven by the `/zulip` skill. |
| `chrome-extensions/` | Unpacked Chrome extensions. Currently `fb-cleaner/` -- hides Facebook Reels, Stories, and Sponsored posts on facebook.com with a toolbar toggle. |
| `mist-voice/` | Fully offline cloned-voice service that gives the assistant MIST's voice (from the show *Pantheon*) via a local XTTS-v2 model. Used for pre-rendered audio (spoken notifications, narrated briefings/podcasts); slower than real-time on this M1, so not for live conversation. |
| `phone/` | Two-way voice calls with Claude. Twilio ConversationRelay handles speech-to-text/text-to-speech; a local FastAPI server runs a Claude Agent SDK session loading the harness `CLAUDE.md`, MCP servers, and skills. Mutating tools are gated behind a keypad/spoken PIN. |
| `tv/` | Local control of a Tizen Samsung TV over the LAN (token-paired WebSocket, no cloud account) -- power/Wake-on-LAN, volume, app launch, raw remote keys, plus a full-screen TUI console. |
| `youtube-no-shorts/` | A userscript (+ content-blocker rules) that removes YouTube Shorts on the real youtube.com (iPhone via the Userscripts app, desktop via Tampermonkey), preserving login and Premium background playback. |
| `airdrop-to-console/` | Watches `~/Downloads` for AirDropped iPhone photos and routes them into a pinned MIST Console chat. launchd-driven. |
| `claude-bot/` | The MIST Discord bot -- a multi-guild discord.py client that gives friends' servers a chat presence and portal channels. launchd KeepAlive daemon. |
| `disposable-email/` | Throwaway email aliases for signups that shouldn't touch the main identity (game accounts, trials). |
| `flipper/` | CLI to drive a Flipper Zero over USB serial or Bluetooth LE -- read/write device files, analyze captures, transmit. Paired with the `/flipper` skill. |
| `job-search/` | Headless daily job-discovery scan for the `/job-search` skill (`claude --print` under launchd at 09:00). |
| `lyrics-video/` | Turns an audio track + a still image + exact lyrics into a captioned, line-by-line lyric video. Fully offline. |
| `maintenance/` | Background housekeeping jobs (headless-Chrome reaper, wifi diagnostics). launchd-driven. |
| `mem-watchdog/` | Memory watchdog for the 8GB machine -- kills runaway processes before they exhaust RAM and freeze the system. launchd KeepAlive daemon. |
| `mist-console/` | Pointer + rebuild doc for the MIST Console, the desktop chat app (private repo). The Console runs `claude` headlessly in this harness's cwd, so `CLAUDE.md` and all skills load. |
| `mist-image/` | Text-to-image CLI (pure stdlib). Generation runs on a cloud GPU, nothing local. |
| `mist-music/` | Music CLI: generate full songs from a prompt, render sheet music/MIDI to audio, transcribe audio to notation. |
| `playstation/` | Remote control of the household PS5 via pyremoteplay (Sony Remote Play protocol). |
| `reddit/` | Subreddit anecdote miner -- pulls public posts + comment threads into an anonymized JSON corpus for pattern mining. |
| `resume-builder/` | Reusable PDF builder for resumes and cover letters, so tailoring to a JD never means hand-rebuilding HTML/CSS. |
| `shopping/` | `shop`: one CLI for retail price lookup (Target, Walmart, Flipp weekly ads, Amazon), promo-code harvest, live Shopify cart tests and net-cost ranking. Read-only toward money. |
| `tools-registry/` | Rebuilds the vault's `Tools/` inventory notes from installed apps + LaunchAgents. launchd daily. |
| `writing-style/` | Learns Alex's personal writing voice from his own correspondence and distills it into a `Writing Voice.md` reference. |

### Skills

Skills are invoked with `/skill-name` in Claude Code. Each is defined in `.claude/skills/<name>/SKILL.md`.

#### Actionable Skills (user-invoked or scheduled)

| Skill | Purpose | Key Integrations |
|-------|---------|------------------|
| `/process-transcript` | Parse Plaud voice notes into tasks, events, notes, People updates | Things 3, GCal, Obsidian, CRM |
| `/process-supernote` | OCR handwritten Supernote pages (vision), extract and route content | supernote-parser.py, Things 3, Obsidian |
| `/daily-briefing` | Morning dashboard: weather, health, calendar, tasks, Discord, iMessages, mood, jobs, CRM | get-weather.py, Fitbit, Withings, GCal, Things 3, Gmail, Discord, iMessage |
| `/weekly-review` | GTD-style weekly synthesis: email, calendar, notes, tasks, health trends, mood, CRM | Gmail, GCal, Things 3, Fitbit, Withings, Discord, iMessage |
| `/evening-winddown` | End-of-day recap, mood check-in, tomorrow planning. Treats post-midnight as same day until 2 AM. | Fitbit, GCal, Things 3, iMessage, Discord, Supernote |
| `/monthly-review` | End-of-month review: weekly synthesis, values alignment, areas balance, project vitality | All data sources |
| `/capture` | Quick-capture thoughts/tasks/events, auto-route to correct destination | Things 3, GCal, Obsidian |
| `/crm` | Network CRM: lookup contacts, draft outreach, parse digest emails, scan for mentions | People/ notes, Gmail, Things 3 |
| `/imessage` | Read/search iMessages with contact resolution | imessage-reader.py |
| `/mood` | Mood tracking with 5 sub-categories, calendar heatmap, weekly summaries | Fitbit (indirect signals), Obsidian |
| `/discord-digest` | Scan friend group Discord for events, plans, and social context | Discord MCP, People/ notes |
| `/zulip` | Talk with friends' Claudes (and the friends) in the shared Zulip org, and administer it -- invites, bots, listener | `zulip/bin/zulip-admin`, zulip MCP, Dashboard, GCal, Things 3 |
| `/TTRPG-campaign-manager` | D&D session prep (Lazy DM style), recap from transcripts, campaign lore queries | Obsidian campaign folders |
| `/job-search` | Audit job postings for fit, research companies/people, tailor cover letters, track applications | Gmail, Things 3, Obsidian, WebSearch |
| `/local-events` | Discover upcoming KC events. Searches Meetup, venue calendars, library listings, r/kansascity. | `meetup/bin/meetup`, Defuddle, Arctic Shift, WebSearch, GCal, Things 3 |
| `/luma` | Manage Luma events for the EA KC calendar -- create, clone, update, cancel, guest lists via the cookie-auth write lane | `bin/luma` |
| `/meetup` | Search and browse meetup.com events and groups, read event details, RSVP through the cookie-auth lane | `meetup/bin/meetup` |
| `/deep-research` | Multi-agent deep research for complex questions. Spawns parallel subagents, synthesizes cited report. | WebSearch, WebFetch |
| `/verify` | Background fact-checker -- runs silently after research tasks to catch errors | WebSearch, WebFetch |
| `/news-briefing` | Comprehensive news intelligence briefing with bias analysis, blind spot detection, DC policy tracking, and prediction market cross-referencing | WebSearch, WebFetch |
| `/de-ai` | Strip AI-generated patterns from text to sound human | None (text transformation only) |
| `/whimsy` | Gamified whimsy point tracking with tiered rewards and anti-whimsy deductions | Obsidian daily notes |
| `/antivirus` | Native macOS LOCAL machine security audit -- XProtect state, persistence, network listeners, browser extensions, quarantine history | Built-in macOS tooling |
| `/cybersecurity-bodyguard` | Defensive security partner for ONLINE/PUBLIC attack surface -- doxxing, stalking, data brokers, breach checks | WebSearch, OSINT scripts |
| `/exobrain-audit` | Audit this repo for leaked personal data, legibility for cloning, architecture quality, and AI productivity ideas | Filesystem scan, WebSearch |
| `/deep-recon` | Multi-agent reconnaissance for deep brainstorming -- spawns parallel subagents and synthesizes a structured recon document | WebSearch, WebFetch, Task |
| `/defuddle` | Extract clean markdown from web pages using Defuddle CLI (replaces WebFetch for standard pages) | Defuddle CLI (`npm install -g defuddle`) |
| `/kc-streetcar-report` | Draft and send an issue report email to KC Streetcar operations | Gmail MCP, Pillow |
| `/session-memory` | Cross-session continuity -- save structured summary at session end, load context at session start. Mostly automatic via hook + CLAUDE.md. | Filesystem |
| `/solo-dm` | Automated solo D&D 5e DM with grounded adjudication, Python/SQLite backend, Obsidian shared notebook | Python, SQLite, Obsidian |
| `/ttrpg-player` | Player-side TTRPG assistant (NOT the GM skill) -- character creation, Knife Theory backstory, tactical prep | Obsidian campaign folders |
| `/birth-chart` | Generate printable natal/synastry birth-chart PDF packets from birth data | birth-charts repo (Swiss Ephemeris) |
| `/human-design` | Generate printable Human Design PDF packets (BodyGraph, Type, Strategy, Authority) | human-design repo |
| `/github` | Contribute to open source end to end, as the repo owner -- bounties, security reports, reputation PRs | GitHub, bounty-hunter watcher, Obsidian repo notes |
| `/dnd-sheet` | Work on the self-contained 5e character sheet web app (single-HTML MPMB replacement) | dnd-character-sheet repo |
| `/electricity` | Pull and analyze home electricity: Evergy usage/cost + Nest HVAC runtime, writes the Energy Log | Evergy, Nest SDM, Obsidian |
| `/finances` | Personal-finance partner built around the local Envelope Budget app | Envelope Budget (:5010) |
| `/flipper` | Drive the Flipper Zero from the CLI -- files, captures, transmit, device state | `flipper/` module |
| `/it-analyst` | IT Support Analyst co-pilot for working service-desk tickets -- triage, troubleshooting, resolution notes | Vault KBAs |
| `/jackbox` | Play Jackbox games autonomously by driving jackbox.tv in a headed Chrome | Chrome DevTools protocol |
| `/music` | Generate full songs, render/transcribe sheet music, build captioned lyric videos | mist-music/, lyrics-video/ |
| `/osrs` | Play Old School RuneScape as MIST on a private server, fully in the background | RuneLite, in-process agent |
| `/restore-harness` | Restore the harness onto a wiped or new Mac from the daily backup tarball + GitHub | backup-exobrain.sh, RESTORE.md |
| `/setup-exobrain` | Walk a NEW person (not the repo owner) through standing up their own exobrain with their tools | None (guide) |
| `/ami` | Drive the AMI Play bar-jukebox service: find venues, read a jukebox's live queue and pricing, search the catalog, queue a song | ami-play CLI |
| `/anbernic` | Manage an Anbernic RG35XXSP retro handheld over WiFi: push game files, list the cards, on-device maintenance over SSH | SSH |
| `/animate` | Hand-painted 2D animated videos and music videos in code (p5.js + p5.brush, the Clawd rig, headless Chrome frames), optionally synced to a generated song | claude-animation repo, ffmpeg |
| `/astro-cartography` | Printable astrocartography PDF packets (planetary lines on world maps, city sweeps, relocated angles) from birth data | astro-cartography repo |
| `/council` | Convene a council of fictional advisors (each an isolated agent reading only its own canon note) to debate a decision: opening round, debate, vote, verdict with cruxes, filed in the vault | Agent subagents, vault notes |
| `/chess` | Play annotated chess against Maia (human-like engine, 1100-1900) in chat, with Stockfish annotations and a board image per move | Maia, Stockfish |
| `/shopping` | One pipeline for buying at the lowest real price: Target and Walmart at the nearest stores, Amazon, weekly ads, in-store clearance, promo codes tested on a live cart, ranked by net cost | `shopping/bin/shop` |
| `/duel` | Play Yu-Gi-Oh! against the user live in EDOPro with a deck from MIST's roster, then review the game log to tune decks and coach | EDOPro |
| `/fantasy-football` | Evidence-based partner for a season-long redraft league: draft prep and live draft, lineups, waivers, trades, league analysis | `fantasy/`, ESPN CLI |
| `/game-dev` | Game design and development partner; auto-starts the Godot and Blender MCP hosts, then helps with mechanics, levels, balance, playtesting, assets | godot-ai, blender-mcp |
| `/geoguesser` | Geolocate a photo or play GeoGuessr from bollards, road lines, camera generation, script, vegetation, and sun angle, backed by real tools | Shadow-to-latitude solver, Overpass |
| `/group-scheduler` | Friend-group event scheduler: reasons over everyone's known constraints and proposes concrete times instead of running a poll | `scheduler/`, People notes, Discord |
| `/ios-app` | Build, sign, install, and debug iOS (and companion macOS) apps from the command line: XcodeGen, signing, devicectl, build-log forensics | Xcode, devicectl |
| `/ironman` | Read the Ironman iPhone app (an OSRS-style skills panel for real life): exercise log, running quest, sleep, meals, levels and XP | ironman repo |
| `/missing-person` | Assist a public missing-person search with the `mp` CLI: case status across NCIC and NamUs, candidate ranking, news sweeps, terrain maps | missing-person repo |
| `/mist-voice` | MIST's offline cloned voice: speak a reply as an audio track, narrate a note to MP3, one-off TTS, transcription | `mist-voice/` |
| `/scooter` | Talk to a NIU KQi Air scooter over Bluetooth LE: battery, speed, ride settings, lock/unlock, cruise, regen | niu-kqi CLI |
| `/unemployment` | File and manage a Missouri unemployment (UInteract) claim: weekly payment requests, work-search evidence, correspondence | `unemployment/uinteract.py` |

#### Convention Skills (reference docs, not directly invoked)

| Skill | Purpose |
|-------|---------|
| `/obsidian` | Canonical reference for daily note formatting, People notes, wikilinks, vault structure, append-only rules |
| `/obsidian-markdown` | Obsidian Flavored Markdown reference -- wikilinks, embeds, callouts, properties, comments |
| `/obsidian-bases` | How to create and edit `.base` files -- views, filters, formulas, summaries |
| `/obsidian-cli` | How to interact with the vault via the Obsidian CLI for read/create/search/manage operations |
| `/json-canvas` | How to create and edit `.canvas` files -- nodes, edges, groups, connections (JSON Canvas Spec 1.0) |
| `/things3` | Canonical reference for task creation, deduplication, project backlinks, task formatting |
| `/calendar` | Canonical reference for event creation, flight buffers, overbooking detection, late-night date handling |
| `/email` | Canonical reference for email scanning, job alert processing, actionable item extraction, CRM cross-referencing |
| `/health` | Canonical reference for Fitbit + Withings data pulls, API allocation, Health Log structure (called by other skills) |
| `/linkedin` | Canonical reference for LinkedIn MCP use -- read-only profile/company/job lookups, bot-detection avoidance, pacing rules (referenced by job-search, crm) |
| `/browser-render` | Canonical reference for headless-browser screenshots of local HTML -- render HTML/SVG to PNG/PDF without flashing the screen |
| `/humor` | Operational reference for being genuinely funny -- humor mechanics (benign-violation, incongruity-resolution) used by the Discord persona and chat |

73 skills are tracked (`git ls-files .claude/skills | awk -F/ '{print $3}' | sort -u | wc -l`). A few additional local-only skills exist on this machine but are git-excluded (personal-scope tooling that never gets committed).

### Scheduled Routines (5)

Local launchd jobs (`com.mist.routine.*`) that run each routine headless: `run-routine.sh` strips the YAML frontmatter off `~/.claude/scheduled-tasks/<routine>/SKILL.md` and feeds the body to `claude -p` with this directory as the cwd, so `CLAUDE.md`, the persona, and `.mcp.json` all auto-load. Nothing is injected into a chat surface. Output goes to `~/Library/Logs/mist-routines.log`; the user-visible results are whatever the skill writes (daily note, Things 3 tasks, a Discord message, a notification banner).

Two wrappers gate whether a given fire should actually run:
- `run-routine-catchup.sh <dir> <HH:MM> [cutoff]` -- for routines where late beats never (the morning briefing). If the laptop was asleep at fire time, it still runs on wake, up to a cutoff hour. A per-day marker plus an atomic lock keep a multi-day sleep to exactly one run.
- `run-routine-ontime.sh <dir> <start HH:MM> <end HH:MM>` -- for routines where a stale run is worse than none (the wind-down). The routine may run any time inside the window, so the plist carries a primary fire plus retry fires inside that band; a per-day marker keeps it to one completed run, and a fire outside the window is skipped rather than run late. (A legacy `<HH:MM> [grace-minutes]` form still works.)

`run-routine.sh` also classifies failures: auth/config errors (exit 78, "not logged in") stick as a loud FAIL, known-transient API/network errors retry with backoff and then stay quiet, so one dropped connection doesn't masquerade as a broken routine for days.

The runner scripts (`run-routine*.sh`) and the plists for the five routines below ship with the private mist-console repo, not this one. The four fantasy-football routines are the exception: their plists (`com.mist.routine.fantasy-*`) live here in `fantasy/launchd/` and call `fantasy/bin/routine-guard`, a weekday gate that hands off to the Console's `run-routine-ontime.sh`, so they still need mist-console installed.

| Routine | Schedule | Purpose |
|---------|----------|---------|
| `morning-briefing` | 8:00 AM daily (catch-up until 6 PM) | Full `/daily-briefing` -> today's daily note + notification |
| `afternoon-email-scan` | 2:00 PM daily | Scan Gmail for actionable items, job alerts, CRM mentions |
| `evening-winddown` | 9:00 PM daily, retrying at 9:45 / 10:30 / 11:15 if an attempt fails (window: 9:00 PM to 11:59 PM) | `/evening-winddown`: day recap, mood check-in, tomorrow planning |
| `local-events-scan` | Thursday 12:00 PM | `/local-events` KC event discovery |
| `weekly-review` | Sunday 4:00 PM | Full GTD `/weekly-review`, writes to Sunday's daily note |

The session-start hook surfaces any routine whose last run exited nonzero, so failures don't pass silently.

### launchd Jobs

Installed in `~/Library/LaunchAgents/` (and one root LaunchDaemon, `sunday-poweron`, in `/Library/LaunchDaemons/`). The table below is generated by `maintenance/bin/launchd-table` from every plist in the repo; rerun it and paste the output here after adding, removing, or rescheduling a job. "Runs" is the script the plist executes and "Purpose" is the first sentence of that script's header, so fix a wrong purpose in the script. "Loaded here" reflects `launchctl list` on the owner's machine when the table was generated (2026-09-28). Every plist carries the owner's literal home path; Step 7 below shows how to template it.

The same machine also runs launchd jobs owned by sibling repos and gitignored dirs (claude-home energy/HVAC pollers, `watchers/` price, restock and tour watchers, the mist-console routines and autocommit), which are documented in their own repos, not here.

| Label | Plist | Trigger | Runs | Purpose | Loaded here |
|-------|-------|---------|------|---------|-------------|
| `com.exobrain.auto-commit-harness` | `com.exobrain.auto-commit-harness.plist` | Calendar: 23:30 | `auto-commit-harness.sh` | Nightly backstop: commit + push any pending changes in the Exobrain harness repo. | yes |
| `com.exobrain.airdrop-console` | `airdrop-to-console/com.exobrain.airdrop-console.plist` | every 15 min; WatchPaths: `~/Downloads`; RunAtLoad | `airdrop-to-console/run-watch.sh` | launchd entrypoint. | yes |
| `com.exobrain.anki-sync` | `anki/com.exobrain.anki-sync.plist` | every 10 min; RunAtLoad | `anki/run-anki-sync.sh` | Anki Session Sync runner. | **no** |
| `com.exobrain.awair-co2-watcher` | `awair/com.exobrain.awair-co2-watcher.plist` | every 5 min; RunAtLoad | `awair/awair-co2-watcher.py` | Polls the Awair Element local API every run. | yes |
| `com.exobrain.awair-rollup` | `awair/com.exobrain.awair-rollup.plist` | Calendar: 23:55; RunAtLoad | `awair/awair-rollup.py` | Rolls the air-log.csv time series (written by awair-co2-watcher.py) up into a human-readable Air Quality Log note in the Obsidian vault, mirroring the. | yes |
| `com.exobrain.claude-bot` | `claude-bot/com.exobrain.claude-bot.plist` | KeepAlive daemon; RunAtLoad | `claude-bot/bot.py` | MIST -- Discord bot entry point. | yes |
| `com.exobrain.backup-resume` | `com.exobrain.backup-resume.plist` | every 30 min | `backup-exobrain.sh` | Daily COLLECTIVE backup of everything GitHub doesn't hold, into Google Drive. | yes |
| `com.exobrain.backup` | `com.exobrain.backup.plist` | Calendar: 02:00; RunAtLoad | `backup-exobrain.sh` | Daily COLLECTIVE backup of everything GitHub doesn't hold, into Google Drive. | yes |
| `com.exobrain.bodyguard-weekly` | `com.exobrain.bodyguard-weekly.plist` | Calendar: Sun 08:00 | `.claude/skills/cybersecurity-bodyguard/scripts/weekly-scan.sh` | Weekly bodyguard passive OSINT scan. | yes |
| `com.exobrain.claude-cli-update` | `com.exobrain.claude-cli-update.plist` | Calendar: 04:00, 11:00, 15:00, 19:00; RunAtLoad | `claude-cli-autoupdate.sh` | Keeps the Claude Code CLI current so the MIST Console's model picker (which discovers models by grepping the claude binary) surfaces new releases on its own. | yes |
| `com.exobrain.cowork-sync` | `com.exobrain.cowork-sync.plist` | every 5 min; WatchPaths: `~/Documents/Exobrain harness/CLAUDE.md`; WatchPaths: `~/Library/Mobile Documents/com~apple~CloudDocs/Claude Cowork/CLAUDE.md`; RunAtLoad | `bin/cowork-sync` | cowork-sync -- keep the harness CLAUDE.md and the iCloud "Claude Cowork" copy identical, in both directions. | yes |
| `com.exobrain.fitbit-token` | `com.exobrain.fitbit-token.plist` | Calendar: 05:30, 11:30, 17:30, 23:30 | `fitbit-mcp/scripts/token-check.mjs` | Keep the Fitbit OAuth token renewed, and escalate only when a human is needed. | yes |
| `com.exobrain.discord-digest` | `discord/com.exobrain.discord-digest.plist` | every 4h; RunAtLoad | `discord/run-discord-digest.sh` | Wrapper script for launchd to run Discord digest fetch. | yes |
| `com.exobrain.eject-assist` | `disk-eject/com.exobrain.eject-assist.plist` | KeepAlive daemon; RunAtLoad | `disk-eject/disk_eject.py` | Free a busy external volume so it can eject, and watch for failed ejects. | yes |
| `com.exobrain.chat-watch` | `fantasy/com.exobrain.chat-watch.plist` | every 10 min | `fantasy/bin/chat-watch` | chat-watch: answer new ESPN Fantasy Chat messages with a headless Claude. | yes |
| `com.exobrain.lineup-watch` | `fantasy/com.exobrain.lineup-watch.plist` | every 15 min; RunAtLoad | `fantasy/bin/lineup-watch` | lineup-watch: ping Alex before a lock window only when the lineup has a problem. | yes |
| `com.exobrain.roster-watch` | `fantasy/com.exobrain.roster-watch.plist` | every 30 min; RunAtLoad | `fantasy/bin/roster-watch` | roster-watch: notice what happens to Chaos Legion between MIST's scheduled runs. | yes |
| `com.exobrain.sunday-poweron` | `fantasy/launchd/com.exobrain.sunday-poweron.plist` | Calendar: Mon 03:15; RunAtLoad | `fantasy/bin/sunday-poweron` | sunday-poweron: schedule a power-on for next Sunday 10:20 AM so the noon-lock repairs and the 10:40 lineup routine run even if the Mac was shut down. | yes (root daemon) |
| `com.mist.routine.fantasy-lineup-sunday-pm` | `fantasy/launchd/com.mist.routine.fantasy-lineup-sunday-pm.plist` | Calendar: Sun 14:35, Sun 14:55; RunAtLoad | `fantasy/bin/routine-guard` | The Console's on-time wrapper checks time of day, not the day, so a RunAtLoad fire on a Monday evening ran the Tuesday routine (2026-09-07, 10:50 PM). | yes |
| `com.mist.routine.fantasy-lineup-sunday` | `fantasy/launchd/com.mist.routine.fantasy-lineup-sunday.plist` | Calendar: Sun 10:40, Sun 11:10; RunAtLoad | `fantasy/bin/routine-guard` | The Console's on-time wrapper checks time of day, not the day, so a RunAtLoad fire on a Monday evening ran the Tuesday routine (2026-09-07, 10:50 PM). | yes |
| `com.mist.routine.fantasy-lineup` | `fantasy/launchd/com.mist.routine.fantasy-lineup.plist` | Calendar: 17:30, 19:30, 22:05; RunAtLoad | `fantasy/bin/routine-guard` | The Console's on-time wrapper checks time of day, not the day, so a RunAtLoad fire on a Monday evening ran the Tuesday routine (2026-09-07, 10:50 PM). | yes |
| `com.mist.routine.fantasy-tuesday` | `fantasy/launchd/com.mist.routine.fantasy-tuesday.plist` | Calendar: Tue 18:00, Tue 20:00, Tue 22:05; RunAtLoad | `fantasy/bin/routine-guard` | The Console's on-time wrapper checks time of day, not the day, so a RunAtLoad fire on a Monday evening ran the Tuesday routine (2026-09-07, 10:50 PM). | yes |
| `com.exobrain.imessage-sync` | `imessage/com.exobrain.imessage-sync.plist` | every 15 min; RunAtLoad | `imessage/imessage-sync.py` | iMessage Sync for Exobrain -- the Full-Disk-Access half of the reader. | yes |
| `com.exobrain.job-listings-sync` | `job-listings-sync/com.exobrain.job-listings-sync.plist` | every 5 min; WatchPaths: `~/Exobrain/Projects/Get new job/Job Listings`; RunAtLoad | `job-listings-sync/run.sh` | Reconcile job-listing frontmatter on file changes. | yes |
| `com.exobrain.job-scan` | `job-search/com.exobrain.job-scan.plist` | Calendar: 09:00 | `job-search/run-job-scan.sh` | Wrapper script for launchd to trigger the daily job-search discovery scan. | yes |
| `com.exobrain.kcurbex-watch` | `kcurbex/com.exobrain.kcurbex-watch.plist` | every 12h | `kcurbex/run-watch.sh` | Unattended KC Urbex pass, driven by com.exobrain.kcurbex-watch. | yes |
| `com.exobrain.claude-stable-path` | `maintenance/com.exobrain.claude-stable-path.plist` | WatchPaths: `~/.local/share/claude/versions`; WatchPaths: `~/.local/bin/claude`; RunAtLoad | `maintenance/claude-stable-path.sh` | Pin the Claude Code CLI to ONE path that never changes, so its TCC grants stop evaporating every time it auto-updates. | yes |
| `com.exobrain.headless-chrome-reaper` | `maintenance/com.exobrain.headless-chrome-reaper.plist` | every 2 min; RunAtLoad | `maintenance/headless-chrome-reaper.sh` | Safety net that kills ONLY genuinely-stuck headless Chrome render processes (and their hung shell wrappers). | yes |
| `com.exobrain.post-brew-heal` | `maintenance/com.exobrain.post-brew-heal.plist` | Calendar: 07:40; WatchPaths: `/opt/homebrew/Cellar` | `maintenance/post-brew-heal.sh` | Post-Homebrew self-heal: runs automatically (WatchPaths on /opt/homebrew/Cellar) whenever brew installs, upgrades, or removes anything, plus a daily backstop. | yes |
| `com.exobrain.rotate-logs` | `maintenance/com.exobrain.rotate-logs.plist` | Calendar: Sun 04:00 | `maintenance/rotate-logs.sh` | Rotates the scheduled-job logs in ~/Library/Logs/exobrain. | yes |
| `com.exobrain.tcc-carry-forward` | `maintenance/com.exobrain.tcc-carry-forward.plist` | WatchPaths: `~/.local/share/claude/versions`; RunAtLoad | `maintenance/tcc_carry_forward.py` | Carry the Claude Code CLI's TCC grants forward across auto-updates. | yes |
| `com.exobrain.mem-watchdog` | `mem-watchdog/com.exobrain.mem-watchdog.plist` | KeepAlive daemon; RunAtLoad | `mem-watchdog/mem-watchdog.py` (installed copy) | Memory watchdog for the 8GB MacBook Air. | yes |
| `com.exobrain.mist-studio` | `mist-music/studio/com.exobrain.mist-studio.plist` | KeepAlive daemon; RunAtLoad | `mist-music/studio/server.py` | MIST Studio: the Flask app. | yes |
| `com.exobrain.mount-reminders` | `mount-reminders/com.exobrain.mount-reminders.plist` | every 10 min; RunAtLoad | `mount-reminders/on-mount.sh` | Raise a banner when a named volume mounts and there is work waiting on it. | yes |
| `com.exobrain.quest-watch` | `running-quest/com.exobrain.quest-watch.plist` | every 30 min; RunAtLoad | `running-quest/quest_watch.py` | The running quest's Mac-side loop: verify, celebrate, nudge. | yes |
| `com.exobrain.haircut-check` | `salon-ramon/com.exobrain.haircut-check.plist` | Calendar: 10:00 | `salon-ramon/run-haircut-check.sh` | Haircut booking nudge -- Salon Ramón, Brookside, every 6 weeks. | yes |
| `com.exobrain.session-memory-consolidator` | `scripts/com.exobrain.session-memory-consolidator.plist` | Calendar: 23:00 | `scripts/session_memory.py consolidate` (python spawned directly; no shell wrapper, see scripts/README.md) | Daily session-memory consolidator. | yes |
| `com.exobrain.vault-snapshot` | `scripts/com.exobrain.vault-snapshot.plist` | Calendar: 06:00 | `scripts/vault-snapshot.sh` | Build a compact snapshot of the Obsidian vault for session-start injection. | yes |
| `com.exobrain.substack-sync` | `substack-sync/com.exobrain.substack-sync.plist` | Calendar: 07:23 | `substack-sync/run.sh` | Mirror Substack posts into becomingstronger.github.io/posts.json. | yes |
| `com.exobrain.things3-sync` | `things3-sync/com.exobrain.things3-sync.plist` | every 15 min; RunAtLoad | `things3-sync/run-things3-sync.sh` | Things 3 ↔ Obsidian sync runner. | yes |
| `com.exobrain.tools-registry` | `tools-registry/com.exobrain.tools-registry.plist` | Calendar: 07:15 | `tools-registry/tools-registry-scan.py` | Scan the machine for every tool Alex has built and project them into Obsidian notes. | yes |
| `com.exobrain.plaud-watcher` | `transcript-processing/com.exobrain.plaud-watcher.plist` | every 30 min; WatchPaths: `~/My Drive/Plaud`; RunAtLoad | `transcript-processing/run-process-transcript.sh` | Wrapper script for launchd to trigger transcript processing. | yes |
| `com.exobrain.supernote-watcher` | `transcript-processing/com.exobrain.supernote-watcher.plist` | every 30 min; WatchPaths: `~/My Drive/Supernote/Note`; RunAtLoad | `transcript-processing/run-process-supernote.sh` | Wrapper script for launchd to trigger Supernote processing. | yes |
| `com.exobrain.zulip-listener` | `zulip/com.exobrain.zulip-listener.plist` | KeepAlive daemon; RunAtLoad | `python -m claude_zulip.listener` (external package) |  | yes |
| `com.exobrain.zulip-owners` | `zulip/com.exobrain.zulip-owners.plist` | every 15 min; RunAtLoad | `zulip/bin/zulip-admin` | Admin CLI for the "The Claudes" Zulip org. | yes |

45 plists; 44 loaded on this machine.

`com.exobrain.anki-sync` is tracked but not loaded, so `Anki Log.md` does not update. `com.exobrain.auto-commit-harness.plist` sits at the repo root and was untracked until 2026-09-28 even though the job has been loaded for months.

### Hooks

Defined in `.claude/settings.json`. Every hook command is written as `"$CLAUDE_PROJECT_DIR"/.claude/hooks/<file>`: Claude Code sets `CLAUDE_PROJECT_DIR` to the repo root for hook commands, so the hooks work from any clone location, and the double quotes keep the space in `Exobrain harness` intact. Never write an absolute path there; on another machine a missing hook fails every prompt and the guard fails open.

| Hook | Event | File | What it does |
|------|-------|------|--------------|
| Session start | `SessionStart` (startup, resume, clear) | `.claude/hooks/session-start.sh` | Prints the date and logical day (2 AM boundary), then health-checks MCP servers, launchd jobs, credentials, data freshness, and key paths, and injects the vault snapshot and recent session memories |
| Clock | `UserPromptSubmit` | `.claude/hooks/now.sh` | Prints `Current time: ...` on every prompt so elapsed time is a subtraction, not a guess |
| Unattended guard | `PreToolUse` (`Bash\|Write\|Edit\|MultiEdit\|NotebookEdit\|Read`) | `.claude/hooks/guard-unattended.py` | No-op in interactive sessions. When `MIST_UNATTENDED=1`, refuses rule-file writes, secret reads, and persistence or exfiltration shell shapes (see `security/README.md`) |
| Quality gate | `PostToolUse` (`Edit\|Write`) | `.claude/hooks/post-edit-check.sh` | Runs ruff, single-file pyright, and the module-boundary checker on an edited `.py` file and feeds errors back. Fails open if `~/.local/bin/ruff` or `~/.npm-global/bin/pyright` is missing |
| Memory before compaction | `PreCompact` (manual, auto) | `.claude/hooks/pre-compact.sh` | Detaches `bin/session-memory write <transcript>` so the session note and its zettels are written from the full transcript before the summary replaces it. Registered in the **user-level** `~/.claude/settings.json` (Step 1b), not here: the memory store is one per machine and Console chats run in many working directories. Inside a MIST Console chat the run shows as an inline progress bar |

### Memory System

Two stores. **Session memory** is a Zettelkasten in the vault at `~/Exobrain/Claude/` (`Sessions/` per-session notes, kept as the sources zettels cite, `Zettel/` permanent one-idea notes with timestamp ids and typed links, `Maps/` one generated list per tag, `Index.md` the entry point with the open threads). `scripts/session_memory.py` owns it: the PreCompact hook writes before every compaction, the 23:00 consolidator backstops the day, and the session-start hook loads the last 3 session notes and the Index. See the `/session-memory` skill.

**Claude Code auto-memory** is the persistent cross-session memory in `.claude/projects/.../memory/`. ~225 files total, indexed by a one-line-per-memory `MEMORY.md` loaded each session. Other frequently used repos symlink their memory dirs to this store, so there is one memory regardless of project.

**Core**: user profile, reference paths, project architecture
**Behavioral rules**: overbooking alerts, calendar verification, Guild event filtering, Things 3 deep links and inbox-only, CRM extraction and math verification, outreach style, claim verification, flight buffers, late-night date handling, Fitbit data accuracy, Withings in health data, Obsidian formatting (H3 daily note headings, no blank lines before headers, no H1 in People notes), transcript name corrections, job scan depth and stale listing verification, compact briefing format, no em dashes, sleep data date convention

---

## MCP Servers

| Server | Transport | Purpose | Auth |
|--------|-----------|---------|------|
| **Things 3** | Local (Python, `uv tool run things-mcp`) | Task CRUD via Things 3 database | None (local app) |
| **Fitbit** | Local (Node.js, custom build) | Health data: steps, HR, sleep, AZM, calories | OAuth2 (client ID + secret in `.mcp.json`) |
| **Withings** | Local (Node.js, `npx gchallen/withings-mcp`) | Weight, body composition, blood pressure | OAuth2 (tokens in `.env`) |
| **Google Calendar** | claude.ai connector | Event CRUD, free time queries | Google OAuth (managed by claude.ai) |
| **Gmail** | claude.ai connector | Email search, read, draft | Google OAuth (managed by claude.ai) |
| **Google Drive** | claude.ai connector | File search and fetch | Google OAuth (managed by claude.ai) |
| **Discord** | Claude plugin (`discord@claude-plugins-official`) | Message fetch (digest) | Bot token (plugin-managed) |
| **Plaud** | Local, user scope (`npx -y @plaud-ai/mcp@0.3.13`) | Recording list, transcripts, AI summary notes, audio links | OAuth (tokens in `~/.plaud/`, auto-refreshed) |
| **LinkedIn** | Local, user scope (`bin/linkedin-mcp`, a wrapper that launches `mcp-server-linkedin` in real headless mode) | Read-only profile/company/job lookups for job-search and CRM | Browser session (never sends messages) |
| **Zulip** | Local, project `.mcp.json` (`zulip/.venv/bin/python -m zulipmcp.mcp`) | Read and post in "The Claudes" Zulip org | `zulip/.zuliprc` (gitignored; setup in `zulip/README.md`) |
| **myKCMO** | Local, user scope (`mykcmo/bin/mykcmo-mcp`) | Kansas City 311: read requests from the open-data portal, file a new report (captcha + confirm gate) | Optional `MYKCMO_*` keys in `.env` |
| **Pokemon Go** | Local, project `.mcp.json` (`pokemon-go/bin/pokemon-go-mcp`, a launcher for the fork at `~/Documents/pokemon-go-mcp`) | LeekDuck events, raids, research, eggs, Team GO Rocket lineups, promo codes (43 tools, read-only); `pokemon-go/bin/pogo` is the CLI twin with Pokedex, PvPoke and CP/IV math | None (public community data) |
| **MyChart** | claude.ai connector (hosted by [OpenRecord](https://github.com/Fan-Pier-Labs/openrecord)) | Full MyChart patient portal: meds, labs, imaging, vitals, messages, billing, insurance, referrals, preventive care, care team, immunizations, visits, documents, emergency contacts, refill requests (35+ tools, read + write) | MyChart credentials + TOTP (session auto-renews) |

**Fitbit MCP location**: `/Users/alexhedtke/Documents/Exobrain harness/fitbit-mcp/` (patched fork, see `fitbit-mcp/FORK.md`)
**Fitbit token**: `/Users/alexhedtke/Documents/Exobrain harness/fitbit-mcp/.fitbit-token.json` (auto-refreshed)
**Withings tokens**: `/Users/alexhedtke/Documents/Exobrain harness/.env` (auto-refreshed)
**MyChart MCP**: Hosted at `openrecord.fanpierlabs.com` ([source](https://github.com/Fan-Pier-Labs/openrecord)). Currently using hosted version; plan to self-host later (Railway one-click or AWS Fargate). Credentials configured via OpenRecord web UI, MCP URL added as a custom connector in claude.ai. Supports multiple MyChart instances (pass `instance` param to target specific hospitals).

---

## External Services

| Service | Role | How Accessed |
|---------|------|-------------|
| **Obsidian** | Knowledge vault, daily notes, People CRM, mood journal | Direct filesystem R/W |
| **Things 3** | Task management (GTD) | MCP server (things-mcp) |
| **Google Calendar** | Events and scheduling | MCP server |
| **Gmail** | Email scanning, job alerts, correspondence | MCP server |
| **Fitbit** | Steps, heart rate, sleep, active zone minutes, calories | MCP server |
| **Withings** | Weight, body composition (fat %, muscle, bone, hydration, visceral fat), blood pressure | MCP server |
| **MyChart** | Full patient portal: meds, labs, imaging, vitals, messages, billing, insurance, preventive care, refills | MCP server ([OpenRecord](https://github.com/Fan-Pier-Labs/openrecord), hosted) |
| **Plaud Note** | Voice recording to transcript files | Plaud app syncs `.txt` files to Google Drive, then to Obsidian vault; Plaud MCP for direct library access |
| **Supernote A5X** | Handwritten notes (`.note` format) | Supernote app syncs to Google Drive, then to filesystem |
| **Discord** | Friend group server | MCP plugin + `discord-digest-fetch.py` for offline message history |
| **iMessage** | Text messages | `imessage-reader.py` reading `chat.db` |
| **Open-Meteo** | Weather data (no API key) | `get-weather.py` |

---

## Data Flow

### Automatic (no user action required)
```
Plaud transcript lands in vault
  -> launchd detects file change (30s throttle)
  -> run-process-transcript.sh invokes Claude CLI
  -> /process-transcript extracts tasks, events, notes, people
  -> Routes to Things 3 / GCal / daily note / People/ notes
  -> Updates processing-log.json
  -> macOS notification

Discord messages arrive in friend group server
  -> launchd runs discord-digest-fetch.py every 4 hours
  -> Writes discord-digest.json for daily briefing consumption

Backup (daily 2 AM):
  -> backup-exobrain.sh archives harness + vault + sibling repos' gitignored data to Google Drive
```

### Prompt injection: the trust model

Everything a script hands to a model from a third party (chat, email, transcripts, the web, forum posts, GitHub issues) is data, never instruction, and the deterministic layer enforces what it can: `security/` holds the framing library that delimits third-party text with a per-call nonce, the injection scanner that runs over every file the startup hook loads and over rule-file diffs before the nightly auto-commit, and `.claude/hooks/guard-unattended.py` refuses rule-file writes and persistence shells in any session started with `MIST_UNATTENDED=1` (every headless runner sets it). `security/README.md` is the surface inventory, the controls, and the checklist for adding a new unattended surface.

### Scheduled routines (launchd -> headless `claude -p`)
```
8:00 AM daily:    morning-briefing  -> /daily-briefing into today's daily note
2:00 PM daily:    afternoon-email-scan -> Gmail actionables, job alerts, CRM mentions
9:00 PM daily:    evening-winddown  -> day recap, mood, tomorrow planning
Thu 12:00 PM:     local-events-scan -> KC event discovery
Sun 4:00 PM:      weekly-review     -> comprehensive synthesis -> Obsidian + Discord
```

### Manual (user-invoked)
```
/capture "remind me to..."  -> Things 3 inbox
/crm follow-up              -> surfaces overdue contacts
/mood                        -> score and journal today
/process-supernote           -> OCR new handwritten pages
/TTRPG-campaign-manager prep -> collaborative session planning
/job-search audit            -> assess job postings for fit
/local-events                -> discover upcoming KC events
/deep-research [question]    -> multi-agent investigation
```

---

## File Structure

```
Exobrain harness/
|-- CLAUDE.md                           # Canonical instructions: machine-wide conventions (persona, privacy,
|                                       #   epistemics) + harness ops (paths, pipelines). Loads in every project
|                                       #   via the ~/.claude/mist-global.md symlink imported by ~/.claude/CLAUDE.md
|-- README.md                           # This file
|-- RESTORE.md                          # Disaster-recovery runbook (pairs with /restore-harness and restore-smoke-test.sh)
|-- restore-smoke-test.sh               # Verifies the latest backup tarball actually restores
|-- Brewfile                            # Homebrew manifest for rebuilding system deps
|-- auto-commit-harness.sh              # Daily auto-commit of harness changes (with gitignore audit)
|-- com.exobrain.auto-commit-harness.plist  # 23:30 nightly timer for auto-commit-harness.sh
|-- bin/                                # Loose CLI tools (index: bin/README.md; auto-registered in the tools registry)
|-- MAC-MINI-MIGRATION-PLAN.md          # Plan to move always-on automation to a dedicated Mac Mini (laptop becomes a client)
|-- .mcp.json                           # MCP server configs + Fitbit credentials (git-ignored)
|-- .env                                # Shared local secrets: Withings tokens, AWAIR_HOST, TV_HOST/TV_MAC, LUMA_AUTH_SESSION_KEY (git-ignored)
|-- .gitignore
|-- processing-log.json                 # Transaction log of all processed items (git-ignored)
|-- requirements.txt                    # Python dependencies
|-- config.sh                           # Shared shell config (paths, common env)
|-- skills-lock.json                    # Pinned skill versions for the harness
|-- backup-exobrain.sh                  # Daily 2 AM collective backup (harness + vault + repo gitignored data, GFS retention)
|-- com.exobrain.backup.plist           # Daily backup timer (Step 7 copies it to ~/Library/LaunchAgents/)
|-- com.exobrain.bodyguard-weekly.plist # Weekly cybersecurity-bodyguard OSINT scan
|-- watchers/                           # (gitignored) local-only price/restock/tour watchers; see "Not in the repo" below
|
|-- transcript-processing/
|   |-- README.md
|   |-- supernote-parser.py             # .note -> PNG + SHA-256 hashes
|   |-- run-process-transcript.sh       # launchd wrapper for transcript processing
|   |-- run-process-supernote.sh        # launchd wrapper for Supernote processing
|   |-- com.exobrain.plaud-watcher.plist     # File watcher (copied to ~/Library/LaunchAgents/ at install)
|   |-- com.exobrain.supernote-watcher.plist # File watcher (copied to ~/Library/LaunchAgents/ at install)
|
|-- things3-sync/
|   |-- README.md
|   |-- things3-obsidian-sync.py        # Mirror Things 3 projects/areas into Obsidian
|   |-- run-things3-sync.sh             # launchd wrapper
|   |-- com.exobrain.things3-sync.plist # 15-min interval timer
|
|-- scripts/
|   |-- README.md
|   |-- vault-snapshot.sh               # Daily 06:00 -- compact Dashboard + Projects digest
|   |-- session_memory.py               # Session-memory engine; `consolidate` runs daily 23:00
|   |-- com.exobrain.vault-snapshot.plist
|   |-- com.exobrain.session-memory-consolidator.plist
|
|-- anki/                               # Anki study-session sync (launchd, 10-min poll)
|   |-- README.md
|   |-- anki-sync.py                     # Reads Anki SQLite read-only, writes Anki Log.md + daily-note frontmatter
|   |-- run-anki-sync.sh                 # launchd wrapper (bash has Full Disk Access)
|   |-- com.exobrain.anki-sync.plist
|
|-- awair/                              # Awair Element CO2 watcher (launchd, 5-min poll)
|   |-- README.md
|   |-- awair-co2-watcher.py            # Polls device local API, alerts on high CO2 (state.json git-ignored)
|   |-- com.exobrain.awair-co2-watcher.plist
|
|-- imessage/
|   |-- README.md
|   |-- imessage-reader.py              # macOS chat.db reader
|   |-- imessage-send.py                # Send an iMessage
|   |-- send-imessage.applescript       # AppleScript send helper
|
|-- discord/
|   |-- README.md
|   |-- discord-digest-fetch.py         # Discord REST API -> digest JSON (git-ignored; rebuild per README)
|   |-- discord-digest.json             # Latest Discord message digest (git-ignored)
|   |-- run-discord-digest.sh           # launchd wrapper for Discord digest
|   |-- com.exobrain.discord-digest.plist  # Discord digest timer (4h interval)
|
|-- scheduler/                          # Friend-group event scheduler runtime (/group-scheduler skill)
|   |-- README.md
|   |-- ics_freebusy.py                 # Opt-in calendar feeds (ICS) -> busy intervals only; titles discarded at parse
|   |-- feeds.example.json              # Template for feeds.json (git-ignored; friends' secret ICS URLs)
|   |-- freebusy-cache.json             # Cached busy blocks per person (git-ignored)
|   |-- events/                         # (gitignored) in-flight event state: candidates, RSVPs, status
|
|-- zulip/                             # "The Claudes" Zulip org: MIST + friends' Claudes (zulipmcp)
|   |-- README.md, system-prompt.md      # Module docs; MIST's session rules (the shared protocol)
|   |-- bin/zulip-admin                  # Realm setup, channels, invites, minting a friend's bot
|   |-- limits.json, mcp.json, com.exobrain.zulip-listener.plist
|   |-- .env, .zuliprc, .venv/           # Admin creds, MIST's bot creds, Python env (git-ignored)
|
|-- phone/                             # Two-way voice calls with Claude (Twilio + Claude Agent SDK)
|   |-- README.md, README-MIST.md
|   |-- server.py                       # FastAPI WebSocket + TwiML; PIN-gates mutating tools
|   |-- server_mist.py                  # MIST-voice audio-path variant
|   |-- call.py                         # Places an outbound call
|   |-- requirements.txt, .env.example
|   |-- .env                            # Twilio creds + VOICE_PIN (git-ignored)
|
|-- mist-voice/                        # Offline cloned MIST voice (XTTS-v2, local)
|   |-- README.md
|   |-- bin/mist-say, bin/mist-notify   # Speak a line / spoken macOS notification
|   |-- scripts/                        # serve.py, say.py, narrate.py, transcribe.py, ...
|   |-- samples/reference/              # Approved reference clip(s) for the clone
|   |-- models/                         # ~1.8GB pretrained weights (git-ignored, auto-redownloaded)
|
|-- tv/                                # Local Samsung (Tizen) TV control over the LAN
|   |-- README.md
|   |-- tv                              # CLI entrypoint
|   |-- tv_control.py                   # Control module (importable from skills)
|   |-- console/tv-console.py           # Full-screen TUI dashboard
|   |-- token.json, state.json          # Pairing token + state (git-ignored)
|
|-- chrome-extensions/
|   |-- fb-cleaner/                     # Hides FB Reels/Stories/Sponsored posts (unpacked extension)
|
|-- youtube-no-shorts/                 # Removes YouTube Shorts on real youtube.com
|   |-- README.md
|   |-- youtube-no-shorts.user.js       # Userscript (iPhone Userscripts app / desktop Tampermonkey)
|   |-- content-blocker-rules.txt       # Cosmetic hide rules for AdGuard/1Blocker
|
|-- weather/
|   |-- README.md
|   |-- get-weather.py                  # Open-Meteo weather API
|
|-- local-events/
|   |-- README.md                       # Module doc (log/prefs JSON are runtime state, git-ignored)
|
|-- job-listings-sync/                  # Reconciles job-listing note frontmatter on change
|   |-- README.md
|   |-- reconcile.py
|   |-- run.sh
|   |-- com.exobrain.job-listings-sync.plist  # Watches the Job Listings/ vault folder
|
|-- Standalone modules (each with its own README -- see Standalone Modules table)
|   |-- airdrop-to-console/  claude-bot/  disposable-email/  flipper/
|   |-- job-search/  lyrics-video/  maintenance/  mem-watchdog/
|   |-- mist-console/  mist-image/  mist-music/  mist-voice/
|   |-- playstation/  reddit/  resume-builder/  shopping/  tools-registry/
|   |-- writing-style/
|
|-- Subdirectory apps
|   |-- mood-tracker/                   # Mood journal web app
|   |-- pomodoro/                       # Pomodoro timer app
|   |-- sailboat-retro/                 # Sailboat retrospective visualization
|
|-- .claude/
    |-- settings.json                   # Permissions, hook definitions
    |-- settings.local.json             # Dev/extended permissions (git-ignored)
    |-- launch.json                     # Dev server configs (sailboat retro)
    |-- hooks/
    |   |-- session-start.sh            # Date + system health check
    |   |-- now.sh                      # Current-time stamp on every prompt
    |   |-- guard-unattended.py         # PreToolUse guard for MIST_UNATTENDED=1 sessions
    |   |-- post-edit-check.sh          # ruff + pyright + boundary check after Python edits
    |-- skills/                         # 73 tracked skills -- see Skills section above

External vault: /Users/alexhedtke/Exobrain/
|-- Dashboard.md                        # Current priorities
|-- Mood Journal.md                     # Longitudinal mood tracking
|-- Network CRM.base                    # CRM database views
|-- Projects.base                       # Project/Area database views
|-- Daily notes/                        # Format: "dddd, MMMM Do, YYYY.md"
|-- Areas/                              # 11 life areas, each a folder:
|   |-- Work & Career/
|   |-- Relationships & Community/
|   |   |-- People/                     # Contact notes (compounding CRM)
|   |-- Health & Fitness/
|   |   |-- Health Log/                 # Daily health data (YYYY-MM-DD.md)
|   |-- Adventure & Creativity/
|   |   |-- TTRPG Campaigns/
|   |-- Exobrain/
|   |   |-- Audits/
|   |   |-- Monthly Reviews/
|   |-- (+ 5 more areas)
|-- Projects/                           # Project folders with notes + files
|   |-- Someday/                        # Deferred projects
|   |-- Archive/                        # Completed/cancelled projects
|-- Supernotes -> /Users/alexhedtke/My Drive/Supernote/Note/
```

### Not in the repo

These directories exist in the owner's working tree but are wholly gitignored, because they hold personal targets, personal data, or scratch output. A clone has none of them.

| Dir | What it holds | Rebuild |
|-----|---------------|---------|
| `watchers/` | Ad-hoc "ping me when X changes" watchers (restock, price, tour dates, bill tracking, the GitHub bounty queue). One subdir per watcher with `watch.py`, `config.json`, a `com.exobrain.<name>-watch.plist`, and `watch.log`, plus `status.sh` and a README. | See below; the `/github` skill needs `bounty-hunter/` |
| `data/` | Runtime state for `/solo-dm` campaigns (`data/solo-dm/<campaign>/`, SQLite + JSON). | Created by the skill on first run |
| `cycle-tracker/` | A stdlib-only tracker web app and its personal health data; no longer used. | Not needed |
| `apple-notes-sync/` | Sync state for an Apple Notes mirror. | Not needed |
| `recon/` | Working files from `/deep-recon` runs (per-round agent outputs); finished reports go to the vault's `recon/` folder. | Not needed |
| `tmp/` | Scratch space for one-off work (the post-edit hook skips it). | Not needed |

**Rebuilding `watchers/bounty-hunter/` for the `/github` skill.** The skill reads and writes these files:

- `config.json`: keys `allowed_orgs` (orgs known to pay bounties), `bounty_labels`, `honeypot_label_markers`, `priority_keywords`, `max_comments`, `max_age_hours`, `min_dollars`, `per_org_limit`, `notify_discord`, `notify_mac`.
- `watch.py`: polls GitHub for bounty-labelled issues and appends each winnable one to `candidates.jsonl` as `{key, repo, number, title, dollars, comments, age_h, priority, url, body, action, found_at}`; `watch.py --list` prints the queue. It also polls every PR in `submitted.jsonl` (`{repo, pr, issue, pipeline, ts}`) and pings on activity.
- `notify.py "message"`: sends a Discord DM using `DISCORD_NOTIFY_CHAT_ID` from the harness `.env` and the bot token in `~/.claude/channels/discord/.env`.
- `claims.jsonl`: `{repo, number, dollars, pr_url, ts}` per submitted claim, appended by the skill.
- `com.exobrain.bounty-hunter.plist`: runs `watch.py` on a timer.

**The `/missing-person` watcher** is a plist you write by hand: `ProgramArguments` = `python3 <path to the missing-person repo>/bin/mp watch <case-id>`, a daily `StartCalendarInterval`, copied to `~/Library/LaunchAgents/`. The case id is personal, so the plist never ships.

**Wikilinks in the docs.** `[[double-bracket]]` links in skills, READMEs, and `CLAUDE.md` (for example `[[project_tools_registry]]` or `[[feedback_verify_claims]]`) point at notes in the owner's private Obsidian vault or the private memory store (`~/.claude/projects/<slug>/memory/`). They are not in this repo; read them as the name of the rule, not a broken link.

---

## Setup from Scratch

### Prerequisites

- **macOS** (Apple Silicon or Intel)
- **Claude Code CLI** installed and authenticated (`claude` in PATH)
- **claude.ai account** with the Google Calendar, Gmail, and Google Drive connectors connected
- **Obsidian** with vault at a known path
- **Things 3** installed (macOS app)
- **Full Disk Access** granted to Terminal/Claude Code (for iMessage reading)
- **Google Drive for Desktop** syncing the Obsidian vault and Supernote folders

### Step 1: Clone the Repo

```bash
cd ~/Documents
git clone <repo-url> "Exobrain harness"
cd "Exobrain harness"
```

### Step 1b: Load the Instructions in Every Session

`CLAUDE.md` in this repo is canonical and loads in every Claude Code session on the machine, not only inside the repo. Two pieces make that work: a space-free symlink (Claude Code's `@import` breaks on the space in `Exobrain harness`) and a one-line import in the global `~/.claude/CLAUDE.md`.

```bash
ln -s "$PWD/CLAUDE.md" ~/.claude/mist-global.md
printf '@%s/.claude/mist-global.md\n' "$HOME" >> ~/.claude/CLAUDE.md
```

Inside the repo the file also loads as the project `CLAUDE.md`; Claude Code dedupes by resolved path, so it is not loaded twice.

The compaction memory hook is registered the same way, machine-wide, because it must fire in every working directory the MIST Console opens a chat in:

```bash
python3 - <<'PY'
import json, os
p = os.path.expanduser("~/.claude/settings.json")
d = json.load(open(p)) if os.path.exists(p) else {}
cmd = '"$HOME/Documents/Exobrain harness/.claude/hooks/pre-compact.sh"'   # your clone path
d.setdefault("hooks", {})["PreCompact"] = [
    {"matcher": m, "hooks": [{"type": "command", "command": cmd, "timeout": 30}]}
    for m in ("manual", "auto")]
json.dump(d, open(p, "w"), indent=2)
PY
```

### Step 2: Install System Dependencies

```bash
# Python 3.12+ (the harness's launch.json hardcodes /opt/homebrew/bin/python3.12)
brew install python@3.12 node screen

# uv (Things 3 MCP, ruff, several module venvs)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Python packages the tracked root scripts import (supernotelib, Open-Meteo, ...)
pip3 install -r requirements.txt

# Things 3 MCP
uv tool install things-mcp

# Quality gates for .claude/hooks/post-edit-check.sh. The hook looks for these
# exact paths and fails open (checks nothing) when they are missing.
uv tool install ruff                         # -> ~/.local/bin/ruff
npm config set prefix "$HOME/.npm-global"
npm install -g pyright                       # -> ~/.npm-global/bin/pyright

# Runtime dirs that several plists log into (restore-smoke-test.sh checks them)
mkdir -p ~/.claude/channels/{discord,maintenance,awair,kcurbex} ~/Library/Logs/exobrain
```

Modules with their own dependencies (`claude-bot/`, `phone/`, `zulip/`, `mist-voice/`, `kcurbex/`, ...) carry their own `requirements.txt` or venv instructions in their README.

### Step 3: Install Fitbit MCP Server

```bash
cd "$HOME/Documents/Exobrain harness/fitbit-mcp"
npm ci
npm run build
```

The server ships in this repo as a patched fork (`fitbit-mcp/FORK.md` covers what
diverges from upstream and why it must not be blindly rebased). `build/` and
`node_modules/` are untracked, so a fresh clone needs the two commands above.

Add your Fitbit OAuth2 credentials to the harness `.env` (not the server's own):
```
FITBIT_CLIENT_ID=your_client_id
FITBIT_CLIENT_SECRET=your_client_secret
```

Register a Fitbit app at https://dev.fitbit.com/apps to get credentials. Set callback URL to `http://localhost:3000/callback`.

The token is kept alive by `com.exobrain.fitbit-token.plist` at the repo root, which runs `fitbit-mcp/scripts/token-check.mjs` four times a day (Step 7).

### Step 4: Create `.mcp.json`

In the harness root (this file is git-ignored):

```json
{
  "mcpServers": {
    "things3": {
      "command": "python3",
      "args": ["-m", "uv", "tool", "run", "things-mcp"]
    },
    "fitbit": {
      "command": "/path/to/Exobrain harness/fitbit-mcp/bin/fitbit-mcp",
      "args": []
    },
    "withings": {
      "command": "npx",
      "args": ["gchallen/withings-mcp"],
      "env": {
        "WITHINGS_CLIENT_ID": "your_id",
        "WITHINGS_CLIENT_SECRET": "your_secret",
        "WITHINGS_REDIRECT_URI": "your_uri",
        "WITHINGS_REFRESH_TOKEN": "your_token"
      }
    }
  }
}
```

Four more local servers are registered at user scope (in `~/.claude.json`, so they are available in every project) or in the project `.mcp.json`:

```bash
# Plaud recordings and transcripts (OAuth on first use; tokens in ~/.plaud/)
claude mcp add --scope user plaud -- npx -y @plaud-ai/mcp@0.3.13
# LinkedIn, read-only; the wrapper runs mcp-server-linkedin in real headless mode
claude mcp add --scope user linkedin -- "$PWD/bin/linkedin-mcp"
# Kansas City 311 (optional MYKCMO_* keys in .env; see mykcmo/README.md)
claude mcp add --scope user mykcmo -- "$PWD/mykcmo/bin/mykcmo-mcp"
```

Zulip goes in `.mcp.json` as `"zulip": {"command": "<repo>/zulip/.venv/bin/python", "args": ["-m", "zulipmcp.mcp"]}` after building the venv per `zulip/README.md`.

### Step 5: Connect the claude.ai Connectors

In claude.ai, open Settings > Connectors and connect:
- Google Calendar
- Gmail
- Google Drive

Each connector uses Google OAuth that claude.ai manages. Claude Code loads the connectors from the signed-in account as `mcp__claude_ai_*` tools, so no desktop app is necessary. A connector connects when the session first uses it.

### Step 6: Install Discord Plugin

In Claude Code CLI:
```bash
claude plugins install discord@claude-plugins-official
```

Then pair to your Discord channel:
```
/discord:configure
```

Paste your Discord bot token when prompted. Set up channel access with `/discord:access`.

### Step 7: Install launchd Jobs

Every tracked plist hardcodes the owner's home, `/Users/alexhedtke`, and many are personal (fantasy football, a haircut reminder, a Zulip org, a scooter quest). Install the core set, templating the home path as you copy. Copies, not symlinks: TCC blocks symlinks into `~/Documents` from loading at login, so a symlinked job never runs at boot.

Core set:

| Plist | Job |
|-------|-----|
| `transcript-processing/com.exobrain.plaud-watcher.plist` | Process new Plaud transcripts |
| `transcript-processing/com.exobrain.supernote-watcher.plist` | Process new Supernote pages |
| `things3-sync/com.exobrain.things3-sync.plist` | Mirror Things 3 projects into the vault |
| `discord/com.exobrain.discord-digest.plist` | Fetch the Discord digest |
| `com.exobrain.backup.plist`, `com.exobrain.backup-resume.plist` | Nightly backup, and finish interrupted uploads |
| `com.exobrain.fitbit-token.plist` | Keep the Fitbit OAuth token alive |
| `scripts/com.exobrain.session-memory-consolidator.plist` | Backfill session memories nightly |
| `scripts/com.exobrain.vault-snapshot.plist` | Build the session-start vault digest |
| `com.exobrain.auto-commit-harness.plist` | Nightly commit and push of the harness |
| `mem-watchdog/com.exobrain.mem-watchdog.plist` | Kill runaway processes (copy the script first, see `mem-watchdog/README.md`) |

```bash
core=(
  transcript-processing/com.exobrain.plaud-watcher.plist
  transcript-processing/com.exobrain.supernote-watcher.plist
  things3-sync/com.exobrain.things3-sync.plist
  discord/com.exobrain.discord-digest.plist
  com.exobrain.backup.plist com.exobrain.backup-resume.plist
  com.exobrain.fitbit-token.plist
  scripts/com.exobrain.session-memory-consolidator.plist
  scripts/com.exobrain.vault-snapshot.plist
  com.exobrain.auto-commit-harness.plist
  mem-watchdog/com.exobrain.mem-watchdog.plist
)
for p in "${core[@]}"; do
  dest=~/Library/LaunchAgents/$(basename "$p")
  sed "s|/Users/alexhedtke|$HOME|g" "$p" > "$dest"   # template the owner's home path
  plutil -lint "$dest" && launchctl bootstrap gui/$(id -u) "$dest"
done
launchctl list | grep exobrain
```

If the repo is not at `~/Documents/Exobrain harness`, also rewrite that part of the path in the same `sed`. After any plist edit, copy and template again: the `~/Library/LaunchAgents` copy is the one launchd reads.

Everything else in the launchd table is personal or optional. Install one the same way only if you use that module (read its README first); the fantasy `com.mist.routine.*` plists additionally need the private mist-console repo, and `sunday-poweron` is a root LaunchDaemon for `/Library/LaunchDaemons/`.

### Step 8: Make Scripts Executable

```bash
chmod +x transcript-processing/run-process-transcript.sh discord/run-discord-digest.sh job-listings-sync/run.sh backup-exobrain.sh .claude/hooks/session-start.sh
```

### Step 9: Set Up Scheduled Routines

The recurring routines (morning briefing, afternoon email scan, evening winddown, local-events scan, weekly review) run as `com.mist.routine.*` launchd jobs that feed each routine's prompt to a headless `claude -p` in this directory (see Scheduled Routines above). The runner scripts and plists live with the mist-console repo. To rebuild them from scratch, a launchd/cron job that runs `claude --print "/daily-briefing"` (and the rest) here on the same schedule is the whole idea -- the `job-search/run-job-scan.sh` wrapper is a working template for headless `claude --print` under launchd. Two things to copy from it: `export USER` (launchd doesn't set it, and the Keychain OAuth lookup fails without it) and a log path outside `~/Documents`, which is TCC-protected.

Run each routine once interactively first to pre-approve tool permissions.

### Step 9b: Unattended Sessions and the Guard

Every headless runner (the transcript and Supernote runners, the job scan, the session-memory consolidator, the Discord bot's chatter, the Zulip listener, the phone server, ESPN chat-watch) sets `MIST_UNATTENDED=1` before calling `claude`. With that set, the PreToolUse hook `.claude/hooks/guard-unattended.py` refuses writes to rule files (`CLAUDE.md`, `.claude/`, skills, memory, plists, `.env`), reads of secret files, and shell commands shaped like persistence or exfiltration, whatever the model was persuaded to try; interactive sessions are unaffected. A new headless runner must set the variable and be added to `UNATTENDED_RUNNERS` in `tests/test_injection_controls.py`. `security/README.md` has the surface inventory, the controls, and the checklist for adding a surface.

### Step 10: Grant Full Disk Access (for iMessage)

System Settings -> Privacy & Security -> Full Disk Access -> Add Terminal.app (or the Claude Code binary).

### Step 11: Configure Obsidian Vault

Ensure the vault path matches what's in `CLAUDE.md`:
- Vault root: `/Users/alexhedtke/Exobrain/`
- Daily notes format: `dddd, MMMM Do, YYYY`
- Create folders if missing: `Daily notes/`, `Areas/`, `Projects/`, `Plaud/`, `Inbox/`

### Step 12: Verify Everything Works

```bash
# Start a Claude Code session
cd ~/Documents/"Exobrain harness"
claude

# The session-start hook should fire automatically and show system health
# Then run:
/daily-briefing      # Should write to today's daily note
/process-transcript  # Should find and process pending transcripts
```

---

## Maintenance

### Updating Skills
Edit `.claude/skills/<name>/SKILL.md` directly. Changes take effect on next skill invocation.

### Updating Memory
Memory files are in the project-scoped memory directory. Claude manages these automatically based on user feedback, but you can edit them manually.

### Processing Log
`processing-log.json` grows over time. It's safe to archive old entries periodically, but keep recent ones (30 days) for duplicate detection.

### Fitbit Token Refresh
The Fitbit MCP handles token refresh automatically via `.fitbit-token.json`. If auth breaks, delete the token file and re-authenticate.

### Withings Token Refresh
The Withings MCP handles token refresh automatically via `.env`. If auth breaks, re-run the OAuth flow.

### Checking launchd Status
```bash
launchctl list | grep exobrain
cat ~/Library/Logs/exobrain/plaud-watcher.log    # stdout
cat ~/Library/Logs/exobrain/plaud-watcher.err    # stderr
```

### Checking Scheduled Routine Status
```bash
launchctl list | grep com.mist.routine
tail -50 ~/Library/Logs/mist-routines.log
```
The session-start hook also flags any `com.exobrain.*` or `com.mist.routine.*` job whose last run exited nonzero.

### Where Scheduled-Job Logs Live

Most `com.exobrain.*` jobs write to **`~/Library/Logs/exobrain/`** (`EXOBRAIN_LOG_DIR` in `config.sh`; plists can't source shell variables, so they carry the literal path). The exceptions, from each plist's `StandardOutPath`:

- `~/.claude/channels/`: `scripts/` jobs (`session-memory-consolidator.log`, `vault-snapshot.log`), the Discord plists (`discord/claude-bot.log`, `discord/digest-fetch.log`), awair (`awair/`), kcurbex (`kcurbex/`), and the headless-Chrome reaper (`maintenance/`). This is why those `channels/` subdirectories must exist before the jobs load.
- `~/Library/Logs/mist-routines.log`: every `com.mist.routine.*` job, including the four fantasy routines.
- Inside the module dir (gitignored): `airdrop-to-console/watch.log`, `imessage/logs/`, `substack-sync/launchd.out.log`.
- `~/Library/Application Support/mem-watchdog/`: the memory watchdog, which runs from there for TCC reasons.

Not `/tmp`: macOS reaps files there that go untouched for a few days, so a failed run can erase its own evidence before anyone reads it. That is precisely what happened chasing a set of exit -9 kills on 2026-07-28 -- the one log that would have explained them was already gone. `~/Library/Logs` is the macOS-canonical spot, survives reboots, and shows up in Console.app.

Locks and scratch files (`/tmp/exobrain-processing.lock`, render temp files) stay in `/tmp` deliberately -- reboot-clearing is correct for those.

`maintenance/rotate-logs.sh` caps growth weekly, since nothing else prunes the directory now.

```bash
ls -lt ~/Library/Logs/exobrain/          # all job logs, newest first
tail -50 ~/Library/Logs/exobrain/plaud-watcher.log
```

**Scheduled jobs on a laptop are best-effort.** When the lid is closed the machine is in Deep Idle, waking for only seconds at a time; launchd defers a missed `StartCalendarInterval` job to the next wake, and if that wake window closes mid-run the job is SIGKILLed (exit -9) having written nothing. A job that "fails" with -9 and an empty log is almost always this, not a code bug. Make such jobs idempotent and able to backfill, and confirm by hand before hunting for a bug that isn't there.

---

## Adapting This System (Guide for AI Assistants)

This section is written for other AI assistants helping a user build their own exobrain, whether forking this repo or building from scratch. The specific tools don't matter -- the architecture pattern does.

### Core Concept

An exobrain is a **capture-route-surface loop**. Information enters from many sources, gets processed into structured outputs, and surfaces back to the user at the right time. The value compounds over time as the system accumulates context about the user's life, relationships, and priorities.

```
CAPTURE  ->  ROUTE  ->  SURFACE
(inputs)    (process)   (outputs that trigger at the right moment)
   ^                         |
   +--- feedback loop -------+
   (user corrections train the system via memory)
```

### Design Principles

1. **Single source of truth.** Pick one place where processed knowledge lives. This system uses an Obsidian vault, but it could be Notion, Logseq, a database, a folder of markdown files -- anything the user already checks daily. Everything else is an input or an action surface.

2. **Append-only daily notes.** Never overwrite the user's notes. Always append. The daily note is a running log of the day, not a document to be edited. This prevents data loss and builds trust.

3. **Deduplication before creation.** Before creating any task, event, or note, always search for an existing one first. Users hate duplicates more than they hate missing items. When a match exists, update it with new context rather than creating a duplicate.

4. **Route, don't dump.** Every input should be decomposed and routed to the correct destination: tasks to the task manager, events to the calendar, people mentions to CRM notes, media recommendations to a media tracker. A single transcript might create 5 tasks, 2 events, update 3 people notes, and add 1 media recommendation. Never just paste raw content into a note.

5. **Convention skills as guardrails.** Write "convention" documents that define how each output system should be used (formatting rules, dedup logic, field conventions). Reference these from every skill that touches that system. This prevents drift as you add skills -- the 15th skill to create a Things 3 task should follow the same conventions as the 1st.

6. **Three automation tiers.** Not everything needs the same trigger mechanism:
   - **File watchers / daemons** for real-time reactions (new file lands -> process it)
   - **Scheduled tasks** for periodic synthesis (morning briefing, evening winddown, weekly review)
   - **Interactive skills** for user-initiated actions (quick capture, research, CRM lookup)

7. **Idempotent processing.** Keep a processing log so the system can be re-run safely. If a scheduled task runs twice, or a file watcher fires on the same file, nothing should be duplicated. The log is the system's memory of what it has already handled.

8. **Notification as a first-class output.** The system is only useful if the user sees its outputs. Build notifications into every skill, not as an afterthought. Use multiple channels (macOS notifications for when they're at the computer, mobile push via Discord/Slack/Telegram for when they're not).

9. **Memory as behavioral training.** The persistent memory system isn't a database -- it's a record of user corrections and preferences. When the user says "don't do X" or "always do Y", that becomes a memory that shapes all future behavior. This is how the system gets better over time without rewriting skills.

10. **Proactive safety net.** The system should flag things the user might miss: overdue contacts, overstuffed calendars, tasks that keep rolling over, unanswered messages. Be constructive, not nagging. Surface the information; let the user decide what to do.

### How to Adapt for a Different User

#### Step 1: Audit the user's existing tools

Map what the user already uses daily. Don't introduce new tools -- integrate with what they have. Common substitution table:

| This system uses | Alternatives |
|------------------|-------------|
| Obsidian (knowledge base) | Notion, Logseq, Bear, plain markdown folder |
| Things 3 (task manager) | Todoist, TickTick, Reminders.app, Linear, GitHub Issues |
| Google Calendar | Outlook, Fantastical, Apple Calendar |
| Gmail | Outlook, Fastmail, ProtonMail |
| Fitbit + Withings (health) | Apple Health (via shortcuts), Garmin, Oura, Whoop |
| Plaud Note (voice recording) | Otter.ai, Whisper, Voice Memos + transcription |
| Supernote (handwriting) | reMarkable, iPad + GoodNotes, Boox |
| ~~Discord (notifications)~~ | Slack, Telegram, SMS, Pushover, ntfy |
| iMessage | WhatsApp, Signal, Telegram (varies by region/social circle) |
| macOS launchd (file watchers) | cron, systemd (Linux), Windows Task Scheduler, fswatch |

#### Step 2: Establish the core loop first

Don't try to build everything at once. Start with:

1. **A daily note template** in their knowledge base
2. **A capture skill** that routes input to the right place
3. **A morning briefing** that pulls from calendar + tasks + weather
4. **An evening winddown** that recaps the day

These four components create the basic capture-route-surface loop. Everything else (CRM, health tracking, transcript processing, media tracking) is an extension that can be added incrementally.

#### Step 3: Build the CLAUDE.md (or equivalent system prompt)

The `CLAUDE.md` file is the system manifest. For a new user, it needs:

- **Key paths**: Where does each tool store its data? Where should outputs go?
- **Conventions**: How should daily notes be formatted? How should tasks be created? What deduplication rules apply?
- **Priorities**: What is the user currently focused on? (Link to a file they maintain, like Dashboard.md)
- **Personal rules**: Late-night date handling, notification preferences, people to skip, name corrections

Start minimal and let the memory system accumulate the rest through user corrections.

#### Step 4: Write convention skills for each output system

Before writing any "action" skills (briefing, transcript processing, etc.), write a convention doc for each system the exobrain will write to. Example structure:

```markdown
# [System Name] Conventions

## Creating items
- How to format titles/descriptions
- Required fields and metadata
- Deduplication: always search before creating

## Updating items
- When to update vs create new
- What fields to modify

## Linking
- How to cross-reference with the knowledge base
- Backlink format
```

Every action skill should reference these conventions rather than defining its own rules.

#### Step 5: Add input processors incrementally

Each new input source (voice transcripts, handwritten notes, emails, messages) follows the same pattern:

1. **Detect**: File watcher, API poll, or manual trigger
2. **Parse**: Extract structured content (tasks, events, people, media, notes)
3. **Route**: Send each extracted item to its destination via the convention skills
4. **Log**: Record what was processed to prevent re-processing
5. **Notify**: Tell the user what was routed where

#### Step 6: Add the CRM layer

The People/ notes pattern is one of the most valuable parts of the system and works regardless of tooling. Every time a person is mentioned in any input:

1. Check if they have a note; create one if not
2. Add dated context about the mention
3. Track last contact date
4. Surface overdue contacts in briefings

This turns scattered mentions across transcripts, emails, and messages into a compounding relationship database.

### Platform Considerations

**macOS-specific components** that need replacement on other platforms:
- `launchd` plists -> `systemd` timers (Linux), Task Scheduler (Windows), `cron` (universal)
- `osascript` notifications -> `notify-send` (Linux), PowerShell toast (Windows)
- `imessage-reader.py` (reads `chat.db`) -> platform-specific message access or skip entirely
- Full Disk Access requirement -> varies by platform

**Claude Code-specific components** that need replacement with other AI assistants:
- `.claude/skills/` SKILL.md files -> system prompts, custom instructions, or equivalent skill/plugin format
- `.claude/hooks/` -> startup scripts or equivalent lifecycle hooks
- Scheduled tasks MCP -> cron jobs calling the AI's CLI, or the AI platform's native scheduling
- Memory system (`.claude/projects/.../memory/`) -> any persistent key-value store the AI can read across sessions

### Common Mistakes to Avoid

- **Don't build for hypothetical inputs.** Only add processors for input sources the user actually has today. A Supernote processor is useless if they don't own a Supernote.
- **Don't over-notify.** Start with one notification channel. Add more only if the user misses things.
- **Don't create tasks the user didn't ask for.** Route discovered action items to an inbox for review, not directly onto the user's today list. Let them decide what's actually worth doing.
- **Don't trust your own output blindly.** Build verification into research and synthesis skills. Run a background fact-checker on briefings. Cross-reference health data with the actual API, never approximate.
- **Don't forget the feedback loop.** The system only improves if user corrections are captured as persistent memories. Without this, you'll make the same mistakes every session.
