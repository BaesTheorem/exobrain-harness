"""loopkit: additive synthesis for pieces that are exact loops.

Every note is a Shepard stack: one tone copied at every octave, and each copy
weighted by a fixed bell curve over log frequency. A pitch class then has no
octave, so a line can rise (or fall) forever and still arrive where it began.

The whole piece renders into ONE period buffer. A note whose tail passes the end
of the period wraps to the start, and the reverb is a circular convolution. So
the result is periodic to the sample: the last sample leads into the first, and
the file can repeat with no seam.

Pitches are points of the 5-limit lattice (powers of 3 and 5), so chords can be
exactly pure. Pure intervals never close a loop (3^a 5^b is never a power of 2),
so a Loop can apply a glide common to all notes: the whole texture rises by a
small, fixed amount per period. A glide of one comma per cycle pays back the
comma that a pure-tuned cycle loses.

    loop = Loop(period=216.0, layers=[...], glide=3 * PYTHAGOREAN_COMMA)
    for note in notes: loop.add(note)
    y = loop.mix(wet_db=-4.0)                 # stereo, exactly one period
    write_outputs(y, loop.sr, OUT / "name", meta, roll=2.0)
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
import zlib
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import butter, sosfilt, sosfiltfilt

HARNESS = Path(__file__).resolve().parents[2]
OUT = HARNESS / "tmp" / "audio"
SR = 48000
LOG2_3 = math.log2(3)
LOG2_5 = math.log2(5)
PYTHAGOREAN_COMMA = 12 * LOG2_3 - 19      # log2(3^12 / 2^19), 23.46 cents
SYNTONIC_COMMA = 4 * LOG2_3 - LOG2_5 - 4  # log2(81/80), 21.51 cents
C4 = 440.0 * 2 ** (-9 / 12)
F_LO, F_HI = 18.0, 16000.0                # stack copies outside this band are skipped


def lattice(a: int, b: int) -> float:
    """log2 of the ratio 3^a * 5^b (octave not reduced)."""
    return a * LOG2_3 + b * LOG2_5


def cents(log2_ratio: float) -> float:
    return 1200.0 * log2_ratio


@dataclass(frozen=True)
class Tone:
    """A timbre. partials: (ratio to the fundamental, amplitude, decay multiplier).

    tau440=None makes a sustained tone (pipe, voice): full level from the attack
    to note off, then a release. With tau440 set, each partial decays with
    tau = tau440 * (440 / f)**tau_exp * multiplier, so high partials and high
    notes die first (string, bell).
    """

    partials: tuple[tuple[float, float, float], ...]
    attack: float
    release: float
    tau440: float | None = None
    tau_exp: float = 0.5
    noise: float = 0.0                          # onset burst: pipe chiff, pluck, clapper
    noise_ms: float = 25.0
    noise_band: tuple[float, float] = (2.0, 6.0)  # in multiples of the loudest copy's fundamental
    bright: float = 6000.0                      # partials roll off above this frequency (4th order)
    vibrato: tuple[float, float, float] = (0.0, 5.0, 0.3)  # depth cents, rate Hz, onset s


@dataclass(frozen=True)
class Layer:
    name: str
    tone: Tone
    center: float   # Hz: the peak of this layer's Shepard envelope
    sigma: float    # octaves: the width (standard deviation) of the envelope
    gain: float = 1.0
    send: float = 0.3


@dataclass(frozen=True)
class Note:
    layer: str
    t: float        # onset, seconds into the period
    dur: float      # seconds from onset to note off
    log2f: float    # log2(Hz) before the glide; the octave does not matter
    amp: float = 1.0
    pan: float = 0.0  # -1 left .. +1 right
    tone: Tone | None = None     # these three override the layer for one note
    center: float | None = None  # (for example, bells of different sizes in one layer)
    sigma: float | None = None


class Loop:
    """One period of an exactly periodic piece, rendered note by note into per-layer stems."""

    def __init__(self, period: float, layers: list[Layer], glide: float = 0.0, sr: int = SR, seed: int = 1):
        self.n = round(period * sr)
        if abs(self.n - period * sr) > 1e-6:
            raise ValueError("the period must be a whole number of samples")
        self.period, self.sr = period, sr
        self.rate = glide / period  # log2 per second, common to every note
        self.layers = {x.name: x for x in layers}
        self.stems = {x.name: np.zeros((self.n, 2), np.float32) for x in layers}
        self.seed = seed
        # One random stream per layer, so a layer renders the same whatever the other layers do
        # (that is what makes the per-layer cache and the parallel render exact).
        self.rngs = {x.name: np.random.default_rng([seed, zlib.crc32(x.name.encode())]) for x in layers}
        self.count: Counter[str] = Counter()

    @staticmethod
    def copies(center: float, sigma: float, log2f: float) -> list[tuple[float, float]]:
        """(frequency, weight) of every octave copy of a pitch under a Shepard envelope."""
        c = math.log2(center)
        k0 = math.ceil(math.log2(F_LO) - log2f)
        k1 = math.floor(math.log2(F_HI) - log2f)
        out = []
        for k in range(k0, k1 + 1):
            w = math.exp(-((log2f + k - c) ** 2) / (2 * sigma**2))
            if w > 1e-3:
                out.append((2 ** (log2f + k), w))
        return out

    def add(self, note: Note) -> None:
        layer = self.layers[note.layer]
        tone = note.tone or layer.tone
        rng = self.rngs[note.layer]
        sr = self.sr
        log2f = note.log2f + self.rate * note.t  # the glide, frozen at the onset for the stack weights
        stack = self.copies(note.center or layer.center, note.sigma or layer.sigma, log2f)
        if not stack:
            return
        if tone.tau440 is None:
            length = note.dur + tone.release
        else:
            f_min = min(f for f, _ in stack) * min(r for r, _, _ in tone.partials)
            m_max = max(m for _, _, m in tone.partials)
            ring = 6.9 * tone.tau440 * (440 / f_min) ** tone.tau_exp * m_max  # to -60 dB
            length = min(note.dur + tone.release, ring)
        length = min(length, self.period - 1.0)
        m = int(length * sr) + 1
        t = np.arange(m) / sr
        # One phase track for the whole note: every partial of every copy scales it,
        # so the glide (and any vibrato) moves the stack as a rigid body.
        ratio = np.exp2(self.rate * t)
        depth, vrate, onset = tone.vibrato
        if depth:
            ratio *= np.exp2(depth / 1200 * np.sin(2 * np.pi * vrate * t) * np.clip(t / onset, 0, 1))
        phi = 2 * np.pi * np.cumsum(ratio) / sr
        sig = np.zeros(m)
        nyq = 0.45 * sr
        for f0, w in stack:
            for r, a, mult in tone.partials:
                f = f0 * r
                if f > nyq:
                    continue
                amp = w * a / math.sqrt(1 + (f / tone.bright) ** 4)
                if amp < 2e-4:
                    continue
                wave = np.sin(f * phi + rng.uniform(0, 2 * np.pi))
                if tone.tau440 is not None:
                    tau = tone.tau440 * (440 / f) ** tone.tau_exp * mult
                    wave *= np.exp(-t / tau)
                sig += amp * wave
        env = np.ones(m)
        na = max(1, int(tone.attack * sr))
        env[:na] = 0.5 - 0.5 * np.cos(np.pi * np.arange(min(na, m)) / na)[: min(na, m)]
        off = int(note.dur * sr)
        if off < m:
            nr = m - off
            env[off:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(nr) / max(1, int(tone.release * sr)))
            env[off + int(tone.release * sr):] = 0.0
        sig *= env
        if tone.noise:
            f_main = max(stack, key=lambda s: s[1])[0]
            lo, hi = (min(x * f_main, 0.4 * sr) for x in tone.noise_band)
            nb = min(m, int(4 * tone.noise_ms / 1000 * sr))
            burst = rng.standard_normal(nb) * np.exp(-np.arange(nb) / (tone.noise_ms / 1000 * sr))
            if hi > lo * 1.05:
                burst = sosfilt(butter(2, [lo, hi], "bandpass", fs=sr, output="sos"), burst)
            sig[:nb] += tone.noise * np.asarray(burst) * sum(w for _, w in stack)
        theta = (note.pan + 1) * np.pi / 4
        self._wrap_add(self.stems[note.layer], round(note.t * sr), sig * note.amp, math.cos(theta), math.sin(theta))
        self.count[note.layer] += 1

    def _wrap_add(self, stem: np.ndarray, start: int, sig: np.ndarray, gl: float, gr: float) -> None:
        start %= self.n
        first = min(len(sig), self.n - start)
        stem[start:start + first, 0] += (gl * sig[:first]).astype(np.float32)
        stem[start:start + first, 1] += (gr * sig[:first]).astype(np.float32)
        rest = len(sig) - first
        if rest > 0:  # the tail crosses the end of the period: it sounds at the start
            stem[:rest, 0] += (gl * sig[first:]).astype(np.float32)
            stem[:rest, 1] += (gr * sig[first:]).astype(np.float32)

    def render(self, notes: list[Note], cache: Path | None = None, workers: int | None = None) -> None:
        """Render every layer in its own process, and keep each stem in `cache` under a key made
        from everything that shapes it. A later run re-renders only the layers that changed."""
        jobs = []
        for name, layer in self.layers.items():
            mine = [nt for nt in notes if nt.layer == name]
            key = hashlib.sha1(repr((layer, mine, self.n, self.sr, self.rate, self.seed)).encode()).hexdigest()[:16]
            path = cache / f"{name}-{key}.npy" if cache else None
            if path and path.exists():
                self.stems[name] = np.load(path)
                self.count[name] += len(mine)
                continue
            jobs.append((name, layer, mine, path))
        if not jobs:
            return
        if cache:
            cache.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="loopkit-"))
        args = [(layer, mine, self.period, self.sr, self.rate * self.period, self.seed, path or tmp / f"{name}.npy")
                for name, layer, mine, path in jobs]
        with ProcessPoolExecutor(max_workers=workers or min(len(jobs), max(1, (os.cpu_count() or 2) - 2))) as ex:
            for (name, _, mine, _), out in zip(jobs, ex.map(_render_layer, args), strict=True):
                self.stems[name] = np.load(out)
                self.count[name] += len(mine)
                if cache:  # drop this layer's stale stems
                    for old in cache.glob(f"{name}-*.npy"):
                        if old != out:
                            old.unlink()
        shutil.rmtree(tmp, ignore_errors=True)

    def dry(self) -> np.ndarray:
        y = np.zeros((self.n, 2))
        for name, layer in self.layers.items():
            y += layer.gain * self.stems[name]
        return y

    def mix(self, wet_db: float = -5.0, ir: np.ndarray | None = None) -> np.ndarray:
        """Dry stems plus a circular hall: wet RMS sits wet_db below the dry RMS."""
        dry = self.dry()
        send = np.zeros((self.n, 2))
        for name, layer in self.layers.items():
            send += layer.gain * layer.send * self.stems[name]
        wet = circular_convolve(send, cathedral_ir(self.sr) if ir is None else ir)
        wet *= 10 ** (wet_db / 20) * rms(dry) / max(rms(wet), 1e-12)
        return highpass(dry + wet, self.sr, 28.0)


def _render_layer(args: tuple[Layer, list[Note], float, int, float, int, Path]) -> Path:
    """Worker: render one layer's notes into its stem and save it (a process-pool target)."""
    layer, notes, period, sr, glide, seed, out = args
    loop = Loop(period, [layer], glide=glide, sr=sr, seed=seed)
    for note in notes:
        loop.add(note)
    np.save(out, loop.stems[layer.name])
    return out


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def cathedral_ir(sr: int = SR, seconds: float = 7.0, seed: int = 11) -> np.ndarray:
    """Stereo impulse response of a large stone room, synthesized.

    Band-limited noise with a longer decay in the low bands than in the high
    ones (air absorbs treble), a 35 ms pre-delay, and a soft build-up for the
    early reflections. The two channels use different noise, so the tail is wide.
    """
    rng = np.random.default_rng(seed)
    n = int(sr * seconds)
    t = np.arange(n) / sr
    bands = ((None, 250, 4.6), (250, 1000, 4.1), (1000, 3000, 3.2), (3000, 7000, 2.2), (7000, None, 1.2))
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
    ir *= (1 - np.exp(-t / 0.03))[:, None]
    ir = np.vstack([np.zeros((int(0.035 * sr), 2)), ir])
    return ir / np.sqrt((ir**2).sum(axis=0))


