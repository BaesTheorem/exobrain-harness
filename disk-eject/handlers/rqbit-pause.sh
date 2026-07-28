#!/bin/sh
# Pause every rqbit torrent so it checkpoints before we stop the daemon.
# rqbit has no bulk endpoint -- only POST /torrents/{id}/pause -- so we iterate.
# Best effort by design: if rqbit is unreachable, the caller still SIGTERMs it.
API="${RQBIT_API:-http://localhost:3030}"

curl -s --max-time 5 "$API/torrents" 2>/dev/null | /opt/homebrew/bin/python3 -c '
import json, sys, urllib.request

api = sys.argv[1]
try:
    torrents = json.load(sys.stdin).get("torrents", [])
except Exception:
    sys.exit(0)

for t in torrents:
    tid = t.get("id")
    if tid is None:
        continue
    req = urllib.request.Request(f"{api}/torrents/{tid}/pause", method="POST")
    try:
        urllib.request.urlopen(req, timeout=5).read()
        print(f"paused {tid}")
    except Exception as exc:
        print(f"pause {tid} failed: {exc}")
' "$API" 2>/dev/null || true

exit 0
