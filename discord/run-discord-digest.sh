#!/bin/bash
# Wrapper script for launchd to run Discord digest fetch
# Uses Homebrew python3 which has proper file access permissions

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

cd "$HARNESS_DIR/discord" || exit 1

python3 discord-digest-fetch.py
