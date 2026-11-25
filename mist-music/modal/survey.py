"""survey: read a recording before you arrange it.

Four instruments, numpy only:

  tempo_grid()  the tempo and the phase of the sixteenth-note grid, for music with
                a constant tempo (sequenced game music, a click-tracked band)
  form()        which bars repeat which, from rhythm and pitch together, with the
                bass pitch class of each bar
  align()       slide a transcription over the recording in all 12 transpositions.
                The written key must win, and the best offsets show where each
                section sits and which beat is the downbeat
  roll()        a spectral piano-roll: the strongest pitches of each sixteenth, in
                three registers, for the parts that no transcription has
  f0_track()    one pitch for each sixteenth from a YIN tracker on a band-passed
                signal: the lead line, when the roll and a tab disagree

Limits that cost time on the first two pieces:
- A strong note in the top register can be the third harmonic of a middle-register
  note (a twelfth lower) whose fundamental is weak in the mix. roll() marks it.
- The roll reads a low note one slot late, because a long window smears it.
- A short percussive stab barely shows in the roll. align() still finds it.
- align() tests whole beats, so the downbeat it gives can be a sixteenth off. If the
  tracker reads every note one slot early or late against a tab, move bar 1 by a slot.
- The tracker follows one voice. On two notes at once it can report a pitch between them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

import modalkit as mk

SR = 22050
NAMES = mk.PC_NAMES
C1 = 440.0 * 2 ** (-45 / 12)        # MIDI 24


def load(path: Path) -> np.ndarray:
    return mk.decode(path, SR).astype(np.float32)


def _stft(x: np.ndarray, n: int, hop: int) -> np.ndarray:
    """Magnitudes [bins, frames], computed in blocks to keep memory small."""
    win = np.hanning(n).astype(np.float32)
    k = max(0, 1 + (len(x) - n) // hop)
    out = np.empty((n // 2 + 1, k), dtype=np.float32)
    base = np.arange(n)[None, :]
    for a in range(0, k, 512):
        idx = base + hop * np.arange(a, min(k, a + 512))[:, None]
        out[:, a:a + idx.shape[0]] = np.abs(np.fft.rfft(x[idx] * win, axis=1)).T
    return out


def onset_envelope(x: np.ndarray, band: tuple[float, float] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Spectral flux of the log spectrum (hop 11.6 ms), optionally in one frequency band."""
    n, hop = 1024, 256
    s = np.log1p(20 * _stft(x, n, hop))
    if band is not None:
        f = np.fft.rfftfreq(n, 1 / SR)
        s = s[(f >= band[0]) & (f <= band[1])]
    flux = np.maximum(0.0, np.diff(s, axis=1, prepend=s[:, :1])).sum(axis=0)
    return flux, (np.arange(len(flux)) * hop + n / 2) / SR


def tempo_grid(x: np.ndarray, bpm_lo: float, bpm_hi: float, step: float = 0.02) -> tuple[float, float, float]:
    """(bpm, time of the first beat-phase grid point, score ratio best/median). Searches a
    constant tempo and a phase so that the sixteenth grid lands on the most onset energy."""
    env, t = onset_envelope(x)
    dur = len(x) / SR
    scores = []
    for bpm in np.arange(bpm_lo, bpm_hi, step):
        six = 60.0 / bpm / 4
        for off in np.arange(0.0, 60.0 / bpm, 0.005):
            idx = np.clip(np.searchsorted(t, np.arange(off, dur, six)), 0, len(env) - 1)
            scores.append((float(env[idx].mean()), float(bpm), float(off)))
    best = max(scores)
    return best[1], best[2], best[0] / float(np.median([s[0] for s in scores]))


