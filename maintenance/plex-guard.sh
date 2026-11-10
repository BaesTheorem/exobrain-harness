#!/bin/bash
# plex-guard.sh: keep Plex Media Server running while the media SSD is mounted.
#
# Run by com.alexhedtke.plex (launchd). launchd starts this script at login and
# when the drive mounts (KeepAlive PathState on the drive path), and starts it
# again if it exits while the drive is present. The script itself is the
# supervisor: it checks Plex every CHECK_SECS and
#   - starts Plex when the drive is mounted and no server process exists
#     (first start after a mount or login is silent),
#   - restarts Plex after a crash (the process was up, now it is gone) and
#     sends a banner + Discord DM,
#   - restarts Plex when the process exists but the API has not answered for
#     HUNG_SECS (a hung server), with the same alert.
# It exits when the drive goes away and leaves Plex running, so an eject is
# never blocked by a kill here (maintenance/disk-eject owns a graceful quit).
#
# Plex is started with `open -g -a`, so it belongs to LaunchServices, not to this
# job: a reload of this job does not kill the server.
#
# INVARIANTS
# - Never start Plex when the drive is absent (it would show empty libraries).
# - Never kill a Plex process that answers the API.
# - One alert per restart, never one per check.

{
DRIVE="${PLEX_GUARD_DRIVE:-/Volumes/Extreme SSD}"
APP="Plex Media Server"
API="http://127.0.0.1:32400/identity"
CHECK_SECS="${PLEX_GUARD_CHECK_SECS:-30}"
HUNG_SECS="${PLEX_GUARD_HUNG_SECS:-300}"
NOTIFY="$HOME/Documents/Exobrain harness/mist-voice/bin/mist-notify"
LOG="$HOME/Library/Logs/exobrain/plex-guard.log"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

server_pid() { pgrep -x "$APP" | head -1; }
api_up() { [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$API")" = 200 ]; }

alert() {
  log "ALERT: $1"
  "$NOTIFY" "$1" "Plex restarted" --discord \
    --context "plex-guard on $(hostname -s). Server log: ~/Library/Application Support/Plex Media Server/Logs/Plex Media Server.log. Guard log: $LOG" \
    >/dev/null 2>&1 || log "mist-notify failed"
}

# Plug-in processes outlive a killed server and hold its port and files.
kill_orphans() {
  local p
  for p in $(pgrep -f 'Plex Plug-in \[' ; pgrep -x 'Plex Tuner Service'); do
    kill "$p" 2>/dev/null && log "stopped orphan pid $p"
  done
}

start_server() {
  kill_orphans
  open -g -a "$APP" && log "started Plex ($1)"
  # Give the server time to bind its port before the next check.
  local i
  for i in $(seq 1 30); do api_up && return 0; sleep 2; done
  log "Plex did not answer within 60 s of start"
}

[ -d "$DRIVE" ] || exit 0
log "guard up, drive mounted"

was_up=0          # 1 after we have seen a healthy server in this run
down_since=0      # epoch seconds when the API first failed with a live process

while [ -d "$DRIVE" ]; do
  pid="$(server_pid)"
  if [ -z "$pid" ]; then
    if [ "$was_up" = 1 ]; then
      alert "Plex Media Server stopped without a shutdown. plex-guard started it again."
    fi
    start_server "$([ "$was_up" = 1 ] && echo 'after crash' || echo 'drive mounted')"
    was_up=0; down_since=0
  elif api_up; then
    was_up=1; down_since=0
  else
    now=$(date +%s)
    [ "$down_since" = 0 ] && down_since=$now
    if [ $((now - down_since)) -ge "$HUNG_SECS" ]; then
      log "pid $pid has not answered for $((now - down_since)) s, stopping it"
      kill "$pid" 2>/dev/null
      for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null && log "pid $pid needed SIGKILL"
      alert "Plex Media Server stopped answering for $((HUNG_SECS / 60)) min. plex-guard restarted it."
      start_server "after hang"
      was_up=0; down_since=0
    fi
  fi
  sleep "$CHECK_SECS"
done

log "drive unmounted, guard exiting (Plex left as is)"
exit 0
}
