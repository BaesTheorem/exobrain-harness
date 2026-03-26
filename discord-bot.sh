#!/bin/bash
# Discord bot launcher — runs claude in a screen session so it has a TTY
# Managed by launchd: com.exobrain.discord-bot

SESSION_NAME="discord-bot"
CLAUDE_BIN="/Users/alexhedtke/.npm-global/bin/claude"
WORK_DIR="/Users/alexhedtke/Documents/Exobrain harness"

# Kill any existing session
/usr/bin/screen -S "$SESSION_NAME" -X quit 2>/dev/null

# Start a new detached screen session running claude with the discord channel
cd "$WORK_DIR"
/usr/bin/screen -dmS "$SESSION_NAME" "$CLAUDE_BIN" \
    --channels plugin:discord@claude-plugins-official

# Wait for the screen session — if it dies, this script exits and launchd restarts it
while /usr/bin/screen -list | grep -q "$SESSION_NAME"; do
    sleep 30
done
