"""
MIST-voice phone brain -- Twilio Media Streams edition.

Same Exobrain brain, PIN security, and caller-trust as server.py, but the audio
path is fully LOCAL so the voice on the phone is MIST's offline clone:

    You (phone) <--audio--> Twilio Media Streams <--mulaw/WS--> server_mist.py
        inbound  -> faster-whisper (local STT) -> Agent SDK (brain)
        outbound -> Claude text -> MIST XTTS service -> mulaw -> phone

Latency note (measured on this M1): XTTS runs ~1.6-1.8x slower than real-time, so
MIST starts a turn after a short delay and we sentence-pipeline to keep her
talking. It is NOT gapless on this hardware -- see mist-voice/README.

Run:
    # 1) MIST voice service (XTTS) -- separate process, keeps the model resident
    ../mist-voice/.venv/bin/python ../mist-voice/scripts/serve.py --port 8087 &
    # 2) this server
    .venv/bin/uvicorn server_mist:app --host 0.0.0.0 --port 8080
    # 3) public tunnel -> set PUBLIC_WS_URL=wss://<host>/media in .env, restart
    cloudflared tunnel --url http://localhost:8080
    # 4) place the call
    .venv/bin/python call.py
"""
import os
import re
import json
import base64
import asyncio
import audioop
import urllib.request

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from claude_agent_sdk import ResultMessage, StreamEvent

# Reuse the brain, security gate, and config from the ConversationRelay server.
from server import (
    start_agent, VOICE_PIN, PUBLIC_WS_URL,
)

load_dotenv()

MIST_TTS_URL = os.environ.get("MIST_TTS_URL", "http://127.0.0.1:8087/say")
MIST_STT_URL = os.environ.get("MIST_STT_URL", "http://127.0.0.1:8087/stt")
WELCOME = os.environ.get(
    "MIST_WELCOME",
    "Hey Alex, it's MIST. I've got your Exobrain right here. What do you need?",
)

app = FastAPI()

# --- audio constants (Twilio Media Streams = 8kHz mono mu-law, 20ms frames) ----
TW_RATE = 8000
FRAME_MS = 20
FRAME_BYTES_ULAW = int(TW_RATE * FRAME_MS / 1000)   # 160 bytes mu-law / 20ms
SILENCE_END_MS = 700                                 # end-of-utterance gap
MIN_SPEECH_MS = 250                                  # ignore blips

# ====================== inbound: mu-law -> text (STT service) ==================
class Utterance:
    """Energy/VAD-lite segmenter over inbound mu-law frames. Buffers PCM16 8kHz
    during speech; flush() returns the utterance when a silence gap closes it."""
    def __init__(self):
        self.buf = bytearray()
        self.speech_ms = 0
        self.silence_ms = 0
        self.in_speech = False

    def add(self, ulaw: bytes):
        """Feed one ~20ms mu-law frame. Returns PCM16 bytes if an utterance just
        ended, else None."""
        pcm = audioop.ulaw2lin(ulaw, 2)                 # mu-law -> PCM16 8kHz
        rms = audioop.rms(pcm, 2)
        voiced = rms > 500                              # simple energy gate
        if voiced:
            self.in_speech = True
            self.speech_ms += FRAME_MS
            self.silence_ms = 0
            self.buf += pcm
        elif self.in_speech:
            self.silence_ms += FRAME_MS
            self.buf += pcm                             # keep trailing silence
            if self.silence_ms >= SILENCE_END_MS:
                done = bytes(self.buf) if self.speech_ms >= MIN_SPEECH_MS else None
                self.__init__()
                return done
        return None


