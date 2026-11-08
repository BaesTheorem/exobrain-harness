#!/usr/bin/env python3
"""Post a message to a Discord channel as MIST.

Reads DISCORD_BOT_TOKEN from ~/.claude/channels/discord/.env (the same token the
digest fetcher and the bot use) and POSTs over REST, so it does not need the
gateway connection the bot holds open.

Usage:
    discord-send.py <channel_id> "message text"
    discord-send.py <channel_id> --file path/to/message.txt
    discord-send.py <channel_id> "caption" --attach path/to/image.png

--attach uploads one file with the message (the caption must fit in one
message, 2000 characters).

Discord caps a message at 2000 characters; longer input is split on blank lines
and sent as consecutive messages.
"""
import json
import mimetypes
import os
import subprocess
import uuid
import sys
import urllib.error
import urllib.request

ENV_PATH = os.path.expanduser("~/.claude/channels/discord/.env")
API = "https://discord.com/api/v10"
LIMIT = 2000
RECORD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "claude-bot", "bin", "discord-record")


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


def record(channel_id, text, message_id=None, notify=False):
    """Copy a sent message into the bot's conversation log (best effort).
    Shelled out, not imported: top-level dirs are islands."""
    try:
        ppid = os.getppid()
        parent = subprocess.run(["ps", "-o", "command=", "-p", str(ppid)],
                                capture_output=True, text=True, timeout=5).stdout.split()
        # The calling script, skipping the shell or interpreter that runs it.
        skip = {"bash", "zsh", "sh", "env", "mist-launch"}
        source = os.environ.get("DISCORD_SEND_SOURCE") or next(
            (os.path.basename(w) for w in parent if "/" in w
             and os.path.basename(w) not in skip
             and not os.path.basename(w).lower().startswith("python")), "shell")
        cmd = [str(RECORD), "--channel", str(channel_id), "--source", source]
        if message_id:
            cmd += ["--message-id", str(message_id)]
        if notify:
            cmd.append("--notify")
        subprocess.run(cmd, input=text, text=True, capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001 -- the log must never fail a send
        pass


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


def send_file(token, channel_id, content, path):
    """One message with one attachment, as multipart/form-data."""
    boundary = uuid.uuid4().hex
    name = os.path.basename(path)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        blob = fh.read()
    payload = json.dumps({"content": content, "attachments": [{"id": 0, "filename": name}]})
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        f"Content-Type: application/json\r\n\r\n{payload}\r\n"
        f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="{name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + blob + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages",
        data=body,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "MIST (exobrain-harness, 1.0)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    channel_id = sys.argv[1]
    if len(sys.argv) == 5 and sys.argv[3] == "--attach":
        content = sys.argv[2].rstrip()
        if len(content) > LIMIT:
            raise SystemExit(f"caption is {len(content)} chars; the limit with --attach is {LIMIT}")
        try:
            msg = send_file(load_token(), channel_id, content, sys.argv[4])
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            raise SystemExit(f"HTTP {exc.code} from Discord: {body}") from exc
        print(f"sent {msg['id']} with {len(msg.get('attachments', []))} attachment(s)")
        record(channel_id, f"{content}\n[attachment: {os.path.basename(sys.argv[4])}]", msg["id"])
        return
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
        record(channel_id, piece, msg["id"])


if __name__ == "__main__":
    main()
