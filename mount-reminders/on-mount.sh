#!/bin/bash
# Raise a banner when a named volume mounts and there is work waiting on it.
#
# launchd runs this with StartOnMount (every filesystem mount) and at login.
# Reminders live OUTSIDE the repo, one file per volume name:
#   ~/Library/Application Support/exobrain/mount-reminders/<Volume Name>.txt
# Non-empty file + volume present -> one silent, clickable banner per mount.
# Empty or missing file -> nothing. Delete or empty the file when the work is done.
#
# Env overrides (tests): VOLUMES_DIR (default /Volumes), REMINDERS_DIR, NOTIFY.
set -euo pipefail

VOLUMES_DIR="${VOLUMES_DIR:-/Volumes}"
REMINDERS_DIR="${REMINDERS_DIR:-$HOME/Library/Application Support/exobrain/mount-reminders}"
HARNESS="$(cd "$(dirname "$0")/.." && pwd)"
NOTIFY="${NOTIFY:-$HARNESS/mist-voice/bin/mist-notify}"
FLAGS="$REMINDERS_DIR/.notified"
mkdir -p "$REMINDERS_DIR" "$FLAGS"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

shopt -s nullglob
for f in "$REMINDERS_DIR"/*.txt; do
    name="$(basename "$f" .txt)"
    flag="$FLAGS/$name"
    if [ ! -d "$VOLUMES_DIR/$name" ]; then
        # Volume gone: re-arm so the next mount notifies again.
        [ -e "$flag" ] && rm -f "$flag" && log "$name unmounted, re-armed"
        continue
    fi
    if [ ! -s "$f" ]; then
        continue
    fi
    if [ -e "$flag" ]; then
        continue
    fi
    body="$(tr '\n' ' ' < "$f" | sed 's/  */ /g; s/ $//')"
    log "$name mounted, notifying: $body"
    if "$NOTIFY" "$body" "$name is plugged in" none console --reply --group mount-reminders --id "mount-$name"; then
        touch "$flag"
    else
        log "WARN: notify failed for $name (will retry on next mount event)"
    fi
done
