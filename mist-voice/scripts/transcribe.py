#!/usr/bin/env python3
"""Transcribe an audio file to timestamped segments so we can locate MIST-only
windows by content. Writes <input>.segments.tsv (start  end  text) next to a
readable transcript. CPU int8 -- fine on M1/8GB.

Usage: transcribe.py <audio.wav> [--model distil-medium.en]
"""
import sys, json, argparse
from pathlib import Path
from faster_whisper import WhisperModel

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    # Batch, one-off, latency-insensitive -- so spend the cycles on accuracy.
    # distil-medium.en beats small.en clearly and still fits an 8GB M1 at int8.
    ap.add_argument("--model", default="distil-medium.en")
    args = ap.parse_args()

    src = Path(args.audio)
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(src), vad_filter=True,
                                      vad_parameters=dict(min_silence_duration_ms=400))

    tsv = src.with_suffix(".segments.tsv")
    rows = []
    with tsv.open("w") as f:
        f.write("start\tend\tdur\ttext\n")
        for s in segments:
            dur = s.end - s.start
            line = f"{s.start:.2f}\t{s.end:.2f}\t{dur:.2f}\t{s.text.strip()}"
            f.write(line + "\n")
            rows.append(line)
            print(line)
    print(f"\n[ok] {len(rows)} segments -> {tsv}", file=sys.stderr)

if __name__ == "__main__":
    main()
