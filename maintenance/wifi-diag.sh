#!/bin/bash
# Starbucks Wi-Fi captive-portal diagnostic.
# Run this WHILE connected to Starbucks Wi-Fi (no internet needed).
# It writes everything to wifi-diag-out.txt, then reconnect to hotspot and let MIST read it.

OUT="$(dirname "$0")/wifi-diag-out.txt"
exec > "$OUT" 2>&1

echo "===== Wi-Fi diag $(date) ====="

echo; echo "--- Associated network ---"
networksetup -getairportnetwork en0
/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I 2>/dev/null | grep -E ' SSID|state|channel|agrCtlRSSI'

echo; echo "--- IP / gateway (did we get a DHCP lease?) ---"
ifconfig en0 | grep -E 'inet |status'
echo "Default route:"; route -n get default 2>/dev/null | grep -E 'gateway|interface'

echo; echo "--- DNS servers in use ---"
scutil --dns | grep 'nameserver\[' | sort -u
echo "Manual DNS configured for Wi-Fi:"; networksetup -getdnsservers Wi-Fi

echo; echo "--- Private Wi-Fi Address (MAC randomization) ---"
ifconfig en0 | grep ether

echo; echo "--- Can we reach the gateway at all? (no internet required) ---"
GW=$(route -n get default 2>/dev/null | awk '/gateway/{print $2}')
echo "Gateway: $GW"; ping -c 3 -t 3 "$GW"

echo; echo "--- Apple captive check (THE key test) ---"
echo "[plain HTTP to captive.apple.com - portal should hijack this]"
curl -sL -m 10 -A "CaptiveNetworkSupport/1.0 wispr" -w "\n[HTTP %{http_code} | final: %{url_effective}]\n" http://captive.apple.com/hotspot-detect.html

echo; echo "--- Raw redirect headers (shows portal Location if any) ---"
curl -sI -m 10 http://captive.apple.com/hotspot-detect.html

echo; echo "--- DNS resolution test (does the portal hijack DNS?) ---"
nslookup captive.apple.com 2>&1 | grep -vi '^$'

echo; echo "===== done ====="
