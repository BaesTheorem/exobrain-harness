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

# Plaud lands transcripts in Google Drive; copy new ones into the Obsidian vault
LOG_FILE="$PROCESSING_LOG"

if [ ! -d "$GDRIVE_PLAUD" ]; then
    exit 0
fi

# Move new files from GDrive landing zone to vault (move, not copy,
# so Zapier's truncated filenames don't linger and get re-copied)
mkdir -p "$PLAUD_VAULT"
for f in "$GDRIVE_PLAUD"/*.{txt,md}; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    if [ ! -f "$PLAUD_VAULT/$base" ]; then
        mv "$f" "$PLAUD_VAULT/$base"
    else
        # Already in vault — remove the GDrive copy
        rm "$f"
    fi
done

# Count .md/.txt files in vault Plaud dir
FILE_COUNT=$(find "$PLAUD_VAULT" \( -name "*.md" -o -name "*.txt" \) -type f 2>/dev/null | wc -l | tr -d ' ')
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
