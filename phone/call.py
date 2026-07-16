"""
Place an outbound call: Claude rings your phone and starts talking.

Prereqs (see README.md):
    - server.py running and exposed via cloudflared
    - PUBLIC_WS_URL in .env pointing at the cloudflared wss URL (/ws)
    - Twilio + Anthropic creds in .env

Usage:
    python call.py
"""
import os
import sys

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
FROM = os.environ["TWILIO_FROM_NUMBER"]
TO = os.environ["MY_PHONE_NUMBER"]
WS_URL = os.environ["PUBLIC_WS_URL"]
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "Amazon")
TTS_VOICE = os.environ.get("TTS_VOICE", "Matthew-Neural")

WELCOME = "Hey Alex, it's Claude. I've got your Exobrain in front of me. What do you need?"

# Inline TwiML: hand the call straight to ConversationRelay -> our WebSocket.
# dtmfDetection lets you key in the PIN to unlock write actions.
TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Response><Connect>"
    f'<ConversationRelay url="{WS_URL}" welcomeGreeting="{WELCOME}" '
    f'ttsProvider="{TTS_PROVIDER}" voice="{TTS_VOICE}" '
    'dtmfDetection="true" interruptible="true" />'
    "</Connect></Response>"
)


def main():
    if not WS_URL:
        sys.exit("PUBLIC_WS_URL is empty: start cloudflared and set it in .env first.")
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    call = client.calls.create(to=TO, from_=FROM, twiml=TWIML)
    print(f"Calling {TO} ... call SID {call.sid}")


if __name__ == "__main__":
    main()
