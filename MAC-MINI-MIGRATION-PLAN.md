# Mac Mini Server Migration Plan

Move the always-on parts of the exobrain harness to a dedicated Mac Mini so the laptop can sleep without breaking automation, Discord, or phone access.

## Goal

- One always-on host (Mini) runs all background watchers, scheduled jobs, and the Discord bot.
- MacBook remains a full client -- same vault, same Things 3, same repo -- but stops being the heartbeat.
- Chat from the phone works whether the laptop is awake or not.

## Architecture: heartbeat vs. clients

```
                       Things Cloud / Obsidian Sync / Google Drive / iCloud
                              ▲                      ▲
                              │                      │
                    ┌─────────┴─────────┐  ┌─────────┴─────────┐
                    │   Mac Mini (24/7) │  │  MacBook (client) │
                    │  HEARTBEAT        │  │                   │
                    │  • launchd jobs   │  │  • manual Claude  │
                    │  • Discord bot    │  │  • dev work       │
                    │  • watchers       │  │  • read/write OK  │
                    │  • cron / sched   │  │  • NO watchers    │
                    └─────────┬─────────┘  └───────────────────┘
                              │
                              ▼
                       Discord / phone
```

Rule: **exactly one machine owns the automation.** Both machines can read and edit data freely; only one runs the scheduled jobs and the Discord bot.

## Hardware

- **Mac Mini M4 base** (16GB / 256GB) -- ~$599, ~7W idle. Sufficient for everything below.
- Ethernet preferred over Wi-Fi for reliability.
- UPS optional but nice (a $50 CyberPower keeps it up through brownouts).

## What syncs natively (no work needed)

| System            | Sync mechanism            |
|-------------------|---------------------------|
| Obsidian vault    | Obsidian Sync (paid first-party service, existing; NOT iCloud Drive) |
| Things 3          | Things Cloud              |
| Plaud transcripts | Google Drive for Desktop  |
| Supernote files   | Google Drive for Desktop  |
| Repo              | git (push from either)    |
| Health data       | fetched fresh per call    |
| MyChart           | session lives in cloud    |

## What does NOT sync (manual copy required, one-time)

These are gitignored or local-only -- copy from MacBook to Mini during setup:

- `/Users/alexhedtke/Documents/Exobrain harness/.env` (Withings + other credentials)
- `~/.plaud/tokens-mcp.json` and `~/.plaud/tokens.json`
- `~/.config/fitbit/` (Fitbit refresh tokens)
- `~/.config/withings/` (if present beyond `.env`)
- Discord bot token (lives in `~/.claude/channels/discord/` per the bot script)
- `~/.claude/` -- global settings, skills, memory directory
- Any OAuth caches for cloud MCPs (Gmail, Calendar, Drive, MyChart) -- re-authorize from Claude.ai if needed

**Token refresh caveat:** Fitbit/Withings/Plaud store refresh tokens locally. After migration, refreshing on the Mini invalidates the MacBook's copies -- that's fine because the MacBook won't be calling those APIs anymore.

## Launchd jobs -- current inventory

All of these currently run on the MacBook. **Move all to Mini, disable all on MacBook.**

| Plist                                       | What it does                              |
|---------------------------------------------|-------------------------------------------|
| `com.exobrain.plaud-watcher`                | Watches GDrive Plaud folder, processes    |
| `com.exobrain.supernote-watcher`            | Watches GDrive Supernote folder           |
| `com.exobrain.awair-co2-watcher`            | Polls Awair sensor on LAN                 |
| `com.exobrain.discord-digest`               | Scheduled Discord digest fetch            |
| `com.exobrain.session-memory-consolidator`  | Backfills session memories nightly        |
| `com.exobrain.things3-sync`                 | Things 3 backlinks / project sync         |
| `com.exobrain.job-listings-sync`            | Job listings sync                         |
| `com.exobrain.backup`                       | Backup of exobrain harness                |
| `com.exobrain.vault-snapshot`               | Vault snapshot                            |
| `com.exobrain.bodyguard-weekly`             | Weekly bodyguard run                      |
| `com.exobrain.session-memory-consolidator`  | Session memory consolidation              |

