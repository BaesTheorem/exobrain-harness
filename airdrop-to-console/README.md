# AirDrop → MIST Console

Send a photo from your iPhone straight into the MIST Console with zero clicks on
the Mac. AirDrop the photo to this Mac; it appears in a pinned **📷 iPhone Photos**
chat in the Console, ready for MIST to look at.

## Why this exists

macOS hardwires AirDrop's receive folder to `~/Downloads` and offers no setting to
change it. This watcher gives you the effect of a different destination: it plucks
AirDropped images back out of Downloads and routes them to the Console instead.

## How it works

- **launchd** (`com.exobrain.airdrop-console`) fires on any change to `~/Downloads`
  (`WatchPaths`), plus every 15 min as a fallback for photos that landed while the
  Console was closed.
- `watch.py` keeps only files that are **both** an image **and** AirDropped. The
  AirDrop signal is the `com.apple.quarantine` xattr: its third field is the agent
  that wrote the file, which is `sharingd` for AirDrop and `Chrome`/`Safari` for
  downloads. The fourth field is a per-file UUID, used to dedup so a Downloads
  change never re-posts the same photo.
- HEIC/HEIF (the usual iPhone format, which Claude's image reader and the Console's
  resizer can't decode) is transcoded to JPEG with `sips`.
- The image is **moved** out of Downloads into `../tmp/images/airdrop/` and POSTed
  to the Console (`/send/<sid>`) as a data-URL, so it renders in the chat bubble and
  MIST can `Read` it.
- Target is a dedicated, pinned **📷 iPhone Photos** chat, recreated automatically
  if you delete it (or if it gets too large and hits the context gate).

## Install

```sh
cp "com.exobrain.airdrop-console.plist" ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.exobrain.airdrop-console.plist 2>/dev/null
launchctl load  ~/Library/LaunchAgents/com.exobrain.airdrop-console.plist
```

(The LaunchAgents copy must be a real file, not a symlink into `~/Documents`, or
launchd's sandbox can't read it.)

## Usage

Take a photo on the iPhone → Share → AirDrop → this Mac. Done. It shows up in the
**📷 iPhone Photos** chat a second or two later.

## Files

- `watch.py` — the watcher (pure stdlib; macOS `xattr` + `sips`).
- `com.exobrain.airdrop-console.plist` — launchd agent.
- `state.json` — runtime state (dedup UUIDs + the dedicated chat id). Gitignored.
- `watch.log` — launchd stdout/stderr. Gitignored.

## Switching where photos land

Default is the isolated **📷 iPhone Photos** chat so an AirDrop never barges into a
conversation you're mid-way through. If you'd rather photos drop into whatever chat
is active, that needs the Console to expose the focused tab server-side (it doesn't
today); ask MIST to wire it up.
