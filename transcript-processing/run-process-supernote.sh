#!/bin/bash
# Wrapper script for launchd to trigger Supernote processing
# Finds the latest Claude Code CLI and runs /process-supernote

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

LOG_DIR="/tmp"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if ! command -v claude &>/dev/null; then
    osascript -e 'display notification "Claude CLI not found — cannot process Supernote files" with title "Exobrain ERROR" sound name "Basso"'
    # Touch the watched directory so launchd re-triggers when it next checks,
    # rather than silently consuming the WatchPaths event
    touch "$GDRIVE_SUPERNOTE" 2>/dev/null
    exit 1
fi

# Check if there are actually .note files
SUPERNOTE_DIR="$GDRIVE_SUPERNOTE"
LOG_FILE="$PROCESSING_LOG"

if [ ! -d "$SUPERNOTE_DIR" ]; then
    exit 0
fi

# Bail out if every .note file is already in the processing log with mtime >= file's mtime.
# Single Python pass — fast even with hundreds of files.
/usr/bin/python3 - "$SUPERNOTE_DIR" "$LOG_FILE" <<'PY'
import json, os, sys
from datetime import datetime, timezone

supernote_dir, log_file = sys.argv[1], sys.argv[2]
parent = os.path.dirname(supernote_dir)

files = []
for root, _, names in os.walk(supernote_dir):
    for n in names:
        if n.endswith(".note"):
            files.append(os.path.join(root, n))
if not files:
    sys.exit(0)  # nothing to process

try:
    log = json.load(open(log_file))
except (FileNotFoundError, json.JSONDecodeError):
    sys.exit(1)  # no/broken log → process

# Latest processedAt per id
latest = {}
for e in log:
    eid = e.get("id"); ts = e.get("processedAt")
    if eid and ts and ts > latest.get(eid, ""):
        latest[eid] = ts

for f in files:
    rel = os.path.relpath(f, parent)
    logged = latest.get(rel)
    if not logged:
        sys.exit(1)  # never processed
    try:
        logged_epoch = datetime.strptime(logged.rstrip("Z").split(".")[0], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        sys.exit(1)
    if os.path.getmtime(f) > logged_epoch:
        sys.exit(1)  # file modified since last process
sys.exit(0)  # all clean
PY
PY_EXIT=$?
if [ $PY_EXIT -eq 0 ]; then
    exit 0
fi

# Run Claude with the process-supernote prompt (cd to harness dir for project context)
cd "$HARNESS_DIR"
# --dangerously-skip-permissions is required because launchd runs non-interactively
# and cannot present permission prompts to the user
claude \
    --print \
    --dangerously-skip-permissions \
    -p "Run /process-supernote to check for and process any new or modified Supernote files." \
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
