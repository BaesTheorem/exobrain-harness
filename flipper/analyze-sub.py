#!/usr/bin/env python3
"""
analyze-sub.py -- inspect a Flipper SubGHz RAW .sub capture and guess its nature.

A RAW .sub is OOK/ASK pulse timing in microseconds: positive = carrier ON,
negative = carrier OFF. This doesn't decode a protocol; it characterizes the
signal -- fundamental timing unit, frame structure, whether frames repeat
(fixed-code remote) or differ (rolling code / noise), and rough bit count.

Usage: analyze-sub.py <file.sub>
"""
import sys
from collections import Counter


def load(path):
    header = {}
    raw = []
    with open(path) as f:
        for line in f:
            if line.startswith("RAW_Data:"):
                raw.extend(int(x) for x in line.split(":", 1)[1].split())
            elif ":" in line:
                k, v = line.split(":", 1)
                header[k.strip()] = v.strip()
    return header, raw


def cluster(durations, tol=0.25):
    """Group durations into levels; return sorted (center, count) list."""
    levels = []  # [center, count, sum]
    for d in sorted(durations):
        for lv in levels:
            if abs(d - lv[0]) <= tol * lv[0]:
                lv[1] += 1
                lv[2] += d
                lv[0] = lv[2] / lv[1]
                break
        else:
            levels.append([d, 1, d])
    return sorted(((round(c), n) for c, n, _ in levels), key=lambda x: -x[1])


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: analyze-sub.py <file.sub>")
    header, raw = load(sys.argv[1])

    print("== Header ==")
    for k in ("Filetype", "Frequency", "Preset", "Protocol"):
        if k in header:
            print(f"  {k}: {header[k]}")
    freq = int(header.get("Frequency", 0))
    print(f"  → {freq/1e6:.3f} MHz, modulation: "
          f"{'OOK/ASK (amplitude)' if 'Ook' in header.get('Preset','') else header.get('Preset','?')}")

    durs = [abs(x) for x in raw]
    on = [abs(x) for x in raw if x > 0]
    off = [abs(x) for x in raw if x < 0]
    total_us = sum(durs)
    print("\n== Gross stats ==")
    print(f"  edges (pulses): {len(raw)}")
    print(f"  total duration: {total_us/1000:.1f} ms")
    print(f"  ON  width: min {min(on)} / med {sorted(on)[len(on)//2]} / max {max(on)} us")
    print(f"  OFF width: min {min(off)} / med {sorted(off)[len(off)//2]} / max {max(off)} us")

    print("\n== Timing levels (most common pulse widths) ==")
    levels = cluster(durs)
    for center, n in levels[:8]:
        print(f"  ~{center:>6} us   x{n}")
    short = min(c for c, n in levels[:5] if n > len(raw) * 0.05)
    print(f"  → likely fundamental unit (te): ~{short} us")

    # Frame split on large OFF gaps (inter-frame silence).
    gap_thresh = max(short * 12, 2500)
    frames, cur = [], []
    for v in raw:
        cur.append(v)
        if v < 0 and abs(v) >= gap_thresh:
            frames.append(cur)
            cur = []
    if cur:
        frames.append(cur)
    frames = [f for f in frames if len(f) > 4]  # drop tiny fragments

    print(f"\n== Frame structure (split on OFF gaps ≥ {gap_thresh} us) ==")
    print(f"  frames found: {len(frames)}")
    lengths = [len(f) for f in frames]
    if frames:
        lc = Counter(lengths)
        print(f"  edges per frame: {sorted(set(lengths))}")
        print(f"  most common frame length: {lc.most_common(1)[0][0]} edges "
              f"(appears {lc.most_common(1)[0][1]}x)")
        # Repetition check: do frames share a consistent length?
        dominant = lc.most_common(1)[0]
        repeat_ratio = dominant[1] / len(frames)
        approx_bits = dominant[0] // 2
        print("\n== Verdict ==")
        if len(frames) >= 3 and repeat_ratio >= 0.5:
            print(f"  Looks like a REPEATING remote: {dominant[1]} frames of ~{dominant[0]} edges")
            print(f"  (~{approx_bits} bits/frame). Consistent repeats ⇒ likely a")
            print("  FIXED-CODE remote (cloneable/replayable). Rolling codes change each frame.")
        elif len(frames) >= 3 and repeat_ratio < 0.5:
            print(f"  {len(frames)} frames but INCONSISTENT lengths ⇒ either a rolling code,")
            print("  a noisy/partial capture, or multiple overlapping signals.")
        else:
            print(f"  Only {len(frames)} clean frame(s). Could be a single button press,")
            print("  a fragment, or ambient noise. A clean remote usually repeats 3-10x.")
    else:
        print("  No clear frames -- likely noise or an unusable capture.")


if __name__ == "__main__":
    main()
