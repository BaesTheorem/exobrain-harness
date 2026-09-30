"""pianokit: perform a written piano score and render it to audio.

A score is a list of bars. Each bar gives its harmony as chord symbols over an
explicit bass note, the melody as pitch:beats tokens, a left-hand pattern, a
right-hand texture, a tempo, and two dynamics (melody and accompaniment).
pianokit voices the chords and plays the patterns. Then it performs the notes
the way a pianist does: rubato across each phrase, ritardandi and holds at the
cadences, high notes a little louder, the melody slightly ahead of the
accompaniment, legato pedal in the left hand, and small seeded variation in
timing and velocity. It writes a performance MIDI (real time baked in) and a
quantized score MIDI, then renders audio with FluidSynth and a synthesized
hall reverb.

Tokens
  melody   E5:1.5   Ab4:2   r:.5 (rest)   G#4+G#5:.5 (dyad)
           A5!:1 (a written non-chord tone: the harmony check skips it)
  chords   Fmaj7@F2    C/G@G2:2, G7@G2:2    (symbol @ bass note, optional :beats)

Left-hand patterns: wave, wave2, calm, rise, climax, rolled, octave.
Right-hand textures: solo; duet (a third or sixth under the long notes);
octaves (the melody doubled an octave up, with an inner chord tone).
Tuning: equal temperament, or adaptive just intonation with --tuning just.
"""

from __future__ import annotations

import argparse
import bisect
import math
import random
import re
import shutil
import subprocess
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path

import mido
import numpy as np
from scipy.io import wavfile
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import butter, oaconvolve, sosfilt, sosfiltfilt

HARNESS = Path(__file__).resolve().parents[2]
DEFAULT_OUT = HARNESS / "tmp" / "audio"
DEFAULT_SF2 = (
    Path.home()
    / "Library/Audio/Sounds/Banks/SalamanderGrandPiano-SF2-V3+20200602"
    / "SalamanderGrandPiano-V3+20200602.sf2"
)
BEATS = 4  # every bar is 4/4
LEAD_IN = 0.6  # seconds before the first note
TAIL = 6.0  # seconds rendered after the last note: key release plus the room

_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_ACC = {"": 0, "#": 1, "b": -1}
_FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


def pitch(name: str) -> int:
    """'C4' -> 60, 'Eb5' -> 75, 'G#2' -> 44."""
    m = re.fullmatch(r"([A-G])([#b]?)(-?\d)", name)
    if not m:
        raise ValueError(f"bad pitch {name!r}")
    return 12 * (int(m[3]) + 1) + _PC[m[1]] + _ACC[m[2]]


def pitch_class(name: str) -> int:
    m = re.fullmatch(r"([A-G])([#b]?)", name)
    if not m:
        raise ValueError(f"bad pitch class {name!r}")
    return (_PC[m[1]] + _ACC[m[2]]) % 12


def note_name(p: int) -> str:
    return f"{_FLAT_NAMES[p % 12]}{p // 12 - 1}"


# quality: (chord tones above the root, left-hand shape above the root)
QUALITIES: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "": ((0, 4, 7), (0, 7, 12, 16, 19)),
    "m": ((0, 3, 7), (0, 7, 12, 15, 19)),
    "add9": ((0, 2, 4, 7), (0, 7, 12, 14, 16)),
    "6": ((0, 4, 7, 9), (0, 7, 9, 16, 19)),
    "69": ((0, 2, 4, 7, 9), (0, 7, 9, 14, 16)),
    "m6": ((0, 3, 7, 9), (0, 7, 9, 15, 19)),
    "maj7": ((0, 4, 7, 11), (0, 7, 11, 16, 19)),
    "m7": ((0, 3, 7, 10), (0, 7, 10, 15, 19)),
    "7": ((0, 4, 7, 10), (0, 7, 10, 16, 19)),
    "7sus4": ((0, 5, 7, 10), (0, 7, 10, 12, 17)),
    "m7b5": ((0, 3, 6, 10), (0, 6, 10, 15, 18)),
}
_SYMBOL = re.compile(r"([A-G][#b]?)(maj7|m7b5|7sus4|add9|69|m6|m7|6|7|m|)(?:/([A-G][#b]?))?")

# Left-hand figures, as indexes into the voicing, one per eighth note. Indexes
# from 5 up continue through the chord tones above the voicing; -1 strikes the
# bass in octaves; None rests.
PATTERNS: dict[str, dict[int, tuple[int | None, ...]]] = {
    "wave": {8: (0, 1, 2, 3, 4, 3, 2, 1), 6: (0, 1, 2, 3, 4, 2), 4: (0, 1, 3, 4), 2: (0, 3)},
    "wave2": {8: (0, 1, 2, 3, 0, 2, 3, 4)},
    "calm": {8: (0, None, 2, None, 4, None, 3, None), 4: (0, None, 3, None)},
    "rise": {8: (0, 1, 2, 3, 4, 5, 6, None)},
    "climax": {8: (-1, 1, 2, 3, 4, 5, 4, 3), 4: (-1, 1, 2, 4)},
}


