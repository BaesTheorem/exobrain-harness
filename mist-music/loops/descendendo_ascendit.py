#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.26", "scipy>=1.11"]
# ///
"""Descendendo ascendit ("by descending, it rises"): a strange loop in all 24 keys.

For Shepard organ, harp, flute, and eight bells. Written 30 September 2026.

The whole piece is one sequence read at different speeds. The sequence is the
chain of thirds: G E C A F D Bb G Eb C ..., a minor third down, then a major
third down, again and again. Two thirds make a fifth, so the chain falls one
fifth for every two links. After 24 links it has fallen seven octaves, and
(in equal temperament) it is back on G.

  - Any three adjacent links make a major or minor triad. The 24 windows of the
    chain are the 24 major and minor triads, each one time. That is the harmony,
    one triad per bar, 3/4 at 60.
  - The pedal plays one link per bar (the root of each triad): it falls by thirds.
  - The flute plays one link per bar (the fifth of each triad) with a passing
    tone: a diatonic scale that falls forever and adds one flat every two bars.
  - The organ plays every third link, in three voices. Three thirds down is a
    seventh down, and a seventh down is a step up, one octave higher. So each
    organ voice RISES by step (an octatonic scale), and the three voices are a
    canon. The two held notes of each triad stay, and the new one rises into place.
  - The harp arpeggiates each triad upward, and it goes up again at each bar line.
  - Bell d rings every d bars, for each divisor d of 24. Bell d plays every d-th
    link, and that line falls by thirds (d=1), rises by fourths (2), rises by
    steps (3), falls by whole tones (4), rises by minor thirds (6), falls by
    major thirds (8), alternates by tritones (12), or stays on C (24). The
    number of bells that ring at bar b is the number of divisors of gcd(b, 24).

Every voice is a Shepard stack, so no line ever leaves its register: the organ
climbs one octave per cycle, and the flute and the pedal fall seven, and after
72 seconds all of them are where they started.

Tuning: every triad is pure (4:5:6 major, 10:12:15 minor), with the two common
tones held exactly. Pure tuning cannot close the loop. Twelve pure fifths
overshoot seven octaves by the Pythagorean comma, 3^12/2^19, because a power of
3 is never a power of 2. So the chain comes back 23.46 cents flat. The whole
texture rises by that comma in each cycle, 0.33 cents per second, below what any
ear can follow. With that glide, the loop closes to the sample.

Form: three cycles of 24 bars (216 s). The foreground turns between harp, flute,
and bells, and their three levels always sum to the same total. Each one peaks
in the middle of its cycle, on G-flat, the key farthest from C.

    uv run mist-music/loops/descendendo_ascendit.py            # render to tmp/audio/
    uv run mist-music/loops/descendendo_ascendit.py --dump     # the score, bar by bar
    uv run --with matplotlib mist-music/loops/descendendo_ascendit.py --check   # render + measure
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from pathlib import Path

import numpy as np

import loopkit as lk

TITLE = "Descendendo ascendit"
SLUG = "descendendo-ascendit"
BAR = 3.0                       # seconds: 3/4 at 60 beats per minute
CYCLE = 24                      # bars in one pass through the chain
CYCLES = 3                      # the foreground rotation takes three passes
PERIOD = BAR * CYCLE * CYCLES   # 216 s
DIVISORS = (1, 2, 3, 4, 6, 8, 12, 24)
BELL_PAN = {1: 0.55, 2: -0.5, 3: 0.42, 4: -0.34, 6: 0.26, 8: -0.18, 12: 0.1, 24: 0.0}
ORGAN_PAN = (-0.45, 0.0, 0.45)  # organ voice b % 3; the moving voice circles the stereo field


def x(n: int) -> float:
    """log2 pitch of link n of the chain of thirds, pure-tuned (link 2 is C4)."""
    k, odd = divmod(n, 2)
    return math.log2(lk.C4) + (lk.lattice(-k, 1) if odd else lk.lattice(1 - k, 0))


def name(log2f: float) -> str:
    return lk.PC_NAMES[round(12 * (log2f - math.log2(lk.C4))) % 12]


def triad(b: int) -> str:
    """Name of the triad in bar b. Names come from the first cycle: the raw chain falls one
    comma per cycle (the glide makes it up), so a later cycle would round to the wrong key."""
    b %= CYCLE
    return name(x(b + 2)) + ("" if b % 2 == 0 else "m")


def harp_partials(beta: float = 0.13, n: int = 14) -> tuple[tuple[float, float, float], ...]:
    """A string plucked at beta of its length: partial h has amplitude sin(pi h beta) / h."""
    top = math.sin(math.pi * beta)
    return tuple((float(h), abs(math.sin(math.pi * h * beta)) / top / h**1.1, 1.0) for h in range(1, n + 1))


PRINCIPAL = lk.Tone(partials=((1, 1.0, 1), (2, 0.42, 1), (3, 0.26, 1), (4, 0.16, 1), (5, 0.10, 1),
                              (6, 0.07, 1), (7, 0.04, 1), (8, 0.03, 1)),
                    attack=0.10, release=0.35, noise=0.02, noise_ms=25, noise_band=(2.5, 5.0), bright=4500)
PEDAL = lk.Tone(partials=((1, 1.0, 1), (2, 0.55, 1), (3, 0.30, 1), (4, 0.16, 1), (5, 0.09, 1), (6, 0.05, 1)),
                attack=0.12, release=0.45, noise=0.015, noise_band=(1.5, 4.0), bright=3000)
HARP = lk.Tone(partials=harp_partials(), attack=0.003, release=0.25, tau440=1.9, tau_exp=0.9,
               noise=0.04, noise_ms=6, noise_band=(4.0, 12.0), bright=8000)
FLUTE = lk.Tone(partials=((1, 1.0, 1), (2, 0.16, 1), (3, 0.07, 1), (4, 0.025, 1), (5, 0.012, 1)),
                attack=0.09, release=0.30, noise=0.015, noise_ms=60, noise_band=(1.0, 3.0), bright=5000,
                vibrato=(5.0, 4.8, 0.35))


def bell(third: float) -> lk.Tone:
    """An ideal bell: every partial is a pure ratio of the nominal (1.0), and the tierce
    matches the chord (5/4 on major triads, 6/5 on minor ones), so no bell clashes with
    its triad. The hum rings longest."""
    return lk.Tone(partials=((0.25, 0.35, 2.2), (0.5, 0.45, 1.8), (0.5 * third, 0.38, 1.5), (0.75, 0.15, 1.2),
                             (1.0, 1.0, 1.0), (1.5, 0.28, 0.7), (2.0, 0.18, 0.5), (2.0 * third, 0.10, 0.4),
                             (3.0, 0.05, 0.3)),
                   attack=0.002, release=2.5, tau440=1.8, tau_exp=0.55, noise=0.05, noise_ms=4,
                   noise_band=(3.0, 10.0), bright=9500)


BELL_MAJOR, BELL_MINOR = bell(5 / 4), bell(6 / 5)

# Target loudness of each layer on its own (ungated BS.1770 LUFS, averaged over the period).
# The renderer sets each layer's gain to meet its target, so the balance is written in LUFS.
TARGETS = {"organ": -25.0, "pedal": -28.0, "harp": -24.0, "cantus": -22.0, "bells": -25.0}
LAYERS = [
    lk.Layer("organ", PRINCIPAL, center=300.0, sigma=1.0, send=0.55),
    lk.Layer("pedal", PEDAL, center=70.0, sigma=0.6, send=0.35),
    lk.Layer("harp", HARP, center=760.0, sigma=0.8, send=0.45),
    lk.Layer("cantus", FLUTE, center=560.0, sigma=0.7, send=0.4),
    lk.Layer("bells", BELL_MAJOR, center=1000.0, sigma=0.4, send=0.6),
]


def rotation(t: float, i: int) -> float:
    """Level of foreground layer i (0 harp, 1 cantus, 2 bells) at time t. The three levels
    turn through one period 120 degrees apart and always sum to 1.875."""
    return 0.25 + 0.75 * math.cos(math.pi * (t / PERIOD - i / 3 - 1 / 6)) ** 2


def swell(b: int) -> float:
    """Organ and pedal breathe once per cycle: fullest on G-flat (bar 12), softest on C."""
    return 0.85 + 0.15 * math.sin(math.pi * (b % CYCLE) / CYCLE) ** 2


def score(seed: int = 3) -> list[lk.Note]:
    rng = random.Random(seed)
    notes: list[lk.Note] = []
    bars = CYCLE * CYCLES
    for b in range(bars):
        t0 = b * BAR
        fifth, third, root = x(b), x(b + 1), x(b + 2)
        # Organ: the voice that moves this bar rises by step to the new root and holds it
        # for three bars (root, then third, then fifth of the next two triads).
        notes.append(lk.Note("organ", t0, 3 * BAR, root, amp=swell(b), pan=ORGAN_PAN[b % 3]))
        # Pedal: the root, falling by a third every bar.
        notes.append(lk.Note("pedal", t0, BAR - 0.05, root, amp=swell(b)))
        # Harp: the triad upward three times per bar, in triplets.
        for j in range(9):
            t = t0 + j * BAR / 9 + rng.uniform(-0.005, 0.005)
            amp = (1.0 if j == 0 else 0.85 if j % 3 == 0 else 0.7) * rng.uniform(0.95, 1.05)
            notes.append(lk.Note("harp", t, 5.0, (root, third, fifth)[j % 3], amp=amp * rotation(t, 0),
                                 pan=-0.25 + rng.uniform(-0.1, 0.1)))
        # Flute: the fifth for two beats, then a passing tone a pure whole tone (9:8) below.
        w = rotation(t0, 1)
        notes.append(lk.Note("cantus", t0, 2.0, fifth, amp=w, pan=0.2))
        notes.append(lk.Note("cantus", t0 + 2.0, 1.0, fifth + lk.lattice(-2, 0), amp=0.8 * w, pan=0.2))
        # Bells: bell d rings the root every d bars. Size (register) and ring time grow with d.
        for d in DIVISORS:
            if b % d == 0:
                size = math.log(d) / math.log(24)
                notes.append(lk.Note("bells", t0 + rng.uniform(-0.003, 0.003), 6.0 + 0.5 * d, root,
                                     amp=(0.55 + 0.45 * size) * rotation(t0, 2), pan=BELL_PAN[d],
                                     tone=BELL_MAJOR if b % 2 == 0 else BELL_MINOR,
                                     center=1500.0 * d ** -0.62))
    return notes


# ---- checks ----------------------------------------------------------------------------------

def step_cents(a: float, b: float) -> float:
    """The shorter way round the pitch circle from a to b, in cents (what a Shepard ear hears)."""
    d = (b - a) % 1.0
    return 1200 * (d - 1 if d > 0.5 else d)


def check_score() -> bool:
    ok = True
    bars = CYCLE * CYCLES
    # 1. Every window is a pure triad; the 24 triads of a cycle are distinct.
    for b in range(bars):
        f, t, r = x(b), x(b + 1), x(b + 2)
        fifth = (f - r) % 1.0
        thd = (t - r) % 1.0
        pure = abs(fifth - math.log2(1.5)) < 1e-9 and min(abs(thd - math.log2(1.25)), abs(thd - math.log2(1.2))) < 1e-9
        ok &= pure
    distinct = len({triad(b) for b in range(CYCLE)})
    print(f"pure triads in every bar: {ok};  distinct triads per cycle: {distinct}/24")
    ok &= distinct == 24
    # 2. The loop closes: link n + 72, raised by the glide over one period, is link n plus whole octaves.
    glide = CYCLES * lk.PYTHAGOREAN_COMMA
    gaps = [(x(n + bars) + glide - x(n)) for n in range(bars)]
    closes = all(abs(g - round(g)) < 1e-9 for g in gaps)
    print(f"loop closes after {bars} bars with a glide of {lk.cents(glide):.2f} cents: {closes}"
          f"  (without it: {lk.cents((x(bars) - x(0)) % 1 - 1):.2f} cents)")
    ok &= closes
    # 3. Direction of each line, by the shorter way round the circle.
    lines = {
        "organ voices (every 3rd link)": [(x(b + 2), x(b + 5)) for b in range(bars)],
        "pedal (every link)": [(x(b + 2), x(b + 3)) for b in range(bars)],
        "flute (fifth -> passing -> next fifth)": [p for b in range(bars) for p in
                                                   ((x(b), x(b) + lk.lattice(-2, 0)), (x(b) + lk.lattice(-2, 0), x(b + 1)))],
        "harp (root -> third -> fifth -> ...)": [p for b in range(bars) for p in
                                                 ((x(b + 2), x(b + 1)), (x(b + 1), x(b)), (x(b), x(b + 2)),
                                                  (x(b), x(b + 3)))],
    }
    want = {"organ": 1, "pedal": -1, "flute": -1, "harp": 1}
    for label, pairs in lines.items():
        steps = [step_cents(a, c) for a, c in pairs]
        sign = want[label.split()[0]]
        good = all(s * sign > 0 for s in steps)
        ok &= good
        print(f"  {label:42s} {'rises' if sign > 0 else 'falls'}: {good}   steps {min(steps):+.0f} to {max(steps):+.0f} cents")
    for d in DIVISORS:
        steps = {round(step_cents(x(b + 2), x(b + 2 + d))) for b in range(0, bars, d)}
        print(f"  bell {d:2d}: every {d:2d} bars, steps {sorted(steps)} cents")
    return ok


def check_audio(y: np.ndarray, sr: int, files: dict[str, Path], n: int) -> None:
    # Harmony heard in the audio: the best triad per bar, from beats 1-2 of the final mix.
    got = []
    for b in range(CYCLE * CYCLES):
        s = int((b * BAR + 0.35) * sr)
        got.append(lk.best_triad(lk.pitch_class_profile(y[s:s + int(1.5 * sr)], sr))[0])
    want = [triad(b) for b in range(CYCLE * CYCLES)]
    hit = sum(g == w for g, w in zip(got, want, strict=True))
    shifted = sum(g == w for g, w in zip(got, want[1:] + want[:1], strict=True))
    print(f"triads heard in the mix: {hit}/{len(want)} match the score; control (labels one bar late): {shifted}/{len(want)}")
    if hit < len(want):
        print("  misses:", [(b, want[b], got[b]) for b in range(len(want)) if got[b] != want[b]][:12])
    # The seam, in the lossless loop and in the MP3's loop window.
    flac = lk.decode(files["flac"], sr)
    mp3 = lk.decode(files["mp3"], sr)
    print(f"flac: {len(flac)} samples (period {n}); mp3: {len(mp3)} samples")
    for label, arr, start in (("flac, whole file", flac, 0), ("mp3, window [2.0, 218.0)", mp3, int(2.0 * sr))):
        wrap, p9999 = lk.seam(arr, start, n)
        hf_wrap, hf_med = lk.seam_hf(arr, start, n, sr)
        print(f"  seam {label:26s} step at wrap {wrap:.5f} (99.99th pct inside {p9999:.5f}); "
              f">8 kHz peak at wrap {hf_wrap:.1f} dBFS vs median {hf_med:.1f}")
    # Control for the seam test: a window one sample too long should show a step at the wrap.
    wrap_bad, _ = lk.seam(mp3, int(2.0 * sr), n + 37)
    print(f"  control, window 37 samples too long: step at wrap {wrap_bad:.5f}")
    lufs, peak = lk.loudness(files["flac"])
    print(f"loudness {lufs:.1f} LUFS, true peak {peak:.1f} dBTP")


def measure(y: np.ndarray, sr: int, files: dict[str, Path]) -> None:
    check_audio(y, sr, files, len(y))
    marks = [(b * BAR, triad(b)) for b in range(CYCLE)]
    png = files["mp3"].with_name(f"{SLUG}-cycle1.png")
    lk.spectrogram_png(y, sr, png, 0.0, CYCLE * BAR, f"{TITLE}: cycle 1", marks)
    print(f"spectrogram {png}")


def main() -> None:
    ap = argparse.ArgumentParser(description=TITLE)
    ap.add_argument("--dump", action="store_true", help="print the score and the score checks, no audio")
    ap.add_argument("--check", action="store_true", help="render, then measure harmony, seam, loudness, spectrogram")
    ap.add_argument("--measure", action="store_true", help="measure the files of the last render, no render")
    ap.add_argument("--wet", type=float, default=-4.5, help="reverb level against the dry mix, dB")
    ap.add_argument("--air", type=float, default=2.5, help="high shelf above 5 kHz on the mix, dB")
    ap.add_argument("--out", type=Path, default=lk.OUT)
    args = ap.parse_args()

    if args.dump:
        for b in range(CYCLE):
            v = [name(x(b + 2 - k)) for k in (0, 1, 2)]
            bells = [d for d in DIVISORS if b % d == 0]
            print(f"bar {b + 1:2d}  {triad(b):4s} organ {' '.join(v):10s} pedal {name(x(b + 2)):3s} "
                  f"flute {name(x(b))}-{name(x(b) + lk.lattice(-2, 0))}  bells {bells}")
        sys.exit(0 if check_score() else 1)

    if not check_score():
        sys.exit("score check failed")
    if args.measure:
        files = {"flac": args.out / f"{SLUG}-loop.flac", "mp3": args.out / f"{SLUG}.mp3"}
        y = lk.decode(files["flac"])
        measure(y, lk.SR, files)
        return
    t_start = time.time()
    loop = lk.Loop(PERIOD, LAYERS, glide=CYCLES * lk.PYTHAGOREAN_COMMA, seed=7)
    loop.render(score(), cache=lk.HARNESS / "tmp" / "loopkit-cache" / SLUG)
    print(f"rendered {dict(loop.count)} in {time.time() - t_start:.0f} s", flush=True)
    for layer in LAYERS:  # set each gain so the layer meets its loudness target
        stem = loop.stems[layer.name].astype(np.float64)
        measured = lk.lufs_ungated(stem)
        gain = 10 ** ((TARGETS[layer.name] - measured) / 20)
        loop.layers[layer.name] = lk.Layer(layer.name, layer.tone, layer.center, layer.sigma, gain, layer.send)
        print(f"  {layer.name:7s} raw {measured:6.1f} LUFS -> gain {gain:.3f} for {TARGETS[layer.name]:.1f}")
    y = lk.master(lk.shelf(loop.mix(wet_db=args.wet), loop.sr, 5000.0, args.air), loop.sr)
    meta = {"title": TITLE, "artist": "MIST", "album": "Strange Loops",
            "comment": "Chain of thirds through all 24 keys; just intonation; Shepard stacks; loops exactly every 216 s"}
    files = lk.write_outputs(y, loop.sr, args.out / SLUG, meta, roll=2.0)
    print(f"wrote {files['mp3']} and {files['flac']}  ({time.time() - t_start:.0f} s)")
    if args.check:
        measure(y, loop.sr, files)
    print(f"![{TITLE}]({files['mp3']}#loop=2,{2 + PERIOD:g})")


if __name__ == "__main__":
    main()
