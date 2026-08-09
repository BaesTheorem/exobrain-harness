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

## Where the photo lands

The watcher picks the target chat by intent, in priority order:

1. **Manual claim.** Type `/here` in a Console chat's composer and AirDrops route
   into that chat for 5 minutes; `/photos` forces them into the dedicated photos
   chat instead; `/here off` clears the claim. (These are Console-local commands,
   intercepted client-side, never sent to MIST.)
2. **The chat on screen.** Absent a claim, the photo joins whichever chat the
   Console is currently showing. The front-end POSTs its active chat id to
   `/active-chat` on every tab switch, on window focus, and on a 30s heartbeat;
   the watcher uses that id if the report is under **90s** old.
3. **Recency.** If the Console can't say what's on screen (it's closed, or it's an
   older build without `/active-chat`), fall back to the most recently active chat
   within **120s**.
4. **Dedicated chat.** Otherwise a pinned **📷 iPhone Photos** chat, recreated
   automatically if you delete it (or if it gets too large and hits the context
   gate).

So: photos land in the chat you're looking at; photos you grab while the Console
is closed land in the photos chat; and `/here` / `/photos` override either way.

Why the heartbeat matters: recency alone counts *agent output*, not your
attention, so with two chats open it routes to whichever one happens to be mid
turn rather than the one you're typing in. The heartbeat also expires on its own,
so a chat that was on screen hours ago can't capture a photo you take today.

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

- `watch.py` -- the watcher (pure stdlib; macOS `xattr` + `sips`).
- `com.exobrain.airdrop-console.plist` -- launchd agent.
- `state.json` -- runtime state (dedup UUIDs + the dedicated chat id). Gitignored.
- `watch.log` -- launchd stdout/stderr. Gitignored.

## Console dependency

The routing reads two Console endpoints: `GET /sessions` (recency) and
`GET/POST /airdrop-claim` (manual claims, set by the `/here` and `/photos`
composer commands in `mist-console`). If the Console is an older build without
`/airdrop-claim`, the claim lookup fails closed and routing falls back to recency
then the dedicated chat, so nothing breaks. Restart the Console after updating it
to pick up the endpoint and commands.
