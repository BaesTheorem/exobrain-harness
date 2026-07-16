#!/bin/bash
# Wrapper script for launchd to trigger the daily job-search discovery scan.
# Mirrors transcript-processing/run-process-transcript.sh.
#
# Runs /job-search's daily discovery flow headless: Google X-ray of ATS boards +
# 80,000 Hours + LinkedIn (if the MCP is reachable in a headless run), applies the
# 4 hard gates, verifies postings are open, dedups against the Job Listings folder,
# creates per-listing notes for survivors, appends a hub-note log entry, and
# notifies ONLY when new verified candidates were added.
#
# Scheduled by com.exobrain.job-scan.plist (daily). Source copy of the plist lives
# beside this script; the live copy is a REAL FILE in ~/Library/LaunchAgents/
# (never a symlink — see feedback_launchd_symlinks).

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

LOG_DIR="/tmp"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

if ! command -v claude &>/dev/null; then
    osascript -e 'display notification "Claude CLI not found — cannot run job scan" with title "Exobrain ERROR" sound name "Basso"'
    exit 1
fi

# cd to harness dir so the project CLAUDE.md (persona + skill context) auto-loads
cd "$HARNESS_DIR"

# --dangerously-skip-permissions is required because launchd runs non-interactively
# and cannot present permission prompts.
TIMEOUT_SEC=1800

PROMPT='Run the daily /job-search discovery scan as defined in the job-search skill (its "Daily Briefing" section). Do this INLINE in this single session — do NOT spawn parallel subagents, to keep daily token cost low.

Steps:
1. Read the resume PDF and Claude Reference.md for the comp floor (the number lives in the gitignored Claude Reference.md; read it at runtime, never assume it) and the 4 hard gates (fully remote / full-time permanent / comp at-or-above the reference floor listed-or-strong-evidence / >=80% strong fit, failing no stated hard requirement).
2. List the existing Projects/Get new job/Job Listings/ folder and dedup against it — never re-surface a company+role already noted.
3. Run a rotating set of discovery searches (vary day-to-day so the pattern looks human):
   - 2-3 Google X-ray searches across ATS boards (site:boards.greenhouse.io / jobs.lever.co / jobs.ashbyhq.com / apply.workable.com) and niche remote boards (remoterocketship.com / himalayas.app / builtin.com), rotating a responsibility keyword (Entra ID, phishing remediation, access provisioning, M365 admin, compromised account, Intune endpoint, IAM analyst).
   - The 80,000 Hours board (jobs.80000hours.org) plus a couple EA/AI-governance org careers pages — ops/IT/security/compliance roles only, not research.
   - LinkedIn via mcp__linkedin__search_jobs IF the MCP is available in this headless run (read /linkedin rules; use only references[] job_id->title mappings; remote + full_time + past_24_hours). If the LinkedIn MCP is NOT available, skip that lane and note it — do not fail the run.
4. For each candidate: read the actual JD, apply all 4 gates, and verify the posting is OPEN (Greenhouse/Lever API where possible; mark "verification incomplete" if JS-blocked). Drop anything failing a gate.
5. For every survivor, create a per-listing note in Projects/Get new job/Job Listings/ per the skill schema (full frontmatter + raw JD archived verbatim in a collapsible callout).
6. Append a dated "Pipeline" entry to the hub note (Projects/Get new job/Get new job.md) under ## Job Search Log summarizing: which lanes ran, scan tally (searches/JD-reads/passed/failed), and each survivor with apply URL. Be honest about counts; do not pad.
7. NOTIFY ONLY IF new verified candidates were added: run  mist-voice/bin/mist-notify "Job scan: N new verified candidate(s) in the tracker"  (use the urgent variant only if a stand-out high-comp remote strong-fit appeared). If zero survivors, stay completely silent (no notification), just leave the honest hub-note log entry.
8. LINKEDIN LANE MARKER (REQUIRED, for the wrapper): the VERY LAST line of your output must be exactly one of:
   - "LINKEDIN_LANE: RAN"     if the LinkedIn MCP was available and you actually searched it this run.
   - "LINKEDIN_LANE: SKIPPED" if the LinkedIn MCP was NOT reachable in this headless run (so that lane was skipped).
   Print nothing after that line. The wrapper uses it to flag the next interactive session to backfill the LinkedIn lane.

