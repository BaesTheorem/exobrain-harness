#!/usr/bin/env bash
# Launch a throwaway Chrome with remote debugging on :9222, opened to jackbox.tv.
# Uses a dedicated profile so the user's real Chrome/profile is never touched.
# Runs in the background; the CDP session persists across separate node calls.
PROFILE="${JACKBOX_PROFILE:-/tmp/jackbox-chrome-profile}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
mkdir -p "$PROFILE"
"$CHROME" --remote-debugging-port=9222 \
  --user-data-dir="$PROFILE" \
  --no-first-run --no-default-browser-check \
  --new-window "https://jackbox.tv" \
  >/tmp/jackbox-chrome.log 2>&1 &
echo "jackbox Chrome launched (pid $!), CDP on http://localhost:9222"