# Adaptive just intonation. Each chord's root keeps its equal-tempered pitch, so
# nothing drifts across a piece, and every other pitch class takes a 5-limit
# ratio above that root: pure 5:4 thirds (14 cents under the piano's), 3:2
# fifths, 6:5 minor thirds.
JUST_RATIOS: dict[int, float] = {0: 1, 1: 16 / 15, 2: 9 / 8, 3: 6 / 5, 4: 5 / 4, 5: 4 / 3, 6: 45 / 32,
                                 7: 3 / 2, 8: 8 / 5, 9: 5 / 3, 10: 16 / 9, 11: 15 / 8}
# Chord sevenths at 9:5 sit a pure minor third over the fifth (D-F in G7). The
# 7:4 barbershop seventh is purer alone but 31 cents flat, which bends melody
# lines that pass through it. 7sus4 keeps 16:9 so the sus fourth and the
# seventh stay a pure fourth apart. In m7b5 the upper three notes form a pure
# minor triad.
JUST_QUALITY: dict[str, dict[int, float]] = {
    "7": {10: 9 / 5},
    "m7": {10: 9 / 5},
    "m7b5": {6: 36 / 25, 10: 9 / 5},
}


def just_offsets(root: int, quality: str) -> list[float]:
    """Cents away from equal temperament for each pitch class, while one chord sounds."""
    out = [0.0] * 12
    for iv, ratio in {**JUST_RATIOS, **JUST_QUALITY.get(quality, {})}.items():
        out[(root + iv) % 12] = 1200 * math.log2(ratio) - 100 * iv
    return out


def voice(root: int, quality: str, bass: int) -> list[int]:
    """Five left-hand notes: the bass, then four chord tones in open spacing."""
    tones, shape = QUALITIES[quality]
    if bass % 12 == root:
        return [bass + i for i in shape]
    # An inversion: build the chord on the first root above the bass, inside a tenth or so.
    r = bass + (root - bass) % 12
    upper = [r + i for i in shape[:4] if r + i <= bass + 22]
    pcs = {(root + t) % 12 for t in tones}
    for p in range(bass + 7, bass + 23):
        if len(upper) >= 4:
            break
        if p % 12 in pcs and p not in upper and all(abs(p - q) > 1 for q in upper):
            upper.append(p)
    k = 0
    while len(upper) < 4:
        upper.append(sorted(upper)[k] + 12)
        k += 1
    return [bass, *sorted(upper)]


@dataclass
class Chord:
    symbol: str
    root: int
    quality: str
    pcs: frozenset[int]
    bass: int
    voicing: list[int]
    start: float
    beats: float

    @property
    def end(self) -> float:
        return self.start + self.beats


def parse_chords(spec: str, bar: int) -> list[Chord]:
    items = []
    for tok in (t.strip() for t in spec.split(",")):
        m = re.fullmatch(r"([^@]+)@([A-G][#b]?-?\d)(?::([\d.]+))?", tok)
        if not m:
            raise ValueError(f"bar {bar + 1}: bad chord {tok!r}")
        items.append((m[1], pitch(m[2]), float(m[3]) if m[3] else None))
    fixed = sum(b for *_, b in items if b is not None)
    free = [i for i in items if i[2] is None]
    share = (BEATS - fixed) / len(free) if free else 0.0
    out, pos = [], bar * BEATS
    for symbol, bass, beats in items:
        m = _SYMBOL.fullmatch(symbol)
        if not m:
            raise ValueError(f"bar {bar + 1}: unknown chord symbol {symbol!r}")
        root = pitch_class(m[1])
        if m[3] and pitch_class(m[3]) != bass % 12:
            raise ValueError(f"bar {bar + 1}: {symbol} does not match bass {note_name(bass)}")
        tones, _ = QUALITIES[m[2]]
        n = beats if beats is not None else share
        out.append(Chord(symbol, root, m[2], frozenset((root + t) % 12 for t in tones), bass,
                         voice(root, m[2], bass), pos, n))
        pos += n
    if abs(pos - (bar + 1) * BEATS) > 1e-9:
        raise ValueError(f"bar {bar + 1}: chords fill {pos - bar * BEATS} beats, not {BEATS}")
    return out


@dataclass
class Event:
    beat: float
    beats: float
    pitches: list[int]  # empty for a rest
    nct: bool
    bar: int


def parse_melody(spec: str, bar: int) -> list[Event]:
    out, pos = [], 0.0
    for tok in spec.split():
        head, _, dur = tok.partition(":")
        beats = float(dur) if dur else 1.0
        nct = head.endswith("!")
        head = head.rstrip("!")
        pitches = [] if head == "r" else [pitch(p) for p in head.split("+")]
        out.append(Event(bar * BEATS + pos, beats, pitches, nct, bar))
        pos += beats
    if abs(pos - BEATS) > 1e-9:
        raise ValueError(f"bar {bar + 1}: melody fills {pos} beats, not {BEATS}")
    return out


