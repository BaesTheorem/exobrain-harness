#!/bin/bash
# Daily full-folder backup of the Exobrain harness to Google Drive.
# Keeps the last 3 backups; only prunes after verifying the new archive.
#
# Schedule: daily at 2:00 AM via com.exobrain.backup.plist
#
# Excludes runtime caches (__pycache__, .DS_Store, .claude/projects, etc.)
# but DOES include .env and .mcp.json — these are needed to restore a working
# harness, and Google Drive is the user's own private storage.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.sh"

BACKUP_DIR="$HOME/My Drive/Exobrain backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="exobrain-harness-$TIMESTAMP.tar.gz"
BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"
KEEP=3

mkdir -p "$BACKUP_DIR"

# Freshness guard: skip if a verified backup already exists from the last 20h.
# This pairs with RunAtLoad in the plist so login/boot catches up after a
# power-off, but doesn't spam duplicate backups during normal logins.
# 20h is intentionally < 24h so the daily 2 AM run is never suppressed.
if find "$BACKUP_DIR" -name 'exobrain-harness-*.tar.gz' -mmin -1200 -print -quit 2>/dev/null | grep -q .; then
    echo "[$(date)] Recent backup exists (<20h old); skipping."
    exit 0
fi

# Build archive of the entire harness folder, excluding only caches/runtime junk.
HARNESS_PARENT="$(dirname "$HARNESS_DIR")"
HARNESS_BASENAME="$(basename "$HARNESS_DIR")"

tar \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude="$HARNESS_BASENAME/.claude/projects" \
    --exclude="$HARNESS_BASENAME/.claude/channels" \
    --exclude="$HARNESS_BASENAME/.claude/worktrees" \
    --exclude="$HARNESS_BASENAME/.claude/session-memories" \
    --exclude="$HARNESS_BASENAME/.claude/plugins" \
    -czf "$BACKUP_PATH" \
    -C "$HARNESS_PARENT" \
    "$HARNESS_BASENAME"

# Verify: file exists, is non-empty, and is a valid gzip tar.
if [ ! -s "$BACKUP_PATH" ]; then
    echo "[$(date)] ERROR: backup file missing or empty: $BACKUP_PATH" >&2
    osascript -e 'display notification "Backup file missing or empty" with title "Exobrain URGENT" sound name "Basso"'
    exit 1
fi

if ! tar -tzf "$BACKUP_PATH" >/dev/null 2>&1; then
    echo "[$(date)] ERROR: backup archive is corrupted: $BACKUP_PATH" >&2
    rm -f "$BACKUP_PATH"
    osascript -e 'display notification "Backup archive corrupted" with title "Exobrain URGENT" sound name "Basso"'
    exit 1
fi

BACKUP_SIZE=$(du -h "$BACKUP_PATH" | cut -f1)
echo "[$(date)] Backup verified: $BACKUP_PATH ($BACKUP_SIZE)"

# Only after verification: prune old daily full-folder backups, keep last $KEEP.
# Note: this pattern intentionally does NOT match legacy `exobrain-backup-*`
# archives from the previous weekly curated job — those are left in place.
ls -t "$BACKUP_DIR"/exobrain-harness-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while IFS= read -r old; do
    echo "[$(date)] Pruning old backup: $old"
    rm -f "$old"
done

echo "[$(date)] Backup complete."
