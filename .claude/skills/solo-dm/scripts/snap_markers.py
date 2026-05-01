#!/usr/bin/env python3
"""Snap each marker to the nearest city-dot blob, rejecting letters in labels.

Key insight: letters in a city-name label appear in a horizontal row of
similarly-sized dark blobs. A real city-dot is isolated and typically more
solid/round. We reject any candidate that has >=2 similar-sized blobs in a
horizontal strip around it.
"""
from __future__ import annotations
import argparse, json, sqlite3, math, sys
from collections import deque
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np

HARNESS_ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = HARNESS_ROOT / "data/solo-dm"

# Filled in main() from --slug + --map args.
MAP_PATH: Path = None  # type: ignore
DB_PATH: Path = None   # type: ignore

WIN_HALF   = 90
DARK_THR   = 105
MIN_AREA   = 14
MAX_AREA   = 320
MAX_ASPECT = 1.8
MIN_FILL   = 0.55
MAX_SNAP   = 85
TEXT_DX = 55
TEXT_DY = 10


def find_blobs(window):
    h, w = window.shape
    dark = window < DARK_THR
    visited = np.zeros_like(dark)
    out = []
    for y in range(h):
        for x in range(w):
            if not dark[y, x] or visited[y, x]:
                continue
            q = deque([(y, x)])
            visited[y, x] = True
            pts = []
            while q:
                yy, xx = q.popleft()
                pts.append((yy, xx))
                for dy, dx in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
                    ny, nx = yy+dy, xx+dx
                    if 0 <= ny < h and 0 <= nx < w and dark[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        q.append((ny, nx))
            area = len(pts)
            if area < 4 or area > 2000:
                continue
            ys = [p[0] for p in pts]; xs = [p[1] for p in pts]
            bw = max(xs) - min(xs) + 1
            bh = max(ys) - min(ys) + 1
            cx = sum(xs) / area; cy = sum(ys) / area
            out.append({
                'cx': cx, 'cy': cy, 'area': area,
                'bw': bw, 'bh': bh,
                'aspect': max(bw, bh) / max(1, min(bw, bh)),
                'fill': area / (bw * bh),
            })
    return out


def is_in_text_line(blob, all_blobs):
    near = 0
    for other in all_blobs:
        if other is blob: continue
        if abs(other['cy'] - blob['cy']) > TEXT_DY: continue
        if abs(other['cx'] - blob['cx']) > TEXT_DX: continue
        if other['area'] < blob['area'] * 0.25: continue
        if other['area'] > blob['area'] * 4.0: continue
        near += 1
        if near >= 2:
            return True
    return False


def score_candidate(blob, wcx, wcy):
    dist = math.hypot(blob['cx'] - wcx, blob['cy'] - wcy)
    dist_score = max(0, 1 - dist / MAX_SNAP)
    a = blob['area']
    if a < 20: area_score = a / 20.0 * 0.6
    elif a <= 100: area_score = 1.0
    else: area_score = max(0.2, 1 - (a - 100) / 400)
    aspect_score = max(0, 1 - (blob['aspect'] - 1.0) / 0.8)
    return dist_score * 1.8 + area_score * 0.6 + blob['fill'] * 0.6 + aspect_score * 0.4


def main():
    global MAP_PATH, DB_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, help="Campaign slug (subdir of data/solo-dm/)")
    ap.add_argument("--map", required=True, help="Path to map image (jpg/png/webp)")
    args = ap.parse_args()
    MAP_PATH = Path(args.map).expanduser()
    DB_PATH = DATA_ROOT / args.slug / "state.sqlite"
    if not MAP_PATH.exists():
        sys.exit(f"map image not found: {MAP_PATH}")
    if not DB_PATH.exists():
        sys.exit(f"no db for slug {args.slug!r}")

    im_full = Image.open(MAP_PATH)
    arr = np.asarray(im_full.convert('L'))
    H, W = arr.shape
    conn = sqlite3.connect(DB_PATH)
    markers = json.loads(conn.execute("SELECT value FROM world_state WHERE key='map_markers'").fetchone()[0])

    vis = im_full.convert('RGB').copy()
    draw = ImageDraw.Draw(vis, 'RGBA')
    try: font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 18)
    except: font = ImageFont.load_default()

    updated = []; n_snap = n_skip = 0
    for m in markers:
        if m.get('kind') == 'region':
            updated.append(m); n_skip += 1; continue
        px = int(m['x'] * W); py = int(m['y'] * H)
        x0 = max(0, px-WIN_HALF); y0 = max(0, py-WIN_HALF)
        x1 = min(W, px+WIN_HALF+1); y1 = min(H, py+WIN_HALF+1)
        win = arr[y0:y1, x0:x1]
        all_blobs = find_blobs(win)
        candidates = []
        for b in all_blobs:
            if b['area'] < MIN_AREA or b['area'] > MAX_AREA: continue
            if b['aspect'] > MAX_ASPECT: continue
            if b['fill'] < MIN_FILL: continue
            if is_in_text_line(b, all_blobs): continue
            candidates.append(b)
        wcx = px - x0; wcy = py - y0
        best = None; best_score = -1e9
        for b in candidates:
            dist = math.hypot(b['cx']-wcx, b['cy']-wcy)
            if dist > MAX_SNAP: continue
            s = score_candidate(b, wcx, wcy)
            if s > best_score:
                best_score = s; best = b
        if best is None:
            draw.ellipse([px-6, py-6, px+6, py+6], outline=(200,0,0,255), width=2)
            updated.append(m); n_skip += 1
            print(f'  (no dot) {m["label"]:22} ({len(candidates)} cand, {len(all_blobs)} blobs)')
            continue
        new_px = x0 + best['cx']; new_py = y0 + best['cy']
        dx = new_px - px; dy = new_py - py
        draw.line([(px, py), (new_px, new_py)], fill=(255,255,0,255), width=2)
        draw.ellipse([new_px-7, new_py-7, new_px+7, new_py+7], outline=(0,255,0,255), width=3)
        m2 = dict(m); m2['x'] = round(new_px / W, 4); m2['y'] = round(new_py / H, 4)
        updated.append(m2); n_snap += 1
        print(f'  ~ {m["label"]:22} d=({dx:+.0f},{dy:+.0f}) area={best["area"]} fill={best["fill"]:.2f}')

    print(f'\nSnapped {n_snap}, kept {n_skip}')
    for name, (fx0,fy0,fx1,fy1) in [('NW',(0,0,0.5,0.5)),('NE',(0.5,0,1,0.5)),
                                     ('SW',(0,0.5,0.5,1)),('SE',(0.5,0.5,1,1))]:
        c = vis.crop((int(fx0*W), int(fy0*H), int(fx1*W), int(fy1*H)))
        c.thumbnail((1800,1800))
        c.save(f'/tmp/snap3-{name}.png')

    cid = conn.execute('SELECT id FROM campaigns LIMIT 1').fetchone()[0]
    conn.execute(
        "INSERT INTO world_state (campaign_id, key, value) VALUES (?,?,?) "
        "ON CONFLICT(campaign_id, key) DO UPDATE SET value=excluded.value, "
        "updated_at=datetime('now')",
        (cid, 'map_markers', json.dumps(updated)),
    )
    conn.commit()


if __name__ == '__main__':
    main()
