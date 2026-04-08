#!/usr/bin/env python3
"""
iMessage Reader for Exobrain
Reads chat.db (requires Full Disk Access on the terminal app).

Usage:
    python3 imessage-reader.py recent [--hours N] [--limit N]
    python3 imessage-reader.py chat "Chat Name or Phone" [--days N] [--limit N]
    python3 imessage-reader.py list [--limit N]
    python3 imessage-reader.py search "keyword" [--days N]
    python3 imessage-reader.py unread
"""

import sqlite3
import os
import sys
import argparse
from datetime import datetime, timedelta

DB_PATH = os.path.expanduser("~/Library/Messages/chat.db")
CONTACTS_DIR = os.path.expanduser("~/Library/Application Support/AddressBook/Sources")

# Apple's epoch: 2001-01-01 00:00:00 UTC
APPLE_EPOCH = datetime(2001, 1, 1)

# Global contact lookup cache: normalized_phone -> "First Last"
_CONTACTS = None


def _normalize_phone(number):
    """Strip non-digit chars, keep leading +."""
    if not number:
        return number
    digits = "".join(c for c in number if c.isdigit() or c == "+")
    # Ensure US numbers have +1 prefix for consistent matching
    if digits.startswith("1") and len(digits) == 11:
        digits = "+" + digits
    elif len(digits) == 10:
        digits = "+1" + digits
    return digits


def get_contacts():
    """Build a phone→name lookup from all AddressBook source databases."""
    global _CONTACTS
    if _CONTACTS is not None:
        return _CONTACTS
    _CONTACTS = {}
    if not os.path.isdir(CONTACTS_DIR):
        return _CONTACTS
    for source in os.listdir(CONTACTS_DIR):
        db_path = os.path.join(CONTACTS_DIR, source, "AddressBook-v22.abcddb")
        if not os.path.isfile(db_path):
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            rows = conn.execute("""
                SELECT p.ZFULLNUMBER, r.ZFIRSTNAME, r.ZLASTNAME
                FROM ZABCDPHONENUMBER p
                JOIN ZABCDRECORD r ON p.ZOWNER = r.Z_PK
                WHERE p.ZFULLNUMBER IS NOT NULL
            """).fetchall()
            for phone, first, last in rows:
                name = " ".join(filter(None, [first, last])) or None
                if name:
                    _CONTACTS[_normalize_phone(phone)] = name
            conn.close()
        except Exception:
            continue
    return _CONTACTS


def resolve_sender(identifier):
    """Resolve a phone number or email to a contact name, or return as-is."""
    if not identifier:
        return "?"
    contacts = get_contacts()
    normalized = _normalize_phone(identifier)
    return contacts.get(normalized, identifier)


def apple_ts_to_datetime(ts):
    """Convert Apple's CoreData timestamp (nanoseconds since 2001-01-01 UTC) to local datetime."""
    if ts is None or ts == 0:
        return None
    try:
        seconds = ts / 1_000_000_000
        # Timestamps are UTC-based; convert to local for display
        utc_dt = APPLE_EPOCH + timedelta(seconds=seconds)
        local_offset = datetime.now() - datetime.utcnow()
        return utc_dt + local_offset
    except (OverflowError, OSError):
        return None


def utc_cutoff_ts(hours=0, days=0):
    """Get an Apple-epoch nanosecond timestamp for N hours/days ago (UTC)."""
    cutoff = datetime.utcnow() - timedelta(hours=hours, days=days)
    return int((cutoff - APPLE_EPOCH).total_seconds() * 1_000_000_000)


def extract_body_text(blob):
    """Extract plain text from NSAttributedString / NSArchiver blob (attributedBody column).

    The blob is an NSKeyedArchiver/NSArchiver serialization. The text payload
    lives after the first 'NSString' marker with the following byte pattern:
        NSString <header bytes> 0x2b('+') <length encoding> <utf-8 text>
    Length encoding: 0x01 NN (1-byte), 0x81 NN (1-byte extended),
                     0x84 NNNNNNNN (4-byte LE), 0x85 NNNNNNNNNNNNNNNN (8-byte LE).
    Some messages use a simpler layout where text immediately follows '+' with a
    single length byte.
    """
    if not blob:
        return None
    try:
        idx = blob.find(b"NSString")
        if idx == -1:
            return None
        # Jump past 'NSString' and scan for the '+' (0x2b) marker that precedes the text.
        remaining = blob[idx + 8:]
        plus_idx = remaining.find(b"+")
        if plus_idx == -1 or plus_idx > 20:
            return None
        after_plus = remaining[plus_idx + 1:]
        # Decode length
        tag = after_plus[0]
        if tag == 0x81:
            # Extended 1-byte length: next 2 bytes, first is length
            length = after_plus[1]
            text_start = 2
        elif tag == 0x84:
            length = int.from_bytes(after_plus[1:5], "little")
            text_start = 5
        elif tag == 0x85:
            length = int.from_bytes(after_plus[1:9], "little")
            text_start = 9
        else:
            # Simple: tag itself is the length byte
            length = tag
            text_start = 1
        raw = after_plus[text_start : text_start + length]
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def get_db():
    if not os.path.exists(DB_PATH):
        print("Error: chat.db not found at", DB_PATH, file=sys.stderr)
        sys.exit(1)
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        if "authorization denied" in str(e) or "unable to open" in str(e):
            print("Error: Full Disk Access not granted.", file=sys.stderr)
            print("Go to: System Settings > Privacy & Security > Full Disk Access", file=sys.stderr)
            print("Add your terminal app / Claude Code and restart.", file=sys.stderr)
            sys.exit(1)
        raise


