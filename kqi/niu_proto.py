#!/usr/bin/env python3
"""
niu_proto.py -- the NIU Bluetooth LE protocol, reimplemented from the NIU app.

NIU vehicles (KQi kick scooters, N/M/U mopeds) expose one GATT service with a
notify characteristic and a write characteristic.  Which service is present
tells you the "BLE version", which in turn picks the frame family:

  service ...daea50  bleVer 10  frame family 1  (20-byte AES frames)
  service ...daea51  bleVer 20  frame family 1  (20-byte AES frames, v2 handshake)
  service ...daea52  bleVer 21  frame family 10 (variable-length "5aa5" frames)

Family 1 frames are exactly 20 bytes: 2-byte header, 1-byte index (number of
frames still to come), 16 bytes of AES-128-ECB ciphertext, 1-byte checksum
(sum of the preceding bytes mod 256).  Family 10 frames are
5aa5 + len(2) + cmd(1) + payload(each byte +51) + checksum + 96.

The vehicle holds named fields, each addressed by a 3-byte code with a fixed
type and length (see data/fields.json, extracted from the app).  Reads send a
list of codes; writes send code+value pairs.

Before any field traffic the app authenticates with the scooter's per-vehicle
"blePassword" (16 chars, handed out by NIU's cloud for a vehicle bound to your
account):

  v1 (bleVer 10):  012301 + AES_pwd(random16) ; then 010300 + AES_pwd(md5(random ‖ reply ‖ pwd))
  v2 (bleVer>=20): 013401 + firstKey          ; then 011400 + AES_reply(reply[4:8] ‖ rand4 ‖ 0 ‖ crc16)
                   where firstKey = AES_pwd(rand4 ‖ now+604800 ‖ 0*6 ‖ crc16) and the decrypted
                   first reply becomes the session key for every later family-1 frame.

Family-1 data frames are encrypted with the "bleAes" secret (bleVer 10) or the
session key (bleVer 20).  Family-10 frames are not encrypted at all.

Nothing here does I/O; see kqi_ble.py for the bleak side and niu_cloud.py for
the credential fetch.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import struct
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "data", "fields.json"), encoding="utf-8") as _f:
    _TABLES = json.load(_f)
KCONFIG: dict[str, dict] = _TABLES["kconfig"]   # kick-scooter fields (foc_k_*, db_k_*)
GENERIC: dict[str, dict] = _TABLES["generic"]   # shared NIU fields (bms_*, ecu_*, db_*, foc_*)
FIELDS: dict[str, dict] = {**GENERIC, **KCONFIG}
BY_CODE: dict[str, tuple[str, dict]] = {}
for _n, _s in GENERIC.items():
    BY_CODE[_s["code"].upper()] = (_n, _s)
for _n, _s in KCONFIG.items():          # KConfig wins on collisions
    BY_CODE[_s["code"].upper()] = (_n, _s)

SERVICE_BASE = "8ec94e3{n}-f315-4f60-9fb8-838830daea5{v}"
SERVICES = {SERVICE_BASE.format(n=0, v=v): ver for v, ver in ((0, 10), (1, 20), (2, 21))}
FRAME_TAIL = "96"
OBF = 51  # byte offset applied to 5aa5 payloads


class NiuError(Exception):
    def __init__(self, msg: str, code: str = ""):
        super().__init__(msg)
        self.code = code


# ----------------------------------------------------------------------------- basics

def field(name: str) -> dict:
    try:
        return FIELDS[name]
    except KeyError:
        raise NiuError(f"unknown field {name!r}; see `kqi fields`") from None


def chars_for(service_uuid: str) -> tuple[str, str]:
    """(notify characteristic, write characteristic) for a NIU service UUID."""
    v = service_uuid[-1]
    return (SERVICE_BASE.format(n=1, v=v), SERVICE_BASE.format(n=2, v=v))


def checksum(hexstr: str) -> str:
    return "%02x" % (sum(bytes.fromhex(hexstr)) % 256)


def cs_ok(frame: str) -> bool:
    return len(frame) >= 4 and frame[-2:].lower() == checksum(frame[:-2])


def crc16_niu(data: bytes, poly: int = 0xA1E8, init: int = 0xFFFF) -> int:
    """The app's k0.a.f(): reflected table CRC-16, poly 0xA1E8, init 0xFFFF, no final xor."""
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ poly if c & 1 else c >> 1
        table.append(c & 0xFFFF)
    crc = init
    for b in data:
        crc = (crc >> 8) ^ table[(b ^ crc) & 0xFF]
    return crc & 0xFFFF


