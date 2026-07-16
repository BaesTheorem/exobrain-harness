#!/bin/bash
# Wrapper script for launchd to trigger transcript processing
# Finds the latest Claude Code CLI and runs /process-transcript

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

LOG_DIR="/tmp"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Serialize plaud/supernote processing: both append to processing-log.json.
# macOS ships no flock(1), so python takes flock(2) on the inherited FD; the
# lock lives on the open file description and holds for this script's lifetime.
exec 200>"/tmp/exobrain-processing.lock"
/usr/bin/python3 -c '
import fcntl, sys, time
deadline = time.time() + 1800
while True:
    try:
        fcntl.flock(200, fcntl.LOCK_EX | fcntl.LOCK_NB)
        sys.exit(0)
    except OSError:
        if time.time() >= deadline:
            sys.exit(1)
        time.sleep(5)
' || { echo "[$(date +%Y%m%d_%H%M%S)] SKIPPED: could not acquire processing lock in 30m" >> /tmp/exobrain-plaud-failures.log; exit 0; }

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
TIMEOUT_SEC=900
claude \
    --print \
    --dangerously-skip-permissions \
    -p "Run /process-transcript to check for and process any new Plaud transcripts." \
    >"$LOG_DIR/exobrain-process-$TIMESTAMP.out" \
    2>"$LOG_DIR/exobrain-process-$TIMESTAMP.err" &
CLAUDE_PID=$!
(
    sleep $TIMEOUT_SEC
    if kill -0 $CLAUDE_PID 2>/dev/null; then
        kill -TERM $CLAUDE_PID 2>/dev/null
        sleep 5
        kill -KILL $CLAUDE_PID 2>/dev/null
        echo "[$TIMESTAMP] TIMEOUT after ${TIMEOUT_SEC}s — claude --print killed" >> "$LOG_DIR/exobrain-plaud-failures.log"
        osascript -e "display notification \"Plaud processor hung — killed after ${TIMEOUT_SEC}s\" with title \"Exobrain ERROR\" sound name \"Basso\""
    fi
) &
KILLER_PID=$!
wait $CLAUDE_PID 2>/dev/null
EXIT_CODE=$?
kill $KILLER_PID 2>/dev/null
wait $KILLER_PID 2>/dev/null

# claude's stdout was captured to a per-run file; replay it to launchd's
# StandardOutPath so the running processing history is preserved as before.
cat "$LOG_DIR/exobrain-process-$TIMESTAMP.out" 2>/dev/null

if [ $EXIT_CODE -ne 0 ]; then
    ERROR_MSG=$(tail -1 "$LOG_DIR/exobrain-process-$TIMESTAMP.err" 2>/dev/null | head -c 100)
    # claude --print prints API errors (e.g. "Connection closed mid-response") to
    # stdout, not stderr. When stderr is empty, fall back to the stdout tail so the
    # failure log is never blank (that blank is exactly what made 2026-07-15 hard to diagnose).
    [ -z "$ERROR_MSG" ] && ERROR_MSG=$(tail -3 "$LOG_DIR/exobrain-process-$TIMESTAMP.out" 2>/dev/null | tr '\n' ' ' | head -c 200)
    osascript -e "display notification \"Transcript processing failed (exit $EXIT_CODE): $ERROR_MSG\" with title \"Exobrain ERROR\" sound name \"Basso\""

    # Log the failure for debugging
    echo "[$TIMESTAMP] FAILED (exit $EXIT_CODE)" >> "$LOG_DIR/exobrain-plaud-failures.log"
    echo "  detail: $ERROR_MSG" >> "$LOG_DIR/exobrain-plaud-failures.log"
fi

# Clean up error file if empty
[ ! -s "$LOG_DIR/exobrain-process-$TIMESTAMP.err" ] && rm -f "$LOG_DIR/exobrain-process-$TIMESTAMP.err"
# Drop the per-run stdout copy on success (already replayed above); keep it on
# failure for post-mortem.
[ $EXIT_CODE -eq 0 ] && rm -f "$LOG_DIR/exobrain-process-$TIMESTAMP.out"
