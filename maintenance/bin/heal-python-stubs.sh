#!/bin/bash
# Heal the dedicated TCC interpreter stubs after a Homebrew python patch bump.
#
# venv --copies produces a stub whose LC_LOAD_DYLIB references the *versioned*
# Cellar framework path (Cellar/python@3.12/3.12.13/...). brew deletes that
# directory on every patch upgrade, killing the stub with a dyld error and
# taking imessage-sync and tcc-carry-forward down with it (observed 2026-08-25).
#
# Fix: re-copy the current stub, rewrite the framework reference to the
# version-stable opt path (/opt/homebrew/opt/python@3.12/...), ad-hoc re-sign.
# The file PATH never changes, so the FDA grant row still applies;
# tcc-carry-forward reconciles the csreq if macOS balks at the new cdhash.
# Idempotent: healthy stubs are left untouched.
#
# DO NOT health-check a stub by running it (2026-08-27). These venvs live under
# ~/Documents, which is TCC-protected. A stub with no Documents-folder grant
# raises a consent prompt, and under launchd nobody can answer it, so the
# process BLOCKS indefinitely. The old exec-based canary tested all six
# python* stubs, but only the two mist-*python3 stubs are ever run by a launchd
# job and only those have TCC grants; the other four hung or were denied every
# single run, were reported "STILL BROKEN", and fired a false "Brew update broke
# something" notification on every brew change. Worse, the rebuild changes the
# ad-hoc cdhash, which invalidates the very TCC grant it depends on.
# So: detect dyld breakage with otool (no exec, no TCC), and exec-canary ONLY
# the job stubs, under a hard timeout, and trust the owning job over the canary.
set -euo pipefail
HARNESS="$(cd "$(dirname "$0")/../.." && pwd)"
healed=0
tcc_blocked=()

# Stubs a launchd job actually invokes. These are the only ones that need to
# *run* correctly outside a UI session, and the only ones holding TCC grants.
# mist-fantasy-python3 (2026-09-30) exists because tccd cannot parse the
# signature of the brew python3.14 launcher stub ("failed to read header ...
# truncated"), so an "access data from other apps" grant keyed on that path is
# never matched and the dialog returns on every run that reaches Things 3.
JOB_STUBS=(
  "$HARNESS/imessage/.venv/bin/mist-imessage-python3"
  "$HARNESS/maintenance/venv/bin/mist-tcc-python3"
  "$HARNESS/fantasy/venv/bin/mist-fantasy-python3"
)

# The framework this stub links against, or "" if the Mach-O is unreadable.
fw_ref() { /usr/bin/otool -L "$1" 2>/dev/null | awk '/Python\.framework/{print $1; exit}'; }

# The signing identity a stub carries: the Apple Development certificate's
# common name when it was signed with one, else "-" (ad-hoc). A rebuilt stub
# is signed the same way, because the identity is what its TCC rows key on.
# Ad-hoc rows store no code requirement, so an "access data from other apps"
# row keyed on an ad-hoc binary never matches again; the fantasy stub is
# signed with the developer certificate for that reason (2026-09-30).
sign_id_of() {
  local cn
  cn=$(/usr/bin/codesign -dvv "$1" 2>&1 | sed -nE 's/^Authority=(Apple Development: .*)$/\1/p' | head -1)
  echo "${cn:--}"
}

# The python minor series a stub was built from (3.12, 3.14), read off its
# framework reference, Cellar or opt path alike. Falls back to 3.12, the
# series every stub used before the fantasy one arrived.
series_of() {
  local s; s=$(fw_ref "$1" | sed -nE 's#.*python@([0-9]+\.[0-9]+)/.*#\1#p')
  echo "${s:-3.12}"
}

# dyld-broken == the linked framework no longer exists on disk. No exec needed.
dyld_broken() {
  local ref; ref=$(fw_ref "$1")
  [ -n "$ref" ] || return 0
  [ -e "$ref" ] && return 1 || return 0
}

# The canary's stderr, kept so an EXEC FAIL in the log says why.
CANARY_ERR=$(mktemp -t heal-canary)
trap 'rm -f "$CANARY_ERR"' EXIT

