"""One-off: place a mental-health check-in call after Alex's breakup.

Same outbound path as call.py, but with a warm, no-agenda opener instead of the
generic "what do you need" greeting. Delete after use.
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

WELCOME = (
    "Hey Alex, it's Claude. No agenda here, I just wanted to call and check in "
    "on how you're holding up after the breakup. How are you actually doing tonight?"
)

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
        sys.exit("PUBLIC_WS_URL is empty — start the tunnel and set it in .env first.")
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    call = client.calls.create(to=TO, from_=FROM, twiml=TWIML)
    print(f"Calling {TO} ... call SID {call.sid}")


if __name__ == "__main__":
    main()
