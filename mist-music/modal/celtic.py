"""celtic: play a score as an Irish session band, in code.

A piece file writes each part as a list of Tone records on a sixteenth-note
grid. This module turns the parts into sound:

  whistle()   a synthesized tin whistle. One breath is one continuous tone, so
              a slur is a pitch change with no new attack, and a cut, a tap or
              a roll is a 24 ms pitch flick inside the note. That is how the
              ornaments work on the real instrument.
  bodhran()   a synthesized frame drum: a skin tone that falls in pitch after
              the strike, two inharmonic partials, and the click of the tipper.
              Hand pressure (tone) raises and shortens the note.
  MidiPart    parts for sampled instruments (fiddle, banjo, guitar, harp, bass,
              pipe drone), rendered by FluidSynth. Fiddle slides, cuts and
              vibrato are pitch-bend curves, and tuning_table() measures the
              pitch error of each sample so that bowed() can correct it.
  mixdown()   sets each stem to a loudness target, adds one room, and masters.

The grid: 16 slots per bar of 4/4. Clock.lilt delays the second sixteenth of
each pair, which is the swing of a reel (0.5 is straight).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import mido
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, oaconvolve, sosfilt, sosfiltfilt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "piano"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "loops"))
from loopkit import k_weighted  # noqa: E402  (a sibling folder, on the path from the lines above)
from pianokit import limit, loudness  # noqa: E402

SR = 48000
HARNESS = Path(__file__).resolve().parents[2]
OUT = HARNESS / "tmp" / "audio"
CACHE = HARNESS / "tmp" / "modal-cache"
GM_BANK = Path.home() / "Library/Audio/Sounds/Banks/FluidR3Mono_GM.sf3"
FONTS = Path(__file__).resolve().parent / "soundfonts"

# General MIDI programs used here (0-based)
STEEL_GUITAR, ACOUSTIC_BASS, HARP, BANJO, FIDDLE, BAGPIPE = 25, 32, 46, 105, 110, 109


@dataclass
class Clock:
    bpm: float
    lilt: float = 0.5        # position of the second sixteenth inside its pair
    lead_in: float = 0.6     # seconds before bar 1

    def t(self, slot: float) -> float:
        six = 60.0 / self.bpm / 4
        pair, frac = divmod(slot, 2.0)
        pos = frac * 2 * self.lilt if frac < 1 else 2 * self.lilt + (frac - 1) * (2 - 2 * self.lilt)
        return self.lead_in + (pair * 2 + pos) * six


@dataclass
class Tone:
    slot: float              # start, in sixteenths from bar 1
    dur: float               # length in sixteenths
    pitch: int               # MIDI
    vel: float = 0.8         # 0..1
    slur: bool = False       # joined to the note before it: no new breath, bow or pick
    cut: int = 0             # semitones above, for a flick at the start of the note
    tap: int = 0             # semitones below, for a flick at the start (or the second flick of a roll)
    roll: bool = False       # cut and tap inside the note (whistle, fiddle); a picked triplet (banjo)
    slide: float = 0.0       # start this many semitones flat and rise to the note
    vib: bool = True
    stacc: float = 1.0       # part of the written length that sounds


@dataclass
class Stroke:
    slot: float
    vel: float = 0.7
    kind: str = "D"          # D down stroke, U up stroke, T the tipper on the rim
    tone: float = 0.0        # 0 open skin, 1 pressed with the hand: higher and shorter


def _ramp(n: int) -> np.ndarray:
    return 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, max(n, 1)))


def _band(x: np.ndarray, lo: float | None, hi: float | None, order: int = 2) -> np.ndarray:
    if lo is None:
        sos = butter(order, hi, "lowpass", fs=SR, output="sos")
    elif hi is None:
        sos = butter(order, lo, "highpass", fs=SR, output="sos")
    else:
        sos = butter(order, [lo, hi], "bandpass", fs=SR, output="sos")
    return np.asarray(sosfilt(sos, x))


def _unit(x: np.ndarray) -> np.ndarray:
    return x / max(float(np.sqrt(np.mean(x**2))), 1e-12)


# ---------------------------------------------------------------- tin whistle

def whistle(tones: Sequence[Tone], clock: Clock, total: float, seed: int = 1) -> np.ndarray:
    """A mono tin whistle line. Tones must not overlap."""
    rng = np.random.default_rng(seed)
    n = int(total * SR)
    pitch, amp = np.zeros(n), np.zeros(n)
    filled = np.zeros(n, dtype=bool)
    onsets: list[tuple[int, float]] = []
    line = sorted(tones, key=lambda x: x.slot)
    blip = int(0.024 * SR)
    for i, tn in enumerate(line):
        nxt = line[i + 1] if i + 1 < len(line) else None
        joined = nxt is not None and nxt.slur and abs(nxt.slot - (tn.slot + tn.dur)) < 1e-6
        t0 = clock.t(tn.slot) + (0.0 if tn.slur else float(rng.normal(0, 0.004)))
        full = clock.t(tn.slot + tn.dur) - clock.t(tn.slot)
        t1 = clock.t(tn.slot + tn.dur) if joined else t0 + max(0.05, full * tn.stacc - 0.012)
        a0, a1 = max(0, int(t0 * SR)), min(n, int(t1 * SR))
        m = a1 - a0
        if m <= 0:
            continue
        seg = np.full(m, tn.pitch + float(rng.normal(0, 0.025)))
        if tn.roll and m > 5 * blip:
            k1, k2 = m // 3, 2 * m // 3
            seg[k1:k1 + blip] = tn.pitch + (tn.cut or 2)
            seg[k2:k2 + blip] = tn.pitch - (tn.tap or 2)
        elif tn.cut:
            seg[:min(blip, m // 2)] = tn.pitch + tn.cut
        elif tn.tap:
            seg[:min(blip, m // 2)] = tn.pitch - tn.tap
        if tn.slide:
            sl = min(m, int(0.085 * SR))
            seg[:sl] -= tn.slide * (1 - np.linspace(0, 1, sl)) ** 1.6
        if tn.vib and m / SR > 0.5:
            tt = np.arange(m) / SR
            seg += 0.10 * np.clip((tt - 0.28) / 0.3, 0, 1) * np.sin(2 * np.pi * 5.3 * tt)
        env = np.full(m, (0.5 + 0.5 * tn.vel) * (1 + 0.012 * (tn.pitch - 81)))
        if tn.slur:
            d = min(m, int(0.010 * SR))
            env[:d] *= 0.8 + 0.2 * _ramp(d)
        else:
            a = min(m, int(0.012 * SR))
            env[:a] *= _ramp(a)
            push = min(m, int(0.07 * SR))
            env[:push] *= 1 + 0.14 * (1 - np.linspace(0, 1, push))
            onsets.append((a0, tn.vel))
        if not joined:
            r = min(m, int(0.025 * SR))
            env[-r:] *= _ramp(r)[::-1]
        pitch[a0:a1], amp[a0:a1], filled[a0:a1] = seg, env, True
    if not filled.any():
        return np.zeros(n)
    idx = np.where(filled, np.arange(n), 0)
    np.maximum.accumulate(idx, out=idx)
    first = int(np.argmax(filled))
    idx[:first] = first
    pitch = pitch[idx]
    k = int(0.003 * SR)  # a finger takes about 3 ms to open or close a hole
    pitch = np.convolve(np.pad(pitch, k, mode="edge"), np.ones(k) / k, mode="same")[k:-k]
    phase = 2 * np.pi * np.cumsum(440.0 * 2 ** ((pitch - 69) / 12)) / SR
    breath = _unit(_band(rng.standard_normal(n), None, 350.0))
    body = amp * (1 + 0.05 * breath)
    bright = 0.75 + 0.5 * amp / max(float(amp.max()), 1e-9)
    h2 = np.clip(0.26 - 0.011 * (pitch - 74), 0.05, 0.28) * bright  # the low octave has more overtones
    tone = np.sin(phase) + h2 * np.sin(2 * phase + 0.6) + 0.45 * h2 * np.sin(3 * phase + 1.1) + 0.12 * h2 * np.sin(4 * phase)
    out = body * tone + amp * 0.030 * _unit(_band(rng.standard_normal(n), 2500.0, 9000.0))
    chiff = _unit(_band(rng.standard_normal(n), 1200.0, 6000.0))
    ln = int(0.03 * SR)
    decay = np.exp(-np.arange(ln) / (0.007 * SR))
    for a0, vel in onsets:
        e = min(n, a0 + ln)
        out[a0:e] += 0.11 * vel * chiff[a0:e] * decay[: e - a0]
    return out * 0.35


# ---------------------------------------------------------------- bodhran

def bodhran(strokes: Iterable[Stroke], clock: Clock, total: float, seed: int = 3,
            tuning: Sequence[float] = (110.0, 123.47, 146.83, 164.81)) -> np.ndarray:
    """A frame drum. `tuning` is the skin pitch in Hz from open (tone 0) to pressed (tone 1).
    Give it tones of the scale: the default is A2 B2 D3 E3. With a skin at 92 to 140 Hz and
    no relation to the key, 30% of the low band of an A Dorian mix was on A flat and B flat."""
    rng = np.random.default_rng(seed)
    n = int(total * SR)
    out = np.zeros(n + SR)
    click = _unit(_band(rng.standard_normal(n + SR), 1200.0, 5000.0))
    thud = _unit(_band(rng.standard_normal(n + SR), None, 600.0))
    for s in strokes:
        a0 = int((clock.t(s.slot) + float(rng.normal(0, 0.003))) * SR)
        if a0 < 0 or a0 >= n:
            continue
        if s.kind == "T":
            ln = int(0.05 * SR)
            t = np.arange(ln) / SR
            w = 0.5 * click[a0:a0 + ln] * np.exp(-t / 0.005) + 0.3 * np.sin(2 * np.pi * 830 * t) * np.exp(-t / 0.012)
        else:
            up = s.kind == "U"
            f0 = tuning[int(round(float(np.clip(s.tone, 0, 1)) * (len(tuning) - 1)))] * (1 + float(rng.normal(0, 0.004)))
            tau = (0.13 - 0.07 * s.tone) * (0.75 if up else 1.0)
            ln = int(min(0.6, tau * 7) * SR)
            t = np.arange(ln) / SR
            ph = 2 * np.pi * np.cumsum(f0 * (1 + 0.5 * np.exp(-t / 0.006))) / SR
            w = (np.sin(ph) * np.exp(-t / tau) + 0.42 * np.sin(1.59 * ph + 0.7) * np.exp(-t / (tau * 0.5))
                 + 0.20 * np.sin(2.14 * ph + 1.3) * np.exp(-t / (tau * 0.35)) + 0.10 * np.sin(2.65 * ph) * np.exp(-t / (tau * 0.25))
                 + (0.30 if up else 0.22) * click[a0:a0 + ln] * np.exp(-t / 0.0045) + 0.25 * thud[a0:a0 + ln] * np.exp(-t / 0.02))
        w = w * s.vel**1.4
        w[:72] *= _ramp(72)
        out[a0:a0 + len(w)] += w
    return out[:n] * 0.5


# ---------------------------------------------------------------- sampled instruments

class MidiPart:
    """Events for one FluidSynth render. Times are seconds, bends are cents."""

    TPS = 1920.0  # ticks per second: 960 ticks per beat at 120 BPM

    def __init__(self, programs: dict[int, int], bend_range: int = 2) -> None:
        self.programs, self.bend_range = programs, bend_range
        self.ev: list[tuple[int, int, mido.Message]] = []

    def _add(self, t: float, order: int, msg: mido.Message) -> None:
        self.ev.append((max(0, int(round(t * self.TPS))), order, msg))

    def note(self, ch: int, t0: float, t1: float, pitch: int, vel: float) -> None:
        self._add(t0, 2, mido.Message("note_on", channel=ch, note=pitch, velocity=int(np.clip(vel, 1, 127))))
        self._add(max(t1, t0 + 0.02), 0, mido.Message("note_off", channel=ch, note=pitch, velocity=0))

    def bend(self, ch: int, t: float, cents: float) -> None:
        val = int(np.clip(round(cents / (100.0 * self.bend_range) * 8192), -8192, 8191))
        self._add(t, 1, mido.Message("pitchwheel", channel=ch, pitch=val))

    def cc(self, ch: int, t: float, num: int, val: float) -> None:
        self._add(t, 1, mido.Message("control_change", channel=ch, control=num, value=int(np.clip(val, 0, 127))))

    def save(self, path: Path, total: float) -> None:
        mid = mido.MidiFile(ticks_per_beat=960)
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        tr.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
        for ch, prog in self.programs.items():
            tr.append(mido.Message("program_change", channel=ch, program=prog, time=0))
            for num, val in ((101, 0), (100, 0), (6, self.bend_range), (38, 0), (101, 127), (100, 127)):
                tr.append(mido.Message("control_change", channel=ch, control=num, value=val, time=0))
        last = 0
        end = int(total * self.TPS)
        events = sorted(self.ev, key=lambda e: (e[0], e[1])) + [(end, 3, mido.Message("control_change", channel=0, control=123, value=0))]
        for tick, _, msg in events:
            tr.append(msg.copy(time=max(0, tick - last)))
            last = max(last, tick)
        mid.save(path)

    def render(self, sf2: Path, total: float, gain: float = 0.6) -> np.ndarray:
        """Stereo float audio, dry: the room comes later, in mixdown()."""
        fs = shutil.which("fluidsynth") or "/opt/homebrew/bin/fluidsynth"
        with tempfile.TemporaryDirectory() as td:
            mid, wav = Path(td) / "part.mid", Path(td) / "part.wav"
            self.save(mid, total)
            r = subprocess.run([fs, "-ni", "-q", "-R", "0", "-C", "0", "-g", str(gain), "-r", str(SR), "-O", "float",
                                "-o", "synth.polyphony=512", "-F", str(wav), str(sf2), str(mid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if r.returncode != 0 or not wav.exists():
                raise SystemExit(f"fluidsynth failed ({r.returncode}):\n{r.stderr}")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", wavfile.WavFileWarning)
                _, x = wavfile.read(wav)
        x = np.asarray(x, dtype=np.float64)
        if x.ndim == 1:
            x = np.stack([x, x], axis=1)
        n = int(total * SR)
        out = np.zeros((n, 2))
        out[: min(n, len(x))] = x[:n]
        return out


def tuning_table(sf2: Path, program: int, pitches: Iterable[int]) -> dict[int, float]:
    """Pitch error of each note of a preset, in cents (positive = sharp), measured from a
    render of the held note. Sample sets are often 5 to 15 cents off on some keys."""
    want = sorted(set(pitches))
    CACHE.mkdir(parents=True, exist_ok=True)
    store = CACHE / f"tuning-{sf2.stem}-{program}.json"
    known: dict[int, float] = {int(k): v for k, v in json.loads(store.read_text()).items()} if store.exists() else {}
    todo = [p for p in want if p not in known]
    if todo:
        part = MidiPart({0: program})
        for i, p in enumerate(todo):
            part.note(0, 0.1 + i * 1.5, 0.1 + i * 1.5 + 0.9, p, 100)
        x = part.render(sf2, 0.1 + len(todo) * 1.5 + 0.5).mean(axis=1)
        nfft = 1 << 18
        f = np.fft.rfftfreq(nfft, 1 / SR)
        for i, p in enumerate(todo):
            a = int((0.1 + i * 1.5 + 0.35) * SR)
            seg = x[a:a + int(0.5 * SR)]
            sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), nfft))
            f_exp = 440.0 * 2 ** ((p - 69) / 12)
            m = np.nonzero((f > f_exp * 0.955) & (f < f_exp * 1.045))[0]
            k = int(m[np.argmax(sp[m])])
            y0, y1, y2 = np.log(sp[k - 1:k + 2] + 1e-20)
            peak = f[k] + (f[1] - f[0]) * 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
            known[p] = round(float(1200 * np.log2(peak / f_exp)), 2)
        store.write_text(json.dumps({str(k): v for k, v in sorted(known.items())}))
    return {p: known[p] for p in want}


def bowed(part: MidiPart, tones: Sequence[Tone], clock: Clock, chans: tuple[int, ...] = (0, 1),
          tuning: dict[int, float] | None = None, seed: int = 2, vel: tuple[int, int] = (56, 124)) -> None:
    """A fiddle line. Notes alternate between channels so that the bend curve of one
    note does not move the release of the note before it."""
    rng = np.random.default_rng(seed)
    for i, tn in enumerate(sorted(tones, key=lambda x: x.slot)):
        ch = chans[i % len(chans)]
        t0 = clock.t(tn.slot) + float(rng.normal(0, 0.005))
        full = clock.t(tn.slot + tn.dur) - clock.t(tn.slot)
        sec = max(0.06, full * tn.stacc + (0.02 if tn.slur else -0.012))
        base = -(tuning or {}).get(tn.pitch, 0.0)
        pts: list[tuple[float, float]] = [(t0 - 0.004, base)]
        if tn.slide:
            pts = [(t0 - 0.004 + 0.09 * q, base - 100 * tn.slide * (1 - q) ** 1.6) for q in np.linspace(0, 1, 9)]
        elif tn.cut and not tn.roll:
            pts = [(t0 - 0.004, base + 100 * tn.cut), (t0 + 0.03, base)]
        if tn.roll and sec > 0.3:
            for frac, off in ((1 / 3, 100.0 * (tn.cut or 2)), (2 / 3, -100.0 * (tn.tap or 2))):
                pts += [(t0 + sec * frac, base + off), (t0 + sec * frac + 0.028, base)]
        elif tn.vib and sec >= 0.45:
            for tv in np.arange(0.22, sec, 0.012):
                depth = 13.0 * min(1.0, (tv - 0.22) / 0.3)
                pts.append((t0 + float(tv), base + depth * float(np.sin(2 * np.pi * 5.6 * tv))))
        for tb, cents in pts:
            part.bend(ch, tb, cents)
        part.note(ch, t0, t0 + sec, tn.pitch, vel[0] + (vel[1] - vel[0]) * tn.vel)


def plucked(part: MidiPart, ch: int, tones: Sequence[Tone], clock: Clock, ring: float = 0.7, seed: int = 4,
            vel: tuple[int, int] = (48, 122), jitter: float = 0.004) -> None:
    """Banjo, harp, bass or a single guitar string. A Tone with roll=True is a picked triplet."""
    rng = np.random.default_rng(seed)
    for tn in tones:
        t0 = clock.t(tn.slot) + float(rng.normal(0, jitter))
        full = clock.t(tn.slot + tn.dur) - clock.t(tn.slot)
        v = vel[0] + (vel[1] - vel[0]) * tn.vel
        if tn.roll:
            third = min(full, 60.0 / clock.bpm / 2) / 3
            for k, (dp, dv) in enumerate(((0, 1.0), (tn.cut, 0.72), (0, 0.86))):
                part.note(ch, t0 + k * third, t0 + (k + 1) * third + (0.0 if k < 2 else max(0.0, full - 3 * third)),
                          tn.pitch + dp, v * dv)
        else:
            part.note(ch, t0, t0 + min(max(full * tn.stacc, 0.09), max(ring, 0.09)), tn.pitch, v)


def strum(part: MidiPart, ch: int, clock: Clock, slot: float, pitches: Sequence[int], vel: float, down: bool = True,
          ring: float = 3.0, spread: float = 0.011, rng: np.random.Generator | None = None) -> None:
    """One strum: the strings sound a few milliseconds apart, low to high on a down stroke."""
    order = list(pitches) if down else list(pitches)[::-1]
    t0 = clock.t(slot) + (float(rng.normal(0, 0.004)) if rng is not None else 0.0)
    t1 = clock.t(slot + ring)
    for k, p in enumerate(order):
        part.note(ch, t0 + k * spread, t1, p, vel * (1 - 0.05 * k))


# ---------------------------------------------------------------- mix

def room_ir(rt60: float = 1.2, seed: int = 5) -> np.ndarray:
    """Stereo impulse response of a small wooden room: band-limited noise that decays
    faster in the treble, with a 12 ms pre-delay."""
    rng = np.random.default_rng(seed)
    n = int(SR * rt60 * 1.8)
    t = np.arange(n) / SR
    bands = ((None, 250.0, 1.0), (250.0, 1000.0, 0.95), (1000.0, 3000.0, 0.8), (3000.0, 7000.0, 0.55), (7000.0, None, 0.35))
    ir = np.zeros((n, 2))
    for c in range(2):
        noise = rng.standard_normal(n)
        for lo, hi, rel in bands:
            if lo is None:
                sos = butter(4, hi, "lowpass", fs=SR, output="sos")
            elif hi is None:
                sos = butter(4, lo, "highpass", fs=SR, output="sos")
            else:
                sos = butter(4, [lo, hi], "bandpass", fs=SR, output="sos")
            ir[:, c] += sosfiltfilt(sos, noise) * np.exp(-6.908 * t / (rt60 * rel))
    ir *= (1 - np.exp(-t / 0.008))[:, None]
    ir = np.vstack([np.zeros((int(0.012 * SR), 2)), ir])
    return ir / np.sqrt((ir**2).sum(axis=0))


def pan(x: np.ndarray, pos: float) -> np.ndarray:
    """Place a mono or stereo stem: pos -1 is left, 0 centre, 1 right (constant power)."""
    th = (pos + 1) * np.pi / 4
    if x.ndim == 1:
        return np.stack([x * np.cos(th), x * np.sin(th)], axis=1)
    return np.stack([x[:, 0] * min(1.0, np.sqrt(2) * np.cos(th)), x[:, 1] * min(1.0, np.sqrt(2) * np.sin(th))], axis=1)


def lufs_active(x: np.ndarray, floor: float = -58.0) -> float:
    """Loudness of the parts of a stem that sound: K-weighted 400 ms blocks above a fixed gate."""
    z = k_weighted(x if x.ndim == 2 else np.stack([x, x], axis=1))
    p = np.sum(z**2, axis=1)
    blk, hop = int(0.4 * SR), int(0.1 * SR)
    if len(p) < blk:
        return -120.0
    c = np.concatenate([[0.0], np.cumsum(p)])
    ms = (c[blk::hop] - c[:-blk:hop]) / blk
    keep = ms[-0.691 + 10 * np.log10(np.maximum(ms, 1e-20)) > floor]
    return -120.0 if len(keep) == 0 else float(-0.691 + 10 * np.log10(keep.mean()))


@dataclass
class Stem:
    name: str
    audio: np.ndarray        # n x 2
    lufs: float              # target loudness of the sounding parts
    send: float = 0.0        # reverb send, dB relative to the stem
    lead: bool = False


def mixdown(stems: Sequence[Stem], target_lufs: float = -16.0, wet_db: float = -11.0, rt60: float = 1.2,
            ceiling_db: float = -1.2) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Returns (master, stems at their mix level before the room and the master gain)."""
    n = max(len(s.audio) for s in stems)
    tail = int(rt60 * 1.6 * SR)
    dry, bus = np.zeros((n + tail, 2)), np.zeros((n + tail, 2))
    placed: dict[str, np.ndarray] = {}
    for s in stems:
        g = 10 ** ((s.lufs - lufs_active(s.audio)) / 20)
        y = s.audio * g
        placed[s.name] = y
        dry[: len(y)] += y
        bus[: len(y)] += y * 10 ** (s.send / 20)
    ir = room_ir(rt60)
    wet = np.stack([oaconvolve(bus[:, c], ir[:, c])[: n + tail] for c in range(2)], axis=1)
    rms = lambda v: float(np.sqrt(np.mean(v**2)))  # noqa: E731
    y = dry + 10 ** (wet_db / 20) * rms(dry) / max(rms(wet), 1e-12) * wet
    y = np.asarray(sosfilt(butter(2, 30, "highpass", fs=SR, output="sos"), y, axis=0))
    env = np.abs(y).max(axis=1)
    last = int(np.nonzero(env > env.max() * 10 ** (-66 / 20))[0][-1]) + int(0.25 * SR)
    y = y[: min(last, len(y))]
    fade = int(0.8 * SR)
    y[-fade:] *= (np.linspace(1.0, 0.0, fade) ** 2)[:, None]
    y = y * 10 ** ((target_lufs - lufs_active(y, floor=-70.0)) / 20)
    y = limit(y, SR, 10 ** (ceiling_db / 20))
    return y, placed