Stay in MIST voice in any notification. This is a silent tracker-populating job, not a briefing.'

claude \
    --print \
    --dangerously-skip-permissions \
    -p "$PROMPT" \
    >"$LOG_DIR/exobrain-job-scan-$TIMESTAMP.out" \
    2>"$LOG_DIR/exobrain-job-scan-$TIMESTAMP.err" &
CLAUDE_PID=$!
(
    sleep $TIMEOUT_SEC
    if kill -0 $CLAUDE_PID 2>/dev/null; then
        kill -TERM $CLAUDE_PID 2>/dev/null
        sleep 5
        kill -KILL $CLAUDE_PID 2>/dev/null
        echo "[$TIMESTAMP] TIMEOUT after ${TIMEOUT_SEC}s — claude --print killed" >> "$LOG_DIR/exobrain-job-scan-failures.log"
        osascript -e "display notification \"Job scan hung — killed after ${TIMEOUT_SEC}s\" with title \"Exobrain ERROR\" sound name \"Basso\""
    fi
) &
KILLER_PID=$!
wait $CLAUDE_PID 2>/dev/null
EXIT_CODE=$?
kill $KILLER_PID 2>/dev/null
wait $KILLER_PID 2>/dev/null

if [ $EXIT_CODE -ne 0 ]; then
    ERROR_MSG=$(tail -1 "$LOG_DIR/exobrain-job-scan-$TIMESTAMP.err" 2>/dev/null | head -c 100)
    # claude --print prints API errors (e.g. "Connection closed mid-response") to
    # stdout, not stderr. When stderr is empty, fall back to the stdout tail so the
    # failure log is never blank.
    [ -z "$ERROR_MSG" ] && ERROR_MSG=$(tail -3 "$LOG_DIR/exobrain-job-scan-$TIMESTAMP.out" 2>/dev/null | tr '\n' ' ' | head -c 200)
    osascript -e "display notification \"Job scan failed (exit $EXIT_CODE): $ERROR_MSG\" with title \"Exobrain ERROR\" sound name \"Basso\""
    echo "[$TIMESTAMP] FAILED (exit $EXIT_CODE)" >> "$LOG_DIR/exobrain-job-scan-failures.log"
    echo "  detail: $ERROR_MSG" >> "$LOG_DIR/exobrain-job-scan-failures.log"
fi

# === LinkedIn-lane sentinel ===
# The session-start hook surfaces this flag so the next interactive session
# backfills the LinkedIn discovery lane that a headless run couldn't reach.
# Bash owns the flag, driven by the marker the run prints as its last line:
#   RAN     -> LinkedIn was searched this run; clear any pending flag.
#   SKIPPED -> LinkedIn MCP was unreachable; raise the flag (stamp today).
#   (absent / timeout / crash) -> leave the flag untouched; we can't know.
SENTINEL="$HARNESS_DIR/job-search/.linkedin-scan-pending"
MARKER=$(grep -oE 'LINKEDIN_LANE: (RAN|SKIPPED)' "$LOG_DIR/exobrain-job-scan-$TIMESTAMP.out" 2>/dev/null | tail -1)
case "$MARKER" in
    *RAN)     rm -f "$SENTINEL" ;;
    *SKIPPED) date +%Y-%m-%d > "$SENTINEL" ;;
esac

# Clean up empty error/out files
[ -s "$LOG_DIR/exobrain-job-scan-$TIMESTAMP.err" ] || rm -f "$LOG_DIR/exobrain-job-scan-$TIMESTAMP.err"
[ -s "$LOG_DIR/exobrain-job-scan-$TIMESTAMP.out" ] || rm -f "$LOG_DIR/exobrain-job-scan-$TIMESTAMP.out"

exit 0