@dataclass
class Bar:
    chords: str
    melody: str
    bpm: float
    mel: int  # melody velocity at the downbeat
    acc: int  # accompaniment velocity at the downbeat
    lh: str = "wave"
    rh: str = "solo"
    ring: int = 0  # let the right hand ring through this many bars (0: play legato)
    section: int = 0


def section(rows: list[tuple], **defaults) -> list[Bar]:
    """Rows are (chords, melody, bpm, mel, acc[, {overrides}]); keywords set lh, rh, ring."""
    return [Bar(*row[:5], **{**defaults, **(row[5] if len(row) > 5 else {})}) for row in rows]


Pos = tuple[int, float]  # (bar, beat), both counted from 1 the way musicians count


@dataclass
class Piece:
    title: str
    sections: list[list[Bar]]
    transpose: int = 0
    key: str = "C"
    phrases: tuple[int, ...] = ()  # bars that start a phrase, for the rubato
    rits: tuple[tuple[Pos, Pos, float], ...] = ()  # slow to factor x tempo between two positions
    holds: tuple[tuple[Pos, float], ...] = ()  # extra seconds at a position (fermata, breath)
    rubato: float = 0.025  # tempo swell at mid-phrase
    seed: int = 1
    artist: str = "MIST"
    comment: str = ""

    @property
    def bars(self) -> list[Bar]:
        out = []
        for i, sec in enumerate(self.sections):
            for b in sec:
                b.section = i
                out.append(b)
        return out


def _beat(p: Pos) -> float:
    return (p[0] - 1) * BEATS + (p[1] - 1)


@dataclass
class Note:
    beat: float
    beats: float
    pitch: int
    hand: str  # rh or lh
    role: str  # top, double, inner (rh); bass, arp (lh)
    ref: int = 0  # melody pitch the note belongs to, for dynamics
    written: float = 0.0  # notated length, for the score MIDI
    delay: float = 0.0  # seconds added after the tempo map (rolled chords)
    legato_to: float | None = None  # next melody onset, if one follows directly
    ring_to: float | None = None
    vel: int = 64
    on: float = 0.0
    off: float = 0.0


def _inner(top: int, pcs: frozenset[int], intervals: tuple[int, ...]) -> int | None:
    for iv in intervals:
        if (top - iv) % 12 in pcs:
            return top - iv
    return None


def left_hand(ch: Chord, pattern: str) -> list[Note]:
    v = ch.voicing
    if pattern == "rolled":
        return [Note(ch.start, ch.beats, p, "lh", "bass" if k == 0 else "arp", written=ch.beats, delay=0.075 * k)
                for k, p in enumerate(v)]
    if pattern == "octave":
        return [Note(ch.start, ch.beats, p, "lh", "bass", written=ch.beats) for p in (v[0] - 12, v[0])]
    ext, p = list(v), v[-1] + 1
    while len(ext) < 9:
        if p % 12 in ch.pcs and p - ext[-1] >= 2:
            ext.append(p)
        p += 1
    n8 = round(ch.beats * 2)
    seq = PATTERNS[pattern].get(n8) or PATTERNS["wave"].get(n8)
    if seq is None:
        raise ValueError(f"no {pattern} figure for a chord of {ch.beats} beats")
    out = []
    for k, idx in enumerate(seq):
        at = ch.start + k / 2
        if idx is None:
            continue
        if idx == -1:  # bass octave, the lower note a hair early
            out.append(Note(at, ch.end - at, v[0] - 12, "lh", "bass", written=0.5, delay=-0.012))
            out.append(Note(at, ch.end - at, v[0], "lh", "bass", written=0.5))
        elif idx == 0:  # the bass is held by the finger until the harmony changes
            out.append(Note(at, ch.end - at, v[0], "lh", "bass", written=0.5))
        else:
            out.append(Note(at, min(0.75, ch.end - at), ext[idx], "lh", "arp", written=0.5))
    return out


