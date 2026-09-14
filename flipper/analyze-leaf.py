#!/usr/bin/env python3
"""Analyze a LEAF (WaveLynx) MIFARE DESFire dump and test candidate master keys
OFFLINE against the card's free-read signature -- no card or reader needed.

Why this works without the card: the LEAF EV1-compat app (AID F532F0) exposes a
free-read Card Identifier Object whose last 8 bytes are a CMAC over the object,
keyed by the per-card-diversified OCPSK. The diversification (NXP AN10957 4.5.1,
with LEAF's Appendix-B modified DIV input) is deterministic from the UID, which
is in the dump. So for any *candidate master key* we can recompute the expected
signature and compare. A match proves that keyset personalizes the card; every
diversified per-app key then follows from the UID.

This CANNOT recover an unknown key -- it only confirms or refutes a candidate.
It is the verification instrument for the "obtain the LEAF keyset" challenge:
feed it eval keys (built in), or any keyset later obtained from reader firmware /
SDK / a leak, and it says yes/no offline.

Crypto is validated at import-time --selftest against NXP's own AN10957 test
vectors, so a NO answer means "wrong key", not "our bug".

INVARIANTS
    - --selftest MUST pass (both AN10957 vectors) or the tool refuses to judge.
    - Only PUBLIC key material is embedded (NXP vectors + the spec's Appendix-A
      test keys). Never hardcode a real/production key or any card's data here.
    - Card UID + signature come from the dump passed at runtime, never the source.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

H = bytes.fromhex


def aes_ecb(key: bytes, block: bytes) -> bytes:
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(block) + enc.finalize()


def _dbl(b: bytes) -> bytes:
    """CMAC subkey doubling in GF(2^128)."""
    n = (int.from_bytes(b, "big") << 1) & ((1 << 128) - 1)
    out = n.to_bytes(16, "big")
    if b[0] & 0x80:
        out = bytes(x ^ y for x, y in zip(out, b"\x00" * 15 + b"\x87", strict=True))
    return out


def _subkeys(key: bytes) -> tuple[bytes, bytes]:
    k0 = aes_ecb(key, b"\x00" * 16)
    k1 = _dbl(k0)
    return k1, _dbl(k1)


def cmac(key: bytes, msg: bytes, iv: bytes = b"\x00" * 16) -> bytes:
    """AES-CMAC (NIST SP800-38B) allowing a nonzero starting IV (LEAF sets IV=UID)."""
    k1, k2 = _subkeys(key)
    if msg and len(msg) % 16 == 0:
        blocks = [bytearray(msg[i : i + 16]) for i in range(0, len(msg), 16)]
        tweak = k1
    else:
        padded = msg + b"\x80" + b"\x00" * (15 - (len(msg) % 16))
        blocks = [bytearray(padded[i : i + 16]) for i in range(0, len(padded), 16)]
        tweak = k2
    for i in range(16):
        blocks[-1][i] ^= tweak[i]
    x = iv
    for blk in blocks:
        x = aes_ecb(key, bytes(a ^ b for a, b in zip(x, blk, strict=True)))
    return x


def diversify(master: bytes, div_payload: bytes) -> bytes:
    """AN10957 4.5.1: DIV input = payload||0x80 padded to 32B, XOR K2 into the
    last block, CBC-MAC, take the last block."""
    _, k2 = _subkeys(master)
    di = (div_payload + b"\x80").ljust(32, b"\x00")[:32]
    b0, b1 = bytearray(di[:16]), bytearray(di[16:32])
    for i in range(16):
        b1[i] ^= k2[i]
    c1 = aes_ecb(master, bytes(b0))
    return aes_ecb(master, bytes(a ^ b for a, b in zip(c1, b1, strict=True)))


def leaf_signature(ocpsk_master: bytes, uid: bytes, signed_data: bytes) -> bytes:
    """8-byte LEAF Card-Identifier-Object signature for a candidate OCPSK master."""
    dk = diversify(ocpsk_master, b"\x88" + uid + b"\x88" + uid)  # spec Appendix B
    iv = (uid + b"\x80").ljust(16, b"\x00")[:16]  # "CMAC with IV set to UID"
    return cmac(dk, signed_data, iv)[:8]


def selftest() -> bool:
    """Validate diversification + signature against AN10957's published vectors."""
    master = H("f3f9377698707b688eaf84abe39e3791")
    uid = H("04deadbeeffeed")
    ok_div = diversify(master, b"\x01" + uid) == H("0bb408baff98b6ee9f2e1585777f6a51")
    sig_data = H(
        "0100000000112200000000000655300000000000001122334455667788990011223344"
        "5566778899"
    )
    dk = diversify(master, b"\x01" + uid)
    iv = (uid + b"\x80").ljust(16, b"\x00")[:16]
    ok_sig = cmac(dk, sig_data, iv)[:8] == H("8fb0ef8eb12ac1f3")
    print(f"  AN10957 diversification vector: {'PASS' if ok_div else 'FAIL'}")
    print(f"  AN10957 signature vector:       {'PASS' if ok_sig else 'FAIL'}")
    return ok_div and ok_sig


