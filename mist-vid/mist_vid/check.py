"""Validate an edit: clip bounds vs shots, gaps, speeds, talk flags. mist-vid check edit.yaml"""
from __future__ import annotations

import glob
import json
import sys

import numpy as np

from .timeline import Project


def main():
    P = Project(sys.argv[1])
    cat = {}
    for f in glob.glob("work/catalog/part_*.json"):
        for r in json.load(open(f)):
            cat[int(r["shot"])] = r
    starts = P.shot_starts
    prev_end = None
    n_warn = 0
    for c in [c for c in P.clips if c.layer == 0]:
        cfg = P.cfg["track"][c.idx]
        if prev_end is not None and abs(c.start - prev_end) > 1e-6 and "at" not in cfg:
            print(f"GAP before clip {c.idx}: {prev_end:.3f} -> {c.start:.3f}")
        prev_end = c.end
        if cfg.get("card") is not None:
            print(f"{c.idx:3d} {c.start:7.2f}-{c.end:7.2f} ({c.end - c.start:5.2f}s) CARD")
            continue
        lo_t, hi_t = c.start - c.pre, c.end + c.post
        raw0 = c.src_frame + (lo_t - c.start) * c.speed * P.src_fps
        raw1 = c.src_frame + (hi_t - c.start) * c.speed * P.src_fps
        shot = int(np.searchsorted(starts, c.src_frame + 0.5, side="right"))
        r = cat.get(shot, {})
        flags = []
        if raw1 > c.shot_hi + 1:
            flags.append(f"OVERRUN {(raw1 - c.shot_hi) / P.src_fps:.2f}s (freezes)")
        if raw0 < c.shot_lo - 1:
            flags.append(f"PREROLL-FREEZE {(c.shot_lo - raw0) / P.src_fps:.2f}s")
        if r.get("talk"):
            flags.append("talk")
        if flags:
            n_warn += 1
        sp = (f" x{c.speed:g}" + (" rife" if c.rife else "")) if c.speed != 1 else ""
        print(f"{c.idx:3d} {c.start:7.2f}-{c.end:7.2f} ({c.end - c.start:5.2f}s) #{shot:<5}{sp:10} "
              f"{r.get('desc', '')[:60]:60} {' '.join(flags)}")
    print(f"\nclips: {len([c for c in P.clips if c.layer == 0])}, duration {P.duration:.2f}s, warnings {n_warn}")


if __name__ == "__main__":
    main()
