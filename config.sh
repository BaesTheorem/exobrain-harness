#!/bin/bash
# Central path configuration for the Exobrain harness.
# All shell scripts source this file instead of hardcoding paths.
#
# To adapt this system for your own use, update these paths once here.
# Note: launchd plists and JSON configs cannot source shell variables —
# those must be updated separately (see README "Adapting This System").

# Core directories
HARNESS_DIR="$HOME/Documents/Exobrain harness"
VAULT_DIR="$HOME/Exobrain"

# Google Drive sources (require Google Drive for Desktop)
# Raw data stays in GDrive — backed up, persistent, and replayable
GDRIVE_PLAUD="$HOME/My Drive/Plaud"
GDRIVE_SUPERNOTE="$HOME/My Drive/Supernote/Note"
GDRIVE_DISCORD="$HOME/My Drive/Discord"
GDRIVE_IMESSAGE="$HOME/My Drive/iMessage"

# Vault subdirectories
DAILY_NOTES_DIR="$VAULT_DIR/Daily notes"
PEOPLE_DIR="$VAULT_DIR/Areas/Relationships & Community/People"
HEALTH_LOG_DIR="$VAULT_DIR/Areas/Health & Fitness/Health Log"
AUDITS_DIR="$VAULT_DIR/Areas/Exobrain/Audits"

# Harness runtime files
PROCESSING_LOG="$HARNESS_DIR/processing-log.json"
DISCORD_DIGEST="$HARNESS_DIR/discord/discord-digest.json"
SESSION_MEMORY_DIR="$VAULT_DIR/Claude"

# Backup (see backup-exobrain.sh). One collective archive per run bundles the
# harness, the vault, and every sibling repo's gitignored data into Google
# Drive. Retention is grandfather-father-son: a single archive can satisfy more
# than one tier, so nothing is stored twice. Tune the counts here.
BACKUP_DIR="$HOME/My Drive/Exobrain backups"
KEEP_DAILY=7      # last N daily archives
KEEP_WEEKLY=4     # newest archive of each of the last N ISO weeks
KEEP_MONTHLY=6    # newest archive of each of the last N calendar months
# Where to discover sibling git repos whose gitignored data should be backed up
# (the harness and vault are captured in full separately, so they're skipped).
REPO_SCAN_ROOT="$HOME/Documents"
# Repos whose gitignored data should NOT be swept into the archive (huge
# regenerable assets, VM images). Skips are logged loudly in the backup log.
BACKUP_EXCLUDE_REPOS=(
    "Cannonballs Resurrection"   # 14GB of game/VM assets; tripled the archive and ENOSPC'd the run (2026-07)
)
# Per-repo cap on gitignored-data size (MB). Repos over the cap are skipped with
# a loud log line instead of silently sinking the backup (disk, Drive quota).
BACKUP_REPO_MAX_MB=2048
# Abort a run early if the local staging volume has less than this much free.
BACKUP_MIN_FREE_GB=20

# Out-of-tree files/dirs captured verbatim under a home-extras/ namespace in the
# archive. These are secrets + local state that live OUTSIDE the harness, the
# vault, and the git-repo sweep (either above $HOME/Documents, or not git repos),
# so nothing else would catch them. Paths are relative to $HOME; missing entries
# are silently skipped. node_modules/.venv/caches/history-DB/logs are filtered in
# backup-exobrain.sh, so listing a whole app dir stays lean. The large/ephemeral
# Claude dirs (projects/, channels/ except the Discord token, plugins/) are
# deliberately NOT listed — only the irreplaceable settings + the bot token.
EXTRA_INCLUDES=(
    ".plaud"                                    # Plaud MCP OAuth token + device IDs
    ".claude/settings.json"                     # global Claude Code settings (bypassPermissions etc.)
    ".claude/settings.local.json"
    ".claude/CLAUDE.md"                         # global persona / user instructions
    ".claude/mist-global.md"                    # symlink hop for the @import (paths with spaces break)
    ".claude/projects/-Users-alexhedtke-Documents-Exobrain-harness/memory"  # MIST's single persistent memory store (projects/ is otherwise excluded)
    ".claude.json"                              # user-scope MCP servers (fitbit/withings creds) + Claude CLI state
    ".claude/.mcp.json"                         # global things3 MCP definition
    ".claude/statusline-command.sh"
    ".claude/channels/discord/.env"             # Discord bot token (channels/ is otherwise excluded)
    ".claude/channels/discord/access.json"
    "Documents/Claude Code/mcp-fitbit-main"     # Fitbit MCP: .env + token + build (NOT a git repo)
    "Documents/ytmusic-manager/browser.json"    # YT Music auth (not a git repo)
    "Documents/osrs-companion/credentials.json" # OSRS agent auth (not a git repo)
    "Documents/home-assistant/config"           # HA hand-built config (history DB excluded below)
)

# Optional second backup destination OFF Google Drive (external disk or another
# cloud mount). Empty = disabled. Google Drive is both the backup target AND a
# primary data source, so a single account lockout takes both at once; a copy
# here breaks that single point of failure. Each verified archive is copied here.
LOCAL_BACKUP_DIR=""

# External dependencies (outside the harness)
FITBIT_TOKEN="$HOME/Documents/Claude Code/mcp-fitbit-main/.fitbit-token.json"

# Ensure HOME is set (launchd doesn't set it)
export HOME="${HOME:-$(dscl . -read /Users/$(whoami) NFSHomeDirectory | awk '{print $2}')}"

# Claude CLI (npm global or local bin — whichever is found)
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
