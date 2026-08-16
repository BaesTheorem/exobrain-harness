#!/bin/bash
# Wrapper script for launchd to run Discord digest fetch
# Uses Homebrew python3 which has proper file access permissions

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

cd "$HARNESS_DIR/discord" || exit 1

# launchd fires a StartInterval job the instant the Mac wakes, before Wi-Fi has
# reassociated, so the fetch dies on DNS with "nodename nor servname provided".
# Confirmed 2026-08-16: DarkWake at 09:46:30, digest failed at 09:46:32 (Errno 8),
# which then left the digest blind for 20h. Same fix already used by substack-sync,
# session-memory-consolidator, run-job-scan, and auto-commit-harness. No network at
# all means skip quietly -- a sleeping laptop is not a failure worth alerting on.
if ! "$SCRIPT_DIR/scripts/wait-for-network.sh" discord.com 300; then
    echo "$(date '+%Y-%m-%dT%H:%M:%S') SKIP no network after 300s"
    exit 0
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT=$(python3 discord-digest-fetch.py 2>&1)
EXIT_CODE=$?
printf '%s\n' "$OUTPUT"

if [ $EXIT_CODE -ne 0 ]; then
    TAIL=$(printf '%s\n' "$OUTPUT" | tail -3 | tr '\n' ' ' | head -c 200)
    echo "[$TIMESTAMP] FAILED (exit $EXIT_CODE)" >> "$EXOBRAIN_LOG_DIR/discord-digest-failures.log"
    echo "  detail: $TAIL" >> "$EXOBRAIN_LOG_DIR/discord-digest-failures.log"
    NOTIFY="$SCRIPT_DIR/mist-voice/bin/mist-notify"
    [ -x "$NOTIFY" ] && "$NOTIFY" "discord-digest failed (exit $EXIT_CODE)" "MIST" Basso console
fi

exit $EXIT_CODE
