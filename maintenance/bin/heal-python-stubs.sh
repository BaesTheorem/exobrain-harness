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
set -euo pipefail
PY_KEG=/opt/homebrew/opt/python@3.12
STABLE_FW="$PY_KEG/Frameworks/Python.framework/Versions/3.12/Python"
HARNESS="$(cd "$(dirname "$0")/../.." && pwd)"
healed=0

heal_stub() {  # $1 = stub path
  local stub="$1"
  [ -f "$stub" ] || return 0
  if "$stub" -c 'import sys' >/dev/null 2>&1; then return 0; fi
  local old
  old=$(otool -L "$stub" 2>/dev/null | awk '/Cellar\/python@/{print $1; exit}')
  echo "healing: $stub (was -> ${old:-unreadable})"
  cp -f "$PY_KEG/bin/python3.12" "$stub.new"
  local cur
  cur=$(otool -L "$stub.new" | awk '/Cellar\/python@/{print $1; exit}')
  if [ -n "$cur" ]; then
    install_name_tool -change "$cur" "$STABLE_FW" "$stub.new" 2>/dev/null
    codesign -s - -f "$stub.new" >/dev/null 2>&1
  fi
  mv -f "$stub.new" "$stub"     # same path: the TCC grant row survives
  "$stub" -c 'import sys' >/dev/null 2>&1 || { echo "  STILL BROKEN"; return 1; }
  echo "  ok ($("$stub" -c 'import sys;print(sys.version.split()[0])'))"
  healed=$((healed+1))
}

for venv in "$HARNESS/imessage/.venv" "$HARNESS/maintenance/venv"; do
  for stub in "$venv"/bin/python* "$venv"/bin/mist-*python3; do
    heal_stub "$stub" || true
  done
done

if [ "$healed" -gt 0 ]; then
  for job in com.exobrain.imessage-sync com.exobrain.tcc-carry-forward; do
    launchctl kickstart -k "gui/$(id -u)/$job" 2>/dev/null || true
  done
  echo "healed $healed stub(s), kickstarted the FDA jobs"
fi