# Run a command with a hard wall-clock limit. macOS has no timeout(1).
# Returns the command's rc, or 137 when the watchdog had to SIGKILL it.
run_limited() {
  local secs="$1"; shift
  "$@" >/dev/null 2>"$CANARY_ERR" & local pid=$!
  ( sleep "$secs"; kill -9 "$pid" 2>/dev/null ) & local wd=$!
  local rc=0
  wait "$pid" 2>/dev/null || rc=$?
  kill "$wd" 2>/dev/null || true
  wait "$wd" 2>/dev/null || true
  return "$rc"
}

heal_stub() {  # $1 = stub path
  local stub="$1"
  [ -f "$stub" ] || return 0
  dyld_broken "$stub" || return 0
  echo "healing: $stub (was -> $(fw_ref "$stub" || true))"
  local ser; ser=$(series_of "$stub")
  local keg="/opt/homebrew/opt/python@$ser"
  local stable_fw="$keg/Frameworks/Python.framework/Versions/$ser/Python"
  local ident; ident=$(sign_id_of "$stub")
  cp -f "$keg/bin/python$ser" "$stub.new"
  local cur; cur=$(fw_ref "$stub.new")
  if [ -n "$cur" ] && [ "$cur" != "$stable_fw" ]; then
    install_name_tool -change "$cur" "$stable_fw" "$stub.new" || true
    codesign -s "$ident" -f -i "com.exobrain.$(basename "$stub")" "$stub.new" >/dev/null 2>&1 \
      || echo "  WARN: resign failed (identity: $ident)"
  fi
  mv -f "$stub.new" "$stub"     # same path: the TCC grant row survives
  if dyld_broken "$stub"; then echo "  STILL BROKEN (framework ref unresolved)"; return 1; fi
  echo "  ok (relinked -> $(fw_ref "$stub"))"
  healed=$((healed+1))
}

for venv in "$HARNESS/imessage/.venv" "$HARNESS/maintenance/venv" "$HARNESS/fantasy/venv"; do
  for stub in "$venv"/bin/python* "$venv"/bin/mist-*python3; do
    heal_stub "$stub" || true
  done
done

# Exec-canary the job stubs only, bounded, so a stale TCC grant surfaces as a
# TCC problem instead of masquerading as a dyld break.
#
# The canary runs in this job's TCC context, not the owning job's. The fantasy
# stub is denied Documents here (PermissionError on pyvenv.cfg) while
# roster-watch runs it cleanly (2026-09-30). So a canary failure only counts
# when the owning job also failed its last run, or when a stub was rebuilt
# this run and that job's last exit code predates the rebuild.
owner_job() {
  case "$(basename "$1")" in
    mist-imessage-python3) echo com.exobrain.imessage-sync ;;
    mist-tcc-python3)      echo com.exobrain.tcc-carry-forward ;;
    mist-fantasy-python3)  echo com.exobrain.roster-watch ;;
  esac
}
owner_ok() {  # $1 = stub; true when the owning job's last run exited 0
  local job; job=$(owner_job "$1")
  [ -n "$job" ] && [ "$healed" -eq 0 ] || return 1
  launchctl print "gui/$(id -u)/$job" 2>/dev/null | grep -q "last exit code = 0"
}

for stub in "${JOB_STUBS[@]}"; do
  [ -f "$stub" ] || continue
  rc=0; run_limited 10 "$stub" -c 'import sys' || rc=$?
  if [ "$rc" -ne 0 ] && owner_ok "$stub"; then
    echo "canary rc=$rc for $(basename "$stub") in this context, but $(owner_job "$stub") last exited 0: ok"
    continue
  fi
  case "$rc" in
    0)   ;;
    137) echo "TCC-BLOCKED: $stub hung on a Documents-folder consent prompt"
         tcc_blocked+=("$(basename "$stub")") ;;
    *)   echo "EXEC FAIL (rc=$rc): $stub"
         tail -5 "$CANARY_ERR" | sed 's/^/  stderr: /'
         tcc_blocked+=("$(basename "$stub") rc=$rc") ;;
  esac
done

if [ "$healed" -gt 0 ]; then
  for job in com.exobrain.imessage-sync com.exobrain.tcc-carry-forward com.exobrain.roster-watch; do
    launchctl kickstart -k "gui/$(id -u)/$job" 2>/dev/null || true
  done
  echo "healed $healed stub(s), kickstarted the FDA jobs"
fi

if [ ${#tcc_blocked[@]} -gt 0 ]; then
  echo "TCC_REGRANT_NEEDED: ${tcc_blocked[*]}"
  exit 2   # distinct from a heal failure: needs a human in System Settings
fi
exit 0
