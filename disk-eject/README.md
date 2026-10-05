# disk-eject

Clicking the eject arrow on an external drive fails whenever some process still
has a file open on it. macOS names the offending PID in a dialog and stops
there, leaving you to hunt it down. This makes the eject just work: a launchd
agent watches for failed ejects, asks the holders to quit, and finishes the job.

Built after `rqbit` (the Trawl torrent daemon) sat on a 1 TB media drive with
~200 open file handles and blocked the eject.

**It never forces.** There is no `diskutil unmount force`, no SIGKILL, and no
flag that turns either on. Finder already has a Force Eject button; a tool that
forces behind your back is worse than the dialog it replaces. When a holder
will not quit, the volume stays mounted and the notification names it.

## Use it

Nothing to run. Click eject in Finder; if it fails, the agent asks the holders
to quit, waits for them, completes the eject, then notifies.

Manually:

```sh
disk-eject/bin/mist-eject                 # the mounted external volume
disk-eject/bin/mist-eject "Extreme SSD"   # by name, /Volumes path, or device
disk-eject/bin/mist-eject --dry-run       # show what would be asked to quit
disk-eject/bin/mist-eject --no-eject      # release holders, stay mounted
```

## How it decides

The trigger is `diskarbitrationd` logging
`unable to unmount /dev/diskNsM (status code 0x00000010)`. `0x10` is `EBUSY`;
any other status is a different failure and is ignored. Finder fires several
solicitations per click, so repeats within `debounce_seconds` are dropped, and
the debounce restarts when a run ends (our own failed eject logs the same line).

Each holder is asked to quit the way it expects to be quit:

1. **Per-app pre-stop hook** first, so an app can checkpoint. rqbit gets every
   torrent paused (`handlers/rqbit-pause.sh`).
2. **launchd jobs** (the holder's pid is a job in the gui domain) are
   **booted out**. KeepAlive would otherwise relaunch the job the moment it
   exits, and the relaunch reopens the volume; this is why Plex used to look
   like it "ignored SIGTERM". launchd sends SIGTERM and waits the plist's
   `ExitTimeOut` before it kills the job itself, so that value must exceed the
   grace period (`com.alexhedtke.plex` is set to 300 s; the log warns when a
   plist's timeout is shorter than its `wait`). After the eject attempt the
   job is bootstrapped again, so its own RunAtLoad / StartOnMount / KeepAlive
   rules bring it back. Plex's guard script exits at once while the drive is
   absent and starts Plex on the next mount.
3. **App bundles** get an AppleScript `quit`, the same as Cmd-Q, so the app
   can save state or ask about unsaved changes. A "save changes?" sheet just
   leaves the app as a remaining holder.
4. **Everything else** gets SIGTERM.

All holders are asked at once, then one shared grace period runs (the longest
`wait` among them). Asking in sequence would cost grace period times holders,
and a media drive easily has rqbit, Plex and a player on it together.

After the wait the volume is checked again with `lsof`, not the pids that were
signalled: a relaunched or newly started process is just as much a holder. If
anything non-protected still holds it, the run stops, the launchd jobs are
reloaded, and the notification names the holder. Otherwise `diskutil eject`
runs on the whole device.

## Safety rails

**The boot disk is refused before anything else.** The whole device behind `/`
is resolved and compared against the target, so every volume and snapshot on
the internal drive is off limits regardless of how it is addressed. This
matters because the boot volume also appears at `/Volumes/Macintosh HD`.
Beyond that, the volume must be mounted under `/Volumes` and be
ejectable/removable.

**Protected processes are never signalled** (`config.json`). Spotlight,
fseventsd, backupd and Finder all release when diskarbitrationd asks them to;
killing them just causes reindexing and broken Time Machine state. They are
also ignored in the "still held" check, since a normal eject clears them.

### Why there is no middle rung

Earlier versions escalated to `diskutil unmount force` for a holder that
ignored SIGTERM, and offered `--force` for SIGKILL. Both are gone. Forcing is
what Finder's Force Eject button is for, and the one holder that triggered the
forced unmount in practice (Plex) was not stubborn at all: launchd was
relaunching it. The launchd-aware quit above fixes the cause.

A "is this process mid-write?" guard was also tried and dropped: open-file
offset deltas miss in-place writes (how rqbit writes torrent pieces), and
`proc_pid_rusage` disk counters stay flat because buffered writes are charged
to writeback. A guard that fails open is worse than no guard.

## Files

| Path | What |
|------|------|
| `disk_eject.py` | Everything: `free` (one-shot) and `watch` (daemon) |
| `config.json` | Allowlist, protected processes, per-app handlers. Read fresh each run, no reload needed |
| `handlers/rqbit-pause.sh` | Pauses all torrents before rqbit is asked to quit |
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
under launchd. After editing `disk_eject.py`, restart the agent
(`launchctl kickstart -k gui/$(id -u)/com.exobrain.eject-assist`); the running
daemon keeps the old code otherwise.

## Adding an app

Give it an entry in `graceful_handlers`: `pre` for a flush/checkpoint command,
`wait` for how long it needs to shut down. If the app runs as a launchd job,
make sure its plist's `ExitTimeOut` is longer than `wait`.

```json
"Plex Media Server": { "wait": 60 }
```

## Verified

Tested against a mounted sparse disk image with real holders: a SIGTERM-honoring
holder released and the image ejected; a SIGTERM-ignoring holder left the image
mounted and the process alive, with the holder named; a KeepAlive launchd job
holding a file was booted out, the image ejected, and the job bootstrapped
again; the boot disk refused via `/`, `/Volumes/Macintosh HD`,
`/System/Volumes/Data` and the whole device; and the watch path exercised
under launchd with a `diskutil eject` that failed EBUSY.
