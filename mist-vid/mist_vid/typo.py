"""Storybook typography: gold-leaf and printer's-ink text sprites, ornaments, aged paper.

Sprites are straight-alpha RGBA uint8 arrays. Gold sprites also return a specular
map (float32, 0..1) so the compositor can sweep a glint across the letters.
"""
from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .paths import FONTS, PAPER
SYS = "/System/Library/Fonts/Supplemental"

FACES = {
    "fell": os.path.join(FONTS, "IMFeENrm28P.ttf"),
    "fell-it": os.path.join(FONTS, "IMFeENit28P.ttf"),
    "fell-sc": os.path.join(FONTS, "IMFeENsc28P.ttf"),
    "canon": os.path.join(FONTS, "IMFeFCrm28P.ttf"),
    "canon-it": os.path.join(FONTS, "IMFeFCit28P.ttf"),
    "canon-sc": os.path.join(FONTS, "IMFeFCsc28P.ttf"),
    "primer": os.path.join(FONTS, "IMFeGPrm28P.ttf"),
    "primer-it": os.path.join(FONTS, "IMFeGPit28P.ttf"),
    "pica": os.path.join(FONTS, "IMFELLDoublePica-Regular.ttf"),
    "pica-it": os.path.join(FONTS, "IMFELLDoublePica-Italic.ttf"),
    "cinzel-deco": os.path.join(FONTS, "CinzelDecorative-Regular.ttf"),
    "orn": os.path.join(SYS, "Hoefler Text Ornaments.ttf"),
    "orn2": os.path.join(SYS, "Bodoni Ornaments.ttf"),
}

# Hoefler Text Ornaments code points
ORN = {"rule": "", "rule2": "", "thin": "", "crown": "", "fleur": "",
       "ship": "", "sun": "", "moon": "", "hourglass": "⌛", "curl_l": "",
       "curl_r": "", "dingbat": ""}
ORN2 = {"swash": "•", "scroll_l": "°", "scroll_r": "±", "longrule": "∂", "leaf": "r",
        "leaf2": "s"}


def _font(face: str, size: float):
    path = FACES.get(face) or face
    return ImageFont.truetype(path, int(size))


