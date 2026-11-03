"""govee_ble: Bluetooth LE control for Govee H6008 bulbs that use the encoded link.

Run it through the harness `bin/ble-run` (bare python is killed by TCC when it
touches Bluetooth). `bin/govee` calls it for a bulb that gives no LAN reply and
has a `ble` field in data/devices.json, so you rarely run it by hand:

    bin/ble-run govee/govee_ble.py GVH6008A1B2 status
    bin/ble-run govee/govee_ble.py GVH6008A1B2,GVH6008C3D4 brightness 25
    bin/ble-run govee/govee_ble.py GVH6008A1B2 color ff0000 | temp 2700 | on | off

These H6008 bulbs advertise as GV<SKU><4 hex> and set bit 0x40 in the flags
byte of their advertisement data (the bulbs seen here read 0x43). The name does
not decide the bit, and a firmware update can set it. A bulb with the bit set
ignores plaintext 0x33 and 0xAA frames. Each connection runs a handshake under a
fixed base seed, and the bulb gives a session seed. Every later frame is encoded
under that seed: AES-128-ECB over the first 16 bytes, an RC4-style stream over
the last 4. The protocol, the codec and the frame layouts come from
damient/govee-toolkit (MIT): docs/protocol/ble.md, packages/rust/src/ble/encode.rs
and devices/H6008.yaml. The test vectors in tests/test_govee_ble.py come from
that project's H6008 captures and codec tests.

INVARIANTS:
- A bulb takes one BLE link. While a link is up it does not advertise, so a scan
  that does not find a bulb that has power most often means that a different
  controller holds it.
- A write gets no GATT acknowledgement. The bulb sends a status frame, but it
  says only that the firmware accepted the frame. Hold the link open after the
  last write (DRAIN), or the frame is lost and nothing reports it.
- The XOR checksum is calculated on the plaintext, before the encoding.
- Nothing here fades: each command is one instant set (Alex's no-fade rule).
  The firmware itself fades between colours, and no known frame stops that.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import math
import os
import sys

from bleak import BleakClient, BleakScanner
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SERVICE = "00010203-0405-0607-0809-0a0b0c0d1910"
WRITE = "00010203-0405-0607-0809-0a0b0c0d2b11"
NOTIFY = "00010203-0405-0607-0809-0a0b0c0d2b10"
FRAME = 20
DRAIN = 0.3  # seconds the link stays up after a write. A margin: govee-toolkit measured 25 ms, on the A5 colour channel only
REPLY = 2.0  # seconds to wait for each reply
SCAN = 20.0  # seconds to look for the advertisement

# The base seed every device of this generation takes for the handshake.
# From govee-toolkit encode.rs, kept in the same encoded form.
BASE_SEED = base64.b64decode("TWFraW" + "5nTGlm" + "ZVNtYX" + "J0ZQ==")


def frame(*body: int) -> bytes:
    """A 20-byte plaintext frame: body, zero padding, XOR of the first 19 bytes."""
    p = bytearray(body) + bytes(19 - len(body))
    x = 0
    for b in p:
        x ^= b
    return bytes(p) + bytes([x])


class Codec:
    """Encode and decode 20-byte frames under one 16-byte seed."""

    def __init__(self, seed: bytes) -> None:
        if len(seed) != 16:
            raise ValueError("a seed is 16 bytes")
        self._aes = Cipher(algorithms.AES(seed), modes.ECB())
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + seed[i % 16]) & 0xFF
            s[i], s[j] = s[j], s[i]
        self._schedule = s

    def _stream(self, data: bytes) -> bytes:
        s = self._schedule.copy()
        i = j = 0
        out = bytearray()
        for byte in data:
            i = (i + 1) & 0xFF
            j = (j + s[i]) & 0xFF
            s[i], s[j] = s[j], s[i]
            out.append(byte ^ s[(s[i] + s[j]) & 0xFF])
        return bytes(out)

    def _apply(self, data: bytes, encode: bool) -> bytes:
        n = len(data) // 16 * 16
        op = self._aes.encryptor() if encode else self._aes.decryptor()
        head = op.update(data[:n]) + op.finalize() if n else b""
        return head + self._stream(data[n:])

    def encode(self, plain: bytes) -> bytes:
        return self._apply(plain, True)

    def decode(self, coded: bytes) -> bytes:
        return self._apply(coded, False)


def handshake_frame(kind: int) -> bytes:
    """E7 <kind> with random padding. The padding carries nothing."""
    return frame(0xE7, kind, *os.urandom(17))


def kelvin_rgb(kelvin: int) -> tuple[int, int, int]:
    """The RGB rendering of a white temperature (Tanner Helland's fit, 1000-40000 K).

    The bulb needs this triplet with the kelvin value: it does not calculate it.
    """
    t = kelvin / 100
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        r = 329.698727446 * (t - 60) ** -0.1332047592
        g = 288.1221695283 * (t - 60) ** -0.0755148492
    if t >= 66:
        b = 255.0
    elif t <= 19:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10) - 305.0447927307

    def clamp(v: float) -> int:
        return max(0, min(255, round(v)))

    return clamp(r), clamp(g), clamp(b)


def parse_rgb(text: str) -> tuple[int, int, int]:
    named = {"red": "ff0000", "green": "00ff00", "blue": "0000ff", "white": "ffffff", "orange": "ff7f00"}
    t = named.get(text.lower(), text).lstrip("#")
    if len(t) != 6:
        raise SystemExit(f"govee_ble: colour must be RRGGBB or a name, not {text!r}")
    return int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16)


class Link:
    """One encoded session with one bulb."""

    def __init__(self, client: BleakClient) -> None:
        self.client = client
        self.replies: asyncio.Queue[bytes] = asyncio.Queue()
        self.codec = Codec(BASE_SEED)

    async def _await(self, codec: Codec, head: bytes) -> bytes:
        loop = asyncio.get_running_loop()
        end = loop.time() + REPLY
        while (left := end - loop.time()) > 0:
            try:
                plain = codec.decode(await asyncio.wait_for(self.replies.get(), left))
            except TimeoutError:
                break
            if plain.startswith(head):
                return plain
        raise TimeoutError(f"no reply to {head.hex(' ')}")

    async def open(self) -> None:
        await self.client.start_notify(NOTIFY, lambda _c, d: self.replies.put_nowait(bytes(d)))
        base = self.codec
        await self.client.write_gatt_char(WRITE, base.encode(handshake_frame(0x01)), response=False)
        seed = (await self._await(base, b"\xe7\x01"))[2:18]
        await self.client.write_gatt_char(WRITE, base.encode(handshake_frame(0x02)), response=False)
        await self._await(base, b"\xe7\x02")
        self.codec = Codec(seed)

    async def send(self, *body: int) -> bytes:
        """Write one frame under the session seed and return the decoded answer."""
        await self.client.write_gatt_char(WRITE, self.codec.encode(frame(*body)), response=False)
        return await self._await(self.codec, bytes(body[:2]))

    async def state(self) -> dict:
        power = (await self.send(0xAA, 0x01))[2]
        level = (await self.send(0xAA, 0x04))[2]
        mode = await self.send(0xAA, 0x05)
        st = {"on": bool(power), "brightness": level, "submode": mode[2]}
        if mode[2] == 0x0D:
            r, g, b, khi, klo = mode[3:8]
            kelvin = khi << 8 | klo
            st["shade"] = f"{kelvin}K" if kelvin and not (r or g or b) else f"#{r:02x}{g:02x}{b:02x}"
        return st


async def run_one(name: str, cmd: str, args: list[str]) -> int:
    dev = await BleakScanner.find_device_by_name(name, timeout=SCAN)
    if dev is None:
        print(f"govee_ble: {name} is not advertising. Another controller (a phone, the remote) holds its"
              " one BLE link, or it has no power.", file=sys.stderr)
        return 3
    async with BleakClient(dev, timeout=20, services=[SERVICE]) as client:
        link = Link(client)
        await link.open()
        ack = b""
        if cmd in {"on", "off"}:
            ack = await link.send(0x33, 0x01, int(cmd == "on"))
        elif cmd == "brightness":
            ack = await link.send(0x33, 0x04, max(1, min(100, int(args[0]))))
        elif cmd == "color":
            r, g, b = parse_rgb(args[0])
            ack = await link.send(0x33, 0x05, 0x0D, r, g, b, 0, 0, 0, 0, 0)
        elif cmd == "temp":
            k = max(2700, min(6500, int(args[0])))
            wr, wg, wb = kelvin_rgb(k)
            ack = await link.send(0x33, 0x05, 0x0D, 0, 0, 0, k >> 8, k & 0xFF, wr, wg, wb)
        if ack and ack[2] != 0:
            print(f"govee_ble: {name} refused {cmd}: status {ack[2]:#04x}", file=sys.stderr)
        await asyncio.sleep(DRAIN)
        st = await link.state()
        power = "on " if st["on"] else "off"
        shade = st.get("shade") or f"mode {st['submode']:#04x}"
        print(f"{name:<12} {'ble':<15} {power} {st['brightness']:>3}%  {shade}")
        await asyncio.sleep(DRAIN)
    return 0 if not ack or ack[2] == 0 else 1


async def main() -> int:
    ap = argparse.ArgumentParser(description="Bluetooth LE control for Govee H6008 bulbs (encoded link).")
    ap.add_argument("names", help="advertised names, comma-separated (GVH6008A1B2)")
    ap.add_argument("cmd", choices=["status", "on", "off", "brightness", "color", "temp"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    if a.cmd in {"brightness", "color", "temp"} and not a.args:
        ap.error(f"{a.cmd} needs a value")
    rc = 0
    for name in a.names.split(","):
        try:
            rc = max(rc, await run_one(name, a.cmd, a.args))
        except Exception as exc:  # noqa: BLE001 - one bulb's failure must not stop the next
            print(f"govee_ble: {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            rc = max(rc, 2)
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