def compose(piece: Piece) -> tuple[list[Bar], list[Chord], list[Note], list[str]]:
    """Expand the score into notes. Returns bars, chords, notes, and warnings."""
    bars = piece.bars
    chords = [c for i, b in enumerate(bars) for c in parse_chords(b.chords, i)]
    starts = [c.start for c in chords]

    def chord_at(beat: float) -> Chord:
        return chords[bisect.bisect_right(starts, beat + 1e-9) - 1]

    events = [e for i, b in enumerate(bars) for e in parse_melody(b.melody, i)]
    warnings: list[str] = []
    notes: list[Note] = []
    for k, e in enumerate(events):
        if not e.pitches:
            continue
        bar, ch = bars[e.bar], chord_at(e.beat)
        nxt = events[k + 1] if k + 1 < len(events) else None
        legato_to = e.beat + e.beats if nxt and nxt.pitches else None
        ring_to = (e.bar + bar.ring) * BEATS if bar.ring else None
        pos = e.beat - e.bar * BEATS
        if not e.nct and (e.beats >= 1 or pos in (0, 2)):
            for p in e.pitches:
                if p % 12 not in ch.pcs:
                    warnings.append(f"bar {e.bar + 1} beat {pos + 1:g}: {note_name(p)} is not in {ch.symbol}")

        def add(p: int, role: str, e: Event = e, lt: float | None = legato_to, rt: float | None = ring_to) -> None:
            notes.append(Note(e.beat, e.beats, p, "rh", role, ref=max(e.pitches), written=e.beats,
                              legato_to=lt, ring_to=rt))

        if len(e.pitches) > 1:
            for p in e.pitches:
                add(p, "top" if p == max(e.pitches) else "double")
            continue
        p = e.pitches[0]
        if bar.rh == "octaves":
            add(p + 12, "top")
            add(p, "double")
            q = _inner(p + 12, ch.pcs, (3, 4, 5)) if e.beats >= 1 else None
            if q is not None and q > p + 2:
                add(q, "inner")
        else:
            add(p, "top")
            q = _inner(p, ch.pcs, (3, 4, 8, 9, 5, 7)) if bar.rh == "duet" and e.beats >= 1 else None
            if q is not None:
                add(q, "inner")
    for ch in chords:
        notes += left_hand(ch, bars[int(ch.start // BEATS)].lh)

    # Keep the hands apart: a left-hand note must sit a minor third or more under
    # every right-hand note sounding with it.
    rh = [n for n in notes if n.hand == "rh"]
    moved = 0
    for n in (x for x in notes if x.hand == "lh"):
        while True:
            over = [r.pitch for r in rh if r.beat < n.beat + n.beats and n.beat < r.beat + r.beats]
            if not over or n.pitch <= min(over) - 3:
                break
            n.pitch -= 12
            moved += 1
    if moved:
        warnings.append(f"{moved} left-hand note(s) dropped an octave to clear the right hand")
    return bars, chords, notes, warnings


def tempo_map(piece: Piece, bars: list[Bar]) -> tuple[np.ndarray, np.ndarray]:
    """Beat grid and the performed time (seconds) of each grid point."""
    total = len(bars) * BEATS
    step = 1 / 48
    grid = np.arange(0.0, total + step / 2, step)
    phrase_starts = sorted({1, *piece.phrases})
    rits = [(_beat(a), _beat(z), f) for a, z, f in piece.rits]

    def bpm(b: float) -> float:
        i = min(int(b // BEATS), len(bars) - 1)
        frac = (b - i * BEATS) / BEATS
        nxt = bars[i + 1].bpm if i + 1 < len(bars) else bars[i].bpm
        v = bars[i].bpm + (nxt - bars[i].bpm) * frac
        bar_no = b / BEATS + 1
        s = max(p for p in phrase_starts if p <= bar_no + 1e-9)
        e = next((p for p in phrase_starts if p > bar_no + 1e-9), len(bars) + 1)
        v *= 1 + piece.rubato * math.sin(math.pi * (bar_no - s) / (e - s))
        for a, z, f in rits:
            if a <= b < z:
                v *= 1 + (f - 1) * (b - a) / (z - a)
        return v

    mids = grid[:-1] + step / 2
    dt = np.array([step * 60 / bpm(b) for b in mids])
    times = np.concatenate([[0.0], np.cumsum(dt)]) + LEAD_IN
    for p, secs in piece.holds:
        times[grid > _beat(p) + 1e-9] += secs
    return grid, times


def perform(piece: Piece, bars: list[Bar], chords: list[Chord], notes: list[Note]) -> list[tuple[float, int]]:
    """Set velocity, onset and release (seconds) on every note. Returns left-hand pedal events."""
    rng = random.Random(piece.seed)
    grid, times = tempo_map(piece, bars)

    def t(b: float) -> float:
        return float(np.interp(b, grid, times))

    def dyn(b: float, attr: str) -> float:
        i = min(int(b // BEATS), len(bars) - 1)
        v0 = float(getattr(bars[i], attr))
        if i + 1 < len(bars) and bars[i + 1].section == bars[i].section:
            v1 = float(getattr(bars[i + 1], attr))
            return v0 + (v1 - v0) * (b - i * BEATS) / BEATS
        return v0

    def clip(x: float, lim: float) -> float:
        return max(-lim, min(lim, x))

    for n in notes:
        pos = n.beat % BEATS
        accent = 3 if pos == 0 else 1 if pos == 2 else 0 if pos == int(pos) else -2
        if n.hand == "rh":
            v = dyn(n.beat, "mel") + clip(0.45 * (n.ref - 74), 7) + accent + (2 if n.beats >= 2 else 0)
            v -= {"top": 0, "double": 8, "inner": 17}[n.role]
            n.on = t(n.beat) + n.delay + (0.004 if n.role == "inner" else -0.012) + clip(rng.gauss(0, 0.005), 0.012)
            if n.ring_to is not None:
                n.off = t(n.ring_to) + 0.02
            elif n.legato_to is not None:
                n.off = t(n.legato_to) + (0.035 if n.role != "inner" else -0.01)
            else:
                n.off = t(n.beat + n.beats) - 0.03
        else:
            v = dyn(n.beat, "acc") + accent + (7 if n.role == "bass" else min(3.0, 0.12 * (n.pitch - 40)))
            n.on = t(n.beat) + n.delay + clip(rng.gauss(0, 0.007), 0.018)
            n.off = t(n.beat + n.beats) + (0.02 if n.role == "bass" else 0.0)
        n.vel = int(round(max(18, min(118, v + rng.gauss(0, 2.0)))))
        n.on = max(0.0, n.on)
        n.off = max(n.off, n.on + 0.06)

    # Legato pedal: lift just after the new bass sounds, press again 0.1 s later.
    pedals: list[tuple[float, int]] = []
    prev = None
    for ch in chords:
        key = (ch.symbol, ch.bass)
        if prev is None:
            pedals.append((t(ch.start) + 0.10, 127))
        elif key != prev:
            pedals += [(t(ch.start) + 0.015, 0), (t(ch.start) + 0.11, 127)]
        prev = key
    pedals.append((t(len(bars) * BEATS) + 0.4, 0))
    return pedals


def tuning_changes(chords: list[Chord], notes: list[Note], transpose: int) -> list[tuple[float, list[float]]]:
    """(seconds, offsets) for each chord whose just tuning differs from the one before.

    A change lands 3 ms before the first note of its chord and after every note
    of the chords before it. The MIDI Tuning messages are non-real-time, so
    notes that already sound keep their pitch and never slide.
    """
    changes: list[tuple[float, list[float]]] = []
    prev: list[float] | None = None
    for ch in chords:
        offsets = just_offsets((ch.root + transpose) % 12, ch.quality)
        if offsets == prev:
            continue
        mine = [n.on for n in notes if ch.start - 1e-9 <= n.beat < ch.end - 1e-9]
        before = [n.on for n in notes if n.beat < ch.start - 1e-9]
        at = min(mine) - 0.003 if mine else max(before, default=0.0) + 0.003
        if before and max(before) >= at:
            raise SystemExit(f"{ch.symbol} at beat {ch.start:g}: a note of the chord before it starts later")
        changes.append((max(0.0, at), offsets))
        prev = offsets
    return changes


def _tuning_sysex(offsets: list[float]) -> mido.Message:
    """MIDI Tuning Standard: non-real-time single-note tuning change, bank 0, program 0, keys 21-108."""
    data = [0x7E, 0x7F, 0x08, 0x07, 0, 0, 88]
    for key in range(21, 109):
        target = 100 * key + offsets[key % 12]
        semitone = int(target // 100)
        frac = round((target - 100 * semitone) / 100 * 16384)
        if frac == 16384:
            semitone, frac = semitone + 1, 0
        data += [key, semitone, frac >> 7, frac & 0x7F]
    return mido.Message("sysex", data=data)


def _select_tuning(channel: int) -> list[tuple[int, int, mido.Message]]:
    """RPN 4 (tuning bank) and RPN 3 (tuning program) set to 0, then the null RPN, at tick 0."""
    ccs = [(101, 0), (100, 4), (6, 0), (101, 0), (100, 3), (6, 0), (101, 127), (100, 127)]
    return [(0, -1, mido.Message("control_change", control=c, value=v, channel=channel)) for c, v in ccs]


def _note_events(notes: list[Note], channel: int, on_tick, off_tick) -> list[tuple[int, int, mido.Message]]:
    """Note on/off pairs; a repeated key is released one tick before it is struck again."""
    ev: list[tuple[int, int, mido.Message]] = []
    by_key: dict[int, list[Note]] = {}
    for n in sorted(notes, key=on_tick):
        by_key.setdefault(n.pitch, []).append(n)
    for key, ns in by_key.items():
        for a, b in zip(ns, [*ns[1:], None], strict=True):
            on, off = on_tick(a), off_tick(a)
            if b is not None:
                off = min(off, on_tick(b) - 1)
            off = max(off, on + 1)
            ev.append((on, 2, mido.Message("note_on", note=key, velocity=a.vel, channel=channel)))
            ev.append((off, 0, mido.Message("note_off", note=key, velocity=0, channel=channel)))
    return ev


def _track(name: str, channel: int, events: list[tuple[int, int, mido.Message]]) -> mido.MidiTrack:
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("track_name", name=name, time=0))
    tr.append(mido.Message("program_change", program=0, channel=channel, time=0))
    last = 0
    for tick, _, msg in sorted(events, key=lambda e: (e[0], e[1])):
        tr.append(msg.copy(time=tick - last))
        last = tick
    tr.append(mido.MetaMessage("end_of_track", time=0))
    return tr


def write_performance(path: Path, piece: Piece, notes: list[Note], pedals: list[tuple[float, int]],
                      tuning: list[tuple[float, list[float]]] | None = None) -> float:
    """Real-time MIDI: 60 BPM, so one beat is one second and every tick is 1/960 s.
    With a tuning, both hands select tuning 0/0 and the changes ride on the right-hand track."""
    tpb = 960
    mid = mido.MidiFile(type=1, ticks_per_beat=tpb)
    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("track_name", name=piece.title, time=0))
    conductor.append(mido.MetaMessage("set_tempo", tempo=1_000_000, time=0))
    mid.tracks.append(conductor)
    end = max(n.off for n in notes) + TAIL

    def tick(s: float) -> int:
        return int(round(s * tpb))

    for ch, hand, name in ((0, "rh", "Right hand"), (1, "lh", "Left hand")):
        ev = _note_events([n for n in notes if n.hand == hand], ch, lambda n: tick(n.on), lambda n: tick(n.off))
        if hand == "lh":
            ev += [(tick(s), 1, mido.Message("control_change", control=64, value=v, channel=1)) for s, v in pedals]
        if tuning:
            ev += _select_tuning(ch)
            if hand == "rh":
                ev += [(tick(s), 1, _tuning_sysex(offsets)) for s, offsets in tuning]
        # A silent controller at the very end keeps the renderer running through the tail.
        ev.append((tick(end), 1, mido.Message("control_change", control=91, value=0, channel=ch)))
        mid.tracks.append(_track(name, ch, ev))
    mid.save(path)
    return end


def write_score(path: Path, piece: Piece, bars: list[Bar], chords: list[Chord], notes: list[Note]) -> None:
    """Quantized MIDI with tempo, key and meter, for notation software."""
    tpb = 480
    mid = mido.MidiFile(type=1, ticks_per_beat=tpb)
    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("track_name", name=piece.title, time=0))
    conductor.append(mido.MetaMessage("key_signature", key=piece.key, time=0))
    conductor.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    last = 0
    for i, b in enumerate(bars):
        tick = i * BEATS * tpb
        conductor.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(b.bpm), time=tick - last))
        last = tick
    mid.tracks.append(conductor)

    def tick_of(beat: float) -> int:
        return int(round(beat * tpb))

    pedal, prev = [], None
    for ch in chords:
        if (ch.symbol, ch.bass) != prev:
            if prev is not None:
                pedal.append((tick_of(ch.start), 1, mido.Message("control_change", control=64, value=0, channel=1)))
            pedal.append((tick_of(ch.start) + 1, 1, mido.Message("control_change", control=64, value=127, channel=1)))
        prev = (ch.symbol, ch.bass)
    pedal.append((tick_of(len(bars) * BEATS), 1, mido.Message("control_change", control=64, value=0, channel=1)))
    for ch, hand, name in ((0, "rh", "Right hand"), (1, "lh", "Left hand")):
        ev = _note_events([n for n in notes if n.hand == hand], ch,
                          lambda n: tick_of(n.beat), lambda n: tick_of(n.beat + n.written))
        mid.tracks.append(_track(name, ch, ev + (pedal if hand == "lh" else [])))
    mid.save(path)


def render(midi: Path, wav: Path, sf2: Path, sr: int = 48000) -> None:
    """FluidSynth, dry: its own reverb and chorus stay off because master() adds the room."""
    fs = shutil.which("fluidsynth") or "/opt/homebrew/bin/fluidsynth"
    cmd = [fs, "-ni", "-q", "-R", "0", "-C", "0", "-g", "0.5", "-r", str(sr), "-O", "float",
           "-o", "synth.polyphony=1024", "-F", str(wav), str(sf2), str(midi)]
    # stderr only carries the "no preset on channel 9" drum notice unless something breaks.
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise SystemExit(f"fluidsynth failed ({r.returncode}):\n{r.stderr}")


def hall_ir(sr: int, seconds: float = 3.4, seed: int = 7) -> np.ndarray:
    """Stereo impulse response for a medium concert hall, synthesized.

    Band-limited noise decays faster in the high bands than in the low ones, the
    way air and soft surfaces absorb treble. A 20 ms pre-delay and a short
    build-up stand in for the early reflections.
    """
    rng = np.random.default_rng(seed)
    n = int(sr * seconds)
    t = np.arange(n) / sr
    bands = ((None, 200, 2.4), (200, 800, 2.2), (800, 2500, 1.9), (2500, 6000, 1.4), (6000, None, 0.9))
    ir = np.zeros((n, 2))
    for c in range(2):
        noise = rng.standard_normal(n)
        for lo, hi, rt60 in bands:
            if lo is None:
                sos = butter(4, hi, "lowpass", fs=sr, output="sos")
            elif hi is None:
                sos = butter(4, lo, "highpass", fs=sr, output="sos")
            else:
                sos = butter(4, [lo, hi], "bandpass", fs=sr, output="sos")
            ir[:, c] += sosfiltfilt(sos, noise) * np.exp(-6.908 * t / rt60)
    ir *= (1 - np.exp(-t / 0.015))[:, None]
    ir = np.vstack([np.zeros((int(0.02 * sr), 2)), ir])
    return ir / np.sqrt((ir**2).sum(axis=0))


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x**2)))


