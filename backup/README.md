# backup/ -- Drive API uploader for the collective backup

`drive-upload.py` pushes the nightly `exobrain-collective-*.tar.gz` archive to
Google Drive through the API's resumable-upload protocol. It exists because the
previous path (drop the file in the DriveFS mount, poll for the item-id xattr)
lost data five separate times between 2026-07-20 and 2026-08-28: DriveFS retries
a queued upload a few times, every retry lands in a 45-second darkwake sliver
with no network on a sleeping battery Mac, and it then reverts the cloud file to
0 bytes. A resumable API session survives sleep, process death, and reboots --
the session URI stays valid about a week and each chunk resumes from the last
byte the server acknowledged.

Driven by `../backup-exobrain.sh` (launchd `com.exobrain.backup` daily at 2 AM +
`com.exobrain.backup-resume` every 30 minutes). The shell script feeds it to
`/usr/bin/python3` via stdin so the python process never opens a file under
`~/Documents` (TCC), which is also why the script must never use `__file__`.

## Runtime state (all OUTSIDE this repo, in `~/Exobrain backup staging/`)

- `.drive-token.json` -- gitignored-equivalent secret. OAuth refresh token with
  the full `drive` scope (needed to see and prune archives the old DriveFS path
  created; `drive.file` only sees files this client uploaded). To rebuild:
  `python3 backup/drive-upload.py auth` interactively; it needs
  `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` in the harness `.env`
  (reused from the claude-nest GCP project, OAuth consent screen must be
  published "In production" or the refresh token dies in 7 days).
- `uploaded.log` -- append-only ledger of confirmed uploads
  (`timestamp<TAB>name<TAB>driveFileId<TAB>md5`). The shell script's freshness
  guard reads it; only md5-verified uploads count as backups.
- `exobrain-collective-*.tar.gz` -- the newest uploaded archive is kept here as
  off-cloud redundancy (`BACKUP_LOCAL_KEEP`), plus any archive whose upload has
  not finished yet (never deleted until the cloud md5 matches).
- `*.driveupload.json` -- per-archive resumable-session state; deleted when the
  upload confirms.

## Subcommands

```
drive-upload.py auth              one-time consent -> refresh token
drive-upload.py upload FILE       resumable upload (exit 75 = deadline, resume later)
drive-upload.py verify NAME       is NAME in the Drive folder? prints id/md5
drive-upload.py list              list cloud archives
drive-upload.py prune             GFS retention (--daily/--weekly/--monthly)
drive-upload.py delete NAME       delete one cloud file by exact name
```
