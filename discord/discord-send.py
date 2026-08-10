#!/usr/bin/env python3
"""Post a message to a Discord channel as MIST.

Reads DISCORD_BOT_TOKEN from ~/.claude/channels/discord/.env (the same token the
digest fetcher and the bot use) and POSTs over REST, so it does not need the
gateway connection the bot holds open.

Usage:
    discord-send.py <channel_id> "message text"
    discord-send.py <channel_id> --file path/to/message.txt

Discord caps a message at 2000 characters; longer input is split on blank lines
and sent as consecutive messages.
"""
import json
import os
import sys
import urllib.error
import urllib.request

ENV_PATH = os.path.expanduser("~/.claude/channels/discord/.env")
API = "https://discord.com/api/v10"
LIMIT = 2000


def load_token():
    with open(ENV_PATH) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit(f"DISCORD_BOT_TOKEN not found in {ENV_PATH}")


def chunk(text):
    """Split into <=LIMIT pieces, preferring paragraph then line boundaries."""
    if len(text) <= LIMIT:
        return [text]
    out, buf = [], ""
    for para in text.split("\n\n"):
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) <= LIMIT:
            buf = candidate
            continue
        if buf:
            out.append(buf)
        while len(para) > LIMIT:
            cut = para.rfind("\n", 0, LIMIT)
            cut = cut if cut > 0 else LIMIT
            out.append(para[:cut])
            para = para[cut:].lstrip("\n")
        buf = para
    if buf:
        out.append(buf)
    return out


def send(token, channel_id, content):
    req = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages",
        data=json.dumps({"content": content}).encode(),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "MIST (exobrain-harness, 1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    channel_id = sys.argv[1]
    if sys.argv[2] == "--file":
        with open(sys.argv[3]) as fh:
            content = fh.read()
    else:
        content = sys.argv[2]
    content = content.rstrip()
    if not content:
        raise SystemExit("nothing to send")

    token = load_token()
    for piece in chunk(content):
        try:
            msg = send(token, channel_id, piece)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise SystemExit(f"HTTP {exc.code} from Discord: {body}") from exc
        print(f"sent {msg['id']} ({len(piece)} chars)")


if __name__ == "__main__":
    main()
