#!/usr/bin/env python3
"""Build Blurb-ready dust jacket PDFs for each HPMOR volume.

Input: downloads/volume-N-cover.png (original softcover wrap)
Output: output/volume-N-jacket.pdf (hardcover dust jacket spread, 300 DPI)

Source softcover wraps: [bleed][back 6"][spine][front 6"][bleed] at 9.25" tall.
Target hardcover dust jacket: [bleed][flap 3.375"][back 6.542"][spine][front 6.542"][flap 3.375"][bleed] at 9.5" tall.

Cover panels are wider on the jacket (6.542" vs 6.0") because hardcover boards
overhang the page block. We split the source on its softcover geometry, then
resize each panel to the jacket geometry. Flaps are filled with a solid color
sampled from the cover's outermost edges.
"""
import json
import subprocess
import sys
from pathlib import Path
from PIL import Image

HERE = Path(__file__).parent
DOWNLOADS = HERE / "downloads"
OUTPUT = HERE / "output"
OUTPUT.mkdir(exist_ok=True)
CONFIG = HERE / "config.json"


def inches_to_px(inches: float, dpi: int) -> int:
    return round(inches * dpi)


def get_pdf_pages(pdf: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True
    )
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[1])
    raise RuntimeError(f"Could not read page count from {pdf}")


def split_source_cover(cover: Image.Image, dpi: int, bleed_in: float, page_trim_w_in: float):
    """Split softcover wrap into (back, spine, front) images.

    Source layout: [bleed][back page_trim_w][spine][front page_trim_w][bleed].
    Each panel returned includes the full source image height (trim + top/bottom bleed).
    Spine width is back-computed from total image width.
    """
    bleed_px = inches_to_px(bleed_in, dpi)
    trim_px = inches_to_px(page_trim_w_in, dpi)
    total_w, total_h = cover.size
    spine_px = total_w - (2 * bleed_px) - (2 * trim_px)
    if spine_px < 1:
        raise RuntimeError(
            f"Computed source spine is {spine_px}px — cover width {total_w} "
            f"is smaller than 2*bleed + 2*trim at {dpi} DPI."
        )
    back_x0 = bleed_px
    spine_x0 = back_x0 + trim_px
    front_x0 = spine_x0 + spine_px
    back = cover.crop((back_x0, 0, spine_x0, total_h))
    spine = cover.crop((spine_x0, 0, front_x0, total_h))
    front = cover.crop((front_x0, 0, front_x0 + trim_px, total_h))
    return back, spine, front


def sample_edge_color(img: Image.Image, side: str, strip_px: int = 20) -> tuple:
    """Average color of the outermost vertical strip on one side of img."""
    w, h = img.size
    if side == "left":
        strip = img.crop((0, 0, min(strip_px, w), h))
    else:
        strip = img.crop((max(0, w - strip_px), 0, w, h))
    strip = strip.convert("RGB")
    pixels = list(strip.getdata())
    n = len(pixels)
    return (
        sum(p[0] for p in pixels) // n,
        sum(p[1] for p in pixels) // n,
        sum(p[2] for p in pixels) // n,
    )


def build_jacket(volume: int, cfg: dict) -> Path:
    vcfg = cfg["volumes"][str(volume)]
    spine_in = vcfg["spine_in"]

    dpi = cfg["dpi"]
    bleed_in = cfg["bleed_in"]
    flap_in = cfg["flap_width_in"]
    page_trim_w = cfg["page_trim_width_in"]
    panel_w_in = cfg["jacket_panel_width_in"]
    trim_h_in = cfg["jacket_trim_height_in"]

    cover_path = DOWNLOADS / f"volume-{volume}-cover.png"
    padded_pdf = DOWNLOADS / f"volume-{volume}-contents-padded.pdf"
    raw_pdf = DOWNLOADS / f"volume-{volume}-contents.pdf"
    pdf_path = padded_pdf if padded_pdf.exists() else raw_pdf
    if not cover_path.exists() or not pdf_path.exists():
        raise RuntimeError(
            f"Missing source files for volume {volume}. Run download.py and pad_interiors.py."
        )
    pages = get_pdf_pages(pdf_path)

    bleed_px = inches_to_px(bleed_in, dpi)
    flap_px = inches_to_px(flap_in, dpi)
    panel_px = inches_to_px(panel_w_in, dpi)
    trim_h_px = inches_to_px(trim_h_in, dpi)
    spine_px = inches_to_px(spine_in, dpi)
    canvas_w = 2 * bleed_px + 2 * flap_px + 2 * panel_px + spine_px
    canvas_h = 2 * bleed_px + trim_h_px  # final PDF height = trim + top/bottom bleed

    cover = Image.open(cover_path).convert("RGB")
    back, spine, front = split_source_cover(cover, dpi, bleed_in, page_trim_w)

    # Resize each panel to jacket dimensions (full final height including bleed)
    back_scaled = back.resize((panel_px, canvas_h), Image.LANCZOS)
    front_scaled = front.resize((panel_px, canvas_h), Image.LANCZOS)
    spine_scaled = spine.resize((spine_px, canvas_h), Image.LANCZOS)

    # Sample flap colors BEFORE scaling — from source edges (the side adjacent to the flap fold)
    left_flap_color = sample_edge_color(back, "left")
    right_flap_color = sample_edge_color(front, "right")

    jacket = Image.new("RGB", (canvas_w, canvas_h), "white")
    x = 0
    jacket.paste(Image.new("RGB", (bleed_px, canvas_h), left_flap_color), (x, 0))
    x += bleed_px
    jacket.paste(Image.new("RGB", (flap_px, canvas_h), left_flap_color), (x, 0))
    x += flap_px
    jacket.paste(back_scaled, (x, 0))
    x += panel_px
    jacket.paste(spine_scaled, (x, 0))
    x += spine_px
    jacket.paste(front_scaled, (x, 0))
    x += panel_px
    jacket.paste(Image.new("RGB", (flap_px, canvas_h), right_flap_color), (x, 0))
    x += flap_px
    jacket.paste(Image.new("RGB", (bleed_px, canvas_h), right_flap_color), (x, 0))

    out = OUTPUT / f"volume-{volume}-jacket.pdf"
    jacket.save(out, "PDF", resolution=dpi)
    print(
        f"Volume {volume}: pages={pages} spine={spine_in}in "
        f"canvas={canvas_w}x{canvas_h}px ({canvas_w/dpi:.3f}x{canvas_h/dpi:.3f}in) -> {out.name}"
    )
    return out


def main(argv: list[str]) -> int:
    cfg = json.loads(CONFIG.read_text())
    volumes = [int(a) for a in argv[1:]] if len(argv) > 1 else list(range(1, 7))
    for v in volumes:
        try:
            build_jacket(v, cfg)
        except (RuntimeError, KeyError) as e:
            print(f"SKIP volume {v}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
