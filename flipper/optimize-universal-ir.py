#!/usr/bin/env python3
"""optimize-universal-ir.py — make the Flipper's on-board universal remote sweep
(TV-B-Gone and friends) finish faster.

The universal remote sends every signal whose name matches the pressed button
(e.g. all "Power" signals) sequentially, top-to-bottom, and you abort the instant
the device reacts. So the *effective* wait is the position of your device's code
in the list. This tool rewrites an assets/*.ir library to:

  1. DEDUP identical signals (same protocol+address+command, or identical raw data)
  2. REORDER by brand/protocol popularity so mainstream gear powers off first

Coverage is preserved by default (nothing is dropped) — only the order changes,
so even an exotic device still eventually gets hit. `--top N` additionally trims
the prioritised button to the N most-popular codes for maximum speed (drops the
long tail; use when you only target mainstream gear).

Usage:
  optimize-universal-ir.py tv.ir.orig -o tv.ir
  optimize-universal-ir.py tv.ir.orig -o tv.ir --button Power --top 40
"""
import argparse
import re
import sys

# Protocol family -> rank, by global TV-brand market share (lower = sooner).
# Samsung(#1) is a small, pure bucket -> first. NEC/NECext is the big bucket that
# holds LG/TCL/Hisense/Vizio (#2-#4 + long tail). Sony(SIRC) next, then the rest.
FAMILY_RANK = {
    "Samsung32": 0,
    "NEC": 1, "NECext": 1, "NEC42": 1,
    "SIRC": 2, "SIRC15": 2, "SIRC20": 2,
    "Kaseikyo": 3,                       # Panasonic
    "RC6": 4, "RC5": 4, "RC5X": 4,       # Philips et al.
    "RCA": 5, "Pioneer": 5,
}
OTHER_PARSED_RANK = 6
RAW_RANK = 7

# Codes I'm fairly confident map to a top brand — nudged to the front of their
# family. Order-only, so a wrong guess costs at most a few positions, never a miss.
KNOWN_TOP = {
    ("Samsung32", "07 00 00 00"),        # Samsung TVs
    ("SIRC", "01 00 00 00"),             # Sony TVs
    ("NEC", "04 00 00 00"),              # LG TVs
}

# (protocol, address) -> rank, by 2025 global TV units shipped (US-blended).
# Fingerprints verified against the Flipper-IRDB TVs/<brand> power codes; ranks
# from TrendForce/Omdia 2025 share (TCL ~16%, Samsung ~13%, Hisense ~12%, LG ~8%,
# then Vizio/Sony/Insignia/Toshiba/Sharp/Panasonic/Philips). Order-only.
SIGNATURE_RANK = {
    ("NECext", "EA C7 00 00"): 1,        # TCL / Onn (onn. TVs are TCL-built)
    ("Samsung32", "07 00 00 00"): 2,     # Samsung
    ("NECext", "00 BF 00 00"): 3,        # Hisense
    ("NEC", "04 00 00 00"): 4,           # LG / Vizio / Hisense (shared NEC addr, all top-tier)
    ("NECext", "04 F4 00 00"): 4,        # LG
    ("SIRC", "01 00 00 00"): 5,          # Sony
    ("SIRC15", "01 00 00 00"): 5,
    ("SIRC20", "01 00 00 00"): 5,
    ("NECext", "86 05 00 00"): 6,        # Insignia (Best Buy, US-popular)
    ("NECext", "02 7D 00 00"): 6,        # Toshiba / Insignia
    ("NEC", "40 00 00 00"): 7,           # Toshiba
    ("NECext", "00 7F 00 00"): 8,        # Sharp
    ("Kaseikyo", "80 02 20 00"): 9,      # Panasonic
    ("RC5", "00 00 00 00"): 10,          # Philips
    ("RC6", "00 00 00 00"): 10,          # Philips
    ("NECext", "00 BD 00 00"): 10,       # Philips
}
POP_UNMATCHED_BASE = 50                  # known protocol, unknown brand -> after the named brands
POP_RAW_RANK = 60                        # raw timing capture, unattributable -> last

SIGNATURE_BRAND = {
    ("NECext", "EA C7 00 00"): "TCL/Onn", ("Samsung32", "07 00 00 00"): "Samsung",
    ("NECext", "00 BF 00 00"): "Hisense", ("NEC", "04 00 00 00"): "LG/Vizio",
    ("NECext", "04 F4 00 00"): "LG", ("SIRC", "01 00 00 00"): "Sony",
    ("SIRC15", "01 00 00 00"): "Sony", ("SIRC20", "01 00 00 00"): "Sony",
    ("NECext", "86 05 00 00"): "Insignia", ("NECext", "02 7D 00 00"): "Toshiba/Insignia",
    ("NEC", "40 00 00 00"): "Toshiba", ("NECext", "00 7F 00 00"): "Sharp",
    ("Kaseikyo", "80 02 20 00"): "Panasonic", ("RC5", "00 00 00 00"): "Philips",
    ("RC6", "00 00 00 00"): "Philips", ("NECext", "00 BD 00 00"): "Philips",
}


def parse_blocks(text):
    """Return (header, [block_text, ...]). A block starts at a 'name:' line."""
    m = re.search(r"^name:", text, re.M)
    if not m:
        return text, []
    header = text[:m.start()]
    body = text[m.start():]
    parts = re.split(r"(?=^name:)", body, flags=re.M)
    return header, [p for p in parts if p.strip().startswith("name:")]


def field(block, key):
    m = re.search(rf"^{key}:\s*(.+?)\s*$", block, re.M)
    return m.group(1).strip() if m else None


FIELD_RE = re.compile(r"^(name|type|protocol|address|command|frequency|duty_cycle|data):", re.M)


