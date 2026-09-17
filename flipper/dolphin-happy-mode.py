#!/usr/bin/env python3
"""Decode and patch the Flipper Zero dolphin state file (`/int/.dolphin.state`).

Unleashed (and OFW) gate the whole mood system behind a `DolphinFlagHappyMode`
bit in the persisted state. When it is set, every consumer of dolphin stats is
handed `butthurt = 0` no matter what the internal counter says, so the mood can
never decay. The firmware exposes the same bit as Settings -> Desktop ->
Happy Mode; this script sets it without touching the device UI, and also zeroes
the stored counter so the setting is safe to turn back off later.

File format (lib/toolbox/saved_struct.c + services/dolphin/helpers/dolphin_state.h):

    SavedStructHeader (8 bytes)     magic 0xD0 | version 0x01 | checksum | flags | u32 timestamp
    DolphinStoreData  (32 bytes)    u8 icounter_daily_limit[DolphinAppMAX]
                                    u8 butthurt_daily_limit
                                    u32 flags          <- DolphinFlagHappyMode = 1
                                    u32 icounter       (XP)
                                    i32 butthurt       (0 = happiest, 14 = max sulk)
                                    u64 timestamp

`checksum` is the low byte of the sum of the 32 payload bytes. A bad checksum,
or a butthurt outside 0..14, makes the firmware discard the file and reset the
dolphin to zero -- which also wipes the XP, so always rewrite the checksum.

Usage:
    dolphin-happy-mode.py show  state.bin
    dolphin-happy-mode.py patch state.bin -o patched.bin [--off]
"""

import argparse
import struct
import sys

HEADER = 8
PAYLOAD = 32
MAGIC = 0xD0
VERSION = 0x01
HAPPY_MODE = 1
BUTTHURT_MAX = 14

# payload-relative offsets
OFF_FLAGS = 8
OFF_ICOUNTER = 12
OFF_BUTTHURT = 16
OFF_TIMESTAMP = 24

LEVEL2_THRESHOLD = 300
LEVEL3_THRESHOLD = 1800


def load(path):
    with open(path, "rb") as f:
        blob = f.read()
    if len(blob) != HEADER + PAYLOAD:
        sys.exit(f"{path}: expected {HEADER + PAYLOAD} bytes, got {len(blob)}")
    if blob[0] != MAGIC or blob[1] != VERSION:
        sys.exit(f"{path}: not a dolphin state file (magic {blob[0]:#04x} version {blob[1]:#04x})")
    return bytearray(blob)


def checksum(payload):
    return sum(payload) & 0xFF


def decode(blob):
    p = blob[HEADER:]
    return {
        "checksum_stored": blob[2],
        "checksum_actual": checksum(p),
        "flags": struct.unpack_from("<I", p, OFF_FLAGS)[0],
        "icounter": struct.unpack_from("<I", p, OFF_ICOUNTER)[0],
        "butthurt": struct.unpack_from("<i", p, OFF_BUTTHURT)[0],
        "timestamp": struct.unpack_from("<Q", p, OFF_TIMESTAMP)[0],
    }


def level(icounter):
    if icounter <= LEVEL2_THRESHOLD:
        return 1
    return 2 if icounter <= LEVEL3_THRESHOLD else 3


def report(state):
    happy = bool(state["flags"] & HAPPY_MODE)
    ok = state["checksum_stored"] == state["checksum_actual"]
    print(f"  checksum    {state['checksum_stored']:#04x} "
          f"({'valid' if ok else f'INVALID, computed {state['checksum_actual']:#04x}'})")
    print(f"  flags       {state['flags']:#010x}  happy mode {'ON' if happy else 'off'}")
    print(f"  icounter    {state['icounter']} XP (level {level(state['icounter'])})")
    print(f"  butthurt    {state['butthurt']} / {BUTTHURT_MAX}"
          + ("  (overridden to 0 by happy mode)" if happy else ""))
    print(f"  timestamp   {state['timestamp']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show", help="decode a state file")
    s.add_argument("state")
    p = sub.add_parser("patch", help="set happy mode and zero the butthurt counter")
    p.add_argument("state")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--off", action="store_true", help="clear happy mode instead of setting it")
    args = ap.parse_args()

    blob = load(args.state)
    print(f"before ({args.state}):")
    report(decode(blob))

    if args.cmd == "show":
        return

    payload = blob[HEADER:]
    flags = struct.unpack_from("<I", payload, OFF_FLAGS)[0]
    flags = flags & ~HAPPY_MODE if args.off else flags | HAPPY_MODE
    struct.pack_into("<I", payload, OFF_FLAGS, flags)
    struct.pack_into("<i", payload, OFF_BUTTHURT, 0)
    blob[HEADER:] = payload
    blob[2] = checksum(payload)

    with open(args.out, "wb") as f:
        f.write(blob)
    print(f"\nafter ({args.out}):")
    report(decode(blob))


if __name__ == "__main__":
    main()
