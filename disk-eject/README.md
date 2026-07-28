# disk-eject

Clicking the eject arrow on an external drive fails whenever some process still
has a file open on it. macOS names the offending PID in a dialog and stops
there, leaving you to hunt it down. This makes the eject just work: a launchd
agent watches for failed ejects and finishes the job.

Built after `rqbit` (the Trawl torrent daemon) sat on a 1 TB media drive with
~200 open file handles and blocked the eject.

## Use it

Nothing to run. Click eject in Finder; if it fails, the agent releases the
holders and completes it within a second or two, then notifies.

Manually:

```sh
disk-eject/bin/mist-eject                 # the mounted external volume
disk-eject/bin/mist-eject "Extreme SSD"   # by name, /Volumes path, or device
disk-eject/bin/mist-eject --dry-run       # list what would be stopped
disk-eject/bin/mist-eject --force         # allow SIGKILL (see below)
disk-eject/bin/mist-eject --no-eject      # release holders, stay mounted
```

## How it decides

The trigger is `diskarbitrationd` logging
`unable to unmount /dev/diskNsM (status code 0x00000010)`. `0x10` is `EBUSY`;
any other status is a different failure and is ignored. Finder fires several
solicitations per click, so repeats within `debounce_seconds` are dropped.

Escalation, gentlest first:

1. **Per-app pre-stop hook**, so an app can checkpoint. rqbit gets every
   torrent paused first (`handlers/rqbit-pause.sh`).
2. **SIGTERM** to every non-protected holder at once, then one shared grace
   period. Signalling in parallel matters: waiting per-process in sequence
   would cost the grace period times the number of holders, and a media drive
   easily has rqbit, Plex and a player on it together.
3. **`diskutil unmount force`** for anything that ignored SIGTERM. This is the
   OS's own way to take a volume back. It flushes the filesystem and revokes
   the handles while leaving the app running to report an I/O error.
4. **`diskutil eject`** on the whole device.

`SIGKILL` is never sent unless you pass `--force`.

## Safety rails

**The boot disk is refused before anything else.** The whole device behind `/`
is resolved and compared against the target, so every volume and snapshot on
the internal drive is off limits regardless of how it is addressed. This
matters because the boot volume also appears at `/Volumes/Macintosh HD`.
Beyond that, the volume must be mounted under `/Volumes` and be
ejectable/removable.

**Protected processes are never signalled** (`config.json`). Spotlight,
fseventsd, backupd and Finder all release on their own once the forced unmount
lands; killing them just causes reindexing and broken Time Machine state.

### Why there is no "is it mid-write?" check

The first design force-killed holders that ignored SIGTERM, but only if they
looked idle. Both instruments tried for that failed:

- **Open-file offset deltas** miss in-place and random-offset writes. A test
  writer doing `seek(0)` before each write was scored idle and killed. That is
  exactly how rqbit writes torrent pieces into preallocated files, so the guard
  would have failed on the one process it was written for.
- **`proc_pid_rusage` disk-I/O counters** stay flat under a heavy writer,
  because buffered writes are accounted to writeback rather than the process.

A guard that fails open is worse than no guard, since it invites trusting it.
So the ladder stops short of SIGKILL instead, and the forced unmount does the
work. (`iostat` was ruled out earlier for a different reason: it only tracks
physical devices like `disk0`, not APFS volumes.)

## Files

| Path | What |
|------|------|
| `disk_eject.py` | Everything: `free` (one-shot) and `watch` (daemon) |
| `config.json` | Allowlist, protected processes, per-app handlers. Read fresh each run, no reload needed |
| `handlers/rqbit-pause.sh` | Pauses all torrents before rqbit is stopped |
| `bin/mist-eject` | CLI wrapper |
| `com.exobrain.eject-assist.plist` | launchd agent |

Log: `~/Library/Logs/exobrain/eject-assist.log`

## Manage

```sh
launchctl list | grep eject-assist
launchctl bootout   gui/$(id -u)/com.exobrain.eject-assist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.eject-assist.plist
```

Per harness convention the plist is a real copy in `~/Library/LaunchAgents/`,
not a symlink, and runs `/opt/homebrew/bin/python3` so it has Full Disk Access
under launchd.

## Adding an app

Give it an entry in `graceful_handlers`: `pre` for a flush/checkpoint command,
`wait` for how long it needs to shut down.

```json
"Plex Media Server": { "wait": 20 }
```

## Verified

Tested against a mounted sparse disk image with real holders: idle holder
released and ejected; two SIGTERM-ignoring writers survived the forced unmount
with the disk still ejecting; boot disk refused via `/`, `/Volumes/Macintosh
HD`, `/System/Volumes/Data`, `disk3s5` and `disk0`; and the full path exercised
under launchd, not just in a shell.
