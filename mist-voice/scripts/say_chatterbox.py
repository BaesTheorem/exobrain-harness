#!/usr/bin/env python3
"""Speak text in MIST's voice using Resemble AI's Chatterbox (MIT-licensed),
zero-shot cloned from a single reference clip.

  say_chatterbox.py "Hello Alex." [-o out.wav] [--play] [--device cpu|mps]
      [--ref PATH] [--exaggeration 0.5] [--cfg 0.5]

Track-A candidate to replace XTTS-v2 (scripts/say.py). Same reference clip
(samples/reference/06_need_your_help.wav), permissive license, emotion dial.
First run downloads the Chatterbox weights (~1GB) from HuggingFace.
"""
import sys, argparse, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REF = ROOT / "samples" / "reference" / "06_need_your_help.wav"
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text")
    ap.add_argument("-o", "--out", default=str(ROOT / "out_chatterbox.wav"))
    ap.add_argument("--play", action="store_true")
    ap.add_argument("--device", default="cpu", choices=["cpu", "mps"])
    ap.add_argument("--ref", default=str(DEFAULT_REF))
    ap.add_argument("--exaggeration", type=float, default=0.5,
                    help="emotion intensity 0.0-1.0+ (0.5 neutral; MIST likes a touch more)")
    ap.add_argument("--cfg", type=float, default=0.5,
                    help="cfg/pace weight; lower = slower, more deliberate")
    args = ap.parse_args()

    if not Path(args.ref).exists():
        sys.exit(f"No reference clip at {args.ref}")

    import torch, torchaudio as ta
    from chatterbox.tts import ChatterboxTTS
    from pronounce import fix_pronunciation

    # Chatterbox's checkpoints were saved on CUDA; remap to our device on load.
    if args.device != "cuda":
        _orig_load = torch.load
        def _load(*a, **k):
            k.setdefault("map_location", torch.device(args.device))
            return _orig_load(*a, **k)
        torch.load = _load

    model = ChatterboxTTS.from_pretrained(device=args.device)
    wav = model.generate(
        fix_pronunciation(args.text),
        audio_prompt_path=args.ref,
        exaggeration=args.exaggeration,
        cfg_weight=args.cfg,
    )
    ta.save(args.out, wav, model.sr)
    print(f"[ok] {args.out}  (chatterbox, ref={Path(args.ref).name}, "
          f"exag={args.exaggeration}, cfg={args.cfg})")
    if args.play:
        subprocess.run(["afplay", args.out])


if __name__ == "__main__":
    main()
