# iMessage Reader + Sender

Reads iMessage history from macOS `chat.db` (briefings, CRM, winddowns) and sends
iMessages on Alex's behalf via Messages.app.

## Architecture — why there are two halves

Reading `chat.db` needs macOS **Full Disk Access (FDA)**, and FDA is granted per
**binary path**. The old setup had Claude Code shell out to `python3` directly, so
the process touching `chat.db` was attributed to *Claude Code's* binary — which
lives at a versioned path that changes on every CC update. Result: FDA silently
broke every time Claude Code updated.

The fix decouples **reading** from **consuming**:

- **`imessage-sync.py`** (the FDA half) runs under a **stable** interpreter,
  `/usr/bin/python3`, via the `com.exobrain.imessage-sync` launchd agent every 15
  minutes. It takes a consistent snapshot of `chat.db` (sqlite online-backup API,
  WAL-safe) into `cache/chat.db`, caches a `contacts.json` phone→name map, and
  writes `sync-status.json`. You grant FDA to `/usr/bin/python3` **once** and it
  survives every future Claude Code update.
- **`imessage-reader.py`** (the consuming half) reads `cache/chat.db` — an ordinary
  file, **no FDA needed**. Claude never touches the protected path.

`cache/` and `logs/` are gitignored (message snapshots + real contact names).

## One-time setup (Full Disk Access)

1. **System Settings → Privacy & Security → Full Disk Access**.
2. Click **+**, press **⌘⇧G**, enter `/usr/bin/python3`, add it, and toggle it ON.
   (This is Apple's own interpreter at a fixed path — it does not move on CC or
   Homebrew updates.)
3. Load + run the agent:
   ```bash
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.imessage-sync.plist
   launchctl kickstart -k gui/$(id -u)/com.exobrain.imessage-sync
   ```
4. Confirm it's healthy:
   ```bash
   python3 imessage-reader.py status   # -> "DB source: cache snapshot ... (fresh)"
   ```

If `status` ever shows STALE or an FDA error, re-check step 2 and kickstart again.
The `session-start` health check now monitors this job automatically: it WARNs on a
nonzero launchd exit code (with the FDA fix inline) and on a missing or stale
(`>6h`) cache snapshot, so this can no longer die silently. The launchd plist lives
at `imessage/com.exobrain.imessage-sync.plist` (tracked).

## Usage

```bash
# Read (from the synced cache — no FDA needed)
python3 imessage-reader.py status                          # DB source + cache freshness
python3 imessage-reader.py recent [--hours N] [--limit N]
python3 imessage-reader.py chat "Name or Phone" [--days N] [--limit N]
python3 imessage-reader.py list [--limit N]
python3 imessage-reader.py search "keyword" [--days N]
python3 imessage-reader.py unread
python3 imessage-reader.py dump [--hours N]                # full JSON dump to ~/My Drive/iMessage

# Send (every message is auto-signed)
python3 imessage-send.py "<recipient phone or email>" "<message>"
python3 imessage-send.py "<recipient>" -                   # read body from stdin
```

**DB source resolution** (reader): `$IMESSAGE_DB` → `cache/chat.db` → live
`~/Library/Messages/chat.db`. It only falls back to the live (FDA-requiring) path
if the cache doesn't exist yet.

## Signing rule

`imessage-send.py` automatically appends **`-Alex's Claude`** to every outgoing
message so recipients always know it's the assistant, not Alex personally. The
signature is enforced in code — don't bypass it by sending through raw osascript.
Outgoing messages to other people are outward-facing prose: humanize them
(no em dashes, run /de-ai) and confirm content before sending.

## Dependencies

None — stdlib only (`sqlite3`, `shutil`). Sender shells out to `osascript` +
`send-imessage.applescript`.
