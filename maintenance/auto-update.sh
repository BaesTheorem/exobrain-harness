#!/bin/bash
# Keeps installed tools current: Homebrew formulae and casks, global npm
# packages, uv tools, and cargo binaries. Mac App Store apps are left to the App
# Store's own automatic updates: mas 7 wants sudo for `mas upgrade`, which a
# launchd job cannot supply. The Claude CLI has its own
# job (claude-cli-autoupdate.sh) and Playwright browsers are re-fetched by
# post-brew-heal.sh, which fires on its own when this run changes the Cellar.
#
# Why (2026-10-23): a Node Brotli RCE (CVE-2026-111497) found Homebrew node two
# months stale and 111 formulae outdated. Nothing upgraded on a schedule.
#
# When it runs: launchd starts it every hour; it does real work at most once a
# day, only on AC power, and only in the 1-6 AM window or when Alex has been idle
# for 20+ minutes (a cask upgrade can quit a running app). Pass --force to skip
# those gates.
#
# Hold a formula back with `brew pin <name>`; brew upgrade skips pinned formulae.
#
# Notifies (banner + Discord DM, one digest) only when a step fails or a
# package jumps a major version. Major bumps are the ones that break dependents
# (ffmpeg 8->9 silently broke torchcodec for five weeks in 2026), so the digest
# names them to suspect first. Everything else goes to the log.
set -uo pipefail
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$HOME/.npm-global/bin:$HOME/.cargo/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOMEBREW_NO_ENV_HINTS=1 NONINTERACTIVE=1

HARNESS="$(cd "$(dirname "$0")/.." && pwd)"
NOTIFY="$HARNESS/mist-voice/bin/mist-notify"
LOG="$HOME/Library/Logs/exobrain/auto-update.log"
STATE="$HOME/Library/Application Support/exobrain/auto-update"
STAMP="$STATE/last-success"
mkdir -p "$STATE" "$(dirname "$LOG")"

force=0; [ "${1:-}" = "--force" ] && force=1

# -- gates --------------------------------------------------------------------
if [ "$force" -eq 0 ]; then
  now=$(date +%s)
  last=$(cat "$STAMP" 2>/dev/null || echo 0)
  [ $((now - last)) -lt $((20 * 3600)) ] && exit 0
  pmset -g batt | head -1 | grep -q "AC Power" || exit 0
  hour=$(date +%-H)
  idle=$(ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {print int($NF/1000000000); exit}')
  if ! { [ "$hour" -ge 1 ] && [ "$hour" -lt 6 ]; } && [ "${idle:-0}" -lt 1200 ]; then
    exit 0
  fi
fi

# One run at a time (mkdir is atomic). A lock older than 3 h is a dead run.
LOCK="$STATE/lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +180 2>/dev/null)" ]; then
    rmdir "$LOCK" && mkdir "$LOCK" || exit 0
  else
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') auto-update ==="

failed=()
snapshot() {
  { brew list --versions --formula 2>/dev/null | sed 's/^/brew /'
    brew list --versions --cask 2>/dev/null | sed 's/^/cask /'
    npm ls -g --depth=0 2>/dev/null | sed -n 's/^[├└]── \(.*\)@\([^@]*\)$/npm \1 \2/p'
    uv tool list 2>/dev/null | sed -n 's/^\([^ -][^ ]*\) v\(.*\)$/uv \1 \2/p'
  } | sort
}
step() {  # step <name> <command...>
  local name=$1; shift
  echo "--- $name"
  if ! nice -n 10 "$@"; then
    echo "!!! $name failed"
    failed+=("$name")
  fi
}

before=$(snapshot)

step "brew update" brew update
# brew upgrade exits non-zero if any single package fails but still upgrades the
# rest, so one bad cask (an untrusted tap, a pkg that wants sudo) cannot stall
# everything else.
step "brew upgrade" brew upgrade --formula
step "brew upgrade --cask" brew upgrade --cask
step "npm update -g" npm update -g
step "uv tool upgrade" uv tool upgrade --all
if command -v cargo >/dev/null; then
  while IFS= read -r crate; do
    step "cargo install $crate" cargo install --locked "$crate"
  done < <(cargo install --list | sed -n 's/^\([^ ]*\) v.*:$/\1/p')
fi
step "brew cleanup" brew cleanup --prune=30

# A new default python formula takes the unversioned python3 link with it.
step "pin python3" "$HARNESS/maintenance/bin/pin-python3-default"

# A keg that installed but did not link is usually a file pip put in Homebrew's
# site-packages first (pillow, pydantic, rpds-py on 2026-10-23). Name them: the
# fix is `pip uninstall` of the stale copy, then `brew link --overwrite`.
unlinked=$(brew info --json=v2 --installed 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(" ".join(f["name"] for f in d["formulae"]
               if not f["keg_only"] and not f["linked_keg"]
               and not f["name"].startswith("python@")))' 2>/dev/null)
[ -n "$unlinked" ] && echo "unlinked: $unlinked" && failed+=("not linked: $unlinked")

after=$(snapshot)

# Major-version bumps: the first number of the version changed. A first field
# of 1000 or more is a date (libewf 20140816), not a major version.
majors=$(join -j1 \
  <(echo "$before" | awk '{print $1":"$2, $NF}' | sort) \
  <(echo "$after"  | awk '{print $1":"$2, $NF}' | sort) |
  awk '{ split($2,a,/[.,_-]/); split($3,b,/[.,_-]/);
         if (a[1] ~ /^[0-9]+$/ && b[1] ~ /^[0-9]+$/ && a[1] < 1000 && a[1] != b[1]) {
           sub(/^[^:]*:/, "", $1); print $1" "$2"->"$3 } }')
changed=$(diff <(echo "$before") <(echo "$after") | grep -c '^>' || true)

echo "changed: $changed package(s)"
[ -n "$majors" ] && echo "major bumps:" && echo "$majors"

# Stamp even after a failure: a step that fails every time (a cask that wants
# sudo) must cost one banner a day, not one an hour.
date +%s > "$STAMP"

if [ "${#failed[@]}" -gt 0 ] || [ -n "$majors" ]; then
  msg="Updated $changed package(s)."
  [ -n "$majors" ] && msg="$msg Major bumps: $(echo "$majors" | paste -sd ',' - | sed 's/,/, /g')."
  [ "${#failed[@]}" -gt 0 ] && msg="$msg Failed: ${failed[*]}."
  "$NOTIFY" "$msg" "Software updates" "" "$LOG" \
    --subtitle "Click to open auto-update.log" \
    --action "Open log=$LOG" \
    --context-file "$LOG" \
    --group auto-update --id auto-update --discord 2>/dev/null
fi
echo "=== done $(date '+%H:%M:%S')"
exit 0
