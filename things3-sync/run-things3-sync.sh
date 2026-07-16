#!/bin/bash
# Things 3 ↔ Obsidian sync runner
# Wraps the Python script so launchd uses bash (which typically has Full Disk Access)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.." || exit 1

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT=$(/usr/bin/python3 things3-sync/things3-obsidian-sync.py 2>&1)
EXIT_CODE=$?
printf '%s\n' "$OUTPUT"

if [ $EXIT_CODE -ne 0 ]; then
    TAIL=$(printf '%s\n' "$OUTPUT" | tail -3 | tr '\n' ' ' | head -c 200)
    echo "[$TIMESTAMP] FAILED (exit $EXIT_CODE)" >> /tmp/exobrain-things3-sync-failures.log
    echo "  detail: $TAIL" >> /tmp/exobrain-things3-sync-failures.log
    NOTIFY="$SCRIPT_DIR/../mist-voice/bin/mist-notify"
    [ -x "$NOTIFY" ] && "$NOTIFY" "things3-sync failed (exit $EXIT_CODE)" "MIST" Basso console
fi

exit $EXIT_CODE
