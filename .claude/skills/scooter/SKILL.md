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
   reads it from `system_profiler`). Its BLE name is `NIU Link <device-name>`; the MAC is in the gitignored `secrets/scooter.json`, never in this skill.
2. **The scooter is on or in standby, and within range.** With the dashboard off it keeps
   advertising for a while; after a long idle it sleeps and needs a power-button press. `kqi find` shows
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

## Not charging

The charger LED is red while current flows and green at full. A green LED on a pack the
dashboard shows as low means the pack refused the current. Read before guessing:

```
kqi read db_k_f_code bms_bat_sta_rt bms_c_cur_rt bms_soc_rt
kqi poll --seconds 75 bms_bat_sta_rt bms_c_cur_rt bms_soc_rt   # Alex plugs/unplugs during it
```

- `db_k_f_code` prints the manual's meaning (34 = cold lockout, charging is allowed 0-45 C;
  31-42 are battery codes, most say "dealer"). 0 = nothing raised, which was the case 2026-11-09.
- Seen live 2026-11-09: `bms_soc_rt` 100 with a low dashboard, `bms_bat_sta_rt` 0x8001,
  `bms_c_cur_rt` 0. A few power cycles fixed it; afterwards `bms_soc_rt` 91 and `bms_bat_sta_rt` 1.
  So first ask Alex to power-cycle the scooter a few times, then re-read.
- `bms_soh_rt` 0, `bms_dc_fl_t_rt` 255, `db_k_estimated_mileage` 0 are placeholders on the KQi
  Air (the CLI labels them). They are not symptoms.
- If it recurs: ask for the dashboard reading, whether the LED flickers red at plug-in, and
  run `kqi poll` across a plug/unplug. The 2-year warranty covers the battery (Best Buy listing;
  NIU's own KQi Air page not checked).

## iPhone app (KQi Rides) and tap-to-unlock

`~/Documents/niu-kqi/ios` is a SwiftUI app (`KQiRides`, bundle `com.alexhedtke.KQiRides`)
that does the same BLE reads/settings/commands as the CLI, plus ride charts. Build with
`ios/scripts/build.sh` (compile check) or `--device` to sign (fill `Config/Signing.xcconfig`).
A connected, paired iPhone installs via `xcrun devicectl device install app`.

**NFC unlock is a phone-side pipeline, not the scooter's NFC.** The base KQi Air has no NFC
reader (that is a KQi Air X / moped feature), and iOS does not let an app emulate an NFC
card, so "phone as the card the scooter reads" is impossible. Instead: a passive NTAG
sticker the phone reads fires a BLE unlock through KQiRides. The app answers URL scheme
`kqirides://unlock|lock|on|off` and App Intents "Unlock/Lock KQi Air" (Siri, Action button,
Shortcuts), both routed through `AppState.performExternal` with a fixed allowlist (never
factory-reset). Setup: any blank NTAG21x + a Shortcuts NFC automation running the intent,
"Ask Before Running" off. README has the step list. Proximity auto-unlock (NIU Link /
`ecu_bt_status` bit 32768) already exists but flaps at the range edge; the tap is
deterministic.

**Lock Screen power button (added 2026-11-09).** `ios/Widget/` holds a Lock Screen
widget and an iOS 18 control that run `PowerOnScooterIntent` (`ios/Shared/`). It is a
`LiveActivityIntent`, so iOS runs it in the app's process in the background, and
`ScooterPower.swift` does the work: saved-identifier reconnect, read the power bit,
`db_k_cmd = 1` only if off, read back, park the link. The NIU app's own power path is
the same single write (`acc_on`, 2 s ack, one retry). Debug a failed tap from the
attempt log, `Documents/power-log.jsonl` in the app container (README has the
`devicectl device copy from` line). A scooter whose link the NIU app holds does not
advertise, so the app reaches it through the phone's open link, matched by BLE name.
The app needs the scooter's BLE credentials in its Keychain: a NIU sign-in puts them
there, or the Mac hands them over through `Documents/ble-import.json` (README).

## Where things live

- Repo: `~/Documents/niu-kqi` (`kqi_ble.py` CLI + bleak session, `niu_proto.py` frames and
  crypto with a self-test, `niu_cloud.py` login/list/bleinfo, `data/fields.json` table).
- Credentials: `~/Documents/niu-kqi/secrets/` (gitignored; README there explains rebuild).
- App bundle: `/Applications/NIU KQi.app` (id `com.exobrain.niu-kqi`).
- Memory: `project_kqi_scooter_cli` in the MIST memory store has the live-test status.
