#!/bin/bash
# Weekly bodyguard passive OSINT scan.
# Triggered by com.exobrain.bodyguard-weekly.plist (Sundays at 8 AM).
#
# Writes the raw scan plan/results to /tmp, then posts a macOS notification
# inviting Alex to open Claude Code and ingest findings into Security Log.md.
# The heavy lifting (Google dorks, broker presence) happens in Claude with
# WebSearch; this script just refreshes HIBP and builds the query plan.

set -euo pipefail

HARNESS_DIR="/Users/alexhedtke/Documents/Exobrain harness"
SKILL_DIR="${HARNESS_DIR}/.claude/skills/cybersecurity-bodyguard"
SCAN_OUT="/tmp/bodyguard-weekly-$(date +%Y%m%d).json"
LOG="/tmp/bodyguard-weekly.log"

exec >>"$LOG" 2>&1
echo "--- $(date) ---"

# Load .env so HIBP_API_KEY is available
if [ -f "${HARNESS_DIR}/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "${HARNESS_DIR}/.env"
    set +a
fi

cd "$HARNESS_DIR"

if ! python3 "${SKILL_DIR}/scripts/osint_self_scan.py" --mode full > "$SCAN_OUT"; then
    osascript -e 'display notification "Weekly bodyguard scan failed — check /tmp/bodyguard-weekly.log" with title "Exobrain URGENT" sound name "Basso"'
    exit 1
fi

# Count preliminary findings (HIBP breaches) from the raw output.
HIBP_BREACHES=$(python3 -c "
import json, sys
with open('$SCAN_OUT') as f:
    data = json.load(f)
hibp = data.get('findings', {}).get('hibp', {})
if not isinstance(hibp, dict):
    print(0); sys.exit()
total = 0
for v in hibp.values():
    if isinstance(v, list):
        total += len(v)
print(total)
" 2>/dev/null || echo "?")

TITLE="Bodyguard scan ready"
MSG="Scan written to ${SCAN_OUT}. HIBP breaches detected: ${HIBP_BREACHES}. Open Claude Code and say 'ingest bodyguard scan' to log findings to Security Log.md."

osascript -e "display notification \"${MSG}\" with title \"${TITLE}\" sound name \"Purr\""
echo "Notification posted. Scan file: $SCAN_OUT"
