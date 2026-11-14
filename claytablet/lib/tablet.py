#!/usr/bin/env python3
"""claytablet: render lines of Unicode cuneiform as a clay tablet under raking light.

The tablet is a height field: a pillow-shaped body, ruled lines, wedges pressed
in from a cuneiform font (depth from a distance transform, so the head of each
wedge is the deepest point), wear, pits, cracks, breaks, and an optional stamp
impression. The height field is lit with one directional light, marched
shadows and a cavity term. No image model and no photo is used.

Returns the lit picture, an alpha matte, the shadow that the tablet throws on
the ground, and the height field (for an STL).
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi


def _noise(shape, rng, cell):
    """Smooth unit-variance noise with features of about `cell` pixels."""
    h, w = shape
    gh, gw = max(4, int(h / cell) + 4), max(4, int(w / cell) + 4)
    g = rng.standard_normal((gh, gw)).astype(np.float32)
    z = np.asarray(ndi.zoom(g, (h / (gh - 3), w / (gw - 3)), order=3))[:h, :w]
    if z.shape != (h, w):
        z = np.pad(z, ((0, h - z.shape[0]), (0, w - z.shape[1])), mode="edge")
    return (z - z.mean()) / (z.std() + 1e-6)


def _fbm(shape, rng, cell, octaves=4, gain=0.5):
    out = np.zeros(shape, np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        out += amp * _noise(shape, rng, max(2.0, cell / (2 ** o)))
        tot += amp
        amp *= gain
    return out / tot


def _smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def layout_text(lines, font_path, W, H, top, pitch, margin, rng, embolden=0.02,
                size_factor=0.66, max_squeeze=0.62):
    """Rasterize the lines to a float mask in [0,1]. Returns (mask, line_ys, slopes)."""
    mask = np.zeros((H, W), np.float32)
    probe = ImageFont.truetype(font_path, 200)
    sample = [s for l in lines for s in l if s != " "]
    boxes = [probe.getbbox(s) for s in sample]
    tops = np.array([b[1] for b in boxes], np.float32); bots = np.array([b[3] for b in boxes], np.float32)
    ink_h = float(np.median(bots - tops)) / 200.0          # ink height per em
    ink_c = float(np.median((bots + tops) / 2)) / 200.0    # ink centre per em, from the draw origin
    fsize = int(pitch * size_factor / ink_h)
    font = ImageFont.truetype(font_path, fsize)
    stroke = max(0, int(round(fsize * embolden)))
    avail = W - 2 * margin
    line_ys, slopes = [], []
    for li, line in enumerate(lines):
        y0 = top + li * pitch + pitch * 0.5 - ink_c * fsize   # draw origin that centres the ink
        slope = rng.normal(0, 0.004)            # lines are not level
        line_ys.append(top + li * pitch)
        slopes.append(slope)
        if not line.strip():
            continue
        words = [list(w) for w in line.split(" ") if w]
        signs = [s for w in words for s in w]
        adv = [font.getlength(s) for s in signs]
        gap = fsize * 0.035
        natural = sum(adv) + gap * (len(signs) - 1)
        sx = min(1.0, avail / natural) if natural > avail else 1.0
        sx = max(sx, max_squeeze)
        adv_s = [a * sx for a in adv]
        natural_s = sum(adv_s) + gap * (len(signs) - 1)
        # positions
        xs = []
        if natural_s >= avail or len(signs) == 1:
            x = margin
            for a in adv_s:
                xs.append(x); x += a + gap
            if natural_s > avail:                 # run over the right edge a little, as scribes did
                over = natural_s - avail
                xs = [x - over * 0.25 for x in xs]
        elif natural_s < 0.60 * avail and len(signs) <= 5:
            # short line: first sign left, last sign right, the rest spread between
            free = avail - sum(adv_s)
            step = free / (len(signs) - 1)
            x = margin
            for a in adv_s:
                xs.append(x); x += a + step
        else:
            # justify between words, signs in a word stay close
            nw = len(words)
            free = avail - natural_s
            wgap = free / (nw - 1) if nw > 1 else 0
            wgap = min(wgap, fsize * 1.6)
            x = margin
            k = 0
            for w in words:
                for _ in w:
                    xs.append(x); x += adv_s[k] + gap; k += 1
                x += wgap
            # push the last word to the right edge
            if nw > 1:
                last_n = len(words[-1])
                width_last = sum(adv_s[-last_n:]) + gap * (last_n - 1)
                start = margin + avail - width_last
                x = start
                for j in range(len(signs) - last_n, len(signs)):
                    xs[j] = x; x += adv_s[j] + gap
        # draw sign by sign with jitter
        for s, x, a in zip(signs, xs, adv_s, strict=True):
            pad = int(fsize * 0.5)
            gw, gh = int(a / sx + 2 * pad) + 2, int(fsize * 1.6 + 2 * pad)
            g = Image.new("L", (gw, gh), 0)
            ImageDraw.Draw(g).text((pad, pad), s, font=font, fill=255,
                                   stroke_width=stroke, stroke_fill=255)
            sc = 1.0 + rng.normal(0, 0.025)
            g = g.resize((max(2, int(gw * sx * sc)), max(2, int(gh * sc))), Image.Resampling.LANCZOS)
            g = g.rotate(rng.normal(0, 1.1), resample=Image.Resampling.BICUBIC, expand=False)
            ga = np.asarray(g, np.float32) / 255.0
            px = int(round(x - pad * sx * sc))
            py = int(round(y0 + (x - margin) * slope - pad * sc + rng.normal(0, pitch * 0.02)))
            y1, x1 = py + ga.shape[0], px + ga.shape[1]
            cy0, cx0 = max(py, 0), max(px, 0)
            cy1, cx1 = min(y1, H), min(x1, W)
            if cy1 <= cy0 or cx1 <= cx0:
                continue
            sub = ga[cy0 - py:cy1 - py, cx0 - px:cx1 - px]
            np.maximum(mask[cy0:cy1, cx0:cx1], sub, out=mask[cy0:cy1, cx0:cx1])
    return mask, line_ys, slopes, fsize


def render_face(lines, font_path, face_w=1000, aspect=2.32, pad=None, seed=1,
                n_rows=None, light=(-0.62, -0.62, 0.48), stamp=None, stamp_pos=(0.5, 0.80),
                stamp_diam=0.60, stamp_angle=-9.0, breaks=(), chips=(), crack=True, nicks=6,
                clay=(0.86, 0.765, 0.61), embolden=0.045, wear_amount=0.5,
                rulings=True, text_top=0.035):
    """Render one face. Sizes are in pixels; face_w is the tablet width."""
    rng = np.random.default_rng(seed)
    Wt, Ht = int(face_w), int(face_w * aspect)
    pad = int(face_w * 0.20) if pad is None else int(pad)
    W, H = Wt + 2 * pad, Ht + 2 * pad
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx, cy = W / 2, H / 2

    # ---- outline: rounded rectangle with an irregular edge and chips
    r = Wt * 0.085
    qx = np.abs(xx - cx) - (Wt / 2 - r)
    qy = np.abs(yy - cy) - (Ht / 2 - r)
    sdf = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
    sdf += Wt * 0.0045 * _noise((H, W), rng, Wt * 0.40) + Wt * 0.0018 * _noise((H, W), rng, Wt * 0.09) \
        + Wt * 0.0011 * _noise((H, W), rng, Wt * 0.022)
    chips = list(chips)
    for _ in range(nicks):                            # shallow flakes off the edge, longer than deep
        side = int(rng.integers(0, 4)); tpos = rng.uniform(0.06, 0.94)
        ux, uy = [(tpos, 0.0), (tpos, 1.0), (0.0, tpos), (1.0, tpos)][side]
        px, py = pad + ux * Wt, pad + uy * Ht
        along, deep = Wt * rng.uniform(0.025, 0.07), Wt * rng.uniform(0.006, 0.013)
        ax, ay = (along, deep) if side < 2 else (deep, along)
        blob = np.hypot((xx - px) / ax, (yy - py) / ay) + 0.35 * _noise((H, W), rng, Wt * 0.012)
        sdf = np.maximum(sdf, (1.0 - blob) * deep)
    for (ux, uy, rad) in chips:                       # chips: fractions of the face
        px, py = pad + ux * Wt, pad + uy * Ht
        blob = np.hypot(xx - px, yy - py) / (rad * Wt)
        blob += 0.25 * _noise((H, W), rng, Wt * 0.05)
        sdf = np.maximum(sdf, (1.0 - blob) * rad * Wt)
    inside = sdf < 0
    d = np.where(inside, -sdf, 0).astype(np.float32)   # distance to the edge, inside

    # ---- body
    R = Wt * (0.118 + 0.028 * _noise((H, W), rng, Wt * 0.5))
    t = np.clip(d / R, 0, 1)
    z = R * np.sqrt(np.clip(1 - (1 - t) ** 2, 0, 1))
    u = (xx - cx) / (Wt / 2); v = (yy - cy) / (Ht / 2)
    z += Wt * 0.035 * np.clip(1 - u * u, 0, 1) * np.clip(1 - v * v * v * v, 0, 1)
    z += Wt * 0.0055 * _fbm((H, W), rng, Wt * 0.45, 3)          # slow undulation
    z *= inside

    # ---- text
    rows = n_rows or len(lines)
    top = pad + Ht * text_top
    usable = Ht * (1 - 2 * text_top)
    pitch = usable / max(rows, 1)
    margin = pad + Wt * 0.045
    tmask_full = np.zeros((H, W), np.float32)
    tm, line_ys, slopes, fsize = layout_text(lines, font_path, W, H, top + pitch * 0.02, pitch,
                                            margin, rng, embolden=embolden)
    tmask_full = tm
    slope_w = 2.3
    dmax = pitch * 0.21
    edt = np.asarray(ndi.distance_transform_edt(tmask_full > 0.42), np.float32)
    wedge = np.minimum(edt * slope_w, dmax)
    wedge = ndi.gaussian_filter(wedge, 0.9)

    # ---- rulings
    rule = np.zeros((H, W), np.float32)
    if rulings:
        for li, (y0, sl) in enumerate(zip(line_ys, slopes, strict=True)):
            if li == 0:
                continue
            yline = y0 + (xx - margin) * sl + pitch * 0.015 * np.sin(xx / Wt * 9 + li)
            band = np.exp(-((yy - yline) ** 2) / (2 * (pitch * 0.022) ** 2))
            fade = 0.55 + 0.45 * _smoothstep(-0.6, 0.6, _noise((1, W), rng, Wt * 0.2))
            rule = np.maximum(rule, band * fade)
        rule *= pitch * 0.050

    # ---- wear, breaks
    wear = _smoothstep(0.7, 1.9, _fbm((H, W), rng, Wt * 0.28, 3)) * wear_amount
    brk = np.zeros((H, W), np.float32)
    for (ux, uy, rx, ry) in breaks:
        px, py = pad + ux * Wt, pad + uy * Ht
        q = np.hypot((xx - px) / (rx * Wt), (yy - py) / (ry * Wt))
        q += 0.22 * _noise((H, W), rng, Wt * 0.06)
        brk = np.maximum(brk, _smoothstep(1.05, 0.8, q))
    text_depth = wedge * (1 - wear) * (1 - brk)
    rule *= (1 - 0.7 * wear) * (1 - brk)

    # ---- stamp impression
    stamp_depth = np.zeros((H, W), np.float32)
    if stamp is not None:
        dia = int(Wt * stamp_diam)
        st = stamp.convert("RGBA").resize((dia, dia), Image.Resampling.LANCZOS)
        st = st.rotate(stamp_angle, resample=Image.Resampling.BICUBIC)
        sa = np.asarray(st, np.float32) / 255.0
        lum = (0.299 * sa[..., 0] + 0.587 * sa[..., 1] + 0.114 * sa[..., 2]) * sa[..., 3] + (1 - sa[..., 3])
        ink = 1 - lum                                   # dark parts of the seal press deepest
        ink = ndi.gaussian_filter(ink, dia / 250)
        ink *= 0.88 + 0.12 * _noise((dia, dia), rng, dia * 0.06)      # clay does not take a stamp evenly
        sy, sx_ = np.mgrid[0:dia, 0:dia].astype(np.float32)
        rr = np.hypot(sx_ - dia / 2, sy - dia / 2) / (dia / 2)
        disc = _smoothstep(1.0, 0.94, rr)
        tilt = 0.62 + 0.55 * (sx_ / dia) + 0.12 * (sy / dia)        # pressed harder on one side
        tilt = tilt * (0.85 + 0.15 * _noise((dia, dia), rng, dia * 0.22))
        rim = _smoothstep(0.985, 1.0, rr) * _smoothstep(1.075, 1.0, rr)   # clay pushed up round the stamp
        dep = (disc * dia * 0.012 + ink * dia * 0.042) * tilt - rim * dia * 0.0045 * tilt
        px = int(pad + stamp_pos[0] * Wt - dia / 2); py = int(pad + stamp_pos[1] * Ht - dia / 2)
        stamp_depth[py:py + dia, px:px + dia] = dep
        text_depth *= 1 - _smoothstep(0, 0.002 * dia, stamp_depth)

    # ---- small damage: pits and a crack
    pits = np.zeros((H, W), np.float32)
    n_pits = int(Wt * Ht / 14000)
    ys = rng.integers(pad, pad + Ht, n_pits); xs = rng.integers(pad, pad + Wt, n_pits)
    pits[ys, xs] = rng.uniform(0.3, 1.0, n_pits)
    pits = ndi.gaussian_filter(pits, Wt * 0.0022) * (Wt * 0.0022) ** 2 * 6.28
    pits = np.clip(pits, 0, 1) * Wt * 0.006
    crack = np.zeros((H, W), np.float32) if not crack else _crack((H, W), rng, pad, Wt, Ht)

    grain = Wt * 0.00022 * _noise((H, W), rng, 2.2) + Wt * 0.00045 * _noise((H, W), rng, 7) \
        + Wt * 0.0012 * _noise((H, W), rng, Wt * 0.035)
    rough = brk * (Wt * 0.012 + Wt * 0.010 * _fbm((H, W), rng, Wt * 0.03, 3))
    relief = -text_depth - rule - stamp_depth - pits - crack * Wt * 0.012 - rough + grain
    z = np.where(inside, z + relief, 0).astype(np.float32)

    # ---- light
    lx, ly, lz = np.asarray(light, np.float32) / np.linalg.norm(light)
    gy, gx = np.gradient(z)
    nz = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0)
    nx, ny = -gx * nz, -gy * nz
    diff = np.clip(nx * lx + ny * ly + nz * lz, 0, 1)
    # marched shadows
    hmag = float(np.hypot(lx, ly)); ux_, uy_ = lx / hmag, ly / hmag; tan_e = lz / hmag
    hor = np.full((H, W), -1e9, np.float32)
    max_s = int(Wt * 0.42)
    s = 1.0
    while s < max_s:
        dx, dy = int(round(s * ux_)), int(round(s * uy_))
        sh = _shift(z, dx, dy)
        np.maximum(hor, sh - s * tan_e, out=hor)
        s += 1.0 if s < 24 else (2.0 if s < 80 else 4.0)
    shadow = np.clip((hor - z) / (Wt * 0.004), 0, 1)
    shadow = ndi.gaussian_filter(shadow, Wt * 0.0022)
    cav_s = np.clip((ndi.gaussian_filter(z, Wt * 0.006) - z) / (Wt * 0.012), 0, 1)
    cav_l = np.clip((ndi.gaussian_filter(z, Wt * 0.03) - z) / (Wt * 0.04), 0, 1)
    ao = 1 - 0.45 * cav_s - 0.25 * cav_l

    # ---- colour
    base = np.array(clay, np.float32)
    mott = _fbm((H, W), rng, Wt * 0.30, 4)
    fine = _fbm((H, W), rng, Wt * 0.03, 3)
    alb = base[None, None, :] * (1 + 0.055 * mott + 0.035 * fine)[..., None]
    stain = _smoothstep(0.5, 1.6, _fbm((H, W), rng, Wt * 0.22, 3))
    alb *= 1 - stain[..., None] * np.array([0.02, 0.06, 0.13], np.float32)
    alb *= (1 - 0.05 * _noise((H, W), rng, Wt * 0.9))[..., None]            # one end fired darker
    speck = rng.random((H, W)).astype(np.float32)
    alb *= (1 - 0.30 * ndi.gaussian_filter((speck > 0.9992).astype(np.float32), 1.3) * 9)[..., None].clip(0.55, 1)
    alb += (0.10 * ndi.gaussian_filter((speck < 0.0007).astype(np.float32), 1.6) * 12)[..., None].clip(0, 0.12)
    dirt = np.clip(cav_s * 1.2, 0, 1)
    alb *= 1 - dirt[..., None] * np.array([0.16, 0.24, 0.36], np.float32)
    alb = np.where(brk[..., None] > 0.5, alb * np.array([1.04, 1.02, 0.98], np.float32), alb)
    key = np.array([1.0, 0.965, 0.90], np.float32) * 0.86
    amb = np.array([0.40, 0.42, 0.46], np.float32)
    lit = alb * (amb[None, None, :] * ao[..., None] + key[None, None, :] * (diff * (1 - 0.88 * shadow))[..., None])
    hv = np.array([lx, ly, lz + 1.0], np.float32); hv /= np.linalg.norm(hv)
    spec = np.clip(nx * hv[0] + ny * hv[1] + nz * hv[2], 0, 1) ** 24 * 0.035 * (1 - shadow)
    lit += spec[..., None]
    rgb = np.clip(lit, 0, 1) ** (1 / 1.12)

    alpha = _smoothstep(0.8, -0.8, sdf)
    ground_shadow = np.where(inside, 0, shadow).astype(np.float32)
    return {"rgb": rgb, "alpha": alpha.astype(np.float32), "ground_shadow": ground_shadow,
            "z": z, "inside": inside, "pad": pad, "face": (Wt, Ht)}


def _shift(a, dx, dy):
    """Return a shifted by (dx, dy): out[y, x] = a[y + dy, x + dx], zeros outside."""
    H, W = a.shape
    out = np.zeros_like(a)
    ys0, ys1 = max(0, -dy), min(H, H - dy)
    xs0, xs1 = max(0, -dx), min(W, W - dx)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = a[ys0 + dy:ys1 + dy, xs0 + dx:xs1 + dx]
    return out


def _crack(shape, rng, pad, Wt, Ht):
    H, W = shape
    im = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(im)
    x, y = pad + Wt * 0.985, pad + Ht * rng.uniform(0.40, 0.52)
    pts = [(x, y)]
    ang = np.pi + rng.normal(0, 0.2)
    for _ in range(int(rng.integers(9, 14))):
        ang += rng.normal(0, 0.45)
        step = Wt * rng.uniform(0.02, 0.05)
        x += np.cos(ang) * step; y += np.sin(ang) * step * 0.6
        pts.append((x, y))
    dr.line(pts, fill=255, width=max(1, int(Wt * 0.003)))
    c = np.asarray(im, np.float32) / 255.0
    return ndi.gaussian_filter(c, Wt * 0.0012)


def compose(face, bg=(0.105, 0.10, 0.098), shadow_strength=0.72, vignette=0.25, seed=5):
    """Put a rendered face on a plain ground with its shadow. Returns a PIL image."""
    rgb, a, gs = face["rgb"], face["alpha"], face["ground_shadow"]
    H, W = a.shape
    rng = np.random.default_rng(seed)
    g = np.array(bg, np.float32)[None, None, :] * np.ones((H, W, 1), np.float32)
    g *= (1 + 0.05 * _noise((H, W), rng, 3.0))[..., None]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    rad = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2))
    g *= (1 - vignette * np.clip(rad - 0.4, 0, 1))[..., None]
    g *= (1 - shadow_strength * ndi.gaussian_filter(gs, 2.0))[..., None]
    out = rgb * a[..., None] + g * (1 - a[..., None])
    return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))


def scene(faces, tablet_h=1040, margin=0.10, gap=0.14, bg=(0.115, 0.108, 0.104), scale_bar=False,
          width_cm=5.0, seed=3, label_font="/System/Library/Fonts/Helvetica.ttc"):
    """Put rendered faces side by side on dark ground, each with its shadow. Returns a PIL image."""
    rng = np.random.default_rng(seed)
    layers = []
    for f in faces:
        fw, fh = f["face"]
        s = tablet_h / fh
        full_h, full_w = f["alpha"].shape
        nw, nh = int(round(full_w * s)), int(round(full_h * s))

        def small(a, nw=nw, nh=nh):
            im = Image.fromarray((np.clip(a, 0, 1) * 255 + 0.5).astype(np.uint8))
            return np.asarray(im.resize((nw, nh), Image.Resampling.LANCZOS), np.float32) / 255

        layers.append({"rgb": small(f["rgb"]), "a": small(f["alpha"]), "sh": small(f["ground_shadow"]),
                       "w": fw * s, "pad": f["pad"] * s, "size": (nw, nh)})
    tw = layers[0]["w"]
    m, g = tw * margin * 2.2, tw * gap
    W = int(m * 2 + sum(l["w"] for l in layers) + g * (len(layers) - 1))
    bar_room = int(tw * 0.16) if scale_bar else 0
    H = int(tablet_h + m * 2 + bar_room)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    out = np.ones((H, W, 3), np.float32) * np.array(bg, np.float32)
    pool = np.exp(-(((xx - W * 0.42) / (W * 0.75)) ** 2 + ((yy - H * 0.40) / (H * 0.75)) ** 2))
    out *= (0.72 + 0.50 * pool)[..., None]
    out *= (1 + 0.035 * rng.standard_normal((H, W)).astype(np.float32))[..., None]
    x = m
    for l in layers:
        l["x0"], l["y0"] = int(round(x - l["pad"])), int(round(m - l["pad"]))
        x += l["w"] + g
    for l in layers:
        _blend(out, None, ndi.gaussian_filter(l["sh"], 2.5) * 0.80, l["x0"], l["y0"], "shadow")
    for l in layers:
        _blend(out, l["rgb"], l["a"], l["x0"], l["y0"], "over")
    im = Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8))
    if scale_bar:
        cm = tw / width_cm
        n = int(width_cm)
        dr = ImageDraw.Draw(im)
        by, bx, bh = int(m + tablet_h + m * 0.45), int(m), max(8, int(cm * 0.14))
        for i in range(n):
            col = (236, 232, 224) if i % 2 == 0 else (24, 23, 22)
            dr.rectangle([bx + int(i * cm), by, bx + int((i + 1) * cm), by + bh], fill=col)
        dr.rectangle([bx, by, bx + int(n * cm), by + bh], outline=(236, 232, 224), width=2)
        font = ImageFont.truetype(label_font, max(14, int(cm * 0.26)))
        dr.text((bx + int(n * cm) + 12, by + bh / 2), f"{n} cm", font=font, fill=(226, 222, 214), anchor="lm")
    return im


def _blend(out, rgb, a, x0, y0, mode):
    H, W, _ = out.shape
    h, w = a.shape
    ys0, xs0 = max(0, y0), max(0, x0)
    ys1, xs1 = min(H, y0 + h), min(W, x0 + w)
    if ys1 <= ys0 or xs1 <= xs0:
        return
    sub = a[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0][..., None]
    if mode == "shadow":
        out[ys0:ys1, xs0:xs1] *= (1 - sub)
    else:
        out[ys0:ys1, xs0:xs1] = rgb[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0] * sub + out[ys0:ys1, xs0:xs1] * (1 - sub)
