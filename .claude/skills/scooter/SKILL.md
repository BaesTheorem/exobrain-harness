---
name: scooter
description: "Talk to Alex's NIU KQi Air electric scooter from the Mac over Bluetooth LE with the niu-kqi CLI -- battery, speed, ride settings, lock/unlock, power, cruise, regen level, and any raw field. Use when Alex mentions the scooter, the KQi, KQi Air, NIU, 'lock the scooter', 'how's the scooter's battery', 'scooter settings', 'scooter firmware', or wants anything read from or changed on the scooter. Also the reference for the NIU BLE protocol."
metadata:
  hardware: "NIU KQi Air (bought 2026-08-24), NIU app on Alex's iPhone"
  repo: "/Users/alexhedtke/Documents/niu-kqi (public: BaesTheorem/niu-kqi)"
---

# /scooter

`~/Documents/niu-kqi` is a command-line client for the KQi Air. It replaces the NIU phone
app for status, settings, and commands. Everything in it was recovered from the NIU
Android app (5.12.2) by decompiling it; NIU publishes nothing. Read the repo README before
deep work: it has the protocol on one screen and the list of known unknowns.

Always run it through the launcher, never the .py directly:

```
~/Documents/niu-kqi/bin/kqi <command>
```

The launcher runs the CLI inside `/Applications/NIU KQi.app` because macOS kills bare
Bluetooth processes (TCC, exit 134, no message). If a command dies with 134, the bundle is
stale: rerun with `--rebuild` once, and if it still dies, `tccutil reset Bluetooth
com.exobrain.niu-kqi` and let it prompt again.

## Preconditions (check these before blaming the code)

1. **Credentials.** `kqi status` needs `secrets/scooter.json`. It is already set up and
   the login token is long-lived, so normally just run commands. To rebuild it:
   `kqi login <account>` (needs Alex's NIU password; prompt in a terminal or
   `--password-stdin`, never chat), then `kqi setup --mac auto` with the scooter on.
   The KQi Air is a kick scooter and is NOT bound to the cloud account; its password comes
   from `v5/device/bluetooth_secret` by MAC, which any logged-in account can fetch.
   `kqi mac` prints the real MAC (macOS hides it from scans; the tool connects briefly and
   reads it from `system_profiler`). Its BLE name is "NIU Link D840", MAC ends in D8:40.
2. **The scooter is on and within range.** It does not advertise when off. `kqi find` shows
   what matched and remembers the CoreBluetooth address; `kqi scan` lists everything nearby
   when `find` sees nothing; `kqi probe` dumps its GATT with no credentials.
3. **First contact may need the button.** If the connection drops right after connecting,
   the app's own wording is "Need 3 Press key": press the scooter's power button three
   times, then retry.

## What to run

- `kqi status` (add `--json` for machine output, `-v` to see every frame). Reads battery,
  speed, ride mode, setting bits, serials, firmware in seven small groups; a failing group
  is retried one field at a time.
- `kqi read <field> ...` and `kqi write <field> <value>` for anything in `kqi fields`
  (44 kick-scooter fields, `--all` adds the 255 shared NIU fields). Values are the raw
  unit: speeds are km/h x 10, timestamps are unix seconds.
- Named commands, straight from the app: `lock`/`unlock`, `on`/`off` (dashboard power),
  `cruise on|off`, `kickstart on|off`, `fastlock on|off`, `alarm on|off`, `ebs 0..3`
  (regen braking), `custom on --max 20`/`custom off`, `daylight on|off|led`, `unit 0|1`,
  `clock`. `cmd N` and `cmd --db N` send raw `foc_k_cmd`/`db_k_cmd` numbers.
- `kqi monitor --seconds 120` prints what the scooter pushes on its own (ride it, press
  buttons). `kqi raw <hex>` sends one frame.
- Writes and `cmd` ask for confirmation; pass `-y` only when Alex already said do it.

## Judgment rules

- **Do not invent command numbers.** The known ones are in `COMMANDS` in `kqi_ble.py` and
  in the README; anything else goes through `cmd` as an explicit experiment Alex asked
  for, one number at a time, with the scooter stationary. Never send `factory-reset`
  unless he says those words.
- **Tested and working** end to end against the real KQi Air (2026-09-06): the BLE-20
  password handshake, status reads, and settings writes (`kqi clock` was the first write).
  Max speed reads 320 = 32.0 km/h (its 20 mph cap), speeds are km/h times ten, `bms_soc_rt`
  is battery percent. Bits still marked `(?)` in `BITS` need a toggle to confirm; when a
  live reading contradicts a label, fix it in the repo (generator, not output) and commit.
- **Headlight:** no on/off command exists in the app; say so instead of guessing. The
  physical button (double tap) does it.
- **Frame family** is picked from the service UUID (BLE 10/20 = 20-byte AES frames,
  BLE 21 = `5aa5`). The app's kick-scooter code always uses family 1 for `foc_k_*`/
  `db_k_*`; `--family` overrides if a scooter ignores one.
- Long scans or monitors from the Console go through `mist-progress run`.
- Commits to the repo read as Alex's work: run `/de-ai` on messages, no attribution.

## Where things live

- Repo: `~/Documents/niu-kqi` (`kqi_ble.py` CLI + bleak session, `niu_proto.py` frames and
  crypto with a self-test, `niu_cloud.py` login/list/bleinfo, `data/fields.json` table).
- Credentials: `~/Documents/niu-kqi/secrets/` (gitignored; README there explains rebuild).
- App bundle: `/Applications/NIU KQi.app` (id `com.exobrain.niu-kqi`).
- Memory: `project_kqi_scooter_cli` in the MIST memory store has the live-test status.
