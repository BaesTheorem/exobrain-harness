#!/usr/bin/env python3
"""Speak text in MIST's voice using an offline XTTS-v2 clone conditioned on the
reference set in samples/reference/.

  say.py "Hello Alex." [-o out.wav] [--play] [--speed 1.0] [--device cpu|mps]

Reference clips are auto-gathered from samples/reference/*.wav. First run
downloads the XTTS-v2 model (~1.8GB) under models/.
"""
import os, sys, argparse, glob, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF_DIR = ROOT / "samples" / "reference"
os.environ.setdefault("COQUI_TOS_AGREED", "1")
os.environ.setdefault("TTS_HOME", str(ROOT / "models"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("-o", "--out", default=str(ROOT / "out.wav"))
    ap.add_argument("--play", action="store_true")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--device", default="cpu", choices=["cpu", "mps"])
    args = ap.parse_args()

    refs = sorted(glob.glob(str(REF_DIR / "*.wav")))
    if not refs:
        sys.exit(f"No reference clips in {REF_DIR}. Build the sample pack first.")

    from TTS.api import TTS
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(args.device)
    tts.tts_to_file(
        text=args.text,
        speaker_wav=refs,
        language="en",
        speed=args.speed,
        file_path=args.out,
    )
    print(f"[ok] {args.out}  (conditioned on {len(refs)} reference clips)")
    if args.play:
        subprocess.run(["afplay", args.out])

if __name__ == "__main__":
    main()
