#!/usr/bin/env python3
"""cuneify: convert ATF transliteration (CDLI style) to Unicode cuneiform.

Reads the Oracc sign list (osl.asl, CC0) and maps each reading to the sign's
Unicode string. Prints one cuneiform line per ATF line, and reports every token
it could not resolve. `--back` prints the sign names for an independent check.
"""
import re, sys, json, argparse, pathlib

SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

def load_osl(path):
    val2sign = {}      # reading -> (sign name, ucun)
    name2ucun = {}
    name = ucun = None
    vals = []
    def flush():
        if name and ucun:
            name2ucun[name] = ucun
            for v in vals:
                val2sign.setdefault(v, (name, ucun))
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if line.startswith("@sign"):
            flush()
            name = line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else None
            ucun = None; vals = []
        elif line.startswith("@end sign"):
            flush(); name = ucun = None; vals = []
        elif line.startswith("@form"):
            # variant forms: stop collecting values for the parent sign
            flush(); name = None; ucun = None; vals = []
        elif line.startswith("@ucun") and name:
            parts = line.split(None, 1)
            if len(parts) > 1: ucun = parts[1].strip()
        elif re.match(r"@v[?\-]?\s", line) and name:
            if line.startswith("@v-"):        # deprecated reading
                continue
            body = line.split(None, 1)[1].strip()
            body = re.sub(r"^%\S+\s+", "", body)   # language tag
            tok = body.split()[0] if body else ""
            if tok and "ₓ" not in tok:
                vals.append(tok)
    flush()
    return val2sign, name2ucun

def norm(tok):
    """ATF token -> OSL reading."""
    t = tok.lower()
    t = t.replace("sz", "š").replace("s,", "ṣ").replace("t,", "ṭ")
    m = re.match(r"^(.*?)(\d+)$", t)
    if m and m.group(1):
        t = m.group(1) + m.group(2).translate(SUB)
    return t

def cuneify_line(line, val2sign, name2ucun, unknown):
    line = re.sub(r"^\d+'?\.\s*", "", line.strip())
    out_words = []; names = []
    for word in line.split():
        word = word.replace("_", "")
        word = re.sub(r"[#\[\]<>!?*]", "", word)
        # determinatives {d} -> separate token
        word = re.sub(r"\{([^}]+)\}", r"-\1-", word)
        signs = []
        for tok in [t for t in re.split(r"[-.]", word) if t]:
            if re.fullmatch(r"x|\(x\)", tok):
                continue
            mnum = re.fullmatch(r"(\d+)\((\w+)\)", tok)
            if mnum:
                key = f"{mnum.group(1)}({norm(mnum.group(2))})"
                cand = [key, key.upper(), f"{mnum.group(1)}({norm(mnum.group(2)).upper()})"]
                hit = next((name2ucun[c] for c in cand if c in name2ucun), None)
                if hit is None:
                    hit = next((val2sign[c][1] for c in cand if c in val2sign), None)
                if hit is None: unknown.append(tok); continue
                signs.append(hit); names.append(key); continue
            r = norm(tok)
            if r == "d": r = "an"                      # divine determinative
            if r in val2sign:
                nm, uc = val2sign[r]
                signs.append(uc); names.append(nm)
            else:
                unknown.append(tok)
        out_words.append("".join(signs))
    return " ".join(w for w in out_words if w), names

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("atf", help="ATF file, or - for stdin")
    ap.add_argument("--osl", required=True, help="path to osl.asl")
    ap.add_argument("--back", action="store_true", help="also print sign names")
    ap.add_argument("--json", help="write {lines:[{atf,cun,signs}]} here")
    a = ap.parse_args()
    val2sign, name2ucun = load_osl(a.osl)
    text = sys.stdin.read() if a.atf == "-" else pathlib.Path(a.atf).read_text(encoding="utf-8")
    unknown = []; rows = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(("&", "#", "@", "$")):
            if line.lstrip().startswith("@"): rows.append({"section": line.strip()})
            continue
        cun, names = cuneify_line(line, val2sign, name2ucun, unknown)
        rows.append({"atf": line.strip(), "cun": cun, "signs": names})
        print(cun)
        if a.back: print("    " + " ".join(names))
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps({"lines": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    if unknown:
        print("UNRESOLVED: " + " ".join(sorted(set(unknown))), file=sys.stderr); sys.exit(2)

if __name__ == "__main__":
    main()
