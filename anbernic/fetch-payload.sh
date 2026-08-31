#!/bin/sh
# Download the community stock-OS apps this tool rides on (not committed):
#   Temporary SSH Server   - primary lane (push-rom drives sshd)
#   Temporary SAMBA Server - backup lane (Finder smb:// if SSH misbehaves)
# Source: github.com/cbepx-me/Anbernic-H700-RG-xx-StockOS-Modification (by G.R.H).
#
# Install FLAT, matching how these apps ship on the card (each app's .sh sits
# at APPS root; res/ and Imgs/ are shared folders that get merged):
#   <app>.sh             -> OS card  Roms/APPS/
#   <app>/res/*.png      -> merged into  Roms/APPS/res/
#   <app>/Imgs/<app>.png -> Roms/APPS/Imgs/   (the menu icon)
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="https://raw.githubusercontent.com/cbepx-me/Anbernic-H700-RG-xx-StockOS-Modification/main"

fetch_app() {
  name="$1"; shift
  app="$DIR/card/APPS/$name"
  mkdir -p "$app/res" "$app/Imgs"
  curl -sfL "$REPO/$name/$name.sh" -o "$app/$name.sh"
  curl -sfL "$REPO/$name/Imgs/$name.png" -o "$app/Imgs/$name.png"
  for f in "$@"; do
    curl -sfL "$REPO/$name/res/$f.png" -o "$app/res/$f.png"
  done
  chmod +x "$app/$name.sh"
  echo "staged: $name"
}

fetch_app Temporary_SSH_Server noconn-0 noconn-2 noconn-3 sshtmp-0 sshtmp-2 sshtmp-3
fetch_app Temporary_SAMBA_Server noconn-0 noconn-2 noconn-3 sambatmp-0 sambatmp-2 sambatmp-3
echo "Staged under card/APPS/. Install flat into the OS card's Roms/APPS/ (see header)."
