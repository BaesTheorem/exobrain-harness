#!/usr/bin/env python3
"""Extract MIST-only windows from a source clip, isolate vocals (demucs), and
assemble a clean reference set for the XTTS clone.

Input: a windows TSV with lines `start_seconds<TAB>end_seconds<TAB>label`.
For each window: ffmpeg-cut from source -> demucs (vocals stem) -> loudnorm to
mono 24kHz wav in samples/reference/. Also writes a concatenated all-in-one.

Usage: extract_reference.py <source.wav> <windows.tsv>
"""
import sys, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "samples" / "reference"
PY = ROOT / ".venv" / "bin" / "python"

def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    source, windows = Path(sys.argv[1]), Path(sys.argv[2])
    REF.mkdir(parents=True, exist_ok=True)
    outs = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for i, line in enumerate(windows.read_text().splitlines()):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("start"):
                continue
            start, end, *rest = line.split("\t")
            label = (rest[0] if rest else f"seg{i}").replace(" ", "_")[:30]
            dur = float(end) - float(start)
            cut = td / f"cut_{i}.wav"
            # cut window
            run(["ffmpeg", "-y", "-ss", start, "-t", f"{dur:.2f}", "-i", str(source),
                 "-ac", "2", "-ar", "44100", str(cut)])
            # demucs: two-stem (vocals / no_vocals)
            run([str(PY), "-m", "demucs", "--two-stems", "vocals", "-o", str(td), str(cut)])
            voc = next(td.glob(f"*/cut_{i}/vocals.wav"))
            out = REF / f"{i:02d}_{label}.wav"
            # loudness-normalize, mono, 24kHz (XTTS reference format)
            run(["ffmpeg", "-y", "-i", str(voc), "-af",
                 "loudnorm=I=-18:TP=-2:LRA=11,highpass=f=70,lowpass=f=11000",
                 "-ac", "1", "-ar", "24000", str(out)])
            outs.append(out)
            print(f"[ok] {out.name}  ({dur:.1f}s)")
    print(f"\n{len(outs)} reference clips -> {REF}")

if __name__ == "__main__":
    main()
