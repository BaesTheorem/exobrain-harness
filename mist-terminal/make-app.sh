#!/bin/zsh
# Build (or rebuild) MIST.app — a double-clickable launcher that opens Ghostty
# (MIST theme, from ~/.config/ghostty/config) running mist-terminal/bin/mist.
# Idempotent: safe to re-run after editing the launcher.
set -e

HARNESS="/Users/alexhedtke/Documents/Exobrain harness"
APP="$HOME/Desktop/Apps/MIST.app"
GHOSTTY="/Applications/Ghostty.app/Contents/MacOS/ghostty"
ICON_SRC="$HARNESS/.claude/MIST 1.webp"   # Cloud form — fitting for the first Cloud Intelligence

echo "Building $APP ..."
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# --- Launcher: open a new Ghostty window in the harness, running the MIST launcher ---
cat > "$APP/Contents/MacOS/MIST" <<EOF
#!/bin/zsh
exec "$GHOSTTY" --working-directory="$HARNESS" -e "$HARNESS/mist-terminal/bin/mist"
EOF
chmod +x "$APP/Contents/MacOS/MIST"

# --- Info.plist ---
cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>MIST</string>
  <key>CFBundleDisplayName</key><string>MIST</string>
  <key>CFBundleIdentifier</key><string>com.exobrain.mist-terminal</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>MIST</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF

# --- App icon from the Cloud-form portrait (optional; skip cleanly if anything fails) ---
if [ -f "$ICON_SRC" ]; then
  TMP="$(mktemp -d)"
  if sips -s format png "$ICON_SRC" --out "$TMP/src.png" >/dev/null 2>&1; then
    # Square it by padding to the larger dimension, then build the iconset.
    W=$(sips -g pixelWidth  "$TMP/src.png" | awk '/pixelWidth/{print $2}')
    H=$(sips -g pixelHeight "$TMP/src.png" | awk '/pixelHeight/{print $2}')
    S=$(( W > H ? W : H ))
    sips --padToHeightWidth "$S" "$S" --padColor 0E1C2B "$TMP/src.png" --out "$TMP/sq.png" >/dev/null 2>&1
    ICONSET="$TMP/MIST.iconset"; mkdir -p "$ICONSET"
    for sz in 16 32 64 128 256 512; do
      sips -z $sz $sz "$TMP/sq.png" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null 2>&1
      sips -z $((sz*2)) $((sz*2)) "$TMP/sq.png" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1
    done
    if iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" >/dev/null 2>&1; then
      echo "  icon: built from MIST 1 (Cloud form)"
    fi
  fi
  rm -rf "$TMP"
fi
[ -f "$APP/Contents/Resources/AppIcon.icns" ] || echo "  icon: skipped (using default app icon)"

# Refresh Finder/Dock icon cache for this bundle.
touch "$APP"
echo "Done. Double-click ~/Desktop/Apps/MIST.app, or run mist-terminal/bin/mist directly."
