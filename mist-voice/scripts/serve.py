#!/usr/bin/env python3
"""Resident MIST voice service. Loads XTTS-v2 once, caches MIST's speaker
latents, and synthesizes on request — no 28s reload per call.

  uvicorn-free: just run it.   python scripts/serve.py [--device cpu|mps] [--port 8087]

  POST /say   {"text": "...", "speed": 1.0}  -> audio/wav  (MIST's voice)
  GET  /health                                -> {"ok": true, "device": ...}

Used by the `mist-say` CLI and (later) the phone audio path.
"""
import os, glob, io, argparse, wave
os.environ.setdefault("COQUI_TOS_AGREED", "1")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("TTS_HOME", os.path.join(ROOT, "models"))
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json, torch
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts

REFS = sorted(glob.glob(os.path.join(ROOT, "samples", "reference", "*.wav")))
MODEL = None
GPT_LATENT = None
SPK_EMB = None
SR = 24000

def load(device):
    """Load XTTS and precompute MIST's conditioning latents once."""
    global MODEL, GPT_LATENT, SPK_EMB
    from TTS.utils.manage import ModelManager
    mdir = ModelManager().download_model("tts_models/multilingual/multi-dataset/xtts_v2")[0]
    cfg = XttsConfig(); cfg.load_json(os.path.join(mdir, "config.json"))
    MODEL = Xtts.init_from_config(cfg)
    MODEL.load_checkpoint(cfg, checkpoint_dir=mdir, use_deepspeed=False)
    MODEL.to(device)
    GPT_LATENT, SPK_EMB = MODEL.get_conditioning_latents(audio_path=REFS)
    print(f"[mist] ready on {device}; {len(REFS)} reference clips cached", flush=True)

def synth(text, speed=1.0):
    out = MODEL.inference(text, "en", GPT_LATENT, SPK_EMB, speed=speed, temperature=0.65)
    wav = out["wav"]
    buf = io.BytesIO()
    import numpy as np
    pcm = (np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm)
    return buf.getvalue()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == "/health":
            self._json({"ok": MODEL is not None, "device": str(next(MODEL.parameters()).device) if MODEL else None})
        else: self.send_error(404)
    def do_POST(self):
        if self.path != "/say": return self.send_error(404)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        data = synth(body["text"], float(body.get("speed", 1.0)))
        self.send_response(200); self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
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
