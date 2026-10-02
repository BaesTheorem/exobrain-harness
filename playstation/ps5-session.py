#!/usr/bin/env python3
"""Persistent PS5 Remote Play link: live frames out, controller commands in.

Holds one Remote Play session open through pyremoteplay, writes the latest decoded frame
to ``<dir>/latest.jpg`` every ``--frame-interval`` seconds, and serves a one-line command
protocol on the UNIX socket ``<dir>/ctl.sock``. ``ps5ctl`` is the client.

Commands (one request per connection, ``;`` separates a sequence, replies start with
``ok`` or ``err``)::

    tap BTN [ms]          press and release (default 100 ms hold)
    press BTN             hold a button down until release
    release BTN
    stick left|right X Y  set a stick; X: left -1 .. right 1, Y: up -1 .. down 1
    move X Y MS           left stick for MS ms, then centered (walk)
    look X Y MS           right stick for MS ms, then centered (turn)
    center                both sticks to rest
    wait MS
    snap [PATH]           save the latest frame as a full-size PNG, reply with the path
    status                JSON: frames, fps, uptime, size, last command, error
    quit                  disconnect and exit

Button names are case-insensitive. Aliases: x, o, sq, tri, opt, dup/ddown/dleft/dright.
Run with the ``playstation/.venv`` interpreter. Exit code 2 when the session drops.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import pathlib
import signal
import sys
import time

from pyremoteplay import RPDevice
from pyremoteplay.profile import Profiles
from pyremoteplay.receiver import QueueReceiver

from ps5lib import fail, install_av_compat, resolve_host

DEFAULT_DIR = pathlib.Path(__file__).resolve().parents[1] / "tmp" / "ps5-live"
BUTTONS = {
    "UP", "DOWN", "LEFT", "RIGHT", "L1", "R1", "L2", "R2", "CROSS", "CIRCLE", "SQUARE",
    "TRIANGLE", "OPTIONS", "SHARE", "PS", "L3", "R3", "TOUCHPAD",
}  # fmt: skip
ALIASES = {
    "X": "CROSS", "O": "CIRCLE", "SQ": "SQUARE", "TRI": "TRIANGLE", "OPT": "OPTIONS",
    "DUP": "UP", "DDOWN": "DOWN", "DLEFT": "LEFT", "DRIGHT": "RIGHT", "START": "OPTIONS",
}  # fmt: skip

log = logging.getLogger("ps5-session")


class LiveReceiver(QueueReceiver):
    """QueueReceiver that counts frames and remembers when the last one arrived."""

    def __init__(self) -> None:
        super().__init__(max_frames=2)
        self.video_count = 0
        self.last_frame_at = 0.0
        self._window: list[float] = []

    def handle_video(self, frame) -> None:
        now = time.monotonic()
        self.video_count += 1
        self.last_frame_at = now
        self._window.append(now)
        if len(self._window) > 90:
            del self._window[: len(self._window) - 90]
        super().handle_video(frame)

    def fps(self) -> float:
        if len(self._window) < 2:
            return 0.0
        span = self._window[-1] - self._window[0]
        return (len(self._window) - 1) / span if span > 0 else 0.0


def norm_button(name: str) -> str:
    key = name.upper()
    key = ALIASES.get(key, key)
    if key not in BUTTONS:
        raise ValueError(f"unknown button {name!r}; valid: {sorted(BUTTONS)}")
    return key


class Link:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.dir = pathlib.Path(args.dir)
        self.receiver = LiveReceiver()
        self.device = RPDevice(args.host)
        self.session = None
        self.started = time.monotonic()
        self.last_cmd = ""
        self.lock = asyncio.Lock()
        self.stop = asyncio.Event()
        self.error = ""

    # --- session -------------------------------------------------------------
    async def connect(self) -> None:
        profiles = Profiles.load()
        users = profiles.usernames
        if not users:
            fail("no registered profile; run ps5-pair.py first")
        user = self.args.user or users[0]
        if not self.device.get_status():
            fail(f"no answer from {self.args.host}")
        self.session = self.device.create_session(
            user,
            profiles=profiles,
            receiver=self.receiver,
            resolution=self.args.resolution,
            fps=self.args.fps,
            quality="default",
            codec="h264",
        )
        if self.session is None:
            fail("could not create a session")
        if not await self.device.connect():
            fail(f"session did not start: {self.session.error}")
        if not await self.device.async_wait_for_session(timeout=30):
            fail(f"timed out waiting for the stream: {self.session.error}")
        self.device.controller.start()
        self.session.events.on("stop", self._on_stop)
        log.info("stream up: codec %s, user %s", self.session.codec, user)

    def _on_stop(self) -> None:
        self.error = (self.session.error if self.session else "") or "session stopped"
        log.warning("session stopped: %s", self.error)
        self.stop.set()

    # --- frames --------------------------------------------------------------
    async def frame_writer(self) -> None:
        latest = self.dir / "latest.jpg"
        tmp = self.dir / "latest.jpg.tmp"
        while not self.stop.is_set():
            frame = self.receiver.get_latest_video_frame()
            if frame is not None:
                try:
                    frame.to_image().save(
                        tmp, format="JPEG", quality=self.args.jpeg_quality
                    )
                    os.replace(tmp, latest)
                except Exception as exc:  # noqa: BLE001 - keep the writer alive
                    log.warning("frame write failed: %s", exc)
            await asyncio.sleep(self.args.frame_interval)

    def snap(self, path: str | None) -> str:
        frame = self.receiver.get_latest_video_frame()
        if frame is None:
            raise RuntimeError("no frame yet")
        target = (
            pathlib.Path(path)
            if path
            else self.dir / f"snap-{time.strftime('%H%M%S')}.png"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_image().save(target)
        return str(target)

    # --- commands ------------------------------------------------------------
    def status(self) -> dict:
        frame = self.receiver.get_latest_video_frame()
        return {
            "frames": self.receiver.video_count,
            "fps": round(self.receiver.fps(), 1),
            "frame_age_s": round(time.monotonic() - self.receiver.last_frame_at, 2)
            if self.receiver.last_frame_at
            else None,
            "size": f"{frame.width}x{frame.height}" if frame is not None else None,
            "uptime_s": round(time.monotonic() - self.started, 1),
            "last_cmd": self.last_cmd,
            "error": self.error,
        }

    async def run_one(self, words: list[str]) -> str:
        ctl = self.device.controller
        op = words[0].lower()
        if op == "tap":
            btn = norm_button(words[1])
            ms = int(words[2]) if len(words) > 2 else 100
            await ctl.async_button(btn, "tap", delay=ms / 1000)
            return f"ok tap {btn} {ms}ms"
        if op in ("press", "release"):
            btn = norm_button(words[1])
            ctl.button(btn, op)
            return f"ok {op} {btn}"
        if op == "stick":
            side = words[1].lower()
            x, y = float(words[2]), float(words[3])
            ctl.stick(side, point=(x, y))
            return f"ok stick {side} {x} {y}"
        if op in ("move", "look"):
            side = "left" if op == "move" else "right"
            x, y, ms = float(words[1]), float(words[2]), int(words[3])
            ctl.stick(side, point=(x, y))
            await asyncio.sleep(ms / 1000)
            ctl.stick(side, point=(0.0, 0.0))
            return f"ok {op} {x} {y} {ms}ms"
        if op == "center":
            ctl.stick("left", point=(0.0, 0.0))
            ctl.stick("right", point=(0.0, 0.0))
            return "ok center"
        if op == "wait":
            await asyncio.sleep(int(words[1]) / 1000)
            return f"ok wait {words[1]}ms"
        if op == "snap":
            return "ok " + self.snap(" ".join(words[1:]) if len(words) > 1 else None)
        if op == "status":
            return "ok " + json.dumps(self.status())
        if op == "quit":
            self.error = "quit requested"
            self.stop.set()
            return "ok quit"
        raise ValueError(f"unknown command {op!r}")

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            line = (
                (await asyncio.wait_for(reader.readline(), timeout=5)).decode().strip()
            )
        except (asyncio.TimeoutError, UnicodeDecodeError):
            writer.close()
            return
        replies = []
        async with self.lock:
            for part in filter(None, (p.strip() for p in line.split(";"))):
                words = part.split()
                try:
                    replies.append(await self.run_one(words))
                except (ValueError, IndexError, RuntimeError) as exc:
                    replies.append(f"err {part!r}: {exc}")
                    break
            self.last_cmd = line
        log.info("cmd %r -> %s", line, " | ".join(replies))
        writer.write(("\n".join(replies) + "\n").encode())
        await writer.drain()
        writer.close()

    # --- lifecycle -----------------------------------------------------------
    async def run(self) -> int:
        self.dir.mkdir(parents=True, exist_ok=True)
        sock = self.dir / "ctl.sock"
        if sock.exists():
            sock.unlink()
        await self.connect()
        server = await asyncio.start_unix_server(self.handle, path=str(sock))
        (self.dir / "session.pid").write_text(str(os.getpid()))
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop.set)
        writer = asyncio.create_task(self.frame_writer())
        log.info("ready: socket %s, frames in %s", sock, self.dir / "latest.jpg")
        await self.stop.wait()
        writer.cancel()
        server.close()
        self.device.controller.stop()
        self.device.disconnect()
        for leftover in (sock, self.dir / "session.pid"):
            if leftover.exists():
                leftover.unlink()
        log.info("link closed: %s", self.error or "clean exit")
        return 2 if self.error and self.error != "quit requested" else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--host", help="PS5 address; default $PS5_HOST or LAN discovery"
    )
    parser.add_argument("--user", help="profile name; default is the first registered")
    parser.add_argument("--resolution", default="720p")
    parser.add_argument("--fps", default="low", help="low (30) or high (60)")
    parser.add_argument("--dir", default=str(DEFAULT_DIR))
    parser.add_argument("--frame-interval", type=float, default=0.5)
    parser.add_argument("--jpeg-quality", type=int, default=80)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    pathlib.Path(args.dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(pathlib.Path(args.dir) / "session.log"),
            logging.StreamHandler(sys.stderr),
        ],
    )
    logging.getLogger("pyremoteplay").setLevel(logging.WARNING)
    args.host = resolve_host(args.host)
    install_av_compat()
    sys.exit(asyncio.run(Link(args).run()))


if __name__ == "__main__":
    main()
