#!/usr/bin/env python3
"""Smoke test for the PS5 Remote Play link: frames in, button taps out.

Streams from the console for a few seconds through pyremoteplay, counts decoded video
frames, saves a sample of them as PNG, and taps a button part way through (RIGHT then
LEFT on the home screen by default, which moves the selection and then moves it back).
The saved frames before and after the tap are the proof that both directions work.

Run with the ``playstation/.venv`` interpreter after ``ps5-pair.py register``.
Exit code 0 means frames arrived and the taps were sent.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import sys
import time

from pyremoteplay import RPDevice
from pyremoteplay.profile import Profiles

from ps5lib import fail, install_av_compat, resolve_host
from pyremoteplay.receiver import QueueReceiver

DEFAULT_OUT = pathlib.Path(__file__).resolve().parents[1] / "tmp" / "ps5-smoke"


class CountingReceiver(QueueReceiver):
    """QueueReceiver that counts every decoded video frame."""

    def __init__(self) -> None:
        super().__init__(max_frames=4)
        self.video_count = 0
        self.first_frame_at: float | None = None

    def handle_video(self, frame) -> None:
        if self.first_frame_at is None:
            self.first_frame_at = time.monotonic()
        self.video_count += 1
        super().handle_video(frame)


async def run(args: argparse.Namespace) -> int:
    install_av_compat()
    profiles = Profiles.load()
    users = profiles.usernames
    if not users:
        fail("no registered profile; run ps5-pair.py first")
    user = args.user or users[0]
    device = RPDevice(args.host)
    if not device.get_status():
        fail(f"no answer from {args.host}")
    print(
        f"{device.host_name}: {device.status_name}, app: {device.app_name or '(home screen)'}"
    )

    receiver = CountingReceiver()
    session = device.create_session(
        user,
        profiles=profiles,
        receiver=receiver,
        resolution=args.resolution,
        fps=args.fps,
        quality="default",
        codec="h264",
    )
    if session is None:
        fail("could not create a session (is this user registered with the console?)")
    t_connect = time.monotonic()
    if not await device.connect():
        fail(f"session did not start: {session.error}")
    if not await device.async_wait_for_session():
        fail(f"timed out waiting for the stream: {session.error}")
    print(f"stream up in {time.monotonic() - t_connect:.1f}s, codec {session.codec}")
    device.controller.start()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    saved: list[pathlib.Path] = []
    taps: list[str] = []
    t0 = time.monotonic()
    next_save = 0.0
    while time.monotonic() - t0 < args.seconds:
        elapsed = time.monotonic() - t0
        frame = receiver.get_latest_video_frame()
        if frame is not None and elapsed >= next_save:
            path = out / f"frame-{elapsed:04.1f}s.png"
            frame.to_image().save(path)
            saved.append(path)
            next_save = elapsed + args.save_every
        if args.press and elapsed >= 3.0 and len(taps) == 0:
            await device.controller.async_button(args.press)
            taps.append(args.press)
        if args.press and args.undo and elapsed >= 5.0 and len(taps) == 1:
            await device.controller.async_button(args.undo)
            taps.append(args.undo)
        await asyncio.sleep(0.05)

    frames = receiver.video_count
    span = time.monotonic() - (receiver.first_frame_at or t0)
    fps = frames / span if span > 0 else 0.0
    size = "?"
    last = receiver.get_latest_video_frame()
    if last is not None:
        size = f"{last.width}x{last.height}"
    device.controller.stop()
    device.disconnect()

    print(f"frames decoded: {frames} ({fps:.1f} fps, {size})")
    print(f"taps sent: {taps or 'none'}")
    print(f"saved {len(saved)} PNGs in {out}")
    ok = frames > 0 and (not args.press or len(taps) >= 1)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument(
        "--host", help="PS5 address; default $PS5_HOST or LAN discovery"
    )
    parser.add_argument("--user", help="profile name; default is the first registered")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--resolution", default="720p", help="360p, 540p, 720p, 1080p")
    parser.add_argument("--fps", default="low", help="low (30) or high (60)")
    parser.add_argument(
        "--press", default="RIGHT", help="button to tap at 3s; '' for none"
    )
    parser.add_argument(
        "--undo", default="LEFT", help="button to tap at 5s; '' for none"
    )
    parser.add_argument(
        "--save-every", type=float, default=1.0, help="seconds between PNGs"
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    args.host = resolve_host(args.host)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
