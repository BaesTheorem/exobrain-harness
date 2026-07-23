#!/usr/bin/env python3
"""Resident MIST voice service. Loads XTTS-v2 once, caches MIST's speaker
latents, and synthesizes on request -- no 28s reload per call.

  uvicorn-free: just run it.   python scripts/serve.py [--device cpu|mps] [--port 8087]

  POST /say   {"text": "...", "speed": 1.0}  -> audio/wav  (MIST's voice)
  POST /stt   {"pcm16_8k": "<base64>"}        -> {"text": ...}  (phone STT, faster-whisper)
  GET  /health                                -> {"ok": true, "device": ...}

Used by the `mist-say` CLI and (later) the phone audio path.
"""
import os, glob, io, argparse, wave
os.environ.setdefault("COQUI_TOS_AGREED", "1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("TTS_HOME", os.path.join(ROOT, "models"))
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64, audioop, json
from TTS.api import TTS

REFS = sorted(glob.glob(os.path.join(ROOT, "samples", "reference", "*.wav")))
MODEL = None        # a TTS.api object -- SAME path as the approved demo
DEVICE = "cpu"
SR = 24000
_WHISPER = None  # lazy STT for the phone (/stt)


def stt(pcm16_8k: bytes) -> str:
    """Transcribe raw PCM16 mono 8kHz bytes (phone audio). Resamples to 16kHz."""
    global _WHISPER
    if _WHISPER is None:
        from faster_whisper import WhisperModel
        # distil-small.en: ~small.en accuracy at ~base.en latency. The right
        # trade for a live phone turn -- better words without slowing the reply.
        _WHISPER = WhisperModel(os.environ.get("PHONE_STT_MODEL", "distil-small.en"),
                                device="cpu", compute_type="int8")
    import numpy as np
    pcm16k, _ = audioop.ratecv(pcm16_8k, 2, 1, 8000, 16000, None)
    audio = np.frombuffer(pcm16k, dtype="<i2").astype("float32") / 32768.0
    # Each utterance is one independent phone turn -- don't condition on the
    # previous transcript, which invites repeated-phrase hallucinations.
    segs, _ = _WHISPER.transcribe(audio, language="en", vad_filter=True,
                                  condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segs).strip()

def load(device):
    """Load XTTS via the high-level TTS.api -- identical to the approved demo so
    the service voice matches it exactly (no hand-tuned sampling params)."""
    global MODEL, DEVICE
    DEVICE = device
    MODEL = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    print(f"[mist] ready on {device}; {len(REFS)} reference clips", flush=True)

def synth(text, speed=1.0):
    # Same call as scripts/say.py (the demo Alex approved): conditions on the
    # full reference set each time, all default XTTS sampling params.
    from pronounce import fix_pronunciation
    text = fix_pronunciation(text)
    wav = MODEL.tts(text=text, speaker_wav=REFS, language="en", speed=speed)
    import numpy as np
    pcm = (np.clip(np.asarray(wav, dtype="float32"), -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm)
    return buf.getvalue()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/health":
            self._json({"ok": MODEL is not None, "device": DEVICE})
        else: self.send_error(404)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        if self.path == "/say":
            data = synth(body["text"], float(body.get("speed", 1.0)))
            self.send_response(200); self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        elif self.path == "/stt":
            text = stt(base64.b64decode(body["pcm16_8k"]))   # phone STT
            self._json({"text": text})
        else:
            self.send_error(404)
    def _json(self, o):
        b = json.dumps(o).encode(); self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cpu", choices=["cpu", "mps"])
    ap.add_argument("--port", type=int, default=8087)
    args = ap.parse_args()
    load(args.device)
    print(f"[mist] serving on http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()
