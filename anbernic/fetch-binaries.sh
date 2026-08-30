#!/bin/sh
# Download the dufs static binaries this tool depends on (not committed to git).
# Populates vendor/ and copies the device binaries into card/APPS/wifipush/.
# The darwin build lands in vendor/ only, for local end-to-end testing.
set -eu

VER="v0.46.0"
BASE="https://github.com/sigoden/dufs/releases/download/$VER"
DIR="$(cd "$(dirname "$0")" && pwd)"
VENDOR="$DIR/vendor"
WP="$DIR/card/APPS/wifipush"
mkdir -p "$VENDOR" "$WP"

fetch() {
  name="dufs-$VER-$1"
  if [ ! -f "$VENDOR/$name/dufs" ]; then
    echo "fetching $name"
    curl -sL "$BASE/$name.tar.gz" -o "$VENDOR/$name.tar.gz"
    mkdir -p "$VENDOR/$name"
    tar -xzf "$VENDOR/$name.tar.gz" -C "$VENDOR/$name"
  fi
}

fetch aarch64-unknown-linux-musl
fetch armv7-unknown-linux-musleabihf
fetch aarch64-apple-darwin

cp "$VENDOR/dufs-$VER-aarch64-unknown-linux-musl/dufs" "$WP/dufs-arm64"
cp "$VENDOR/dufs-$VER-armv7-unknown-linux-musleabihf/dufs" "$WP/dufs-arm32"
chmod 755 "$WP/dufs-arm64" "$WP/dufs-arm32"
echo "card payload ready: $WP"
