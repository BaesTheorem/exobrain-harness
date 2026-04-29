#!/bin/bash
# Daily session-memory consolidator
# Reads today's Claude Code transcripts and writes session memory files
# for any significant sessions that didn't write one.
# Managed by launchd: com.exobrain.session-memory-consolidator (23:00 local)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

CLAUDE_BIN="$(command -v claude)"
HARNESS="$HARNESS_DIR"
MEMORY_DIR="$HARNESS/.claude/session-memory"
TRANSCRIPTS_DIR="$HOME/.claude/projects/-Users-alexhedtke-Documents-Exobrain-harness"
TODAY="$(date +%Y-%m-%d)"

# Prune old memory files. Sessions/deltas: 14 days. Digests: 30 days.
# Uses mtime, which is fine since these files are write-once (deltas are
# separate files; the day's digest is the only one that gets overwritten,
# always with a fresh mtime).
PRUNED_SESSIONS=$(find "$MEMORY_DIR" -maxdepth 1 -name '*.md' ! -name '*_DIGEST.md' -type f -mtime +14 2>/dev/null | wc -l | tr -d ' ')
PRUNED_DIGESTS=$(find "$MEMORY_DIR" -maxdepth 1 -name '*_DIGEST.md' -type f -mtime +30 2>/dev/null | wc -l | tr -d ' ')
find "$MEMORY_DIR" -maxdepth 1 -name '*.md' ! -name '*_DIGEST.md' -type f -mtime +14 -delete 2>/dev/null || true
find "$MEMORY_DIR" -maxdepth 1 -name '*_DIGEST.md' -type f -mtime +30 -delete 2>/dev/null || true
[ "$PRUNED_SESSIONS" -gt 0 ] || [ "$PRUNED_DIGESTS" -gt 0 ] && \
    echo "[$(date)] Pruned $PRUNED_SESSIONS old session memories, $PRUNED_DIGESTS old digests"

# Build list of today's transcript files (modified today, jsonl only).
# We use mtime so sessions that were written-to today are picked up even if
# the file was originally created on a previous day.
TODAYS_TRANSCRIPTS="$(find "$TRANSCRIPTS_DIR" -maxdepth 1 -name '*.jsonl' -type f -newermt "$TODAY 00:00" ! -newermt "$TODAY 23:59:59" 2>/dev/null | sort)"

# All recent session memory files (last 14 days) — pass paths so the agent
# can read frontmatter (session_id, covered_through) for delta decisions.
RECENT_MEMORIES="$(find "$MEMORY_DIR" -maxdepth 1 -name '*.md' -type f -newermt "$(date -v-14d +%Y-%m-%d) 00:00" 2>/dev/null | sort)"
RECENT_MEMORIES="${RECENT_MEMORIES:-(none)}"

if [ -z "$TODAYS_TRANSCRIPTS" ]; then
    echo "[$(date)] No transcripts modified today. Exiting."
    exit 0
fi

# Build the prompt with a quoted heredoc (no shell expansion inside) and
# substitute placeholders with awk to avoid quoting hazards in the prompt body.
read -r -d '' PROMPT_TEMPLATE << 'PROMPTEOF' || true
You are running as a scheduled consolidator at 11pm. Your job is to review today's Claude Code session transcripts and write or update session memory files.

**Today's date:** __TODAY__

**Transcript files modified today (jsonl, one JSON object per line):**
__TODAYS_TRANSCRIPTS__

The basename of each transcript (without .jsonl) is the session_id — a UUID that uniquely identifies that Claude Code session.

**Recent session memory files (last 14 days) — read frontmatter to make delta decisions:**
__RECENT_MEMORIES__

Each memory file's frontmatter MAY contain:
- session_id: UUID matching a transcript filename (added by this consolidator)
- covered_through: ISO8601 timestamp of the last message that memory covered

Older / manually-written memories may lack these fields. Fall back to time-window matching (date + nearby HHMM).

**Your task:**

For each transcript jsonl path above:

1. Identify session_id from the filename (strip the .jsonl extension).

2. Read the transcript to find:
   - Timestamp of the first message and the last message
   - Whether the session involved meaningful work. Significant = processed data, made decisions, created tasks, discussed plans, took non-trivial actions. Trivial = quick lookups, weather checks, one-off questions. SKIP trivial.

