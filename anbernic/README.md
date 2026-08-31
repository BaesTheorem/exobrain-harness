# Anbernic wireless ROM push

Wireless game-file transfer for an Anbernic RG35XX-family handheld running the
**stock OS**, which has no file transfer of its own, no open network port, and
no USB drive mode (verified: the device presents nothing but charging over
USB-C, and nothing listens on any TCP port).

The stock OS *does* ship a full SSH service. It's just turned off. So:

- **On the device (one-time):** install the community **Temporary SSH Server**
  app into the OS card's `Roms/APPS/`. Launching it from the APPS menu runs
  `systemctl start ssh.service`, exposing SSH on port 22 (user `root`, pass
  `root`) while the app is on screen. The app is by G.R.H, from
  [cbepx-me/Anbernic-H700-RG-xx-StockOS-Modification](https://github.com/cbepx-me/Anbernic-H700-RG-xx-StockOS-Modification);
  `fetch-payload.sh` pulls it (it isn't vendored here).
- **On the Mac:** `bin/push-rom` drives it over SSH. First run installs a
  dedicated key (so later pushes need no password), finds the games card's
  Roms folder (handles a two-card OS/games split by targeting the non-OS card),
  infers the `Roms/<SYSTEM>/` folder from the file extension, streams the
  upload with progress, and verifies it with a remote sha256.

## Why SSH and not a custom server

Stock has no way in from cold: no listening service to push to, and no USB mass
storage. Any wireless path therefore needs the device to *start* something, and
the one capable thing already installed is `sshd`. Using it means no foreign
binary on the device, exact path control (so games land on the games card, not
the OS card), and a plain root shell for setup and debugging.

## One-time setup (needs the OS card written once)

Getting the app onto the card is the one unavoidable manual step, because stock
offers no way in until SSH is running. Any single write to the OS card does it:
a borrowed SD reader, a friend's PC, or a phone + USB-C microSD reader.

1. `./fetch-payload.sh` — stages both apps (SSH, plus SAMBA as a backup lane)
   under `card/APPS/`.
2. Install **flat** on the **OS card** (TF1, the one that boots; stock reads
   the APPS menu from `/mnt/mmc/Roms/APPS/`), matching the card's convention:
   each app's `.sh` goes into `Roms/APPS/` itself, its `res/*.png` merge into
   the shared `Roms/APPS/res/`, and its `Imgs/<app>.png` menu icon goes into
   `Roms/APPS/Imgs/`. Games still go to the games card, over the network.
3. Run `dot_clean -m` on the card's APPS folder if copying from a Mac (the
   `._*` droppings would show up as phantom menu entries), eject, card back
   in, boot, connect to WiFi (Settings > Network Settings).

## Every time

On the device: APPS menu > **Temporary SSH Server**. It shows the device IP on
screen. Then, on the Mac:

```
push-rom --setup --ip 192.168.0.21   # first time only: key + find both cards
push-rom game.gba                    # system folder inferred, games card
push-rom disc.chd --system PS        # explicit system folder
push-rom game.gba --card os          # target the OS card instead
push-rom --list                      # what system folders exist
push-rom --list GBA --card os        # inspect the OS card's copy
push-rom game.gba --dry-run          # show what it would do
```

The IP and games-Roms path are cached in `~/.config/push-rom/config.json`
after setup; the dedicated key lives beside it. If a pushed game doesn't
appear, re-enter that system's list on the device (it rescans on entry) or
reboot. The SSH app must be on screen for the device to answer.

`root:root` over SSH on the home LAN, only while the app is open, is the same
posture the community app ships with. `PUSH_ROM_PASS` overrides the password if
you change it on the device.

## Field notes (RG35XXSP, stock 64-bit firmware)

- The SSH app's UI dies instantly on this firmware (in its button-input loop),
  but only after `systemctl enable ssh.service` has run, so the crash is
  cosmetic and one launch is enough forever: `ssh.service` stays enabled and
  sshd answers on every boot from then on (verified across a reboot). Turn it
  off with `systemctl disable ssh` over SSH if wanted.
- Mounts: OS card (TF1) at `/mnt/mmc`, games card (TF2) at `/mnt/sdcard`.
- The device's clock and locale can be wildly wrong; it doesn't affect pushes.
