# flipper

A small command-line tool to drive a Flipper Zero from this harness over its
USB serial CLI. Lets MIST read files off the device, write files to it, and
trigger transmits, all from Bash. No Flask app, no protobuf, no Flipper SDK,
just `pyserial` against the device's built-in command prompt.

## Requirements

- Flipper Zero connected via USB-C, unlocked.
- No other program holding the port (quit qFlipper / the mobile app first).
- `pyserial` (`python3 -m pip install --break-system-packages pyserial`).
- Works on stock or any custom firmware (Unleashed/Momentum/RogueMaster); the
  CLI is upstream. Custom firmware is only needed for the 433 TX region unlock,
  not for this tool.

## Usage

```bash
python3 flipper.py info                                  # device_info
python3 flipper.py list /ext                             # browse the SD card
python3 flipper.py list /ext/subghz
python3 flipper.py read /ext/subghz/foo.sub             # read a capture
python3 flipper.py write ./local.sub /ext/subghz/foo.sub  # push a file back
python3 flipper.py delete /ext/subghz/foo.sub
python3 flipper.py tx-subghz /ext/subghz/foo.sub 10      # transmit a .sub
python3 flipper.py raw "storage list /ext/nfc"           # any CLI command
```

`--port` overrides auto-detection (auto-detect looks for `/dev/cu.usbmodemflip_*`).

## What "all its data, both directions" means here

Everything the Flipper captures lives as files on the SD card under `/ext`
(`.sub`, `.ir`, `.nfc`, `.rfid`, BadUSB `.txt`, logs). So:

- **Read everything** = `list` to enumerate, `read` to pull each file.
- **Write back** = `write` a `.sub` to transmit, drop an IR library, update a
  BadUSB script.
- **Act** = `tx-subghz`, `tx-ir`, or `raw` to trigger on-device functions.

## Known limits

- **Single session.** While this tool is connected the Flipper shows a CLI
  session and can't be hand-used at the same time. It releases on exit.
- **Text vs binary.** Reads are clean for text-y files (`.sub`, `.ir`, BadUSB
  `.txt`, logs). Binary dumps (`.nfc`/`.rfid`) come back as the CLI renders them
 -- fine for inspection, not guaranteed byte-perfect.
- **tx verbs vary by firmware.** `tx-subghz`/`tx-ir` are thin wrappers over
  `raw`. If a firmware names the verb differently, use `raw` and we'll adjust.

## Wireless (Bluetooth LE) -- `flipper_ble.py`

`flipper_ble.py` drives the Flipper **wirelessly over Bluetooth**, no cable.

```bash
python3 flipper_ble.py info                          # device_info over BLE
python3 flipper_ble.py battery                        # battery %
python3 flipper_ble.py list /ext/subghz
python3 flipper_ble.py read /ext/subghz/foo.sub > foo.sub
python3 flipper_ble.py write ./foo.sub /ext/subghz/foo.sub
python3 flipper_ble.py delete /ext/foo.sub
python3 flipper_ble.py ping                           # confirm RPC link
```

Requires `bleak` (`pip install --break-system-packages bleak`) and the
Flipper's Bluetooth ON (Settings → Bluetooth → ON).

### How it works (and why it's not just the USB tool)

The Flipper's BLE serial channel does **not** expose the text CLI -- over
Bluetooth it speaks the **protobuf RPC** only. So `flipper_ble.py` is a
from-scratch, dependency-free RPC client: hand-rolled protobuf wire
encode/decode (no `protoc`, no protobuf runtime) over the BLE GATT serial
service via `bleak`. Field numbers come from the official `.proto` definitions
(flipperdevices/flipperzero-protobuf).

- First run scans for "Flipper <name>"; the device address is cached to
  `.ble_addr` (gitignored) so later runs connect directly -- faster and far more
  reliable than re-scanning each time.
- First connection may prompt a pairing PIN on the Flipper screen; confirm it
  there.

### Known limits

- **Large file reads can be flaky** over BLE (known firmware transfer bug). Small
  files, listings, info, and writes are solid. For bulk SD pulls, use USB.
- Single session and BLE range (~10 m) caveats from the USB tool still apply.
