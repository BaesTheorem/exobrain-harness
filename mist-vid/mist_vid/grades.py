"""Colour grades as 3D LUTs (33^3), built from small numpy grade functions.

Each preset maps display RGB in [0,1] to graded RGB. The GPU samples the LUT with
trilinear filtering, so any function of RGB is one texture fetch.
"""
from __future__ import annotations

import numpy as np

N = 33


def _luma(c):
    return c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722


def _sat(c, s):
    y = _luma(c)[..., None]
    return y + (c - y) * s


def _curve(x, toe=0.0, shoulder=1.0, contrast=1.0, pivot=0.45):
    """Soft S-curve around pivot, then lift blacks to `toe` and roll highlights to `shoulder`."""
    x = np.clip(x, 0, 1)
    y = np.where(x < pivot,
                 pivot * (x / pivot) ** contrast,
                 1 - (1 - pivot) * ((1 - x) / (1 - pivot)) ** contrast)
    return toe + (shoulder - toe) * y


def _split(c, shadow_rgb, high_rgb, amount_s=0.12, amount_h=0.10):
    """Split toning: push shadows toward one hue, highlights toward another."""
    y = np.clip(_luma(c), 0, 1)[..., None]
    ws = (1 - y) ** 2
    wh = y ** 2
    return c + ws * amount_s * (np.array(shadow_rgb) - 0.5) + wh * amount_h * (np.array(high_rgb) - 0.5)


def _warmth(c, k):
    return c * np.array([1 + 0.06 * k, 1 + 0.01 * k, 1 - 0.08 * k])


def _rgb2hsv(c):
    c = np.clip(c, 0, 1)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    mx, mn = c.max(axis=-1), c.min(axis=-1)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-6
    rm = m & (mx == r)
    gm = m & (mx == g) & ~rm
    bm = m & ~rm & ~gm
    h[rm] = ((g[rm] - b[rm]) / d[rm]) % 6
    h[gm] = (b[gm] - r[gm]) / d[gm] + 2
    h[bm] = (r[bm] - g[bm]) / d[bm] + 4
    h = h * 60.0
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return np.stack([h, s, mx], axis=-1)


