#!/bin/bash
# Wrapper script for launchd to trigger transcript processing
# Finds the latest Claude Code CLI and runs /process-transcript

export PATH="$HOME/.npm-global/bin:$HOME/.local/bin:$PATH"

LOG_DIR="/tmp"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if ! command -v claude &>/dev/null; then
    osascript -e 'display notification "Claude CLI not found — cannot process transcripts" with title "Exobrain ERROR" sound name "Basso"'
    exit 1
fi

# Plaud lands transcripts in Google Drive; copy new ones into the Obsidian vault (iCloud)
PLAUD_GDRIVE="$HOME/My Drive/Plaud"
PLAUD_VAULT="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Plaud"
LOG_FILE="$HOME/Documents/Exobrain harness/processing-log.json"

if [ ! -d "$PLAUD_GDRIVE" ]; then
    exit 0
fi

# Copy any new files from GDrive landing zone to vault
mkdir -p "$PLAUD_VAULT"
for f in "$PLAUD_GDRIVE"/*.{txt,md}; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    if [ ! -f "$PLAUD_VAULT/$base" ]; then
        cp "$f" "$PLAUD_VAULT/$base"
    fi
done

# Count .md/.txt files in vault Plaud dir
FILE_COUNT=$(find "$PLAUD_VAULT" -name "*.md" -o -name "*.txt" -type f 2>/dev/null | wc -l | tr -d ' ')
if [ "$FILE_COUNT" -eq 0 ]; then
    exit 0
fi

# Run Claude with the process-transcript prompt, capturing exit code
claude \
    --print \
    --dangerously-skip-permissions \
    --project-dir "$HOME/Documents/Exobrain harness" \
    --prompt "Run /process-transcript to check for and process any new Plaud transcripts." \
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