def write_mp3(y: np.ndarray, path: Path, meta: dict[str, str]) -> tuple[float, float]:
    """Write a 320k MP3 and return ffmpeg's (integrated LUFS, true peak dBFS) for the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "master.wav"
        wavfile.write(tmp, SR, y.astype(np.float32))
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(tmp), "-c:a", "libmp3lame", "-b:a", "320k"]
        for k, v in meta.items():
            cmd += ["-metadata", f"{k}={v}"]
        subprocess.run([*cmd, str(path)], check=True)
    return loudness(path)


def balance_spans(placed: dict[str, np.ndarray], leads: Iterable[str], clock: Clock, spans: Sequence[tuple[str, float, float]]) -> str:
    """Lead bus against the accompaniment bus in each span (name, first slot, end slot).
    A lead that sits 3 to 6 LU over the band reads clearly."""
    lead_names = set(leads)
    n = max(len(v) for v in placed.values())
    lead, acc = np.zeros((n, 2)), np.zeros((n, 2))
    for name, y in placed.items():
        (lead if name in lead_names else acc)[: len(y)] += y
    rows = ["section            lead    band    lead minus band"]
    for name, s0, s1 in spans:
        a, e = int(clock.t(s0) * SR), int(clock.t(s1) * SR)
        la, ac = lufs_active(lead[a:e], -70.0), lufs_active(acc[a:e], -70.0)
        rows.append(f"{name:<16} {la:7.1f} {ac:7.1f} {la - ac:+9.1f} LU")
    return "\n".join(rows)


def stem_table(placed: dict[str, np.ndarray], clock: Clock, spans: Sequence[tuple[str, float, float]]) -> str:
    """Loudness of each stem in each span, to see which voice is on top when two lines share the lead."""
    names = list(placed)
    rows = [f"{'section':<18}" + "".join(f"{n[:8]:>9}" for n in names)]
    for name, s0, s1 in spans:
        a, e = int(clock.t(s0) * SR), int(clock.t(s1) * SR)
        cells = []
        for n in names:
            v = lufs_active(placed[n][a:e], -70.0)
            cells.append(f"{'-':>9}" if v < -65 else f"{v:9.1f}")
        rows.append(f"{name:<18}" + "".join(cells))
    return "\n".join(rows)


def balance(placed: dict[str, np.ndarray], leads: Iterable[str], clock: Clock, sections: Sequence[tuple[str, int, int]]) -> str:
    """balance_spans() for sections given as bars of 4/4 (1-based, inclusive)."""
    return balance_spans(placed, leads, clock, [(name, (b0 - 1) * 16, b1 * 16) for name, b0, b1 in sections])


# ---------------------------------------------------------------- the band

DORIAN = (0, 2, 3, 5, 7, 9, 10)
STRUM = {"X": (104, 3.5), "D": (84, 2.5), "d": (62, 1.6), "u": (52, 1.2)}   # velocity, ring in slots
# Bodhran bars of sixteen strokes: a plain reel, and a bar that leans on the 3+3+2 of the tune's stabs
REEL = [.9, .3, .45, .35, .6, .3, .45, .35, .85, .3, .45, .35, .6, .3, .5, .4]
TRES = [.95, .25, .35, .8, .3, .35, .8, .3, .85, .3, .62, .3, .72, .3, .45, .4]
# A guitar in DADGAD for A Dorian and E Dorian, low string first. "G5" is the subtonic chord with
# its major seventh (F sharp, the Dorian sixth of A) as an inner voice, a ninth under a melody G.
DADGAD = {
    "Am": [45, 52, 57, 60, 64], "G5": [43, 50, 54, 62, 67], "G": [43, 50, 55, 59, 62, 67], "G/B": [47, 50, 55, 62, 67],
    "D": [38, 45, 50, 57, 62, 66], "D/F#": [42, 50, 57, 62, 66], "Em": [40, 47, 52, 55, 59, 64], "E5": [40, 47, 52, 59, 64],
    "Bm": [47, 54, 59, 62, 66], "C": [48, 52, 55, 60, 64], "A": [45, 52, 57, 61, 64], "A5": [45, 52, 57, 64, 69],
    "F#m": [42, 49, 54, 57, 61],
}
LEVELS = {"whistle": -18.0, "fiddle": -19.5, "banjo": -21.5, "guitar": -27.5, "bouzouki": -30.5, "harp": -28.0,
          "bass": -26.0, "bodhran": -27.0, "drone": -32.0}   # LUFS of the sounding parts; from the first piece's mix
SENDS = {"whistle": 0.0, "fiddle": 0.0, "banjo": -4.0, "guitar": -6.0, "bouzouki": -5.0, "harp": -2.0, "bass": -14.0,
         "bodhran": -8.0, "drone": -3.0}
PANS = {"whistle": 0.18, "fiddle": -0.3, "banjo": 0.3, "guitar": -0.5, "bouzouki": 0.55, "harp": -0.12, "bass": 0.0,
        "bodhran": -0.12, "drone": 0.0}
LEADS = ("whistle", "fiddle", "banjo")


def step(p: int, tonic: int, k: int, scale: Sequence[int] = DORIAN) -> int:
    """The pitch k scale steps from p (p moves to the nearest scale tone first)."""
    rel, octv = (p - tonic) % 12, (p - tonic) // 12
    j = min(range(len(scale)), key=lambda i: abs(scale[i] - rel)) + k
    return tonic + 12 * (octv + j // len(scale)) + scale[j % len(scale)]


def cut(p: int, tonic: int, scale: Sequence[int] = DORIAN) -> int:
    """Semitones up to the cut note: two scale steps above."""
    return step(p, tonic, 2, scale) - p


def tap(p: int, tonic: int, scale: Sequence[int] = DORIAN) -> int:
    """Semitones down to the tap note: one scale step below."""
    return p - step(p, tonic, -1, scale)


class Band:
    """The nine parts of the session band, and the helpers that write them.

    A piece makes one Band, writes notes with lead(), rhythm(), low(), harp_roll(),
    bod_bar(), bod_roll() and drone_span(), then calls render(). Positions are
    absolute slots (sixteenths from the start), so a bar of any length works.
    Every written note goes into `written` for the census, and the piece adds the
    notes of the tune to `tune` for the presence test.
    """

    def __init__(self, clock: Clock, chords: dict[str, list[int]] | None = None, seed: int = 11) -> None:
        self.clock = clock
        self.ch = chords or DADGAD
        self.rng = np.random.default_rng(seed)
        self.whistle: list[Tone] = []
        self.fiddle: list[Tone] = []
        self.fiddle_low: list[Tone] = []      # the second string of a double stop
        self.banjo: list[Tone] = []
        self.harp: list[Tone] = []
        self.bass: list[Tone] = []
        self.gtr_single: list[Tone] = []
        self.bod: list[Stroke] = []
        self.gtr = MidiPart({0: STEEL_GUITAR, 1: STEEL_GUITAR})
        self.bouz = MidiPart({0: STEEL_GUITAR})
        self.drone = MidiPart({0: BAGPIPE, 1: BAGPIPE})
        self.written: list[tuple[float, float, int]] = []    # (slot, length in slots, pitch)
        self.tune: list[tuple[float, float, int]] = []
        # MIDI velocity for Tone.vel 0 and 1 on the fiddle. The floor is low so that a held chord can sit
        # under a riff: with a floor of 56 a "quiet" long note still swelled to the level of the riff.
        self.fiddle_vel = (34, 124)

    def count(self, slot: float, dur: float, p: int) -> None:
        self.written.append((slot, dur, p))

    def lead(self, part: list[Tone], tone: Tone) -> None:
        part.append(tone)
        self.count(tone.slot, tone.dur, tone.pitch)

    def low(self, slot: float, dur: float, p: int, vel: float = 0.8) -> None:
        self.lead(self.bass, Tone(slot, dur, p, vel=vel))

    def rhythm(self, slot0: float, pattern: str, chords: dict[int, str], riff: dict[int, tuple[int, float]] | None = None,
               level: float = 1.0, bz: float = 1.0) -> None:
        """Guitar and bouzouki from slot0, one pattern character for each sixteenth:
        X D d = down strums (loud to soft), u = up strum on the top strings, r = one low
        string (the riff note of that slot, or the chord root), . = nothing. `chords` maps
        a slot inside the pattern to the chord that starts there."""
        cur = ""
        for i, sym in enumerate(pattern):
            cur = chords.get(i, cur)
            if sym == ".":
                continue
            notes = self.ch[cur]
            if sym == "r":
                p, d = (riff or {}).get(i, (notes[0], 2.0))
                self.lead(self.gtr_single, Tone(slot0 + i, max(d, 2.0), p, vel=min(1.0, 0.85 * level)))
                continue
            v, ring = STRUM[sym]
            down = sym != "u"
            pts = notes if down else notes[-3:]
            strum(self.gtr, 0, self.clock, slot0 + i, pts, v * level, down=down, ring=ring, rng=self.rng)
            for p in pts:
                self.count(slot0 + i, ring, p)
            if bz > 0:
                top = [p + 12 for p in (notes[-4:] if down else notes[-3:])]
                strum(self.bouz, 0, self.clock, slot0 + i, top, v * 0.92 * level * bz, down=down, ring=ring, spread=0.009, rng=self.rng)
                for p in top:
                    self.count(slot0 + i, ring, p)

    def hit(self, slot: float, chord: str, vel: float, ring: float = 2.2, harp: float = 0.6, bass: bool = True) -> None:
        """One chord from the whole rhythm section: guitar, bouzouki, a harp roll and the bass."""
        notes = self.ch[chord]
        strum(self.gtr, 0, self.clock, slot, notes, vel, ring=ring, rng=self.rng)
        strum(self.bouz, 0, self.clock, slot, [p + 12 for p in notes[-4:]], vel * 0.92, ring=ring, rng=self.rng)
        for p in notes:
            self.count(slot, ring, p)
        if harp > 0:
            self.harp_roll(slot, [p + 12 for p in notes[-4:]], harp, spread=0.12, ring=4)
        if bass:
            self.low(slot, ring + 0.3, notes[0], 0.82)

    def bod_bar(self, slot0: float, vels: Sequence[float], level: float = 1.0) -> None:
        """Strokes on successive sixteenths. A loud stroke is open, a soft stroke is pressed."""
        for i, v in enumerate(vels):
            if v > 0:
                self.bod.append(Stroke(slot0 + i, min(1.0, v * level), "D" if i % 2 == 0 else "U",
                                       tone=0.08 if v >= 0.75 else (0.35 if v >= 0.55 else 0.7)))

    def bod_roll(self, slot0: float, slot1: float, v0: float, v1: float, per_slot: float = 1.5) -> None:
        """A roll from v0 to v1: triplets (per_slot 1.5) or thirty-seconds (per_slot 2)."""
        n = max(2, int(round((slot1 - slot0) * per_slot)))
        for k in range(n):
            q = k / (n - 1)
            kind = "DUD"[k % 3] if per_slot == 1.5 else "DU"[k % 2]
            self.bod.append(Stroke(slot0 + (slot1 - slot0) * k / n, v0 + (v1 - v0) * q, kind, tone=0.5 - 0.4 * q))

    def harp_roll(self, slot: float, pitches: Sequence[int], vel: float, spread: float = 0.2, ring: float = 10.0) -> None:
        for i, p in enumerate(pitches):
            self.harp.append(Tone(slot + i * spread, ring, p, vel=min(1.0, vel * (1 + 0.04 * i))))
            self.count(slot, 4.0, p)

    def drone_span(self, ch: int, pitches: Sequence[int], slot0: float, slot1: float, level: int,
                   fade_in: float = 0.5, fade_out: float = 0.4) -> None:
        """A pipe drone with a swell in and out (controller 11). Use one channel for each drone pitch set
        that overlaps a different set. A drone is quiet, so the census counts a quarter of its length."""
        t0, t1 = self.clock.t(slot0), self.clock.t(slot1)
        for q in np.linspace(0, 1, 12):
            self.drone.cc(ch, t0 + fade_in * q, 11, level * q**1.5)
            self.drone.cc(ch, t1 - fade_out * (1 - q), 11, level * (1 - q) ** 1.5)
        for p in pitches:
            self.drone.note(ch, t0, t1 + 0.05, p, 90)
            self.count(slot0, (slot1 - slot0) * 0.25, p)

    def census(self, tonic: int, slot0: float = 0.0, slot1: float = 1e12) -> list[tuple[float, int]]:
        """(length, pitch) of the written notes that start in [slot0, slot1), for modalkit.census()."""
        return [(d, p) for s, d, p in self.written if slot0 <= s < slot1]

    def substitute(self, fix) -> None:
        """Change pitches in every part: fix(slot, pitch) -> pitch. This makes a control render,
        for example the same arrangement with the sixth degree a semitone lower."""
        for part in (self.whistle, self.fiddle, self.fiddle_low, self.banjo, self.harp, self.bass, self.gtr_single):
            for t in part:
                t.pitch = fix(t.slot, t.pitch)
        times = np.array([self.clock.t(s) for s in np.arange(0.0, 4096.0)])

        def slot_of(tick: int) -> float:
            return float(np.searchsorted(times, tick / MidiPart.TPS + 0.02) - 1)

        for mp in (self.gtr, self.bouz, self.drone):
            held: dict[tuple[int, int], list[int]] = {}
            fixed = []
            for tick, order, msg in sorted(mp.ev, key=lambda e: (e[0], e[1])):
                if msg.type == "note_on":
                    p = fix(slot_of(tick), msg.note)
                    held.setdefault((msg.channel, msg.note), []).append(p)
                    msg = msg.copy(note=p)
                elif msg.type == "note_off" and held.get((msg.channel, msg.note)):
                    msg = msg.copy(note=held[(msg.channel, msg.note)].pop(0))
                fixed.append((tick, order, msg))
            mp.ev = fixed

    def render(self, out: Path, total: float, meta: dict[str, str], levels: dict[str, float] | None = None,
               target_lufs: float = -16.0) -> dict[str, np.ndarray]:
        """Render the nine stems, mix them and write the MP3. Returns the stems at mix level."""
        lv = {**LEVELS, **(levels or {})}
        c = self.clock
        fid = MidiPart({0: FIDDLE, 1: FIDDLE, 2: FIDDLE, 3: FIDDLE}, bend_range=4)
        table = tuning_table(GM_BANK, FIDDLE, [t.pitch for t in self.fiddle + self.fiddle_low])
        bowed(fid, self.fiddle, c, chans=(0, 1), tuning=table, seed=2, vel=self.fiddle_vel)
        bowed(fid, self.fiddle_low, c, chans=(2, 3), tuning=table, seed=6, vel=self.fiddle_vel)
        bj, hp, bs = MidiPart({0: BANJO}), MidiPart({0: HARP}), MidiPart({0: ACOUSTIC_BASS})
        plucked(bj, 0, self.banjo, c, ring=0.5, seed=4)
        plucked(hp, 0, self.harp, c, ring=2.4, seed=5, vel=(40, 112))
        plucked(bs, 0, self.bass, c, ring=6.0, seed=7, vel=(60, 118))
        plucked(self.gtr, 1, self.gtr_single, c, ring=1.2, seed=8, vel=(60, 122))
        audio = {
            "whistle": whistle(self.whistle, c, total), "fiddle": fid.render(GM_BANK, total),
            "banjo": bj.render(GM_BANK, total), "guitar": self.gtr.render(GM_BANK, total),
            "bouzouki": self.bouz.render(GM_BANK, total), "harp": hp.render(GM_BANK, total),
            "bass": bs.render(GM_BANK, total), "bodhran": bodhran(self.bod, c, total),
            "drone": self.drone.render(FONTS / "fs-uilleann-pipe.sf2", total),
        }
        stems = [Stem(name, pan(x, PANS[name]), lv[name], send=SENDS[name], lead=name in LEADS) for name, x in audio.items()]
        y, placed = mixdown(stems, target_lufs=target_lufs, wet_db=-11.5, rt60=1.15)
        lufs, peak = write_mp3(y, out, meta)
        print(f"wrote {out}  {len(y) / SR:.1f} s  {lufs:.1f} LUFS  peak {peak:.1f} dBFS")
        return placed
