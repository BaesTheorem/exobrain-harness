#!/bin/bash
# Backup critical Exobrain data to a timestamped archive
# Run manually or via cron: 0 2 * * 0 (weekly, Sunday 2 AM)
#
# What's backed up:
#   - processing-log.json (irreplaceable transaction history)
#   - .env (credentials/tokens)
#   - .mcp.json (MCP config with credentials)
#   - All skills (SKILL.md files)
#   - All scripts
#   - CLAUDE.md (system manifest)
#   - Memory files
#
# What's NOT backed up (too large, already synced elsewhere):
#   - Obsidian vault (synced via Obsidian Sync)
#   - Plaud transcripts (synced via Google Drive)
#   - Supernote files (synced via Google Drive)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.sh"

BACKUP_DIR="$HOME/My Drive/Exobrain backups"
# Claude Code auto-generates this path from the project directory — it will differ per user
MEMORY_DIR="$HOME/.claude/projects/-Users-$(whoami)-Documents-Exobrain-harness/memory"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="exobrain-backup-$TIMESTAMP"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"

mkdir -p "$BACKUP_PATH"

# Core files
cp "$HARNESS_DIR/processing-log.json" "$BACKUP_PATH/" 2>/dev/null
cp "$HARNESS_DIR/.env" "$BACKUP_PATH/" 2>/dev/null
cp "$HARNESS_DIR/.mcp.json" "$BACKUP_PATH/" 2>/dev/null
cp "$HARNESS_DIR/CLAUDE.md" "$BACKUP_PATH/" 2>/dev/null
cp "$HARNESS_DIR/requirements.txt" "$BACKUP_PATH/" 2>/dev/null

# Scripts (now organized in subdirectories)
# -maxdepth 2 is intentionally shallow: it covers HARNESS_DIR/*.{py,sh,plist} and
# HARNESS_DIR/*/*.{py,sh,plist}. Skill scripts at .claude/skills/*/scripts/* are
# captured by the wholesale skills copy below (see "Skills" section).
mkdir -p "$BACKUP_PATH/scripts"
find "$HARNESS_DIR" -maxdepth 2 -name "*.py" -o -name "*.sh" -o -name "*.plist" | while read -r f; do
    cp "$f" "$BACKUP_PATH/scripts/" 2>/dev/null
done

# Skills
if [ -d "$HARNESS_DIR/.claude/skills" ]; then
    cp -r "$HARNESS_DIR/.claude/skills" "$BACKUP_PATH/skills" 2>/dev/null
fi

# Settings
mkdir -p "$BACKUP_PATH/settings"
cp "$HARNESS_DIR/.claude/settings.json" "$BACKUP_PATH/settings/" 2>/dev/null
cp "$HARNESS_DIR/.claude/settings.local.json" "$BACKUP_PATH/settings/" 2>/dev/null

# Hooks
if [ -d "$HARNESS_DIR/.claude/hooks" ]; then
    cp -r "$HARNESS_DIR/.claude/hooks" "$BACKUP_PATH/hooks" 2>/dev/null
fi

# Memory
if [ -d "$MEMORY_DIR" ]; then
    cp -r "$MEMORY_DIR" "$BACKUP_PATH/memory" 2>/dev/null
fi

# Compress
cd "$BACKUP_DIR"
tar -czf "$BACKUP_NAME.tar.gz" "$BACKUP_NAME" 2>/dev/null
rm -rf "$BACKUP_PATH"

# Prune old backups (keep last 8 = ~2 months of weekly backups)
ls -t "$BACKUP_DIR"/exobrain-backup-*.tar.gz 2>/dev/null | tail -n +9 | xargs rm -f 2>/dev/null

BACKUP_SIZE=$(du -h "$BACKUP_DIR/$BACKUP_NAME.tar.gz" | cut -f1)
echo "Backup complete: $BACKUP_DIR/$BACKUP_NAME.tar.gz ($BACKUP_SIZE)"
