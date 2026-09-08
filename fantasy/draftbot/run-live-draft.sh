#!/bin/sh
# Tonight's chain: get in, arm, then supervise. Kept as a file so the whole
# sequence survives without anyone typing it at 7:00 sharp.
cd "$(dirname "$0")"
URL="$(cat live-draft-url.txt)"
echo "=== enter.py starting $(date +%H:%M:%S) ==="
python3 -u enter.py "$URL" 5400 || { echo "ENTER FAILED"; exit 1; }
echo "=== supervise.py starting $(date +%H:%M:%S) ==="
exec python3 -u supervise.py 12
