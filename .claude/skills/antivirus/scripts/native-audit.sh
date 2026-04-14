#!/bin/bash
# Native macOS security audit — Phases 1-6 from the antivirus skill.
# Prints structured output suitable for ingestion into a Security/av-scans/ report.
set -u

echo "# Native macOS audit — $(date '+%Y-%m-%d %H:%M:%S')"
echo

echo "## Phase 1 — OS protections"
echo "- SIP: $(csrutil status 2>&1 | sed 's/^.*: //')"
echo "- Gatekeeper: $(spctl --status 2>&1)"
echo "- FileVault: $(fdesetup status 2>&1)"
echo "- Firewall: $(/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate 2>&1 | tail -1)"
echo "- XProtect version: $(defaults read /Library/Apple/System/Library/CoreServices/XProtect.bundle/Contents/Info CFBundleShortVersionString 2>/dev/null || echo unknown)"
echo

echo "## Phase 2 — Persistence"
echo "### User LaunchAgents"
ls ~/Library/LaunchAgents/ 2>/dev/null | sed 's/^/- /'
echo "### System LaunchAgents (non-Apple)"
ls /Library/LaunchAgents/ 2>/dev/null | sed 's/^/- /'
echo "### System LaunchDaemons (non-Apple)"
ls /Library/LaunchDaemons/ 2>/dev/null | sed 's/^/- /'
echo "### Login items"
osascript -e 'tell application "System Events" to get the name of every login item' 2>/dev/null
echo

echo "## Phase 3 — Known-bad paths"
FOUND=0
for p in \
  "$HOME/Library/Application Support/Genieo" \
  "$HOME/Library/Application Support/MacKeeper" \
  "$HOME/Library/Application Support/VSearch" \
  "$HOME/Library/mdworker_shared" \
  "$HOME/Library/softwareupdated" \
  "/Applications/MPlayerX.app" \
  "/Applications/Shlayer.app" \
  "/Library/LaunchAgents/com.apple.softwareupdated.plist" \
  "/private/tmp/GoogleSoftwareUpdateAgent.bundle" ; do
  if [ -e "$p" ]; then
    echo "- FOUND: $p"
    FOUND=1
  fi
done
[ "$FOUND" -eq 0 ] && echo "- none"
echo

echo "## Phase 4 — Network listeners"
lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR==1 || $1 !~ /^(rapportd|ControlCe|sharingd|mDNSResp|rpc.state|nfsd|AirPlay)$/'
echo

echo "## Phase 5 — Browser extensions"
echo "### Chrome (Default profile)"
for ext_dir in "$HOME/Library/Application Support/Google/Chrome/Default/Extensions/"*/; do
  ext_id=$(basename "$ext_dir")
  manifest=$(find "$ext_dir" -name manifest.json -maxdepth 2 2>/dev/null | head -1)
  if [ -n "$manifest" ]; then
    name=$(python3 -c "import json; m=json.load(open('$manifest')); print(m.get('name', '?'))" 2>/dev/null)
    perms=$(python3 -c "import json; m=json.load(open('$manifest')); p=m.get('permissions', []); print(','.join(x for x in p if isinstance(x, str))[:100])" 2>/dev/null)
    echo "- $ext_id | $name | $perms"
  fi
done
echo "### Safari"
ls ~/Library/Safari/Extensions/ 2>/dev/null | sed 's/^/- /'
echo

echo "## Phase 6 — Quarantine (last 30)"
sqlite3 ~/Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2 \
  "SELECT datetime(LSQuarantineTimeStamp + 978307200, 'unixepoch', 'localtime') || ' | ' ||
          COALESCE(LSQuarantineAgentName,'?') || ' | ' ||
          COALESCE(LSQuarantineDataURLString,'')
   FROM LSQuarantineEvent
   ORDER BY LSQuarantineTimeStamp DESC LIMIT 30;" 2>/dev/null | sed 's/^/- /'