def chroma(x: np.ndarray, n: int = 4096, hop: int = 512, lo: float = 65.0, hi: float = 2100.0) -> tuple[np.ndarray, np.ndarray]:
    """Energy by pitch class [12, frames] and the frame times."""
    s = _stft(x, n, hop) ** 2
    f = np.fft.rfftfreq(n, 1 / SR)
    m = np.nonzero((f >= lo) & (f <= hi))[0]
    pcs = np.round(12 * np.log2(f[m] / C1)).astype(int) % 12
    c = np.zeros((12, s.shape[1]))
    for k in range(12):
        c[k] = s[m[pcs == k]].sum(axis=0)
    return c, (np.arange(s.shape[1]) * hop + n / 2) / SR


def form(x: np.ndarray, bpm: float, t1: float, meter: int = 4, thresh: float = 0.8) -> str:
    """Label each bar (A, B, C ...) by its sixteenth-by-pitch-class pattern, and list the
    bass pitch class and the nearest other bar. t1 is the time of bar 1 beat 1."""
    c, tc = chroma(x)
    b, _ = chroma(x, n=8192, hop=1024, lo=32.0, hi=131.0)
    tb = (np.arange(b.shape[1]) * 1024 + 4096) / SR
    beat = 60.0 / bpm
    slots = meter * 4
    nbars = int(round((len(x) / SR - t1) / (meter * beat)))
    vec, bass, top = [], [], []
    for i in range(nbars):
        v = np.zeros((slots, 12))
        for s in range(slots):
            a, e = t1 + (i * meter + s / 4) * beat, t1 + (i * meter + (s + 1) / 4) * beat
            sel = (tc >= a) & (tc < e)
            if sel.any():
                v[s] = c[:, sel].mean(axis=1)
        vec.append(v.ravel() / (np.linalg.norm(v) + 1e-9))
        a, e = t1 + i * meter * beat, t1 + (i + 1) * meter * beat
        bass.append(b[:, (tb >= a) & (tb < e)].mean(axis=1) if ((tb >= a) & (tb < e)).any() else np.zeros(12))
        top.append(c[:, (tc >= a) & (tc < e)].mean(axis=1) if ((tc >= a) & (tc < e)).any() else np.zeros(12))
    sim = np.array(vec) @ np.array(vec).T
    labels: list[int] = []
    reps: list[int] = []
    for i in range(nbars):
        hit = next((k for k, r in enumerate(reps) if sim[i, r] > thresh), None)
        if hit is None:
            reps.append(i)
            hit = len(reps) - 1
        labels.append(hit)
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    rows = [f"bar 1 beat 1 at {t1:.3f} s, {nbars} bars of {meter}/4, one bar = {meter * beat:.3f} s",
            "form: " + " ".join(letters[k % len(letters)] for k in labels)]
    for i in range(nbars):
        bb = np.argsort(bass[i])[::-1][:2]
        tt = np.argsort(top[i])[::-1][:5]
        near = max((sim[i, o], o) for o in range(nbars) if o != i) if nbars > 1 else (0.0, 0)
        rows.append(f"bar {i + 1:02d} [{letters[labels[i] % len(letters)]}] {t1 + i * meter * beat:6.2f} s  bass {NAMES[bb[0]]:>2}/{NAMES[bb[1]]:<2} "
                    f" top {' '.join(NAMES[k] for k in tt):<16} nearest bar {near[1] + 1:02d} ({near[0]:.2f})")
    return "\n".join(rows)


