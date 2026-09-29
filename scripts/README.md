# Scripts

Top-level utility scripts that run on a launchd schedule, separate from the input-watcher pipelines in `transcript-processing/` and `things3-sync/`.

## Files

| File | Purpose |
|------|---------|
| `session_memory.py` | The session-memory engine (CLI: `bin/session-memory`). Condenses a Claude Code transcript, asks a headless `claude` (no tools) for the session note plus Zettelkasten operations as JSON, and writes the notes itself. Owns the vault layout under `Claude/`: `Sessions/` (kept; zettels cite them), `Zettel/` (permanent, one idea per note, timestamp ids), `Maps/` and `Index.md` (generated). Subcommands: `write`, `backfill`, `migrate`, `index`, `lint`, `prune`, `condense`, `consolidate`. `write` is called by the PreCompact hook (`.claude/hooks/pre-compact.sh`); `consolidate` is the nightly backstop that runs `write` over every transcript modified today in every `~/.claude/projects/*/` dir (3 in parallel), then `prune`. |
| `vault-snapshot.sh` | Builds a compact Markdown digest of `Dashboard.md` plus active project notes (skipping `Archive/` and `Someday/`) and writes it to `~/.claude/projects/<slug>/vault-snapshot.md`. The session-start hook injects this so every Claude session opens with current priorities loaded. Warns if the file exceeds 4 KB. |
| `com.exobrain.session-memory-consolidator.plist` | launchd plist for `session_memory.py consolidate`. `StartCalendarInterval`: 23:00 daily. `RunAtLoad: false` (only runs on schedule). It spawns `/opt/homebrew/bin/python3` directly, no shell wrapper: a Homebrew interpreter exec'd by a launchd shell is denied `~/Documents` by TCC (EPERM). |
| `com.exobrain.vault-snapshot.plist` | launchd plist for `vault-snapshot.sh`. `StartCalendarInterval`: 06:00 daily. `RunAtLoad: false`. |

`vault-snapshot.sh` sources `../config.sh` for `HARNESS_DIR`, `VAULT_DIR`, `SESSION_MEMORY_DIR` (and its `SESSION_NOTES_DIR` / `SESSION_ZETTEL_DIR` children), and `CLAUDE_PROJECT_SLUG`.

`<slug>` is Claude Code's per-project data directory name: the project's absolute path with `/` and spaces replaced by dashes (for the owner, `-Users-alexhedtke-Documents-Exobrain-harness`). `config.sh` derives it from `HARNESS_DIR` as `CLAUDE_PROJECT_SLUG`, and `vault-snapshot.sh` uses that, so a different clone path needs no edit there.

## Install

Copy plists into `~/Library/LaunchAgents/` as real files -- NOT symlinks. macOS TCC blocks login-time loading of symlinks pointing into `~/Documents/`, so a symlinked plist will never run at boot.

```bash
cp com.exobrain.session-memory-consolidator.plist ~/Library/LaunchAgents/
cp com.exobrain.vault-snapshot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.exobrain.session-memory-consolidator.plist
launchctl load ~/Library/LaunchAgents/com.exobrain.vault-snapshot.plist
launchctl list | grep com.exobrain
```

After editing a plist, copy it again -- the LaunchAgents copy is what launchd actually reads.

## Logs

Both jobs log to `~/.claude/channels/` (gitignored):

- `session-memory-consolidator.log` / `session-memory-consolidator-error.log`
- `vault-snapshot.log` / `vault-snapshot-error.log`

## Dependencies

- `bash` (system)
- `claude` CLI in PATH (used by the consolidator)
- Python 3.12+ (used by `vault-snapshot.sh` for the inline frontmatter parser)
- The plists set `PATH` to include `/Users/alexhedtke/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin` so launchd jobs find `claude` and `python3`.