3. Look for an existing memory for this session_id:
   - First check the frontmatter session_id field across the recent memories list.
   - If no session_id match, fall back to date-prefix + time-window match (any memory with same date prefix whose HHMM is within 60 min of any activity in this transcript).

4. Decide what to write:
   - No existing memory + significant: write a NEW memory at __MEMORY_DIR__/__TODAY___HHMM.md (HHMM = local time of last message). Frontmatter MUST include date, time, type, session_id, and covered_through (ISO8601 of last message).
   - Existing memory found, but transcript has new messages after covered_through: write a DELTA memory at __MEMORY_DIR__/__TODAY___HHMM_delta.md (HHMM = local time of latest new message). Frontmatter MUST include the same fields plus previous_memory (basename of the prior file). The body should ONLY summarize what happened after covered_through, not re-summarize the prior content. Reference the previous memory in Open Threads if relevant.
   - Existing memory found, and covered_through already includes the latest message: SKIP. Nothing new.
   - Existing memory found but lacks covered_through (legacy/manual): assume it covered everything up to its file mtime; only write a delta if there are messages after that mtime.

5. Body format (same for new and delta memories): use the /session-memory skill structure with sections Decisions, Data Pulled, Tasks Created, People Updated, Open Threads, Active Themes, Next Session Hint. Each section 2-5 bullets max.

6. Notification: count total files written (N = new + delta). If N > 0, run the macOS notification command:
   osascript -e "display notification \"Saved N session memories\" with title \"Exobrain\" sound name \"Purr\""
   (replace N with the actual count).

7. End with a one-line summary listing each transcript and what you did with it (wrote/delta/skipped, with reason).

8. **Daily digest** (always write after step 7): produce a rolling daily digest at __MEMORY_DIR__/__TODAY___DIGEST.md summarizing the whole day. This is loaded by the next session's startup hook for context, so make it dense and useful. Overwrite if it already exists.

   Frontmatter:
       date: __TODAY__
       type: daily_digest
       generated_at: <ISO8601 of now>
       sessions_covered: <N>   # count of session memories that exist for today (new + delta + skipped-but-already-covered)

   Body (target ~150 words, max 200): a short prose paragraph or tight bullet list covering:
   - **Active themes**: what was Alex working on across the day's sessions? (1-3 bullets)
   - **Key people**: who came up multiple times or had significant interactions? (1-3 bullets, link to People notes when known)
   - **Open threads / deferred**: unresolved items spanning sessions, things rolling forward to tomorrow (1-3 bullets)
   - **Health/mood signal** if any session captured it (1 line)

   The digest is for cross-day continuity: when the next session starts, it gets the last 3 digests + last 3 individual sessions. So the digest should give the "shape of the day" without duplicating the granular session content.

Do NOT modify any existing session memory files. Only create new ones (regular or _delta) and overwrite the day's _DIGEST.md.
PROMPTEOF

# Substitute placeholders. Use python for safe multi-line replacement
# (sed struggles with newlines in the replacement values).
PROMPT=$(
    TEMPLATE="$PROMPT_TEMPLATE" \
    P_TODAY="$TODAY" \
    P_TRANSCRIPTS="$TODAYS_TRANSCRIPTS" \
    P_MEMORIES="$RECENT_MEMORIES" \
    P_MEMORY_DIR="$MEMORY_DIR" \
    python3 -c '
import os
t = os.environ["TEMPLATE"]
t = t.replace("__TODAY__", os.environ["P_TODAY"])
t = t.replace("__TODAYS_TRANSCRIPTS__", os.environ["P_TRANSCRIPTS"])
t = t.replace("__RECENT_MEMORIES__", os.environ["P_MEMORIES"])
t = t.replace("__MEMORY_DIR__", os.environ["P_MEMORY_DIR"])
print(t)
'
)

cd "$HARNESS"

echo "[$(date)] Starting session-memory consolidation"
echo "$PROMPT" | "$CLAUDE_BIN" \
    --print \
    --dangerously-skip-permissions
echo "[$(date)] Done"