def aes_key(key: str) -> bytes:
    if len(key) == 16:
        return key.encode("utf-8")
    if len(key) == 32:
        return bytes.fromhex(key)
    raise NiuError("AES key must be 16 chars or 32 hex")


def aes_enc(hex32: str, key: str) -> str:
    if not key:
        return hex32
    if len(hex32) != 32:
        raise NiuError("AES block must be 16 bytes")
    enc = Cipher(algorithms.AES(aes_key(key)), modes.ECB()).encryptor()
    return (enc.update(bytes.fromhex(hex32)) + enc.finalize()).hex()


def aes_dec(hex32: str, key: str) -> str:
    if not key:
        return hex32
    if len(hex32) != 32:
        raise NiuError("AES block must be 16 bytes")
    dec = Cipher(algorithms.AES(aes_key(key)), modes.ECB()).decryptor()
    return (dec.update(bytes.fromhex(hex32)) + dec.finalize()).hex()


def _pad_right(hexstr: str, n: int) -> str:
    return hexstr + "0" * max(0, n - len(hexstr))


# ----------------------------------------------------------------------------- values

def encode_value(spec: dict, value) -> str:
    """Field value -> hex, mirroring n0.s()."""
    typ, ln = spec["type"], spec["len"]
    s = "" if value is None else str(value)
    if typ == "HEX":
        s = s.lower()
        if len(s) > ln * 2:
            raise NiuError(f"value too long, max {ln} bytes")
        return _pad_right(s, ln * 2)
    if typ in ("UTF-8", "US-ASCII"):
        h = s.encode("utf-8").hex()
        if len(h) > ln * 2:
            raise NiuError(f"value too long, max {ln} bytes")
        return _pad_right(h, ln * 2)
    if typ in ("U8", "U16", "U32", "S8", "S16", "S32"):
        n = int(s or "0", 0)
        bits = ln * 8
        return "%0*x" % (ln * 2, n & ((1 << bits) - 1))
    if typ == "F32":
        return struct.pack(">f", float(s or 0)).hex()
    if typ == "F64":
        return struct.pack(">d", float(s or 0)).hex()
    raise NiuError(f"unsupported field type {typ}")


def decode_value(spec: dict, hexval: str):
    """Hex -> Python value, mirroring n0.g()."""
    typ = spec["type"]
    if typ == "HEX":
        return hexval
    if typ in ("UTF-8", "US-ASCII"):
        raw = bytes.fromhex(hexval).rstrip(b"\x00")
        return raw.decode("utf-8", errors="replace")
    if typ in ("U8", "U16", "U32"):
        return int(hexval, 16)
    if typ in ("S8", "S16", "S32"):
        bits = len(hexval) * 4
        n = int(hexval, 16)
        return n - (1 << bits) if n & (1 << (bits - 1)) else n
    if typ == "F32":
        return struct.unpack(">f", bytes.fromhex(hexval))[0]
    if typ == "F64":
        return struct.unpack(">d", bytes.fromhex(hexval))[0]
    return hexval


def parse_fields_sequential(data_hex: str, names: list[str]) -> dict:
    """Values laid out in request order (read replies)."""
    out, pos = {}, 0
    for name in names:
        spec = field(name)
        end = pos + spec["len"] * 2
        if end > len(data_hex):
            raise NiuError(f"reply too short for {name} (got {len(data_hex) // 2} bytes)")
        out[name] = decode_value(spec, data_hex[pos:end])
        pos = end
    return out


