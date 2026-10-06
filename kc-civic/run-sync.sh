#!/bin/bash
# Unattended kc-civic pass, driven by com.exobrain.kc-civic.
#
# Syncs the configured KC public meetings to Google Calendar, then preps remarks
# for meetings in the next few days whose agenda is out. The prep step starts a
# headless Claude on third-party agenda text, so MIST_UNATTENDED=1 is exported
# here and again in prep.py (the guard hook applies either way).
#
# /bin/bash rather than /bin/sh: under launchd, /bin/sh cannot read scripts in
# ~/Documents and exits 126.
set -uo pipefail
export MIST_UNATTENDED=1
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="$(cd "$HERE/.." && pwd)"
LOG_DIR="$HOME/Library/Logs/exobrain"
LOG="$LOG_DIR/kc-civic.log"
mkdir -p "$LOG_DIR"
stamp() { date '+%Y-%m-%d %H:%M:%S'; }

# A wake-fired run routinely beats DNS.
if [ -x "$HARNESS/scripts/wait-for-network.sh" ]; then
    "$HARNESS/scripts/wait-for-network.sh" webapi.legistar.com 300 || {
        echo "[$(stamp)] no network; skipping" >> "$LOG"; exit 0; }
fi

echo "[$(stamp)] sync pass" >> "$LOG"
if "$HERE/bin/kc-civic" sync >> "$LOG" 2>&1; then
    echo "[$(stamp)] done" >> "$LOG"
else
    code=$?
    echo "[$(stamp)] FAILED (exit $code)" >> "$LOG"
    "$HARNESS/mist-voice/bin/mist-notify" \
        "(>_<) KC Civic sync failed (exit $code). Log: ~/Library/Logs/exobrain/kc-civic.log" \
        "KC Civic" "Basso" "$LOG" --group watchers --discord \
        --context "$(tail -n 40 "$LOG")" 2>/dev/null || true
    exit "$code"
fi
