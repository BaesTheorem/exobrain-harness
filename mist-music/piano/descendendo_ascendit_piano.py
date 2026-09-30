#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mido>=1.3", "numpy>=1.26", "scipy>=1.11"]
# ///
"""Descendendo ascendit, for piano.

Written on 30 September 2026, from the Shepard-tone piece of the same name
(mist-music/loops/descendendo_ascendit.py). Three passes through the chain of
thirds, 72 bars, about four and a half minutes. It can loop forever: the last
bar leads back into the first, and --loop renders it as one exact period.

The harmony is the chain of thirds, G E C A F D Bb G Eb C ..., one window per
bar. Three links make the 24 major and minor triads; four links make the 24
major and minor seventh chords. Both lists visit each key one time.

  Cycle 1   1-24   Ascendit. Triads. The melody climbs one octave on the
                   octatonic scale (G A Bb C Db Eb E F# G), one step every three
                   bars: this is every third link of the chain. A six-bar phrase
                   rises a minor third each time (C, Eb, Gb, A), like Bach's
                   Canon per tonos.
  Cycle 2   25-48  Descendendo. Seventh chords. The top of the melody falls one
                   octave by whole tones (G F Eb Db B A G), one step every four
                   bars: every fourth link. Each top note is the root, the third,
                   the fifth, then the seventh of its chords, and resolves down.
  Cycle 3   49-72  Both lines at once, in the right hand. The falling voice
                   starts an octave above the rising one. They meet in unison on
                   D-flat under G-flat major, the key farthest from C, and pass.

At each seam one voice goes on: the rising voice turns into the falling one at
the top (bar 25), the falling voice turns into the rising one at the bottom
(bar 49), and in the last bar the upper voice drops out while the lower one
starts the piece again. The bass falls by thirds throughout.

The piano is in equal temperament, and that is what closes the loop: twelve
tempered fifths are exactly seven octaves. (In pure tuning the chain returns a
Pythagorean comma flat. The Shepard version pays it back with a glide.)

    uv run mist-music/piano/descendendo_ascendit_piano.py            # concert version, with a final bar
    uv run mist-music/piano/descendendo_ascendit_piano.py --dump     # voicings + harmony warnings
    uv run mist-music/piano/descendendo_ascendit_piano.py --balance  # melody against accompaniment
    uv run mist-music/piano/descendendo_ascendit_piano.py --loop     # the endless version, one exact period
"""

import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
from scipy.io import wavfile

import pianokit as pk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "loops"))
import loopkit as lk  # noqa: E402  (a sibling folder, on the path from the line above)

NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


def chain(n: int) -> int:
    """Pitch class of link n of the chain of thirds (link 0 is G)."""
    pc = 7
    for k in range(n):
        pc = (pc - (3 if k % 2 == 0 else 4)) % 12
    return pc


def harmony() -> list[str]:
    """Chord symbol with its bass, per bar: triads in cycle 1, seventh chords after.
    The bass falls by thirds and jumps up an octave when it would pass below F1."""
    out, prev = [], 36
    for i in range(72):
        cycle, b = divmod(i, 24)
        if cycle == 0:
            root, quality = chain(b + 2), ("" if b % 2 == 0 else "m")
        else:
            root, quality = chain(b + 3), ("m7" if b % 2 == 0 else "maj7")
        bass = 36 if i == 0 else prev - (prev - root) % 12
        if bass < 29:
            bass += 12
        prev = bass
        if i in (58, 59):  # the climax doubles the bass an octave down: keep that octave on the keyboard
            bass += 12
        out.append(f"{NAMES[root]}{quality}@{pk.note_name(bass)}")
    return out


def tr(spec: str, k: int) -> str:
    """Melody tokens moved k semitones."""
    out = []
    for tok in spec.split():
        head, _, dur = tok.partition(":")
        bang = "!" if head.endswith("!") else ""
        head = head.rstrip("!")
        if head != "r":
            head = "+".join(pk.note_name(pk.pitch(p) + k) for p in head.split("+"))
        out.append(f"{head}{bang}:{dur}" if dur else f"{head}{bang}")
    return " ".join(out)