def parse_fields_coded(data_hex: str) -> dict:
    """code(3 bytes)+value pairs (unsolicited pushes)."""
    out, pos = {}, 0
    while pos + 6 <= len(data_hex):
        code = data_hex[pos:pos + 6].upper()
        hit = BY_CODE.get(code)
        if not hit:
            out[f"code_{code}"] = data_hex[pos + 6:]
            break
        name, spec = hit
        end = pos + 6 + spec["len"] * 2
        if end > len(data_hex):
            break
        out[name] = decode_value(spec, data_hex[pos + 6:end])
        pos = end
    return out


# ----------------------------------------------------------------------------- family 1 / 2 (20-byte frames)

HEADERS = {
    1: {"read": ("0121", "0101"), "read_ack": ("01a1", "0181"), "read_err": ("01e1", "01c1"),
        "write": ("0122", "0102"), "write_ack": ("01a2", "0182"), "write_err": ("01e2", "01c2")},
    2: {"read": ("012f", "010f"), "read_ack": ("01af", "018f"), "read_err": ("01ef", "01cf"),
        "write": ("0130", "0110"), "write_ack": ("01b0", "0190"), "write_err": ("01f0", "01d0")},
}
PUSH_HEADERS = {"0127", "0107", "0125", "0122", "0102", "0130", "0110"}


