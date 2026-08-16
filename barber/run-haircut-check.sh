#!/bin/bash
# Haircut booking nudge -- Rich Forever Barbershop, every 6 weeks.
#
# Runs daily and almost always exits immediately. When a cut comes due,
# schedule.py opens the gate and this hands off to a headless MIST run, which
# is the only piece that can see Alex's Google Calendar (via the Calendar MCP)
# and so is the only piece that can honour "fit it wherever I'm open".
#
# Alex has authorised booking outright, so the run books the slot itself using
# the saved Booksy session (see login.py) and tells him afterwards. Changes are
# free up to an hour before the visit, so an auto-booked slot is cheap to move.
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

3. Pick the slot. Alex's rule is the HIGHEST RATED barber available in the window, not the
   earliest opening. Every barber is 5.0, so review count is the real tiebreak; config.json
   is already sorted best-first and booksy.best_slot() applies exactly this rule. Among
   slots with the best available barber, take the one nearest the due date that sits in a
   comfortable gap rather than wedged between two commitments.

4. Book it:
     cd "${SCRIPT_DIR}" && python3 book.py --barber <business_id> --at "YYYY-MM-DD HH:MM" --confirm
   If it exits non-zero, do NOT retry blindly -- read steps/*.png and say what happened.
   A "session expired" error means Alex must re-run login.py; tell him that specifically.

5. Record it and put it on his calendar:
     cd "${SCRIPT_DIR}" && python3 schedule.py record --date <YYYY-MM-DD> --barber "<name>"
   Then create the Google Calendar event at the booked time, 30 minutes long, location
   "Rich Forever Barbershop, 3845 Main St, Kansas City, MO 64111", with the cut description
   in the notes.

6. Tell him, clickable through to the barber's Booksy page so he can change it if he wants:
     "${HARNESS}/mist-voice/bin/mist-notify" "<day, time, barber, price>" "Haircut booked" Glass "<booking url>"
   Use --reply. One line. Say it is booked, not that it needs booking.

If booking fails for any reason, fall back to notifying him with the slot you picked and the
booking URL so he can finish it by hand, and say plainly that the automation could not.
Never report a booking as done unless book.py exited 0 and printed a confirmation.
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
