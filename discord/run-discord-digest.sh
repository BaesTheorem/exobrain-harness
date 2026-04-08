#!/bin/bash
# Wrapper script for launchd to run Discord digest fetch
# Uses Homebrew python3 which has proper file access permissions

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

cd "/Users/alexhedtke/Documents/Exobrain harness/discord" || exit 1

python3 discord-digest-fetch.py