def limit(y: np.ndarray, sr: int, ceiling: float) -> np.ndarray:
    """Look-ahead peak limiter. The gain holds its lowest value for 60 ms and moves in
    20 ms ramps, and it never lets a sample pass the ceiling: every gain sample is a
    mean of minimums over windows that all contain that sample."""
    need = np.minimum(1.0, ceiling / np.maximum(np.abs(y).max(axis=1), 1e-12))
    hold, ramp = int(0.06 * sr), int(0.02 * sr)
    g = minimum_filter1d(need, size=hold, origin=-(hold // 2))  # min over the next `hold` samples
    g = uniform_filter1d(g, size=ramp, origin=(ramp - 1) // 2)  # mean over the last `ramp` samples
    return y * g[:, None]


def master(wav_in: Path, mp3_out: Path, meta: dict[str, str], wet_db: float = -9.0, target_lufs: float = -18.0,
           max_boost_db: float = 5.0, ceiling_db: float = -1.2) -> float:
    """Hall reverb, fade, loudness, MP3. Returns the length in seconds.

    Loudness: peak-normalize to the ceiling, measure, then raise the level toward
    target_lufs by at most max_boost_db and let the limiter hold the peaks. For
    a solo piano that shaves only the loudest chords of the climax.
    """
    with warnings.catch_warnings():  # FluidSynth writes a LIST chunk that scipy skips
        warnings.simplefilter("ignore", wavfile.WavFileWarning)
        sr, x = wavfile.read(wav_in)
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    x = np.asarray(sosfilt(butter(2, 28, "highpass", fs=sr, output="sos"), x, axis=0))
    ir = hall_ir(sr)
    wet = np.stack([oaconvolve(x[:, c], ir[:, c]) for c in range(2)], axis=1)
    dry = np.vstack([x, np.zeros((len(wet) - len(x), 2))])
    y = dry + 10 ** (wet_db / 20) * _rms(dry) / _rms(wet) * wet
    env = np.abs(y).max(axis=1)
    last = int(np.nonzero(env > env.max() * 10 ** (-72 / 20))[0][-1]) + int(0.3 * sr)
    y = y[: min(last, len(y))]
    fade = int(1.0 * sr)
    y[-fade:] *= (np.linspace(1.0, 0.0, fade) ** 2)[:, None]
    ceiling = 10 ** (ceiling_db / 20)
    y *= ceiling / np.abs(y).max()
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "master.wav"
        wavfile.write(tmp, sr, y.astype(np.float32))
        boost = min(max_boost_db, max(0.0, target_lufs - loudness(tmp)[0]))
        if boost > 0:
            y = limit(y * 10 ** (boost / 20), sr, ceiling)
            wavfile.write(tmp, sr, y.astype(np.float32))
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(tmp), "-c:a", "libmp3lame", "-b:a", "320k"]
        for k, v in meta.items():
            cmd += ["-metadata", f"{k}={v}"]
        subprocess.run([*cmd, str(mp3_out)], check=True)
    return len(y) / sr


def loudness(path: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBTP), measured by ffmpeg's EBU R128 filter."""
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True, check=True)
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])
    peak = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", r.stderr)[-1])
    return lufs, peak