def transcribe(pcm16_8k: bytes) -> str:
    """Send PCM16 8kHz to the local STT service (faster-whisper in the 3.12 env)."""
    req = urllib.request.Request(
        MIST_STT_URL, method="POST",
        data=json.dumps({"pcm16_8k": base64.b64encode(pcm16_8k).decode()}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("text", "").strip()


# ====================== outbound: text -> mu-law (MIST XTTS) ====================
def mist_wav(text: str) -> bytes:
    req = urllib.request.Request(
        MIST_TTS_URL, method="POST",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def wav_to_ulaw_frames(wav_bytes: bytes):
    """WAV (24kHz mono PCM16 from XTTS) -> list of 20ms mu-law frames @ 8kHz.

    Uses ffmpeg's high-quality resampler with an anti-alias lowpass (telephone
    band) + a small presence lift, instead of audioop.ratecv whose crude
    downsample aliased into a raspy 'smoker' artifact."""
    import subprocess
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-af", "highpass=f=80,lowpass=f=3400,equalizer=f=2200:t=q:w=1.4:g=3,dynaudnorm=g=7",
         "-ar", str(TW_RATE), "-ac", "1", "-f", "mulaw", "pipe:1"],
        input=wav_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    ulaw = proc.stdout
    return [ulaw[i:i + FRAME_BYTES_ULAW] for i in range(0, len(ulaw), FRAME_BYTES_ULAW)]


async def stream_speech(ws, stream_sid, text, session):
    """Synthesize `text` with MIST and stream it to Twilio, pacing ~realtime so
    barge-in stays responsive. Returns early if the caller starts talking."""
    loop = asyncio.get_event_loop()
    wav = await loop.run_in_executor(None, mist_wav, text)
    frames = wav_to_ulaw_frames(wav)
    session["speaking"] = True
    try:
        for fr in frames:
            if session.get("barge") or session.get("closed"):   # interrupted / call ended
                if not session.get("closed"):
                    await ws.send_text(json.dumps({"event": "clear", "streamSid": stream_sid}))
                return
            await ws.send_text(json.dumps({
                "event": "media", "streamSid": stream_sid,
                "media": {"payload": base64.b64encode(fr).decode()},
            }))
            await asyncio.sleep(FRAME_MS / 1000)        # pace playback
    except (WebSocketDisconnect, RuntimeError):
        session["closed"] = True                        # socket closed mid-send
    finally:
        session["speaking"] = False


# sentence chunker so we can synth+send as Claude streams, not after it finishes
SENT_END = re.compile(r"(.+?[.!?])(\s+|$)", re.S)
def pop_sentences(buf: str):
    out = []
    while True:
        m = SENT_END.match(buf)
        if not m:
            break
        out.append(m.group(1).strip()); buf = buf[m.end():]
    return out, buf


async def speak_turn(ws, stream_sid, session, user_text: str):
    """Run one agent turn; stream MIST audio sentence-by-sentence as it generates."""
    if session.get("client") is None:                 # brain still booting
        task = session.get("client_task")
        if task:
            await task
    client = session["client"]
    await client.query(user_text, session_id="phone")
    pending = ""
    spoke_filler = False
    async for message in client.receive_response():
        if session.get("barge"):
            try: await client.interrupt()
            except Exception: pass
            break
        if isinstance(message, StreamEvent):
            ev = message.event or {}
            if ev.get("type") == "content_block_delta":
                d = ev.get("delta", {})
                if d.get("type") == "text_delta":
                    pending += d.get("text", "")
                    sents, pending = pop_sentences(pending)
                    for s in sents:
                        if s:
                            await stream_speech(ws, stream_sid, s, session)
            elif ev.get("type") == "content_block_start":
                blk = ev.get("content_block", {})
                if blk.get("type") == "tool_use" and not spoke_filler:
                    spoke_filler = True
                    await stream_speech(ws, stream_sid, "One moment.", session)
        elif isinstance(message, ResultMessage):
            break
    if pending.strip():
        await stream_speech(ws, stream_sid, pending.strip(), session)


# ============================== TwiML + WS endpoint =============================
def twiml_response() -> Response:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<Stream url="{PUBLIC_WS_URL}" />'
        "</Connect></Response>"
    )
    return Response(content=xml, media_type="text/xml")


@app.get("/twiml")
@app.post("/twiml")
async def twiml():
    return twiml_response()


@app.websocket("/media")
async def media(ws: WebSocket):
    await ws.accept()
    session = {"authed": False, "pin": "", "client": None, "caller_allowed": False,
               "speaking": False, "barge": False, "closed": False}
    stream_sid = None
    utt = Utterance()
    busy = False  # a turn is being processed

    async def handle_user_text(text: str):
        nonlocal busy
        text = text.strip()
        if not text:
            return
        # PIN spoken as digits (keypad DTMF also handled below)
        if not session["authed"] and VOICE_PIN and VOICE_PIN in re.sub(r"\D", "", text):
            session["authed"] = True
            await stream_speech(ws, stream_sid, "Got it, you're unlocked. What next?", session)
            return
        busy = True
        session["barge"] = False
        try:
            await speak_turn(ws, stream_sid, session, text)
        finally:
            busy = False

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            ev = msg.get("event")

            if ev == "start":
                stream_sid = msg["start"]["streamSid"]
                # Outbound-only deployment (call.py dials Alex), so the caller is
                # trusted for reads. The PIN still gates every mutating tool.
                session["caller_allowed"] = True
                # Boot the brain in the background so the greeting plays right
                # away instead of 10-30s of dead air while MCP servers start.
                async def _boot():
                    session["client"] = await start_agent(session)
                session["client_task"] = asyncio.create_task(_boot())
                await stream_speech(ws, stream_sid, WELCOME, session)

            elif ev == "media":
                payload = base64.b64decode(msg["media"]["payload"])
                # barge-in: caller speaks while MIST is talking
                if session.get("speaking"):
                    pcm = audioop.ulaw2lin(payload, 2)
                    if audioop.rms(pcm, 2) > 800:
                        session["barge"] = True
                if busy:
                    continue
                done = utt.add(payload)
                if done is not None:
                    text = await asyncio.get_event_loop().run_in_executor(None, transcribe, done)
                    if text:
                        asyncio.create_task(handle_user_text(text))

            elif ev == "dtmf":
                digit = msg.get("dtmf", {}).get("digit", "")
                if not session["authed"] and VOICE_PIN:
                    session["pin"] += digit
                    if session["pin"].endswith(VOICE_PIN):
                        session["authed"] = True
                        await stream_speech(ws, stream_sid, "Got it, you're unlocked. What next?", session)

            elif ev == "stop":
                break

    except WebSocketDisconnect:
        pass
    finally:
        session["closed"] = True            # stop any in-flight stream_speech
        client = session.get("client")
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
