#!/bin/bash
# build-app.sh -- build a native .app wrapper around a local web app.
#
#   ./build-app.sh "The Priory" priory http://127.0.0.1:5025/ com.exobrain.priory-web \
#       [--plist PATH] [--log PATH] [--icon PATH.icns] [--bundle-id ID] [--health URL]
#
# Creates /Applications/<Name>.app whose executable is a copy of the brew
# python interpreter (own TCC identity + correct menu-bar name), running the
# shared shell.py from the bundle's Resources with deps from a shared venv at
# ~/.local/share/mist-appshell (created on first run). Idempotent.
set -euo pipefail

NAME="$1"; SLUG="$2"; URL="$3"; LABEL="${4:-}"; shift 4 || true
PLIST="" LOG="" ICON="" BUNDLE_ID="" HEALTH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --plist) PLIST="$2"; shift 2;;
    --log) LOG="$2"; shift 2;;
    --icon) ICON="$2"; shift 2;;
    --bundle-id) BUNDLE_ID="$2"; shift 2;;
    --health) HEALTH="$2"; shift 2;;
    *) echo "unknown arg $1" >&2; exit 2;;
  esac
done
BUNDLE_ID="${BUNDLE_ID:-com.exobrain.$SLUG}"

SHELL_HOME="$HOME/.local/share/mist-appshell"
PYBASE="/opt/homebrew/opt/python@3.12/bin/python3.12"
if [ ! -x "$SHELL_HOME/.venv/bin/python" ]; then
  uv venv --python "$PYBASE" "$SHELL_HOME/.venv"
fi
uv pip install --quiet --python "$SHELL_HOME/.venv/bin/python" \
  pywebview pyobjc-framework-Cocoa pyobjc-framework-WebKit setproctitle
SITE=$("$SHELL_HOME/.venv/bin/python" -c "import site; print(site.getsitepackages()[0])")

APP="/Applications/$NAME.app"
MACOS="$APP/Contents/MacOS"; RES="$APP/Contents/Resources"
rm -rf "$APP"
mkdir -p "$MACOS" "$RES"

# Interpreter copy: resolves symlinks so framework links stay absolute.
cp -L "$PYBASE" "$MACOS/$SLUG-python"
HERE="$(cd "$(dirname "$0")" && pwd)"
cp "$HERE/shell.py" "$RES/shell.py"
[ -n "$ICON" ] && cp "$ICON" "$RES/AppIcon.icns"

cat > "$MACOS/launch" <<LAUNCH
#!/bin/zsh
HERE="\${0:A:h}"
export APPSHELL_TITLE="$NAME"
export APPSHELL_URL="$URL"
${HEALTH:+export APPSHELL_HEALTH="$HEALTH"}
${LABEL:+export APPSHELL_LABEL="$LABEL"}
${PLIST:+export APPSHELL_PLIST="$PLIST"}
${LOG:+export APPSHELL_LOG="$LOG"}
export APPSHELL_ICON="\$HERE/../Resources/AppIcon.icns"
export PYTHONPATH="$SITE"
export PYTHONNOUSERSITE=1
exec "\$HERE/$SLUG-python" "\$HERE/../Resources/shell.py" >> "\$HOME/Library/Logs/exobrain/appshell-$SLUG.log" 2>&1
LAUNCH
chmod +x "$MACOS/launch"

cat > "$APP/Contents/Info.plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST_EOF

codesign -s - --force --deep "$APP" 2>/dev/null || true
echo "built: $APP"
