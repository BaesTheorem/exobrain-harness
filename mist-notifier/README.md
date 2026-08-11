# MIST Notifier

The native notification arm of `mist-voice/bin/mist-notify`: a tiny Swift
LSUIElement app (`/Applications/MIST Notifier.app`, shows as **MIST** with the
MIST icon on banners) that posts through `UNUserNotificationCenter` and handles
what the old terminal-notifier path never could:

- **Action buttons** (up to 3 per banner, arbitrary labels/targets)
- **Inline reply**: type into the banner, the text lands in a MIST Console chat
  (`POST /notify-reply`). If the Console is closed the helper boots it and
  retries for ~30s. Undelivered text is logged, never dropped.
- **Image attachments**, subtitle, thread grouping, replace-by-id, urgency
  (interruption level)
- **Click targets** with the same semantics as mist-notify's 4th arg
  (`console`, `console:<sid>`, URL/scheme, file path) plus `cmd:<shell>` for
  buttons.

`mist-notify` composes a JSON spec, invokes `open -n -a "MIST Notifier" --args
post <spec>`, and reads `<spec>.result`. Anything but `{"ok": true}` (helper
missing, permission pending/denied) falls back to terminal-notifier, then
osascript, so notifications always degrade gracefully.

## Build / install

```sh
./build.sh                                        # builds, signs, installs, lsregisters
open -a "/Applications/MIST Notifier.app" --args auth   # one-time permission prompt
```

If the permission prompt gets dismissed, macOS records a deny; re-enable in
System Settings → Notifications → MIST (`open
"x-apple.systempreferences:com.apple.Notifications-Settings.extension"`).

## Hard-won macOS 26 facts (why this app exists)

- `usernoted` validates every UN API caller against its Launch Services bundle
  record ("Failed to find or validate client"). The validation requires the
  process's **main executable to be the bundle's declared Mach-O**. The MIST
  Console (shell script exec'ing bundled python) can never pass it; this app
  does.
- Apps in `/tmp` (or other scratch paths) fail the same validation even when
  correctly signed and LS-launched. **/Applications works.** That's also why
  the notification prompt never fired for any of the probe builds.
- Ad-hoc signing was not the blocker (Apple Development identity used anyway,
  from the Xcode setup).
- The legacy `NSUserNotification` API (terminal-notifier's route) has none of
  these checks, which is why the fallback works unsigned.
- `com.apple.ncprefs.plist` no longer exists on macOS 26; notification
  settings live in `usernoted`'s TCC-protected container. Diagnose with
  `log show/stream --predicate 'process == "usernoted"'`, not the plist.
- Category ids are content-hashed (djb2) so identical button layouts reuse one
  registered `UNNotificationCategory` across the app's single-shot instances
  (Swift's `hashValue` is per-process seeded and would leak categories).
- **Never re-sign a running app**: macOS revokes the live process's TCC grants
  on the mismatch (a mid-session re-sign of the Console cost it Documents
  access until relaunch).

Log: `~/Library/Logs/exobrain/mist-notifier.log`. History (written by
mist-notify, read by the Console's bell panel):
`~/Library/Logs/exobrain/notifications-history.jsonl`.
