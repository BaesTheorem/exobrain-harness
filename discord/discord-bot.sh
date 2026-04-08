#!/bin/bash
# Discord bot launcher — keeps a persistent Claude session with the Discord plugin
# Managed by launchd: com.exobrain.discord-bot
#
# The Discord plugin (MCP server) auto-loads because it's enabled in settings.json.
# It connects to Discord, listens for messages, and sends them to Claude via
# notifications/claude/channel. Claude processes them and replies using plugin tools.
#
# We use --print with stream-json input to keep Claude alive as a daemon.
# tail -f /dev/null holds stdin open indefinitely.

export PATH="/usr/local/bin:/opt/homebrew/bin:/Users/alexhedtke/.npm-global/bin:/Users/alexhedtke/.local/bin:/usr/bin:/bin"

CLAUDE_BIN="/Users/alexhedtke/.npm-global/bin/claude"
WORK_DIR="/Users/alexhedtke/Documents/Exobrain harness"

cd "$WORK_DIR"

exec tail -f /dev/null | "$CLAUDE_BIN" \
    --print \
    --verbose \
    --input-format stream-json \
    --output-format stream-json \
    --dangerously-skip-permissions
