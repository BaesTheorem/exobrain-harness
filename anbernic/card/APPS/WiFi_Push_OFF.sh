#!/bin/sh
# WiFi Push (OFF): stop the file server started by WiFi_Push_ON.sh.

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/wifipush/wifipush.log"

echo "=== WiFi Push OFF $(date)" >> "$LOG"
if [ -f /tmp/wifipush.pid ]; then
  kill "$(cat /tmp/wifipush.pid)" 2>/dev/null
  rm -f /tmp/wifipush.pid
fi
# Belt and suspenders in case the pidfile went stale.
pkill -f /tmp/dufs 2>/dev/null
echo "server stopped" >> "$LOG"
exit 0
