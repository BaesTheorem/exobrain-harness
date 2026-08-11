#!/bin/zsh
# Build + install "/Applications/MIST Notifier.app" from main.swift. Idempotent.
#
# Hard requirements learned the slow way (macOS 26):
#  - The app MUST live in /Applications. usernoted validates the caller against
#    its Launch Services record and refuses apps in /tmp or other scratch paths
#    with UNErrorDomain Code=1 before the permission prompt can ever fire.
#  - The bundle executable MUST be the Mach-O that calls UserNotifications.
#    A launcher script that execs an interpreter fails the same validation
#    (which is why the MIST Console can't post these itself).
#  - Sign with a real identity when one exists (Apple Development from Xcode);
#    ad-hoc is the fallback.
#  - NEVER re-sign an app while it's running: macOS revokes the live process's
#    TCC grants (Documents access etc.) on the signature mismatch.
set -e

DIR="${0:A:h}"
APP="/Applications/MIST Notifier.app"
BIN="MIST Notifier"

if pgrep -f "MIST Notifier.app/Contents/MacOS" >/dev/null 2>&1; then
  echo "MIST Notifier is running. Not rebuilding under it. Quit it and re-run."
  exit 1
fi

echo "Building $APP ..."
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -swift-version 5 "$DIR/main.swift" -o "$APP/Contents/MacOS/$BIN"

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>MIST</string>
  <key>CFBundleDisplayName</key><string>MIST</string>
  <key>CFBundleIdentifier</key><string>com.exobrain.mist-notifier</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>MIST Notifier</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

# Icon: build from the MIST logo; fall back to the Console's already-built icns.
# Never let icon trouble abort the install; the app matters more than its face.
set +e
ICON_SRC="/Users/alexhedtke/Documents/mist-console/static/mist-logo.png"
CONSOLE_ICNS="/Applications/MIST Console.app/Contents/Resources/AppIcon.icns"
TMP="$(mktemp -d)"
if sips -s format png "$ICON_SRC" --out "$TMP/src.png" >/dev/null 2>&1; then
  W=$(sips -g pixelWidth  "$TMP/src.png" | awk '/pixelWidth/{print $2}')
  H=$(sips -g pixelHeight "$TMP/src.png" | awk '/pixelHeight/{print $2}')
  S=$(( W > H ? W : H ))
  sips --padToHeightWidth "$S" "$S" --padColor 0E1C2B "$TMP/src.png" --out "$TMP/sq.png" >/dev/null 2>&1
  ICONSET="$TMP/MIST.iconset"; mkdir -p "$ICONSET"
  for sz in 16 32 64 128 256 512; do
    sips -z $sz $sz "$TMP/sq.png" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null 2>&1
    sips -z $((sz*2)) $((sz*2)) "$TMP/sq.png" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" >/dev/null 2>&1 \
    && echo "  icon: built from mist-logo.png"
fi
rm -rf "$TMP"
if [ ! -f "$APP/Contents/Resources/AppIcon.icns" ] && [ -f "$CONSOLE_ICNS" ]; then
  cp "$CONSOLE_ICNS" "$APP/Contents/Resources/AppIcon.icns"
  echo "  icon: copied from MIST Console"
fi
set -e

IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null \
  | awk -F'"' '/Apple Development/{print $2; exit}')
if [ -n "$IDENTITY" ]; then
  codesign --force -s "$IDENTITY" "$APP"
  echo "  signed: $IDENTITY"
else
  codesign --force -s - "$APP"
  echo "  signed: ad-hoc (no Apple Development identity found)"
fi

/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
echo "Done. First run asks macOS's one-time notification permission:"
echo "  open -a \"$APP\" --args auth"
