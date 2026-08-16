#!/bin/bash
# Wrapper script for launchd to trigger the daily job-search discovery scan.
# Mirrors transcript-processing/run-process-transcript.sh.
#
# Runs /job-search's daily discovery flow headless across every lane that works
# without a human: Gmail job alerts (if the claude.ai connector is reachable),
# hiringcafe.py + indeed.py scripted lanes, Greenhouse/Lever X-ray, 80,000 Hours
# Algolia, LinkedIn (if the MCP is reachable), and the warm-connection/re-apply
# watchlists. Applies the 4 hard gates (comp gate = band rule since 2026-08-10),
# verifies postings are open, dedups STATUS-AWARE against the Job Listings
# folder + Archive/, writes listing notes for survivors AND near-misses, appends
# a hub-note log entry, and notifies ONLY when new verified candidates appeared.
#
# Retries once on failure: ~half of 7/21-8/10 runs died on "Connection closed
# mid-response" with no retry, no hub entry, and a non-clickable osascript
# banner, so crashed days were indistinguishable from honest 0-survivor days.
#
# Scheduled by com.exobrain.job-scan.plist (daily). Source copy of the plist lives
# beside this script; the live copy is a REAL FILE in ~/Library/LaunchAgents/
# (never a symlink -- see feedback_launchd_symlinks).

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/config.sh"

LOG_DIR="$EXOBRAIN_LOG_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NOTIFY="$HARNESS_DIR/mist-voice/bin/mist-notify"

if ! command -v claude &>/dev/null; then
    "$NOTIFY" "Claude CLI not found -- cannot run job scan" "Exobrain ERROR" Basso "$LOG_DIR" \
        || osascript -e 'display notification "Claude CLI not found -- cannot run job scan" with title "Exobrain ERROR" sound name "Basso"'
    exit 1
fi

# 09:00 is often slept through, and launchd fires the catch-up run the instant
# the Mac wakes, before DNS answers. Three scans died that way (7/28, 8/04,
# 8/05) and nobody saw it, because the failure is logged here and the job still
# exits 0. Generic host on purpose: this scan hits a dozen job boards, so what
# matters is that the internet is up, not one specific endpoint.
if ! "$SCRIPT_DIR/scripts/wait-for-network.sh" cloudflare.com 300; then
    echo "[$(date)] No network after 300s. Skipping job scan." >> "$LOG_DIR/job-scan-failures.log"
    exit 0
fi

# cd to harness dir so the project CLAUDE.md (persona + skill context) auto-loads
cd "$HARNESS_DIR"

# --dangerously-skip-permissions is required because launchd runs non-interactively
# and cannot present permission prompts.
# 40 min per attempt: the lane set grew (Gmail + scripted lanes) on 2026-08-10.
TIMEOUT_SEC=2400
MAX_ATTEMPTS=2

PROMPT='Run the daily /job-search discovery scan as defined in the job-search skill (its "Daily Briefing" section). Do this INLINE in this single session -- do NOT spawn parallel subagents, to keep daily token cost low.

