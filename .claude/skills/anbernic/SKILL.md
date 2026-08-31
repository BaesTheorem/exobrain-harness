---
name: anbernic
description: "Manage Alex's Anbernic RG35XXSP retro handheld over WiFi -- push game files to the right system folder, list what's on the cards, and do on-device maintenance (APPS, BIOS, config flags) over SSH. Use when Alex mentions the Anbernic, RG35XXSP, 'the SP', 'the handheld', pushing/sending a ROM or game to it, 'put this game on', what games are on it, or wants anything changed on the device or its SD cards."
metadata:
  hardware: "Anbernic RG35XXSP (H700), stock 64-bit firmware, two-card split: TF1=OS, TF2=games"
  tools_dir: "/Users/alexhedtke/Documents/Exobrain harness/anbernic"
---

# /anbernic

Wireless control of Alex's **RG35XXSP** (GBA-SP-style clamshell). The stock OS
has no transfer feature, no USB data mode, and no open ports out of the box;
everything here rides the OS's own **sshd**, which is now armed at every boot.
Read this before touching the device -- the gotchas below are all field-tested.

## Reachability (check first, explains most "failures")

- **SSH root@device, port 22, key auth already installed.** IP and both Roms
  paths are cached in `~/.config/push-rom/config.json` (key + known_hosts sit
  beside it). Password fallback is the firmware default `root`; push-rom
  re-installs the key by itself if it ever vanishes.
- **sshd auto-starts ~35s after power-on.** Mechanism: the firmware boot script
  `/mnt/mod/ctrl/autostart` enables sshd only if `global.ssh=1` is in
  `/mnt/mod/ctrl/configs/system.cfg` (set 2026-08-31; pre-change backup
  `system.cfg.bak-mist` alongside). Without the flag it actively stops+disables
  sshd every boot -- so a bare `systemctl enable` never survives. Remove the
  flag line to turn always-on SSH off.
- **Unreachable device = it's off or the lid's closed** (sleep kills WiFi),
  or DHCP moved it. Ping + port-22 probe first; if the IP moved, rescan the
  LAN for port 22 and re-run `push-rom --ip <new-ip>` once (it re-caches).
- The "Temporary SSH Server" app in the APPS menu crashes on launch (its input
  loop) but still starts sshd first -- it's the manual fallback if the flag
  ever gets lost. A "Temporary SAMBA Server" app is also installed, untested.

## Pushing games: `anbernic/bin/push-rom`

```
push-rom <file> [...]            # infer Roms/<SYSTEM>/ from extension, push, sha256-verify
push-rom disc.chd --system PS    # ambiguous formats (.zip/.chd/.cue/.iso) need --system
push-rom game.gba --card os      # target the OS card instead of the games card
push-rom --list [SYSTEM]         # what's on the games card (add --card os for TF1)
push-rom game.gba --dry-run      # show routing without writing
push-rom --setup --ip <ip>       # re-key + re-discover after IP/card changes
```

- Default target is the **games card** (TF2). Every push is **sha256-verified
  remotely**; trust the tool's verdict, don't re-verify by hand.
- A pushed game appears after **re-entering that system's menu** on-device
  (stock rescans on entry), or a reboot. Say so when reporting a push.
- Big files stream with a progress line; in the Console, wrap the call in
  `mist-progress run` so Alex sees a bar.
- Unknown extension → the tool exits 2 and prints the card's real folder list;
  pick with `--system` rather than guessing a new folder name.

## Maintenance over SSH (root shell)

- **Mounts:** OS card (TF1) = `/mnt/mmc` (vfat), games card (TF2) =
  `/mnt/sdcard`. Rootfs is plain read-write ext4 (no overlay), so changes
  under `/` persist -- including mistakes. BIOS files live in `/mnt/mmc/bios`.
- **APPS convention** (for installing/fixing menu apps): flat `<Name>.sh` at
  `/mnt/mmc/Roms/APPS/`, runtime images merged into the shared `APPS/res/`,
  menu icon at `APPS/Imgs/<Name>.png`. If files came via a Mac card-mount, run
  `dot_clean -m` -- `._*` files become phantom menu entries.
- **system.cfg flags** (`/mnt/mod/ctrl/configs/system.cfg`): known keys
  `arcade.auto`, `global.bezel`, `global.dark`, `global.shader`, `power.quick`,
  `power.lock`, `global.ssh`. `autostart` is the reader. Back the file up
  before any edit.
- **Be conservative with rm/mv on the cards** -- `/mnt/sdcard/Roms` is the
  entire game library. Prefer moving to a `/mnt/sdcard/.trash/` you create
  over deleting, unless Alex explicitly says delete.

## Gotchas

- **Never trust the device's clock, dates, or locale** (it thinks it's another
  year and speaks Chinese). File mtimes on-device are decoration.
- Verified dead ends -- don't re-litigate: USB is charge-only (no mass
  storage/MTP on stock; the Mac's USB tree shows nothing), and cold stock
  exposes zero TCP ports until sshd is armed.
- Security posture: root/root on the home LAN whenever the device is on. Fine
  at home; if Alex ever takes it to public WiFi, offer to strip the
  `global.ssh=1` flag first.

Deeper background: `anbernic/README.md` (field notes) and memory
[[anbernic-rom-push]].
