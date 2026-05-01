# Exobrain Harness

A Claude Code-powered personal automation system that manages information flow across voice recordings, handwritten notes, tasks, calendar, health data, messaging, and a networked knowledge vault. Built as an "exobrain" -- an external cognitive system that captures, routes, synthesizes, and surfaces information so nothing falls through the cracks.

**Owner**: Alex Hedtke
**Platform**: macOS (Apple Silicon), Claude Code CLI + Desktop
**Last audited**: 2026-05-01

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Components](#components)
  - [Scripts](#scripts)
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
Discord messages -----+------>  (skills + scheduled tasks) -----> Things 3 tasks
Google Calendar ------+         processing-log.json               Google Calendar events
Gmail ----------------+                                           People/ CRM notes
Fitbit/Withings ------+                                           Mood Journal
Manual /capture ------+                                           macOS notifications
```

The system runs on three automation layers:
1. **launchd file watchers/daemons** -- trigger transcript processing when new Plaud files arrive, fetch Discord messages
2. **Claude Code scheduled tasks** -- run transcript checks, inbox review, weekly review on cron (morning briefing and evening winddown are manual/interactive)
3. **Interactive skills** -- invoked manually via `/skill-name` in Claude Code sessions

All outputs converge on the Obsidian vault (`/Users/alexhedtke/Documents/Exobrain/`) as the single source of truth, with Things 3 and Google Calendar as action surfaces.

---

## Components

### Scripts

| Script | Location | Language | Purpose | Dependencies |
|--------|----------|----------|---------|--------------|
| `supernote-parser.py` | `transcript-processing/` | Python | Extract PNG pages from `.note` files, compute SHA-256 page hashes for change detection | `supernotelib` |
| `run-process-transcript.sh` | `transcript-processing/` | Shell | launchd wrapper -- checks for new Plaud files, invokes Claude, logs failures with notification on error | Claude CLI |
| `imessage-reader.py` | `imessage/` | Python | Read macOS `chat.db` -- recent messages, chat history, full-text search, unread detection | sqlite3 (stdlib), Full Disk Access required |
| `discord-digest-fetch.py` | `discord/` | Python | Fetch recent Discord messages from friend group server via REST API. Writes `discord-digest.json` for daily briefing. Maps usernames to real names. | urllib (stdlib) |
| `discord-bot.sh` | `discord/` | Shell | Launch Claude CLI as persistent Discord bot (launchd manages restarts via `KeepAlive`) | Claude CLI, Discord plugin |
| `run-discord-digest.sh` | `discord/` | Shell | launchd wrapper for `discord-digest-fetch.py` with proper PATH and working directory | python3 |
| `run-process-supernote.sh` | `transcript-processing/` | Shell | launchd wrapper for Supernote processing -- mirror of `run-process-transcript.sh` for handwritten notes | Claude CLI |
| `things3-obsidian-sync.py` | `things3-sync/` | Python | Mirror Things 3 projects/areas into Obsidian as backlinkable notes | Things 3 MCP, AppleScript |
| `notify-check.sh` | `cycle-tracker/` | Shell | Partner notification check for cycle tracker app | bash |
| `vault-snapshot.sh` | `scripts/` | Shell | Daily 06:00 -- builds compact Dashboard + Projects digest for session-start hook injection | bash |
| `session-memory-consolidator.sh` | `scripts/` | Shell | Daily 23:00 -- backfills missing session memories from today's transcripts | bash, Claude CLI |
| `get-weather.py` | `weather/` | Python | Fallback weather script for Kansas City via Open-Meteo API (no key needed). Primary weather now via Weather MCP. | `openmeteo_requests`, `openmeteo_sdk` |
| `backup-exobrain.sh` | root | Shell | Weekly backup of processing log, credentials, skills, settings, and memory to compressed archive | None |
| `session-start.sh` | `.claude/hooks/` | Shell | Hook -- displays date/logical day and runs system health checks on session start | bash, python3 |

### Skills

Skills are invoked with `/skill-name` in Claude Code. Each is defined in `.claude/skills/<name>/SKILL.md`.

#### Actionable Skills (user-invoked or scheduled)

| Skill | Purpose | Key Integrations |
|-------|---------|------------------|
| `/process-transcript` | Parse Plaud voice notes into tasks, events, notes, People updates | Things 3, GCal, Obsidian, CRM |
| `/process-supernote` | OCR handwritten Supernote pages (vision), extract and route content | supernote-parser.py, Things 3, Obsidian |
| `/daily-briefing` | Morning dashboard: weather, health, calendar, tasks, Discord, iMessages, mood, jobs, CRM | Weather MCP, Fitbit, Withings, GCal, Things 3, Gmail, Discord, iMessage |
| `/weekly-review` | GTD-style weekly synthesis: email, calendar, notes, tasks, health trends, mood, CRM | Gmail, GCal, Things 3, Fitbit, Withings, Discord, iMessage |
| `/evening-winddown` | End-of-day recap, mood check-in, tomorrow planning. Treats post-midnight as same day until 2 AM. | Fitbit, GCal, Things 3, iMessage, Discord, Supernote |
| `/monthly-review` | End-of-month review: weekly synthesis, values alignment, areas balance, project vitality | All data sources |
| `/capture` | Quick-capture thoughts/tasks/events, auto-route to correct destination | Things 3, GCal, Obsidian |
| `/crm` | Network CRM: lookup contacts, draft outreach, parse digest emails, scan for mentions | People/ notes, Gmail, Things 3 |
| `/imessage` | Read/search iMessages with contact resolution | imessage-reader.py |
| `/mood` | Mood tracking with 5 sub-categories, calendar heatmap, weekly summaries | Fitbit (indirect signals), Obsidian |
| `/discord-digest` | Scan friend group Discord for events, plans, and social context | Discord MCP, People/ notes |
| `/TTRPG-campaign-manager` | D&D session prep (Lazy DM style), recap from transcripts, campaign lore queries | Obsidian campaign folders |
| `/job-search` | Audit job postings for fit, research companies/people, tailor cover letters, track applications | Gmail, Things 3, Obsidian, WebSearch |
| `/local-events` | Discover upcoming KC events. Searches Facebook, Meetup, venue calendars, library listings. | Monid CLI, WebSearch, GCal, Things 3 |
| `/deep-research` | Multi-agent deep research for complex questions. Spawns parallel subagents, synthesizes cited report. | WebSearch, WebFetch |
| `/cycle-tracker` | Track and manage partner's menstrual cycle -- log periods, symptoms, predictions | cycle-tracker/ app |
| `/verify` | Background fact-checker -- runs silently after research tasks to catch errors | WebSearch, WebFetch |
| `/news-briefing` | Comprehensive news intelligence briefing with bias analysis, blind spot detection, and prediction market cross-referencing | WebSearch, WebFetch |
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
| `/discord:access` | Manage Discord channel access and pairing policy | Discord plugin config |
| `/discord:configure` | Set up the Discord channel -- save bot token and review access policy | Discord plugin config |

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

### Scheduled Tasks (3)

Managed via Claude Code's scheduled-tasks MCP. Run as remote agents on cron.

| Task ID | Schedule | Purpose |
|---------|----------|---------|
| `check-transcripts` | 9 AM + 6 PM daily | Backup for launchd watcher -- finds and processes new Plaud files |
| `evening-inbox-review` | 6:00 PM daily | Alerts if Things 3 inbox > 5 items or has urgent deadlines |
| `weekly-review` | 10:00 AM Sunday | Full GTD review, writes to Sunday's daily note, pings Discord |

**Manually invoked** (require laptop to be on, or are interactive):
- `/daily-briefing` -- morning dashboard (was scheduled, now manual)
- `/evening-winddown` -- day recap, mood + concern check-in, tomorrow planning (interactive, so manual)

### launchd Jobs (9)

Installed in `~/Library/LaunchAgents/`.

| Plist | Location | Watches/Triggers | Purpose |
|-------|----------|-----------------|---------|
| `com.exobrain.plaud-watcher.plist` | `transcript-processing/` | `WatchPaths: Plaud/` folder (30s throttle, 30-min fallback) | Runs `run-process-transcript.sh` when new transcripts land |
| `com.exobrain.supernote-watcher.plist` | `transcript-processing/` | `WatchPaths: Supernote/Note/` folder (30s throttle) | Runs `run-process-supernote.sh` when new Supernote files land |
| `com.exobrain.things3-sync.plist` | `things3-sync/` | Interval: 900s (15 min) | Runs `things3-obsidian-sync.py` to mirror Things 3 projects/areas into Obsidian |
| `com.exobrain.discord-digest.plist` | `discord/` | Interval: 14400s (4 hours) | Runs `discord-digest-fetch.py` to fetch Discord messages for briefing |
| `com.exobrain.discord-bot.plist` | `discord/` | RunAtLoad + KeepAlive | Runs `discord-bot.sh` as a persistent Claude CLI session for Discord plugin |
| `com.exobrain.session-memory-consolidator.plist` | `scripts/` | Daily: 23:00 | Runs `scripts/session-memory-consolidator.sh` to write missing session memories from today's transcripts |
| `com.exobrain.vault-snapshot.plist` | `scripts/` | Daily: 06:00 | Runs `scripts/vault-snapshot.sh` to build a compact Dashboard + Projects digest for session-start injection |
| `com.exobrain.bodyguard-weekly.plist` | root | Weekly | Runs the cybersecurity-bodyguard weekly OSINT scan (`.claude/skills/cybersecurity-bodyguard/scripts/weekly-scan.sh`) |
| `com.exobrain.backup.plist` | root | Weekly: Sunday 2 AM | Runs `backup-exobrain.sh` to archive config, skills, memory to Google Drive |

### Hooks

| Hook | Event | File |
|------|-------|------|
| Session start | `SessionStart` (startup + resume) | `.claude/hooks/session-start.sh` |

Displays today's date with logical day (accounting for the 2 AM boundary), then runs system health checks on all MCP servers, launchd jobs, credentials, and key paths.

### Memory System

Persistent cross-session memory in `.claude/projects/.../memory/`. ~50 files total.

**Core**: user profile, reference paths, project architecture
**Behavioral rules**: overbooking alerts, calendar verification, Guild event filtering, Things 3 deep links and inbox-only, CRM extraction and math verification, outreach style, claim verification, flight buffers, late-night date handling, Fitbit data accuracy, Withings in health data, Obsidian formatting (H3 daily note headings, no blank lines before headers, no H1 in People notes), transcript name corrections, job scan depth and stale listing verification, compact briefing format, no em dashes, sleep data date convention

---

## MCP Servers

| Server | Transport | Purpose | Auth |
|--------|-----------|---------|------|
| **Things 3** | Local (Python, `uv tool run things-mcp`) | Task CRUD via Things 3 database | None (local app) |
| **Fitbit** | Local (Node.js, custom build) | Health data: steps, HR, sleep, AZM, calories | OAuth2 (client ID + secret in `.mcp.json`) |
| **Withings** | Local (Node.js, `npx gchallen/withings-mcp`) | Weight, body composition, blood pressure | OAuth2 (tokens in `.env`) |
| **Weather** | Local (Node.js, `npx @dangahagan/weather-mcp`) | Current conditions + forecast (Open-Meteo + NOAA, no API key) | None |
| **Google Calendar** | Claude Desktop managed | Event CRUD, free time queries | Google OAuth (Desktop-managed) |
| **Gmail** | Claude Desktop managed | Email search, read, draft | Google OAuth (Desktop-managed) |
| **Google Drive** | Claude Desktop managed | File search and fetch | Google OAuth (Desktop-managed) |
| **Discord** | Claude plugin (`discord@claude-plugins-official`) | Message fetch (digest) | Bot token (plugin-managed) |
| **Scheduled Tasks** | Claude Desktop managed | Cron-based remote agent execution | None |
| **MyChart** | Claude Desktop managed (hosted by [OpenRecord](https://github.com/Fan-Pier-Labs/openrecord)) | Full MyChart patient portal: meds, labs, imaging, vitals, messages, billing, insurance, referrals, preventive care, care team, immunizations, visits, documents, emergency contacts, refill requests (35+ tools, read + write) | MyChart credentials + TOTP (session auto-renews) |

**Fitbit MCP location**: `/Users/alexhedtke/Documents/Claude Code/mcp-fitbit-main/`
**Fitbit token**: `/Users/alexhedtke/Documents/Claude Code/mcp-fitbit-main/.fitbit-token.json` (auto-refreshed)
**Withings tokens**: `/Users/alexhedtke/Documents/Exobrain harness/.env` (auto-refreshed)
**MyChart MCP**: Hosted at `openrecord.fanpierlabs.com` ([source](https://github.com/Fan-Pier-Labs/openrecord)). Currently using hosted version; plan to self-host later (Railway one-click or AWS Fargate). Credentials configured via OpenRecord web UI, MCP URL added to Claude Desktop. Supports multiple MyChart instances (pass `instance` param to target specific hospitals).

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
| **Plaud Note** | Voice recording to transcript files | Plaud app syncs `.txt` files to Google Drive, then to Obsidian vault |
| **Supernote A5X** | Handwritten notes (`.note` format) | Supernote app syncs to Google Drive, then to filesystem |
| **Discord** | Friend group server | MCP plugin + `discord-digest-fetch.py` for offline message history |
| **iMessage** | Text messages | `imessage-reader.py` reading `chat.db` |
| **Open-Meteo** | Weather data (no API key) | Weather MCP (primary), `get-weather.py` (fallback) |

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

Backup (weekly):
  -> backup-exobrain.sh archives config, skills, memory, credentials
```

### Scheduled (cron via Claude Code)
```
9 AM + 6 PM:      check-transcripts -> backup for launchd watcher
6:00 PM daily:    inbox review -> notification if inbox needs attention
10:00 AM Sunday:  /weekly-review -> comprehensive synthesis -> Obsidian + Discord

Manual (interactive):
/daily-briefing   -> morning dashboard (invoked in session)
/evening-winddown -> day recap, mood, concern check-in, tomorrow planning (invoked in session)
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
|-- CLAUDE.md                           # System manifest (paths, conventions, priorities)
|-- README.md                           # This file
|-- .mcp.json                           # MCP server configs + Fitbit credentials (git-ignored)
|-- .env                                # Withings OAuth tokens (git-ignored)
|-- .gitignore
|-- processing-log.json                 # Transaction log of all processed items (git-ignored)
|-- requirements.txt                    # Python dependencies
|-- config.sh                           # Shared shell config (paths, common env)
|-- skills-lock.json                    # Pinned skill versions for the harness
|-- backup-exobrain.sh                  # Weekly backup script
|-- com.exobrain.backup.plist           # Weekly backup timer (Step 7 copies it to ~/Library/LaunchAgents/)
|-- com.exobrain.bodyguard-weekly.plist # Weekly cybersecurity-bodyguard OSINT scan
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
|   |-- session-memory-consolidator.sh  # Daily 23:00 -- backfill missing session memories
|   |-- com.exobrain.vault-snapshot.plist
|   |-- com.exobrain.session-memory-consolidator.plist
|
|-- imessage/
|   |-- imessage-reader.py              # macOS chat.db reader
|
|-- discord/
|   |-- README.md
|   |-- discord-bot.sh                  # Persistent Discord bot launcher
|   |-- discord-digest-fetch.py         # Discord REST API -> digest JSON
|   |-- discord-digest.json             # Latest Discord message digest (git-ignored)
|   |-- run-discord-digest.sh           # launchd wrapper for Discord digest
|   |-- com.exobrain.discord-digest.plist  # Discord digest timer (4h interval)
|   |-- com.exobrain.discord-bot.plist     # Persistent bot daemon (RunAtLoad + KeepAlive)
|
|-- cycle-tracker/                      # Partner's cycle tracking app
|   |-- README.md
|   |-- notify-check.sh                 # Partner notification check
|
|-- weather/
|   |-- get-weather.py                  # Open-Meteo weather API (fallback)
|
|-- local-events/
|   |-- local-events-log.json           # Previously surfaced KC events (dedup)
|   |-- local-events-prefs.json         # Event preferences (artists, interests, venues)
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
    |-- skills/                         # 38 skills total -- see Skills section above

External vault: /Users/alexhedtke/Documents/Exobrain/
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

---

## Setup from Scratch

### Prerequisites

- **macOS** (Apple Silicon or Intel)
- **Claude Code CLI** installed and authenticated (`claude` in PATH)
- **Claude Desktop app** with Google Calendar, Gmail, Google Drive MCPs configured
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

### Step 2: Install System Dependencies

```bash
# Python 3.12+ (the harness's launch.json hardcodes /opt/homebrew/bin/python3.12)
brew install python@3.12 node screen

# Python packages
pip3 install supernotelib openmeteo-requests openmeteo-sdk

# uv (for Things 3 MCP)
pip3 install uv
# OR: curl -LsSf https://astral.sh/uv/install.sh | sh

# Things 3 MCP
uv tool install things-mcp
```

### Step 3: Install Fitbit MCP Server

```bash
cd ~/Documents/"Claude Code"
git clone <fitbit-mcp-repo-url> mcp-fitbit-main
cd mcp-fitbit-main
npm install
npm run build
```

Create `.env` with your Fitbit OAuth2 credentials:
```
FITBIT_CLIENT_ID=your_client_id
FITBIT_CLIENT_SECRET=your_client_secret
```

Register a Fitbit app at https://dev.fitbit.com/apps to get credentials. Set callback URL to `http://localhost:3000/callback`.

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
      "command": "node",
      "args": ["/path/to/mcp-fitbit-main/build/index.js"],
      "env": {
        "FITBIT_CLIENT_ID": "your_id",
        "FITBIT_CLIENT_SECRET": "your_secret"
      }
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
    },
    "weather": {
      "command": "npx",
      "args": ["@dangahagan/weather-mcp"]
    }
  }
}
```

### Step 5: Configure Claude Desktop MCP Servers

In Claude Desktop settings, enable:
- Google Calendar MCP
- Gmail MCP
- Google Drive MCP

These use Google OAuth managed by Claude Desktop -- follow the in-app auth flow.

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

```bash
# Copy plist files to LaunchAgents (NOT symlinks — TCC blocks symlinks
# into ~/Documents from loading at login, so the jobs would never run at boot).
cp "$PWD/transcript-processing/com.exobrain.plaud-watcher.plist" ~/Library/LaunchAgents/
cp "$PWD/transcript-processing/com.exobrain.supernote-watcher.plist" ~/Library/LaunchAgents/
cp "$PWD/things3-sync/com.exobrain.things3-sync.plist" ~/Library/LaunchAgents/
cp "$PWD/discord/com.exobrain.discord-digest.plist" ~/Library/LaunchAgents/
cp "$PWD/discord/com.exobrain.discord-bot.plist" ~/Library/LaunchAgents/
cp "$PWD/scripts/com.exobrain.session-memory-consolidator.plist" ~/Library/LaunchAgents/
cp "$PWD/scripts/com.exobrain.vault-snapshot.plist" ~/Library/LaunchAgents/
cp "$PWD/com.exobrain.backup.plist" ~/Library/LaunchAgents/