def circular_convolve(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    """Convolution modulo the length of x: the tail of the end rings into the start."""
    n = len(x)
    out = np.zeros_like(x, dtype=np.float64)
    for c in range(x.shape[1]):
        h = np.zeros(n)
        h[: len(ir)] = ir[:, c]
        out[:, c] = np.fft.irfft(np.fft.rfft(x[:, c]) * np.fft.rfft(h), n)
    return out


def highpass(x: np.ndarray, sr: int, fc: float) -> np.ndarray:
    """Zero-phase 2nd-order high-pass applied in the frequency domain, so it is circular too."""
    f = np.fft.rfftfreq(len(x), 1 / sr)
    mag = 1 / np.sqrt(1 + (fc / np.maximum(f, 1e-9)) ** 4)
    return np.stack([np.fft.irfft(np.fft.rfft(x[:, c]) * mag, len(x)) for c in range(x.shape[1])], axis=1)


def shelf(x: np.ndarray, sr: int, fc: float, gain_db: float) -> np.ndarray:
    """Zero-phase high shelf (gain_db above fc, a smooth 2nd-order step), circular like the rest."""
    f = np.fft.rfftfreq(len(x), 1 / sr)
    step = 1 / (1 + (fc / np.maximum(f, 1e-9)) ** 2)
    mag = 10 ** (gain_db * step / 20)
    return np.stack([np.fft.irfft(np.fft.rfft(x[:, c]) * mag, len(x)) for c in range(x.shape[1])], axis=1)


def limit_circular(y: np.ndarray, sr: int, ceiling: float) -> np.ndarray:
    """Look-ahead peak limiter whose windows wrap around the period (pianokit's limiter, mode='wrap')."""
    need = np.minimum(1.0, ceiling / np.maximum(np.abs(y).max(axis=1), 1e-12))
    hold, ramp = int(0.06 * sr), int(0.02 * sr)
    g = minimum_filter1d(need, size=hold, origin=-(hold // 2), mode="wrap")
    g = uniform_filter1d(g, size=ramp, origin=(ramp - 1) // 2, mode="wrap")
    return y * g[:, None]


def k_weighted(x: np.ndarray) -> np.ndarray:
    """ITU-R BS.1770 K-weighting (the standard's 48 kHz coefficients)."""
    shelf = sosfilt(np.array([[1.53512485958697, -2.69169618940638, 1.19839281085285, 1.0,
                               -1.69065929318241, 0.73248077421585]]), x, axis=0)
    return np.asarray(sosfilt(np.array([[1.0, -2.0, 1.0, 1.0, -1.99004745483398, 0.99007225036621]]),
                              shelf, axis=0))


def lufs_ungated(x: np.ndarray) -> float:
    """BS.1770 loudness without the gates: close to integrated LUFS for music with no silences."""
    z = k_weighted(np.asarray(x, dtype=np.float64))
    return -0.691 + 10 * math.log10(max(float(np.mean(np.sum(z**2, axis=1))), 1e-20))


def loudness(path: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBTP), measured by ffmpeg's EBU R128 filter."""
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true",
                        "-f", "null", "-"], capture_output=True, text=True, check=True)
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1])
    peak = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", r.stderr)[-1])
    return lufs, peak


