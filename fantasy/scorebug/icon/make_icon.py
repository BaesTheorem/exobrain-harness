"""Scorebug app icon: the Material Symbols "scoreboard" glyph (Apache-2.0,
pinned in ~/Documents/material-design/material-design-icons/variablefont) in white on the scorebug red,
with a steel bar along the bottom like the score bug's win split.

    python3 fantasy/scorebug/icon/make_icon.py   # writes icon-1024.png, Scorebug.icns and the website icons
"""
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT = Path.home() / "Documents/material-design/material-design-icons/variablefont/MaterialSymbolsOutlined[FILL,GRAD,opsz,wght].ttf"
RED, STEEL, INK = (229, 56, 59), (201, 194, 184), (14, 16, 19)


def draw(size: int, rounded: bool) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.2237) if rounded else 0          # macOS squircle-ish corner
    inset = int(size * 0.1) if rounded else 0          # macOS icons sit inside a margin
    box = (inset, inset, size - inset, size - inset)
    d.rounded_rectangle(box, radius=r, fill=INK)
    w = box[2] - box[0]
    d.rounded_rectangle((box[0], box[1], box[2], box[1] + int(w * 0.78)), radius=r, fill=RED)
    d.rectangle((box[0], box[1] + int(w * 0.5), box[2], box[1] + int(w * 0.78)), fill=RED)
    d.rectangle((box[0] + int(w * 0.58), box[1] + int(w * 0.78), box[2] - (r if r else 0) // 2, box[3]), fill=STEEL)
    font = ImageFont.truetype(str(FONT), int(w * 0.62))
    glyph = chr(0xEBD0)  # scoreboard, from the codepoints file next to the font
    ImageDraw.Draw(img).text((box[0] + w / 2, box[1] + w * 0.39), glyph, font=font, fill="white", anchor="mm")
    if rounded:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle(box, radius=r, fill=255)
        img.putalpha(mask)
    return img


def main() -> None:
    draw(1024, rounded=False).convert("RGB").save(HERE / "icon-1024.png")   # iOS masks it itself
    with tempfile.TemporaryDirectory() as t:
        iconset = Path(t) / "Scorebug.iconset"
        iconset.mkdir()
        for s in (16, 32, 128, 256, 512):
            draw(s, True).save(iconset / f"icon_{s}x{s}.png")
            draw(s * 2, True).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "Scorebug.icns")], check=True)
    # Website: a 32 px favicon, a 192 px icon, and the 180 px Apple touch icon.
    draw(64, True).resize((32, 32), Image.LANCZOS).save(HERE / "favicon-32.png")
    draw(192, False).convert("RGB").save(HERE / "icon-192.png")
    draw(180, False).convert("RGB").save(HERE / "apple-touch-icon.png")


if __name__ == "__main__":
    main()
