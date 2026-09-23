"""Render a retired TTRPG character's memorial card as a PNG.

Material Design 3, flat and sharp: the dark tonal scheme comes from the
vendored material-color-utilities seeded by the portrait, type is Roboto on
the MD3 type scale, icons are Material Symbols Sharp. Everything is drawn with
Pillow; the only subprocess is the color engine (palette.ts via tsx).

Usage:
    python3 memorial_card.py card.json -o out.png [--pdf out.pdf]

card.json holds the character's facts; see README.md for the fields.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ASSETS = Path.home() / "Documents" / "material-design"
FONTS = ASSETS / "fonts"
SYMBOLS = ASSETS / "material-design-icons" / "variablefont"
SYMBOLS_TTF = SYMBOLS / "MaterialSymbolsSharp[FILL,GRAD,opsz,wght].ttf"
SYMBOLS_MAP = SYMBOLS / "MaterialSymbolsSharp[FILL,GRAD,opsz,wght].codepoints"

S = 2  # render scale; layout below is in 1x dp
W = 1600
M = 72  # outer margin
GUTTER = 48

# MD3 type scale: (size, line height, weight)
TYPE = {
    "displayLarge": (57, 64, 400),
    "headlineMedium": (28, 36, 400),
    "headlineSmall": (24, 32, 400),
    "titleLarge": (22, 28, 400),
    "titleMedium": (16, 24, 500),
    "bodyLarge": (16, 24, 400),
    "bodyMedium": (14, 20, 400),
    "labelLarge": (14, 20, 500),
    "labelMedium": (12, 16, 500),
}


def hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def scheme_from(portrait: Image.Image) -> dict[str, tuple[int, int, int]]:
    small = portrait.convert("RGB").resize((112, 168))
    argb = [(255 << 24) | (r << 16) | (g << 8) | b for r, g, b in small.get_flattened_data()]  # pyright: ignore[reportGeneralTypeIssues]  # RGB image yields 3-tuples
    out = subprocess.run(
        ["npx", "-y", "tsx", str(HERE / "palette.ts")],
        input=json.dumps(argb), capture_output=True, text=True, check=True, cwd=HERE,
    ).stdout
    return {k: hex_rgb(v) for k, v in json.loads(out).items()}


@dataclass
class Style:
    font: ImageFont.FreeTypeFont
    line: int


_font_cache: dict[tuple[str, int, int], ImageFont.FreeTypeFont] = {}


def font(role: str, italic: bool = False, weight: int | None = None) -> Style:
    size, line, wght = TYPE[role]
    wght = weight or wght
    key = (("i" if italic else "r") + role, size, wght)
    if key not in _font_cache:
        f = ImageFont.truetype(str(FONTS / ("Roboto-Italic.ttf" if italic else "Roboto.ttf")), size * S)
        f.set_variation_by_axes([wght, 100])
        _font_cache[key] = f
    return Style(_font_cache[key], line * S)


class Icons:
    def __init__(self) -> None:
        self.cp = dict(
            (name, chr(int(code, 16)))
            for name, code in (ln.split() for ln in SYMBOLS_MAP.read_text().splitlines() if ln.strip())
        )
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}

    def draw(self, d: ImageDraw.ImageDraw, name: str, x: float, y: float, size: int, fill) -> None:
        if size not in self._fonts:
            f = ImageFont.truetype(str(SYMBOLS_TTF), size * S)
            f.set_variation_by_axes([0, 0, size, 400])  # FILL, GRAD, opsz, wght
            self._fonts[size] = f
        d.text((x * S, y * S), self.cp[name], font=self._fonts[size], fill=fill)


def wrap(text: str, st: Style, width: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if st.font.getlength(trial) <= width * S:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


class Card:
    def __init__(self, data: dict, portrait: Image.Image, scheme: dict) -> None:
        self.data, self.portrait, self.c = data, portrait, scheme
        self.img = Image.new("RGB", (W * S, 4000 * S), scheme["surface"])
        self.d = ImageDraw.Draw(self.img)
        self.icons = Icons()

    # primitives, all in 1x dp -------------------------------------------
    def text(self, x, y, s, role, color, width=None, italic=False, weight=None) -> float:
        st = font(role, italic, weight)
        lines = wrap(s, st, width) if width else [s]
        for i, ln in enumerate(lines):
            # center glyphs inside the MD3 line box
            asc, desc = st.font.getmetrics()
            pad = (st.line - (asc + desc)) / 2
            self.d.text((x * S, y * S + i * st.line + pad), ln, font=st.font, fill=self.c[color])
        return y + len(lines) * st.line / S

    def rect(self, x, y, w, h, fill=None, outline=None) -> None:
        self.d.rectangle(
            (x * S, y * S, (x + w) * S - 1, (y + h) * S - 1),
            fill=self.c[fill] if fill else None,
            outline=self.c[outline] if outline else None,
            width=S if outline else 0,
        )

    def hline(self, x, y, w, color="outlineVariant") -> None:
        self.d.rectangle((x * S, y * S, (x + w) * S, y * S + S - 1), fill=self.c[color])

    def text_w(self, s, role) -> float:
        return font(role).font.getlength(s) / S

    # components ---------------------------------------------------------
    def section(self, y, title) -> float:
        y = self.text(M, y, title, "titleLarge", "onSurface")
        self.hline(M, y + 12, W - 2 * M)
        return y + 32

    def chips(self, x, y, width, items, icon=None) -> float:
        cx, h, gap = x, 32, 8
        for label, faded in items:
            lead = 18 + 8 if icon else 0
            w = 16 + lead + self.text_w(label, "labelLarge") + 16
            if cx + w > x + width:
                cx, y = x, y + h + gap
            self.rect(cx, y, w, h, outline="outline" if not faded else "outlineVariant")
            color = "onSurfaceVariant" if faded else "onSurface"
            if icon:
                self.icons.draw(self.d, icon, cx + 12, y + 7, 18, self.c["primary" if not faded else "outline"])
            self.text(cx + 16 + lead - (4 if icon else 0), y + 6, label, "labelLarge", color)
            cx += w + gap
        return y + h

    # layout -------------------------------------------------------------
    def render(self) -> Image.Image:
        dt, c = self.data, self
        y = float(M)
        y = c.text(M, y, dt["campaign"], "titleMedium", "primary")
        y = c.text(M, y + 8, dt["name"], "displayLarge", "onSurface")
        y = c.text(M, y + 4, dt["full_name"], "titleLarge", "onSurfaceVariant")
        y += 32

        # portrait, outlined, square corners
        pw = 560
        ph = round(pw * self.portrait.height / self.portrait.width)
        p = self.portrait.convert("RGB").resize((pw * S, ph * S), Image.Resampling.LANCZOS)
        self.img.paste(p, (M * S, int(y * S)))
        self.rect(M, y, pw, ph, outline="outlineVariant")
        top, left = y, M + pw + GUTTER
        rw = W - M - left

        ry = c.text(left, top, dt["class_line"], "headlineSmall", "onSurface")
        ry = c.text(left, ry + 8, dt["summary"], "bodyLarge", "onSurfaceVariant", width=rw)
        ry += 24

        # stat grid, 3 x 2 outlined cells sharing hairlines
        cols, cw, chh = 3, rw / 3, 112
        for i, st in enumerate(dt["stats"]):
            cx, cy = left + (i % cols) * cw, ry + (i // cols) * chh
            c.rect(cx, cy, cw + 1, chh + 1, outline="outlineVariant")
            self.icons.draw(self.d, st["icon"], cx + 16, cy + 16, 24, c.c["primary"])
            c.text(cx + 16, cy + 44, st["value"], "headlineMedium", "onSurface")
            c.text(cx + 16, cy + 80, st["label"], "labelMedium", "onSurfaceVariant")
        ry += chh * ((len(dt["stats"]) + cols - 1) // cols) + 24

        # ideal, filled tonal card
        qy = ry
        q_end = c.text(left + 56, qy + 20, dt["ideal"], "headlineSmall", "onSecondaryContainer", width=rw - 80)
        c.rect(left, qy, rw, q_end - qy + 44, fill="secondaryContainer")
        self.icons.draw(self.d, "format_quote", left + 16, qy + 20, 24, c.c["onSecondaryContainer"])
        c.text(left + 56, qy + 20, dt["ideal"], "headlineSmall", "onSecondaryContainer", width=rw - 80)
        c.text(left + 56, q_end + 4, "Ideal", "labelMedium", "onSecondaryContainer")
        ry = q_end + 44 + 16

        # trait / bond / flaw list
        for label, body in dt["personality"]:
            c.text(left, ry + 12, label, "labelLarge", "primary")
            end = c.text(left + 72, ry + 12, body, "bodyLarge", "onSurface", width=rw - 72)
            ry = end + 12
            c.hline(left, ry, rw)

        # chip groups under the personality list, icon beside each title
        ry += 32
        for g in dt["groups"]:
            if g.get("icon"):
                self.icons.draw(self.d, g["icon"], left, ry + 2, 20, c.c["primary"])
            gy = c.text(left + (28 if g.get("icon") else 0), ry, g["title"], "titleMedium", "onSurface") + 10
            items = [(it.removeprefix("~"), it.startswith("~")) for it in g["items"]]
            ry = self.chips(left, gy, rw, items) + 24
        if dt.get("chip_note"):
            ry = c.text(left, ry - 8, dt["chip_note"], "bodyMedium", "onSurfaceVariant")

        y = max(top + ph, ry) + 56

        # campaign timeline, two-column MD3 list
        y = self.section(y, dt.get("timeline_title", "The campaign"))
        colw = (W - 2 * M - GUTTER) / 2
        half = (len(dt["timeline"]) + 1) // 2
        col_y = [y, y]
        for i, ev in enumerate(dt["timeline"]):
            k = 0 if i < half else 1
            x, ey = M + k * (colw + GUTTER), col_y[k]
            c.rect(x, ey + 4, 40, 40, fill="secondaryContainer")
            self.icons.draw(self.d, ev["icon"], x + 8, ey + 12, 24, c.c["onSecondaryContainer"])
            ty = c.text(x + 56, ey, ev["when"], "labelMedium", "primary")
            ty = c.text(x + 56, ty + 2, ev["text"], "bodyLarge", "onSurface", width=colw - 56)
            col_y[k] = max(ty, ey + 48) + 20
        y = max(col_y) + 40

        # footer
        c.hline(M, y, W - 2 * M)
        y += 20
        for i, (label, value) in enumerate(dt["credits"]):
            fx = M + i * 320
            c.text(fx, y, label, "labelMedium", "onSurfaceVariant")
            c.text(fx, y + 18, value, "titleMedium", "onSurface")
        y += 44 + M
        return self.img.crop((0, 0, W * S, int(y * S)))


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a TTRPG memorial card.")
    ap.add_argument("card", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--pdf", type=Path)
    a = ap.parse_args()
    data = json.loads(a.card.read_text())
    portrait = Image.open((a.card.parent / data["portrait"]).expanduser())
    img = Card(data, portrait, scheme_from(portrait)).render()
    img.save(a.out, optimize=True)
    if a.pdf:
        img.save(a.pdf, resolution=144 * S / 2)
    print(a.out)


if __name__ == "__main__":
    main()
