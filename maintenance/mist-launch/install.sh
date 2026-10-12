#!/bin/bash
# Build mist-launch, sign it with the Team identity that signs MIST Console,
# and install it at a stable path outside ~/Documents (launchd and TCC must not
# depend on where the repo lives). Idempotent; re-run after a cert renewal.
#
#   maintenance/mist-launch/install.sh            # build + sign + install
#   maintenance/mist-launch/install.sh --check    # report the installed copy
#
# After the first install, grant it Full Disk Access once (System Settings >
# Privacy & Security > Full Disk Access > +, pick ~/.local/bin/mist-launch).
# maintenance/mist-launch/sweep.py refuses to rewrite plists until that grant
# is in place.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${MIST_LAUNCH_DEST:-$HOME/.local/bin/mist-launch}"
TEAM="$(codesign -dv "/Applications/MIST Console.app" 2>&1 | awk -F= '/^TeamIdentifier=/{print $2}')"
if [ "${1:-}" = "--check" ]; then
  [ -x "$DEST" ] || { echo "not installed: $DEST"; exit 1; }
  codesign -dv "$DEST" 2>&1 | grep -E "^(Identifier|TeamIdentifier)=" ; exit 0
fi
[ -n "$TEAM" ] || { echo "cannot read the Console app's TeamIdentifier" >&2; exit 1; }
# find-identity prints the developer's id in parentheses, not the team's, so
# sign with the first Apple identity and then check the binary's TeamIdentifier
# against the Console's: that is the property Login Items grouping needs.
IDENT="$(security find-identity -v -p codesigning | grep -E '"(Apple Development|Developer ID Application)' | head -1 | sed -E 's/.*"(.*)".*/\1/')"
[ -n "$IDENT" ] || { echo "no Apple code-signing identity in the keychain" >&2; exit 1; }
TMP="$(mktemp -d)"
clang -O2 -Wall -o "$TMP/mist-launch" "$HERE/mist-launch.c"
codesign -f -s "$IDENT" -i com.exobrain.mist-launch "$TMP/mist-launch"
GOT="$(codesign -dv "$TMP/mist-launch" 2>&1 | awk -F= '/^TeamIdentifier=/{print $2}')"
[ "$GOT" = "$TEAM" ] || { echo "signed with team $GOT, the Console is $TEAM; pick another identity" >&2; rm -rf "$TMP"; exit 1; }
mkdir -p "$(dirname "$DEST")"
# Replace atomically: a job starting mid-copy must see the old or the new file.
mv -f "$TMP/mist-launch" "$DEST"
rmdir "$TMP"
echo "installed $DEST"
codesign -dv "$DEST" 2>&1 | grep -E "^(Identifier|TeamIdentifier)="
