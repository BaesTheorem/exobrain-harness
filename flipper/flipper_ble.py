#!/usr/bin/env python3
"""
flipper_ble.py — drive a Flipper Zero WIRELESSLY over Bluetooth LE.

The Flipper's BLE serial channel does NOT expose the text CLI (unlike USB);
it speaks the protobuf RPC only. So this is a from-scratch, dependency-free
implementation of the Flipper RPC: hand-rolled protobuf wire encoding/decoding
(no protoc, no protobuf runtime) over the BLE serial GATT service via bleak.

Supports: ping, info (device_info), battery, list, read, write, delete.

Usage:
    flipper_ble.py info
    flipper_ble.py battery
    flipper_ble.py list /ext
    flipper_ble.py read /ext/subghz/foo.sub
    flipper_ble.py write ./local.sub /ext/subghz/foo.sub
    flipper_ble.py delete /ext/subghz/foo.sub

Requires the Flipper's Bluetooth ON. First connect may prompt a pairing PIN
on the Flipper screen — confirm it there.

Caveat: large file reads over BLE can be flaky (known firmware transfer bug).
Small files, listings, and info are solid.
"""
import argparse
import asyncio
import os
import sys

from bleak import BleakScanner, BleakClient

ADDR_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ble_addr")

SVC = "8fe5b3d5-2e7f-4a98-2a48-7acc60fe0000"
RX = "19ed82ae-ed21-4c9d-4145-228e62fe0000"  # host -> Flipper (write)
TX = "19ed82ae-ed21-4c9d-4145-228e61fe0000"  # Flipper -> host (indicate)
BATT = "00002a19-0000-1000-8000-00805f9b34fb"

# --- PB_Main content field numbers (from flipper.proto) ---
PING_REQ, PING_RESP = 5, 6
DEVINFO_REQ, DEVINFO_RESP = 32, 33
POWERINFO_REQ, POWERINFO_RESP = 44, 45
LIST_REQ, LIST_RESP = 7, 8
READ_REQ, READ_RESP = 9, 10
WRITE_REQ = 11
DELETE_REQ = 12


# ---------- protobuf wire format (hand-rolled) ----------
def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _read_varint(buf, i):
    shift = result = 0
    while True:
        b = buf[i]; i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def _tag(field, wt):
    return _varint((field << 3) | wt)


def _fv(field, value):                       # varint field
    return _tag(field, 0) + _varint(value)


def _fl(field, data):                        # length-delimited field
    return _tag(field, 2) + _varint(len(data)) + bytes(data)


def _fs(field, s):                           # string field
    return _fl(field, s.encode())


def parse(buf):
    """Generic protobuf decode -> {field_num: [values]}."""
    i, fields = 0, {}
    while i < len(buf):
        key, i = _read_varint(buf, i)
        field, wt = key >> 3, key & 7
        if wt == 0:
            val, i = _read_varint(buf, i)
        elif wt == 2:
            ln, i = _read_varint(buf, i)
            val, i = buf[i:i + ln], i + ln
        elif wt == 5:
            val, i = buf[i:i + 4], i + 4
        elif wt == 1:
            val, i = buf[i:i + 8], i + 8
        else:
            raise ValueError(f"bad wire type {wt}")
        fields.setdefault(field, []).append(val)
    return fields


class Main:
    def __init__(self, raw):
        f = parse(raw)
        self.command_id = f.get(1, [0])[0]
        self.status = f.get(2, [0])[0]
        self.has_next = bool(f.get(3, [0])[0])
        self.fields = f


def build_main(cid, content_field, content_bytes):
    body = _fv(1, cid) + _fl(content_field, content_bytes)
    return _varint(len(body)) + body          # length-delimited frame


