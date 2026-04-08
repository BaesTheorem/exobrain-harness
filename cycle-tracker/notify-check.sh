#!/bin/bash
# Daily notification check for [Partner]'s cycle tracker
# Run via launchd or scheduled task daily at 8:00 AM

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESULT=$(python3 "$SCRIPT_DIR/app.py" --check-notify)

if [[ "$RESULT" == NOTIFY:* ]]; then
    DATE="${RESULT#NOTIFY:}"
    FORMATTED=$(date -j -f "%Y-%m-%d" "$DATE" "+%B %d")

    # macOS notification
    osascript -e "display notification \"[Partner]'s period is expected tomorrow ($FORMATTED). Be extra thoughtful today.\" with title \"Exobrain — Cycle Tracker\" sound name \"Purr\""

    # Discord notification via Claude (if bot is running)
    echo "Period notification sent for $FORMATTED"
fi
