#!/bin/bash
# Hourly Gmail mirror: mbsync pulls [Gmail]/All Mail into a local Maildir, then,
# when the external disk is mounted, rsync copies it there. Append-only on both
# sides. The Maildir is NOT in the nightly Drive archive on purpose: a Drive copy
# dies in the same Google lockout this mirror hedges against.
set -u
CONF="${GMAIL_MIRROR_CONF:-$HOME/.config/gmail-mirror/mbsyncrc}"
MAILDIR="${GMAIL_MIRROR_DIR:-$HOME/Mail/gmail}"
SSD_DIR="${GMAIL_MIRROR_SSD_DIR:-/Volumes/Extreme SSD/Gmail mirror}"
STATE="$HOME/Library/Application Support/exobrain/gmail-mirror"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$STATE" "$MAILDIR"

# Banner at most once a day, so an hourly failure does not become hourly noise.
alarm() {
    echo "[$(date)] ERROR: $1" >&2
    local last="$STATE/last-alarm"
    if [ ! -f "$last" ] || [ -n "$(find "$last" -mmin +1440)" ]; then
        touch "$last"
        "$HERE/../mist-voice/bin/mist-notify" "$1" "Gmail mirror" Basso "$MAILDIR" \
            --context "$(tail -20 "$HOME/Library/Logs/exobrain/gmail-mirror.log" 2>/dev/null)" 2>/dev/null || true
    fi
}

[ -f "$CONF" ] || { alarm "config missing: $CONF (see gmail-mirror/README.md)"; exit 1; }

echo "[$(date)] mbsync start"
if mbsync -c "$CONF" -q gmail-all; then
    date +%s > "$STATE/last-ok"
    rm -f "$STATE/last-alarm"
    echo "[$(date)] mbsync ok ($(du -sh "$MAILDIR" | cut -f1))"
else
    alarm "mbsync failed (exit $?); the local mirror is stale"
fi

# The disk copy runs even when mbsync failed: what is local is still worth copying.
if [ -d "$(dirname "$SSD_DIR")" ]; then
    mkdir -p "$SSD_DIR"
    if rsync -a "$MAILDIR/" "$SSD_DIR/"; then
        echo "[$(date)] copied to $SSD_DIR"
    else
        alarm "copy to $SSD_DIR failed"
    fi
fi
