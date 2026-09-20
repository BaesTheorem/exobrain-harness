#!/usr/bin/env bash
# Launch the throwaway Chrome with remote debugging, opened to jackbox.tv.
#   launch.sh                 headless (default): no window, no focus change, no flash. jackbox.tv,
#                             its room-lookup API, canvas input and CDP screenshots all verified
#                             working headless on Chrome 153 (2026-09-20).
#   launch.sh --headed        visible window (to watch the bot's "phone"); focus is handed back to
#                             whatever app was in front, since Chrome activates itself on launch.
#   JACKBOX_HEADLESS=new      use --headless=new instead of old (old renders fully offscreen; new
#                             is known to flash the screen once at launch on macOS).
# Idempotent: if something already answers on the CDP port, it just reports that.
PROFILE="${JACKBOX_PROFILE:-/tmp/jackbox-chrome-profile}"
PORT="${JACKBOX_PORT:-9222}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
HEADED=""; [ "$1" = "--headed" ] && HEADED=1

if curl -s -m 1 "http://localhost:$PORT/json/version" >/dev/null 2>&1; then
  echo "Chrome already listening on :$PORT (profile $PROFILE)"; exit 0
fi
mkdir -p "$PROFILE"
ARGS=(--remote-debugging-port="$PORT" --user-data-dir="$PROFILE" --no-first-run --no-default-browser-check
      --mute-audio --window-size=520,900 --window-position=40,40 "https://jackbox.tv")
front() { osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true' 2>/dev/null; }
if [ -n "$HEADED" ]; then
  WAS="$(front)"
  open -n -a "Google Chrome" --args --new-window "${ARGS[@]}"
  MODE=headed
else
  "$CHROME" "--headless=${JACKBOX_HEADLESS:-old}" "${ARGS[@]}" >/tmp/jackbox-chrome.log 2>&1 &
  MODE="headless-${JACKBOX_HEADLESS:-old}"
fi
for i in $(seq 1 40); do
  if curl -s -m 1 "http://localhost:$PORT/json/version" >/dev/null 2>&1; then
    if [ -n "$HEADED" ] && [ -n "$WAS" ]; then
      sleep 1.5   # Chrome activates its window after the port opens; hand focus back afterwards
      osascript -e "tell application \"System Events\" to set frontmost of process \"$WAS\" to true" 2>/dev/null
    fi
    echo "jackbox Chrome up ($MODE), CDP on http://localhost:$PORT"; exit 0
  fi
  sleep 0.25
done
echo "Chrome did not answer on :$PORT within 10s (see /tmp/jackbox-chrome.log)" >&2; exit 1
