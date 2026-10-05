"""Snicker-Snack: pencil-length replica of the vorpal greatsword from D&D.

Built from one front-view painting (reference/snicker_snack.png, kept out of
the repo). The flat parts of the sword (blade, collar, crossguard vines) come
from the traced silhouette: the art is resampled onto a 0.1 mm grid, mirrored
into a symmetric outline and given depth on both faces as a heightfield. The
blade gets a bevelled diamond section with a recessed fuller wherever the
paint is purple. The guard vines become round tubes sized from their traced
width, with sunken pockets where the paint is in deep shadow and domed gems in
raised bezels. The round parts (vine-wrapped grip, leaf cup, rose pommel,
necklace loop) are true 3D shapes. Everything meets in one signed distance
field that sdfmesh meshes by marching cubes.

Coordinates: x across the guard, y along the sword (tip at 0, rose top at
190), z through the thickness. The loop's hole runs along x, so a chain
through it holds the sword face-on when worn.

Run:
  bin/cad build models/snicker_snack/build.py
  .venv/bin/python models/snicker_snack/build.py stage=2d     (2D design maps only)

PARAMS: res (voxel mm, 0.1), faces (print mesh budget), preview_faces
(Console preview budget), stage=all|2d. variant=halves is refused: the thorn
thicket has no clean split (see main).
"""

from __future__ import annotations

import json
import struct
import sys
import time
from pathlib import Path
from typing import cast

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import sdfmesh as sm  # noqa: E402

REF = HERE / "reference" / "snicker_snack.png"
DEFAULTS = {"variant": "full", "res": 0.1, "faces": 700000, "preview_faces": 300000, "stage": "all"}

LENGTH = 190.0          # tip to rose top, an unsharpened pencil

# blade and collar section
H_EDGE = 0.45           # half-thickness at the edge: a 0.9 mm edge
SLOPE = 0.22            # bevel rise per mm in from the edge (12 degrees)
FULLER = 0.32           # depth of the purple fuller panels
# guard vines
R_CAP = 1.5             # vines wider than 3 mm get a flat top
KZ = 1.05               # vine depth / vine width: a touch deeper than wide
H_MIN_VINE = 0.5        # the thinnest vine tip stays 1.0 mm thick
FATTEN = 0.12           # outward offset of the guard outline so thin tips print

# grip
GRIP_Y0, GRIP_Y1 = 153.5, 181.0
R_CORE = 1.85
PITCH = 10.0
R_HELIX = 2.15
R_VINE = 0.55
VINE_Y0, VINE_Y1 = 155.8, 178.8
_M = PITCH / (2 * np.pi * R_HELIX)
M_FAC = _M / np.sqrt(1 + _M ** 2)   # helix distance correction across the vine
# rose
ROSE_Y = 180.2
# Open outer petals with rolled-back tips, more upright petals inside, a
# tight bud in the middle: tier tops step up toward the centre so the side
# view shows layered scallops like the painting.
# Petals are obovate (narrow at the base, broad and round at the top).
#        count, first angle, centre height, radius, tilt, half height, half width, half thick, cup, reflex, base taper
# The outermost petals are one scalloped bowl (rose_bowl): separate open
# petals seen edge-on from the front read as spikes.
TIERS = [(5, 126, 4.6, 2.5, 26, 2.7, 2.5, 0.50, 0.13, 0.08, 0.4),
         (5, 90, 5.8, 1.6, 14, 2.4, 1.9, 0.45, 0.20, 0.05, 0.3),
         (3, 30, 6.9, 0.85, 6, 2.1, 1.3, 0.42, 0.30, 0.0, 0.2)]
# loop: a ring in the y-z plane, hole along x
RING_Y, RING_R, RING_WALL, RING_HW, HOLE_R = 191.9, 2.7, 0.9, 1.5, 1.8
# gem centres on the guard (front view)
GEMS = [(0.0, 151.6), (0.0, 143.6)]
# The quillon as a thorny thicket. The painted guard's vines are read as a
# skeleton with a radius at every point (the medial axis) and rebuilt as round
# canes (spheres along the skeleton), so a vine is as thick as it is wide.
# Copies of the painted vine set, turned about the blade and each weaving in
# and out of its own plane, make the mass, and hooked prickles sit along the
# canes. The painted copy keeps the face's outline; grown rose canes make the
# mass. Prickles never grow into the gems.
THICKET = [  # painted layers: angle about the blade (deg), scale, in-plane tilt (deg), seed
    (0, 1.00, 0.0, 11),
]
# Grown rose canes fill the thicket around the painted layer: each roots on
# the boss, curls like a bramble (steady curvature about a slowly turning
# axis), is kept inside a rounded envelope around the boss so the canes wrap
# into a dense mass, and stays out of a small tunnel in front of each gem.
CANES = 46              # main canes
CANE_SEED = 7
CANE_STEP = 0.25        # mm between samples along a cane
ENVELOPE = (0.0, 146.5, 0.0, 18.0, 11.5, 14.5)   # centre x, y, z and semi-axes of the mass
WEAVE = 2.4             # mm the canes weave out of their plane at full reach
THICKET_JOIN = 0.3      # fillet where the thicket meets the collar
PRICKLE_SPACING = 2.6   # mm between prickles along a cane
GUARD_Y = 147.0         # centre of the guard, for scaling and tilting the copies
CANE_MIN_R = 0.3        # skeleton points thinner than this are dropped (sub-print tips)
CANE_MAX_R = 1.1        # cane radius cap away from the central boss
BOSS_MAX_R = 3.0        # radius cap for the boss itself


def label(mask) -> tuple[np.ndarray, int]:
    out = cast("tuple[np.ndarray, int]", ndi.label(mask))
    return np.asarray(out[0]), int(out[1])


