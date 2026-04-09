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

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

CLAUDE_BIN="$(command -v claude)"
WORK_DIR="$HARNESS_DIR"

cd "$WORK_DIR"

# --dangerously-skip-permissions is required because this runs as a daemon
# and cannot present permission prompts to the user
exec tail -f /dev/null | "$CLAUDE_BIN" \
    --print \
    --verbose \
    --input-format stream-json \
    --output-format stream-json \
    --dangerously-skip-permissions
