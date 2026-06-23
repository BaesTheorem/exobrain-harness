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
  — fine for inspection, not guaranteed byte-perfect.
- **tx verbs vary by firmware.** `tx-subghz`/`tx-ir` are thin wrappers over
  `raw`. If a firmware names the verb differently, use `raw` and we'll adjust.

## Later: wireless

The command layer is transport-agnostic. To go wireless without a Claude Home
app, an ESP32 flashed with a UART-to-TCP bridge on the Flipper's GPIO UART can
expose this same CLI over the LAN; point pyserial at a `socket://host:port` URL.
Not wired up yet — USB first.