def align(x: np.ndarray, bpm: float, off: float, events: list[tuple[float, float, int]], length: float,
          top: int = 8, fine: bool = False) -> str:
    """Slide a transcription over the recording. events = (beat, length in beats, pitch class),
    beats from the start of the passage; length = the passage in beats. `off` is any grid
    beat time (from tempo_grid). Prints the best start beats and the 12-transposition control.
    fine=True uses a 93 ms window above 250 Hz, for a line that moves in sixteenths."""
    c, tc = chroma(x, n=2048, hop=256, lo=250.0, hi=4000.0) if fine else chroma(x, lo=130.0, hi=4000.0)
    cn = c / (np.linalg.norm(c, axis=0, keepdims=True) + 1e-9)
    beat = 60.0 / bpm
    nbeats = int((len(x) / SR - off) / beat)

    def score(start: int, shift: int) -> float:
        vals = []
        for b, d, pc in events:
            t0 = off + (start + b) * beat
            sel = (tc >= t0) & (tc < t0 + max(d, 0.2 if fine else 0.25) * beat)
            if sel.any():
                vals.append(cn[(pc + shift) % 12, sel].mean())
        return float(np.mean(vals)) if vals else 0.0

    res = sorted(((score(sb, 0), sb) for sb in range(-4, nbeats - int(length) + 5)), reverse=True)
    med = float(np.median([r[0] for r in res]))
    best = res[0][1]
    shifts = sorted(((score(best, k), k) for k in range(12)), reverse=True)
    rows = [f"{len(events)} notes over {length:g} beats; median score over all offsets {med:.3f}",
            "best start beats: " + "  ".join(f"{sb} ({off + sb * beat:.2f} s) {s:.3f}" for s, sb in res[:top]),
            "transposition control at the best offset: " + "  ".join(f"{k:+d} st {s:.3f}" for s, k in shifts[:4])
            + ("   WRITTEN KEY WINS" if shifts[0][1] == 0 else "   WRITTEN KEY DOES NOT WIN")]
    return "\n".join(rows)


def roll(x: np.ndarray, bpm: float, t1: float, bars: list[int], meter: int = 4) -> str:
    """The strongest pitches in each sixteenth of the named bars, by register. A number
    0-9 is the strength inside the register, * marks an onset, and (h) marks a note
    that has a stronger note a twelfth or two octaves below it (a probable overtone)."""
    beat = 60.0 / bpm
    f_lo, f_hi = np.fft.rfftfreq(8192, 1 / SR), np.fft.rfftfreq(2048, 1 / SR)
    s_lo, s_hi = _stft(x, 8192, 256), _stft(x, 2048, 256)
    t_lo, t_hi = (np.arange(s_lo.shape[1]) * 256 + 4096) / SR, (np.arange(s_hi.shape[1]) * 256 + 1024) / SR

    def semis(s: np.ndarray, f: np.ndarray, p0: int, p1: int) -> np.ndarray:
        out = np.zeros((p1 - p0, s.shape[1]), dtype=np.float32)
        st = 12 * np.log2(np.maximum(f, 1e-6) / C1) + 24
        for p in range(p0, p1):
            sel = np.abs(st - p) < 0.4
            if sel.any():
                out[p - p0] = s[sel].max(axis=0)
        return out

    regs = [("bass <C3", semis(s_lo, f_lo, 24, 48), t_lo, 24), ("mid C3-B4", semis(s_hi, f_hi, 48, 72), t_hi, 48),
            ("high C5+", semis(s_hi, f_hi, 72, 108), t_hi, 72)]
    refs = [float(np.percentile(m, 99.7)) for _, m, _, _ in regs]
    full_t = t_hi
    full = semis(s_hi, f_hi, 36, 108)

    def cell(m: np.ndarray, tt: np.ndarray, a: float, e: float) -> np.ndarray:
        sel = (tt >= a) & (tt < e)
        return m[:, sel].mean(axis=1) if sel.any() else np.zeros(m.shape[0])

    rows = []
    for b in bars:
        a0 = t1 + (b - 1) * meter * beat
        rows.append(f"--- bar {b} ({a0:.2f} s)   " + " | ".join(r[0] for r in regs))
        for s in range(meter * 4):
            a, e = a0 + s * beat / 4, a0 + (s + 1) * beat / 4
            ref_full = cell(full, full_t, a, e)
            cols = []
            for (_, m, tt, p0), ref in zip(regs, refs, strict=True):
                v, pv = cell(m, tt, a, e), cell(m, tt, a - beat / 4, a)
                items = []
                for i in np.argsort(v)[::-1][:3]:
                    st = int(min(9, 9 * v[i] / ref))
                    if st < 3:
                        continue
                    p = p0 + int(i)
                    over = any(p - h - 36 >= 0 and ref_full[p - h - 36] > 1.5 * ref_full[p - 36] for h in (19, 24)) if p >= 72 else False
                    items.append(f"{NAMES[p % 12]}{p // 12 - 1}{'*' if v[i] > 1.6 * pv[i] + 0.02 * ref else ' '}{st}{'(h)' if over else ''}")
                cols.append(" ".join(items))
            rows.append(f"  {s // 4 + 1}.{s % 4 + 1} | {cols[0]:<22}| {cols[1]:<24}| {cols[2]}")
    return "\n".join(rows)