def master(y: np.ndarray, sr: int, target_lufs: float = -17.0, ceiling_db: float = -1.0) -> np.ndarray:
    """Bring the period to the loudness target; a circular limiter holds the peaks."""
    y = y * 10 ** ((target_lufs - lufs_ungated(y)) / 20)
    ceiling = 10 ** (ceiling_db / 20)
    if np.abs(y).max() > ceiling:
        y = limit_circular(y, sr, ceiling)
    return y


def write_outputs(y: np.ndarray, sr: int, stem: Path, meta: dict[str, str], roll: float = 2.0) -> dict[str, Path]:
    """Write the period three ways.

    <stem>-loop.flac  exactly one period, lossless: loops with no seam in any gapless player
    <stem>.mp3        the period with `roll` seconds of its own tail before it and its own
                      head after it. An MP3 decoder adds delay and padding at the file
                      edges; the roll keeps those edges out of the loop window
                      [roll, roll + period), so that window loops cleanly.
    """
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    stem.parent.mkdir(parents=True, exist_ok=True)
    r = int(roll * sr)
    rolled = np.vstack([y[-r:], y, y[:r]]) if r else y
    out = {"flac": stem.with_name(stem.name + "-loop.flac"), "mp3": stem.with_suffix(".mp3")}
    tags: list[str] = []
    for k, v in meta.items():
        tags += ["-metadata", f"{k}={v}"]
    with tempfile.TemporaryDirectory() as td:
        a, b = Path(td) / "period.wav", Path(td) / "rolled.wav"
        wavfile.write(a, sr, y.astype(np.float32))
        wavfile.write(b, sr, rolled.astype(np.float32))
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(a), "-c:a", "flac",
                        "-sample_fmt", "s32", "-bits_per_raw_sample", "24", *tags, str(out["flac"])], check=True)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(b), "-c:a", "libmp3lame",
                        "-b:a", "320k", *tags, str(out["mp3"])], check=True)
    return out


