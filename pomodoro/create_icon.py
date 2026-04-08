#!/usr/bin/env python3
"""Generate a flat-design tomato icon for the Pomodoro app."""

from PIL import Image, ImageDraw
import subprocess
import os
import shutil
from pathlib import Path

ICON_DIR = Path(__file__).parent / "AppIcon.iconset"
SIZES = [16, 32, 64, 128, 256, 512, 1024]


def draw_tomato(size):
    """Draw a flat-design tomato at the given size."""
    # Draw at 4x for anti-aliasing, then downscale
    s = size * 4
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Proportions
    cx, cy = s // 2, int(s * 0.54)
    rx, ry = int(s * 0.38), int(s * 0.36)

    # Shadow
    draw.ellipse(
        [cx - rx, cy - ry + int(s * 0.03), cx + rx, cy + ry + int(s * 0.03)],
        fill=(200, 60, 50, 40)
    )

    # Main body - Things 3 blue-inspired but tomato red
    draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill='#E05545')

    # Subtle highlight
    hlx, hly = cx - int(rx * 0.2), cy - int(ry * 0.2)
    hlr = int(rx * 0.7)
    draw.ellipse([hlx - hlr, hly - hlr, hlx + hlr, hly + hlr], fill=(235, 100, 85, 80))

    # Stem
    stem_w = int(s * 0.035)
    stem_h = int(s * 0.1)
    stem_top = cy - ry - stem_h + int(s * 0.02)
    draw.rounded_rectangle(
        [cx - stem_w, stem_top, cx + stem_w, cy - ry + int(s * 0.04)],
        radius=stem_w,
        fill='#5B8C3E'
    )

    # Leaves
    leaf_w = int(s * 0.12)
    leaf_h = int(s * 0.045)
    leaf_y = cy - ry + int(s * 0.01)

    # Left leaf
    draw.ellipse(
        [cx - leaf_w - int(s * 0.02), leaf_y - leaf_h,
         cx + int(s * 0.01), leaf_y + leaf_h],
        fill='#6BA34A'
    )
    # Right leaf
    draw.ellipse(
        [cx - int(s * 0.01), leaf_y - leaf_h,
         cx + leaf_w + int(s * 0.02), leaf_y + leaf_h],
        fill='#6BA34A'
    )

    # Downscale with high-quality resampling
    return img.resize((size, size), Image.LANCZOS)


def main():
    ICON_DIR.mkdir(exist_ok=True)

    for size in SIZES:
        img = draw_tomato(size)
        img.save(ICON_DIR / f"icon_{size}x{size}.png")
        # @2x variants
        if size <= 512:
            img2x = draw_tomato(size * 2)
            img2x.save(ICON_DIR / f"icon_{size}x{size}@2x.png")

    # Convert to .icns
    icns_path = Path(__file__).parent / "AppIcon.icns"
    subprocess.run(
        ['iconutil', '-c', 'icns', str(ICON_DIR), '-o', str(icns_path)],
        check=True
    )
    shutil.rmtree(ICON_DIR)
    print(f"Created {icns_path}")


if __name__ == '__main__':
    main()