# ---------------------------------------------------------------------------
# Queries now select both `text` and `attributedBody` so we can fall back.
# `associated_message_type = 0` filters out tapbacks/reactions.
# ---------------------------------------------------------------------------

MSG_QUERY_COLS = """
    m.date as msg_date,
    m.text,
    m.attributedBody,
    m.is_from_me,
    m.service,
    h.id as sender_id,
    COALESCE(c.display_name, c.chat_identifier) as chat_name
"""

MSG_JOINS = """
    FROM message m
    LEFT JOIN handle h ON m.handle_id = h.ROWID
    LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
    LEFT JOIN chat c ON cmj.chat_id = c.ROWID
"""


def _row_text(row):
    """Return the best available text from a message row."""
    return row["text"] or extract_body_text(row["attributedBody"]) or ""


def list_chats(limit=30):
    """List recent chats with last message date."""
    conn = get_db()
    query = f"""
        SELECT
            c.ROWID,
            c.chat_identifier,
            c.display_name,
            c.service_name,
            MAX(m.date) as last_msg_date,
            COUNT(m.ROWID) as msg_count
        FROM chat c
        LEFT JOIN chat_message_join cmj ON c.ROWID = cmj.chat_id
        LEFT JOIN message m ON cmj.message_id = m.ROWID
        GROUP BY c.ROWID
        ORDER BY last_msg_date DESC
        LIMIT ?
    """
    rows = conn.execute(query, (limit,)).fetchall()
    print(f"{'Last Active':<20} {'Messages':>8}  {'Name/ID'}")
    print("-" * 70)
    for row in rows:
        dt = apple_ts_to_datetime(row["last_msg_date"])
        date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "unknown"
        raw_name = row["display_name"] or row["chat_identifier"]
        name = raw_name if row["display_name"] else resolve_sender(raw_name)
        print(f"{date_str:<20} {row['msg_count']:>8}  {name}")
    conn.close()


def get_messages_recent(hours=24, limit=100):
    """Get recent messages across all chats."""
    conn = get_db()
    cutoff = utc_cutoff_ts(hours=hours)
    query = f"""
        SELECT {MSG_QUERY_COLS}
        {MSG_JOINS}
        WHERE m.date > ?
            AND m.associated_message_type = 0
            AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL)
        ORDER BY m.date ASC
        LIMIT ?
    """
    rows = conn.execute(query, (cutoff, limit)).fetchall()
    _print_messages(rows)
    conn.close()


def get_messages_chat(chat_query, days=7, limit=100):
    """Get messages from a specific chat by name or phone number."""
    conn = get_db()
    cutoff = utc_cutoff_ts(days=days)
    chat_search = f"%{chat_query}%"
    query = f"""
        SELECT {MSG_QUERY_COLS}
        {MSG_JOINS}
        WHERE (c.display_name LIKE ? OR c.chat_identifier LIKE ? OR h.id LIKE ?)
            AND m.date > ?
            AND m.associated_message_type = 0
            AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL)
        ORDER BY m.date ASC
        LIMIT ?
    """
    rows = conn.execute(query, (chat_search, chat_search, chat_search, cutoff, limit)).fetchall()
    if not rows:
        print(f"No messages found matching '{chat_query}' in the last {days} days.")
    else:
        _print_messages(rows)
    conn.close()