def mask(text: str, face: str = "fell", size: float = 120, tracking: float = 0.0, ss: int = 3,
         pad: int = 24) -> np.ndarray:
    """Anti-aliased coverage mask (float32 0..1) of `text`, supersampled `ss`x.
    tracking is extra space between letters, in ems."""
    f = _font(face, size * ss)
    if tracking == 0:
        l, t, r, b = f.getbbox(text)
        w, h = r - l, b - t
        im = Image.new("L", (int(w + 2 * pad * ss), int(h + 2 * pad * ss)), 0)
        ImageDraw.Draw(im).text((pad * ss - l, pad * ss - t), text, font=f, fill=255)
    else:
        adv = [f.getlength(ch) for ch in text]
        extra = tracking * size * ss
        total = sum(adv) + extra * (len(text) - 1)
        asc, desc = f.getmetrics()
        im = Image.new("L", (int(total) + 2 * pad * ss, asc + desc + 2 * pad * ss), 0)
        d = ImageDraw.Draw(im)
        x = pad * ss
        for ch, a in zip(text, adv, strict=True):
            d.text((x, pad * ss), ch, font=f, fill=255)
            x += a + extra
        # trim vertical slack
        arr = np.array(im)
        rows = np.where(arr.max(axis=1) > 0)[0]
        if len(rows):
            im = im.crop((0, max(0, rows[0] - pad * ss), im.width, min(im.height, rows[-1] + pad * ss)))
    arr = np.asarray(im, dtype=np.float32) / 255.0
    h, w = arr.shape
    arr = cv2.resize(arr, (max(1, w // ss), max(1, h // ss)), interpolation=cv2.INTER_AREA)
    return arr


def stack(masks: list, align: str = "center", gap: float = 10) -> np.ndarray:
    w = max(m.shape[1] for m in masks)
    h = int(sum(m.shape[0] for m in masks) + gap * (len(masks) - 1))
    out = np.zeros((h, w), np.float32)
    y = 0
    for m in masks:
        x = {"center": (w - m.shape[1]) // 2, "left": 0, "right": w - m.shape[1]}[align]
        out[y:y + m.shape[0], x:x + m.shape[1]] = np.maximum(out[y:y + m.shape[0], x:x + m.shape[1]], m)
        y += int(m.shape[0] + gap)
    return out


def _noise(h, w, scale, seed):
    rng = np.random.default_rng(seed)
    small = rng.random((max(2, int(h / scale)) + 2, max(2, int(w / scale)) + 2)).astype(np.float32)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def fbm(h, w, seed, base=64.0, octaves=5):
    out = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        out += amp * _noise(h, w, base / (2 ** o), seed + o * 17)
        tot += amp
        amp *= 0.5
    return out / tot


def gold(m: np.ndarray, bevel: float = 5.0, light=(-0.45, -0.65, 0.62), seed: int = 3,
         shadow: float = 0.65, glow: float = 0.35, palette: str = "gold"):
    """Gold-leaf rendering of a coverage mask. Returns (rgba uint8, spec float32)."""
    h, w = m.shape
    pad = int(bevel * 6)
    mm = np.pad(m, pad)
    H, W = mm.shape
    binm = (mm > 0.5).astype(np.uint8)
    dist = cv2.distanceTransform(binm, cv2.DIST_L2, 5).astype(np.float32)
    hgt = np.clip(dist / bevel, 0, 1)
    hgt = np.sin(hgt * np.pi / 2) * mm
    hgt = cv2.GaussianBlur(hgt, (0, 0), 0.8)
    gx = cv2.Sobel(hgt, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(hgt, cv2.CV_32F, 0, 1, ksize=3)
    k = 2.2
    n = np.dstack([-gx * k, -gy * k, np.ones_like(gx)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    L = np.array(light, np.float32)
    L /= np.linalg.norm(L)
    diff = np.clip((n * L).sum(axis=2), 0, 1)
    R = 2 * (n * L).sum(axis=2, keepdims=True) * n - L
    spec = np.clip(R[..., 2], 0, 1) ** 24
    leaf = fbm(H, W, seed, base=18.0, octaves=4)
    cracks = fbm(H, W, seed + 99, base=40.0, octaves=3)
    crack_line = np.exp(-((cracks - 0.5) ** 2) / 0.0006) * 0.18
    if palette == "gold":
        dark, mid, light_c = np.array([0.36, 0.22, 0.06]), np.array([0.78, 0.56, 0.20]), np.array([1.0, 0.90, 0.58])
    elif palette == "silver":
        dark, mid, light_c = np.array([0.30, 0.30, 0.32]), np.array([0.70, 0.70, 0.72]), np.array([0.98, 0.98, 1.0])
    else:  # rose gold / copper
        dark, mid, light_c = np.array([0.35, 0.14, 0.08]), np.array([0.80, 0.46, 0.30]), np.array([1.0, 0.82, 0.66])
    shade = np.clip(0.25 + 0.95 * diff + 0.10 * (leaf - 0.5), 0, 1.3)
    col = np.where(shade[..., None] < 0.6,
                   dark + (mid - dark) * (shade[..., None] / 0.6),
                   mid + (light_c - mid) * np.clip((shade[..., None] - 0.6) / 0.6, 0, 1))
    col = col * (1 - crack_line[..., None])
    col = col + spec[..., None] * np.array([1.0, 0.95, 0.80]) * 0.9
    edge = np.clip(dist / (bevel * 0.6), 0, 1)
    col = col * (0.72 + 0.28 * edge[..., None])
    col = np.clip(col, 0, 1)
    # shadow + glow under the letters for legibility on footage
    a = mm
    sh = cv2.GaussianBlur(np.roll(np.roll(mm, int(bevel * 0.8), 0), int(bevel * 0.4), 1), (0, 0), bevel * 0.9)
    gl = cv2.GaussianBlur(mm, (0, 0), bevel * 3.0)
    under_a = np.clip(sh * shadow + gl * glow, 0, 1)
    under_c = np.array([0.10, 0.05, 0.02])
    out_a = a + under_a * (1 - a)
    out_c = (col * a[..., None] + under_c * (under_a * (1 - a))[..., None]) / np.maximum(out_a[..., None], 1e-5)
    rgba = np.dstack([np.clip(out_c, 0, 1), np.clip(out_a, 0, 1)])
    spec_full = cv2.GaussianBlur(np.clip(diff ** 3 * a, 0, 1), (0, 0), 1.0)
    return (rgba * 255 + 0.5).astype(np.uint8), spec_full.astype(np.float32)


def ink(m: np.ndarray, color=(0.16, 0.10, 0.06), rough: float = 0.18, seed: int = 5, density: float = 0.93):
    """Letterpress ink on paper: ragged edges, uneven density. Returns rgba uint8."""
    h, w = m.shape
    n = fbm(h, w, seed, base=6.0, octaves=3)
    a = np.clip((m - 0.5 + (n - 0.5) * rough) * 3.0 + 0.5, 0, 1)
    dens = density * (0.86 + 0.14 * fbm(h, w, seed + 5, base=30.0, octaves=3))
    a = a * dens
    rgba = np.dstack([np.full((h, w), color[0]), np.full((h, w), color[1]), np.full((h, w), color[2]), a])
    return (np.clip(rgba, 0, 1) * 255 + 0.5).astype(np.uint8)


def glow(m: np.ndarray, color=(1.0, 0.86, 0.6), radius: float = 18, strength: float = 1.0):
    """Soft additive halo sprite (rgba uint8, premult-friendly) for 'add' blending."""
    pad = int(radius * 3)
    mm = np.pad(m, pad)
    g = cv2.GaussianBlur(mm, (0, 0), radius) * strength
    g = np.clip(g, 0, 1)
    rgba = np.dstack([g * color[0], g * color[1], g * color[2], g])
    return (rgba * 255 + 0.5).astype(np.uint8)


def paper(w: int, h: int, seed: int = 11, tone=(0.93, 0.87, 0.74), age: float = 1.0) -> np.ndarray:
    """Aged book page, float32 RGB 0..1: ivory tint, fibres, foxing, darkened edges."""
    src = os.path.join(PAPER, "Paper001", "Paper001_2K-JPG_Color.jpg")
    base = cv2.cvtColor(cv2.imread(src), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    base = cv2.resize(base, (w, h), interpolation=cv2.INTER_AREA)
    lum = base.mean(axis=2, keepdims=True)
    tex = (lum - lum.mean()) * 1.6
    col = np.array(tone, np.float32)[None, None, :] + tex
    fox = fbm(h, w, seed, base=160.0, octaves=5)
    blot = np.clip((fox - 0.62) * 4.0, 0, 1) * 0.10 * age
    col = col - blot[..., None] * np.array([0.3, 0.55, 0.9])
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = np.minimum(xx, w - 1 - xx) / w
    dy = np.minimum(yy, h - 1 - yy) / h
    e = np.clip(np.minimum(dx * 1.0, dy * 1.8) / 0.12, 0, 1)
    edge = (1 - e) ** 2 * 0.28 * age * (0.7 + 0.6 * fbm(h, w, seed + 3, base=90.0, octaves=3))
    col = col - edge[..., None] * np.array([0.25, 0.45, 0.75])
    specks = (np.random.default_rng(seed).random((h, w)) > 0.9993).astype(np.float32)
    specks = cv2.GaussianBlur(specks, (0, 0), 0.8) * 3.0
    col = col - np.clip(specks, 0, 0.35)[..., None] * np.array([0.5, 0.6, 0.7])
    return np.clip(col, 0, 1).astype(np.float32)


def to_rgba(rgb: np.ndarray, alpha: float = 1.0) -> np.ndarray:
    a = np.full(rgb.shape[:2] + (1,), alpha, np.float32)
    return (np.clip(np.dstack([rgb, a]), 0, 1) * 255 + 0.5).astype(np.uint8)


def over(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> np.ndarray:
    """Straight-alpha 'over' of uint8 rgba src onto float rgb dst (in place, returns dst)."""
    h, w = src.shape[:2]
    H, W = dst.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return dst
    s = src[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32) / 255.0
    a = s[..., 3:4]
    dst[y0:y1, x0:x1] = dst[y0:y1, x0:x1] * (1 - a) + s[..., :3] * a
    return dst