def _k_weighted(x: np.ndarray) -> np.ndarray:
    """ITU-R BS.1770 K-weighting; the coefficients are the standard's 48 kHz values."""
    shelf = np.asarray(sosfilt(np.array([[1.53512485958697, -2.69169618940638, 1.19839281085285, 1.0,
                                          -1.69065929318241, 0.73248077421585]]), x, axis=0))
    return np.asarray(sosfilt(np.array([[1.0, -2.0, 1.0, 1.0, -1.99004745483398, 0.99007225036621]]), shelf, axis=0))


def balance(piece: Piece, bars: list[Bar], perf_mid: Path, sf2: Path) -> None:
    """Render each hand alone and print its loudness per section.

    A melody sings when it sits a few LU over the accompaniment. Pedaled
    arpeggios pile up, so matching velocities is not enough; this measures it.
    """
    grid, times = tempo_map(piece, bars)
    full = mido.MidiFile(perf_mid)
    stems = []
    with tempfile.TemporaryDirectory() as td:
        for track in (1, 2):
            mf = mido.MidiFile(type=1, ticks_per_beat=full.ticks_per_beat)
            mf.tracks = [full.tracks[0], full.tracks[track]]
            mid, wav = Path(td) / f"hand{track}.mid", Path(td) / f"hand{track}.wav"
            mf.save(mid)
            render(mid, wav, sf2)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", wavfile.WavFileWarning)
                sr, x = wavfile.read(wav)
            stems.append(_k_weighted(np.asarray(x, dtype=np.float64)))

    def lufs(x: np.ndarray, a: float, z: float) -> float:
        seg = x[int(a * sr): int(z * sr)]
        return -0.691 + 10 * math.log10(float(np.sum(np.mean(seg**2, axis=0))) + 1e-20)

    print(f"{'bars':<9}{'melody':>8}{'accomp':>8}   melody over accompaniment")
    first = 0
    for sec in piece.sections:
        a, z = (float(np.interp(b * BEATS, grid, times)) for b in (first, first + len(sec)))
        rh, lh = lufs(stems[0], a, z), lufs(stems[1], a, z)
        print(f"{first + 1:>3}-{first + len(sec):<5}{rh:8.1f}{lh:8.1f}   {rh - lh:+5.1f} LU")
        first += len(sec)


