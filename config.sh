#!/bin/bash
# Central path configuration for the Exobrain harness.
# All shell scripts source this file instead of hardcoding paths.
#
# To adapt this system for your own use, update these paths once here.
# Note: launchd plists and JSON configs cannot source shell variables —
# those must be updated separately (see README "Adapting This System").

# Core directories
HARNESS_DIR="$HOME/Documents/Exobrain harness"
VAULT_DIR="$HOME/Documents/Exobrain"

# Google Drive sources (require Google Drive for Desktop)
GDRIVE_PLAUD="$HOME/My Drive/Plaud"
GDRIVE_SUPERNOTE="$HOME/My Drive/Supernote/Note"

# Vault subdirectories
PLAUD_VAULT="$VAULT_DIR/Plaud"
DAILY_NOTES_DIR="$VAULT_DIR/Daily notes"
PEOPLE_DIR="$VAULT_DIR/People"
HEALTH_LOG_DIR="$VAULT_DIR/Health Log"
AUDITS_DIR="$VAULT_DIR/Audits"

# Harness runtime files
PROCESSING_LOG="$HARNESS_DIR/processing-log.json"
DISCORD_DIGEST="$HARNESS_DIR/discord/discord-digest.json"
SESSION_MEMORY_DIR="$HARNESS_DIR/.claude/session-memory"

# External dependencies (outside the harness)
FITBIT_TOKEN="$HOME/Documents/Claude Code/mcp-fitbit-main/.fitbit-token.json"

# Claude CLI (npm global or local bin — whichever is found)
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"
