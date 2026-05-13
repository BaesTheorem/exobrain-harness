# Samsung TV — local control

Tizen-based Samsung TV control over the LAN (no SmartThings/cloud account).
Token-paired local WebSocket on port 8002.

## Setup

1. Find the TV's IP — turn it on, then `dns-sd -B _services._dns-sd._udp local`
   (Samsung TUxxxx Crystal UHD doesn't broadcast mDNS by default; SSDP/UPnP
   works too: probe `M-SEARCH * HTTP/1.1` to `239.255.255.250:1900`).
2. Add to `.env` at harness root:
   ```
   TV_HOST=192.168.0.160
   TV_MAC=70:B1:3D:BB:AB:D0
   ```
3. Install deps in **both** Pythons the harness uses:
   ```
   /opt/homebrew/bin/python3 -m pip install --break-system-packages samsungtvws wakeonlan websocket-client
   /usr/bin/python3 -m pip install --user samsungtvws wakeonlan websocket-client
   ```
4. Pair (TV must be **on**):
   ```
   ./tv pair
   ```
   An "Allow / Deny" prompt appears on the TV. Tap **Allow**. Token saves to
   `tv/token.json` (gitignored).

## Usage

```
./tv console                 # full-screen TUI dashboard (see below)
./tv status                  # power state + model
./tv on                      # Wake-on-LAN (requires Network Standby on TV)
./tv off                     # power off
./tv pause|play|mute
./tv vol up 3                # volume up x3
./tv app netflix|youtube|prime|plex|disney|hulu|max|spotify|apple
./tv key KEY_INFO            # raw remote key
./tv home|back|up|down|left|right|ok
```

## TUI Console (`./tv console`)

Full-screen control surface with live status, hotkeys, and a manual command line.

**Hotkeys:**

| Key | Action |
|---|---|
| `p` | Play / pause toggle |
| `m` | Mute |
| `↑` / `↓` | Volume up / down |
| `←` / `→` | Navigate left / right |
| `h` | Home |
| `b` | Back |
| `e` | Enter / OK |
| `1` – `9` | Launch app (Netflix=1, YouTube=2, Prime=3, Plex=4, Disney+=5, Hulu=6, HBO Max=7, AppleTV=8, Spotify=9) |
| `w` | Wake (WoL) |
| `o` | Power off — press **twice within 5s** to confirm (deep-sleep warning still applies) |
| `r` | Force refresh status |
| `k` | Focus the manual command input (then type `key KEY_X`, `app NAME`, `vol up 3`, etc.) |
| `q` | Quit |
| `?` | Show hotkey help |

The status panel auto-refreshes every 2 seconds with TV name, power state, model, resolution, IP, and ping latency. The recent-command log scrolls below.

**Dependencies:** `textual` (installed automatically if missing; if not, `pip install textual`).

## Wake-on-LAN setting

On this TV (UN70TU700DBXZA, 2020 Crystal UHD), the relevant setting is
**"IP Control"** under Network/General Settings. Enabling it covers both:
- Local API access while powered on
- Wake-on-LAN from standby

(Other Samsung year/model combos use names like "Wireless Network Standby",
"Wake on Mobile", or split control vs. WoL into separate toggles.)

Without IP Control / Network Standby, `./tv on` is a no-op when the TV is
fully off. Verified working — magic packet wakes the TV in ~3s.

## Files

- `tv` — CLI entrypoint
- `tv_control.py` — control module (importable from skills)
- `token.json` — auth token (gitignored; re-create with `./tv pair`)
- `state.json` — reserved for future use (gitignored)

## ⚠️ `./tv off` is one-way — physical remote required to wake

Sending power-off over the WSS API on this TV (UN70TU700DBXZA) puts it into
a deep-sleep state where ping fails, ports close, and Wake-on-LAN no longer
works. The physical remote's power button uses a different power path that
*does* leave the TV WoL-capable. This is a known Samsung TU-series firmware
quirk — same complaint across Home Assistant / openHAB forums, no public fix
short of using the SmartThings cloud API or an IR blaster.

`./tv off` now warns and 5-second-countdowns before sending. Use `--force` to
skip the prompt. If you do power-off via the CLI, you'll need the physical
remote to wake the TV again.

## Gotchas

- **Two Pythons.** Harness uses `/usr/bin/python3` (3.9) for launchd jobs and
  Homebrew `/opt/homebrew/bin/python3` (3.14) for shebang-based scripts.
  Deps must be installed in both.
- **REST vs WebSocket.** `http://TV:8001/api/v2/` is unauthenticated (used
  for status). Control (key send, app launch) goes over WSS on 8002 with
  token auth.
- **TV must be on to pair.** Pairing exchange happens over the live WS.
- **Pause/play are no-ops** when no media is playing — sending KEY_PAUSE on
  the home screen does nothing visible.
