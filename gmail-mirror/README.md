# gmail-mirror

An hourly local copy of a Gmail account. It is a hedge against losing the Google account.

- `sync.sh` runs `mbsync` (isync). It pulls `[Gmail]/All Mail` into the Maildir `~/Mail/gmail`. When `/Volumes/Extreme SSD` is mounted, `rsync` then copies the Maildir to `Gmail mirror/` on that disk.
- The mirror is append-only. The config pulls new messages and flag changes only. Deletions on the server do not remove local mail.
- The Maildir is NOT in the nightly backup archive. That archive goes to Google Drive, and a Drive copy goes away in the same account lockout.
- If a sync fails, the script shows a banner, a maximum of one each day.

## Setup

1. `brew install isync`
2. Make a Google app password (2FA must be on). Put it in the login Keychain:
   `security add-generic-password -U -a you@gmail.com -s mbsync-gmail -w "<password without spaces>"`
3. `cp mbsyncrc.example ~/.config/gmail-mirror/mbsyncrc`, then write your address in it.
4. `cp com.exobrain.gmail-mirror.plist ~/Library/LaunchAgents/` and `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.gmail-mirror.plist`

The config that the job uses is not in the repo, because it contains the account address. The log is `~/Library/Logs/exobrain/gmail-mirror.log`.