# Cycle 1. Six bars in C (C Am F Dm Bb Gm), sung over the rising line G | A A A | Bb Bb.
# The same phrase then climbs a minor third three times: the harmony is exactly sequential.
RISE = [
    "G4:1.5 E4:.5 G4:2",
    "A4:2 C5:1.5 B4!:.5",
    "A4:1 C5:1 F5:1.5 E5!:.5",
    "D5:2 C5!:1 A4:1",
    "Bb4:2 D5:1 F5:1",
    "Eb5!:1 D5:1 Bb4:2",
]
# Cycle 2. Four bars under the ceiling F (Fmaj7 Dm7 Bbmaj7 Gm7): F is the root, the third,
# the fifth, then the seventh, and it resolves down a whole tone. Each unit is a tone lower.
FALL = [
    "F5:1 E5:.5 C5:.5 A4:1 C5:1",
    "F5:1.5 E5!:.5 D5:1 A4:1",
    "F5:1 D5:.5 Bb4:.5 A4:1 D5:1",
    "F5:2 D5:1 Eb5!:1",
]
# Cycle 3. Upper and lower voice as dyads on each downbeat: the falling line over the rising
# one, a unison on D-flat (bars 59-61, in octaves), then the rising line over the falling one.
BOTH = [
    "G4+G5:2 E5:1 C5:1",      # Am7      G5 / G4   the falling voice enters an octave up
    "A4+F5:2 E5:1 C5:1",      # Fmaj7    F5 / A4
    "A4+F5:2 C5:1 D5:1",      # Dm7
    "A4+F5:2 D5:1 Bb4:1",     # Bbmaj7
    "Bb4+F5:2 D5:1 Eb5!:1",   # Gm7      F5 / Bb4
    "Bb4+Eb5:2 G5:1 F5!:1",   # Ebmaj7   Eb5 / Bb4
    "Bb4+Eb5:2 C5:1 G5:1",    # Cm7
    "C5+Eb5:2 G5:1 Ab5:1",    # Abmaj7   Eb5 / C5
    "C5+Eb5:2 Ab5:1 F5:1",    # Fm7
    "C5+Db5:2 F5:1 Ab5:1",    # Dbmaj7   Db5 / C5, a semitone apart
    "Db5:2 F5:1 Ab5:1",       # Bbm7     the unison, in octaves
    "Bb5:2 Gb5:1 F5:1",       # Gbmaj7   the key farthest from C
    "Db5:4",                  # Ebm7
    "B4+Eb5:2 Gb5:1 Bb5:1",   # Bmaj7    they pass: Eb5 (rising) / B4 (falling)
    "B4+Eb5:2 Gb5:1 Ab5:1",   # Abm7
    "B4+Eb5:2 Ab5:1 E5:1",    # Emaj7
    "B4+E5:2 Ab5:1 B5:1",     # Dbm7     E5 / B4
    "A4+E5:2 Ab5:1 Db5:1",    # Amaj7    E5 / A4
    "A4+E5:2 A5:1 Gb5:1",     # Gbm7
    "A4+Gb5:2 A5:1 D5:1",     # Dmaj7    F#5 / A4
    "A4+Gb5:2 B5:1 A5:1",     # Bm7
    "G4+Gb5:2 D5:1 B4:1",     # Gmaj7    F#5 / G4
    "G4+G5:2 E5:1 B4:1",      # Em7      G5 / G4
    "G4+G5:4",                # Cmaj7    the upper G ends here; the lower G begins bar 1 again
]


def melody() -> list[str]:
    cycle1 = [tr(m, 3 * u) for u in range(4) for m in RISE]
    cycle2 = [tr(FALL[3], 2)] + [tr(m, -2 * k) for k in range(6) for m in FALL][:23]
    return cycle1 + cycle2 + BOTH


