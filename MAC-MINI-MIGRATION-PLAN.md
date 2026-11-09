# Mac Mini Server Migration Plan

> **Historical plan.** Last substantive edit 2026-07-15. The inventory below lists 10 jobs as of that date, while 80 `com.exobrain.*` / `com.mist.*` jobs were loaded on 2026-09-28 (`launchctl list | grep -cE 'exobrain|mist'`), and "Discord is the only off-network entry point" no longer holds: `phone/` (Twilio voice calls) and the MIST Console iOS tunnel are also reachable from outside. For rebuilding a machine use `RESTORE.md`; for the current job list use the generated launchd table in `README.md` (`maintenance/bin/launchd-table`). Kept for the heartbeat-versus-client design, which still applies if the split happens. The [client devices](#client-devices-claude-code-on-every-device) section (added 2026-11-09) is current.

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
| MyChart           | `mychart login` per account (Keychain passkeys never copy) |

## What does NOT sync (manual copy required, one-time)

These are gitignored or local-only -- copy from MacBook to Mini during setup:

- `/Users/alexhedtke/Documents/Exobrain harness/.env` (Withings + other credentials)
- `~/.plaud/tokens-mcp.json` and `~/.plaud/tokens.json`
- `~/.config/fitbit/` (Fitbit refresh tokens)
- `~/.config/withings/` (if present beyond `.env`)
- Discord bot token (lives in `~/.claude/channels/discord/` per the bot script)
- `~/.claude/` -- global settings, skills, memory directory
  - When more than one device runs Claude Code, the memory directory also needs a continuous sync. See [client devices](#client-devices-claude-code-on-every-device), Phase 5 step 3.
- Any OAuth caches for cloud MCPs (Gmail, Calendar, Drive) -- re-authorize from Claude.ai if needed
- MyChart: `mychart/data/` (copy), then `mychart login <name>` per account on the Mini; never copy the Keychain passkeys

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
5. Re-authorize any cloud MCPs that need it (Gmail, Calendar, Drive via claude.ai); run `mychart login <name>` for each MyChart account.

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

Discord was the only off-network entry point when this plan was written (see the banner at the top for what has changed since). No tunnel software needed -- Discord traffic is outbound from the Mini, so as long as the Mini has internet, the bot works from anywhere your phone has Discord.

If a future need for SSH / Screen Sharing from outside the home network emerges, revisit Tailscale (free for personal use, install on Mini + MacBook + iPhone, gives stable reachable hostname). Out of scope for the initial migration.

The client devices need this access: they connect to the Mini through SSH. See [client devices](#client-devices-claude-code-on-every-device).

## Single-heartbeat rules (commit these to memory)

1. **Watchers and schedulers run on Mini only.** MacBook plists stay disabled.
2. **Discord bot runs on Mini only.** One token, one connection.
3. **Manual Claude sessions are permitted on all devices, with the client rules** in [client devices](#client-devices-claude-code-on-every-device). (Changed 2026-11-09. The previous rule is in the [corrections ledger](#corrections-ledger).)
4. **Don't run `daily-briefing`, `evening-winddown`, or `weekly-review` on both machines on the same day** -- they're idempotent-ish but Obsidian Sync conflicts on the daily note are annoying. Pick one (probably Mini if scheduled, MacBook if manual).
5. **If the Mini is down**, you can re-enable the MacBook plists as a fallback. Document this in a runbook (TBD).

## Client devices: Claude Code on every device

Added 2026-11-09. This section replaces the idea of one Claude Code on the Mini that operates on the other devices from a distance.

Claude Code's tools operate on the computer that runs the `claude` process. The [Remote Control docs](https://code.claude.com/docs/en/remote-control.md) say: "Execution and filesystem access stay on your machine." A session on the Mini can operate on the MacBook only through `ssh macbook '...'`, and it cannot use the MacBook's display for computer use or the iOS Simulator. Thus each device runs its own Claude Code, and each item in the table below has one owner.

### Owners

| Item | Owner | How the other devices get it |
|---|---|---|
| Code | the git remote | pull and push |
| Vault and the session-memory Zettelkasten | Obsidian Sync | no change |
| Things 3 | Things Cloud | no change |
| Auto-memory folder (`~/.claude/projects/<harness key>/memory/`) | the MacBook, with no sync | move it into the vault (Phase 5 step 3) |
| Watchers, scheduled tasks, Discord bot | the Mini | not applicable (single-heartbeat rules) |
| MCP servers with tokens or logins: Withings, Plaud, Fitbit, MyChart, LinkedIn | the Mini | stdio through SSH (Phase 5 step 4) |
| Remote HTTP MCP servers and claude.ai connectors | the remote server | they work on each device that signs in |
| MCP servers for a local app: Things 3, Blender, Godot, rea | each Mac that has the app | local. A device without the app uses the Mini's server through SSH |
| A live chat | the device that runs it | Remote Control and cross-session messaging (below) |

### Bridges between devices

Claude Code has these features (examined in the docs on 2026-11-09, with CLI 2.1.319):

- [Remote Control](https://code.claude.com/docs/en/remote-control.md). With `claude remote-control` (server mode) on the Mini, the Claude app (iOS or Android) and claude.ai/code can control the Mini's sessions. Server mode stops after approximately 10 minutes without network, so run it with launchd and `KeepAlive`. A start without a terminal stops at "Workspace not trusted", so first trust the harness folder one time in a terminal. Remote Control needs the claude.ai login, and it does not operate with an API key (`bin/claude-api-gate`).
- [Cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging.md). A session with Remote Control can send a plain-text task to a Remote Control session on a different machine (v2.1.225 or higher). Set `isolatePeerMachines: true` if each message to a different machine must wait for approval.
- [Desktop SSH sessions](https://code.claude.com/docs/en/desktop.md#ssh-sessions). The Desktop app on one Mac can open a session that runs on the other Mac. Desktop installs Claude Code in `~/.claude/remote/` on that Mac, and that Mac needs Remote Login (SSH with SFTP).

### Phase 5: set up the clients (after Phase 4)

1. On the Mini, set Remote Login to on (System Settings > General > Sharing). Put the public key of each client in `~/.ssh/authorized_keys`. To stop password login, put `PasswordAuthentication no` and `KbdInteractiveAuthentication no` in a file in `/etc/ssh/sshd_config.d/`. The macOS `sshd_config` includes that folder.
2. On each client, connect to the tailnet and add this host entry to `~/.ssh/config`:
   ```
   Host mini
     HostName <mini>.<tailnet>.ts.net
     ControlMaster auto
     ControlPath ~/.ssh/cm-%r@%h:%p
     ControlPersist 10m
     ServerAliveInterval 30
   ```
3. Move the auto-memory folder into the vault, for example to `Claude/Auto-memory/`. Then replace `~/.claude/projects/<harness key>/memory` with a symlink to that folder. The memory folders of the other projects point to this folder through symlinks, so they follow. Before the move, make sure that `bin/session-memory` and the other vault scripts do not read that folder. Do not put the folder in a git repo, because it contains personal data (the privacy rules in CLAUDE.md).
4. On each client, change the command of each token server in `mcp-lazy/servers.local.json` (gitignored, one file for each device) to `ssh -T mini '<server command>'`. The remote shell reads the command again, so put quotes around a path with a space (the harness path has one). A command through SSH does not load `~/.zprofile`, so use absolute paths, as `servers.local.json` does. Then remove the client's copies of those tokens (the Plaud, Fitbit and Withings items in "What does NOT sync"), because a token that refreshes on one device can become invalid on the other.
5. Give each client `MIST_HOST_ROLE=client`. Change `.claude/hooks/session-start.sh` so that a client does not do the launchd checks or the fallback processing of Plaud and Supernote files. Without this change, a MacBook session processes the files that the Mini's watchers process. (Not built.)
6. The Mini's routines commit frequently. Add a SessionStart hook on each client that runs `git pull --rebase --autostash` in the harness repo.
7. Run one MIST Console on each Mac. If a browser on the MacBook uses the Mini's Console, its chats run on the Mini. (Idea, not tested: a per-chat host setting in `bridge.py` that starts `claude` through `ssh`.)

### Checks

These checks do not use the reports from Claude:

- From a MacBook session, build a test app. Then, on the MacBook, examine the result with `ls` and `codesign -v`.
- With the Mini's watchers on and a MacBook session open, put one test Plaud file in the folder. Things 3 must show one new task, and only one.
- After one week, the MCP logs on each device must show no `invalid_grant` errors.
- `ssh mini true` must exit with code 0 from each client, on the home Wi-Fi and on a different network.

### The Pixel

The same model applies. Claude Code runs in the phone's Debian VM and uses the Mini's token servers through SSH. The setup, and the tests that wait for the phone, are in `docs/10-three-devices.md` of the private `pixel-claude-code` repo.

## Rollback plan

If migration causes problems:

1. `launchctl bootout` all Mini jobs.
2. `launchctl bootstrap` MacBook jobs again from the same plist files (still present).
3. Mini becomes a passive client until you try again.

No data is destroyed in either direction since everything syncs via Things Cloud / Obsidian Sync / Google Drive.

## Decisions locked

- **Computer-use MCP stays on the MacBook.** Mini runs headless, so screen/mouse control there is useless without a Screen Sharing session or HDMI dummy plug. MacBook is the natural home for interactive desktop control.
- **Tailscale carries SSH between the devices**, at home and away. (Changed 2026-11-09. The previous rule is in the [corrections ledger](#corrections-ledger).)
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

## Corrections ledger

Newest first. Each entry keeps the previous rule, what falsified it, the rule at this time, and the lesson.

### 2026-11-09: manual sessions on every device

- Was: "Manual Claude invocations are fine on either machine -- both can run skills, edit the vault, push commits, ask questions." (Single-heartbeat rule 3.)
- Falsified by: a manual session also starts the token MCP servers and the session-start hook. On the MacBook, the servers refresh the tokens that the token refresh caveat gives to the Mini, and the hook does the fallback processing that the Mini's watchers do.
- Now: manual sessions are permitted on all devices, with the client rules in [client devices](#client-devices-claude-code-on-every-device).
- Lesson: a rule about which machine does the work must include each stateful item that a session uses, for example MCP tokens and start-up hooks.

### 2026-11-09: Tailscale

- Was: "No Tailscale for now. Discord is the only remote entry point. Revisit if SSH/Screen Sharing from outside the home network becomes needed." (Decisions locked.)
- Falsified by: on 2026-09-28, the banner of this plan recorded that Discord was not the only entry point, but this decision did not change. Then the client devices needed SSH to the Mini, at home and away.
- Now: Tailscale carries SSH between the devices.
- Lesson: if a fact causes a decision ("the only remote entry point"), read the decision again when that fact changes.
