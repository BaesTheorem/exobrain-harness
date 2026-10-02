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
