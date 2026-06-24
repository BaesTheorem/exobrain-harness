---
name: flipper
description: "Drive Alex's Flipper Zero from the command line — read/write files on the device, analyze captures, transmit signals, and inspect device state, over USB or wirelessly over Bluetooth LE. Use when Alex mentions the Flipper, Flipper Zero, sub-GHz / 433 MHz, NFC/RFID, infrared/IR, BadUSB, a .sub/.ir/.nfc capture, the dolphin (mood/animations), flashing firmware, or wants to read/write/control the device."
metadata:
  hardware: "Flipper Zero 'Obabry', target f7, Unleashed firmware (unlshd-089e), region-unlocked"
  tools_dir: "/Users/alexhedtke/Documents/Exobrain harness/flipper"
---

# /flipper

Control Alex's **Flipper Zero** from this CLI. The toolkit is a set of small,
dependency-light Python scripts in `flipper/` (in this harness). Read this before
touching the device so we don't re-tread the gotchas already solved.

## Device state (current)

- **Model:** Flipper Zero, name `Obabry`, hardware target **f7**.
- **Firmware:** **Unleashed `unlshd-089e`** (custom). Flashed from Official 1.4.3
  via qFlipper "Install from file."
- **Region:** UNLOCKED (`hardware_region: 0`). **433.92 MHz TX works** — the US
  region gate is gone. (Use responsibly; Alex is legally responsible for TX.)
- **Dolphin mood disabled** — see the Dolphin section below.

## The toolkit (`flipper/`)

| Script | Transport | Use for |
|--------|-----------|---------|
| `flipper.py` | **USB serial** (text CLI) | The reliable workhorse. Bulk/large files, anything where the cable's handy. |
| `flipper_ble.py` | **Bluetooth LE** (protobuf RPC) | Wireless, no cable. Small files, listings, info, writes, tx triggers. |
| `analyze-sub.py` | (offline) | Characterize a `.sub` RAW capture before transmitting it. |

### USB — `flipper.py`
```bash
python3 flipper/flipper.py info                              # device_info
python3 flipper/flipper.py list /ext/subghz
python3 flipper/flipper.py read /ext/subghz/foo.sub > foo.sub
python3 flipper/flipper.py write ./foo.sub /ext/subghz/foo.sub
python3 flipper/flipper.py delete /ext/foo.sub
python3 flipper/flipper.py tx-subghz /ext/subghz/foo.sub 10  # transmit (see TX safety)
python3 flipper/flipper.py raw "subghz"                      # any CLI command verbatim
```
Auto-detects the `/dev/cu.usbmodemflip_*` port. Needs `pyserial`. Quit qFlipper /
the mobile app first (they hold the port).

### Wireless — `flipper_ble.py`
```bash
python3 flipper/flipper_ble.py info | battery | power | ping
python3 flipper/flipper_ble.py list /ext/subghz
python3 flipper/flipper_ble.py read /ext/subghz/foo.sub > foo.sub
python3 flipper/flipper_ble.py write ./foo.sub /ext/subghz/foo.sub
python3 flipper/flipper_ble.py delete /ext/foo.sub
# --- full wireless remote control (drive ANY app/function) ---
python3 flipper/flipper_ble.py app "Sub-GHz"                 # launch an app by name (see catalog below)
python3 flipper/flipper_ble.py app "NFC" /ext/nfc/card.nfc   # ...optionally opening a file
python3 flipper/flipper_ble.py app "Sub-GHz" --force         # exit any running app first, then launch
python3 flipper/flipper_ble.py app-file /ext/nfc/card.nfc    # hand a file to the already-running app
python3 flipper/flipper_ble.py app-exit                      # exit (only if RPC-owned; else use `keys back`)
python3 flipper/flipper_ble.py input down                    # tap one button: up/down/left/right/ok/back
python3 flipper/flipper_ble.py input ok --repeat 2           # repeat a tap; `input ok long` = long-press
python3 flipper/flipper_ble.py keys down down ok             # button SEQUENCE in one session (':long' suffix)
python3 flipper/flipper_ble.py screen                        # ASCII dump of the 128x64 screen (text, not vision)
python3 flipper/flipper_ble.py screen -o shot.png            # ...and save a scaled PNG too
python3 flipper/flipper_ble.py stream -n 8 -d ./caps         # capture N frames while an app runs
# --- system + storage functions ---
python3 flipper/flipper_ble.py alert                         # beep+vibrate+flash (find-my-flipper)
python3 flipper/flipper_ble.py reboot [os|dfu|update]        # reboot into a mode (link drops)
python3 flipper/flipper_ble.py clock | clock --set now       # read / set the device clock
python3 flipper/flipper_ble.py df [path]                     # SD free/used space
python3 flipper/flipper_ble.py stat PATH | md5 PATH          # file type/size | md5sum
python3 flipper/flipper_ble.py mkdir PATH | rename OLD NEW    # storage ops
```
Needs `bleak` and the Flipper's **Bluetooth ON** (Settings → Bluetooth → ON).
The BLE channel speaks **protobuf RPC only** (not the text CLI), so this is a
hand-rolled, dependency-free RPC client (wire codec built from the official
`flipperzero-protobuf` field numbers). First connect may prompt a pairing PIN on
the Flipper; device address is cached to `flipper/.ble_addr` for fast reconnect.

