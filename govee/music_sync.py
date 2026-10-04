"""govee-music: drive Govee bulbs from the audio of one app on this Mac.

    govee-music [--process NAME] [--target GROUP] [--mood auto|COLOR|KELVIN]
                [--rate HZ] [--min PCT] [--max PCT] [--dry-run] [--verbose]

The app's audio is read with AudioTee (a Core Audio process tap, so the speakers keep
playing and nothing else is captured). Each chunk gives a loudness, a bass onset, and a
spectral centroid. Loudness sets the brightness, a bass hit adds a short flash, and the
centroid moves the color along a palette from purple and red (dark, low) through amber to
green and cyan (bright, high). "--mood" fixes the color; brightness still follows the sound.

The bulbs get raw UDP commands on port 4003 (the Govee LAN API), one socket per bulb, so
one tick costs microseconds. The bulbs' state is read before the run and put back on exit.

INVARIANTS:
- Never touch a bulb that is not in the target. The restore writes only what it read.
- The tap must never mute the app: --mute is not passed to AudioTee.
- A chunk that fails to parse is dropped, never fed to the smoother as zeros.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np  # pyright: ignore[reportMissingImports]

import govee_cli as g

HERE = Path(__file__).resolve().parent
AUDIOTEE = Path(os.environ.get("AUDIOTEE", Path.home() / ".local/src/audiotee/.build/release/audiotee"))
COMMAND_PORT = 4003
SAMPLE_RATE = 16000  # AudioTee converts to 16-bit signed int at any explicit rate
CHUNK_S = 0.05

# Spectral centroid (Hz) -> color. Low and dark music sits in purple and red, lively mid
# ranges in amber, airy high ranges in green and cyan. Linear blend between stops.
PALETTE = [
    (300, (120, 0, 255)),
    (600, (255, 0, 40)),
    (1000, (255, 90, 0)),
    (1600, (255, 170, 40)),
    (2600, (60, 220, 120)),
    (4000, (0, 200, 255)),
]


def palette_color(centroid: float) -> tuple[float, float, float]:
    if centroid <= PALETTE[0][0]:
        return PALETTE[0][1]
    for (lo, a), (hi, b) in zip(PALETTE, PALETTE[1:], strict=False):
        if centroid <= hi:
            t = (centroid - lo) / (hi - lo)
            return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))  # type: ignore[return-value]
    return PALETTE[-1][1]


class Smoother:
    """One-pole smoothing with separate attack and release time constants (seconds)."""

    def __init__(self, attack: float, release: float, value: float = 0.0) -> None:
        self.attack, self.release, self.value = attack, release, value

    def push(self, x: float, dt: float) -> float:
        tau = self.attack if x > self.value else self.release
        k = 1 - math.exp(-dt / tau) if tau > 0 else 1.0
        self.value += (x - self.value) * k
        return self.value


class Analyzer:
    """Turn a chunk of mono int16 samples into loudness (0-1), bass onset (0-1), centroid (Hz)."""

    def __init__(self) -> None:
        self.peak = 1e-3  # running loudness ceiling (automatic gain)
        self.floor = 1e-3  # running loudness floor
        self.bass_avg = 1e-6
        self.freqs: np.ndarray | None = None
        self.window: np.ndarray | None = None

    def analyze(self, chunk: np.ndarray, dt: float) -> tuple[float, float, float]:
        x = chunk.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
        # Gain control: the ceiling falls slowly, the floor rises slowly, so a quiet scene
        # still uses the full brightness range after a few seconds.
        self.peak = max(rms, self.peak * math.exp(-dt / 8.0))
        self.floor = min(rms, self.floor + (self.peak - self.floor) * (1 - math.exp(-dt / 20.0)))
        span = max(self.peak - self.floor, 1e-4)
        loud = min(1.0, max(0.0, (rms - self.floor) / span))

        if self.window is None or len(self.window) != len(x):
            self.window = np.hanning(len(x)).astype(np.float32)
            self.freqs = np.fft.rfftfreq(len(x), 1 / SAMPLE_RATE)
        spec = np.abs(np.fft.rfft(x * self.window))
        assert self.freqs is not None
        power = spec * spec
        total = float(power.sum()) + 1e-9
        centroid = float((self.freqs * power).sum() / total)

        bass = float(power[(self.freqs >= 40) & (self.freqs <= 160)].sum())
        onset = max(0.0, (bass - self.bass_avg * 1.8) / (self.bass_avg * 3 + 1e-9))
        self.bass_avg += (bass - self.bass_avg) * (1 - math.exp(-dt / 1.5))
        return loud, min(1.0, onset), centroid


class Bulb:
    def __init__(self, device: g.GoveeDevice, name: str) -> None:
        self.device, self.name = device, name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.connect((device.ip, COMMAND_PORT))
        self.brightness = -1
        self.color: tuple[int, int, int] | None = None
        self.saved = (device.on, device.brightness, device.temperature_color, device.rgb_color)

    def send(self, cmd: str, data: dict) -> None:
        self.sock.send(json.dumps({"msg": {"cmd": cmd, "data": data}}, separators=(",", ":")).encode())

    def set_brightness(self, pct: int) -> None:
        if pct != self.brightness:
            self.brightness = pct
            self.send("brightness", {"value": pct})

    def set_color(self, rgb: tuple[int, int, int]) -> None:
        if rgb != self.color:
            self.color = rgb
            self.send("colorwc", {"color": {"r": rgb[0], "g": rgb[1], "b": rgb[2]}, "colorTemInKelvin": 0})

    def set_temperature(self, kelvin: int) -> None:
        self.send("colorwc", {"color": {"r": 0, "g": 0, "b": 0}, "colorTemInKelvin": kelvin})

    def restore(self) -> None:
        on, brightness, kelvin, rgb = self.saved
        if on is None:
            return
        if kelvin:
            self.set_temperature(kelvin)
        elif rgb:
            self.color = None
            self.set_color(tuple(rgb))  # type: ignore[arg-type]
        if brightness:
            self.brightness = -1
            self.set_brightness(brightness)
        self.send("turn", {"value": int(bool(on))})


def find_pids(name: str) -> list[int]:
    out = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out]


def parse_mood(text: str) -> tuple[int, int, int] | None:
    """'auto' -> None (follow the music). A color name, #rrggbb, r,g,b, or warm/cool -> fixed RGB."""
    if text.lower() == "auto":
        return None
    if text.lower() in g.NAMED_TEMPS:
        return kelvin_to_rgb(g.NAMED_TEMPS[text.lower()])
    if text.isdigit():
        return kelvin_to_rgb(int(text))
    return g.parse_color(text)


