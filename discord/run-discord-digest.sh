#!/bin/bash
# Wrapper script for launchd to run Discord digest fetch
# Uses Homebrew python3 which has proper file access permissions

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

cd "$HARNESS_DIR/discord" || exit 1

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT=$(python3 discord-digest-fetch.py 2>&1)
EXIT_CODE=$?
printf '%s\n' "$OUTPUT"

if [ $EXIT_CODE -ne 0 ]; then
    TAIL=$(printf '%s\n' "$OUTPUT" | tail -3 | tr '\n' ' ' | head -c 200)
    echo "[$TIMESTAMP] FAILED (exit $EXIT_CODE)" >> /tmp/exobrain-discord-digest-failures.log
    echo "  detail: $TAIL" >> /tmp/exobrain-discord-digest-failures.log
    NOTIFY="$SCRIPT_DIR/mist-voice/bin/mist-notify"
    [ -x "$NOTIFY" ] && "$NOTIFY" "discord-digest failed (exit $EXIT_CODE)" "MIST" Basso console
fi

exit $EXIT_CODE
