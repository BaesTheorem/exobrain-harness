#!/bin/bash
# Wrapper script for launchd to trigger transcript processing
# Finds the latest Claude Code CLI and runs /process-transcript

export PATH="$HOME/.npm-global/bin:$PATH"

if ! command -v claude &>/dev/null; then
    osascript -e 'display notification "Claude CLI not found — cannot process transcripts" with title "Exobrain ERROR" sound name "Basso"'
    exit 1
fi

# Check if there are actually new files to process
PLAUD_DIR="$HOME/My Drive/Alex's Exobrain/Plaud"
LOG_FILE="$HOME/Documents/Exobrain harness/processing-log.json"

if [ ! -d "$PLAUD_DIR" ]; then
    exit 0
fi

# Count .md files in Plaud dir
FILE_COUNT=$(find "$PLAUD_DIR" -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
if [ "$FILE_COUNT" -eq 0 ]; then
    exit 0
fi

# Run Claude with the process-transcript prompt
claude \
    --print \
    --dangerously-skip-permissions \
    --project-dir "$HOME/Documents/Exobrain harness" \
    --prompt "Run /process-transcript to check for and process any new Plaud transcripts." \
    2>/dev/null