# Per bar: (bpm, melody velocity, accompaniment velocity, left hand, right hand).
# The melody sits about 28 velocity steps over the accompaniment: in this bank that is
# about 14 dB per note, which the pedaled arpeggios need for the melody to sing (--balance).
def performance() -> list[tuple[float, int, int, str, str]]:
    out = []
    for b in range(24):  # rising: a little brighter every phrase
        u = b // 6
        out.append((66, 62 + 2 * u + min(b % 6, 3), (38, 39, 40, 42)[u], ("calm", "wave", "wave", "wave2")[u],
                    "solo" if u < 2 else "duet"))
    for b in range(24):  # falling: each whole-tone step a little softer
        k = max(0, (b - 1) // 4)
        out.append((70, 72 - 2 * k if b else 70, (42, 41, 40, 40, 39, 38)[k], "wave2" if k < 3 else "wave", "solo"))
    mel = [66, 68, 69, 70, 72, 74, 76, 78, 81, 84, 90, 94, 90, 82, 79, 77, 75, 73, 71, 69, 67, 64, 62, 60]
    acc = [42, 42, 43, 44, 45, 46, 47, 48, 50, 52, 54, 56, 53, 47, 45, 44, 43, 42, 41, 40, 40, 39, 38, 38]
    for b in range(24):  # both: converge to the unison, then part and fade into bar 1
        lh = ("wave" if b < 4 else "wave2" if b < 10 else "climax" if b < 13 else "wave2" if b < 17
              else "wave" if b < 21 else "calm")
        bpm = 70 if b < 8 else 72 if b < 13 else 70 if b < 20 else 68 - 2 * (b - 20)
        out.append((bpm, mel[b], acc[b], lh, "octaves" if 10 <= b <= 12 else "solo"))
    return out


def bars(final: bool) -> list[list[pk.Bar]]:
    rows = [(h, m, bpm, v, a, {"lh": lh, "rh": rh})
            for h, m, (bpm, v, a, lh, rh) in zip(harmony(), melody(), performance(), strict=True)]
    cycles = [pk.section(rows[24 * c:24 * c + 24]) for c in range(3)]
    if final:  # the concert version ends on the chord and the note that begin it
        cycles.append(pk.section([("C@C2", "G4:4", 58, 60, 38, {"lh": "rolled", "ring": 1})]))
    return cycles


PHRASES = (1, 7, 13, 19, 25, 30, 34, 38, 42, 46, 49, 53, 57, 59, 62, 66, 70)
RITS = (
    ((24, 3), (25, 1), 0.90),   # the top of the climb
    ((48, 3), (49, 1), 0.88),   # the bottom of the fall
    ((60, 1), (61, 1), 0.86),   # broaden into the unison
)
COMMENT = ("Composed and performed in Python with pianokit. Piano: Salamander Grand Piano V3 "
           "by Alexander Holm, CC BY 3.0, via FreePats.")

PIECE = pk.Piece(
    title="Descendendo ascendit, for piano",
    sections=bars(final=True),
    phrases=PHRASES,
    rits=(*RITS, ((71, 1), (73, 1), 0.84), ((73, 1), (73, 4), 0.85)),
    holds=(((61, 4.9), 0.35), ((73, 4.5), 1.2)),
    comment=COMMENT,
)
# The endless version: no final bar, and only a breath before bar 1 comes round again.
LOOP = pk.Piece(
    title="Descendendo ascendit, for piano (loop)",
    sections=bars(final=False),
    phrases=PHRASES,
    rits=(*RITS, ((72, 1), (72, 4.99), 0.92)),
    holds=(((61, 4.9), 0.35),),
    comment=COMMENT,
)


def fold(x: np.ndarray, start: int, period: int) -> np.ndarray:
    """Sum a rendering into one period that begins at `start`: the tail past the end rings
    into the beginning, and anything before `start` sounds at the end, as on a real repeat."""
    y = np.zeros((period, 2))
    for k in range(-1, len(x) // period + 2):
        a, z = start + k * period, start + (k + 1) * period
        seg = x[max(a, 0):max(min(z, len(x)), 0)]
        if len(seg):
            off = max(a, 0) - a
            y[off:off + len(seg)] += seg
    return y


def render_loop(wet_db: float = -9.0) -> None:
    piece = LOOP
    bars_, chords, notes, warns = pk.compose(piece)
    for w in warns:
        print(f"warning: {w}")
    pedals = pk.perform(piece, bars_, chords, notes)
    grid, times = pk.tempo_map(piece, bars_)
    t0, t1 = float(times[0]), float(times[-1])
    pedals[-1] = (t1 + 0.015, 0)  # lift at the wrap like at any other chord change
    sr = lk.SR
    period = round((t1 - t0) * 1000) * (sr // 1000)  # a whole number of milliseconds
    with tempfile.TemporaryDirectory() as td:
        mid, wav = Path(td) / "loop.mid", Path(td) / "dry.wav"
        pk.write_performance(mid, piece, notes, pedals)
        pk.render(mid, wav, pk.DEFAULT_SF2, sr)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", wavfile.WavFileWarning)
            _, raw = wavfile.read(wav)
    x = np.asarray(raw, dtype=np.float64)
    y = fold(x, round(t0 * sr), period)
    wet = lk.circular_convolve(y, pk.hall_ir(sr))
    y = lk.highpass(y + 10 ** (wet_db / 20) * lk.rms(y) / lk.rms(wet) * wet, sr, 28.0)
    y = lk.master(y, sr, target_lufs=-18.0, ceiling_db=-1.2)
    meta = {"title": "Descendendo ascendit, for piano (loop)", "artist": "MIST", "comment": COMMENT}
    stem = lk.OUT / "descendendo-ascendit-piano"
    files = lk.write_outputs(y, sr, stem, meta, roll=2.0)
    files |= lk.write_listening(y, sr, stem, meta, passes=2)
    secs = period / sr
    print(f"{len(bars_)} bars, {len(notes)} notes, period {secs:.3f} s")
    for label, arr, start in (("flac", lk.decode(files["flac"]), 0), ("mp3 window", lk.decode(files["mp3"]), 2 * sr)):
        wrap, p9999 = lk.seam(arr, start, period)
        print(f"  seam {label}: step at wrap {wrap:.5f} (99.99th pct inside {p9999:.5f})")
    lufs, peak = lk.loudness(files["flac"])
    print(f"  {lufs:.1f} LUFS, true peak {peak:.1f} dBTP")
    print(f"![Descendendo ascendit, for piano]({files['mp3']}#loop=2,{2 + secs:.3f})")
    print(f"![Descendendo ascendit, for piano, across the join]({files['seam']})")


if __name__ == "__main__":
    if "--loop" in sys.argv:
        render_loop()
    else:
        pk.main(PIECE)
