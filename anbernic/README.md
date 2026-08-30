# Anbernic wireless ROM push

Wireless game-file transfer for an Anbernic RG35XX-family handheld running the
**stock OS**, which has no built-in network transfer. Two halves:

- **`card/APPS/`** goes on the device's SD card once. `WiFi_Push_ON.sh` starts
  a [dufs](https://github.com/sigoden/dufs) file server (port 8035) serving the
  ROMS partition; `WiFi_Push_OFF.sh` stops it. Stock OS runs `.sh` files
  dropped in `Roms/APPS/` straight from its APPS menu, which is the whole
  trick. The server binary is copied to `/tmp` before launch because FAT cards
  can be mounted noexec.
- **`bin/push-rom`** runs on the Mac. Finds the device (cached IP, else LAN
  scan for port 8035 + dufs health check), infers the `Roms/<SYSTEM>/` folder
  from the file extension (validated against the folders actually on the
  card), streams the upload, and verifies it with a server-side sha256.

## One-time setup

1. `./fetch-binaries.sh` (binaries are not committed; this pulls dufs v0.46.0
   for arm64 + arm32 devices and a darwin build for local testing)
2. Put the SD card in the Mac and copy **the contents of `card/APPS/`** into
   the card's `Roms/APPS/` folder (two scripts + the `wifipush` folder).
3. Eject, boot the device, connect it to WiFi (Settings > Network Settings).

## Every time

On the device: APPS menu > `WiFi_Push_ON`. Then:

```
push-rom game.gba                 # push, system folder inferred
push-rom disc.chd --system PS     # explicit system folder
push-rom --list                   # what system folders exist
push-rom --list GBA               # what's in one of them
```

If a pushed game doesn't appear, re-enter that system's game list (stock
rescans on entry) or reboot. A closed lid usually means the device is asleep
or off, so the server won't answer. `WiFi_Push_OFF` stops the server; so does
powering off.

No auth on the server: it only runs when launched by hand, on the home LAN,
serving a game card. Debug log lands on the card at
`Roms/APPS/wifipush/wifipush.log`.