def _hsv2rgb(hsv):
    h, s, v = hsv[..., 0] % 360, np.clip(hsv[..., 1], 0, 1), hsv[..., 2]
    c = v * s
    x = c * (1 - np.abs((h / 60) % 2 - 1))
    m = v - c
    z = np.zeros_like(h)
    k = (h // 60).astype(int)
    r = np.choose(k % 6, [c, x, z, z, x, c])
    g = np.choose(k % 6, [x, c, c, x, z, z])
    b = np.choose(k % 6, [z, z, x, c, c, x])
    return np.stack([r + m, g + m, b + m], axis=-1)


def _hue(c, bands):
    """Hue-selective tweaks. bands: [(center_deg, width_deg, sat_mul, hue_shift_deg, val_mul)]."""
    hsv = _rgb2hsv(c)
    h = hsv[..., 0]
    sm = np.ones_like(h)
    hs = np.zeros_like(h)
    vm = np.ones_like(h)
    for cen, wid, s_mul, shift, v_mul in bands:
        dist = np.abs(((h - cen + 180) % 360) - 180)
        w = np.clip(1 - dist / wid, 0, 1)
        w = w * w * (3 - 2 * w)
        sm *= 1 + (s_mul - 1) * w
        hs += shift * w
        vm *= 1 + (v_mul - 1) * w
    hsv = np.stack([h + hs, hsv[..., 1] * sm, hsv[..., 2] * vm], axis=-1)
    out = _hsv2rgb(hsv)
    # keep near-grey pixels untouched (hue is noise there)
    k = np.clip(_rgb2hsv(c)[..., 1] * 6, 0, 1)[..., None]
    return c * (1 - k) + out * k


# band shorthands (degrees): reds 0, skin/orange 25, yellow 55, green 110, cyan 185, blue 220, magenta 300
def g_neutral(c):
    return _curve(c, toe=0.012, shoulder=0.985, contrast=1.05)


def g_storybook(c):
    """House look: warm cream highlights, umber shadows, olive-gold greens, true-blue skies."""
    c = _warmth(c, 0.6)
    c = _curve(c, toe=0.035, shoulder=0.975, contrast=1.14)
    c = _split(c, (0.44, 0.31, 0.21), (0.66, 0.56, 0.38), 0.22, 0.13)
    c = _hue(c, [(110, 55, 0.82, -10, 0.97), (180, 35, 0.92, 14, 1.0), (212, 40, 0.92, 3, 0.98),
                 (25, 25, 1.04, 0, 1.0)])
    return c


def g_golden(c):
    """Magic-hour gold for the farm and the finale."""
    c = _warmth(c, 1.15)
    c = _curve(c, toe=0.04, shoulder=0.985, contrast=1.12)
    c = _split(c, (0.46, 0.32, 0.20), (0.74, 0.57, 0.30), 0.22, 0.18)
    c = _hue(c, [(110, 55, 0.78, -14, 0.95), (180, 35, 0.88, 16, 1.0), (212, 40, 0.86, 4, 0.97),
                 (25, 25, 1.06, 2, 1.0)])
    return c


def g_night(c):
    """Moonlit teal shadows, skin kept warm."""
    c = _hue(c, [(110, 55, 0.7, 8, 0.95), (25, 25, 1.0, 0, 1.0)])
    c = _sat(c, 0.88)
    c = _curve(c, toe=0.02, shoulder=0.96, contrast=1.16)
    c = _split(c, (0.30, 0.44, 0.52), (0.62, 0.52, 0.42), 0.22, 0.10)
    return c


def g_ember(c):
    """Fire Swamp: burnt orange highlights, deep brown shadows."""
    c = _hue(c, [(110, 60, 0.6, -20, 0.9), (200, 60, 0.6, 0, 0.9), (25, 30, 1.10, -3, 1.0)])
    c = _warmth(c, 1.3)
    c = _curve(c, toe=0.018, shoulder=0.98, contrast=1.22)
    c = _split(c, (0.40, 0.27, 0.18), (0.78, 0.50, 0.24), 0.16, 0.16)
    return c


def g_despair(c):
    """Pit of Despair: drained, green-cyan, crushed."""
    c = _sat(c, 0.42)
    c = _curve(c, toe=0.012, shoulder=0.93, contrast=1.32)
    c = _split(c, (0.36, 0.47, 0.45), (0.52, 0.57, 0.50), 0.18, 0.10)
    return c


def g_dream(c):
    """Memory / reverie: lifted, pastel, low contrast."""
    c = _hue(c, [(110, 55, 0.7, -10, 1.0), (200, 50, 0.7, -5, 1.02)])
    c = _warmth(c, 0.8)
    c = _sat(c, 0.82)
    c = _curve(c, toe=0.08, shoulder=0.975, contrast=0.86)
    c = _split(c, (0.52, 0.42, 0.42), (0.68, 0.58, 0.46), 0.14, 0.12)
    return c


def g_bedroom(c):
    """The framing story: 1987 tungsten video, softened."""
    c = _warmth(c, 0.5)
    c = _sat(c, 0.84)
    c = _curve(c, toe=0.035, shoulder=0.97, contrast=1.05)
    c = _split(c, (0.42, 0.36, 0.32), (0.62, 0.53, 0.40), 0.12, 0.10)
    return c


def g_sepia(c):
    y = _luma(c)[..., None]
    c = y * np.array([1.07, 0.93, 0.74])
    return _curve(c, toe=0.05, shoulder=0.95, contrast=1.1)


def g_castle(c):
    """Night castle: cold stone, torch-warm faces."""
    c = _hue(c, [(25, 30, 1.08, 0, 1.0), (110, 60, 0.7, 10, 0.95), (220, 50, 0.9, -8, 1.0)])
    c = _curve(c, toe=0.02, shoulder=0.97, contrast=1.18)
    c = _split(c, (0.32, 0.40, 0.52), (0.70, 0.53, 0.34), 0.20, 0.16)
    return c


def g_dawn(c):
    """Finale dawn: rose-gold highlights, lavender shadows."""
    c = _hue(c, [(110, 55, 0.8, -10, 0.97), (220, 50, 0.85, 12, 1.0), (330, 40, 1.1, 0, 1.0),
                 (25, 25, 1.05, 0, 1.0)])
    c = _warmth(c, 0.6)
    c = _curve(c, toe=0.035, shoulder=0.985, contrast=1.1)
    c = _split(c, (0.46, 0.38, 0.50), (0.74, 0.58, 0.46), 0.18, 0.18)
    return c


PRESETS = {
    "neutral": g_neutral, "storybook": g_storybook, "golden": g_golden, "night": g_night,
    "ember": g_ember, "despair": g_despair, "dream": g_dream, "bedroom": g_bedroom,
    "sepia": g_sepia, "castle": g_castle, "dawn": g_dawn,
}


def lut(name: str) -> np.ndarray:
    """Return an (N, N, N, 3) float32 LUT indexed [b, g, r] (OpenGL 3D texture order)."""
    g = np.linspace(0, 1, N, dtype=np.float32)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    c = np.stack([r, gg, b], axis=-1)
    out = PRESETS[name](c)
    return np.clip(out, 0, 1).astype(np.float32)