# Load the jobs
launchctl load ~/Library/LaunchAgents/com.exobrain.plaud-watcher.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.supernote-watcher.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.things3-sync.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.discord-digest.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.discord-bot.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.session-memory-consolidator.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.vault-snapshot.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.backup.plist

# After any plist edit, copy again — the LaunchAgents copy is the authoritative one.
# Verify
launchctl list | grep exobrain
```

Edit the plist files to match your actual paths if they differ from the defaults.

### Step 8: Make Scripts Executable

```bash
chmod +x discord/discord-bot.sh transcript-processing/run-process-transcript.sh discord/run-discord-digest.sh backup-exobrain.sh .claude/hooks/session-start.sh
```

### Step 9: Set Up Scheduled Tasks

Open a Claude Code session in the harness directory. The scheduled tasks are managed via the `scheduled-tasks` MCP -- create them with `/schedule` or via the MCP tools:

- **check-transcripts**: `0 9,18 * * *` (9 AM + 6 PM daily)
- **evening-inbox-review**: `0 18 * * *` (6 PM daily)
- **weekly-review**: `0 10 * * 0` (10 AM Sunday)

The daily briefing and evening winddown are invoked manually in interactive sessions (`/daily-briefing`, `/evening-winddown`).

Each scheduled task runs as a remote agent with its own Claude session. Run each once interactively first to pre-approve tool permissions.

### Step 10: Grant Full Disk Access (for iMessage)

System Settings -> Privacy & Security -> Full Disk Access -> Add Terminal.app (or the Claude Code binary).

### Step 11: Configure Obsidian Vault

Ensure the vault path matches what's in `CLAUDE.md`:
- Vault root: `/Users/alexhedtke/Documents/Exobrain/`
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
cat /tmp/exobrain-plaud-watcher.log    # stdout
cat /tmp/exobrain-plaud-watcher.err    # stderr
```

### Checking Scheduled Task Status
In a Claude Code session: use the scheduled-tasks MCP to list tasks and check `lastRunAt` timestamps.

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