def log(msg: str) -> None:
    print(f"[snicker-snack] {msg}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------ the art

def trace_art():
    """Foreground mask of the painting with its see-through openings removed."""
    a = np.asarray(Image.open(REF).convert("RGB")).astype(np.int16)
    mn, mx = a.min(2), a.max(2)
    whiteish = (mn > 232) & (mx - mn < 25)
    lab, _ = label(whiteish)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    fg = ~np.isin(lab, edge[edge > 0])
    # Enclosed white patches over ~0.5 mm2 are openings in the guard; smaller
    # ones are paint highlights.
    isl, n = label(whiteish & fg)
    sizes = np.asarray(ndi.sum(np.ones(isl.shape), isl, np.arange(1, n + 1)))
    holes = np.isin(isl, np.nonzero(sizes > 40)[0] + 1)
    return a.astype(np.float32), fg, fg & ~holes


def fit_axis(fg):
    """Sword axis: principal direction, then corrected so it runs down the
    blade's centreline (the hilt is drawn a hair off-axis)."""
    ys, xs = np.nonzero(fg)
    P = np.stack([xs, ys], 1).astype(np.float64)
    c = P.mean(0)
    u = np.linalg.svd(P - c, full_matrices=False)[2][0]
    if u[1] < 0:
        u = -u
    v = np.array([-u[1], u[0]])
    s, t = (P - c) @ u, (P - c) @ v
    span = s.max() - s.min()
    mids = []
    for sv in np.linspace(s.min() + 0.45 * span, s.min() + 0.95 * span, 40):
        sel = np.abs(s - sv) < 1.0
        if sel.sum() >= 3:
            mids.append((sv, (t[sel].min() + t[sel].max()) / 2))
    m = np.array(mids)
    k, b = np.polyfit(m[:, 0], m[:, 1], 1)
    ang = np.arctan(k)
    u2 = np.cos(ang) * u + np.sin(ang) * v
    o2 = c + b * v
    v2 = np.array([-u2[1], u2[0]])
    s2 = (P - o2) @ u2
    return o2, u2, v2, float(s2.min()), float(s2.max())


def resample(img, solid, axis, xs, ys):
    """Art -> model grid. y runs tip (0) to rose top (LENGTH); x = -t keeps
    the painting's left on the model's left when viewed from +z."""
    o, u, v, s0, s1 = axis
    scale = LENGTH / (s1 - s0)
    XX, YY = np.meshgrid(xs, ys)
    s = s1 - YY / scale
    t = -XX / scale
    coords = [(o[1] + s * u[1] + t * v[1]).ravel(), (o[0] + s * u[0] + t * v[0]).ravel()]

    def samp(arr, cval):
        return ndi.map_coordinates(arr, coords, order=1, cval=cval).reshape(XX.shape)

    mask = samp(solid.astype(np.float32), 0.0) > 0.5
    rgb = np.stack([samp(img[..., c], 255.0) for c in range(3)], -1) / 255.0
    # colour outside the traced mask = nearest painted pixel, so the symmetric
    # outline and the vertex colours never pick up white background
    edt_out = cast("tuple[np.ndarray, np.ndarray]", ndi.distance_transform_edt(~mask, return_indices=True))
    idx = edt_out[1]
    rgb = rgb[idx[0], idx[1]]
    return mask, rgb, scale


# ------------------------------------------------------------- 2D design

def collar_region(xs, ys, res, shape):
    """Envelope of the blade and its angular collar, read off the art on a
    millimetre grid. Everything outside it is guard."""
    from skimage.draw import polygon as draw_polygon

    left = [(0, 136.4), (-2.6, 136.2), (-5.5, 135.4), (-8.2, 134.4), (-10.4, 133.7),
            (-10.3, 130.0), (-9.7, 127.0), (-8.7, 123.5), (-7.95, 120.0), (-7.5, 116.5),
            (-7.2, 113.0), (-7.05, 111.2), (-7.6, 111.0), (-7.6, -1.5)]
    poly = left + [(-x, y) for x, y in reversed(left[1:])]
    rr, cc = draw_polygon([(y - ys[0]) / res for _, y in poly],
                          [(x - xs[0]) / res for x, _ in poly], shape=shape)
    C = np.zeros(shape, bool)
    C[rr, cc] = True
    return C


def remove_small(mask, min_px):
    lab, n = label(mask)
    if n == 0:
        return mask
    sizes = np.asarray(ndi.sum(np.ones(mask.shape), lab, np.arange(1, n + 1)))
    return np.isin(lab, np.nonzero(sizes >= min_px)[0] + 1)


def symmetric(p):
    return 0.5 * (p + p[:, ::-1])


def design_2d(mask, rgb, xs, ys, res):
    """Signed distance D of the flat outline (negative inside) and the
    half-thickness H at every point of it, plus maps for the debug render."""
    from skimage.color import rgb2hsv

    X, Y = np.meshgrid(xs, ys)
    disk1 = ndi.generate_binary_structure(2, 1)

    D = symmetric(sm.sdf2d(mask, res))
    # grip, leaf cup and rose are built in 3D: cut them out of the flat outline
    zone = (Y > 160.5) | ((np.abs(X) < 3.4) & (Y > 154.8))
    D = np.maximum(D, -sm.sdf2d(zone, res))
    D = D - FATTEN * sm.smoothstep(100.0, 112.0, Y)
    # round the blade tip to r 0.3 mm (opening = erode, re-distance, dilate)
    D_open = sm.sdf2d(D < -0.3, res) - 0.3
    w_tip = sm.smoothstep(9.0, 5.0, Y)
    D = w_tip * D_open + (1 - w_tip) * D
    D = ndi.gaussian_filter(D, 0.6)
    # drop specks: anything under 1 mm2 would print as loose debris
    keep = remove_small(D < 0, int(1.0 / res ** 2))
    D = np.where((D < 0) & ~keep, np.maximum(D, 0.05), D)
    S = D < 0

    C = collar_region(xs, ys, res, S.shape)
    wC = ndi.gaussian_filter(C.astype(float), 0.4 / res)
    d = np.maximum(-D, 0.0)
    LT = sm.local_thickness(S, res, R_CAP)

    h_ridge = np.interp(Y, [0, 100, 112, 128], [1.30, 1.38, 1.55, 1.65])
    h_bevel = H_EDGE + np.minimum(SLOPE * d, h_ridge - H_EDGE)
    dd = np.minimum(d, LT)
    h_tube = np.maximum(KZ * np.sqrt(np.maximum(0.0, 2 * LT * dd - dd ** 2)), H_MIN_VINE)
    H = wC * h_bevel + (1 - wC) * h_tube

    hsv = rgb2hsv(np.clip(rgb, 0, 1))
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    # fuller: everything in the blade that is not painted green or yellow
    frame = (hue > 0.10) & (hue < 0.45) & (sat > 0.20) & (val > 0.25)
    frame = symmetric(ndi.gaussian_filter(frame.astype(float), 1.0)) > 0.5
    frame = np.asarray(ndi.binary_closing(ndi.binary_opening(frame, disk1), disk1), dtype=bool)
    rec = remove_small(S & C & ~frame & (d > 0.7), 30)
    rec_soft = ndi.gaussian_filter(rec.astype(float), 1.2)
    H = H - wC * FULLER * rec_soft * np.clip((h_bevel - H_EDGE - 0.12) / FULLER, 0, 1)

    # pockets: deep shadow inside the wide parts of the guard
    dark = (val < 0.30) & S & ~C & (d > 0.45) & (LT >= 1.2)
    dark = remove_small(symmetric(ndi.gaussian_filter(dark.astype(float), 1.0)) > 0.5, 20)
    pk = ndi.gaussian_filter(dark.astype(float), 1.2)
    H = H - (1 - wC) * pk * 0.55 * h_tube

    # the heart of the guard is thicker than its tips
    swell = 0.7 * np.clip(1 - np.hypot(X / 16.0, (Y - 147.0) / 9.0), 0, 1) ** 1.2
    H = H + (1 - wC) * swell

    gems = np.zeros(S.shape, bool)
    for (gx, gy), (a, dh) in zip(GEMS, [(1.0, 0.55), (1.45, 0.85)], strict=True):
        rho = np.hypot(X - gx, Y - gy)
        base = float(H[np.searchsorted(ys, gy), np.searchsorted(xs, gx)])
        dome = base + 0.05 + dh * np.sqrt(np.clip(1 - (rho / a) ** 2, 0, 1))
        H = np.where(rho < a, np.maximum(H, dome), H)
        bezel = (rho >= a) & (rho < a + 0.38)
        H = np.where(bezel, np.maximum(H, base + 0.18), H)
        gems |= rho < a + 0.38

    H = np.where(S, H, H_EDGE)
    H = ndi.gaussian_filter(H, 0.8)
    # blade and collar keep the heightfield; the guard becomes the thicket.
    # D_gfull is the whole painted guard (its hanging claws reach it through
    # the collar), D_gmain only its main connected piece, for the turned copies.
    sdf_c = sm.sdf2d(C, res)
    D_bc = np.maximum(D, sdf_c)
    D_gfull = np.maximum(D, -sdf_c)
    D_gmain = D_gfull.copy()
    glab, gn = label(D_gfull < 0)
    if gn > 1:
        main_piece = int(np.argmax(np.bincount(glab.ravel())[1:])) + 1
        D_gmain = np.where((glab > 0) & (glab != main_piece), 0.1, D_gfull)
    maps = {"S": S, "C": C, "rec": rec, "dark": dark, "gems": gems, "LT": LT,
            "D_bc": D_bc.astype(np.float32), "D_gfull": D_gfull.astype(np.float32),
            "D_gmain": D_gmain.astype(np.float32)}
    return D.astype(np.float32), H.astype(np.float32), maps


def debug_maps(D, H, maps, out: Path):
    """Shaded relief of the front face plus a region map, both upright."""
    S = maps["S"]
    gy, gx = np.gradient(H.astype(np.float64), 0.1)
    n = np.stack([-gx, -gy, np.ones_like(gx)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    light = np.array([-0.5, 0.6, 0.62])
    light /= np.linalg.norm(light)
    shade = np.clip(n @ light, 0, 1) * 0.85 + 0.15 * H / H.max()
    img = np.where(S, shade, 1.0)[::-1]
    rows = np.nonzero(S.any(1))[0]
    img = img[len(S) - 1 - rows.max(): len(S) - rows.min()]
    Image.fromarray((img * 255).astype(np.uint8)).save(out / "relief.png")
    reg = np.ones(S.shape + (3,))
    reg[S] = [0.75, 0.75, 0.75]
    reg[S & maps["C"]] = [0.55, 0.78, 0.45]
    reg[maps["rec"]] = [0.6, 0.45, 0.8]
    reg[maps["dark"]] = [0.15, 0.15, 0.15]
    reg[maps["gems"] & S] = [0.95, 0.85, 0.2]
    reg = reg[::-1][len(S) - 1 - rows.max(): len(S) - rows.min()]
    Image.fromarray((reg * 255).astype(np.uint8)).save(out / "regions.png")


# ------------------------------------------------------------- 3D parts

def grip_core(X, Y, Z):
    t = np.clip((Y - GRIP_Y0) / (GRIP_Y1 - GRIP_Y0), 0, 1)
    r = R_CORE + 0.12 * np.sin(np.pi * t)
    return np.maximum(np.hypot(X, Z) - r, np.maximum(GRIP_Y0 - Y, Y - GRIP_Y1))


def grip_vines(X, Y, Z):
    """Two vines wound in opposite directions, crossing twice per turn."""
    rho, th = np.hypot(X, Z), np.arctan2(Z, X)
    out = None
    for hand, phase in ((1, 0.0), (-1, np.pi / 2)):
        dth = sm.wrap_angle(th - (hand * 2 * np.pi * (Y - GRIP_Y0) / PITCH + phase))
        dv = np.sqrt((rho - R_HELIX) ** 2 + (M_FAC * R_HELIX * dth) ** 2) - R_VINE
        dv = np.maximum(dv, np.maximum(VINE_Y0 - Y, Y - VINE_Y1))
        out = dv if out is None else sm.smin(out, dv, 0.15)
    return out


def leaf(X, Y, Z, centre, phi, tilt, a, b, c, cup, point=0.0, reflex=0.0, base_taper=0.0):
    """A cupped, optionally pointed leaf or petal: an ellipsoid with half
    height a (along its tilted axis), half width b, half thickness c,
    standing around the y axis at angle phi and leaning out by tilt. cup
    curls the sides inward, reflex rolls the upper half outward."""
    er = np.array([np.cos(phi), 0.0, np.sin(phi)])
    et = np.array([-np.sin(phi), 0.0, np.cos(phi)])
    ey = np.array([0.0, 1.0, 0.0])
    ax = np.cos(tilt) * ey + np.sin(tilt) * er
    nm = -np.sin(tilt) * ey + np.cos(tilt) * er
    px, py, pz = X - centre[0], Y - centre[1], Z - centre[2]
    u = px * ax[0] + py * ax[1] + pz * ax[2]
    w = px * et[0] + pz * et[2]
    v = px * nm[0] + py * nm[1] + pz * nm[2] + cup * w * w - reflex * np.maximum(u, 0.0) ** 2
    if point:
        w = w / np.maximum(1.0 - point * np.clip(u / a, 0.0, 1.0), 0.15)
    if base_taper:
        w = w / np.maximum(1.0 - base_taper * np.clip(-u / a, 0.0, 1.0), 0.3)
    return sm.ellipsoid(u, w, v, a, b, c)


def leaf_from_base(X, Y, Z, base_r, base_y, phi, tilt_deg, length, width, thick, cup, point):
    tilt = np.radians(tilt_deg)
    er = np.array([np.cos(phi), 0.0, np.sin(phi)])
    ax = np.cos(tilt) * np.array([0.0, 1.0, 0.0]) + np.sin(tilt) * er
    centre = base_r * er + np.array([0.0, base_y, 0.0]) + 0.5 * length * ax
    return leaf(X, Y, Z, centre, phi, tilt, 0.5 * length, 0.5 * width, 0.5 * thick, cup, point)


def calyx(X, Y, Z):
    """Six pointed leaves cupping the base of the grip, two of them face-on."""
    out = None
    for k in range(6):
        phi = np.radians(30 + 60 * k)
        f = leaf_from_base(X, Y, Z, 1.7, 154.6, phi, 24, 5.2, 2.0, 0.9, 0.15, 0.5)
        out = f if out is None else sm.smin(out, f, 0.15)
    return out


def rose_bowl(X, Y, Z):
    """Outer petals as one cupped shell: flares from r 2.2 to 5.3 mm, rolls
    out at the rim, and the rim rises and falls in five petal scallops."""
    rho, phi = np.hypot(X, Z), np.arctan2(Z, X)
    yl = Y - ROSE_Y
    t = np.clip((yl - 1.0) / 4.8, 0.0, 1.0)
    R = 2.2 + 3.1 * np.sin(t * np.pi / 2) + 0.45 * sm.smoothstep(4.0, 6.0, yl)
    # a shallow crease where neighbouring outer petals meet
    crease = sm.wrap_angle(5 * (phi - np.pi / 2) - np.pi) / 5
    R = R - 0.35 * np.exp(-((crease * R) / 0.45) ** 2) * sm.smoothstep(1.5, 3.5, yl)
    shell = np.abs(rho - R) - 0.55
    top = 5.5 + 0.6 * np.cos(5 * (phi - np.pi / 2))
    # rounded rim: smooth intersection of the shell with the scalloped cap
    return -sm.smin(-shell, -np.maximum(yl - top, 0.9 - yl), 0.35)


def rose(X, Y, Z):
    out = sm.ellipsoid(X, Y - (ROSE_Y + 3.6), Z, 2.8, 3.4, 2.8)                 # core
    out = sm.smin(out, rose_bowl(X, Y, Z), 0.2)
    for count, first, cy, rad, tilt, a, b, c, cup, reflex, taper in TIERS:
        for k in range(count):
            phi = np.radians(first + 360.0 * k / count)
            centre = np.array([rad * np.cos(phi), ROSE_Y + cy, rad * np.sin(phi)])
            f = leaf(X, Y, Z, centre, phi, np.radians(tilt), a, b, c, cup, reflex=reflex, base_taper=taper)
            out = sm.smin(out, f, 0.12)
    out = sm.smin(out, sm.ellipsoid(X, Y - (ROSE_Y + 7.6), Z, 1.0, 1.9, 1.0), 0.15)    # bud
    for k in range(6):                                                            # sepals
        f = leaf_from_base(X, Y, Z, 1.5, ROSE_Y + 1.2, np.radians(60 * k + 30), 140, 2.8, 1.6, 0.8, 0.05, 0.4)
        out = sm.smin(out, f, 0.2)
    neck = np.maximum(np.hypot(X, Z) - 1.75, np.maximum(ROSE_Y - 2.0 - Y, Y - ROSE_Y - 2.5))
    stem = np.maximum(np.hypot(X, Z) - 1.45, np.maximum(ROSE_Y + 6.0 - Y, Y - (RING_Y - 1.0)))
    return sm.smin(sm.smin(out, neck, 0.3), stem, 0.25)


def ring(X, Y, Z):
    q = np.hypot(Y - RING_Y, Z) - RING_R
    return sm.rounded_box2(q, X, RING_WALL, RING_HW, 0.6)


def ring_hole(X, Y, Z):
    return np.maximum(np.hypot(Y - RING_Y, Z) - HOLE_R, np.abs(X) - 3.0)


# (kind, function, box x0 x1 y0 y1 z0 z1, smooth radius); boxes carry a
# margin wider than the blend so fields meet without seams
PARTS = [
    ("union", grip_core, (-4.5, 4.5, 151.5, 183.0, -4.5, 4.5), 0.35),
    ("union", grip_vines, (-4.5, 4.5, 153.5, 181.0, -4.5, 4.5), 0.2),
    ("union", calyx, (-7.0, 7.0, 152.0, 162.0, -7.0, 7.0), 0.25),
    ("union", rose, (-7.6, 7.6, 175.5, 192.0, -7.6, 7.6), 0.3),
    ("union", ring, (-3.4, 3.4, 187.0, 197.5, -5.0, 5.0), 0.3),
]
CUTS = [("cut", ring_hole, (-3.2, 3.2, 190.0, 195.2, -2.6, 2.6), 0.0)]


def rose_sepals(X, Y, Z):
    """The green sepals under the bloom, for colouring only (rose() builds them)."""
    fields = [leaf_from_base(X, Y, Z, 1.5, ROSE_Y + 1.2, np.radians(60 * k + 30), 140, 2.8, 1.6, 0.8, 0.05, 0.4)
              for k in range(6)]
    return np.minimum.reduce(fields)


COLORS = {  # preview colours for the 3D parts (sRGB, 0..1); later entries win ties
    grip_core: (0.40, 0.25, 0.14), grip_vines: (0.33, 0.44, 0.17), calyx: (0.36, 0.47, 0.17),
    rose: (0.60, 0.10, 0.22), ring: (0.64, 0.48, 0.22),
}
OVERRIDES = {rose_sepals: (0.24, 0.36, 0.13)}   # painted over whatever part they sit in


def irange(arr, lo, hi):
    return int(np.searchsorted(arr, lo)), int(np.searchsorted(arr, hi, side="right"))


def skeleton_points(Dg, xs, ys):
    """Medial axis of a guard outline: (x, y, r) for every skeleton pixel,
    r = distance to the outline. Spheres of radius r on these points rebuild
    the outline in the plane and make every vine round across it.

    The painted widths wobble, so r is smoothed along the cane (median over
    1 mm), spurs (points much thinner than their neighbourhood, which the
    medial axis sends toward bumps in the outline) are dropped, and canes away
    from the central boss are capped at CANE_MAX_R."""
    from scipy.spatial import KDTree
    from skimage.morphology import medial_axis

    sk = np.asarray(medial_axis(Dg < 0), dtype=bool)
    iy, ix = np.nonzero(sk)
    r = -Dg[iy, ix].astype(np.float64)
    pts = np.stack([xs[ix], ys[iy]], 1)
    tree = KDTree(pts)
    r_med = np.array([np.median(r[nb]) for nb in tree.query_ball_point(pts, 1.0)])
    keep = (r >= CANE_MIN_R) & (r >= 0.55 * r_med)
    cap = CANE_MAX_R + (BOSS_MAX_R - CANE_MAX_R) * (1 - sm.smoothstep(3.0, 6.0, np.abs(pts[:, 0])))
    r_s = np.minimum(r_med, cap)
    return np.stack([pts[keep, 0], pts[keep, 1], r_s[keep]], 1)


def thin_cane(P, R):
    """Keep samples along an ordered cane so neighbours stay within 0.3 r."""
    keep = np.zeros(len(P), bool)
    keep[0] = keep[-1] = True
    last = 0
    for k in range(1, len(P)):
        if np.linalg.norm(P[k] - P[last]) >= max(0.1, 0.3 * min(R[k], R[last])):
            keep[k] = True
            last = k
    return keep


def thin_out(pts):
    """Greedy thinning: neighbours closer than 0.3 r are covered by the
    bigger sphere (the surface between kept spheres dips < 0.012 r)."""
    from scipy.spatial import KDTree

    tree = KDTree(pts[:, :2])
    taken = np.zeros(len(pts), bool)
    keep = []
    for i in np.argsort(-pts[:, 2], kind="stable"):
        if taken[i]:
            continue
        keep.append(i)
        taken[tree.query_ball_point(pts[i, :2], max(0.1, 0.3 * pts[i, 2]))] = True
    return pts[np.array(keep)]


def prickle(base, tangent, r_cane, rng, colour):
    """Samples for one rose prickle on a cane: broad base, short, hooked
    back along the cane and down toward the blade."""
    tangent = tangent / (np.linalg.norm(tangent) + 1e-9)
    n1 = np.cross(tangent, np.array([0.0, 1.0, 0.0]) if abs(tangent[1]) < 0.9 else np.array([1.0, 0.0, 0.0]))
    n1 /= np.linalg.norm(n1)
    n2 = np.cross(tangent, n1)
    th = rng.uniform(0, 2 * np.pi)
    d = np.cos(th) * n1 + np.sin(th) * n2 - 0.25 * tangent + np.array([0.0, -0.2, 0.0])
    d /= np.linalg.norm(d)
    length = r_cane + rng.uniform(0.6, 1.0)
    t = np.linspace(0.0, 1.0, 14)[:, None]
    hook = -0.5 * tangent + np.array([0.0, -0.5, 0.0])
    pc = base + length * t * d + 0.5 * (length - r_cane) * t ** 2 * hook
    rb = float(np.clip(0.62 * r_cane, 0.32, 0.62))
    radii = rb * (1 - t[:, 0]) ** 1.3 + 0.12 * t[:, 0]   # tip above the 0.1 mm grid
    cols = (1 - t) * np.asarray(colour) + t * np.array([0.55, 0.27, 0.17])
    return pc, radii, cols


def grow_cane(rng, start, direction, length, r0, r1, gems, branch=True):
    """One bramble cane as [(points, radii, tangents)], side shoots included.

    The cane turns at a steady curvature about an axis that drifts slowly,
    so it curls. Inside the outer part of ENVELOPE it is steered back toward
    the centre, near the boss it is pushed out, and it is pushed sideways out
    of a tunnel in front of and behind each gem."""
    cx, cy, cz, ax, ay, az = ENVELOPE
    p, d = np.array(start, float), np.array(direction, float) / np.linalg.norm(direction)
    kappa = rng.uniform(0.12, 0.26)                     # rad per mm
    axis = rng.normal(size=3)
    n = max(4, int(length / CANE_STEP))
    pts, tans = [], []
    for _ in range(n):
        pts.append(p.copy())
        tans.append(d.copy())
        axis += rng.normal(size=3) * 0.15
        a_perp = axis - np.dot(axis, d) * d
        if np.linalg.norm(a_perp) > 1e-6:
            d = d + np.cross(a_perp / np.linalg.norm(a_perp), d) * kappa * CANE_STEP
        q = np.array([(p[0] - cx) / ax, (p[1] - cy) / ay, (p[2] - cz) / az])
        e = float(np.linalg.norm(q))
        if e > 0.82:                                     # curl back in at the edge of the mass
            d = d - (q / e) * (e - 0.82) * 1.6 * CANE_STEP * 4
        rho = np.hypot(p[0], p[2])
        if rho < 2.6 and rho > 1e-6:                     # do not bore through the boss
            d = d + np.array([p[0], 0.0, p[2]]) / rho * (2.6 - rho) * CANE_STEP * 2
        for gy, a, boss in gems:                         # keep the gems in view
            g = np.array([p[0], p[1] - gy])
            gr = float(np.linalg.norm(g))
            if gr < a + 1.3 and abs(p[2]) > boss - 0.6:
                push = g / gr if gr > 1e-6 else np.array([1.0, 0.0])
                d = d + np.array([push[0], push[1], 0.0]) * (a + 1.3 - gr) * CANE_STEP * 6
        d /= np.linalg.norm(d)
        p = p + d * CANE_STEP
    P, T = np.array(pts), np.array(tans)
    R = r0 + (r1 - r0) * np.linspace(0, 1, n) ** 0.8
    out = [(P, R, T)]
    if branch:
        for _ in range(rng.integers(0, 3)):
            k = int(rng.uniform(0.3, 0.75) * n)
            side = np.cross(T[k], rng.normal(size=3))
            side /= np.linalg.norm(side) + 1e-9
            out += grow_cane(rng, P[k], T[k] + 0.9 * side, rng.uniform(4.0, 9.0), R[k] * 0.75, 0.42, gems,
                             branch=False)
    return out


def rose_canes(gems):
    """The grown part of the thicket: CANES bramble canes rooted on the boss."""
    rng = np.random.default_rng(CANE_SEED)
    canes = []
    for _ in range(CANES):
        y0 = rng.uniform(138.0, 155.5)
        phi = rng.uniform(0, 2 * np.pi)
        er = np.array([np.cos(phi), 0.0, np.sin(phi)])
        start = er * 2.0 + np.array([0.0, y0, 0.0])
        direction = er + rng.normal(size=3) * 0.5
        canes += grow_cane(rng, start, direction, rng.uniform(14.0, 26.0), rng.uniform(0.7, 0.9), 0.45, gems)
    return canes


def build_thicket(maps, rgb, xs, ys, gems):
    """Sphere centres, radii and colours for every cane and prickle.
    gems: [(gy, radius, boss radius)] for the windows over the gems."""
    from scipy.spatial import KDTree

    res = float(xs[1] - xs[0])
    full = skeleton_points(maps["D_gfull"], xs, ys)
    main = skeleton_points(maps["D_gmain"], xs, ys)
    centres, radii, colours, layer_of, kinds = [], [], [], [], []
    for li, (phi_deg, scale, tilt_deg, seed) in enumerate(THICKET):
        rng = np.random.default_rng(seed)
        pts = full if phi_deg == 0 else main
        p1, p2, p3 = rng.uniform(0, 2 * np.pi, 3)
        phi, tau = np.radians(phi_deg), np.radians(tilt_deg)

        def place(x, y, phi=phi, tau=tau, scale=scale, p1=p1, p2=p2, p3=p3, front=(phi_deg == 0)):
            dy = y - GUARD_Y
            x2 = scale * (x * np.cos(tau) - dy * np.sin(tau))
            y2 = GUARD_Y + scale * (x * np.sin(tau) + dy * np.cos(tau))
            amp = WEAVE * sm.smoothstep(2.5, 9.0, np.abs(x2))
            if front:   # the painted copy stays in its plane where it holds the collar
                amp = amp * sm.smoothstep(132.0, 142.0, y2)
            w = amp * (np.sin(0.42 * x2 + p1) * np.cos(0.37 * (y2 - GUARD_Y) + p2)
                       + 0.45 * np.sin(0.8 * x2 - 0.6 * y2 + p3))
            return np.stack([x2 * np.cos(phi) - w * np.sin(phi), y2, x2 * np.sin(phi) + w * np.cos(phi)], -1)

        canes = thin_out(pts)
        c3 = place(canes[:, 0], canes[:, 1])
        ix = np.clip(np.round((canes[:, 0] - xs[0]) / res).astype(int), 0, len(xs) - 1)
        iy = np.clip(np.round((canes[:, 1] - ys[0]) / res).astype(int), 0, len(ys) - 1)
        centres.append(c3)
        radii.append(canes[:, 2] * scale)
        colours.append(rgb[iy, ix])
        layer_of.append(np.full(len(c3), li))
        kinds.append(np.zeros(len(c3), bool))

        # prickles: every PRICKLE_SPACING along the thinner canes
        tree = KDTree(pts[:, :2])
        sites: list[np.ndarray] = []
        for q in canes[(canes[:, 2] >= 0.45) & (canes[:, 2] <= 1.35)][rng.permutation(
                int(((canes[:, 2] >= 0.45) & (canes[:, 2] <= 1.35)).sum()))]:
            if all(np.hypot(*(q[:2] - s_[:2])) >= PRICKLE_SPACING for s_ in sites[-400:]):
                sites.append(q)
        normal = np.array([-np.sin(phi), 0.0, np.cos(phi)])
        for q in sites:
            nb = pts[tree.query_ball_point(q[:2], 0.7), :2]
            if len(nb) < 3:
                continue
            t2 = np.linalg.svd(nb - nb.mean(0), full_matrices=False)[2][0]
            a = place(np.array([q[0]]), np.array([q[1]]))[0]
            b = place(np.array([q[0] + 0.2 * t2[0]]), np.array([q[1] + 0.2 * t2[1]]))[0]
            tan = (b - a) / (np.linalg.norm(b - a) + 1e-9)
            n2 = np.cross(tan, normal)
            n2 /= np.linalg.norm(n2) + 1e-9
            th = rng.uniform(0, 2 * np.pi)
            d = np.cos(th) * normal + np.sin(th) * n2 + np.array([0.0, -0.3, 0.0])
            d /= np.linalg.norm(d)
            # a rose prickle: broad base, short, hooked toward the blade
            r_cane = q[2] * scale
            length = r_cane + rng.uniform(0.6, 1.0)
            t = np.linspace(0.0, 1.0, 14)[:, None]
            pc = a + length * t * d + 0.5 * (length - r_cane) * t ** 2 * np.array([0.0, -1.0, 0.0])
            rb = float(np.clip(0.62 * r_cane, 0.32, 0.62))
            centres.append(pc)
            radii.append(rb * (1 - t[:, 0]) ** 1.3 + 0.12 * t[:, 0])   # tip above the 0.1 mm grid
            base_col = rgb[int(np.clip(round((q[1] - ys[0]) / res), 0, len(ys) - 1)),
                           int(np.clip(round((q[0] - xs[0]) / res), 0, len(xs) - 1))]
            colours.append((1 - t) * base_col + t * np.array([0.55, 0.27, 0.17]))
            layer_of.append(np.full(len(pc), li))
            kinds.append(np.ones(len(pc), bool))

    # grown rose canes, coloured olive to bronze with lighter tips, with prickles
    rng = np.random.default_rng(CANE_SEED + 1)
    for ci, (P, Rr, T) in enumerate(rose_canes(gems)):
        mix = rng.uniform()
        base = (1 - mix) * np.array([0.30, 0.34, 0.14]) + mix * np.array([0.42, 0.33, 0.17])
        f_ = np.linspace(0, 1, len(P))[:, None]
        cane_col = (1 - f_) * base + f_ * np.array([0.47, 0.50, 0.23])
        keep_pts = thin_cane(P, Rr)
        centres.append(P[keep_pts])
        radii.append(Rr[keep_pts])
        colours.append(cane_col[keep_pts])
        layer_of.append(np.full(int(keep_pts.sum()), 100 + ci))
        kinds.append(np.zeros(int(keep_pts.sum()), bool))
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
        for at in np.arange(rng.uniform(0.8, 2.0), arc[-1] - 0.6, PRICKLE_SPACING):
            k = int(np.searchsorted(arc, at))
            if Rr[k] < 0.4:
                continue
            pc, pr, pk = prickle(P[k], T[k], Rr[k], rng, cane_col[k])
            centres.append(pc)
            radii.append(pr)
            colours.append(pk)
            layer_of.append(np.full(len(pc), 100 + ci))
            kinds.append(np.ones(len(pc), bool))

    C3 = np.concatenate(centres)
    R = np.concatenate(radii)
    K = np.concatenate(colours)
    L = np.concatenate(layer_of)
    prickle_mask = np.concatenate(kinds)
    # prickles never grow into a gem; canes are left alone, because cutting one
    # can sever a whole arm of a copy
    keep = np.ones(len(C3), bool)
    for gy, a, boss in gems:
        near = np.hypot(C3[:, 0], C3[:, 1] - gy) < a + 0.8
        keep &= ~(prickle_mask & near & (np.abs(C3[:, 2]) > boss - 0.5))
    order = np.argsort(C3[keep, 1], kind="stable")
    return C3[keep][order], R[keep][order], K[keep][order], L[keep][order]


def gem_parts(maps, xs, ys):
    """Domed gems on the front and back of the guard's boss, in gold bezels."""
    out, windows = [], []
    for (gx, gy), a in zip(GEMS, (1.0, 1.45), strict=True):
        j, i = int(np.searchsorted(ys, gy)), int(np.searchsorted(xs, gx))
        boss = min(float(-maps["D_gfull"][j, i]), BOSS_MAX_R)
        windows.append((gy, a, boss))
        for sz in (1.0, -1.0):
            zc = sz * (boss - 0.45 * a)

            def dome(X, Y, Z, gy=gy, a=a, zc=zc):
                return np.sqrt(X ** 2 + (Y - gy) ** 2 + (Z - zc) ** 2) - a

            zb = sz * (boss - 0.1)

            def bezel(X, Y, Z, gy=gy, a=a, zb=zb):
                return np.sqrt((np.hypot(X, Y - gy) - 0.95 * a) ** 2 + (Z - zb) ** 2) - 0.24

            box = (-a - 1.0, a + 1.0, gy - a - 1.0, gy + a + 1.0, min(zc, zb) - a - 1.0, max(zc, zb) + a + 1.0)
            out.append(("union", dome, box, 0.12, (0.80, 0.86, 0.32)))
            out.append(("union", bezel, box, 0.12, (0.66, 0.50, 0.22)))
    return out, windows


class Fields:
    """Every field of the sword on the global lattice, evaluated over index
    boxes: rows (j0, j1), columns (b0, b1), depth samples (k0, k1).

    body: blade and collar as a double-sided heightfield, the thicket of
    canes and prickles as splatted spheres, then the grip, leaf cup, rose,
    loop and gems as 3D parts, and the cuts (loop hole, pin holes)."""

    def __init__(self, D_bc, H, xs, ys, zs, parts, cuts, thicket):
        self.D, self.H, self.xs, self.ys, self.zs = D_bc, H, xs, ys, zs
        self.parts, self.cuts = parts, cuts
        self.tc, self.tr = thicket[0], thicket[1]
        self.r_max = float(self.tr.max()) if len(self.tr) else 0.0

    def _boxes(self, items, ry, rx, rz):
        for kind, fn, box, k in items:
            a0, a1 = irange(self.ys, box[2], box[3])
            b0, b1 = irange(self.xs, box[0], box[1])
            c0, c1 = irange(self.zs, box[4], box[5])
            a0, a1 = max(a0, ry[0]), min(a1, ry[1])
            b0, b1 = max(b0, rx[0]), min(b1, rx[1])
            c0, c1 = max(c0, rz[0]), min(c1, rz[1])
            if a0 < a1 and b0 < b1 and c0 < c1:
                yield kind, fn, k, (a0, a1, b0, b1, c0, c1)

    def thicket(self, ry, rx, rz, margin=0.6):
        (j0, j1), (b0, b1), (k0, k1) = ry, rx, rz
        T = np.full((j1 - j0, b1 - b0, k1 - k0), 5.0, np.float32)
        pad = self.r_max + margin
        lo, hi = np.searchsorted(self.tc[:, 1], [self.ys[j0] - pad, self.ys[j1 - 1] + pad])
        c, r = self.tc[lo:hi], self.tr[lo:hi]
        inside = ((c[:, 0] > self.xs[b0] - pad) & (c[:, 0] < self.xs[b1 - 1] + pad)
                  & (c[:, 2] > self.zs[k0] - pad) & (c[:, 2] < self.zs[k1 - 1] + pad))
        if inside.any():
            sm.splat_spheres(T, self.xs[b0:b1], self.ys[j0:j1], self.zs[k0:k1], c[inside], r[inside], margin)
        return T

    def body(self, ry, rx, rz, cuts=True):
        (j0, j1), (b0, b1), (k0, k1) = ry, rx, rz
        absz = np.abs(self.zs[k0:k1])[None, None, :]
        F = np.maximum(self.D[j0:j1, b0:b1, None], absz - self.H[j0:j1, b0:b1, None]).astype(np.float32)
        F = sm.smin(F, self.thicket(ry, rx, rz), THICKET_JOIN).astype(np.float32)
        items = self.parts + (self.cuts if cuts else [])
        for kind, fn, k, (a0, a1, c_b0, c_b1, c0, c1) in self._boxes(items, ry, rx, rz):
            sub = F[a0 - j0:a1 - j0, c_b0 - b0:c_b1 - b0, c0 - k0:c1 - k0]
            val = fn(self.xs[c_b0:c_b1][None, :, None], self.ys[a0:a1][:, None, None],
                     self.zs[c0:c1][None, None, :])
            sub[...] = sm.smin(sub, val, k) if kind == "union" else np.maximum(sub, -val)
        return F


def full_sword(f: Fields, ry, rx, rz):
    return f.body(ry, rx, rz)


def zneed_rows(f: Fields, maps, margin=0.6):
    """Depth (|z|) each lattice row needs: the blade and collar, the thicket
    spheres that reach the row, and the 3D parts."""
    need = np.where(maps["D_bc"] < 0, f.H, 0.0).max(axis=1)
    res = float(f.ys[1] - f.ys[0])
    for (_cx, cy, cz), r in zip(f.tc, f.tr, strict=True):
        j0, j1 = int((cy - r - f.ys[0]) / res), int((cy + r - f.ys[0]) / res) + 2
        j0, j1 = max(j0, 0), min(j1, len(need))
        need[j0:j1] = np.maximum(need[j0:j1], abs(cz) + r)
    for _, _, box, _ in f.parts + f.cuts:
        a0, a1 = irange(f.ys, box[2], box[3])
        need[a0:a1] = np.maximum(need[a0:a1], max(abs(box[4]), abs(box[5])))
    return need + margin


def mesh_piece(f: Fields, combine, xr, yr, zr, zneed=None):
    """Mesh combine(f, ry, rx, rz) over the global index box xr, yr, zr. With
    zneed, each slab samples only the depth its rows need."""
    (b0, b1), (jy0, jy1), (kz0, kz1) = xr, yr, zr

    def field(j0, j1, k0=0, k1=None):
        k1 = (kz1 - kz0) if k1 is None else k1
        return combine(f, (jy0 + j0, jy0 + j1), (b0, b1), (kz0 + k0, kz0 + k1))

    def zb(j0, j1):
        assert zneed is not None
        lim = float(zneed[jy0 + j0:jy0 + j1].max())
        k0, k1 = irange(f.zs, -lim, lim)
        return max(k0, kz0) - kz0, min(k1, kz1) - kz0

    return sm.mesh_from_field(field, f.xs[b0:b1], f.ys[jy0:jy1], f.zs[kz0:kz1], slab=96,
                              zbounds=zb if zneed is not None else None)


# ---------------------------------------------------------------- preview

def delight(rgb, maps):
    """The painting carries its own highlights and a render adds real ones.
    In the guard, each colour becomes a saturation-weighted local average, so
    pale highlight streaks take the colour of the vine around them."""
    from skimage.color import rgb2hsv

    w = rgb2hsv(np.clip(rgb, 0, 1))[..., 1] ** 2 + 1e-4
    num = np.stack([ndi.gaussian_filter(rgb[..., c] * w, 5.0) for c in range(3)], -1)
    delit = num / ndi.gaussian_filter(w, 5.0)[..., None]
    g = ndi.gaussian_filter((maps["S"] & ~maps["C"]).astype(float), 2.0)[..., None]
    out = g * delit + (1 - g) * rgb
    # everywhere: cap the paint's brightness (its highlight streaks) and give
    # back a little saturation, so the render's own light does the shading
    from skimage.color import hsv2rgb

    hsv = rgb2hsv(np.clip(out, 0, 1))
    hsv[..., 2] = np.minimum(hsv[..., 2], 0.80)
    hsv[..., 1] = np.clip(hsv[..., 1] * 1.12, 0, 1)
    return hsv2rgb(hsv)


def preview_glb(mesh, f: Fields, rgb, thicket_colours, path: Path, colors: dict):
    """Vertex-coloured GLB for the Console viewer and the renders: blade and
    collar take the painting's colours, each cane and prickle the colour it
    was built with, the 3D parts their part colour. Written Y-up as glTF
    expects; the viewer turns it back to lie flat."""
    import trimesh
    from scipy.spatial import KDTree

    xs, ys = f.xs, f.ys
    V = np.asarray(mesh.vertices)
    res = xs[1] - xs[0]
    ix = np.clip(np.round((V[:, 0] - xs[0]) / res).astype(int), 0, len(xs) - 1)
    iy = np.clip(np.round((V[:, 1] - ys[0]) / res).astype(int), 0, len(ys) - 1)
    col = rgb[iy, ix].copy()
    best = np.abs(np.maximum(f.D[iy, ix], np.abs(V[:, 2]) - f.H[iy, ix]))
    if len(f.tc):
        dq, iq = KDTree(f.tc).query(V, k=8)
        dist = np.asarray(dq).reshape(len(V), 8)
        idx = np.asarray(iq, dtype=np.int64).reshape(len(V), 8)
        g = dist - f.tr[idx]
        pick = np.argmin(g, axis=1)
        rows = np.arange(len(V))
        ft = np.abs(g[rows, pick])
        win = ft < best
        col[win] = thicket_colours[idx[rows, pick]][win]
        best = np.minimum(best, ft)
    X, Y, Z = V[:, 0], V[:, 1], V[:, 2]
    for fn, c in colors.items():
        fv = np.abs(fn(X, Y, Z))
        win = fv < best
        shade = 1.0
        if fn is rose:
            shade = 0.72 + 0.28 * np.clip((Y - ROSE_Y) / 10.0, 0, 1)[:, None]
        col = np.where(win[:, None], np.array(c)[None, :] * shade, col)
        best = np.minimum(best, fv)
    # glTF vertex colours are linear; the painting is sRGB
    col = np.clip(col, 0, 1)
    lin = np.where(col <= 0.04045, col / 12.92, ((col + 0.055) / 1.055) ** 2.4)
    rgba = np.concatenate([lin * 255, np.full((len(V), 1), 255)], 1).astype(np.uint8)
    for fn, c in OVERRIDES.items():
        on = np.abs(fn(X, Y, Z)) < 0.08
        cl = np.clip(np.array(c), 0, 1)
        lc = np.where(cl <= 0.04045, cl / 12.92, ((cl + 0.055) / 1.055) ** 2.4)
        rgba[on, :3] = (lc * 255).astype(np.uint8)
    yup = np.stack([V[:, 0], V[:, 2], -V[:, 1]], 1)
    m = trimesh.Trimesh(yup, np.asarray(mesh.faces), vertex_colors=rgba, process=False)
    m.export(str(path))
    _matte(path)


def _matte(path: Path):
    """glTF defaults metalness to 1, which renders black without an
    environment map. Rewrite the GLB's materials as matte."""
    data = path.read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + jlen])
    mats = doc.setdefault("materials", [{}])
    for m in mats:
        pbr = m.setdefault("pbrMetallicRoughness", {})
        pbr["metallicFactor"] = 0.05
        pbr["roughnessFactor"] = 0.62
        pbr.pop("baseColorTexture", None)
        pbr["baseColorFactor"] = [1, 1, 1, 1]
    for mesh in doc.get("meshes", []):
        for prim in mesh.get("primitives", []):
            prim.setdefault("material", 0)
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    rest = data[20 + jlen:]
    total = 12 + 8 + len(js) + len(rest)
    out = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + rest
    path.write_bytes(out)


# -------------------------------------------------------------------- main

def main(params: dict, out_dir: Path, name: str):

    P = dict(DEFAULTS)
    P.update(params)
    res = float(P["res"])
    out_dir.mkdir(parents=True, exist_ok=True)
    dbg = out_dir / "analysis"
    dbg.mkdir(exist_ok=True)
    if not REF.exists():
        raise SystemExit(f"missing reference art: {REF} (see models/snicker_snack/README.md)")

    t0 = time.time()
    img, fg, solid = trace_art()
    axis = fit_axis(fg)
    xs, ys, zs = sm.lattice((-24.0, 24.0), (-1.0, 197.6), (-24.0, 24.0), res)
    mask, rgb, scale = resample(img, solid, axis, xs, ys)
    log(f"art traced: {scale:.4f} mm per pixel, lattice {len(xs)} x {len(ys)} x {len(zs)}")
    D, H, maps = design_2d(mask, rgb, xs, ys, res)
    debug_maps(D, H, maps, dbg)
    log(f"2D design done in {time.time() - t0:.1f}s; maps in {dbg}")
    if P["stage"] == "2d":
        return None

    if P["variant"] in ("kit", "halves"):
        # A plane through a 3D thicket leaves loose arcs of cane in each half
        # (measured: four per half, one of them 8 mm of guard), so there is no
        # support-free split. Print the one piece in resin.
        raise SystemExit("snicker_snack: the thorn thicket does not split into connected halves; "
                         "build the one piece and print it in resin (or FDM with tree supports)")
    paint = delight(rgb, maps)
    gems, windows = gem_parts(maps, xs, ys)
    t1 = time.time()
    tc, tr, tk, tl = build_thicket(maps, paint, xs, ys, windows)
    log(f"thicket: {len(tc):,} spheres in {len(THICKET)} turned copies of the painted guard "
        f"({time.time() - t1:.1f}s)")
    parts = PARTS + [(kind, fn, box, k) for kind, fn, box, k, _ in gems]
    colors = dict(COLORS)
    colors.update({fn: c for _, fn, _, _, c in gems})
    f = Fields(maps["D_bc"], H, xs, ys, zs, parts, CUTS, (tc, tr))
    t1 = time.time()
    m = mesh_piece(f, full_sword, (0, len(xs)), (0, len(ys)), (0, len(zs)), zneed_rows(f, maps))
    log(f"marching cubes: {len(m.faces):,} faces in {time.time() - t1:.1f}s")
    sword = sm.ensure_closed(sm.decimate(m, int(P["faces"])))
    meshes = {"sword": sword}
    pv = sm.ensure_closed(sm.decimate(sword, int(P["preview_faces"])))
    preview_glb(pv, f, paint, tk, out_dir / f"{name}_preview.glb", colors)
    log(f"preview {out_dir / (name + '_preview.glb')} ({len(pv.faces):,} faces)")
    log(f"total {time.time() - t0:.1f}s")
    return meshes


_G = globals()
if _G.get("__name__") == "__cad__":
    result = main(dict(_G.get("PARAMS") or {}), Path(_G["OUT_DIR"]), str(_G["NAME"]))
elif __name__ == "__main__":
    main(dict(a.split("=", 1) for a in sys.argv[1:]), ROOT / "out" / "snicker_snack", "snicker_snack")
