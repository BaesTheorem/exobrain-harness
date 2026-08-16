#!/bin/bash
# Haircut booking nudge -- Rich Forever Barbershop, every 6 weeks.
#
# Runs daily and almost always exits immediately. When a cut comes due,
# schedule.py opens the gate and this hands off to a headless MIST run, which
# is the only piece that can see Alex's Google Calendar (via the Calendar MCP)
# and so is the only piece that can honour "fit it wherever I'm open".
#
# MIST cannot complete the booking: Booksy requires an account with a verified
# phone, and Alex does not have one. So the run ends at a notification with the
# picked slot and a one-tap deep link into the barber's Booksy page.
#
# Managed by launchd: com.exobrain.haircut-check (daily, 10:00 local)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HARNESS="$(cd "$SCRIPT_DIR/.." && pwd)"

CLAUDE_BIN="$(command -v claude)"
TIMEOUT_SEC=600

if ! python3 "$SCRIPT_DIR/schedule.py" check > /dev/null; then
    echo "[$(date)] $(python3 "$SCRIPT_DIR/schedule.py" check || true) -- nothing to do."
    exit 0
fi

# launchd fires missed jobs the instant the Mac wakes, before Wi-Fi and DNS are
# back; without this the run dies with ENOTFOUND and nothing retries until
# tomorrow. See scripts/wait-for-network.sh for the history.
if ! "$HARNESS/scripts/wait-for-network.sh" api.anthropic.com 300; then
    echo "[$(date)] No network after 300s. Skipping; will retry tomorrow."
    exit 0
fi

read -r WINDOW_START WINDOW_END < <(python3 "$SCRIPT_DIR/schedule.py" window)
DUE_INFO="$(python3 "$SCRIPT_DIR/schedule.py" status)"

read -r -d '' PROMPT << PROMPTEOF || true
You are MIST running as the scheduled haircut booker. Work autonomously and finish in one pass.

Alex gets a haircut every 6 weeks at Rich Forever Barbershop (Midtown, 3845 Main St).
Standing order: "2 faded to 3 on sides and back, scissors on top" -- a basic men's haircut.
Exact time is flexible; the rule is to fit it wherever his calendar is open.

Current cadence:
${DUE_INFO}

Do this:

1. Read the open Booksy slots:
     cd "${SCRIPT_DIR}" && python3 booksy.py slots --from ${WINDOW_START} --to ${WINDOW_END} --json
   If that reports warnings and no slots, Booksy is unreachable -- say so in the
   notification rather than claiming he has no availability. Those are different failures.

2. Pull his Google Calendar for ${WINDOW_START} to ${WINDOW_END} and work out where he is
   genuinely free. Treat "Sleep", "Wind down", "Extra sleep cycle", "Bootup routine" and
   "Walk" as soft (moveable); treat everything else as hard busy. Leave 30 minutes of
   travel either side -- the shop is about 10 minutes from him.

3. Pick the single best slot: closest to the due date, in a comfortable gap (not wedged
   between two commitments), and prefer a barber he has been to before. His history is in
   ${SCRIPT_DIR}/state.json.

4. Notify him, clickable straight through to that barber's Booksy page so one tap starts
   the booking:
     "${HARNESS}/mist-voice/bin/mist-notify" "<slot, barber, price>" "Haircut due" Glass "<booking url>"
   Use --reply so he can answer, and keep the message to one line.

5. Add a Things 3 task in the Inbox: "Book haircut -- <day> <time> with <barber>" with the
   Booksy URL and the cut description in the notes. Do NOT set a `when` date; Alex schedules
   his own tasks.

6. Mark the cycle so he is not nudged twice:
     cd "${SCRIPT_DIR}" && python3 schedule.py mark-notified

Do not attempt to complete the Booksy booking yourself and do not create a Booksy account.
Alex has no account and it needs phone verification. The last tap is his.
After he confirms, the booking gets recorded with: python3 schedule.py record --date <YYYY-MM-DD> --barber "<name>"
PROMPTEOF

RUN_OUT="$(mktemp)"
trap 'rm -f "$RUN_OUT"' EXIT

echo "[$(date)] Haircut due; searching ${WINDOW_START}..${WINDOW_END}"

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
