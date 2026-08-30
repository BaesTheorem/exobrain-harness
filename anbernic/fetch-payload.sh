#!/bin/sh
# Download the community "Temporary SSH Server" stock-OS app into card/APPS/.
# Not committed (it's someone else's work); this pulls it on demand.
#
# Source: github.com/cbepx-me/Anbernic-H700-RG-xx-StockOS-Modification (by G.R.H).
# That app just runs `systemctl start ssh.service` on the stock OS, exposing
# SSH on port 22 (root/root) while it's on screen. push-rom drives the rest.
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/card/APPS/Temporary_SSH_Server"
BASE="https://raw.githubusercontent.com/cbepx-me/Anbernic-H700-RG-xx-StockOS-Modification/main/Temporary_SSH_Server"
mkdir -p "$APP/res"

curl -sfL "$BASE/Temporary_SSH_Server.sh" -o "$APP/Temporary_SSH_Server.sh"
for f in noconn-0 noconn-2 noconn-3 sshtmp-0 sshtmp-2 sshtmp-3; do
  curl -sfL "$BASE/res/$f.png" -o "$APP/res/$f.png"
done
chmod +x "$APP/Temporary_SSH_Server.sh"

echo "SSH app staged at: $APP"
echo "One-time install: copy the whole 'Temporary_SSH_Server' folder into the"
echo "OS card's  Roms/APPS/  folder (the OS card is the one that boots, TF1)."
