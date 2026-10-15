#!/bin/bash
# Haircut booker -- Salon Ramón, Brookside, every 6 weeks, kept booked ahead.
#
# Runs daily. schedule.py decides what to look at:
#   - a HUNT when the queue holds fewer than `bookAhead` appointments (config),
#     aimed 6 weeks past the last queued one, because Ramon books out months
#     ahead and a 12-day lead finds nothing;
#   - SWAP WATCHES on queued appointments that sit outside the preferred hours,
#     replaced as soon as a preferred slot opens near the same date.
#
# The slot search and filtering are deterministic and run here. Only when a
# real candidate exists does this hand off to a headless MIST run, which is
# the only piece that can read Google Calendar and so the only piece that can
# honour "fit it wherever I'm open". A slot MIST finds blocked is recorded
# (schedule.py reject) so the same slot does not wake MIST again tomorrow.
#
# Alex has authorised booking and swapping outright; the run acts and tells
# him afterwards. The salon allows free online cancellation up to a day ahead.
#
# Fully unattended: Rosy's token dies 30 minutes after sign-in and the site
# cannot renew it, so the booker re-mints one by replaying Chrome's Google SSO.
#
# Managed by launchd: com.exobrain.haircut-check (daily, 10:00 local)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HARNESS="$(cd "$SCRIPT_DIR/.." && pwd)"
SCHEDULE=(python3 "$SCRIPT_DIR/schedule.py")
RAMON="$SCRIPT_DIR/bin/ramon"
NOTIFY="$HARNESS/mist-voice/bin/mist-notify"

TIMEOUT_SEC=600

# Close out a past appointment before deciding anything. A lapsed one used to
# expire unrecorded, so the next run saw an empty history and hunted for a slot
# weeks early. This must come before `plan`, which reads what it writes.
if RECONCILED="$("${SCHEDULE[@]}" reconcile)"; then
    echo "[$(date)] $RECONCILED"
    "$NOTIFY" \
        "Marked your appointment as done and restarted the six weeks. Did you actually go?" \
        "Haircut" none console --reply || true
fi

PLAN="$("${SCHEDULE[@]}" plan)"
field() { python3 -c 'import json,sys; v=json.loads(sys.argv[1]); exec(sys.argv[2])' "$PLAN" "$1"; }
HAS_HUNT="$(field 'print(1 if v["hunt"] else 0)')"
SWAP_LINES="$(field 'for w in v["swaps"]: print(w["date"], w["time"] or "-", w["id"] or "-", w["since"], w["until"])')"

if [[ "$HAS_HUNT" == 0 && -z "$SWAP_LINES" ]]; then
    echo "[$(date)] $("${SCHEDULE[@]}" check || true) -- nothing to do."
    exit 0
fi

# launchd runs with a minimal PATH that lacks ~/.local/bin (the Claude CLI) and
# Homebrew. Resolve rather than pin: the binary already moved once.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
# Unattended: the guard hook (.claude/hooks/guard-unattended.py) applies.
export MIST_UNATTENDED=1

# launchd fires missed jobs the instant the Mac wakes, before Wi-Fi and DNS are
# back. See scripts/wait-for-network.sh for the history.
if ! "$HARNESS/scripts/wait-for-network.sh" online.rosysalonsoftware.com 300; then
    echo "[$(date)] No network after 300s. Skipping; will retry tomorrow."
    exit 0
fi

# A non-zero exit from `ramon slots --json` means the salon is unreachable or
# the session could not be re-minted; an empty list means no openings. Keep
# those apart: the first fails the job (the session-start check sees it), the
# second is ordinary for Ramon.
slots() {
    "$RAMON" slots --days 180 --since "$1" --until "$2" --limit 500 --json
}