**LAN-bound jobs:** `awair-co2-watcher` polls a device on the home network. Mini will be on the same LAN -- confirmed.

## Migration steps

### Phase 1 -- Set up the Mini (estimate: 2-3 hours)

1. Initial macOS setup, sign into Apple ID (same as MacBook so iMessage, Things 3, iCloud Drive all work).
2. Enable **auto-login** for the user account (System Settings → Users & Groups → Automatic login).
3. Power settings (Settings → Energy):
   - "Prevent automatic sleeping when display is off": ON
   - "Start up automatically after a power failure": ON
   - "Wake for network access": ON
4. Install Homebrew, then: `python@3.12`, `node`, `gh`, `git`, `jq`, `caffeinate` is built-in.
5. Install Claude Code CLI.
6. Install Things 3 (Mac App Store), sign in, wait for sync to finish.
7. Install Google Drive for Desktop, sign in, set Plaud + Supernote folders to mirror (not stream) so launchd watchers see real files.
8. Install Obsidian, sign into **Obsidian Sync** (separate account from the Apple ID), connect the remote vault, and wait for it to fully sync. **Important:** verify the vault path matches `/Users/alexhedtke/Exobrain/` exactly (depends on whether you use the same short username).

### Phase 2 -- Move the harness (estimate: 1 hour)

1. `git clone` the exobrain harness repo to `~/Documents/Exobrain harness/` on the Mini.
2. `pip install -r requirements.txt` for any Python deps.
3. Copy the non-synced files listed under "What does NOT sync" above (use AirDrop or scp over Tailscale).
4. Run a smoke test: invoke Claude Code on the Mini, ask it to read the Dashboard. Verify all MCPs connect (Plaud, Things 3, Fitbit, Withings, Discord, computer-use).
5. Re-authorize any cloud MCPs that need it (Gmail, Calendar, Drive, MyChart via claude.ai).

### Phase 3 -- Move the heartbeat (estimate: 30 min)

1. On the Mini: copy each plist from `~/Library/LaunchAgents/` (per the table above), update any hard-coded paths if usernames differ, then `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.<job>.plist` for each.
2. **Important:** per the `launchd_symlinks` rule, the plists must be real file copies in `~/Library/LaunchAgents/`, not symlinks into `~/Documents/`. TCC blocks symlinked plists at login.
3. Verify each job: `launchctl list | grep exobrain` should show all jobs with a recent PID.
4. On the **MacBook**: disable all jobs from the same list with `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.<job>.plist` (keep the plist files for rollback).
5. Confirm only the Mini is running each job (`ps aux | grep <watcher>` on both).

### Phase 4 -- Verify single-heartbeat (estimate: ongoing for 1 week)

For the first week, watch for duplicate processing:

- Drop a test Plaud .txt into the synced folder. Confirm only one Things 3 task is created.
- Send a Discord message. Confirm only one bot response.
- Check `processing-log.json` and the vault for sync-conflict artifacts (Obsidian Sync conflict copies, Drive `(conflict)` suffixes) -- none expected.
- Compare daily note for any duplicated headings or sections.

## Remote access -- phone to Mini

Discord is the only off-network entry point. No tunnel software needed -- Discord traffic is outbound from the Mini, so as long as the Mini has internet, the bot works from anywhere your phone has Discord.

If a future need for SSH / Screen Sharing from outside the home network emerges, revisit Tailscale (free for personal use, install on Mini + MacBook + iPhone, gives stable reachable hostname). Out of scope for the initial migration.

## Single-heartbeat rules (commit these to memory)

1. **Watchers and schedulers run on Mini only.** MacBook plists stay disabled.
2. **Discord bot runs on Mini only.** One token, one connection.
3. **Manual Claude invocations are fine on either machine** -- both can run skills, edit the vault, push commits, ask questions.
4. **Don't run `daily-briefing`, `evening-winddown`, or `weekly-review` on both machines on the same day** -- they're idempotent-ish but Obsidian Sync conflicts on the daily note are annoying. Pick one (probably Mini if scheduled, MacBook if manual).
5. **If the Mini is down**, you can re-enable the MacBook plists as a fallback. Document this in a runbook (TBD).

