#!/bin/bash
# Mirror Substack posts into becomingstronger.github.io/posts.json.
# Triggered by launchd (com.exobrain.substack-sync), daily.
#
# Uses Homebrew python3, not /usr/bin/python3: the CommandLineTools binary
# lacks TCC Full Disk Access for ~/Documents under launchd, and the site repo
# lives there.

set -euo pipefail

cd "$(dirname "$0")"

# launchd fires this the instant the Mac wakes if 07:23 was slept through, and
# DNS isn't up yet -- every late fire failed with "nodename nor servname
# provided" while every on-time fire succeeded. Wait for a real round trip
# first; no network at all means skip the run rather than log a fake failure.
if ! ../scripts/wait-for-network.sh substack.com 300; then
    echo "$(date '+%Y-%m-%dT%H:%M:%S') SKIP no network after 300s"
    exit 0
fi

/opt/homebrew/bin/python3 sync.py
