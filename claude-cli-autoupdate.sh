#!/bin/bash
# Keeps the Claude Code CLI current so the MIST Console's model picker (which
# discovers models by grepping the claude binary) surfaces new releases on its
# own. The Console never hardcodes model cards; a stale CLI is the only reason a
# new model would fail to appear. See project_mist_console_model_discovery memory.
#
# Uses the native `claude update`, whichever install method is in play.
# Notifies Alex only when the version actually changes (a new model may now be
# selectable after a Console reload). Runs daily via com.exobrain.claude-cli-update.

set -uo pipefail

# launchd hands us a minimal PATH, so `claude update` cannot find node/npm and
# aborts with "npm global folder isn't writable". Pin the real locations:
# node/npm live in Homebrew, claude in either ~/.local/bin (native installer)
# or the npm-global prefix (global npm install).
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.npm-global/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Resolve rather than pin. On 2026-08-15 the 2.1.233 update migrated the install
# from the npm prefix to the native ~/.local/bin location and deleted the old
# binary, which broke every caller that had the npm path baked in.
CLAUDE_BIN="$(command -v claude)"
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
NOTIFY="/Users/alexhedtke/Documents/Exobrain harness/mist-voice/bin/mist-notify"
LOG_DIR="$HOME/Library/Logs/exobrain"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/claude-cli-update.log"

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

# Re-resolve: an update that migrates install methods moves the binary out from
# under us, so the pre-update path may no longer exist.
CLAUDE_BIN="$(command -v claude)"
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
after="$("$CLAUDE_BIN" --version 2>/dev/null | awk '{print $1}')"

if [ -z "$after" ]; then
  # An empty version means the CLI is gone, not that it is current. This used to
  # fall through to the "up to date ()" branch and say nothing, which is how a
  # vanished binary sat unnoticed until the Console failed on every send.
  echo "$(ts) FAIL claude unusable after update (was $before) — binary missing or moved" >>"$LOG"
  "$NOTIFY" "Claude CLI is missing after the update. The Console cannot start sessions until it is reinstalled." \
    "MIST URGENT" Basso console --urgency timeSensitive 2>/dev/null || true
  exit 1
fi

if [ "$after" != "$before" ]; then
  echo "$(ts) UPDATED $before -> $after" >>"$LOG"
  # New models may now be discoverable. Ping Alex, clickable to the Console.
  "$NOTIFY" "Claude CLI updated to $after. Reload the Console to see any new model cards." \
    "MIST" Purr "http://localhost:5014" 2>/dev/null || true
else
  echo "$(ts) up to date ($after)" >>"$LOG"
fi
