#!/bin/bash
# Unattended KC Urbex pass, driven by com.exobrain.kcurbex-watch.
#
# /bin/bash rather than /bin/sh: under launchd, /bin/sh cannot read scripts out of
# ~/Documents and exits 126.
#
# The board is a small volunteer forum on shared hosting. This runs twice a day and the
# client paces itself between requests; do not raise either rate.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="$(cd "$HERE/.." && pwd)"
LOG_DIR="$HOME/.claude/channels/kcurbex"
mkdir -p "$LOG_DIR"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

# A launchd job that fires on wake routinely beats DNS to the punch.
if [ -x "$HARNESS/scripts/wait-for-network.sh" ]; then
    "$HARNESS/scripts/wait-for-network.sh" || {
        echo "[$STAMP] no network; skipping this pass" >> "$LOG_DIR/watch.log"
        exit 0
    }
fi

echo "[$STAMP] starting watch pass" >> "$LOG_DIR/watch.log"
if "$HERE/bin/kcurbex" watch >> "$LOG_DIR/watch.log" 2>&1; then
    echo "[$STAMP] pass complete" >> "$LOG_DIR/watch.log"
else
    code=$?
    echo "[$STAMP] pass FAILED (exit $code)" >> "$LOG_DIR/watch.log"
    # A silent failure here is the thing worth knowing about: the watcher going quiet
    # looks identical to "no new sites" from the outside.
    "$HARNESS/mist-voice/bin/mist-notify" \
        "KC Urbex watcher failed (exit $code) -- check ~/.claude/channels/kcurbex/watch.log" \
        "KC Urbex" "Silent" "console" 2>/dev/null || true
    exit "$code"
fi