Steps:
1. Read the resume PDF and the gitignored Projects/Get new job/Claude Reference.md for the comp floor and the 4 hard gates (read values at runtime, never assume them). NOTE the band rule (2026-08-10): a listed salary RANGE passes gate 3 if the floor falls anywhere inside it -- DQ only when the TOP of the band is below the floor; a bottom under the floor is a pass-with-flag, note the offer risk. Also read the Warm-Connection Watch Lane section of that reference.
2. Dedup is STATUS-AWARE, never blanket -- see "Re-Apply on Repost" in the skill. Skip a discovered match only when its existing note is status candidate/applied/interviewing, or status skipped with unchanged requirements. A match whose note is rejected/closed/withdrawn AND whose posting is genuinely fresh (different job ID, or posted date materially newer than the note) is a RE-APPLY CANDIDATE -- surface it per the skill (dated Repost section on the old note, status back to candidate). Notes with reapply: true always surface on any repost. Sweep Archive/ too, by frontmatter not folder: grep -rl "^type: job-listing" /Users/alexhedtke/Exobrain/ | grep -v "/Job Listings/".
3. Run these lanes, rotating keyword angles day-to-day so the pattern looks human:
   a. GMAIL JOB ALERTS -- the proven highest-yield discovery lane -- IF the claude.ai Gmail MCP is reachable in this headless run: search_threads for (from:indeed.com OR from:linkedin.com OR from:dice.com OR from:ziprecruiter.com) (jobs OR "job alert" OR "new jobs" OR recommended) newer_than:2d, then get_thread each hit (bodies exceed the token cap and auto-save to files -- that is the intended path), extract ALL job IDs and titles from the saved files with the regex snippet in the skill (each alert holds ~6 roles, not just the subject line), dedup across emails and the tracker, apply the title pre-filter, then get_job_details on survivors in paced batches of 2-4. If the Gmail MCP is NOT reachable, skip the lane and note it -- do not fail the run.
   b. HIRING.CAFE scripted lane: python3 job-search/hiringcafe.py "<angle1>" "<angle2>" "<angle3>" --days 3, with 2-3 rotating angles mixing titles and responsibility phrases. The script pre-applies all four gates including the band rule; survivors tagged BAND-STRADDLE pass with the flag carried onto the note. Follow every survivor to its primary posting (employer ATS) and verify there.
   b2. NICHE BOARDS scripted lane: python3 job-search/nicheboards.py "<angle1>" "<angle2>" --days 3. Direct data paths for Himalayas/Remotive/WWR/BuiltIn -- never Google X-ray these boards. SURVIVORS: verify on the employer ATS, then the normal note pipeline. LEADS (comp unlisted): spend a JD read only on squarely in-lane titles; the unlisted-comp DQ still applies after the read.
   b3. ATS WATCHLIST scripted lane: python3 job-search/ats-watchlist.py -- diffs every tracked employer'\''s Greenhouse/Lever/Ashby board against yesterday'\''s snapshot. Each NEW posting: JD read, 4 gates, status-aware dedup, listing note. Report the polled/failed/baselined counts in the hub log. This lane covers ATS-hosted re-apply watchlist employers automatically.
   b4. USAJOBS scripted lane: python3 job-search/usajobs.py "IT specialist" "security analyst" --days 7. Runs BOTH passes automatically: nationwide remote (standard floor) and local Kansas City 30mi (onsite floor -- higher, binary on any office requirement). [LOCAL] survivors are onsite/hybrid seats in Alex'\''s metro, in scope per his 2026-08-14 standing instruction; do NOT DQ them on gate 1, but still JD-read for fit. If the script prints that the API key is missing, log the lane as skipped-with-reason and move on -- do not fail the run. Federal survivors close on hard deadlines; capture the close date on the note.
   c. INDEED scripted lane: python3 job-search/indeed.py "<angle>" --days 3, 1-2 queries. Zero job cards means blocked (the script retries internally); trust the per-row location string over the remote facet. Verify survivors on the employer ATS; if a role exists only on Indeed, mark verification incomplete.
   d. ATS X-RAY: 1-2 WebSearch queries against site:boards.greenhouse.io and site:jobs.lever.co only, rotating a responsibility phrase (Entra ID, phishing remediation, access provisioning, M365 admin, compromised account, Intune endpoint, IAM analyst). Do NOT run Ashby or Workable X-rays -- chronic wrong-domain false negatives, and hiring.cafe covers those ATS inventories. A site: query returning a different domain than filtered = lane did not run; say so.
   e. 80,000 HOURS via the Algolia endpoint (two calls per the skill): the Information security/Operations + Full-time + Remote facet query, and the Fellowship facet query with NO location filter (the fellowship gate variant applies to those hits).
   f. LINKEDIN via mcp__linkedin__search_jobs IF the MCP is reachable (read /linkedin rules; use ONLY references[] job_id-to-title mappings; remote + full_time + past_24_hours; include the entry-level "Cybersecurity Analyst I" / Associate angles with experience_level=entry,associate). If NOT reachable, skip that lane and note it -- do not fail the run.
   g. WARM-CONNECTION + RE-APPLY WATCHLIST: check the careers portals of the firms listed in the Claude Reference watch lane (apply its per-firm gate exceptions) and of employers whose notes carry reapply: true.
4. For each candidate: read the actual JD, apply all 4 gates (band rule on gate 3; the fellowship gate variant for paid AI safety fellowships), and verify the posting is OPEN (Greenhouse/Lever API where possible; mark "verification incomplete -- Alex must spot-check" if JS-blocked).
5. Create listing notes in Projects/Get new job/Job Listings/ per the skill schema (full frontmatter + raw JD archived verbatim in the collapsible callout):
   - Every survivor: status candidate.
   - Every role that CONSUMED A FULL JD READ but died on ANY gate: status skipped, declined: true, plus a "## Why skipped" section quoting the exact failed bar. This is what stops tomorrow from re-reading the same JD. Roles killed by the title pre-filter or before a JD read get no note.
   - CONTRADICTORY REQUIREMENTS (poster-side screening filters contradict the bar stated in the JD body, the Terumo pattern): status candidate with the contradiction spelled out under ## Gaps, flagged for Alex to decide -- never a silent DQ.
6. Append a dated "Pipeline" entry to the hub note (Projects/Get new job/Get new job.md) under ## Job Search Log: honest lane-coverage table (ran / skipped-with-reason per lane), scan tally (searches / JD-reads / passed / near-missed), each survivor with apply URL, near-misses with one-line reasons. Do not pad counts.
7. NOTIFY ONLY IF new verified candidates were added: run  mist-voice/bin/mist-notify "Job scan: N new verified candidate(s) in the tracker" "MIST" Purr console  -- use a Basso sound and an URGENT title only for a stand-out high-comp remote strong fit. If zero survivors, no notification; the honest hub-note entry is enough.
8. LANE MARKERS (REQUIRED, the wrapper parses them): the VERY LAST TWO lines of your output must be exactly, in this order:
   GMAIL_LANE: RAN     (or GMAIL_LANE: SKIPPED if the Gmail MCP was unreachable this run)
   LINKEDIN_LANE: RAN  (or LINKEDIN_LANE: SKIPPED if the LinkedIn MCP was unreachable this run)
   Print nothing after the LINKEDIN_LANE line.