def clean_block(block):
    """Keep only signal field lines (drop stray/scrambled '# Brand' comments and
    blanks) so the reordered file stays tidy and never mislabels a code."""
    return "\n".join(ln for ln in block.splitlines() if FIELD_RE.match(ln))


def signature(block):
    """Identity for dedup."""
    proto = field(block, "protocol")
    if proto:
        return (proto, field(block, "address"), field(block, "command"))
    return ("RAW", field(block, "frequency"), field(block, "data"))


def family_of(block):
    proto = field(block, "protocol")
    if not proto:
        return RAW_RANK
    return FAMILY_RANK.get(proto, OTHER_PARSED_RANK)


def within_key(block, index):
    """Order inside a family: prioritised button first, then known-top brand
    codes, then original order — so each family's first pick is its most-likely
    power code."""
    name = (field(block, "name") or "").lower()
    name_pri = 0 if "power" in name or name in ("pwr", "pow") else 1
    known = 0 if (field(block, "protocol"), field(block, "address")) in KNOWN_TOP else 1
    return (name_pri, known, index)


# Families that carry the most brands get extra slots per round-robin cycle, but
# every family still appears in cycle 1 so any mainstream device is hit early.
FAMILY_WEIGHT = {0: 2, 1: 2}            # Samsung, NEC bucket -> 2 picks/cycle


def pop_rank(block):
    """Rank a block by current brand market share (lower = sooner)."""
    proto = field(block, "protocol")
    if proto is None:
        return POP_RAW_RANK
    r = SIGNATURE_RANK.get((proto, field(block, "address")))
    if r is not None:
        return r
    return POP_UNMATCHED_BASE + FAMILY_RANK.get(proto, OTHER_PARSED_RANK)


def order_blocks(deduped, mode):
    if mode == "popularity":
        # absolute popularity: most-likely-to-work codes first (minimises expected
        # sweep time when pointed at a random TV). Power before other buttons
        # within a rank; otherwise stable.
        def key(t):
            i, b = t
            name = (field(b, "name") or "").lower()
            name_pri = 0 if "power" in name or name in ("pwr", "pow") else 1
            return (pop_rank(b), name_pri, i)
        return [b for _, b in sorted(enumerate(deduped), key=key)]

    groups = {}
    for i, b in enumerate(deduped):
        groups.setdefault(family_of(b), []).append((within_key(b, i), b))
    for k in groups:
        groups[k].sort(key=lambda t: t[0])
    fam_order = sorted(groups)          # by family rank (Samsung, NEC, Sony, ...)

    if mode == "family":                # all of one brand together (single-brand targeting)
        return [b for k in fam_order for _, b in groups[k]]

    queues = [[b for _, b in groups[k]] for k in fam_order]
    weights = [FAMILY_WEIGHT.get(k, 1) for k in fam_order]
    ordered = []
    while any(queues):                  # weighted round-robin interleave (default)
        for qi, q in enumerate(queues):
            for _ in range(weights[qi]):
                if q:
                    ordered.append(q.pop(0))
    return ordered


def main():
    ap = argparse.ArgumentParser(description="Dedup + popularity-reorder a Flipper universal-remote .ir library.")
    ap.add_argument("input")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--button", default="Power",
                    help="button name to count/trim for the report and --top (default: Power)")
    ap.add_argument("--top", type=int, default=0,
                    help="keep only the N most-popular codes for --button (0 = keep all, full coverage)")
    ap.add_argument("--order", choices=("popularity", "interleave", "family"), default="popularity",
                    help="popularity = most-common brands first by 2025 market share (default, "
                         "minimises expected time on a random TV); interleave = round-robin brands "
                         "so any TV dies in the first few codes (best worst-case); "
                         "family = all of one brand together (single-brand targeting)")
    args = ap.parse_args()

    text = open(args.input, encoding="utf-8", errors="replace").read()
    header, blocks = parse_blocks(text)
    if not blocks:
        sys.exit("no signal blocks found — is this a Flipper .ir library file?")

    n_before = len(blocks)
    btn_before = sum(1 for b in blocks if (field(b, "name") or "").lower() == args.button.lower())

    # 1) dedup (stable: keep first occurrence)
    seen, deduped = set(), []
    for b in blocks:
        sig = signature(b)
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(b)

    # 2) reorder by popularity
    ordered = order_blocks(deduped, args.order)

    # 3) optional trim of the prioritised button to the top N
    if args.top:
        kept, btn_kept = [], 0
        for b in ordered:
            is_btn = (field(b, "name") or "").lower() == args.button.lower()
            if is_btn:
                if btn_kept >= args.top:
                    continue
                btn_kept += 1
            kept.append(b)
        ordered = kept

    out = header.rstrip("\n") + "\n" + "".join(clean_block(b) + "\n#\n" for b in ordered)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out)

    btn_after = sum(1 for b in ordered if (field(b, "name") or "").lower() == args.button.lower())
    # First 12 prioritised-button codes, as a sanity view of the new order.
    head = [b for b in ordered if (field(b, "name") or "").lower() == args.button.lower()][:12]
    print(f"signals: {n_before} -> {len(ordered)}  ({n_before - len(ordered)} removed)")
    print(f"'{args.button}' codes: {btn_before} -> {btn_after}")
    print(f"new '{args.button}' order (first {len(head)}):")
    for b in head:
        p = field(b, "protocol") or "RAW"
        a = field(b, "address") or field(b, "frequency") or "?"
        c = field(b, "command") or ""
        brand = SIGNATURE_BRAND.get((p, a), "")
        print(f"  {p:<10} addr {a:<12} cmd {c:<12} {brand}")


if __name__ == "__main__":
    main()