def kelvin_to_rgb(kelvin: int) -> tuple[int, int, int]:
    """Tanner Helland's approximation, enough for a mood color."""
    t = max(1000, min(kelvin, 40000)) / 100
    r = 255 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    gg = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255 if t >= 66 else (0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    return tuple(int(max(0, min(255, v))) for v in (r, gg, b))  # type: ignore[return-value]


async def run(args: argparse.Namespace) -> int:
    pids = find_pids(args.process)
    if not pids and not args.system:
        raise SystemExit(f"govee-music: no process named {args.process!r} is running (or pass --system)")
    if not AUDIOTEE.exists():
        raise SystemExit(f"govee-music: AudioTee binary missing at {AUDIOTEE} (see govee/README.md)")

    cache = g.load_cache()
    controller = await g.discover(cache, False)
    devices = g.select(cache, list(controller.devices), args.target)
    await g.read_status(controller, devices)
    bulbs = [Bulb(d, g.label(cache, d)) for d in devices]
    controller.cleanup()
    for b in bulbs:
        if b.device.on is None:
            print(f"govee-music: {b.name} gave no status; it will not be restored on exit", file=sys.stderr)

    cmd = [str(AUDIOTEE), "--sample-rate", str(SAMPLE_RATE), "--chunk-duration", str(CHUNK_S)]
    if pids:
        cmd += ["--include-processes", *map(str, pids)]
    tap = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE if not args.verbose else None
    )
    assert tap.stdout is not None
    print(
        f"govee-music: {args.process if pids else 'system audio'} -> {', '.join(b.name for b in bulbs)}"
        f" at {args.rate} Hz, mood {args.mood} (Ctrl-C to stop and restore)",
        file=sys.stderr,
    )

    fixed = parse_mood(args.mood)
    analyzer = Analyzer()
    loud_s = Smoother(attack=0.08, release=0.5)
    color_s = [Smoother(attack=2.5, release=2.5, value=c) for c in (fixed or (255, 170, 40))]
    flash = 0.0
    chunk_bytes = int(SAMPLE_RATE * CHUNK_S) * 2
    last = time.monotonic()
    next_tick = last
    last_report = last
    quiet_since: float | None = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    if not args.dry_run:
        for b in bulbs:
            b.send("turn", {"value": 1})

    try:
        while not stop.is_set():
            try:
                raw = await asyncio.wait_for(tap.stdout.readexactly(chunk_bytes), timeout=2.0)
            except asyncio.IncompleteReadError:
                print("govee-music: the audio tap closed", file=sys.stderr)
                break
            except asyncio.TimeoutError:
                if tap.returncode is not None:
                    err = (await tap.stderr.read()).decode() if tap.stderr else ""
                    print(f"govee-music: AudioTee exited {tap.returncode}\n{err[-800:]}", file=sys.stderr)
                    return 1
                print("govee-music: no audio for 2 s (is the app playing, and is System Audio Recording allowed?)", file=sys.stderr)
                continue
            now = time.monotonic()
            dt, last = now - last, now
            chunk = np.frombuffer(raw, dtype="<i2")
            loud, onset, centroid = analyzer.analyze(chunk, dt)

            if analyzer.peak < 2e-4:  # digital silence or near it
                quiet_since = quiet_since or now
            else:
                quiet_since = None
            level = loud_s.push(loud, dt)
            flash = max(flash * math.exp(-dt / 0.12), onset * args.flash)
            target_rgb = fixed or palette_color(centroid)
            rgb = tuple(int(round(s.push(c, dt))) for s, c in zip(color_s, target_rgb, strict=True))
            if quiet_since and now - quiet_since > 3:
                level = 0.0
            pct = int(round(args.min + (args.max - args.min) * min(1.0, level + flash)))

            if now >= next_tick:
                next_tick = now + 1 / args.rate
                if not args.dry_run:
                    for b in bulbs:
                        b.set_color(rgb)  # type: ignore[arg-type]
                        b.set_brightness(pct)
            if args.verbose and now - last_report >= 1:
                last_report = now
                print(
                    f"loud {loud:4.2f} level {level:4.2f} flash {flash:4.2f} centroid {centroid:6.0f}Hz"
                    f" -> {pct:3d}% #{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}",
                    file=sys.stderr,
                )
    finally:
        if tap.returncode is None:
            tap.terminate()
        if not args.dry_run:
            for b in bulbs:
                b.restore()
            print("govee-music: bulbs restored", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="govee-music", description=(__doc__ or "").split("\n\n")[1])
    p.add_argument("--process", default="Pocket Bard", help="exact process name to tap (default: Pocket Bard)")
    p.add_argument("--system", action="store_true", help="tap all system audio when the process is not found")
    p.add_argument("--target", default="dining-room", help="bulb, group, or comma list (default: dining-room)")
    p.add_argument("--mood", default="auto", help="auto, a color name, #rrggbb, r,g,b, warm/cool, or Kelvin")
    p.add_argument("--rate", type=float, default=12.0, help="bulb updates per second (default: 12)")
    p.add_argument("--min", type=int, default=8, help="brightness floor in percent (default: 8)")
    p.add_argument("--max", type=int, default=100, help="brightness ceiling in percent (default: 100)")
    p.add_argument("--flash", type=float, default=0.35, help="bass-hit flash strength 0-1 (default: 0.35)")
    p.add_argument("--dry-run", action="store_true", help="analyze and report, send nothing to the bulbs")
    p.add_argument("--verbose", "-v", action="store_true", help="one analysis line per second")
    args = p.parse_args()
    if not 1 <= args.min < args.max <= 100:
        raise SystemExit("govee-music: need 1 <= --min < --max <= 100")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