### Wireless remote: the model for driving ANY app/function

The BLE link has **no text CLI** and the RPC exposes **no per-feature methods**
(no `subghz`, no `nfc`, etc. — verified against the full `flipperzero-protobuf`).
So you don't call a function directly; you **drive the Flipper's own UI** the way
a person would, and read results from **files**, not the screen. Three primitives
generalize to everything:

- **`app <name> [file]`** — open any app (and optionally a saved file). Names are
  exact, space- and case-sensitive. Confirmed catalog: `"Sub-GHz"`, `"NFC"`,
  `"125 kHz RFID"`, `"Infrared"`, `"iButton"`, `"GPIO"`, `"U2F"`, `"Bad USB"`,
  `"Settings"`, `"Apps"` (external `.fap` launcher). External plugins: `app "Apps"`
  then navigate, or `app-file <path.fap>`.
- **`keys ...` / `input`** — navigate that app's menus and trigger its functions
  (Read, Save, Emulate, Send, etc.). `keys` sends a whole sequence in one session.
- **`screen` / `stream`** — read UI state back **as text** (framebuffer → ASCII).
  Only a navigation aid; never needed for results.

**Results come back as files.** Whatever the app captures (a `.sub`, `.nfc`,
`.ir`, `.rfid`, `.txt` log) is saved to `/ext/<app>/...` and pulled with `read`
as plain text — no image vision, ever. Example, sub-GHz raw read: `app "Sub-GHz"`
→ `input ok` (Read, auto-listens 433.92 MHz OOK650) → on a hit, save via buttons
→ `read /ext/subghz/<name>.sub` → `analyze-sub.py`.

**Gotchas:**
- **One app at a time.** `AppStart` returns RPC `status=17` if an app is already
  running. Use `app ... --force` (exits first) or `keys back` to back out.
- **`app-exit` only works for RPC-owned apps** (`status=21` otherwise) — once
  you're in an app's own menus, `keys back` is the reliable exit.
- **Single BLE session** — exit cleanly (`keys back`) when done so radios aren't
  held and the device is usable by hand again.
- TX safety in the dedicated section below still applies — never transmit unknowns.

### Analyze a capture — `analyze-sub.py`
```bash
python3 flipper/analyze-sub.py some.sub
```
Reports frequency/modulation, timing levels, frame structure, and a verdict:
**fixed-code repeating remote (cloneable)** vs **rolling code / noise / junk**.
Run this before ever transmitting an unknown capture.

### Speed up the on-board universal remote — `optimize-universal-ir.py`

The Infrared **Universal Remotes** (TV-B-Gone et al.) read one asset file —
`/ext/infrared/assets/tv.ir` (also `ac.ir`, `audio.ir`, ...) — and transmit every
signal matching the pressed button (all `Power` codes) **sequentially**, top to
bottom; you abort when the device reacts. So the wait = the position of your
device's code in the list. Stock `tv.ir` is ~300 Power codes in no useful order,
so it crawls. The optimizer **dedups** and **reorders by brand popularity**:
```bash
python3 flipper/optimize-universal-ir.py tv.ir.orig -o tv.ir                    # popularity order (default)
python3 flipper/optimize-universal-ir.py tv.ir.orig -o tv.ir --order interleave # round-robin brands (best worst-case)
python3 flipper/optimize-universal-ir.py tv.ir.orig -o tv.ir --order family     # all of one brand together
python3 flipper/optimize-universal-ir.py tv.ir.orig -o tv.ir --top 40           # also trim Power to top 40
```
Default `--order popularity` ranks codes by **current TV market share** so the
most-likely-to-work codes fire first (minimises expected time on a random TV):
TCL/Onn → Samsung → Hisense → LG/Vizio → Sony → ... Brands are identified by
matching each code's `(protocol, address)` against power-code fingerprints pulled
from the **Flipper-IRDB** (`TVs/<brand>/`); the rank order tracks 2025 unit-share
data (TrendForce/Omdia). `interleave` round-robins families so *any* TV dies in
the first ~8 codes (better if you point at a wide brand mix); `family` groups one
brand together. Coverage is preserved unless `--top` is given.

Caveats worth knowing: ~half of stock `tv.ir`'s Power codes are **RAW** (timing
captures with no protocol/address) so they can't be brand-attributed and sort
last; `NEC 04` is shared by LG/Vizio/Hisense. The signature ranks live in
`SIGNATURE_RANK` in the script — refresh them when market share shifts.

