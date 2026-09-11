#!/bin/bash
# Haircut booking nudge -- Salon Ramón, Brookside, every 6 weeks.
#
# Runs daily and almost always exits immediately. When a cut comes due,
# schedule.py opens the gate and this hands off to a headless MIST run, which
# is the only piece that can see Alex's Google Calendar (via the Calendar MCP)
# and so is the only piece that can honour "fit it wherever I'm open".
#
# Alex has authorised booking outright, so the run books the slot itself and
# tells him afterwards. The salon allows free online cancellation up to a day
# ahead, so an auto-booked slot is cheap to move.
#
# Fully unattended: Rosy's token dies 30 minutes after sign-in and the site
# cannot renew it, so the booker re-mints one by replaying Chrome's Google SSO
# rather than waiting for Alex to log in.
#
# This replaced the Booksy/Rich Forever version on 2026-09-10. One venue, one
# stylist, so all the deposit-and-ranking logic that job carried is gone: the
# only choice left is which open slot fits the calendar best.
#
# Managed by launchd: com.exobrain.haircut-check (daily, 10:00 local)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HARNESS="$(cd "$SCRIPT_DIR/.." && pwd)"

TIMEOUT_SEC=600

# Close out a past appointment before deciding anything. A lapsed one used to
# expire unrecorded, so the next run saw an empty history and hunted for a slot
# weeks early. This must come before `check`, which reads what it writes.
if RECONCILED="$(python3 "$SCRIPT_DIR/schedule.py" reconcile)"; then
    echo "[$(date)] $RECONCILED"
    # Ask here rather than in the MIST prompt below: once the cut is recorded
    # the cadence is satisfied, so this script exits at the `check` on the next
    # line and MIST never runs. The assumption has to be confirmable anyway.
    "$HARNESS/mist-voice/bin/mist-notify" \
        "Marked your appointment as done and restarted the six weeks. Did you actually go?" \
        "Haircut" none console --reply || true
fi

if ! python3 "$SCRIPT_DIR/schedule.py" check > /dev/null; then
    echo "[$(date)] $(python3 "$SCRIPT_DIR/schedule.py" check || true) -- nothing to do."
    exit 0
fi

# launchd runs with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin) that does not
# include ~/.local/bin, where the Claude CLI lives. This used to resolve above the
# schedule gate, so `command -v claude` came back empty, set -e killed the script
# before it printed anything, and every single daily run failed with a bare exit 1
# and two empty log files. Resolve rather than pin the path: the binary already
# moved once (npm-global -> ~/.local/bin) and will move again.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
if ! CLAUDE_BIN="$(command -v claude)"; then
    echo "[$(date)] claude CLI not found on PATH ($PATH). Cannot book; will retry tomorrow."
    exit 1
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

Alex gets a haircut every 6 weeks at Salon Ramón (6315 Brookside Plaza, Suite 101), with
Ramon Walker himself. Service: Men's Haircut, 45 minutes, \$40.
Standing order: "2 faded to 3 on sides and back, scissors on top".
Exact time is flexible; the rule is to fit it wherever his calendar is open.

Current cadence:
${DUE_INFO}

Do this:

0. If the cadence above mentions an appointment that already happened, say so in your
   notification and ask Alex to confirm he went. The runner has already recorded it as
   completed on the assumption that he did; if he says otherwise, correct it with
   schedule.py record. Rosy cannot answer this, so his word is the only source.

1. Read the open slots:
     cd "${SCRIPT_DIR}" && ./bin/ramon slots --days 60 --since ${WINDOW_START} --until ${WINDOW_END} --json
   An empty list [] means Ramon is genuinely booked solid in that window -- he often is,
   with under 20 openings in 45 days. A non-zero exit or an error means the salon is
   unreachable. Those are different failures; say which one, and never report a dead
   session as "no availability".
   The session signs itself back in (Google SSO replay), so a session error means that
   recovery ALSO failed. Then, and only then, the fix is Alex signing in at
   https://online.rosysalonsoftware.com/appointments in Chrome. Tell him that specifically.

2. Pull his Google Calendar for ${WINDOW_START} to ${WINDOW_END} and work out where he is
   genuinely free. Treat "Sleep", "Wind down", "Extra sleep cycle", "Bootup routine" and
   "Walk" as soft (moveable); treat everything else as hard busy. Leave 30 minutes of
   travel either side -- Brookside is about 15 minutes from him.

3. Pick the slot nearest the due date that sits in a comfortable gap rather than wedged
   between commitments. The slot list is already ranked by his preferences (weekdays,
   10:00-18:00). If NOTHING in the window fits his calendar, widen the search by a week
   before giving up, then notify him with the closest options and let him choose.

4. Book it:
     cd "${SCRIPT_DIR}" && ./bin/ramon book --days 60 --at "YYYY-MM-DD HH:MM" --confirm
   It refuses any time that is not actually open, and it verifies against the server
   afterwards rather than trusting its own POST. If it says "POST returned without error
   but the server has no such appointment", do NOT run it again -- check
   \`./bin/ramon appointments\` first, because a real booking reading back as "nothing
   booked" is exactly how a double-booking gets made.

5. Record it and put it on his calendar:
     cd "${SCRIPT_DIR}" && python3 schedule.py pending --date <YYYY-MM-DD> --provider "Ramon Walker"
   Then create the Google Calendar event at the booked time, 45 minutes long, location
   "Salon Ramón, 6315 Brookside Plaza Suite 101, Kansas City, MO 64113", with the standing
   order in the notes.

6. Tell him, clickable through to his appointment list so he can change it if he wants:
     "${HARNESS}/mist-voice/bin/mist-notify" "<day, time, price>" "Haircut booked" Glass "https://online.rosysalonsoftware.com/appointments"
   Use --reply. One line. Say it is booked, not that it needs booking.

If booking fails for any reason, fall back to notifying him with the slot you picked so he
can finish it by hand at https://www.salonramon.com/, and say plainly that the automation
could not. Never report a booking as done unless \`ramon book\` exited 0 and printed
"Booked:".
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
