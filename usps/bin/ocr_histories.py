#!/usr/bin/env python3
"""OCR tracking screenshots in ../data/img and measure each with loopscan.

Writes ../data/ocr/<image>.txt and ../data/histories.json (one record per
image that holds at least 3 timestamped events). Tesseract runs one image at
a time (8 GB machine).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import loopscan  # noqa: E402

DATA = HERE.parent / "data"
IMG, OCR = DATA / "img", DATA / "ocr"


def ocr(path: Path) -> str:
    out = OCR / (path.name + ".txt")
    if out.exists():
        return out.read_text()
    # upscale small phone screenshots; tesseract reads 2x images far better
    tmp = OCR / (path.stem + ".png")
    subprocess.run(["sips", "-s", "format", "png", "--resampleWidth", "1800", str(path), "--out", str(tmp)],
                   capture_output=True, check=False)
    src = tmp if tmp.exists() else path
    r = subprocess.run(["tesseract", str(src), "-", "--psm", "4"], capture_output=True, text=True, check=False)
    tmp.unlink(missing_ok=True)
    out.write_text(r.stdout)
    return r.stdout


def main() -> None:
    OCR.mkdir(exist_ok=True)
    recs = []
    for p in sorted(IMG.iterdir()):
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        text = ocr(p)
        events = loopscan.parse_usps_text(text)
        if len(events) < 3:
            continue
        m = loopscan.metrics(events)
        m["image"] = p.name
        m["first_scan"] = events[0].ts.isoformat()
        m["scan_times"] = [e.ts.isoformat() for e in events if e.plant]
        recs.append(m)
        print(f"{p.name[:40]:40} events={m['events']:3} plant_visits={m['plant_visits']:2} "
              f"returns={m['returns_to_a_plant']:2} transits={m['plant_transit_min']}")
    (DATA / "histories.json").write_text(json.dumps(recs, indent=1, default=str))
    print(f"{len(recs)} usable histories")


if __name__ == "__main__":
    main()