**Workflow (all over BLE):**
1. `read /ext/infrared/assets/tv.ir > flipper/sd-backup/tv.ir.orig` (back up first; `sd-backup/` is gitignored).
2. `optimize-universal-ir.py tv.ir.orig -o tv_new.ir`.
3. **Verified write-back:** `md5` the local file, `write` it to the device, `md5`
   the device copy, compare; restore `tv.ir.orig` on mismatch. (A corrupt asset
   breaks the universal remote, so always verify — large writes are chunk-streamed
   but verify anyway.)

**Reapply after any firmware update / asset reinstall** — those regenerate the
stock assets and revert the order, same as the dolphin manifest. The original is
backed up at `flipper/sd-backup/tv.ir.orig`.

## USB vs BLE — which to reach for

- **BLE** for everyday wireless: info, battery, listings, reading/writing small
  files, triggering an action. No cable.
- **USB** when you need reliability or bulk: pulling a large capture, or when BLE
  is being flaky. Large file *reads* over BLE can drop mid-transfer (known
  firmware bug) — fall back to USB for those.

## Gotchas (all already handled in the tools — don't re-debug)

- **USB CDC re-enumerates** when the port closes, so back-to-back invocations
  hit a ~1s settle and an occasional "Resource busy"/"Device not configured."
  `flipper.py` retries the open; just space rapid calls or re-run.
- **`storage write` APPENDS**, it does not truncate. `flipper.py write` deletes
  the target first to get true overwrite. (BLE write uses the RPC and overwrites
  cleanly.) If you ever see a doubled file, this is why.
- **BLE discovery is flaky** — single scans miss the device. The cached
  `.ble_addr` avoids scanning; if it's stale, delete it to force a re-scan.
- **Single session:** while either tool holds a connection, the Flipper shows a
  CLI/RPC screen and can't be used by hand. Tools release on exit.
- **TX verb:** `subghz tx_from_file <file> <repeat> <device>` where device
  `0 = internal radio`. `tx-subghz` wraps this. IR/tx verbs vary by firmware —
  fall back to `raw` and adjust if needed.

## TX (transmit) safety — IMPORTANT

Transmitting is an **outward-facing action with real-world effect**. Rules:
1. **Never transmit an unknown capture.** Run `analyze-sub.py` first.
2. **Confirm with Alex** before sending anything that could actuate a device.
3. Rolling-code captures (KeeLoq, most car/garage remotes) can't be usefully
   replayed; only fixed-code (PT2262/EV1527/Princeton, e.g. cheap 433 outlet
   plugs) replay reliably.

## Privacy (CRITICAL)

Captured signals are **personal data** and must never be committed:
- `flipper/sd-backup/`, `*.sub`, `*.ir`, `*.nfc`, `*.rfid`, and `.ble_addr` are
  gitignored (`flipper/.gitignore`). Keep it that way. The tool *code* is public;
  the *captures* are not.

## Firmware (Unleashed)

- Flash/update via **qFlipper → gear → Install from file** with the
  `flipper-z-f7-update-unlshd-<ver>.tgz` (the `e` "extra apps" variant) from the
  [Unleashed releases](https://github.com/DarkFlippers/unleashed-firmware/releases).
- Recovery: hold **LEFT+BACK ~5s** to reboot; qFlipper shows a **Repair** button
  over DFU if firmware is broken. Bootloader is in ROM — very hard to brick.
- The CLI tool works on any firmware (CLI is upstream); custom firmware is only
  for the radio region unlock.

## Dolphin (mood/Tamagotchi) — disabled

Alex finds the sad-dolphin mood decay stressful. It's **disabled** by editing
`/ext/dolphin/manifest.txt`: the 5 neglect-triggered animations (`L1_Cry`,
`L1_Sad_song`, `L1_Mad_fist`, `L1_Boxing`, `L1_Leaving_sad`) are set to
**`Weight: 0`** (never selected), and the content animations are widened to
`Max butthurt: 99` so a happy one is always eligible at any mood. The internal
mood counter still ticks but nothing sad ever displays.

- Backup of the stock manifest: `flipper/sd-backup/dolphin-manifest.txt.bak`.
- **Reapply after any firmware update / asset-pack reinstall** — those can
  regenerate the default manifest and bring the sad animations back. Regenerate
  by re-running the Weight:0 + widen transform on a fresh manifest, write it back
  (the tool deletes-first), and reboot the Flipper (`raw "power reboot"`).

## Home-automation direction (not built yet)

The intended payoff: cheap **fixed-code 433 MHz outlet plugs** captured and
replayed to make dumb appliances scriptable from this CLI. Triage any captured
remote with `analyze-sub.py` (confirm fixed-code) before relying on replay.
