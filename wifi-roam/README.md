# WiFi Roam

Keeps this Mac on the best-**throughput** known wifi instead of clinging to
whatever it first joined (the classic "stuck on the phone hotspot" problem).

macOS only consults the preferred-networks list at *join* time, so once it
latches onto a network it stays there even when a better known wifi is in range.
This is a small resident watcher that scans on a timer, ranks every *known*
network by expected throughput, and switches to the best one.

## Why it needs an app bundle

Network **names** on macOS 14.4+ are gated behind Location Services -- a process
without that permission sees every SSID as `<redacted>`. Location grants are keyed
to a bundle identity, so the watcher runs inside `WiFiRoam.app` purely to hold the
grant. You approve it once; launchd runs it forever after.

## How throughput is judged

You can't measure the speed of a network you're not connected to, so it's layered:

1. **Measured** -- a small capped speed probe of the *current* link (Cloudflare,
   ~4 MB, time-boxed). This is what catches a hotspot with strong signal but slow
   cellular backhaul. Skipped on `metered_ssids` so it never burns hotspot data.
2. **Learned** -- every probe is stored per-SSID (EWMA) in `state.json` and reused
   to rank that network later without re-probing.
3. **Estimated** -- for a known network never measured, capacity is estimated from
   the scan (band, channel width, signal). Cold-start only; learning overrides it.

Signal (RSSI) is only a **gate** (`min_join_rssi`, must be joinable) and a
tiebreaker. It no longer drives the choice.

Switching uses `networksetup -setairportnetwork`, which reuses the saved keychain
profile (no passwords handled here). If that fails it disassociates and lets macOS
auto-join.

## Setup

```bash
/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv .venv
.venv/bin/pip install pyobjc-framework-CoreWLAN pyobjc-framework-CoreLocation
./setup.sh
# edit the RUNTIME config (setup.sh seeds it from config.example.json):
#   ~/Library/Application Support/WiFiRoam/config.json  -> set metered_ssids
# (the daemon reads only that copy; a repo-local config.json is ignored)
open ~/Library/Application\ Support/WiFiRoam/WiFiRoam.app  # click Allow on the Location prompt
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alexhedtke.wifiroam.plist
```

Reload after editing `roam.py`:
`launchctl kickstart -k gui/$(id -u)/com.alexhedtke.wifiroam`

## Manual use / debugging

Run these via the **bundle** binary so SSIDs resolve (the bare interpreter is blind):

```bash
WiFiRoam.app/Contents/MacOS/wifiroam --scan          # known nets + signal + est/learned Mbps
WiFiRoam.app/Contents/MacOS/wifiroam --probe         # measure the current link
WiFiRoam.app/Contents/MacOS/wifiroam --once --dry-run # decide, print, don't switch
```

## config.json (gitignored -- holds your network names)

| key | meaning |
|---|---|
| `min_join_rssi` | dBm floor; weaker known nets are ignored |
| `throughput_margin_frac` / `_floor_mbps` | hysteresis -- how much better an alternative must be to switch |
| `probe_*` | speed-probe size / timeout / how often to re-probe a link |
| `metered_ssids` | your hotspot name(s): never probed, assumed slow |
| `assumed_metered_mbps` | the throughput a metered net is assumed to have |

`config.json`, `state.json`, `*.log`, `.venv/`, and `WiFiRoam.app/` are gitignored:
they contain your real SSIDs / build artifacts. The repo is public; keep names out.
