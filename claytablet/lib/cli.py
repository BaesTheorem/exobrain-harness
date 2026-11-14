#!/usr/bin/env python3
"""claytablet: ATF transliteration in, a photo-like cuneiform clay tablet out.

Each @obverse / @reverse section of the ATF becomes one face. The command
writes one PNG per face and one picture with all faces side by side.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np
from PIL import Image

import cuneify
import tablet as ct  # not "claytablet": from the repo root that name resolves to this folder

ASSETS = HERE.parent / "assets"
SYSTEM_FONT = pathlib.Path("/System/Library/Fonts/Supplemental/NotoSansCuneiform-Regular.ttf")


def read_faces(atf_text, osl_path):
    """Return [(section name, [cuneiform line, ...]), ...] and the unresolved tokens."""
    val2sign, name2ucun = cuneify.load_osl(osl_path)
    faces, unknown = [], []
    for line in atf_text.splitlines():
        s = line.strip()
        if not s or s.startswith(("&", "#", "$")):
            continue
        if s.startswith("@"):
            name = s[1:].split()[0]
            if name != "tablet":
                faces.append((name, []))
            continue
        if not faces:
            faces.append(("obverse", []))
        cun, _ = cuneify.cuneify_line(s, val2sign, name2ucun, unknown)
        faces[-1][1].append(cun)
    return [f for f in faces if f[1]], unknown


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("atf", help="ATF file, or - for stdin")
    ap.add_argument("-o", "--out", default="tablet", help="output path stem (default: tablet)")
    ap.add_argument("--width", type=int, default=1000, help="tablet width in pixels")
    ap.add_argument("--aspect", type=float, default=2.32, help="height / width of a face")
    ap.add_argument("--rows", type=int, help="ruled rows per face (default: the longest face)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--stamp", help="image to press into the clay as a seal (dark parts go deepest)")
    ap.add_argument("--stamp-face", default="reverse", help="section that takes the stamp")
    ap.add_argument("--break-at", action="append", default=[], metavar="X,Y,RX,RY",
                    help="a broken patch, in fractions of the face (repeat for more)")
    ap.add_argument("--scale-bar", action="store_true", help="draw a centimetre scale under the tablets")
    ap.add_argument("--width-cm", type=float, default=5.0, help="real width, for the scale bar")
    ap.add_argument("--font", help="cuneiform TTF (default: assets/Santakku.ttf, else Noto Sans Cuneiform)")
    ap.add_argument("--osl", default=str(ASSETS / "osl.asl"), help="Oracc sign list")
    ap.add_argument("--heights", action="store_true", help="also save the height fields (.npz), for a mesh")
    a = ap.parse_args()

    if not pathlib.Path(a.osl).exists():
        sys.exit(f"claytablet: no sign list at {a.osl}; run bin/claytablet-setup")
    font = a.font or next((str(p) for p in (ASSETS / "Santakku.ttf", SYSTEM_FONT) if p.exists()), None)
    if font is None:
        sys.exit("claytablet: no cuneiform font; run bin/claytablet-setup or pass --font")
    text = sys.stdin.read() if a.atf == "-" else pathlib.Path(a.atf).read_text(encoding="utf-8")
    faces, unknown = read_faces(text, a.osl)
    if unknown:
        sys.exit("claytablet: no sign for: " + " ".join(sorted(set(unknown))))
    if not faces:
        sys.exit("claytablet: the ATF has no text lines")

    rows = a.rows or max(len(lines) for _, lines in faces)
    breaks = [tuple(float(v) for v in b.split(",")) for b in a.break_at]
    stamp = Image.open(a.stamp) if a.stamp else None
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rendered = []
    for i, (name, lines) in enumerate(faces):
        takes_stamp = stamp is not None and name == a.stamp_face
        if takes_stamp and len(lines) > rows * 0.64:
            print(f"claytablet: {name} has {len(lines)} of {rows} rows, the stamp will cover text", file=sys.stderr)
        f = ct.render_face(lines, font, face_w=a.width, aspect=a.aspect, seed=a.seed + 4 * i, n_rows=rows,
                           stamp=stamp if takes_stamp else None, breaks=breaks if i == 0 else (),
                           crack=(i == 0))
        rendered.append(f)
        path = out.with_name(f"{out.name}-{name}.png")
        ct.compose(f).save(path)
        print(path)
        if a.heights:
            hp = out.with_name(f"{out.name}-{name}-heights.npz")
            np.savez_compressed(hp, z=f["z"], inside=f["inside"], pad=f["pad"], face=np.array(f["face"]))
            print(hp)
    path = out.with_name(f"{out.name}.png")
    ct.scene(rendered, tablet_h=int(a.width * a.aspect), scale_bar=a.scale_bar, width_cm=a.width_cm).save(path)
    print(path)


if __name__ == "__main__":
    main()
