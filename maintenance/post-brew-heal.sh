#!/bin/bash
# Post-Homebrew self-heal: runs automatically (WatchPaths on /opt/homebrew/Cellar)
# whenever brew installs, upgrades, or removes anything, plus a daily backstop.
#
# Why this exists (2026-08-25): an unattended 2:30 AM `brew upgrade` bumped
# python@3.12/3.14, node, ffmpeg and llvm, and took down six launchd jobs three
# different ways:
#   1. dyld: venv-copied python stubs hard-reference the *versioned* Cellar
#      framework path, which brew deletes on every patch bump (imessage-sync,
#      tcc-carry-forward).
#   2. launchd LWCR: jobs whose Program is a brew binary fail EX_CONFIG /
#      OS_REASON_CODESIGNING after the binary is replaced, until re-bootstrapped
#      (bounty-hunter, awair, asp-baton, comp-hunter, heilung, nest-nightlog).
#   3. plain crash during the swap (5etools under new node) -- self-recovers,
#      but we verify.
# Playwright's chromium cache also vanishes when its package bumps revisions.
#
# All output to the log; a notification fires only when something was healed or
# stays broken. Safe to run any time; every step is idempotent.
set -uo pipefail
LOG="$HOME/Library/Logs/exobrain/post-brew-heal.log"
HARNESS="$(cd "$(dirname "$0")/.." && pwd)"
NOTIFY="$HARNESS/mist-voice/bin/mist-notify"
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') post-brew-heal ==="

# Brew runs touch the Cellar many times; settle before acting.
sleep 60
healed=(); broken=()

# -- 1. TCC python stubs (dyld class) --------------------------------------
out=$("$HARNESS/maintenance/bin/heal-python-stubs.sh" 2>&1); rc=$?
echo "$out"
if echo "$out" | grep -q "^healed"; then healed+=("python stubs relinked"); fi
# rc=2 is not a dyld break. A rebuilt stub has a new ad-hoc cdhash, so its TCC
# row no longer matches and only a human can re-add it in System Settings.
# Keep it distinct so the notification can say what to actually do.
if [ "$rc" -eq 2 ] || echo "$out" | grep -q "TCC_REGRANT_NEEDED"; then
  tcc_regrant=$(echo "$out" | sed -n 's/^TCC_REGRANT_NEEDED: //p')
  broken+=("TCC grant stale for ${tcc_regrant:-the FDA stubs}")
elif [ "$rc" -ne 0 ] || echo "$out" | grep -q "STILL BROKEN"; then
  broken+=("python stub heal failed")
fi

# -- 2. launchd jobs stuck on a replaced binary (LWCR class) ---------------
UID_N=$(id -u)
for p in "$HOME"/Library/LaunchAgents/com.exobrain.*.plist "$HOME"/Library/LaunchAgents/com.mist.*.plist; do
  [ -f "$p" ] || continue
  label=$(basename "$p" .plist)
  info=$(launchctl print "gui/$UID_N/$label" 2>/dev/null) || continue   # not loaded = not ours to decide
  if echo "$info" | grep -qE "last exit code = 78|OS_REASON_CODESIGNING|OS_REASON_DYLD"; then
    echo "re-bootstrapping $label"
    launchctl bootout "gui/$UID_N/$label" 2>/dev/null
    # bootout returns before launchd finishes tearing the service down; an
    # immediate bootstrap can race it and fail (took claude-bot down for 9h on
    # 2026-08-27). Retry with a settle delay before declaring it broken.
    ok=0
    for attempt in 1 2 3; do
      sleep $((attempt * 2))
      if launchctl bootstrap "gui/$UID_N" "$p" 2>/dev/null; then ok=1; break; fi
      echo "  bootstrap attempt $attempt failed for $label; retrying"
    done
    if [ "$ok" -eq 1 ]; then
      healed+=("$label re-bootstrapped")
    else
      broken+=("$label failed to bootstrap")
    fi
  fi
done

# -- 3. venv canary (report-only: rebuilding project venvs is a human call) -
while IFS= read -r py; do
  [ -x "$py" ] || continue
  if ! "$py" -c 'import sys' >/dev/null 2>&1; then
    echo "BROKEN venv: $py"
    broken+=("venv dead: ${py/#$HOME/~}")
  fi
done <<VENVS
$HOME/Documents/Exobrain harness/imessage/.venv/bin/mist-imessage-python3
$HOME/Documents/Exobrain harness/maintenance/venv/bin/mist-tcc-python3
$HOME/Documents/Exobrain harness/mist-voice/.venv/bin/python
$HOME/Documents/Exobrain harness/claude-bot/.venv/bin/python
$HOME/Documents/claude-home/.venv/bin/python
$HOME/Documents/claude-home/integrations/nest/.venv/bin/python
$HOME/Documents/envelope-budget/.venv/bin/python
$HOME/Documents/petkit-loki/.venv/bin/python
VENVS

# -- 4. headline interpreters + playwright browser cache -------------------
/opt/homebrew/bin/python3 -c 'import sys' 2>/dev/null || broken+=("brew python3 broken")
/opt/homebrew/bin/node -e 1 2>/dev/null || broken+=("brew node broken")
if /opt/homebrew/bin/python3 - <<'PY' 2>/dev/null | grep -q MISSING
try:
    from playwright.sync_api import sync_playwright  # noqa
    import pathlib, json, re
    import playwright, os
    d=pathlib.Path(playwright.__file__).parent/"driver"/"package"/"browsers.json"
    spec=json.load(open(d))
    rev=[b["revision"] for b in spec["browsers"] if b["name"]=="chromium_headless_shell"]
    cache=pathlib.Path.home()/"Library/Caches/ms-playwright"
    if rev and not (cache/f"chromium_headless_shell-{rev[0]}").exists():
        print("MISSING")
except ModuleNotFoundError:
    pass
PY
then
  echo "playwright browser cache stale; reinstalling"
  if /opt/homebrew/bin/python3 -m playwright install chromium >/dev/null 2>&1; then
    healed+=("playwright chromium reinstalled")
  else
    broken+=("playwright browser reinstall failed")
  fi
fi

# -- 5. summary ------------------------------------------------------------
echo "healed: ${healed[*]:-none} | broken: ${broken[*]:-none}"
# The banner click must land somewhere that explains itself. "console" only
# raised whatever chat happened to be open, which told Alex nothing about the
# brew problem, so the default target is the log. A stable --id means a repeat
# replaces the banner in place instead of stacking another identical one.
FDA_PANE="x-apple.systempreferences:com.apple.preference.security?Privacy_DocumentsFolder"
if [ ${#broken[@]} -gt 0 ]; then
  "$NOTIFY" "After a Homebrew change: ${broken[*]}. Healed: ${healed[*]:-nothing}." \
    "Brew update broke something" "" "$LOG" \
    --subtitle "Click to open post-brew-heal.log" \
    --action "Open log=$LOG" \
    --action "Privacy settings=$FDA_PANE" \
    --action "Ask MIST to fix=console" \
    --group brew-heal --id brew-heal --urgency active 2>/dev/null
elif [ ${#healed[@]} -gt 0 ]; then
  "$NOTIFY" "Homebrew changed and everything self-healed: ${healed[*]}" \
    "Brew update absorbed" "" "$LOG" \
    --subtitle "Click to open post-brew-heal.log" \
    --group brew-heal --id brew-heal 2>/dev/null
fi
exit 0
