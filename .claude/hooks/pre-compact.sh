#!/bin/bash
# PreCompact hook: save this session's memory BEFORE the history is summarized.
#
# Claude Code hands us {session_id, transcript_path, trigger, cwd} on stdin and
# gives the hook 600 s, but the writer is a headless claude run of its own and
# should never hold compaction hostage, so it is detached here and the hook
# returns at once. Stdout from a PreCompact hook is not shown to the model.
#
# Registered machine-wide in ~/.claude/settings.json (not in this repo's
# .claude/settings.json) because the memory store is single and Console chats
# run in many working directories; see README "Session memory".
# The writer lives in this repo: bin/session-memory -> scripts/session_memory.py.
set -u
export MIST_UNATTENDED=1   # the writer is headless; the guard hook applies to anything it spawns
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
HARNESS="$(cd "$HERE/../.." && pwd)"
INPUT="$(cat)"
read -r TRANSCRIPT TRIGGER < <(printf '%s' "$INPUT" | /usr/bin/python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d.get("transcript_path") or "", d.get("trigger") or "auto")
' 2>/dev/null) || exit 0
[ -n "${TRANSCRIPT:-}" ] && [ -f "$TRANSCRIPT" ] || exit 0
LOG="$HOME/Library/Logs/exobrain/session-memory-writer.log"
mkdir -p "$(dirname "$LOG")"
# mist-progress draws the run as an inline bar in the Console chat that is
# compacting (it reads MIST_CONSOLE_SESSION from the environment we inherit)
# and is a no-op outside the Console.
PROGRESS="$(command -v mist-progress || echo "$HOME/Documents/mist-console/bin/mist-progress")"
if [ -x "$PROGRESS" ]; then
    nohup "$PROGRESS" run --label "Saving session memory before compaction" -- \
        "$HARNESS/bin/session-memory" write "$TRANSCRIPT" --trigger "compact-$TRIGGER" \
        >> "$LOG" 2>&1 < /dev/null &
else
    nohup "$HARNESS/bin/session-memory" write "$TRANSCRIPT" --trigger "compact-$TRIGGER" \
        >> "$LOG" 2>&1 < /dev/null &
fi
disown 2>/dev/null || true
exit 0
