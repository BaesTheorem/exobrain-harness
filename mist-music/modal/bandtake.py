"""bandtake: give a score render to the ACE-Step cover model and get the tune back as a band recording.

The cover task reads the melody, rhythm and form from the source audio and takes
the instruments from the style tags. So a clean render from celtic.py (or any
MIDI render) becomes a take that sounds recorded. The model is free to change
notes, so check each take with `modal-cover check` before you call it a cover
in the target scale.

Run it with the mist-music venv, which has gradio_client:

    mist-music/.venv/bin/python mist-music/modal/bandtake.py health
    mist-music/.venv/bin/python mist-music/modal/bandtake.py take SOURCE.mp3 "irish reel, tin whistle, fiddle" -o OUT.mp3

It uses the backend that MIST Studio is set to (studio/config.json): the free
Space, where one take reserves about 180 s of the daily ZeroGPU pool, or a
self-hosted server. Exit status 3 means the quota is spent; the message gives
the time until it refills.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio import config as studio_config  # noqa: E402  (the mist-music folder, on the path from the line above)
from studio.engine import EngineError, GenRequest, QuotaError, build_engine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="ACE-Step cover of a score render")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health", help="read the backend's parameter list and report drift; uses no GPU")
    t = sub.add_parser("take", help="one cover take")
    t.add_argument("source", type=Path)
    t.add_argument("tags", help="style tags: genre, instruments, mood (a comma list, not a sentence)")
    t.add_argument("-o", "--output", type=Path, required=True)
    t.add_argument("--strength", type=float, default=1.0, help="how long the source steers the take, 0..1")
    t.add_argument("--bpm", type=float, default=0.0)
    t.add_argument("--key", default="", help="a key hint. The model knows major and minor only: for a mode, "
                                             "leave it empty or name the minor key with the same notes")
    t.add_argument("--steps", type=int, default=8)
    t.add_argument("--seed", type=int)
    t.add_argument("--model", default="", help="acestep-v15-xl-turbo (default) or acestep-v15-turbo")
    args = ap.parse_args()

    engine = build_engine(studio_config.load(), studio_config.hf_token())
    if args.cmd == "health":
        print(engine.health())
        return 0
    req = GenRequest(task="cover", caption=args.tags, instrumental=True, bpm=args.bpm, key_scale=args.key,
                     time_signature="4", src_audio=str(args.source.resolve()), cover_strength=args.strength,
                     steps=args.steps, seed=args.seed)
    if args.model:
        req.model = args.model
    seen = ""

    def progress(p: dict) -> None:
        nonlocal seen
        key = f"{p.get('stage')} {p.get('detail')}"
        if key != seen:
            print(f"{key} (queue rank {p.get('rank')}, {p.get('elapsed')} s)", flush=True)
            seen = key

    try:
        res = engine.generate(req, progress)
    except QuotaError as e:
        print(f"QUOTA: {e} (retry in {e.retry_in} s)")
        return 3
    except EngineError as e:
        print(f"FAILED: {e}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(res.audio_paths[0], args.output)
    print(f"wrote {args.output}  seeds {res.seeds}  {res.status[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