def decode(path: Path, sr: int = SR) -> np.ndarray:
    """Any audio file -> float64 stereo at sr, via ffmpeg."""
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    raw = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(path), "-f", "f32le", "-ac", "2",
                          "-ar", str(sr), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).astype(np.float64)


def seam(x: np.ndarray, start: int, period: int) -> tuple[float, float]:
    """Loop the window [start, start + period) and compare the sample step across the wrap
    with the steps inside the window. Returns (step at the wrap, 99.99th percentile of the
    steps inside). A seamless loop has a wrap step inside the normal range."""
    w = x[start:start + period]
    steps = np.abs(np.diff(w, axis=0)).max(axis=1)
    wrap = float(np.abs(w[0] - w[-1]).max())
    return wrap, float(np.percentile(steps, 99.99))


def seam_hf(x: np.ndarray, start: int, period: int, sr: int = SR) -> tuple[float, float]:
    """A click detector: the peak of the >8 kHz band in 10 ms around the wrap of the tiled
    window, against the median 10 ms peak elsewhere. Returns (at the wrap, typical), in dBFS."""
    w = x[start:start + period]
    tiled = np.vstack([w[-sr:], w[:sr]])  # 1 s either side of the wrap, joined as a player would
    hf = sosfilt(butter(4, 8000, "highpass", fs=sr, output="sos"), tiled.mean(axis=1))
    hop = int(0.01 * sr)
    peaks = np.array([np.abs(hf[i:i + hop]).max() for i in range(0, len(hf) - hop + 1, hop)])
    mid = sr // hop  # the first window that starts at the wrap; a click rings forward into it
    db = 20 * np.log10(np.maximum(peaks, 1e-9))
    return float(db[mid - 1:mid + 2].max()), float(np.median(db))