def search_messages(keyword, days=30):
    """Search message text across all chats."""
    conn = get_db()
    cutoff = utc_cutoff_ts(days=days)
    # Pull all messages in range and filter in Python (attributedBody is binary,
    # so SQL LIKE doesn't reliably search within the serialized text).
    query = f"""
        SELECT {MSG_QUERY_COLS}
        {MSG_JOINS}
        WHERE m.date > ?
            AND m.associated_message_type = 0
            AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL)
        ORDER BY m.date DESC
    """
    rows = conn.execute(query, (cutoff,)).fetchall()
    keyword_lower = keyword.lower()
    matches = [r for r in rows if keyword_lower in (_row_text(r) or "").lower()][:50]
    if not matches:
        print(f"No messages containing '{keyword}' in the last {days} days.")
    else:
        _print_messages(matches)
    conn.close()


def get_unread():
    """Show chats where the most recent message is not from you (last 48h)."""
    conn = get_db()
    cutoff = utc_cutoff_ts(hours=48)
    query = f"""
        SELECT
            c.ROWID as chat_rowid,
            COALESCE(c.display_name, c.chat_identifier) as chat_name,
            m.date as msg_date,
            m.text,
            m.attributedBody,
            m.is_from_me,
            h.id as sender_id
        {MSG_JOINS}
        WHERE m.date > ?
            AND m.associated_message_type = 0
            AND (m.text IS NOT NULL OR m.attributedBody IS NOT NULL)
        ORDER BY c.ROWID, m.date ASC
    """
    rows = conn.execute(query, (cutoff,)).fetchall()

    chats = {}
    for row in rows:
        cid = row["chat_rowid"]
        if cid not in chats:
            chats[cid] = {"name": row["chat_name"], "messages": []}
        chats[cid]["messages"].append(row)

    unanswered = []
    for cid, data in chats.items():
        last_msg = data["messages"][-1]
        if not last_msg["is_from_me"]:
            unanswered.append({
                "chat": data["name"],
                "last_msg": last_msg,
                "count_since_reply": sum(
                    1 for m in reversed(data["messages"])
                    if not m["is_from_me"]
                ),
            })

    if not unanswered:
        print("No unanswered messages in the last 48 hours.")
    else:
        print(f"Unanswered chats ({len(unanswered)}):\n")
        for item in unanswered:
            dt = apple_ts_to_datetime(item["last_msg"]["msg_date"])
            date_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "unknown"
            sender = resolve_sender(item["last_msg"]["sender_id"] or "unknown")
            text = (
                item["last_msg"]["text"]
                or extract_body_text(item["last_msg"]["attributedBody"])
                or ""
            )[:200]
            print(f"[{item['chat']}] ({item['count_since_reply']} msg waiting)")
            print(f"  Last from: {sender} at {date_str}")
            print(f"  > {text}")
            print()
    conn.close()


def _print_messages(rows):
    current_chat = None
    for row in rows:
        raw_chat = row["chat_name"] or "Unknown"
        chat = resolve_sender(raw_chat) if raw_chat.startswith("+") else raw_chat
        if chat != current_chat:
            print(f"\n{'=' * 60}")
            print(f"  {chat}")
            print(f"{'=' * 60}")
            current_chat = chat

        dt = apple_ts_to_datetime(row["msg_date"])
        time_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "?"
        sender = "Me" if row["is_from_me"] else resolve_sender(row["sender_id"])
        text = _row_text(row)
        if text:
            print(f"[{time_str}] {sender}: {text}")


def main():
    parser = argparse.ArgumentParser(description="iMessage Reader for Exobrain")
    subparsers = parser.add_subparsers(dest="command")

    p_recent = subparsers.add_parser("recent", help="Recent messages across all chats")
    p_recent.add_argument("--hours", type=int, default=24)
    p_recent.add_argument("--limit", type=int, default=100)

    p_chat = subparsers.add_parser("chat", help="Messages from a specific chat")
    p_chat.add_argument("query", help="Chat name or phone number to search for")
    p_chat.add_argument("--days", type=int, default=7)
    p_chat.add_argument("--limit", type=int, default=100)

    p_list = subparsers.add_parser("list", help="List recent chats")
    p_list.add_argument("--limit", type=int, default=30)

    p_search = subparsers.add_parser("search", help="Search message text")
    p_search.add_argument("keyword", help="Text to search for")
    p_search.add_argument("--days", type=int, default=30)

    subparsers.add_parser("unread", help="Show unanswered messages (last 48h)")

    args = parser.parse_args()

    if args.command == "recent":
        get_messages_recent(hours=args.hours, limit=args.limit)
    elif args.command == "chat":
        get_messages_chat(args.query, days=args.days, limit=args.limit)
    elif args.command == "list":
        list_chats(limit=args.limit)
    elif args.command == "search":
        search_messages(args.keyword, days=args.days)
    elif args.command == "unread":
        get_unread()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