HUNT_CANDS="[]"
if [[ "$HAS_HUNT" == 1 ]]; then
    read -r H_SINCE H_UNTIL H_TARGET < <(field 'h=v["hunt"]; print(h["since"], h["until"], h["target"])')
    if ! RAW="$(slots "$H_SINCE" "$H_UNTIL")"; then
        echo "[$(date)] Salon unreachable while hunting ${H_SINCE}..${H_UNTIL}."
        exit 1
    fi
    HUNT_CANDS="$(printf '%s' "$RAW" | "${SCHEDULE[@]}" candidates --kind hunt)"
    if [[ "$HUNT_CANDS" == "[]" ]]; then
        echo "[$(date)] No openings ${H_SINCE}..${H_UNTIL} for the cut due ${H_TARGET}; will look again tomorrow."
        # One banner per cycle, and only once the date is close enough to matter.
        if "${SCHEDULE[@]}" nudge > /dev/null; then
            "$NOTIFY" "Ramon has no openings near ${H_TARGET} yet. I check every morning and will book the first one that fits." \
                "Haircut" none "https://online.rosysalonsoftware.com/appointments" --reply --discord || true
        fi
    fi
fi

SWAP_TEXT=""
while read -r W_DATE W_TIME W_ID W_SINCE W_UNTIL; do
    [[ -z "${W_DATE:-}" ]] && continue
    if ! RAW="$(slots "$W_SINCE" "$W_UNTIL")"; then
        echo "[$(date)] Salon unreachable while watching ${W_DATE}."
        exit 1
    fi
    CANDS="$(printf '%s' "$RAW" | "${SCHEDULE[@]}" candidates --kind swap --current "$W_DATE $W_TIME")"
    if [[ "$CANDS" == "[]" ]]; then
        echo "[$(date)] Watching ${W_DATE} ${W_TIME}: no preferred opening ${W_SINCE}..${W_UNTIL}."
        continue
    fi
    SWAP_TEXT+="- Booked ${W_DATE} ${W_TIME} (appointment id ${W_ID}), watch window ${W_SINCE}..${W_UNTIL}. Preferred openings:
${CANDS}
"
done <<< "$SWAP_LINES"

if [[ "$HUNT_CANDS" == "[]" && -z "$SWAP_TEXT" ]]; then
    exit 0
fi

if ! CLAUDE_BIN="$(command -v claude)"; then
    echo "[$(date)] claude CLI not found on PATH ($PATH). Cannot book; will retry tomorrow."
    exit 1
fi

DUE_INFO="$("${SCHEDULE[@]}" status)"
CAL_LOCATION="Salon Ramón, 6315 Brookside Plaza Suite 101, Kansas City, MO 64113"

read -r -d '' PROMPT << PROMPTEOF || true
You are MIST running as the scheduled haircut booker. Work autonomously and finish in one pass.

Alex gets a haircut every 6 weeks at Salon Ramón with Ramon Walker. Service: Men's Haircut,
45 minutes, \$40. Standing order: "2 faded to 3 on sides and back, scissors on top".
Ramon books out months ahead, so Alex keeps two cuts booked. Time is flexible; the rule is
to fit it wherever his calendar is open. Preferred: weekdays, 10:00-18:00.

Current cadence:
${DUE_INFO}

The runner already searched the salon. Every slot below is open right now and none has been
ruled out before. Work only from these lists; do not widen them.

## Calendar check (applies to every slot you consider)

Pull his Google Calendar for the dates involved. Treat "Sleep", "Wind down", "Extra sleep
cycle", "Bootup routine" and "Walk" as soft (moveable) and everything else as hard busy.
Leave 30 minutes of travel either side. Every slot you check and find blocked, record so it
is never offered again:
    cd "${SCRIPT_DIR}" && python3 schedule.py reject --at "YYYY-MM-DD HH:MM"

PROMPTEOF

if [[ "$HUNT_CANDS" != "[]" ]]; then
read -r -d '' HUNT_PART << PROMPTEOF || true
## Task A: book the next cut (target ${H_TARGET}, window ${H_SINCE}..${H_UNTIL})

Open slots (JSON; "preferred" marks weekday 10:00-18:00):
${HUNT_CANDS}

1. Pick the slot nearest ${H_TARGET} that clears the calendar check, favouring preferred slots
   and a comfortable gap over one wedged between commitments.
