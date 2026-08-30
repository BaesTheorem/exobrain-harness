#!/bin/sh
# WiFi Push (ON): start a file server so a computer can push ROMs to this card.
#
# Lives in Roms/APPS/ on the stock OS card of an Anbernic RG35XX-family device.
# Launch it from the APPS menu; it starts dufs in the background serving the
# card's ROMS partition on port 8035, then returns to the menu. Pair with
# push-rom on the computer side. WiFi_Push_OFF.sh stops the server.
#
# Binaries are copied to /tmp before exec because FAT cards may mount noexec.

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
WP="$DIR/wifipush"
LOG="$WP/wifipush.log"
PORT=8035

mkdir -p "$WP"
echo "=== WiFi Push ON $(date)" >> "$LOG"

case "$(uname -m)" in
  aarch64|arm64) BIN="$WP/dufs-arm64" ;;
  *)             BIN="$WP/dufs-arm32" ;;
esac
echo "arch=$(uname -m) bin=$BIN root=$ROOT" >> "$LOG"

if [ ! -f "$BIN" ]; then
  echo "ERROR: $BIN missing (copy the wifipush folder to Roms/APPS/)" >> "$LOG"
  exit 1
fi

# Stop any previous instance, then run from RAM.
if [ -f /tmp/wifipush.pid ]; then
  kill "$(cat /tmp/wifipush.pid)" 2>/dev/null
  rm -f /tmp/wifipush.pid
fi
cp "$BIN" /tmp/dufs && chmod 755 /tmp/dufs

if command -v setsid >/dev/null 2>&1; then
  setsid /tmp/dufs -A -b 0.0.0.0 -p "$PORT" "$ROOT" >> "$LOG" 2>&1 &
else
  nohup /tmp/dufs -A -b 0.0.0.0 -p "$PORT" "$ROOT" >> "$LOG" 2>&1 &
fi
echo $! > /tmp/wifipush.pid
sleep 1

if kill -0 "$(cat /tmp/wifipush.pid)" 2>/dev/null; then
  echo "server up, pid $(cat /tmp/wifipush.pid), port $PORT" >> "$LOG"
else
  echo "ERROR: server died right after start, see above" >> "$LOG"
fi
{ ip addr 2>/dev/null || ifconfig 2>/dev/null; } | grep 'inet ' >> "$LOG"
exit 0
