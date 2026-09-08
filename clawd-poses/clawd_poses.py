#!/usr/bin/env python3
"""Draw the Clawd mascot in a range of poses and moods.

The source icon (homarr-labs/dashboard-icons `clawd.webp`) is pixel art on a
regular grid. Measured off the 400px original, one grid unit is 32px and the
character is:

    body      8 x 8 units
    arms      2 x 2 units, flush to the body's left and right edges, rows 2-4
    eyes      1 x 1 units at body-local (1, 1) and (6, 1)
    legs      four 1-unit legs, carved from body-local row 6 down

Everything here works in those units, so every pose stays on-model and on-grid.
Run with no arguments to render every pose plus a contact sheet into `out/`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --- canvas ------------------------------------------------------------------

PU = 48  # pixels per grid unit
CW, CH = 14, 12  # canvas, in units
BX, BY = 3.0, 3.0  # body top-left
BS = 8.0  # body size

BODY = (241, 92, 69, 255)
DARK = (19, 19, 19, 255)
PINK = (232, 54, 93, 255)
BLUE = (79, 163, 227, 255)
GOLD = (255, 194, 75, 255)
CREAM = (255, 245, 235, 255)
DEEP = (206, 61, 44, 255)

# Body-local landmarks, promoted to canvas coordinates.
TORSO = (BX, BY, BS, 6.0)  # solid down to local row 6
LEG_XS = (BX + 0, BX + 2, BX + 5, BX + 7)
LEG_TOP = BY + 6.0
EYE_L = (BX + 1, BY + 1)
EYE_R = (BX + 6, BY + 1)
ARM_Y = BY + 2.0  # default arm row
ARM_LX, ARM_RX = BX - 2.0, BX + BS


# --- primitives --------------------------------------------------------------


def rect(x, y, w, h, color=DARK):
    return ("r", float(x), float(y), float(w), float(h), color)


def glyph(pattern, x, y, w, h, color=DARK, flip=False):
    """Blit a '#'/'.' character grid as rects, scaled into a w x h unit box."""
    rows = [r[::-1] for r in pattern] if flip else list(pattern)
    ny, nx = len(rows), len(rows[0])
    cw, ch = w / nx, h / ny
    out = []
    for r, line in enumerate(rows):
        run = None
        for c in range(nx + 1):
            on = c < nx and line[c] == "#"
            if on and run is None:
                run = c
            elif not on and run is not None:
                out.append(rect(x + run * cw, y + r * ch, (c - run) * cw, ch, color))
                run = None
    return out


# --- body parts --------------------------------------------------------------


def torso():
    return [rect(*TORSO, BODY)]


def legs(style="stand"):
    lens = {
        "stand": (2.0, 2.0, 2.0, 2.0),
        "walk": (2.0, 1.25, 2.5, 1.6),
        "tiptoe": (1.4, 1.4, 1.4, 1.4),
        "long": (2.6, 2.6, 2.6, 2.6),
        "hop": (1.0, 1.6, 1.6, 1.0),
    }[style]
    return [rect(x, LEG_TOP, 1.0, ln, BODY) for x, ln in zip(LEG_XS, lens, strict=True)]


def arm(side, y=None, length=2.0, rise=0.0, hand=0.0):
    """A limb flush to a body edge: a horizontal segment `length` units long,
    optionally with a forearm at the outer end rising (+) or hanging (-), and a
    wider `hand` block capping it."""
    y = ARM_Y if y is None else y
    if rise > 0:
        # Flush against the body edge a raised forearm reads as an ear, so the
        # upper arm always reaches far enough out to clear the silhouette.
        length = max(length, 3.0)
    x = BX - length if side == "l" else BX + BS
    fx = x if side == "l" else x + length - 2.0
    out = [rect(x, y, length, 2.0, BODY)]
    if rise > 0:
        out.append(rect(fx, y - rise, 2.0, rise, BODY))
        if hand:
            out.append(rect(fx - hand / 2, y - rise - hand, 2.0 + hand, hand, BODY))
    elif rise < 0:
        out.append(rect(fx, y + 2.0, 2.0, -rise, BODY))
    return out


def arms(ly=None, ry=None, length=2.0, rise=0.0, hand=0.0):
    return arm("l", ly, length, rise, hand) + arm("r", ry, length, rise, hand)


# --- faces -------------------------------------------------------------------

EYES = {
    "open": ["########"] * 8,
    "wide": ["########"] * 8,
    "happy": [
        "........",
        "...##...",
        "..####..",
        ".##..##.",
        "##....##",
        "##....##",
        "........",
        "........",
    ],
    "smile": [
        "........",
        "........",
        "##....##",
        "##....##",
        ".##..##.",
        "..####..",
        "........",
        "........",
    ],
    "sad": [
        "........",
        "##....##",
        "##....##",
        ".##..##.",
        "..####..",
        "...##...",
        "........",
        "........",
    ],
    "closed": [
        "........",
        "........",
        "........",
        "########",
        "########",
        "........",
        "........",
        "........",
    ],
    "half": [
        "........",
        "........",
        "........",
        "########",
        "########",
        "########",
        "########",
        "########",
    ],
    "dot": [
        "........",
        "........",
        "...##...",
        "..####..",
        "..####..",
        "...##...",
        "........",
        "........",
    ],
    "x": [
        "##....##",
        "###..###",
        ".######.",
        "..####..",
        "..####..",
        ".######.",
        "###..###",
        "##....##",
    ],
    "heart": [
        ".##..##.",
        "########",
        "########",
        "########",
        ".######.",
        "..####..",
        "...##...",
        "........",
    ],
    "spiral": [
        ".######.",
        "##....##",
        "##.###.#",
        "##.#.#.#",
        "##.#.#.#",
        "##.####.",
        "##......",
        ".######.",
    ],
    "up": [  # looking up: pupil block sits high
        "########",
        "########",
        "########",
        "########",
        "........",
        "........",
        "........",
        "........",
    ],
    "side": [  # looking inward
        "....####",
        "....####",
        "....####",
        "....####",
        "....####",
        "....####",
        "....####",
        "....####",
    ],
    "narrow": [
        "........",
        "........",
        "########",
        "########",
        "########",
        "........",
        "........",
        "........",
    ],
}

BROWS = {
    "angry": ["##......", ".#####..", "....####"],
    "sad": ["....####", "..#####.", "####...."],
    "raised": ["########", "........", "........"],
    "flat": ["########", "########", "........"],
}

MOUTHS = {
    "smile": [
        "#..........#",
        "##........##",
        ".###....###.",
        "...######...",
        "............",
    ],
    "frown": [
        "...######...",
        ".###....###.",
        "##........##",
        "#..........#",
        "............",
    ],
    "flat": [
        "............",
        "############",
        "############",
        "............",
        "............",
    ],
    "small": [
        "....####....",
        "...######...",
        "...######...",
        "....####....",
        "............",
    ],
    "open": [
        "..########..",
        ".##########.",
        ".##########.",
        ".##########.",
        "..########..",
    ],
    "grin": [
        "############",
        "############",
        ".##########.",
        "..########..",
        "...######...",
    ],
    "smirk": [
        "............",
        ".#####......",
        "..#####.....",
        "...####.....",
        "............",
    ],
    "wavy": [
        "............",
        "##..##..##..",
        "..##..##..##",
        "............",
        "............",
    ],
    "tiny": [
        "............",
        ".....##.....",
        ".....##.....",
        "............",
        "............",
    ],
    "tooth": [
        "############",
        "############",
        ".###..#####.",
        "..###.####..",
        "...######...",
    ],
}


def eyes(kind="open", size=1.0, color=DARK, dy=0.0, dx=0.0, mirror=True):
    lx, ly = EYE_L[0] - (size - 1) / 2 + dx, EYE_L[1] - (size - 1) / 2 + dy
    rx, ry = EYE_R[0] - (size - 1) / 2 - dx, EYE_R[1] - (size - 1) / 2 + dy
    p = EYES[kind]
    return glyph(p, lx, ly, size, size, color) + glyph(
        p, rx, ry, size, size, color, flip=mirror
    )


def brows(kind, dy=-0.55):
    p = BROWS[kind]
    y = EYE_L[1] + dy
    return glyph(p, EYE_L[0] - 0.2, y, 1.4, 0.45) + glyph(
        p, EYE_R[0] - 0.2, y, 1.4, 0.45, flip=True
    )


def mouth(kind="smile", w=3.0, h=1.1, dy=0.0, dx=0.0, color=DARK):
    x = BX + BS / 2 - w / 2 + dx
    return glyph(MOUTHS[kind], x, EYE_L[1] + 1.7 + dy, w, h, color)


# --- floating decorations ----------------------------------------------------

Z = ["####", "...#", "..#.", ".#..", "####"]
QMARK = ["####", "#..#", "...#", ".##.", ".#..", "....", ".#.."]
STAR = ["..#..", ".###.", "#####", ".###.", "..#.."]
DROP = ["..##..", ".####.", "######", "######", ".####.", "..##.."]
SPARK = ["#...#", ".#.#.", "..#..", ".#.#.", "#...#"]
HEART = [".#.#.", "#####", "#####", ".###.", "..#.."]
ANGER = [".#.#.", "#####", ".#.#.", "#####", ".#.#."]
CONFETTI = ["##", "##"]


def zzz(x=11.3, y=0.6):
    out = []
    for i, size in enumerate((0.5, 0.7, 0.95)):
        out += glyph(Z, x - i * 0.15, y + (2 - i) * 1.0, size, size)
    return out


def blush(dy=1.15, w=1.3, h=0.55):
    return [
        rect(EYE_L[0] - 0.5, EYE_L[1] + dy, w, h, DEEP),
        rect(EYE_R[0] + 0.2, EYE_R[1] + dy, w, h, DEEP),
    ]


def sweat(x, y, size=0.75):
    return glyph(DROP, x, y, size, size, BLUE)


# --- poses -------------------------------------------------------------------

POSES: list[tuple[str, str, list, float]] = []


def add(key, label, shapes, tilt=0.0):
    POSES.append((key, label, shapes, tilt))


def base(leg="stand", **kw):
    return torso() + legs(leg) + arms(**kw)


add("neutral", "neutral", base() + eyes("open"))

add(
    "happy",
    "happy",
    base(ly=ARM_Y - 0.7, ry=ARM_Y - 0.7) + eyes("happy") + mouth("smile"),
)

add(
    "excited",
    "excited",
    base(leg="hop", rise=4.0)
    + eyes("wide", 1.3)
    + mouth("grin", 3.4, 1.4)
    + glyph(SPARK, 0.1, 5.2, 0.9, 0.9, GOLD)
    + glyph(SPARK, 13.0, 5.8, 0.8, 0.8, GOLD)
    + glyph(STAR, 6.6, 0.2, 0.8, 0.8, GOLD),
)

add(
    "sad",
    "sad",
    base(ly=ARM_Y + 1.6, ry=ARM_Y + 1.6, length=1.6)
    + eyes("sad")
    + brows("sad")
    + mouth("frown", 2.6, 1.0, dy=0.2),
)

add(
    "angry",
    "angry",
    base(ly=ARM_Y + 0.9, ry=ARM_Y + 0.9, length=2.5)
    + eyes("narrow")
    + brows("angry")
    + mouth("flat", 3.2, 1.0)
    + glyph(ANGER, 0.6, 1.0, 1.3, 1.3, DARK)
    + glyph(ANGER, 12.1, 1.4, 1.1, 1.1, DARK),
)

add(
    "surprised",
    "surprised",
    base(leg="tiptoe", ly=ARM_Y - 1.6, ry=ARM_Y - 1.6, length=2.6)
    + eyes("wide", 1.5)
    + brows("raised", dy=-1.1)
    + mouth("small", 2.2, 1.4, dy=0.4),
)

add(
    "sleepy",
    "sleepy",
    base(ly=ARM_Y + 1.4, ry=ARM_Y + 1.4, length=1.6)
    + eyes("closed")
    + mouth("tiny", 2.0, 1.0)
    + zzz(),
    tilt=-7,
)

add(
    "thinking",
    "thinking",
    torso()
    + legs()
    + arm("l", ARM_Y + 0.5)
    + arm("r", ARM_Y, rise=3.5, hand=0.8)
    + eyes("up")
    + brows("raised", dy=-1.0)
    + mouth("smirk", 2.4, 1.0, dx=-0.5)
    + glyph(QMARK, 1.0, 0.8, 1.4, 2.2),
)

add(
    "love",
    "in love",
    base(ly=ARM_Y - 0.5, ry=ARM_Y - 0.5)
    + eyes("heart", 1.25, PINK)
    + mouth("smile", 2.8, 1.1)
    + blush()
    + glyph(HEART, 0.9, 0.9, 1.2, 1.2, PINK)
    + glyph(HEART, 12.2, 1.8, 0.8, 0.8, PINK),
)

add(
    "laughing",
    "laughing",
    base(leg="hop", ly=ARM_Y - 1.3, ry=ARM_Y - 1.3)
    + eyes("happy")
    + mouth("open", 3.0, 1.5, dy=0.15),
    tilt=-11,
)

add(
    "crying",
    "crying",
    base(ly=ARM_Y + 1.6, ry=ARM_Y + 1.6, length=1.6)
    + eyes("sad")
    + mouth("frown", 2.6, 1.0, dy=0.25)
    + sweat(EYE_L[0] + 0.1, EYE_L[1] + 1.2)
    + sweat(EYE_R[0] + 0.1, EYE_R[1] + 1.5)
    + sweat(EYE_L[0] - 0.15, EYE_L[1] + 2.7, 0.6),
)

add(
    "wink",
    "wink",
    torso()
    + legs()
    + arm("l", ARM_Y + 0.5)
    + arm("r", ARM_Y, rise=3.5, hand=0.8)
    + glyph(EYES["smile"], EYE_L[0], EYE_L[1], 1, 1)
    + glyph(EYES["open"], EYE_R[0], EYE_R[1], 1, 1)
    + mouth("smirk", 2.6, 1.0, dx=0.4),
)

add(
    "cool",
    "cool",
    base(ly=ARM_Y + 0.7, ry=ARM_Y + 0.7)
    + [
        rect(EYE_L[0] - 0.6, EYE_L[1] - 0.25, 2.1, 1.4),
        rect(EYE_R[0] - 0.5, EYE_R[1] - 0.25, 2.1, 1.4),
        rect(EYE_L[0] + 1.5, EYE_L[1] + 0.1, 2.9, 0.5),
        rect(BX, EYE_L[1] - 0.05, 0.9, 0.4),
        rect(BX + BS - 0.9, EYE_L[1] - 0.05, 0.9, 0.4),
    ]
    + mouth("smirk", 2.6, 1.0, dx=0.3)
    + glyph(SPARK, 3.9, 3.05, 0.75, 0.75, CREAM),
)

add(
    "shrug",
    "shrug",
    torso()
    + legs()
    + arms(rise=2.6, hand=1.0)
    + eyes("half")
    + brows("raised", dy=-1.1)
    + mouth("wavy", 3.0, 1.0),
)

add(
    "wave",
    "waving",
    torso()
    + legs()
    + arm("l", ARM_Y + 0.5)
    + arm("r", ARM_Y - 0.5, length=3.4, rise=3.6, hand=1.2)
    + eyes("happy")
    + mouth("smile", 2.8, 1.1)
    + glyph(SPARK, 12.6, 2.6, 0.9, 0.9, GOLD),
)

add(
    "flex",
    "proud",
    torso()
    + legs("long")
    + arms(length=3.0, rise=3.2, hand=0.8)
    + eyes("narrow")
    + brows("angry", dy=-0.75)
    + mouth("grin", 3.0, 1.2),
)

add(
    "scared",
    "scared",
    base(leg="tiptoe", ly=ARM_Y - 1.9, ry=ARM_Y - 1.9, length=2.4)
    + eyes("dot", 1.2)
    + brows("sad", dy=-1.0)
    + mouth("wavy", 2.6, 1.0)
    + sweat(11.5, 2.2),
    tilt=5,
)

add(
    "dizzy",
    "dizzy",
    base(leg="walk", ly=ARM_Y + 1.1, ry=ARM_Y - 0.9)
    + eyes("spiral", 1.2, mirror=False)
    + mouth("wavy", 3.0, 1.0)
    + glyph(STAR, 2.1, 1.0, 1.0, 1.0, GOLD)
    + glyph(STAR, 11.0, 0.6, 0.8, 0.8, GOLD),
    tilt=13,
)

add(
    "mindblown",
    "mind blown",
    base(leg="tiptoe", rise=4.0, hand=1.0)
    + eyes("x", 1.35)
    + mouth("open", 3.2, 1.6, dy=0.2)
    + glyph(SPARK, 4.3, 0.3, 1.1, 1.1, GOLD)
    + glyph(SPARK, 8.6, 0.3, 1.1, 1.1, GOLD)
    + glyph(STAR, 6.5, 0.0, 1.0, 1.0, GOLD),
)

add(
    "determined",
    "determined",
    base(leg="walk", ly=ARM_Y + 1.0, ry=ARM_Y - 1.0, length=2.6)
    + eyes("narrow")
    + brows("angry", dy=-0.75)
    + mouth("flat", 2.4, 0.9),
    tilt=-6,
)

add(
    "smug",
    "smug",
    torso()
    + legs()
    + arms(ly=ARM_Y + 0.6, ry=ARM_Y + 0.6)
    + glyph(EYES["half"], EYE_L[0], EYE_L[1], 1, 1)
    + glyph(EYES["half"], EYE_R[0], EYE_R[1], 1, 1)
    + glyph(BROWS["raised"], EYE_L[0] - 0.2, EYE_L[1] - 1.0, 1.4, 0.4)
    + glyph(BROWS["flat"], EYE_R[0] - 0.2, EYE_R[1] - 0.5, 1.4, 0.4, flip=True)
    + mouth("smirk", 2.6, 1.0, dx=0.5),
)

add(
    "dead",
    "defeated",
    base(ly=ARM_Y + 1.6, ry=ARM_Y + 1.6, length=1.6)
    + eyes("x", 1.1)
    + mouth("wavy", 2.8, 1.0),
    tilt=180,
)

add(
    "curious",
    "curious",
    torso()
    + legs("walk")
    + arm("l", ARM_Y + 0.7)
    + arm("r", ARM_Y - 0.7)
    + eyes("open", 1.2, dx=-0.15)
    + brows("raised", dy=-1.1)
    + mouth("small", 1.8, 1.2, dy=0.3),
    tilt=-15,
)

add(
    "hungry",
    "hungry",
    base(ly=ARM_Y + 0.7, ry=ARM_Y + 0.7)
    + eyes("smile")
    + mouth("tooth", 3.4, 1.5, dy=0.1)
    + sweat(8.85, 6.6, 0.6),
)

add(
    "focused",
    "focused",
    base(ly=ARM_Y + 1.2, ry=ARM_Y + 1.2, length=3.2)
    + eyes("open")
    + brows("flat", dy=-0.42)
    + mouth("flat", 2.0, 0.8),
)

add(
    "sideeye",
    "side-eye",
    base(ly=ARM_Y + 0.6, ry=ARM_Y + 0.6)
    # Clawd has no eye whites, so a glance is the whole eye sliding off-centre.
    + glyph(EYES["half"], EYE_L[0] + 0.4, EYE_L[1] + 0.1, 1, 1)
    + glyph(EYES["half"], EYE_R[0] + 0.4, EYE_R[1] + 0.1, 1, 1)
    + glyph(BROWS["raised"], EYE_L[0] - 0.1, EYE_L[1] - 0.95, 1.4, 0.4)
    + glyph(BROWS["raised"], EYE_R[0] + 0.1, EYE_R[1] - 0.75, 1.4, 0.4)
    + mouth("smirk", 2.6, 1.0, dx=0.5),
)

add(
    "shy",
    "shy",
    torso()
    + legs("tiptoe")
    + arms(ly=ARM_Y + 1.4, ry=ARM_Y + 1.4, length=1.4)
    + eyes("smile")
    + blush(dy=1.0, w=1.5, h=0.7)
    + mouth("tiny", 2.0, 1.0, dy=0.2),
    tilt=-5,
)

add(
    "sneaky",
    "sneaky",
    base(leg="tiptoe", ly=ARM_Y + 0.9, ry=ARM_Y + 0.9, length=3.2)
    + eyes("half")
    + brows("angry", dy=-0.8)
    + mouth("smirk", 2.8, 1.0, dx=0.3),
    tilt=-9,
)

add(
    "nervous",
    "nervous",
    base(leg="tiptoe", ly=ARM_Y + 1.2, ry=ARM_Y + 1.2, length=1.4)
    + eyes("dot", 1.1)
    + brows("sad", dy=-0.9)
    + mouth("wavy", 2.6, 1.0)
    + sweat(1.6, 2.0, 0.7)
    + sweat(11.9, 2.4, 0.7),
    tilt=3,
)

add(
    "party",
    "celebrating",
    base(leg="hop", rise=4.0, hand=1.0)
    + eyes("happy")
    + mouth("grin", 3.2, 1.3)
    + glyph(CONFETTI, 1.2, 1.0, 0.5, 0.5, GOLD)
    + glyph(CONFETTI, 5.0, 0.3, 0.5, 0.5, PINK)
    + glyph(CONFETTI, 8.4, 0.9, 0.5, 0.5, BLUE)
    + glyph(CONFETTI, 12.3, 0.4, 0.5, 0.5, GOLD)
    + glyph(CONFETTI, 3.0, 2.2, 0.4, 0.4, BLUE)
    + glyph(CONFETTI, 10.6, 2.4, 0.4, 0.4, PINK),
)


# --- rendering ---------------------------------------------------------------


def render(shapes, tilt=0.0, pu=PU):
    im = Image.new("RGBA", (int(CW * pu), int(CH * pu)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for kind, x, y, w, h, color in shapes:
        assert kind == "r"
        x0, y0 = round(x * pu), round(y * pu)
        x1, y1 = round((x + w) * pu), round((y + h) * pu)
        if x1 > x0 and y1 > y0:
            d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=color)
    if tilt:
        im = im.rotate(tilt, resample=Image.Resampling.NEAREST, expand=False)
    return im


def to_svg(shapes, tilt=0.0, pu=PU):
    """Same geometry as `render`, as scalable rects."""
    body = []
    for kind, x, y, w, h, color in shapes:
        assert kind == "r"
        x0, y0 = round(x * pu), round(y * pu)
        x1, y1 = round((x + w) * pu), round((y + h) * pu)
        if x1 > x0 and y1 > y0:
            fill = "#%02x%02x%02x" % color[:3]
            body.append(
                f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" '
                f'height="{y1 - y0}" fill="{fill}"/>'
            )
    W, H = int(CW * pu), int(CH * pu)
    # PIL rotates counter-clockwise about the centre; SVG rotates clockwise.
    g = f'<g transform="rotate({-tilt} {W / 2} {H / 2})">' if tilt else "<g>"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" shape-rendering="crispEdges">'
        + g
        + "".join(body)
        + "</g></svg>\n"
    )


def _font(size):
    for p in (
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
    ):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def contact_sheet(images, labels, cols=6, cell=200, pad=14, label_h=30):
    rows = (len(images) + cols - 1) // cols
    bg = (250, 248, 246, 255)
    W = cols * (cell + pad) + pad
    H = rows * (cell + label_h + pad) + pad
    sheet = Image.new("RGBA", (W, H), bg)
    d = ImageDraw.Draw(sheet)
    f = _font(18)
    for i, (im, label) in enumerate(zip(images, labels, strict=True)):
        r, c = divmod(i, cols)
        x = pad + c * (cell + pad)
        y = pad + r * (cell + label_h + pad)
        thumb = im.resize((cell, cell), Image.Resampling.NEAREST)
        sheet.alpha_composite(thumb, (x, y))
        tw = d.textlength(label, font=f)
        d.text((x + (cell - tw) / 2, y + cell + 4), label, font=f, fill=(60, 55, 52))
    return sheet


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "out"
    out.mkdir(parents=True, exist_ok=True)
    images, labels = [], []
    for key, label, shapes, tilt in POSES:
        im = render(shapes, tilt)
        im.save(out / f"clawd-{key}.png")
        (out / f"clawd-{key}.svg").write_text(to_svg(shapes, tilt))
        images.append(im)
        labels.append(label)
    contact_sheet(images, labels).save(out / "clawd-moods.png")
    print(f"{len(POSES)} poses -> {out}")


if __name__ == "__main__":
    main()
