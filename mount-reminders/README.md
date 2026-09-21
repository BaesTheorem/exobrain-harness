# mount-reminders

Fires a clickable MIST banner the moment a named external volume mounts, if there is
work waiting on that drive. Built for "do X the next time the SSD is plugged in".

- `on-mount.sh` runs under launchd with `StartOnMount` (every mount event), at login, and every
  10 minutes. The interval exists because an unmount is not a mount event: without it the
  debounce flag would survive an eject and swallow the next plug-in of the same drive.
- Reminders are plain text files outside the repo, one per volume name:
  `~/Library/Application Support/exobrain/mount-reminders/<Volume Name>.txt`.
  Non-empty file + `/Volumes/<Volume Name>` present = one banner per mount
  (a `.notified/<name>` flag debounces; it clears when the volume goes away).
- Empty or delete the file when the work is done. The agent stays loaded and idle.
- Log: `~/Library/Logs/exobrain/mount-reminders.log`.

Install: copy (never symlink) the plist into `~/Library/LaunchAgents/` and bootstrap it.

Test without a drive: `VOLUMES_DIR=/tmp/fakevol REMINDERS_DIR=/tmp/fakerem NOTIFY=/bin/echo ./on-mount.sh`.
