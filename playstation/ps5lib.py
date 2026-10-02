"""Shared helpers for the PS5 scripts: console discovery and a typed fail()."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from typing import NoReturn

# PS5 consoles answer Remote Play discovery on UDP 9302 with protocol 00030010.
# PS4 consoles use UDP 987 with 00020020. pyremoteplay's bundled search only probes 987.
DISCOVERY_PORT = 9302
DISCOVERY_VERSION = "00030010"


def fail(msg: str) -> NoReturn:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _broadcast_address() -> str:
    out = subprocess.run(
        "ifconfig en0 | awk '/broadcast/{print $NF}'",
        shell=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return out or "255.255.255.255"


def discover(timeout: float = 3.0) -> dict[str, str] | None:
    """Return the first PS5 that answers a discovery broadcast, or None.

    The result is the console's status fields (host-ip, host-name, status, ...).
    """
    msg = f"SRCH * HTTP/1.1\ndevice-discovery-protocol-version:{DISCOVERY_VERSION}\n".encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.5)
    sock.bind(("", 0))
    try:
        for dst in {_broadcast_address(), "255.255.255.255"}:
            try:
                sock.sendto(msg, (dst, DISCOVERY_PORT))
            except OSError:
                continue
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            lines = data.decode(errors="replace").splitlines()
            fields = {"host-ip": addr[0], "status": lines[0] if lines else ""}
            for line in lines[1:]:
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
            if fields.get("host-type", "PS5") == "PS5":
                return fields
    finally:
        sock.close()
    return None


def resolve_host(explicit: str | None) -> str:
    """Pick the console address: --host, then $PS5_HOST, then LAN discovery."""
    if explicit:
        return explicit
    env = os.environ.get("PS5_HOST")
    if env:
        return env
    found = discover()
    if not found:
        fail("no PS5 answered discovery on the LAN; pass --host or set PS5_HOST")
    print(f"discovered {found.get('host-name', 'PS5')} at {found['host-ip']}")
    return found["host-ip"]


def install_av_compat() -> None:
    """Patch pyremoteplay's AVReceiver for current PyAV (renamed enums, layout names).

    pyremoteplay 0.7.6 (2022) sets codec flags through ``Flags.LOW_DELAY`` and
    ``Flags2.FAST`` and builds its AudioResampler from a channel count. PyAV 14 and later
    spell the flags in lower case and want a layout name. Call once before a session.
    """
    import av
    from pyremoteplay.receiver import AVReceiver

    flags = av.codec.context.Flags
    flags2 = av.codec.context.Flags2
    low_delay = getattr(flags, "low_delay", None) or flags.LOW_DELAY
    fast = getattr(flags2, "fast", None) or flags2.FAST

    def video_codec(codec_name: str):
        ctx = av.codec.Codec(codec_name, "r").create()
        if codec_name.startswith("h264"):
            ctx.options = AVReceiver.AV_CODEC_OPTIONS_H264
        elif codec_name.startswith("hevc"):
            ctx.options = AVReceiver.AV_CODEC_OPTIONS_HEVC
        ctx.pix_fmt = "yuv420p"
        ctx.flags = low_delay
        ctx.flags2 = fast
        ctx.thread_type = av.codec.context.ThreadType.AUTO
        return ctx

    def audio_resampler(
        audio_format: str = "s16", channels: int = 2, rate: int = 48000
    ):
        layout = "mono" if channels == 1 else "stereo"
        return av.audio.resampler.AudioResampler(audio_format, layout, rate)

    AVReceiver.video_codec = staticmethod(video_codec)
    AVReceiver.audio_resampler = staticmethod(audio_resampler)