2. Book it:
     cd "${SCRIPT_DIR}" && ./bin/ramon book --days 180 --at "YYYY-MM-DD HH:MM" --confirm
   It prints "Booked: ... (id N)". If it says the POST returned but the server has no such
   appointment, do NOT run it again: check ./bin/ramon appointments first.
3. Queue it, with the id from step 2:
     cd "${SCRIPT_DIR}" && python3 schedule.py pending --date YYYY-MM-DD --time HH:MM --id N --provider "Ramon Walker"
   If the slot you booked is NOT preferred, add --swap-since ${H_SINCE} --swap-until ${H_UNTIL}
   so the daily run swaps it out when a preferred time opens.
4. Create the Google Calendar event: "Haircut: Ramon @ Salon Ramón (BOOKED)", 45 minutes, location
   "${CAL_LOCATION}", standing order in the notes.
5. If nothing clears the calendar, book nothing (the rejects you recorded keep tomorrow quiet).

PROMPTEOF
PROMPT+="$HUNT_PART"$'\n\n'
fi

if [[ -n "$SWAP_TEXT" ]]; then
read -r -d '' SWAP_PART << PROMPTEOF || true
## Task B: swap a fallback booking for a preferred time

Alex took these slots as fallbacks and asked to move each one the moment an eligible
preferred opening appears:
${SWAP_TEXT}
For each watch:
1. Take the preferred opening nearest the booked date that clears the calendar check.
   If none clears it, leave the booking alone.
2. Book the new slot FIRST:
     cd "${SCRIPT_DIR}" && ./bin/ramon book --days 180 --at "YYYY-MM-DD HH:MM" --confirm
   Go on only if it exited 0 and printed "Booked: ... (id N)".
3. Then cancel the old one by its id:
     cd "${SCRIPT_DIR}" && ./bin/ramon cancel <old id> --confirm
   Never pass --force. If the cancel fails, say so loudly: he now holds two appointments.
4. Update the queue:
     cd "${SCRIPT_DIR}" && python3 schedule.py swap --old-date <old date> --date YYYY-MM-DD --time HH:MM --id N
5. Move his Google Calendar event titled "Haircut: Ramon @ Salon Ramón (BOOKED)" from the old time to the new one (create it if
   there is none: "Haircut: Ramon @ Salon Ramón (BOOKED)", 45 minutes, location "${CAL_LOCATION}").

PROMPTEOF
PROMPT+="$SWAP_PART"$'\n\n'
fi

PROMPT+="## Report

Send ONE notification covering what you booked, swapped or cancelled, clickable through to his
appointment list:
    \"${NOTIFY}\" \"<what changed: day, time>\" \"Haircut\" Glass \"https://online.rosysalonsoftware.com/appointments\" --reply --discord
If you changed nothing, send nothing. If a booking or cancel failed, notify with exactly what
state he is in and how to finish by hand at https://www.salonramon.com/. Never report a
booking as done unless ramon book exited 0 and printed \"Booked:\"."

RUN_OUT="$(mktemp)"
trap 'rm -f "$RUN_OUT"' EXIT

echo "[$(date)] Candidates found; handing off to MIST (hunt: $([[ "$HUNT_CANDS" != "[]" ]] && echo yes || echo no), swaps: $([[ -n "$SWAP_TEXT" ]] && echo yes || echo no))"

echo "$PROMPT" | caffeinate -is "$CLAUDE_BIN" --print --dangerously-skip-permissions > "$RUN_OUT" 2>&1 &
CLAUDE_PID=$!
(
    sleep $TIMEOUT_SEC
    if kill -0 $CLAUDE_PID 2>/dev/null; then
        kill -TERM $CLAUDE_PID 2>/dev/null || true
        sleep 5
        kill -KILL $CLAUDE_PID 2>/dev/null || true
    fi
) &
WATCHDOG_PID=$!

wait $CLAUDE_PID 2>/dev/null && RC=0 || RC=$?
kill $WATCHDOG_PID 2>/dev/null || true

cat "$RUN_OUT"
echo "[$(date)] Finished (rc=$RC)"
exit 0
