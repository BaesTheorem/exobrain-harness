"""Audio mix for a project: the song, leveled dialogue slices from the film, sound effects,
dialogue-keyed ducking of the song, static loudness gain and a true-peak-safe limiter.

  mist-vid audio edit.yaml -o work/mix.wav

YAML `audio:` entries (times are anchors, see timeline.py):
  - {kind: song, at: o26.0, gain: 0}                      # the song file from project.song
  - {kind: dlg, src: 128.38, len: 3.4, at: o1.5, gain: 0, mode: center|full, fade: 0.03, duck: 8}
  - {kind: sfx, file: asset:sfx/rpg-audio/Audio/bookFlip1.ogg, at: b40, gain: -6, rate: 1.0}
  - {kind: synth, name: boom|riser|sub|whoosh, at: o5, len: 1.2, gain: -8}
"""
from __future__ import annotations

import argparse
import os
import subprocess
import zlib

import numpy as np

from .paths import asset
from .timeline import Project

SR = 48000


def decode(path: str, start: float | None = None, dur: float | None = None, channels: int = 2,
           layout_pan: str | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{max(0.0, start):.4f}"]
    cmd += ["-i", path]
    if dur is not None:
        cmd += ["-t", f"{dur:.4f}"]
    cmd += ["-vn", "-sn"]
    if layout_pan:
        cmd += ["-af", layout_pan]
    cmd += ["-ac", str(channels), "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, channels).copy()


def level_p90(x: np.ndarray, target_db: float = -20.0) -> float:
    """Gain (linear) that puts the 90th percentile of 50 ms RMS frames at target_db."""
    mono = x.mean(axis=1)
    n = int(SR * 0.05)
    if len(mono) < n:
        return 1.0
    fr = mono[: len(mono) // n * n].reshape(-1, n)
    rms = np.sqrt((fr ** 2).mean(axis=1) + 1e-12)
    p90 = np.percentile(rms, 90)
    return float(10 ** (target_db / 20) / max(p90, 1e-6))


def fade(x: np.ndarray, fin: float, fout: float) -> np.ndarray:
    n = len(x)
    a, b = int(fin * SR), int(fout * SR)
    if a > 0:
        x[:a] *= np.linspace(0, 1, min(a, n))[:, None][: min(a, n)]
    if b > 0:
        x[-b:] *= np.linspace(1, 0, min(b, n))[:, None][-min(b, n):]
    return x


def synth(name: str, dur: float) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(zlib.crc32(name.encode()))  # hash() is salted per process
    if name == "boom":      # cinematic sub hit with a noise transient
        f = 55 * np.exp(-t * 3.0) + 32
        ph = 2 * np.pi * np.cumsum(f) / SR
        body = np.sin(ph) * np.exp(-t * 2.6)
        click = rng.standard_normal(n) * np.exp(-t * 60) * 0.35
        y = np.tanh((body + click) * 1.6) * 0.9
    elif name == "sub":     # soft low swell
        y = np.sin(2 * np.pi * 38 * t) * np.sin(np.pi * np.clip(t / dur, 0, 1)) * 0.8
    elif name == "riser":   # filtered noise + rising tone
        noise = rng.standard_normal(n)
        k = np.linspace(0.02, 0.35, n)
        lp = np.zeros(n)
        acc = 0.0
        for i in range(n):
            acc += k[i] * (noise[i] - acc)
            lp[i] = acc
        tone = np.sin(2 * np.pi * np.cumsum(np.linspace(180, 900, n)) / SR) * 0.25
        env = (t / dur) ** 2.2
        y = (lp * 0.9 + tone) * env
    elif name == "whoosh":
        noise = rng.standard_normal(n)
        env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
        k = 0.05 + 0.4 * env
        lp = np.zeros(n)
        acc = 0.0
        for i in range(n):
            acc += k[i] * (noise[i] - acc)
            lp[i] = acc
        y = lp * env * 1.2
    elif name == "shimmer":  # high sparkle for gold glints
        y = np.zeros(n)
        for f0 in (2093, 2637, 3136, 4186):
            y += np.sin(2 * np.pi * f0 * t + rng.uniform(0, 6)) * np.exp(-t * rng.uniform(2.5, 4.0))
        y *= 0.12 * np.clip(t / 0.01, 0, 1)
    else:
        raise ValueError(name)
    y = y.astype(np.float32)
    return np.stack([y, y], axis=1)


def smooth_env(x: np.ndarray, attack: float, release: float) -> np.ndarray:
    """One-pole attack/release follower over a control signal sampled at 1 kHz."""
    out = np.zeros_like(x)
    a_up = 1 - np.exp(-1 / (attack * 1000))
    a_dn = 1 - np.exp(-1 / (release * 1000))
    v = 0.0
    for i, s in enumerate(x):
        v += (s - v) * (a_up if s > v else a_dn)
        out[i] = v
    return out


def build(P: Project, total: float | None = None) -> np.ndarray:
    total = total or P.duration
    N = int(total * SR) + SR
    bus_song = np.zeros((N, 2), np.float32)
    bus_dlg = np.zeros((N, 2), np.float32)
    bus_sfx = np.zeros((N, 2), np.float32)
    duck_ctl = np.zeros(int(total * 1000) + 1000, np.float32)   # dB of ducking wanted, at 1 kHz
    src_path = P.p["source"]

    def put(bus, sig, at):
        i = int(round(at * SR))
        if i < 0:
            sig = sig[-i:]
            i = 0
        j = min(N, i + len(sig))
        if j > i:
            bus[i:j] += sig[: j - i]

    for e in P.audio:
        kind = e["kind"]
        at = P.anchor(e["at"]) if "at" in e else 0.0
        g = 10 ** (float(e.get("gain", 0.0)) / 20)
        if kind == "song":
            y = decode(P.p["song"])
            if "trim" in e:
                a, b = e["trim"]
                y = y[int(a * SR): int(b * SR) if b else None]
            put(bus_song, fade(y * g, float(e.get("fade_in", 0.0)), float(e.get("fade_out", 0.0))), at)
        elif kind == "dlg":
            s = float(e["src"])
            ln = float(e["len"])
            mode = e.get("mode", "center")
            pan = {"center": "pan=stereo|c0=FC|c1=FC",
                   "full": "pan=stereo|c0=0.5*FL+0.707*FC+0.5*BL|c1=0.5*FR+0.707*FC+0.5*BR",
                   "wide": "pan=stereo|c0=FL+0.707*FC+0.6*BL|c1=FR+0.707*FC+0.6*BR"}[mode]
            y = decode(src_path, s, ln, 2, pan)
            if e.get("level", True):
                y = y * level_p90(y, float(e.get("target", -20.0)))
            y = fade(y * g, float(e.get("fade", 0.03)), float(e.get("fade_out", e.get("fade", 0.05))))
            put(bus_dlg, y, at)
            duck = float(e.get("duck", 7.0))
            if duck > 0:
                a0, a1 = int(at * 1000), int((at + ln) * 1000)
                duck_ctl[max(0, a0):max(0, a1)] = np.maximum(duck_ctl[max(0, a0):max(0, a1)], duck)
        elif kind == "sfx":
            y = decode(asset(e["file"]))
            if e.get("rate", 1.0) != 1.0:
                idx = np.arange(0, len(y) - 1, float(e["rate"]))
                y = np.stack([np.interp(idx, np.arange(len(y)), y[:, c]) for c in range(2)], axis=1).astype(np.float32)
            if e.get("level", False):
                y = y * level_p90(y, float(e.get("target", -20.0)))
            put(bus_sfx, fade(y * g, 0.005, float(e.get("fade_out", 0.02))), at)
        elif kind == "synth":
            y = synth(e["name"], float(e.get("len", 1.0)))
            put(bus_sfx, y * g, at)
        elif kind == "duck":   # explicit song ducking window
            a0, a1 = int(at * 1000), int(P.anchor(e["to"]) * 1000)
            duck_ctl[a0:a1] = np.maximum(duck_ctl[a0:a1], float(e.get("db", 6.0)))
    # song ducking: smooth the dB control, then apply as gain
    env = smooth_env(duck_ctl, attack=0.12, release=0.45)
    gain = 10 ** (-env / 20)
    gs = np.interp(np.arange(N) / SR, np.arange(len(gain)) / 1000, gain).astype(np.float32)
    mix = bus_song * gs[:, None] + bus_dlg + bus_sfx
    return mix[: int(total * SR)]


def master(mix: np.ndarray, out: str, lufs: float = -14.0, ceiling_db: float = -1.6):
    tmp = out + ".pre.wav"
    write_wav(tmp, mix)
    meas = subprocess.run(["ffmpeg", "-v", "info", "-i", tmp, "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                          capture_output=True, text=True).stderr
    il = None
    for line in meas.splitlines()[::-1]:
        if line.strip().startswith("I:") and "LUFS" in line:
            il = float(line.split()[1])
            break
    g = 0.0 if il is None else lufs - il
    lim = 10 ** (ceiling_db / 20)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", tmp, "-af",
                    # 4x oversampling makes the limiter catch inter-sample (true) peaks
                    f"volume={g:.2f}dB,aresample=192000,alimiter=limit={lim:.4f}:attack=3:release=60:level=disabled,"
                    f"aresample=48000",
                    "-c:a", "pcm_s24le", out], check=True)
    os.remove(tmp)
    return il, g


def write_wav(path: str, x: np.ndarray):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                          "-c:a", "pcm_f32le", path], stdin=subprocess.PIPE)
    stdin = p.stdin
    assert stdin is not None
    stdin.write(np.ascontiguousarray(x.astype(np.float32)).tobytes())
    stdin.close()
    p.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("-o", "--out", default="work/mix.wav")
    ap.add_argument("--lufs", type=float, default=-14.0)
    a = ap.parse_args()
    P = Project(a.project)
    mix = build(P)
    il, g = master(mix, a.out, a.lufs)
    print(f"mix {a.out}: {len(mix) / SR:.2f}s, pre-master {il} LUFS, gain {g:+.2f} dB")


if __name__ == "__main__":
    main()
