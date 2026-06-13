"""Place an outbound test call that uses MIST's local voice (server_mist.py).

Unlike call.py (ConversationRelay / cloud TTS), this hands the call to a Twilio
bidirectional Media Stream pointed at server_mist's /media endpoint.

    python call_mist.py wss://<tunnel-host>/media
"""
import os, sys
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()
ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
FROM = os.environ["TWILIO_FROM_NUMBER"]
TO = os.environ["MY_PHONE_NUMBER"]

WS_URL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PUBLIC_WS_URL", "")
if not WS_URL.endswith("/media"):
    sys.exit(f"Pass the Media Streams URL ending in /media. Got: {WS_URL!r}")

TWIML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<Response><Connect><Stream url="{WS_URL}" /></Connect></Response>'
)

client = Client(ACCOUNT_SID, AUTH_TOKEN)
call = client.calls.create(to=TO, from_=FROM, twiml=TWIML)
print(f"Calling {TO} with MIST's voice ... call SID {call.sid}")