def build_chunked(first_hdr: str, next_hdr: str, data_hex: str, key: str) -> list[str]:
    """n0.O(): split data into 16-byte AES blocks, one 20-byte frame each."""
    n = max(1, (len(data_hex) + 31) // 32)
    frames = []
    for i in range(n):
        chunk = _pad_right(data_hex[i * 32:(i + 1) * 32], 32)
        body = (first_hdr if i == 0 else next_hdr) + "%02x" % (n - i - 1) + aes_enc(chunk, key)
        frames.append(body + checksum(body))
    return frames


def build_read(names: list[str], key: str, family: int = 1) -> list[str]:
    h = HEADERS[family]
    return build_chunked(h["read"][0], h["read"][1], "".join(field(n)["code"].lower() for n in names), key)


def build_write(values: dict, key: str, family: int = 1) -> list[str]:
    h = HEADERS[family]
    data = "".join(field(n)["code"].lower() + encode_value(field(n), v) for n, v in values.items())
    return build_chunked(h["write"][0], h["write"][1], data, key)


def is_last_frame(frame: str) -> bool:
    """n0.J(): a 5aa5 frame stands alone; otherwise index byte 00 closes the reply."""
    return frame[:4].lower() == "5aa5" or frame[4:6] == "00"


def _error_code(frame: str, key: str) -> str:
    if not key:
        return frame[6:8].upper()
    return aes_dec(frame[6:-2], key)[:2].upper()


def parse_read_frames(frames: list[str], names: list[str], key: str, family: int = 1) -> dict:
    """n0.W(): reassemble a family-1 read reply and split it into fields."""
    h = HEADERS[family]
    receivable = actual = 0
    data = ""
    for f in frames:
        if not cs_ok(f):
            raise NiuError(f"bad checksum in reply frame {f}")
        hdr, idx = f[:4].lower(), f[4:6].lower()
        if idx == "ff":
            continue
        if hdr == h["read_ack"][0]:
            receivable = int(idx, 16) + 1
            data += aes_dec(f[6:-2], key)
            actual += 1
        elif hdr == h["read_ack"][1]:
            data += aes_dec(f[6:-2], key)
            actual += 1
        elif hdr in h["read_err"]:
            code = _error_code(f, key)
            raise NiuError(f"scooter refused the read (error {code})", code)
        else:
            raise NiuError(f"unexpected reply header {hdr}")
    if receivable != actual:
        raise NiuError(f"frame loss: expected {receivable} data frames, got {actual}")
    return parse_fields_sequential(data, names)


def parse_write_frames(frames: list[str], key: str, family: int = 1) -> str:
    """n0.o(): validate a family-1 write reply; returns the result byte ("00" = ok)."""
    h = HEADERS[family]
    if not frames:
        raise NiuError("empty write reply")
    last = frames[-1]
    if not cs_ok(last):
        raise NiuError("bad checksum in write reply")
    hdr = last[:4].lower()
    if hdr in h["write_err"]:
        code = _error_code(last, key)
        raise NiuError(f"scooter refused the write (error {code})", code)
    if hdr not in h["write_ack"]:
        raise NiuError(f"unexpected write reply header {hdr}")
    if last[4:6] != "00":
        raise NiuError("write reply did not finish (index != 00)")
    return _error_code(last, key)


def parse_push(frame: str, key: str) -> dict:
    """Decrypt an unsolicited family-1 frame and split it into coded fields."""
    if not cs_ok(frame):
        raise NiuError("bad checksum in push frame")
    return parse_fields_coded(aes_dec(frame[6:-2], key))


# ----------------------------------------------------------------------------- family 10 (5aa5 frames)

CMD_READ, CMD_WRITE = "01", "02"


def build_5aa5(payload_hex: str, cmd: str) -> str:
    obf = bytes((b + OBF) & 0xFF for b in bytes.fromhex(payload_hex)).hex()
    frame = "5aa5" + "%04x" % (len(obf) // 2 + 3) + cmd + obf
    return frame + checksum(frame) + FRAME_TAIL


def frame_5aa5_complete(buf: str) -> bool:
    if len(buf) < 8 or buf[:4].lower() != "5aa5":
        return False
    return len(buf) >= (int(buf[4:8], 16) + 4) * 2


def parse_5aa5(frame: str, expect_cmd: str | None = None) -> tuple[str, str]:
    """n0.n()/n0.E(): returns (cmd, deobfuscated payload hex); raises on error replies."""
    frame = frame.lower()
    if frame[:4] != "5aa5":
        raise NiuError(f"bad 5aa5 header {frame[:4]}")
    if not frame.endswith(FRAME_TAIL):
        raise NiuError("bad 5aa5 tail")
    if not cs_ok(frame[:-2]):
        raise NiuError("bad 5aa5 checksum")
    ln = int(frame[4:8], 16)
    if len(frame) != (ln + 4) * 2:
        raise NiuError(f"bad 5aa5 length (field {ln}, got {len(frame) // 2 - 4})")
    cmd = frame[8:10]
    data = bytes((b - OBF) & 0xFF for b in bytes.fromhex(frame[10:10 + (ln - 3) * 2])).hex()
    if expect_cmd is not None:
        want = int(expect_cmd, 16)
        got = int(cmd, 16)
        if got == want | 0xC0:
            raise NiuError(f"scooter refused command {expect_cmd} (error {data[:2].upper()})", data[:2].upper())
        if got != want | 0x80:
            raise NiuError(f"unexpected 5aa5 reply command {cmd} for {expect_cmd}")
    return cmd, data


def build_read_5aa5(names: list[str]) -> str:
    return build_5aa5("".join(field(n)["code"].lower() for n in names), CMD_READ)


def build_write_5aa5(values: dict) -> str:
    return build_5aa5("".join(field(n)["code"].lower() + encode_value(field(n), v) for n, v in values.items()), CMD_WRITE)


# ----------------------------------------------------------------------------- handshake

def hs1_v1(pwd: str) -> tuple[str, str]:
    """First verify frame for bleVer 10. Returns (frame, random32)."""
    rnd = secrets.token_hex(16)
    body = "012301" + aes_enc(rnd, pwd)
    return body + checksum(body), rnd


def hs1_v1_parse(frame: str, pwd: str) -> str:
    hdr = frame[:4].lower()
    if hdr == "01a3":
        if not cs_ok(frame):
            raise NiuError("bad checksum in verify reply 1")
        return aes_dec(frame[6:-2], pwd)
    if hdr == "01c3":
        raise NiuError(f"password rejected at step 1 (error {_error_code(frame, pwd)})")
    raise NiuError(f"unexpected verify reply header {hdr}")


def hs2_v1(random32: str, reply32: str, pwd: str) -> str:
    digest = hashlib.md5(bytes.fromhex(random32 + reply32 + pwd.encode("utf-8").hex())).hexdigest()
    body = "010300" + aes_enc(digest, pwd)
    return body + checksum(body)


def hs2_v1_parse(frame: str, pwd: str) -> str:
    hdr = frame[:4].lower()
    if hdr == "0183":
        if not cs_ok(frame):
            raise NiuError("bad checksum in verify reply 2")
        plain = aes_dec(frame[6:-2], pwd)
        if not plain.startswith("00"):
            raise NiuError(f"password verify failed (flag {plain[:2]})")
        return plain
    if hdr == "01c3":
        raise NiuError(f"password rejected at step 2 (error {_error_code(frame, pwd)})")
    raise NiuError(f"unexpected verify reply header {hdr}")


def first_key(pwd: str, mac: str | None = None, now: int | None = None) -> tuple[str, str]:
    """n0.j(): (firstKey32, random1_8) for the v2 handshake."""
    rnd = secrets.token_hex(4)
    ts = (now if now is not None else int(time.time())) + 604800
    body = rnd + "%08x" % (ts & 0xFFFFFFFF)
    body += mac.replace(":", "").lower() if mac and len(mac.replace(":", "")) == 12 else "000000000000"
    body += "%04x" % crc16_niu(bytes.fromhex(body))
    return aes_enc(body, pwd), rnd


def hs1_v2(first_key32: str) -> str:
    body = "013401" + first_key32
    return body + checksum(body)


def hs1_v2_parse(frame: str, first_key32: str) -> str:
    hdr = frame[:4].lower()
    if hdr == "01b4":
        if not cs_ok(frame):
            raise NiuError("bad checksum in verify reply 1")
        return aes_dec(frame[6:-2], first_key32)
    if hdr in ("01d4", "01f4"):
        raise NiuError(f"first key rejected (error {_error_code(frame, first_key32)})")
    raise NiuError(f"unexpected verify reply header {hdr}")


def hs2_v2(reply32: str, random1: str) -> str:
    body = reply32[8:16] + random1 + "000000000000"
    body += "%04x" % crc16_niu(bytes.fromhex(body))
    frame = "011400" + aes_enc(body, reply32)
    return frame + checksum(frame)


def hs2_v2_parse(frame: str, session_key32: str) -> str:
    hdr = frame[:4].lower()
    if hdr == "0194":
        if not cs_ok(frame):
            raise NiuError("bad checksum in verify reply 2")
        return aes_dec(frame[6:-2], session_key32)
    if hdr == "01d4":
        raise NiuError(f"session key rejected (error {_error_code(frame, session_key32)})")
    raise NiuError(f"unexpected verify reply header {hdr}")


# ----------------------------------------------------------------------------- self test

def _selftest() -> None:
    assert checksum("5aa5") == "%02x" % ((0x5A + 0xA5) % 256)
    assert cs_ok("5aa5" + checksum("5aa5"))
    k = "0123456789abcdef"
    blk = "00" * 16
    assert aes_dec(aes_enc(blk, k), k) == blk
    fk, r1 = first_key(k, now=1700000000)
    assert len(fk) == 32 and len(r1) == 8
    fr = hs1_v2(fk)
    assert len(fr) == 40 and cs_ok(fr)
    frames = build_read(["foc_k_gears", "foc_k_rt_speed"], k)
    assert len(frames) == 1 and len(frames[0]) == 40 and frames[0][:4] == "0121"
    f5 = build_read_5aa5(["foc_k_gears"])
    cmd, data = parse_5aa5(f5)
    assert cmd == "01" and data == "210009"
    assert frame_5aa5_complete(f5)
    # a fake read reply for the 5aa5 family
    reply = build_5aa5("03" + "00c8", "81")
    assert parse_fields_sequential(parse_5aa5(reply, "01")[1], ["foc_k_gears", "foc_k_rt_speed"]) == {"foc_k_gears": 3, "foc_k_rt_speed": 200}
    assert encode_value(field("db_k_timestamp"), 1700000000) == "6553f100"
    assert decode_value({"type": "S16", "len": 2}, "fffe") == -2
    assert parse_fields_coded("21000903" + "21000b00c8") == {"foc_k_gears": 3, "foc_k_rt_speed": 200}
    print("niu_proto selftest ok")


if __name__ == "__main__":
    _selftest()
