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

# Bail out if every transcript already has a matching entry in the processing log.
# Otherwise this watcher fires Claude every 30 min just to be told "nothing new".
#
# Dedup is by filename + create_time. Plaud reuses the placeholder filename
# `create_tim ... .txt` (and `... (N).txt` variants) for any unrenamed recording,
# so filename-only matching has caused new recordings to be silently swallowed
# whenever a previously-processed file had the same placeholder name. Any file
# whose name starts with "create_tim" is therefore always treated as
# unprocessed here — the skill's step 1 does the real dedup using create_time.
/usr/bin/python3 - "$GDRIVE_PLAUD" "$PROCESSING_LOG" <<'PY'
import json, os, sys
plaud_dir, log_file = sys.argv[1], sys.argv[2]
files = [n for n in os.listdir(plaud_dir) if n.endswith((".md", ".txt"))]
if not files:
    sys.exit(0)
try:
    log = json.load(open(log_file))
except (FileNotFoundError, json.JSONDecodeError):
    sys.exit(1)
processed = {e.get("id") for e in log if e.get("source") == "plaud"}
def is_unprocessed(fname):
    if fname.startswith("create_tim"):
        return True
    return fname not in processed
sys.exit(1 if any(is_unprocessed(f) for f in files) else 0)
PY
if [ $? -eq 0 ]; then
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
