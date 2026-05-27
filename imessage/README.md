# iMessage Reader + Sender

Reads iMessage history from macOS `chat.db` (briefings, CRM, winddowns) and sends
iMessages on Alex's behalf via Messages.app.

## Requirements

- **Reader:** Full Disk Access for the terminal app running the script (System
  Settings > Privacy & Security > Full Disk Access).
- **Sender:** Messages.app signed in to iMessage, and Automation permission for
  the terminal/osascript to control Messages (macOS prompts on first send).

## Usage

```bash
# Read
python3 imessage-reader.py recent [--hours N] [--limit N]
python3 imessage-reader.py chat "Name or Phone" [--days N] [--limit N]
python3 imessage-reader.py list [--limit N]
python3 imessage-reader.py search "keyword" [--days N]
python3 imessage-reader.py unread

# Send (every message is auto-signed "-Alex's Claude")
python3 imessage-send.py "<recipient phone or email>" "<message>"
python3 imessage-send.py "<recipient>" -      # read body from stdin
```

## Signing rule

`imessage-send.py` automatically appends **`-Alex's Claude`** to every outgoing
message so recipients always know it's the assistant, not Alex personally. The
signature is enforced in code — don't bypass it by sending through raw osascript.
Outgoing messages to other people are outward-facing prose: humanize them
(no em dashes, run /de-ai) and confirm content before sending.

## Dependencies

None — stdlib only. Sender shells out to `osascript` + `send-imessage.applescript`.
