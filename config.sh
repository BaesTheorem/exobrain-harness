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

# External dependencies (outside the harness)
FITBIT_TOKEN="$HOME/Documents/Claude Code/mcp-fitbit-main/.fitbit-token.json"

# Ensure HOME is set (launchd doesn't set it)
export HOME="${HOME:-$(dscl . -read /Users/$(whoami) NFSHomeDirectory | awk '{print $2}')}"

# Claude CLI (npm global or local bin — whichever is found)
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
