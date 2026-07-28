#!/bin/bash
# Mirror Substack posts into becomingstronger.github.io/posts.json.
# Triggered by launchd (com.exobrain.substack-sync), daily.
#
# Uses Homebrew python3, not /usr/bin/python3: the CommandLineTools binary
# lacks TCC Full Disk Access for ~/Documents under launchd, and the site repo
# lives there.

set -euo pipefail

cd "$(dirname "$0")"

/opt/homebrew/bin/python3 sync.py
