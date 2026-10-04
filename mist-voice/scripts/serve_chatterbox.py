#!/usr/bin/env python3
"""Resident Chatterbox voice service: MIST's cloned voice on Apple's MLX.

Chatterbox Turbo (Resemble AI, MIT) through mlx-audio, cloned zero-shot from
the same reference clip as XTTS. On this M1 a warm sentence takes about 1.2x
its own length to render, where XTTS on CPU takes about 1.6x. Same HTTP shape as
serve.py, so a caller swaps the port and nothing else.

  .venv-chatterbox/bin/python scripts/serve_chatterbox.py [--port 8088]

  POST /say   {"text": "..."}  -> audio/wav (24 kHz PCM16 mono)
  GET  /health                 -> {"ok": true, "model": ...}

Setup: uv venv --python 3.12 .venv-chatterbox
       uv pip install --python .venv-chatterbox/bin/python -r requirements-chatterbox.txt
The first start downloads the weights (~1.5 GB) to the Hugging Face cache.

INVARIANTS (do not break these in an edit):
  - The model and the speaker conditioning load ONCE at startup. A request
    never reloads either.
  - Port 8088 is the Console's default for this engine (MIST_CHATTERBOX_URL
    in mist-console/voice.py). Change both or neither.
  - One synthesis at a time (the lock). MLX on 8 GB of memory does not
    survive two concurrent generations.
"""
import argparse
import io
import json
import os
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
from mlx_audio.tts.utils import load

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pronounce import fix_pronunciation  # noqa: E402

REF = os.path.join(ROOT, "samples", "reference", "06_need_your_help.wav")
MODEL_ID = os.environ.get("MIST_CHATTERBOX_MODEL", "mlx-community/chatterbox-turbo-fp16")
MODEL = None
SR = 24000
_lock = threading.Lock()


def init():
    global MODEL, SR
    MODEL = load(MODEL_ID)
    MODEL.prepare_conditionals(REF)
    SR = int(getattr(MODEL, "sample_rate", SR))
    print(f"[chatterbox] ready: {MODEL_ID}, ref {os.path.basename(REF)}", flush=True)


def synth(text):
    assert MODEL is not None, "synth() called before init()"
    with _lock:
        parts = [np.asarray(r.audio, dtype="float32")
                 for r in MODEL.generate(fix_pronunciation(text))]
    audio = np.concatenate(parts) if parts else np.zeros(0, dtype="float32")
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm)
    return buf.getvalue()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/health":
            self._send(200, "application/json",
                       json.dumps({"ok": MODEL is not None, "model": MODEL_ID}).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/say":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        text = (body.get("text") or "").strip()
        if not text:
            self.send_error(400, "no text")
            return
        self._send(200, "audio/wav", synth(text))

    def _send(self, code, ctype, data):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8088)
    args = ap.parse_args()
    init()
    print(f"[chatterbox] serving on http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()
