#!/bin/bash
# Setup script for Pomodoro Timer app
# Creates a macOS .app bundle on the Desktop

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Pomodoro"
APP_PATH="$HOME/Desktop/${APP_NAME}.app"

echo "=== Pomodoro Timer Setup ==="

# 1. Install Python dependencies
echo "Installing dependencies..."
pip3 install --quiet pywebview pillow 2>/dev/null || pip install --quiet pywebview pillow

# 2. Generate app icon
echo "Generating app icon..."
python3 "$SCRIPT_DIR/create_icon.py"

# 3. Create .app bundle
echo "Creating app bundle..."
rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# Copy icon
if [ -f "$SCRIPT_DIR/AppIcon.icns" ]; then
    cp "$SCRIPT_DIR/AppIcon.icns" "$APP_PATH/Contents/Resources/AppIcon.icns"
fi

# Create Info.plist
cat > "$APP_PATH/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Pomodoro</string>
    <key>CFBundleDisplayName</key>
    <string>Pomodoro</string>
    <key>CFBundleIdentifier</key>
    <string>com.exobrain.pomodoro</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>launch</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

# Create launcher script
cat > "$APP_PATH/Contents/MacOS/launch" << LAUNCHER
#!/bin/bash
cd "$SCRIPT_DIR"
exec /usr/bin/env python3 "$SCRIPT_DIR/main.py"
LAUNCHER

chmod +x "$APP_PATH/Contents/MacOS/launch"

# 4. Create the Obsidian log note if it doesn't exist
LOG_FILE="$HOME/Documents/Exobrain/Pomodoro Log.md"
if [ ! -f "$LOG_FILE" ]; then
    echo "# Pomodoro Log" > "$LOG_FILE"
    echo "" >> "$LOG_FILE"
    echo "Created Obsidian note: Pomodoro Log.md"
fi

echo ""
echo "=== Setup Complete ==="
echo "App installed at: $APP_PATH"
echo "Pomodoro Log at:  $LOG_FILE"
echo ""
echo "Double-click Pomodoro.app on your Desktop to start!"