Stay in MIST voice in any notification. This is a silent tracker-populating job, not a briefing.'

# === Run with one retry ===
# Each attempt gets its own log pair. The marker/sentinel logic reads the last
# attempt that actually ran.
run_attempt() {
    local attempt=$1
    OUT_FILE="$LOG_DIR/job-scan-$TIMESTAMP-a$attempt.out"
    ERR_FILE="$LOG_DIR/job-scan-$TIMESTAMP-a$attempt.err"

    claude \
        --print \
        --dangerously-skip-permissions \
        -p "$PROMPT" \
        >"$OUT_FILE" \
        2>"$ERR_FILE" &
    local claude_pid=$!
    (
        sleep $TIMEOUT_SEC
        if kill -0 $claude_pid 2>/dev/null; then
            kill -TERM $claude_pid 2>/dev/null
            sleep 5
            kill -KILL $claude_pid 2>/dev/null
            echo "[$TIMESTAMP] TIMEOUT after ${TIMEOUT_SEC}s (attempt $attempt) -- claude --print killed" >> "$LOG_DIR/job-scan-failures.log"
        fi
    ) &
    local killer_pid=$!
    wait $claude_pid 2>/dev/null
    local exit_code=$?
    kill $killer_pid 2>/dev/null
    wait $killer_pid 2>/dev/null
    return $exit_code
}

EXIT_CODE=1
for ATTEMPT in $(seq 1 $MAX_ATTEMPTS); do
    run_attempt $ATTEMPT
    EXIT_CODE=$?
    [ $EXIT_CODE -eq 0 ] && break
    ERROR_MSG=$(tail -1 "$ERR_FILE" 2>/dev/null | head -c 100)
    # claude --print prints API errors (e.g. "Connection closed mid-response") to
    # stdout, not stderr. When stderr is empty, fall back to the stdout tail so the
    # failure log is never blank.
    [ -z "$ERROR_MSG" ] && ERROR_MSG=$(tail -3 "$OUT_FILE" 2>/dev/null | tr '\n' ' ' | head -c 200)
    echo "[$TIMESTAMP] attempt $ATTEMPT FAILED (exit $EXIT_CODE)" >> "$LOG_DIR/job-scan-failures.log"
    echo "  detail: $ERROR_MSG" >> "$LOG_DIR/job-scan-failures.log"
    [ $ATTEMPT -lt $MAX_ATTEMPTS ] && sleep 30
done

if [ $EXIT_CODE -ne 0 ]; then
    # Clickable failure notification (opens the failed attempt's log). The old
    # bare-osascript banner was non-clickable and easy to miss.
    "$NOTIFY" "Job scan failed after $MAX_ATTEMPTS attempts (exit $EXIT_CODE): $ERROR_MSG" "MIST URGENT" Basso "$OUT_FILE" \
        || osascript -e "display notification \"Job scan failed after retries (exit $EXIT_CODE)\" with title \"Exobrain ERROR\" sound name \"Basso\""
fi

# === Lane sentinels ===
# The session-start hook surfaces these flags so the next interactive session
# backfills discovery lanes a headless run could not reach. Bash owns the flags,
# driven by the markers the run prints as its last lines:
#   RAN     -> lane was covered this run; clear any pending flag.
#   SKIPPED -> lane MCP was unreachable; raise the flag (stamp today).
#   (absent / timeout / crash) -> leave the flag untouched; we cannot know.
LI_SENTINEL="$HARNESS_DIR/job-search/.linkedin-scan-pending"
LI_MARKER=$(grep -oE 'LINKEDIN_LANE: (RAN|SKIPPED)' "$OUT_FILE" 2>/dev/null | tail -1)
case "$LI_MARKER" in
    *RAN)     rm -f "$LI_SENTINEL" ;;
    *SKIPPED) date +%Y-%m-%d > "$LI_SENTINEL" ;;
esac

GM_SENTINEL="$HARNESS_DIR/job-search/.gmail-scan-pending"
GM_MARKER=$(grep -oE 'GMAIL_LANE: (RAN|SKIPPED)' "$OUT_FILE" 2>/dev/null | tail -1)
case "$GM_MARKER" in
    *RAN)     rm -f "$GM_SENTINEL" ;;
    *SKIPPED) date +%Y-%m-%d > "$GM_SENTINEL" ;;
esac

# Clean up empty error/out files across attempts
for f in "$LOG_DIR"/job-scan-$TIMESTAMP-a*.out "$LOG_DIR"/job-scan-$TIMESTAMP-a*.err; do
    [ -s "$f" ] || rm -f "$f" 2>/dev/null
done

exit 0
