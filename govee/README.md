# govee

A CLI that controls Govee lights on the local network through the Govee LAN API (UDP). It uses the [govee-local-api](https://github.com/Galorhallen/govee-local-api) library, which is also the library of the Home Assistant integration.

## Setup

1. In the Govee app, open each light, open its settings, and turn on **LAN Control**.
2. Run `bin/govee scan`. The first run makes `.venv` and installs `requirements.txt`.
3. Give each bulb a name: `bin/govee name 3F:F4 desk`.

A bulb with LAN Control off (for example, the bulb that relays an H5125 remote, which needs LAN Control off) gives no LAN reply. Run `bin/govee sync-names` once so the cache has it. Then each command and status for that bulb goes over Bluetooth if its cache entry has a `ble` field, and through the Govee cloud API (`GOVEE_API_KEY` from the harness `.env`) if it does not have one, or if Bluetooth fails.

## Bluetooth

`govee_ble.py` controls an H6008 over Bluetooth LE. `bin/govee` uses it for a bulb that gives no LAN reply and has a `ble` field in `data/devices.json`. The field is the name that the bulb advertises: `GVH6008` and 4 hex digits. On `bedroom-3` and on the two units that govee-toolkit measured, the digits are the last two bytes of the Wi-Fi MAC with 1 added to the last byte. On `bedroom-2` they have no relation to the MAC. Thus, identify each bulb by the Wi-Fi MAC that it gives over Bluetooth:

1. Run `bin/ble-run scan 20 gvh` from the harness root, to get the names that are near.
2. For each name, run `bin/ble-run govee/govee_ble.py NAME mac`.
3. Find the MAC in the device ID of a `data/devices.json` entry (the last 6 bytes), then write the name in that entry's `ble` field.

The script runs in the harness `bin/ble-run` app bundle, because macOS stops bare Python that uses Bluetooth. Its interpreter (`flipper/.venv`) needs `bleak` and `cryptography`.

The protocol, the codec, and the frame layouts come from [govee-toolkit](https://github.com/damient/govee-toolkit) (MIT): `docs/protocol/ble.md` and `packages/rust/src/ble/encode.rs`. These bulbs set an encoding flag (bit 0x40 of the flags byte in their advertisement data), and then they ignore plaintext command and read frames. The name does not decide the flag, and a firmware update can set it. Each connection starts with a handshake under a fixed base seed. Then the bulb gives a session seed, and all frames after that are encoded under it. `tests/test_govee_ble.py` checks the port against wire captures from a physical H6008. Run it with `uv run --no-project --with pytest --with bleak --with cryptography pytest tests/test_govee_ble.py`, because the default test environment does not have those packages.

Limits:

- A bulb accepts one Bluetooth link. While a phone or a different controller holds that link, the bulb does not advertise, and `govee_ble.py` cannot find it. The Govee app on a phone is one such controller. On 2026-11-03, five scans from 00:05 to 00:15 did not find `bedroom-2`. Then it advertised for short periods (00:38 and 00:41). The script looks for 30 s and tries again if the link is taken before it connects.
- A brightness frame turned an off H6008 on (`bedroom-2`, 2026-11-03 00:43). Thus `govee_ble.py` does not send brightness, color, or temp to a bulb that reads off. Only `on` turns a bulb on.
- After a link closes, the bulb is silent for some seconds, sometimes for a minute or more, before it advertises again.
- A write gets no GATT acknowledgement. The bulb sends a status frame, but that status says only that the firmware accepted the frame, not that it applied it. The script holds the link open for 0.3 s after the last write, then reads the values back from the bulb.
- The cloud API answers success for a command that does not get to the bulb, and the values it reports can be out of date. Do not use a cloud answer as proof.

## Commands

```
govee scan                      discover bulbs and show status
govee status [TARGET]
govee on|off [TARGET]
govee brightness PCT [TARGET]
govee color COLOR [TARGET]      red, #ff8800, 255,136,0, or warm/cool/daylight
govee temp KELVIN [TARGET]
govee name DEVICE ALIAS
govee sync-names                copy the Govee app names into the aliases (needs GOVEE_API_KEY in the harness .env)
govee google-script [--room R] [TARGET]   print a Google Home script for the power-on rule (skips bulbs with no room)
govee --check <command>         read the status back after a set command
```

TARGET is `all` (the default), an alias, an alias group (`vanity` selects `vanity-1` to `vanity-4`), a floor (the `floor` field in `data/devices.json`, for example `floor-2`), an IP, or the last part of the device id. Use commas for more than one target.

## Limits

- The LAN API does not acknowledge a set command. Use `--check` to make sure that the command had an effect.
- The LAN API cannot start scenes on basic bulbs such as the H6008. You must use the cloud API for scenes.
- A bulb does not reply when the wall switch is in the OFF position.

## Music sync

`bin/govee-music` moves bulbs with the audio of one app, by default Pocket Bard on the dining room bulbs:

```
govee-music                              Pocket Bard -> dining-room, color follows the music
govee-music --mood red                   fixed color, brightness follows the sound
govee-music --mood warm --min 20 --max 70
govee-music --process Spotify --target bedroom
govee-music --dry-run -v                 analysis only, one line each second, no bulb changes
```

The audio comes from a Core Audio process tap through [AudioTee](https://github.com/makeusabrew/audiotee) (MIT), so only that app is captured and the speakers keep playing. Loudness sets the brightness, a bass hit adds a short flash, and the spectral centroid moves the color from purple and red (dark, low) through amber to green and cyan (bright, high). The color drifts in seconds, the brightness answers in a tenth of a second. The bulbs' settings are read at the start and put back at exit.

Setup:

1. Compile AudioTee: `git clone https://github.com/makeusabrew/audiotee.git ~/.local/src/audiotee && cd ~/.local/src/audiotee && swift build -c release`. Set `AUDIOTEE` to the binary's path if you put it elsewhere.
2. The first run asks macOS for System Audio Recording permission for the terminal or app that runs it. If the run reports no audio, permit it in System Settings > Privacy & Security > Screen & System Audio Recording.
3. The target app must be playing. `--system` taps all apps when the named process is not running.

The H6008 takes 20 commands each second on the LAN (tested), and the bulb fades between values, so the effect is a swell and breathe, not a strobe.

## Power-on color rule

`govee google-script` writes a script for the Google Home script editor (home.google.com > Automations > Add > script). After you paste and save the script, activate it. A saved script that is not active does nothing, and Google shows no error. Each bulb gets three automations. When the bulb turns on, Google sets its color and brightness for the time of day:

| Period | Color | Brightness |
| --- | --- | --- |
| 7:30 AM to 2 hours before sunset | 6500 K | 100% |
| The 2 hours before sunset | 2700 K | 100% |
| Sunset to 7:30 AM | red | 30% |

Bulbs in one group stay in the same state. A bulb's group is the `group` field in `data/devices.json`, or else its alias without the `-N` suffix. A group name is also a TARGET. When one bulb of a group turns on, the automation turns on the full group and sets its color. When one bulb turns off, the full group turns off.

A bulb with a `color` field in `data/devices.json` (hex RGB, for example `FFBF00` for the floor 2 amber) has that color at any time of day, at 100%. It has no period rules and the 7:30 AM wake does not include it.

A bulb that is already on when a period starts also changes. At 2 hours before sunset and at sunset, one automation for each group sets the new color and brightness if any bulb of the group is on.

At 7:30 AM, one more automation turns every bulb on at 6500 K and 100%, even if it is off. A bulb that is off at the wall switch has no power, so it cannot turn on.

6500 K is the coolest white the H6008 makes and gives the most alertness. 2700 K is its warmest white (the API advertises 2000 K, but the bulb clamps a lower value to 2700 K). Red light has almost no effect on melatonin. The rule runs in the Google cloud, so it does not need this computer.

Give a TARGET to limit the script to some bulbs: `govee google-script bedroom` writes the rules for the bedroom group only. The 7:30 AM wake then turns on only those bulbs.

Google names a device "<name> - <room>". Give the room with `--room`, or add a `room` field to a bulb in `data/devices.json`.

