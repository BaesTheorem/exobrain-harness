# Transcript Processing

File-watcher pipeline for two input streams that produce notes Claude needs to process:

- **Plaud Note** voice recordings — `.txt` / `.md` transcripts that Plaud syncs into Google Drive
- **Supernote A5X** handwritten notes — `.note` files that the Supernote app syncs into Google Drive

When new files land, launchd fires Claude Code in `--print` mode to run the relevant skill (`/process-transcript` or `/process-supernote`). Each skill extracts tasks, events, notes, and people mentions and routes them into Things 3, Google Calendar, and Obsidian.

## Files

| File | Purpose |
|------|---------|
| `run-process-transcript.sh` | launchd wrapper invoked when new Plaud transcripts land. Bails out fast if every file is already in `processing-log.json`; otherwise runs `claude --print -p "Run /process-transcript ..."`. Notifies on failure. |
| `run-process-supernote.sh` | launchd wrapper invoked when new Supernote files land. Same pattern — fast bailout if every `.note` file's mtime is already covered by the processing log. |
| `supernote-parser.py` | Standalone helper used by `/process-supernote`. Reads a `.note` file with `supernotelib`, exports each page as PNG, and computes SHA-256 page hashes for change detection. |
| `youtube-transcript.py` | Standalone helper that fetches a YouTube transcript via `yt-dlp` (manual captions, falls back to auto-captions). Used when Alex asks Claude to summarize a YouTube video. |
| `com.exobrain.plaud-watcher.plist` | launchd plist. WatchPaths: `~/My Drive/Plaud`. Throttle 30s, fallback StartInterval 1800s in case Google Drive mounts after launchd's initial check. |
| `com.exobrain.supernote-watcher.plist` | launchd plist. WatchPaths: `~/My Drive/Supernote/Note`. Throttle 30s. |

Both wrapper scripts source `../config.sh` for shared paths (`HARNESS_DIR`, `GDRIVE_PLAUD`, `GDRIVE_SUPERNOTE`, `PROCESSING_LOG`).

## Install

The plists must live as **real files** in `~/Library/LaunchAgents/`, not symlinks — TCC blocks symlinks into `~/Documents/` from loading at boot, so the jobs would never start at login.

```bash
cp com.exobrain.plaud-watcher.plist ~/Library/LaunchAgents/
cp com.exobrain.supernote-watcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.exobrain.plaud-watcher.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.supernote-watcher.plist
launchctl list | grep com.exobrain
```

After any plist edit, copy the file again — the LaunchAgents copy is the authoritative one.

## Dependencies

- **Claude CLI** (`claude` in PATH). Both wrappers invoke it with `--dangerously-skip-permissions` because launchd runs non-interactively and cannot present permission prompts.
- **Python 3.12+** (Homebrew at `/opt/homebrew/bin/python3.12`). The wrappers use `/usr/bin/python3` only for the small dedup pre-check; the skills themselves run inside Claude.
- **Python packages**:
  - `supernotelib` — used by `supernote-parser.py` to extract pages from `.note` files
  - `yt-dlp` — used by `youtube-transcript.py`
- **Google Drive for Desktop** mounting `~/My Drive/Plaud` and `~/My Drive/Supernote/Note`.

```bash
pip3 install supernotelib
brew install yt-dlp
```

## Config (`../config.sh`)

The wrappers expect these env vars from the harness-root `config.sh`:

| Var | Example | Purpose |
|-----|---------|---------|
| `HARNESS_DIR` | `/Users/alexhedtke/Documents/Exobrain harness` | Working directory for the Claude session |
| `GDRIVE_PLAUD` | `/Users/alexhedtke/My Drive/Plaud` | Watched Plaud directory |
| `GDRIVE_SUPERNOTE` | `/Users/alexhedtke/My Drive/Supernote/Note` | Watched Supernote directory |
| `PROCESSING_LOG` | `$HARNESS_DIR/processing-log.json` | Idempotency log read by the dedup pre-check |

Failure logs land in `/tmp/exobrain-plaud-failures.log` and `/tmp/exobrain-supernote-failures.log`; transient stderr files are written to `/tmp/exobrain-process-<timestamp>.err` and cleaned up if empty.
