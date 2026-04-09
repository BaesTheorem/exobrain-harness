# iMessage Reader

Reads iMessage history from macOS `chat.db` for use in daily briefings, CRM updates, and evening winddowns.

## Requirements

- **Full Disk Access** must be granted to whichever terminal app runs this script (Terminal, iTerm, etc.) via System Settings > Privacy & Security > Full Disk Access.

## Usage

```bash
python3 imessage-reader.py recent [--hours N] [--limit N]
python3 imessage-reader.py chat "Name or Phone" [--days N] [--limit N]
python3 imessage-reader.py list [--limit N]
python3 imessage-reader.py search "keyword" [--days N]
python3 imessage-reader.py unread
```

## Dependencies

None — stdlib only.