## Rollback plan

If migration causes problems:

1. `launchctl bootout` all Mini jobs.
2. `launchctl bootstrap` MacBook jobs again from the same plist files (still present).
3. Mini becomes a passive client until you try again.

No data is destroyed in either direction since everything syncs via Things Cloud / Obsidian Sync / Google Drive.

## Decisions locked

- **Computer-use MCP stays on the MacBook.** Mini runs headless, so screen/mouse control there is useless without a Screen Sharing session or HDMI dummy plug. MacBook is the natural home for interactive desktop control.
- **No Tailscale for now.** Discord is the only remote entry point. Revisit if SSH/Screen Sharing from outside the home network becomes needed.
- **Awair watcher moves to the Mini.** Mini will sit on the same LAN as the Awair sensor.

## Open questions / TBD

- **Hostname** for the Mini? (Suggest: `mini-heartbeat` or `exobrain-core`.)
- **iMessage MCP** -- works fine on the Mini once signed into the same Apple ID; Messages.app must be open at least once for the chat.db to populate.

## To-Do (post-setup, after the Mini is stable)

Deferred work that wants the Mini's headroom (16GB, always-on) or is a natural fit once the heartbeat has moved. Do these only after Phase 4 single-heartbeat is verified.

### Fine-tune a dedicated MIST voice model

**Why:** the current voice (`mist-voice/`, XTTS-v2) and the evaluated-and-passed alternative (Chatterbox) are both **zero-shot clones conditioned on a few seconds of reference**. That has a fidelity ceiling. On 2026-07-15 we A/B'd Chatterbox against XTTS across four settings (default 0.5/0.5, MIST-tuned 0.6/0.35, and a rich 27s reference at 0.4/0.4); Chatterbox won on license (MIT vs Coqui non-commercial) and naturalness, but Alex's verdict was "close but distinctly **not her**." XTTS stays the shipping voice because it's still the best zero-shot fidelity we have. The real upgrade is to stop zero-shot cloning and **fine-tune** a speaker model on real data.

**We already have the dataset, locally:**
- `mist-voice/samples/raw/mist_supercut.wav` (~335MB clean MIST corpus)
- `mist-voice/samples/raw/mist_supercut.segments.tsv` (605 curated segments -- which spans are clean MIST)
- Longer clean takes in `mist-voice/samples/reference/_archive/` (a 27s analytical clip, a 15s monologue, etc.)
- Source of truth is the private `BaesTheorem/mist-voice-data` repo (git-lfs).

**Why it waits for the Mini / a GPU:** you cannot train on the 8GB M1 Air. The M4 base (16GB) has real headroom to prep the dataset and orchestrate, but XTTS/F5 fine-tuning is CUDA-centric -- the fastest path is renting a cloud GPU (vast.ai / RunPod, ~$1-3 for a ~1hr run) and pulling the resulting weights back. The Mini is the always-on box that can drive that unattended.

**Rough recipe (flesh out when picked up):**
1. Prep dataset: segment the supercut per the TSV into clean utterance WAVs + a transcript manifest (Whisper is already in the mist-voice venv for transcription).
2. Pick the trainer: XTTS-v2 fine-tune (keeps the current pipeline, most faithful cloner) or F5-TTS (research-grade). Chatterbox venv (`mist-voice/.venv-chatterbox`) stays around regardless -- it's the fast + MIT engine we'd want for any future **real-time** GPU voice (e.g. the "Hey MIST" smart-speaker satellite).
3. Rent GPU, run the fine-tune, evaluate by ear against the current XTTS baseline.
4. If it wins, wire the fine-tuned model into `say.py`/`serve.py`/`mist-say`, update `mist-voice/README.md`'s "Final voice config" section, and commit.

**Keep, don't retread:** Chatterbox was evaluated and passed on for *cloning fidelity* -- don't re-run that A/B. The open lever is fine-tuning, not another zero-shot engine.

## Estimated total effort

- Hardware: ~$600 one-time.
- Setup: one weekend afternoon (4-5 hours).
- Stabilization: 1 week of light monitoring.
- Recurring cost: ~$1/month electricity.