PC_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


def pitch_class_profile(x: np.ndarray, sr: int, f_lo: float = 110.0, f_hi: float = 3000.0) -> np.ndarray:
    """Energy per pitch class (C = 0, nearest equal-tempered class, so just-tuned notes land
    in their own class) in one stretch of audio."""
    mono = x.mean(axis=1) * np.hanning(len(x))
    spec = np.abs(np.fft.rfft(mono)) ** 2
    f = np.fft.rfftfreq(len(mono), 1 / sr)
    band = (f >= f_lo) & (f <= f_hi)
    pc = np.round(12 * np.log2(f[band] / C4)).astype(int) % 12
    return np.bincount(pc, weights=spec[band], minlength=12)


def triad_templates() -> list[tuple[str, np.ndarray]]:
    out = []
    for root in range(12):
        for q, third in (("", 4), ("m", 3)):
            v = np.zeros(12)
            v[[root, (root + third) % 12, (root + 7) % 12]] = 1.0
            out.append((PC_NAMES[root] + q, v))
    return out


def best_triad(profile: np.ndarray) -> tuple[str, float]:
    """The triad whose template correlates best with a pitch-class profile, and the margin
    of its correlation over the runner-up."""
    p = profile / max(float(np.linalg.norm(profile)), 1e-20)
    scores = sorted(((float(p @ (v / np.linalg.norm(v))), name) for name, v in triad_templates()), reverse=True)
    return scores[0][1], scores[0][0] - scores[1][0]


def spectrogram_png(x: np.ndarray, sr: int, path: Path, t0: float, t1: float, title: str,
                    marks: list[tuple[float, str]] | None = None) -> None:
    """Log-frequency spectrogram of [t0, t1) for eyeballing the lines of a piece (needs matplotlib)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    seg = x[int(t0 * sr):int(t1 * sr)].mean(axis=1)
    nfft, hop = 8192, 1200
    win = np.hanning(nfft)
    frames = [np.abs(np.fft.rfft(seg[i:i + nfft] * win)) for i in range(0, len(seg) - nfft, hop)]
    s = 20 * np.log10(np.maximum(np.array(frames).T, 1e-9))
    f = np.fft.rfftfreq(nfft, 1 / sr)
    keep = (f >= 40) & (f <= 6000)
    fig, ax = plt.subplots(figsize=(16, 7), dpi=110)
    t = t0 + np.arange(s.shape[1]) * hop / sr
    top = float(s[keep].max())
    ax.pcolormesh(t, f[keep], s[keep], vmin=top - 70, vmax=top, cmap="magma", shading="auto")
    ax.set_yscale("log")
    ax.set_ylim(40, 6000)
    ax.set_xlabel("seconds")
    ax.set_ylabel("Hz")
    ax.set_title(title)
    for tm, label in marks or []:
        ax.axvline(tm, color="white", lw=0.4, alpha=0.5)
        ax.text(tm + 0.2, 5200, label, color="white", fontsize=7)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
