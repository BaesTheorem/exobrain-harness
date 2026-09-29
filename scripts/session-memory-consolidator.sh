#!/bin/bash
# Daily session-memory consolidator (launchd: com.exobrain.session-memory-consolidator, 23:00).
#
# Orchestrates bin/session-memory (scripts/session_memory.py) over the day:
#   1. write   one run per Claude Code transcript modified today, in every
#              project dir (Console chats live in many cwds). The writer skips
#              sessions the PreCompact hook already covered, writes a _delta
#              for tails, and judges trivial sessions itself.
#   2. prune   stale _skip markers only; session notes and zettels are kept.
# The engine frames transcripts as untrusted, scans everything it writes, and
# rebuilds Maps/ and Index.md; nothing here touches note content.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

# Unattended: the guard hook (.claude/hooks/guard-unattended.py) applies to
# anything the writer spawns; the writer itself runs claude with no tools.
export MIST_UNATTENDED=1

TODAY="$(date +%Y-%m-%d)"
SM="$SCRIPT_DIR/bin/session-memory"
FAIL_LOG="$EXOBRAIN_LOG_DIR/session-memory-failures.log"
NOTIFY="$SCRIPT_DIR/mist-voice/bin/mist-notify"
PARALLEL=3

# The 23:00 fire often lands right as the Mac wakes, before DNS answers, and
# `claude` dies instantly with ENOTFOUND. Wait for a usable network first.
if ! "$SCRIPT_DIR/scripts/wait-for-network.sh" api.anthropic.com 300; then
    echo "[$(date)] No network after 300s. Skipping consolidation."
    exit 0
fi

echo "[$(date)] Starting session-memory consolidation"
"$SM" prune

# Today's transcripts across every project dir (top level only: nested
# subagent transcripts are sidechains and belong to their parent).
TRANSCRIPTS="$(find "$HOME/.claude/projects" -mindepth 2 -maxdepth 2 -name '*.jsonl' -type f \
    -newermt "$TODAY 00:00" 2>/dev/null | sort)"
if [ -z "$TRANSCRIPTS" ]; then
    echo "[$(date)] No transcripts modified today. Done."
    exit 0
fi
COUNT="$(printf '%s\n' "$TRANSCRIPTS" | wc -l | tr -d ' ')"
echo "[$(date)] $COUNT transcript(s) modified today"

# caffeinate: the run must survive system sleep (a 2026-07-13 run stalled 10
# hours across a sleep). Each writer call has its own 600 s model timeout and a
# per-session lock, so a few in parallel are safe.
printf '%s\n' "$TRANSCRIPTS" | caffeinate -is xargs -P "$PARALLEL" -I{} \
    "$SM" write "{}" --trigger consolidator --quiet
WRITE_STATUS=$?

NOTES_TODAY="$(find "$SESSION_NOTES_DIR" -maxdepth 1 -name "${TODAY}_*.md" ! -name '*_skip.md' 2>/dev/null | wc -l | tr -d ' ')"
# xargs exits 123 when any writer call failed (model timeout, no JSON, exit != 0).
if [ "$WRITE_STATUS" -ne 0 ]; then
    REASON="writer failures (xargs exit $WRITE_STATUS); $NOTES_TODAY note(s) still written"
    {
        echo "[$(date +%Y%m%d_%H%M%S)] FAILED ($REASON)"
        tail -n 12 "$EXOBRAIN_LOG_DIR/session-memory-writer.log" 2>/dev/null | sed 's/^/  /'
    } >> "$FAIL_LOG"
    [ -x "$NOTIFY" ] && "$NOTIFY" "Session-memory consolidator: $REASON" "MIST" Basso console || true
    echo "[$(date)] Done (FAILED: $REASON)"
    exit 1
fi
if [ -x "$NOTIFY" ] && [ "$NOTES_TODAY" -gt 0 ]; then
    "$NOTIFY" "Consolidated $NOTES_TODAY session note(s) for $TODAY" "Exobrain" Purr \
        "obsidian://open?vault=Exobrain&file=Claude/Index" --group memory || true
fi
echo "[$(date)] Done ($NOTES_TODAY note(s) today)"