def dump(bars: list[Bar], chords: list[Chord], transpose: int, just: bool = False) -> None:
    for i, b in enumerate(bars):
        here = [c for c in chords if int(c.start // BEATS) == i]
        harmony = "  ".join(f"{c.symbol}[{' '.join(note_name(p + transpose) for p in c.voicing)}]" for c in here)
        print(f"{i + 1:>3} {b.lh:<7}{b.rh:<8}{b.bpm:>4g} {b.mel:>3}/{b.acc:<3} {harmony}\n{'':>28}{b.melody}")
        for c in here if just else []:
            offsets = just_offsets((c.root + transpose) % 12, c.quality)
            tones = sorted({(pc + transpose) % 12 for pc in c.pcs}, key=lambda pc: (pc - c.root - transpose) % 12)
            cents = ", ".join(f"{_FLAT_NAMES[pc]} {offsets[pc]:+.1f}" for pc in tones)
            print(f"{'':>28}just {c.symbol}: {cents}")


def main(piece: Piece) -> None:
    ap = argparse.ArgumentParser(description=f"Perform and render '{piece.title}'.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder (default: harness tmp/audio)")
    ap.add_argument("--soundfont", type=Path, default=DEFAULT_SF2)
    ap.add_argument("--wet", type=float, default=-9.0, help="hall level in dB against the dry piano")
    ap.add_argument("--lufs", type=float, default=-18.0, help="loudness target (the boost stops at +5 dB)")
    ap.add_argument("--midi-only", action="store_true", help="write the MIDI files and stop")
    ap.add_argument("--dump", action="store_true", help="print each bar's voicings and melody")
    ap.add_argument("--balance", action="store_true", help="measure melody against accompaniment per section")
    ap.add_argument("--tuning", choices=("equal", "just"), default="equal",
                    help="just: retune every chord to pure ratios above its root (writes *-just files)")
    args = ap.parse_args()
    just = args.tuning == "just"

    bars, chords, notes, warnings = compose(piece)
    for w in warnings:
        print(f"warning: {w}")
    if args.dump:
        dump(bars, chords, piece.transpose, just)
    pedals = perform(piece, bars, chords, notes)
    for n in notes:
        n.pitch += piece.transpose
    tuning = tuning_changes(chords, notes, piece.transpose) if just else None
    slug = re.sub(r"[^a-z0-9]+", "-", piece.title.lower()).strip("-")
    tag = "-just" if just else ""
    args.out.mkdir(parents=True, exist_ok=True)
    perf_mid, score_mid, mp3 = (args.out / f"{slug}{tag}.mid", args.out / f"{slug}-score.mid",
                                args.out / f"{slug}{tag}.mp3")
    end = write_performance(perf_mid, piece, notes, pedals, tuning)
    if tuning:
        print(f"{len(tuning)} tuning changes (adaptive just intonation, roots in equal temperament)")
    write_score(score_mid, piece, bars, chords, notes)
    lo, hi = min(n.pitch for n in notes), max(n.pitch for n in notes)
    print(f"{len(bars)} bars, {len(notes)} notes, {note_name(lo)}-{note_name(hi)}, {end - TAIL:.1f} s performed")
    print(f"wrote {perf_mid}\nwrote {score_mid}")
    if args.midi_only:
        return
    if not args.soundfont.exists():
        raise SystemExit(f"soundfont not found: {args.soundfont}")
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "dry.wav"
        render(perf_mid, wav, args.soundfont)
        title = f"{piece.title} (just intonation)" if just else piece.title
        seconds = master(wav, mp3, {"title": title, "artist": piece.artist, "comment": piece.comment},
                         wet_db=args.wet, target_lufs=args.lufs)
    lufs, peak = loudness(mp3)
    print(f"wrote {mp3}  ({seconds:.1f} s, {lufs:.1f} LUFS, true peak {peak:.1f} dBTP)")
    if args.balance:
        balance(piece, bars, perf_mid, args.soundfont)