def f0_track(x: np.ndarray, bpm: float, t1: float, bars: list[int], band: tuple[float, float] = (500.0, 3500.0),
             meter: int = 4, threshold: float = 0.35) -> str:
    """One note name for each sixteenth of the named bars, from a YIN pitch tracker on the
    signal inside `band` (Hz). Choose the band to hold the fundamentals of the line you want:
    500-3500 for a high lead, 230-1100 for a line around middle C. A dot means no clear pitch.
    threshold is YIN's limit on the normalized difference: lower reports less and errs less."""
    beat = 60.0 / bpm
    a0 = max(0.0, t1 + (min(bars) - 1) * meter * beat - 0.1)
    a1 = t1 + max(bars) * meter * beat + 0.1
    seg = x[int(a0 * SR):int(a1 * SR)].astype(np.float64)
    spec = np.fft.rfft(seg)
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    spec[(f < band[0]) | (f > band[1])] = 0
    y = np.fft.irfft(spec, len(seg))
    w, hop = 1024, 128
    tau_min, tau_max = max(2, int(SR / band[1])), int(SR / (band[0] * 0.95)) + 2
    k = max(0, 1 + (len(y) - w - tau_max) // hop)
    idx = np.arange(w + tau_max)[None, :] + hop * np.arange(k)[:, None]
    fr = y[idx]
    d = np.zeros((k, tau_max + 1))
    for tau in range(1, tau_max + 1):
        d[:, tau] = ((fr[:, :w] - fr[:, tau:tau + w]) ** 2).sum(axis=1)
    cmnd = d[:, 1:] * np.arange(1, tau_max + 1)[None, :] / np.maximum(np.cumsum(d[:, 1:], axis=1), 1e-12)
    rms = np.sqrt((fr[:, :w] ** 2).mean(axis=1))
    gate = rms > 0.05 * np.percentile(rms, 95)
    midi = np.full(k, np.nan)
    for i in range(k):
        if not gate[i]:
            continue
        c = cmnd[i, tau_min - 1:]
        below = np.nonzero(c < threshold)[0]
        if len(below) == 0:
            continue
        j = int(below[0])
        while j + 1 < len(c) and c[j + 1] < c[j]:
            j += 1
        tau = j + tau_min
        if 1 < tau < tau_max:                      # parabolic refinement of the dip
            y0, y1, y2 = cmnd[i, tau - 2], cmnd[i, tau - 1], cmnd[i, tau]
            den = y0 - 2 * y1 + y2
            tau = tau + (0.5 * (y0 - y2) / den if abs(den) > 1e-12 else 0.0)
        midi[i] = 69 + 12 * np.log2(SR / tau / 440.0)
    tt = a0 + (np.arange(k) * hop + w / 2) / SR
    rows = []
    for b in bars:
        cells = []
        for s in range(meter * 4):
            lo = t1 + ((b - 1) * meter + s / 4) * beat
            sel = (tt >= lo + 0.01) & (tt < lo + beat / 4) & ~np.isnan(midi)
            if sel.sum() >= 4:
                p = int(round(float(np.median(midi[sel]))))
                cells.append(f"{NAMES[p % 12]}{p // 12 - 1}")
            else:
                cells.append("\u00b7")
        rows.append(f"bar {b:02d}: " + " |".join(" ".join(f"{c:>4}" for c in cells[i:i + 4]) for i in range(0, meter * 4, 4)))
    return "\n".join(rows)
