#!/bin/bash
# Keeps the Claude Code CLI current so the MIST Console's model picker (which
# discovers models by grepping the claude binary) surfaces new releases on its
# own. The Console never hardcodes model cards; a stale CLI is the only reason a
# new model would fail to appear. See project_mist_console_model_discovery memory.
#
# Uses the native `claude update`, which respects the npm-global install method.
# Notifies Alex only when the version actually changes (a new model may now be
# selectable after a Console reload). Runs daily via com.exobrain.claude-cli-update.

set -uo pipefail

# launchd hands us a minimal PATH, so `claude update` cannot find node/npm and
# aborts with "npm global folder isn't writable". Pin the real locations:
# node/npm live in Homebrew, claude in the npm-global prefix.
export PATH="/opt/homebrew/bin:$HOME/.npm-global/bin:/usr/bin:/bin:/usr/sbin:/sbin"

CLAUDE_BIN="$HOME/.npm-global/bin/claude"
NOTIFY="/Users/alexhedtke/Documents/Exobrain harness/mist-voice/bin/mist-notify"
LOG="/tmp/exobrain-claude-cli-update.log"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

if [ ! -x "$CLAUDE_BIN" ]; then
  echo "$(ts) FAIL claude binary not found at $CLAUDE_BIN" >>"$LOG"
  exit 1
fi

before="$("$CLAUDE_BIN" --version 2>/dev/null | awk '{print $1}')"
echo "$(ts) checking (current $before)" >>"$LOG"

# Native updater. Falls back to npm if the native path errors out.
if ! "$CLAUDE_BIN" update >>"$LOG" 2>&1; then
  echo "$(ts) native update failed, trying npm" >>"$LOG"
  npm update -g @anthropic-ai/claude-code >>"$LOG" 2>&1
fi

after="$("$CLAUDE_BIN" --version 2>/dev/null | awk '{print $1}')"

if [ -n "$after" ] && [ "$after" != "$before" ]; then
  echo "$(ts) UPDATED $before -> $after" >>"$LOG"
  # New models may now be discoverable. Ping Alex, clickable to the Console.
  "$NOTIFY" "Claude CLI updated to $after. Reload the Console to see any new model cards." \
    "MIST" Purr "http://localhost:5014" 2>/dev/null || true
else
  echo "$(ts) up to date ($after)" >>"$LOG"
fi
