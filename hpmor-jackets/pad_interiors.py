#!/usr/bin/env python3
"""Pad each volume's contents.pdf to a multiple of 4 pages.

Blurb's calculator rejects odd page counts ("Saddle pages need to be multiple of 4";
hardcover/perfect-bound accepts multiples of 2, but multiples of 4 work everywhere
and match the upstream README's reported page counts). Each downloaded PDF is one
page short of a multiple of 4, so we append blank pages of matching size.

Input:  downloads/volume-N-contents.pdf
Output: downloads/volume-N-contents-padded.pdf
"""
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
DOWNLOADS = HERE / "downloads"


def get_page_info(pdf: Path) -> tuple[int, float, float]:
    """Return (pages, width_pt, height_pt)."""
    out = subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True
    ).stdout
    pages = None
    w = h = None
    for line in out.splitlines():
        if line.startswith("Pages:"):
            pages = int(line.split()[1])
        elif line.startswith("Page size:"):
            parts = line.split()
            w = float(parts[2])
            h = float(parts[4])
    if pages is None or w is None:
        raise RuntimeError(f"Could not parse pdfinfo for {pdf}")
    return pages, w, h


def make_blank_pdf(pages: int, w_pt: float, h_pt: float, out: Path) -> None:
    """Create a PDF of N blank white pages at exact point dimensions."""
    w_px = round(w_pt)
    h_px = round(h_pt)
    img = Image.new("RGB", (w_px, h_px), "white")
    # resolution=72 means 1px == 1pt, so final page is w_pt x h_pt
    img.save(out, "PDF", resolution=72.0, save_all=True, append_images=[img] * (pages - 1))


def pad_one(volume: int) -> None:
    src = DOWNLOADS / f"volume-{volume}-contents.pdf"
    dst = DOWNLOADS / f"volume-{volume}-contents-padded.pdf"
    pages, w, h = get_page_info(src)
    target = ((pages + 3) // 4) * 4  # round up to multiple of 4
    extra = target - pages
    if extra == 0:
        print(f"Volume {volume}: {pages} pages, already multiple of 4. Copying as-is.")
        dst.write_bytes(src.read_bytes())
        return
    with tempfile.TemporaryDirectory() as td:
        blank = Path(td) / "blank.pdf"
        make_blank_pdf(extra, w, h, blank)
        subprocess.run(
            ["pdfunite", str(src), str(blank), str(dst)],
            check=True,
        )
    new_pages, _, _ = get_page_info(dst)
    print(f"Volume {volume}: {pages} -> {new_pages} pages (+{extra} blank)")


def main(argv: list[str]) -> int:
    volumes = [int(a) for a in argv[1:]] if len(argv) > 1 else list(range(1, 7))
    for v in volumes:
        pad_one(v)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
