#!/bin/bash
# Wrapper script for launchd to trigger Supernote processing
# Finds the latest Claude Code CLI and runs /process-supernote

export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

LOG_DIR="/tmp"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if ! command -v claude &>/dev/null; then
    osascript -e 'display notification "Claude CLI not found — cannot process Supernote files" with title "Exobrain ERROR" sound name "Basso"'
    exit 1
fi

# Check if there are actually .note files
SUPERNOTE_DIR="$HOME/My Drive/Supernote/Note"
LOG_FILE="$HOME/Documents/Exobrain harness/processing-log.json"

if [ ! -d "$SUPERNOTE_DIR" ]; then
    exit 0
fi

# Count .note files
FILE_COUNT=$(find "$SUPERNOTE_DIR" -name "*.note" -type f 2>/dev/null | wc -l | tr -d ' ')
if [ "$FILE_COUNT" -eq 0 ]; then
    exit 0
fi

# Run Claude with the process-supernote prompt
claude \
    --print \
    --dangerously-skip-permissions \
    --project-dir "$HOME/Documents/Exobrain harness" \
    --prompt "Run /process-supernote to check for and process any new or modified Supernote files." \
    2>"$LOG_DIR/exobrain-supernote-$TIMESTAMP.err"

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    ERROR_MSG=$(tail -1 "$LOG_DIR/exobrain-supernote-$TIMESTAMP.err" 2>/dev/null | head -c 100)
    osascript -e "display notification \"Supernote processing failed (exit $EXIT_CODE): $ERROR_MSG\" with title \"Exobrain ERROR\" sound name \"Basso\""
    echo "[$TIMESTAMP] FAILED (exit $EXIT_CODE)" >> "$LOG_DIR/exobrain-supernote-failures.log"
    echo "  stderr: $ERROR_MSG" >> "$LOG_DIR/exobrain-supernote-failures.log"
fi

# Clean up error file if empty
[ ! -s "$LOG_DIR/exobrain-supernote-$TIMESTAMP.err" ] && rm -f "$LOG_DIR/exobrain-supernote-$TIMESTAMP.err"
