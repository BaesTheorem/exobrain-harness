#!/bin/bash
# Wrapper script for launchd to trigger transcript processing
# Finds the latest Claude Code CLI and runs /process-transcript

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

LOG_DIR="/tmp"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if ! command -v claude &>/dev/null; then
    osascript -e 'display notification "Claude CLI not found — cannot process transcripts" with title "Exobrain ERROR" sound name "Basso"'
    # Touch the watched directory so launchd re-triggers when it next checks,
    # rather than silently consuming the WatchPaths event
    touch "$GDRIVE_PLAUD" 2>/dev/null
    exit 1
fi

# Plaud transcripts stay in Google Drive — processed and renamed in-place
if [ ! -d "$GDRIVE_PLAUD" ]; then
    exit 0
fi

# Count .md/.txt files in GDrive Plaud dir
FILE_COUNT=$(find "$GDRIVE_PLAUD" \( -name "*.md" -o -name "*.txt" \) -type f 2>/dev/null | wc -l | tr -d ' ')
if [ "$FILE_COUNT" -eq 0 ]; then
    exit 0
fi

# Run Claude with the process-transcript prompt (cd to harness dir for project context)
cd "$HARNESS_DIR"
# --dangerously-skip-permissions is required because launchd runs non-interactively
# and cannot present permission prompts to the user
claude \
    --print \
    --dangerously-skip-permissions \
    -p "Run /process-transcript to check for and process any new Plaud transcripts." \
    2>"$LOG_DIR/exobrain-process-$TIMESTAMP.err"

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    ERROR_MSG=$(tail -1 "$LOG_DIR/exobrain-process-$TIMESTAMP.err" 2>/dev/null | head -c 100)
    osascript -e "display notification \"Transcript processing failed (exit $EXIT_CODE): $ERROR_MSG\" with title \"Exobrain ERROR\" sound name \"Basso\""

    # Log the failure for debugging
    echo "[$TIMESTAMP] FAILED (exit $EXIT_CODE)" >> "$LOG_DIR/exobrain-plaud-failures.log"
    echo "  stderr: $ERROR_MSG" >> "$LOG_DIR/exobrain-plaud-failures.log"
fi

# Clean up error file if empty
[ ! -s "$LOG_DIR/exobrain-process-$TIMESTAMP.err" ] && rm -f "$LOG_DIR/exobrain-process-$TIMESTAMP.err"
