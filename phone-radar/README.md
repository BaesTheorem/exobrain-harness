# MIST Radar

Warmer/colder phone finder for macOS. Carry the laptop around and a big MIST
face tells you how close you are to your phone, judged by Bluetooth LE signal
strength (RSSI). Passive only: it listens to advertisements and never connects
to or pairs with anything.

## How it works

- `radar.py` runs a [bleak](https://github.com/hbldh/bleak) BLE scanner in a
  background thread and a [pywebview](https://pywebview.flowrl.com/) window on
  the main thread. The UI (`ui.html`) polls the scanner state twice a second
  over the pywebview JS bridge. No server, no port.
- bleak's CoreBluetooth backend scans with `options=None`, which lets macOS
  coalesce advertisements (RSSI only on first sight). `radar.py` patches the
  scan to pass `CBCentralManagerScanOptionAllowDuplicatesKey` so RSSI streams
  continuously, and restarts the scan every 10s as a fallback.
- RSSI is smoothed with a time-based EMA (tau 1.2s). Faces map to smoothed
  dBm bands from `(>‿<)` RIGHT HERE (≥ -45) down to `(>_<)` Cold (< -88),
  with `(;﹏;)` when the signal is lost.

## Finding an iPhone specifically

iPhones advertise BLE anonymously (no name, rotating random address every
~15 minutes), so you can't pick "Alex's iPhone" from a list by name. Two modes:

- **Lock mode**: hold the phone next to the Mac, the strongest row in the
  picker is the phone; tap it. If the phone rotates its address mid-session
  the app shows the lost face and suggests Auto mode.
- **Auto mode**: tracks the strongest Apple-manufacturer device in range
  (6 dB hysteresis so it doesn't flap). Survives address rotation; can be
  fooled by other nearby Apple devices, so prefer Lock mode when AirPods etc.
  are around.

Distance readout is a rough log-distance estimate from RSSI. Treat it as
vibes; the faces are the real instrument.

## Run

- App: `/Applications/MIST Radar.app` (shell launcher that execs
  `.venv/bin/python radar.py`). The bundle's Info.plist carries
  `NSBluetoothAlwaysUsageDescription`: macOS prompts for Bluetooth on first
  launch, and running from a bare terminal instead gets the process killed by
  TCC (SIGABRT) unless the terminal app has Bluetooth permission.
- Dev: `.venv/bin/python radar.py` from a terminal that has Bluetooth
  permission (System Settings → Privacy & Security → Bluetooth).

## Setup

```sh
python3 -m venv .venv
./.venv/bin/pip install bleak pywebview
```

Logs: `~/Library/Logs/exobrain/mist-radar.log`.