# LEAF Cc test keys, published in the LEAF Memory Usage Spec Appendix A (public).
# The OCPSK is the one that signs the free-read Card Identifier Object.
TEST_KEYS = {
    "LEAF Cc test OCPSK (E1020101..)": H("E1020101" + "01010101" * 3),
    "all-zero AES (factory default)": b"\x00" * 16,
}


def parse_cio(nfc_text: str) -> tuple[bytes, bytes]:
    """Return (uid, 32-byte Card Identifier Object) from a Flipper .nfc dump."""
    uid_m = re.search(r"^UID:\s*([0-9A-Fa-f ]+)$", nfc_text, re.M)
    if not uid_m:
        raise SystemExit("No UID in dump.")
    uid = H(uid_m.group(1).replace(" ", ""))
    # File 1 of the EV1-compat app (free read); Flipper prints AID byte-reversed.
    cio_m = re.search(r"Application f032f5 File 1:\s*([0-9A-Fa-f ]+)$", nfc_text, re.M)
    if not cio_m:
        raise SystemExit("No free-read Card Identifier Object (f032f5 File 1) in dump.")
    cio = H(cio_m.group(1).replace(" ", ""))
    if len(cio) != 32:
        raise SystemExit(f"Card Identifier Object is {len(cio)}B, expected 32.")
    return uid, cio


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Analyze a LEAF DESFire dump; test candidate keys offline"
    )
    ap.add_argument("dump", nargs="?", help="Flipper .nfc DESFire dump")
    ap.add_argument(
        "--selftest", action="store_true", help="run crypto vectors and exit"
    )
    ap.add_argument(
        "--key",
        action="append",
        default=[],
        metavar="HEX32",
        help="extra candidate OCPSK master key (32 hex chars); repeatable",
    )
    args = ap.parse_args()

    print("Self-test (AN10957 vectors):")
    if not selftest():
        raise SystemExit("Self-test FAILED -- refusing to judge any card.")
    if args.selftest:
        return
    if not args.dump:
        ap.error("give a .nfc dump, or --selftest")

    uid, cio = parse_cio(Path(args.dump).read_text())
    signed, card_sig = cio[:24], cio[24:]
    print(f"\nUID {uid.hex()}  |  card signature {card_sig.hex()}")

    candidates = dict(TEST_KEYS)
    for k in args.key:
        candidates[f"user key {k[:8]}.."] = H(k)

    hit = False
    print("Testing candidate OCPSK master keys against the free-read signature:")
    for name, key in candidates.items():
        got = leaf_signature(key, uid, signed)
        match = got == card_sig
        hit = hit or match
        print(f"  {name:34}: {got.hex()}  {'<<< MATCH' if match else ''}")
    print(
        "\nRESULT:",
        "a candidate keyset PERSONALIZES this card -- derive per-app keys from UID."
        if hit
        else "none of the tested keysets match; the card uses keys not among them.",
    )


if __name__ == "__main__":
    main()
