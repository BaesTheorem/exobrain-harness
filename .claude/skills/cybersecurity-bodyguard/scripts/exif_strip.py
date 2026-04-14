#!/usr/bin/env python3
"""
EXIF inspector and stripper.

Images carry GPS, device, and authorship metadata that leaks home address and
identity. Use before posting any image publicly.

Usage:
    python3 exif_strip.py --check path/to/image.jpg     # report what's there
    python3 exif_strip.py --strip path/to/image.jpg     # write *_clean.jpg
    python3 exif_strip.py --strip-inplace path/img.jpg  # overwrite (destructive)

Depends on Pillow (PIL). Install: pip install Pillow
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image, ExifTags
except ImportError:
    print("[!] Pillow not installed. Run: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# EXIF tags we consider high-risk PII leaks
HIGH_RISK_TAGS = {
    "GPSInfo",
    "GPSLatitude",
    "GPSLongitude",
    "GPSAltitude",
    "Artist",
    "Copyright",
    "CameraOwnerName",
    "BodySerialNumber",
    "LensSerialNumber",
    "ImageUniqueID",
    "OwnerName",
}


def read_exif(path: Path) -> dict[str, object]:
    img = Image.open(path)
    raw = img.getexif()
    if not raw:
        return {}
    tag_map = {v: k for k, v in ExifTags.TAGS.items()}  # name -> id, inverted below
    tags = {}
    for tag_id, value in raw.items():
        name = ExifTags.TAGS.get(tag_id, f"tag_{tag_id}")
        if name == "GPSInfo" and isinstance(value, dict):
            gps = {
                ExifTags.GPSTAGS.get(k, f"gps_{k}"): v for k, v in value.items()
            }
            tags[name] = gps
        else:
            tags[name] = str(value)[:200]  # truncate long values
    return tags


def check(path: Path) -> dict[str, object]:
    tags = read_exif(path)
    risks = {k: v for k, v in tags.items() if k in HIGH_RISK_TAGS}
    return {
        "file": str(path),
        "has_exif": bool(tags),
        "tag_count": len(tags),
        "high_risk": risks,
        "verdict": "LEAK" if risks else ("METADATA" if tags else "CLEAN"),
    }


def strip(src: Path, dst: Path) -> None:
    img = Image.open(src)
    data = list(img.getdata())
    clean = Image.new(img.mode, img.size)
    clean.putdata(data)
    clean.save(dst)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", metavar="PATH")
    g.add_argument("--strip", metavar="PATH")
    g.add_argument("--strip-inplace", metavar="PATH")
    args = parser.parse_args()

    if args.check:
        result = check(Path(args.check))
        json.dump(result, sys.stdout, indent=2, default=str)
        print()
        return 0 if result["verdict"] == "CLEAN" else 1

    path = Path(args.strip or args.strip_inplace)
    if not path.exists():
        print(f"[!] Not found: {path}", file=sys.stderr)
        return 1

    if args.strip_inplace:
        dst = path
    else:
        dst = path.with_stem(path.stem + "_clean")

    strip(path, dst)
    result = check(dst)
    print(f"[+] Stripped -> {dst}")
    print(f"    Remaining tags: {result['tag_count']}  verdict: {result['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
