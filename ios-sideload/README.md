# iOS sideload refresher

Keeps apps signed with a **free** Apple developer account alive on the iPhone.

Apple gives free-tier provisioning profiles a 7-day life. When one lapses the
app stays on the home screen and simply refuses to open, so the failure is
invisible until you tap it. This rebuilds each app a couple of days early and
pushes it back over WiFi, which restarts the 7-day clock.

    ./refresh.py --status     what expires when, touches nothing
    ./refresh.py --discover   developer-signed apps on the phone vs apps.json
    ./refresh.py              refresh anything inside the threshold
    ./refresh.py --force      refresh everything now
    ./refresh.py --quiet      same, without the spoken notification

Scheduled twice daily by `com.exobrain.ios-sideload-refresh` (10:30 and 20:30).
Twice, because the laptop sleeps through scheduled jobs often enough that one
attempt per day is not a safe margin. Logs to
`~/Library/Logs/exobrain/ios-sideload-refresh.log`.

## Setup

Copy `apps.example.json` to `apps.json` and fill it in. The real config is
gitignored because it holds an Apple team ID and local paths; `state.json` is
gitignored too, since it just tracks what is currently on the phone and
rebuilds itself on the next run.

Each app entry points at a build script **that already exists in that app's own
repo** and signs for a real device. This deliberately owns no build logic: the
repo knows how to build itself, and duplicating that here would rot.

## Why it works

Three things had to be non-interactive, and all three are (verified 2026-08-23):

* `xcodebuild -allowProvisioningUpdates` renews a profile against the saved
  Xcode account with no 2FA prompt.
* `devicectl` installs over the local-network tunnel with nothing plugged in,
  once the phone has been paired for network connection in Xcode.
* Reinstalling over the same bundle id keeps the app's data.

## The three traps

Each of these produced a build that reported success while achieving nothing:

1. **Xcode reuses a cached profile until it actually expires.** Rebuilding on
   day 5 re-signs with the same profile that dies on day 7, so the app lapses
   anyway. The fix is to delete the cached profile for that bundle id first;
   with nothing to reuse, Xcode mints a fresh one and the clock restarts.
2. **An up-to-date product skips the codesign step.** If nothing changed,
   xcodebuild leaves the old profile embedded. The old device builds are
   deleted before each refresh so signing has to run.
3. **`devicectl list devices` lies about reachability.** It reports a cached
   `tunnelState` of `disconnected` for a phone that answers fine, because the
   tunnel is only raised on demand. Asking for device details is the real
   reachability test.

After all that, the built profile is checked one more time before installing.
If it did not actually renew, the run fails loudly instead of pushing a dud.

## Limits

* The phone must be on the same network and awake. Unreachable runs retry on
  the next tick and only nag if something is inside a day of expiring.
* Apps deleted from the phone stay deleted, unless the entry sets
  `alwaysInstall`. Use `--discover` to find sideloads with no config entry:
  those cannot be refreshed, usually because the source is gone.
* This is a workaround for not paying for the Developer Program. The paid tier
  signs for a year and makes the whole thing unnecessary.
