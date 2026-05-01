# Scripts

Top-level utility scripts that run on a launchd schedule, separate from the input-watcher pipelines in `transcript-processing/` and `things3-sync/`.

## Files

| File | Purpose |
|------|---------|
| `session-memory-consolidator.sh` | Daily backstop for session memory. Reads today's Claude Code transcripts (`~/.claude/projects/-Users-alexhedtke-Documents-Exobrain-harness/*.jsonl`) and writes session-memory files for any significant sessions that didn't write their own at end-of-session. Also prunes old memory: regular session memories after 14 days, daily digests after 30 days. |
| `vault-snapshot.sh` | Builds a compact Markdown digest of `Dashboard.md` plus active project notes (skipping `Archive/` and `Someday/`) and writes it to `~/.claude/projects/-Users-alexhedtke-Documents-Exobrain-harness/vault-snapshot.md`. The session-start hook injects this so every Claude session opens with current priorities loaded. Warns if the file exceeds 4 KB. |
| `com.exobrain.session-memory-consolidator.plist` | launchd plist for `session-memory-consolidator.sh`. `StartCalendarInterval`: 23:00 daily. `RunAtLoad: false` (only runs on schedule). |
| `com.exobrain.vault-snapshot.plist` | launchd plist for `vault-snapshot.sh`. `StartCalendarInterval`: 06:00 daily. `RunAtLoad: false`. |

Both shell scripts source `../config.sh` for `HARNESS_DIR`, `VAULT_DIR`, and `SESSION_MEMORY_DIR`.

## Install

Copy plists into `~/Library/LaunchAgents/` as real files — NOT symlinks. macOS TCC blocks login-time loading of symlinks pointing into `~/Documents/`, so a symlinked plist will never run at boot.

```bash
cp com.exobrain.session-memory-consolidator.plist ~/Library/LaunchAgents/
cp com.exobrain.vault-snapshot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.exobrain.session-memory-consolidator.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.vault-snapshot.plist
launchctl list | grep com.exobrain
```

After editing a plist, copy it again — the LaunchAgents copy is what launchd actually reads.

## Logs

Both scripts log to `~/.claude/channels/` (gitignored):

- `session-memory-consolidator.log` / `session-memory-consolidator-error.log`
- `vault-snapshot.log` / `vault-snapshot-error.log`

## Dependencies

- `bash` (system)
- `claude` CLI in PATH (used by the consolidator)
- Python 3.12+ (used by `vault-snapshot.sh` for the inline frontmatter parser)
- The plists set `PATH` to include `/Users/alexhedtke/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin` so launchd jobs find `claude` and `python3`.
