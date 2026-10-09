#!/bin/bash
# Rotates the scheduled-job logs in ~/Library/Logs/exobrain.
#
# Why this exists: those logs used to live in /tmp, where macOS reaped them on
# its own. That reaping is also what destroyed the evidence of a failure before
# anyone could read it (2026-07-28), so the logs moved somewhere durable. The
# tradeoff is that nothing prunes them now -- launchd appends to
# StandardOutPath forever. This puts a ceiling back on without giving up the
# history that matters.
#
# Two rules:
#   1. Any log over MAX_KB is rotated to .1 (single generation; the previous .1
#      is discarded). Rotation is a COPY-then-truncate, not a move: launchd
#      holds an open file descriptor on StandardOutPath, and renaming the file
#      would leave the job writing into an unlinked inode nobody can read.
#   2. Timestamped per-run artifacts (job-scan-*.out/.err, bodyguard-weekly-*.json)
#      are deleted after KEEP_DAYS.
#
# Scheduled weekly by com.exobrain.rotate-logs.plist.

set -uo pipefail

LOG_DIR="$HOME/Library/Logs/exobrain"
MAX_KB=512
KEEP_DAYS=30

[ -d "$LOG_DIR" ] || exit 0

rotated=0
for f in "$LOG_DIR"/*.log "$LOG_DIR"/*.err "$LOG_DIR"/*.out; do
    [ -f "$f" ] || continue
    case "$f" in *.1) continue ;; esac
    size_kb=$(( $(stat -f %z "$f") / 1024 ))
    if [ "$size_kb" -gt "$MAX_KB" ]; then
        cp "$f" "$f.1" && : > "$f"
        echo "rotated $(basename "$f") (${size_kb}KB)"
        rotated=$((rotated + 1))
    fi
done

pruned=$(find "$LOG_DIR" \( -name 'job-scan-2*' -o -name 'bodyguard-weekly-2*.json' \) \
    -mtime +${KEEP_DAYS} -print -delete 2>/dev/null | wc -l | tr -d ' ')

echo "$(date '+%Y-%m-%d %H:%M:%S') rotate-logs: ${rotated} rotated, ${pruned} pruned"

# Disk hygiene, same weekly cadence. The 2026-10-08 cleanup found 11GB in the
# uv cache, 4GB in npm, 2GB in brew and 11GB of finished scratch in the harness
# tmp/ dir; none of it has an owner that prunes it. Package caches re-fill on
# demand. tmp/ entries are scratch by convention and go after TMP_DAYS.
TMP_DIR="$(cd "$(dirname "$0")/.." && pwd)/tmp"
TMP_DAYS=21
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
command -v uv >/dev/null && uv cache prune -q 2>/dev/null
command -v npm >/dev/null && npm cache verify >/dev/null 2>&1
command -v brew >/dev/null && brew cleanup -s --prune=all >/dev/null 2>&1
if [ -d "$TMP_DIR" ]; then
    swept=$(find "$TMP_DIR" -mindepth 1 -maxdepth 1 -mtime +${TMP_DAYS} -print -exec rm -rf {} + 2>/dev/null | wc -l | tr -d ' ')
    echo "disk-hygiene: swept ${swept} tmp entries older than ${TMP_DAYS} days"
fi
free_gb=$(( $(df -k /System/Volumes/Data | awk 'NR==2 {print $4}') / 1048576 ))
echo "disk-hygiene: ${free_gb}GB free"
if [ "$free_gb" -lt 60 ]; then
    "$(dirname "$0")/../mist-voice/bin/mist-notify" \
        "Disk is down to ${free_gb}GB free after the weekly cleanup. The backup needs 30." \
        "MIST" Basso --discord 2>/dev/null || true
fi
exit 0