# ---------- BLE RPC client ----------
class FlipperBLE:
    def __init__(self):
        self.client = None
        self._buf = bytearray()
        self._off = 0
        self._evt = asyncio.Event()
        self._cid = 0

    async def __aenter__(self):
        # Prefer connecting straight to the cached address (no scan = fast +
        # reliable on macOS). Fall back to a (retried) scan, then cache the hit.
        addr = None
        if os.path.exists(ADDR_CACHE):
            addr = open(ADDR_CACHE).read().strip() or None
        if addr:
            try:
                self.client = BleakClient(addr, timeout=20.0)
                await self.client.connect()
            except Exception:
                self.client = None
        if not (self.client and self.client.is_connected):
            dev = None
            for _ in range(4):
                dev = await BleakScanner.find_device_by_filter(
                    lambda d, a: bool(d.name and "flipper" in d.name.lower()), timeout=8.0)
                if dev:
                    break
            if not dev:
                sys.exit("Flipper not found over BLE after retries. Is its Bluetooth ON and in range?")
            self.client = BleakClient(dev, timeout=20.0)
            await self.client.connect()
            try:
                with open(ADDR_CACHE, "w") as f:
                    f.write(str(dev.address))
            except Exception:
                pass
        await self.client.start_notify(TX, self._on_tx)
        await asyncio.sleep(0.3)
        return self

    async def __aexit__(self, *a):
        try:
            await self.client.stop_notify(TX)
        except Exception:
            pass
        await self.client.disconnect()

    def _on_tx(self, _h, data):
        self._buf.extend(data)
        self._evt.set()

    async def battery(self):
        return int((await self.client.read_gatt_char(BATT))[0])

    async def _write(self, framed):
        # Chunk to the negotiated MTU to be safe on write-without-response.
        try:
            chunk = max(20, (self.client.mtu_size or 23) - 3)
        except Exception:
            chunk = 20
        for i in range(0, len(framed), chunk):
            await self.client.write_gatt_char(RX, framed[i:i + chunk], response=False)
            await asyncio.sleep(0.01)

    async def _next_frame(self, timeout):
        """Pull one complete length-delimited Main from the rx buffer."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            if self._off < len(self._buf):
                try:
                    ln, j = _read_varint(self._buf, self._off)
                except IndexError:
                    ln = None
                if ln is not None and j + ln <= len(self._buf):
                    msg = bytes(self._buf[j:j + ln])
                    self._off = j + ln
                    if self._off > 4096:        # compact periodically
                        del self._buf[:self._off]
                        self._off = 0
                    return Main(msg)
            self._evt.clear()
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                await asyncio.wait_for(self._evt.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return None

    async def rpc(self, content_field, content_bytes=b"", timeout=8.0):
        """Send one request; collect streamed responses until has_next is false."""
        self._cid += 1
        cid = self._cid
        await self._write(build_main(cid, content_field, content_bytes))
        out = []
        while True:
            m = await self._next_frame(timeout)
            if m is None:
                raise TimeoutError("no/incomplete RPC response (BLE)")
            if m.command_id != cid:
                continue
            if m.status != 0:
                raise RuntimeError(f"Flipper RPC error status={m.status}")
            out.append(m)
            if not m.has_next:
                return out

    # --- high-level ops ---
    async def device_info(self):
        pairs = []
        for m in await self.rpc(DEVINFO_REQ):
            d = m.fields.get(DEVINFO_RESP)
            if d:
                kv = parse(d[0])
                k = kv.get(1, [b""])[0].decode(errors="replace")
                v = kv.get(2, [b""])[0].decode(errors="replace")
                if k:
                    pairs.append((k, v))
        return pairs

    async def power_info(self):
        pairs = []
        for m in await self.rpc(POWERINFO_REQ):
            d = m.fields.get(POWERINFO_RESP)
            if d:
                kv = parse(d[0])
                k = kv.get(1, [b""])[0].decode(errors="replace")
                v = kv.get(2, [b""])[0].decode(errors="replace")
                if k:
                    pairs.append((k, v))
        return pairs

    async def list_dir(self, path):
        files = []
        for m in await self.rpc(LIST_REQ, _fs(1, path)):
            for lr in m.fields.get(LIST_RESP, []):       # each ListResponse
                lrf = parse(lr)
                for fb in lrf.get(1, []):                 # repeated File file = 1
                    ff = parse(fb)
                    name = ff.get(2, [b""])[0].decode(errors="replace")
                    ftype = ff.get(1, [0])[0]
                    size = ff.get(3, [0])[0]
                    if name:
                        files.append((("D" if ftype == 1 else "F"), name, size))
        return files

    async def read_file(self, path):
        data = bytearray()
        for m in await self.rpc(READ_REQ, _fs(1, path), timeout=15.0):
            for rb in m.fields.get(READ_RESP, []):
                rr = parse(rb)
                file_msg = rr.get(1, [b""])[0]       # ReadResponse.file
                if file_msg:
                    ff = parse(file_msg)
                    chunk = ff.get(4, [b""])[0]      # File.data
                    if chunk:
                        data.extend(chunk)
        return bytes(data)

    async def write_file(self, path, data):
        # File.data = field 4; WriteRequest{ path=1, file=2: File }
        file_msg = _fl(4, data)
        req = _fs(1, path) + _fl(2, file_msg)
        await self.rpc(WRITE_REQ, req, timeout=15.0)

    async def delete(self, path, recursive=False):
        req = _fs(1, path) + (_fv(2, 1) if recursive else b"")
        await self.rpc(DELETE_REQ, req)


async def run(args):
    async with FlipperBLE() as fz:
        if args.cmd == "ping":
            await fz.rpc(PING_REQ)
            print("pong (RPC alive over BLE)")
        elif args.cmd == "battery":
            print(f"{await fz.battery()}%")
        elif args.cmd == "info":
            for k, v in await fz.device_info():
                print(f"{k:<28}: {v}")
        elif args.cmd == "power":
            for k, v in await fz.power_info():
                print(f"{k:<28}: {v}")
        elif args.cmd == "list":
            for t, name, size in await fz.list_dir(args.path):
                print(f"  [{t}] {name}" + (f"  {size}b" if t == "F" else ""))
        elif args.cmd == "read":
            data = await fz.read_file(args.path)
            sys.stdout.buffer.write(data)
        elif args.cmd == "write":
            with open(args.local, "rb") as f:
                data = f.read()
            await fz.write_file(args.flipper_path, data)
            print(f"wrote {len(data)} bytes -> {args.flipper_path}")
        elif args.cmd == "delete":
            await fz.delete(args.path, args.recursive)
            print(f"deleted {args.path}")


def main():
    ap = argparse.ArgumentParser(description="Drive a Flipper Zero wirelessly over BLE (protobuf RPC).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping")
    sub.add_parser("battery")
    sub.add_parser("info")
    sub.add_parser("power")
    pl = sub.add_parser("list"); pl.add_argument("path", nargs="?", default="/ext")
    pr = sub.add_parser("read"); pr.add_argument("path")
    pw = sub.add_parser("write"); pw.add_argument("local"); pw.add_argument("flipper_path")
    pd = sub.add_parser("delete"); pd.add_argument("path"); pd.add_argument("--recursive", action="store_true")
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
