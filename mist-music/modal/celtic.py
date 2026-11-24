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


def balance(placed: dict[str, np.ndarray], leads: Iterable[str], clock: Clock, sections: Sequence[tuple[str, int, int]]) -> str:
    """Lead bus against the accompaniment bus in each section (bars are 1-based, inclusive).
    A lead that sits 3 to 6 LU over the band reads clearly."""
    lead_names = set(leads)
    n = max(len(v) for v in placed.values())
    lead, acc = np.zeros((n, 2)), np.zeros((n, 2))
    for name, y in placed.items():
        (lead if name in lead_names else acc)[: len(y)] += y
    rows = ["section            lead    band    lead minus band"]
    for name, b0, b1 in sections:
        a, e = int(clock.t((b0 - 1) * 16) * SR), int(clock.t(b1 * 16) * SR)
        la, ac = lufs_active(lead[a:e], -70.0), lufs_active(acc[a:e], -70.0)
        rows.append(f"{name:<16} {la:7.1f} {ac:7.1f} {la - ac:+9.1f} LU")
    return "\n".join(rows)
