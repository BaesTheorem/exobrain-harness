#!/bin/bash
# Scheduled wrapper for refresh.py. See README.md.
# Managed by launchd: com.exobrain.ios-sideload-refresh (10:30 and 20:30 local)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HARNESS="$(cd "$SCRIPT_DIR/.." && pwd)"

# Minting a fresh provisioning profile is an online operation against Apple,
# so a run that fires the instant the Mac wakes would fail on DNS. Same gate
# every other scheduled job here uses.
if ! "$HARNESS/scripts/wait-for-network.sh" developerservices2.apple.com 300; then
    echo "[$(date)] No network after 300s. Skipping; the next run will catch it."
    exit 0
fi

# Builds are slow enough that the lid closing mid-run is a real failure mode,
# and a half-installed refresh is worse than a skipped one.
exec caffeinate -i /usr/bin/python3 "$SCRIPT_DIR/refresh.py"
