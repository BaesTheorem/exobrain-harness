#!/bin/bash
# Deploy WiFi Roam. Source lives in this repo; the *runtime* is copied to
# ~/Library/Application Support/WiFiRoam because launchd cannot read files under
# ~/Documents (TCC-protected) -- the venv interpreter fails to boot there.
# Idempotent: re-run after editing roam.py to redeploy.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUNTIME="$HOME/Library/Application Support/WiFiRoam"
PY_BASE="/opt/homebrew/opt/python@3.14/bin/python3.14"
APP="$RUNTIME/WiFiRoam.app"
PY="$RUNTIME/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/com.alexhedtke.wifiroam.plist"
LABEL="com.alexhedtke.wifiroam"

mkdir -p "$RUNTIME"

echo "deploying roam.py -> $RUNTIME"
cp "$HERE/roam.py" "$RUNTIME/roam.py"

if [[ ! -x "$PY" ]]; then
  echo "creating venv (one-time)"
  "$PY_BASE" -m venv "$RUNTIME/.venv"
  "$PY" -m pip install -q --disable-pip-version-check \
    pyobjc-framework-CoreWLAN pyobjc-framework-CoreLocation
fi

[[ -f "$RUNTIME/config.json" ]] || cp "$HERE/config.example.json" "$RUNTIME/config.json"

echo "building $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>WiFiRoam</string>
  <key>CFBundleDisplayName</key><string>WiFi Roam</string>
  <key>CFBundleIdentifier</key><string>com.alexhedtke.wifiroam</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>wifiroam</string>
  <key>LSUIElement</key><true/>
  <key>NSLocationUsageDescription</key>
  <string>WiFi Roam reads nearby network names so it can switch this Mac to the best-throughput known wifi.</string>
  <key>NSLocationWhenInUseUsageDescription</key>
  <string>WiFi Roam reads nearby network names so it can switch this Mac to the best-throughput known wifi.</string>
</dict>
</plist>
PLISTEOF

cat > "$APP/Contents/MacOS/wifiroam" <<SHIM
#!/bin/bash
exec "$PY" "$RUNTIME/roam.py" "\$@"
SHIM
chmod +x "$APP/Contents/MacOS/wifiroam"

echo "ad-hoc codesigning"
codesign --force --deep --sign - "$APP"

echo "writing $PLIST"
cat > "$PLIST" <<LAUNCHD
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$APP/Contents/MacOS/wifiroam</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$RUNTIME/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$RUNTIME/launchd.err.log</string>
</dict>
</plist>
LAUNCHD

echo
echo "deployed to: $RUNTIME"
echo "next:"
echo "  1. edit config.json -> set metered_ssids to your hotspot name(s):"
echo "       \"$RUNTIME/config.json\""
echo "  2. open '$APP'                  # click Allow on the Location prompt (re-grant at new path)"
echo "  3. launchctl bootstrap gui/\$(id -u) '$PLIST'"
echo "  (redeploy after editing roam.py: ./setup.sh && launchctl kickstart -k gui/\$(id -u)/$LABEL)"
