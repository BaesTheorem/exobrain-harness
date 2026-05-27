#!/usr/bin/env python3
"""
iMessage Sender for Exobrain.

Sends an iMessage via Messages.app (AppleScript bridge). EVERY outgoing message
is automatically signed so recipients always know it came from the assistant and
not Alex personally. The signature is enforced here in code, not left to the
caller to remember.

Requires:
  - Messages.app signed in to iMessage.
  - Automation permission for the terminal/osascript to control Messages
    (macOS prompts on first run).

Usage:
    python3 imessage-send.py "<recipient phone or email>" "<message>"
    python3 imessage-send.py "<recipient>" -      # read message body from stdin
"""
import subprocess
import sys
from pathlib import Path

SIGNATURE = "-Alex's Claude"
SCRIPT = Path(__file__).resolve().parent / "send-imessage.applescript"


def sign(body: str) -> str:
    """Append the signature unless it's already present."""
    body = body.rstrip()
    if SIGNATURE in body:
        return body
    return f"{body}\n\n{SIGNATURE}"


def send(recipient: str, body: str) -> None:
    message = sign(body)
    result = subprocess.run(
        ["osascript", str(SCRIPT), recipient, message],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"Send failed: {result.stderr.strip() or 'unknown error'}")
    print(f"Sent to {recipient} (signed '{SIGNATURE}')")


def main():
    if len(sys.argv) < 3:
        sys.exit('Usage: imessage-send.py "<recipient>" "<message>"  (use - for stdin)')
    recipient, body = sys.argv[1], sys.argv[2]
    if body == "-":
        body = sys.stdin.read()
    send(recipient, body)


if __name__ == "__main__":
    main()
