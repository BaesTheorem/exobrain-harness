# Phone with MIST's voice (`server_mist.py`)

Same Exobrain brain + PIN security as `server.py`, but the audio path is fully
local so the voice on the call is **MIST's offline clone** instead of Twilio's
cloud TTS.

```
You (phone) <--audio--> Twilio Media Streams <--mulaw/WS--> server_mist.py
   inbound  -> faster-whisper (STT service) -> Claude Agent SDK (brain)
   outbound -> Claude text -> MIST XTTS (TTS service) -> mulaw -> phone
```

`server.py` (cloud ConversationRelay voice) is untouched and still works -- this
is a parallel server you opt into.

## Architecture: why two services

- **The phone venv is Python 3.14**; `audioop` (mu-law transcoding) was removed
  in 3.13, so `server_mist` uses the `audioop-lts` backport.
- **STT + TTS run in `mist-voice/.venv` (3.12)** as one HTTP service
  (`mist-voice/scripts/serve.py`) -- faster-whisper for `/stt`, XTTS for `/say`.
  Keeps the heavy models in their own process and out of the phone venv.

## Latency -- read this

Measured on this M1/8GB: XTTS is ~1.6-1.8x slower than real-time and STT adds a
beat. MIST **starts a turn after a noticeable delay** and we sentence-pipeline so
she keeps talking, but it is **not snappy** on this hardware, and both models
resident pressures 8GB RAM. This is the known tradeoff of going local on this box
(see `mist-voice/README.md`). A beefier Mac mini / GPU would fix it.

## Run it

```bash
# 1) voice service (XTTS + whisper), from repo root -- first run downloads models
mist-voice/.venv/bin/python mist-voice/scripts/serve.py --port 8087 &

# 2) the MIST phone server
cd phone
.venv/bin/pip install -r requirements.txt          # adds audioop-lts
.venv/bin/uvicorn server_mist:app --host 0.0.0.0 --port 8080 &

# 3) public tunnel, then point Twilio at /media
cloudflared tunnel --url http://localhost:8080
#   set in .env:  PUBLIC_WS_URL=wss://<host>/media   (note /media, not /ws)
#   restart server_mist so /twiml emits the new URL

# 4) call.py must hit this server's /twiml (it already posts TwiML on dial)
.venv/bin/python call.py
```

## Validated offline

`/tmp` round-trip test passed: text -> MIST TTS -> mu-law 8kHz frames -> decode
-> STT returned the sentence near-verbatim. The only unproven layer is the live
Twilio Media Streams transport -- that needs a real call.

## Still to verify on a live call

- Barge-in (talk over MIST -> she stops): `clear` is sent on inbound energy.
- End-of-utterance timing (`SILENCE_END_MS`) feels right vs. clips you off.
- DTMF PIN unlock still gates mutations.
- RAM headroom with XTTS + whisper + agent all live.
