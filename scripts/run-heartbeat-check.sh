#!/bin/bash
# run-heartbeat-check.sh: the dead-man's switch for the daily routines.
#
# Every other alarm in the harness fires from inside the job that failed, so a
# job that never ran (Mac asleep on battery, plist unloaded, launchd skipped a
# calendar slot) says nothing at all. This checks the OUTPUTS the day's
# routines should have produced and raises one banner listing whatever is
# missing or stale. Deterministic: no model call.
#
# Successor to the April `heartbeat-check` Claude Desktop scheduled task
# (~/.claude/scheduled-tasks/heartbeat-check), which only watched the morning
# briefing, pointed at the pre-move vault path, and had no runner after the
# routines moved to launchd.
#
# Driven by com.exobrain.heartbeat-check (daily 10:15; launchd runs a missed
# slot on wake). One banner per day per distinct set of misses.
#   run-heartbeat-check.sh            check and banner
#   run-heartbeat-check.sh --dry-run  print the verdicts, no banner, no stamp
#
# To watch another routine, add a check_* line in the CHECKS section.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=../config.sh
source "$SCRIPT_DIR/config.sh"

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

LOG="$EXOBRAIN_LOG_DIR/heartbeat.log"
STAMP="$EXOBRAIN_LOG_DIR/heartbeat-notified"
NOTIFY="$SCRIPT_DIR/mist-voice/bin/mist-notify"
NOW=$(date +%s)

# Daily note filename for a `date -v` offset ("" = today, "-1d" = yesterday),
# in the vault's `dddd, MMMM Do, YYYY` format.
note_name() {
	local off="${1:-}" d sfx
	if [ -n "$off" ]; then d=$(date -v"$off" +%-d); else d=$(date +%-d); fi
	case "$d" in
		1|21|31) sfx=st ;; 2|22) sfx=nd ;; 3|23) sfx=rd ;; *) sfx=th ;;
	esac
	if [ -n "$off" ]; then
		date -v"$off" "+%A, %B $d$sfx, %Y"
	else
		date "+%A, %B $d$sfx, %Y"
	fi
}

MISSES=()
OKS=()
miss() { MISSES+=("$1"); }
ok() { OKS+=("$1"); }

# heading LABEL FILE REGEX: FILE exists and has a line matching REGEX.
check_heading() {
	local label="$1" file="$2" re="$3"
	if [ ! -f "$file" ]; then
		miss "$label: no note ($(basename "$file"))"
	elif grep -qiE "$re" "$file"; then
		ok "$label"
	else
		miss "$label: section missing in $(basename "$file")"
	fi
}

# fresh LABEL MAX_HOURS FILE...: the newest of FILE... is under MAX_HOURS old.
check_fresh() {
	local label="$1" max_h="$2"; shift 2
	local newest=0 f m
	for f in "$@"; do
		[ -e "$f" ] || continue
		m=$(stat -f %m "$f" 2>/dev/null || echo 0)
		[ "$m" -gt "$newest" ] && newest=$m
	done
	if [ "$newest" -eq 0 ]; then
		miss "$label: no output file"
		return
	fi
	local age_h=$(( (NOW - newest) / 3600 ))
	if [ "$age_h" -ge "$max_h" ]; then
		miss "$label: last output ${age_h}h ago (limit ${max_h}h)"
	else
		ok "$label (${age_h}h)"
	fi
}

# --- CHECKS ---------------------------------------------------------------
TODAY_NOTE="$DAILY_NOTES_DIR/$(note_name).md"
YDAY_NOTE="$DAILY_NOTES_DIR/$(note_name -1d).md"
YDAY=$(date -v-1d +%Y-%m-%d)

check_heading "morning briefing (08:00)" "$TODAY_NOTE" '^###+ *morning briefing'
check_heading "evening wind-down (21:00, yesterday)" "$YDAY_NOTE" '^###+ *evening wind-?down'
check_fresh "session-memory digest (23:00, yesterday)" 36 "$SESSION_DIGESTS_DIR/${YDAY}_DIGEST.md"
check_fresh "job scan (09:00)" 26 "$EXOBRAIN_LOG_DIR"/job-scan-*.out
check_fresh "backup (daily)" 30 "$EXOBRAIN_LOG_DIR/backup.log"

# --- Report ---------------------------------------------------------------
TS=$(date '+%Y-%m-%d %H:%M:%S')
if [ "$DRY" -eq 1 ]; then
	for o in ${OKS[@]+"${OKS[@]}"}; do echo "ok    $o"; done
	for m in ${MISSES[@]+"${MISSES[@]}"}; do echo "MISS  $m"; done
	exit 0
fi

if [ "${#MISSES[@]}" -eq 0 ]; then
	echo "[$TS] all ${#OKS[@]} routines fresh" >> "$LOG"
	exit 0
fi

SUMMARY="$(printf '%s; ' "${MISSES[@]}")"
SUMMARY="${SUMMARY%; }"
{ echo "[$TS] ${#MISSES[@]} missed:"; printf '  %s\n' "${MISSES[@]}"; } >> "$LOG"

# One banner per day per distinct set of misses.
KEY="$(date +%Y-%m-%d) $(printf '%s' "$SUMMARY" | cksum | cut -d' ' -f1)"
if [ "$(cat "$STAMP" 2>/dev/null)" = "$KEY" ]; then
	exit 0
fi
printf '%s\n' "$KEY" > "$STAMP"
if [ -x "$NOTIFY" ]; then
	"$NOTIFY" "Heartbeat: ${#MISSES[@]} routine(s) produced nothing. $SUMMARY" \
		"Exobrain heartbeat" Basso "$LOG" --group heartbeat || true
fi
exit 0
