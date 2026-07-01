#!/usr/bin/env python3
"""
Render a line-by-line lyric video by compositing PIL-drawn text sprites over a
still background, one line at a time with fade in/out, and piping raw frames to
ffmpeg for H.264 + AAC encoding. Sidesteps the need for a libass/drawtext ffmpeg.

Usage: render_video.py <background.png> <timings.json> <audio> <out.mp4>
"""
import sys, json, subprocess, textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BG, TIMINGS, AUDIO, OUT = sys.argv[1:5]

FPS        = 24
W, H       = 1920, 1080
MAXW       = 1600            # text wrap width in px
MARGIN_BOT = 118            # gap from block bottom to frame bottom
FONT_PATH  = "/System/Library/Fonts/Supplemental/Iowan Old Style.ttc"
SIZE       = 87
SIZE_FIN   = 100
STROKE     = 4
FILL       = (242, 246, 255)
FILL_FIN   = (212, 175, 55)   # #D4AF37 metallic gold for the finale
STROKE_CLR = (18, 10, 4)
LINE_SP    = 1.10

font      = ImageFont.truetype(FONT_PATH, SIZE, index=0)        # Iowan Roman
font_fin  = ImageFont.truetype(FONT_PATH, SIZE_FIN, index=1)   # Iowan Bold for finale

def wrap(text, fnt):
    """Greedy word-wrap to MAXW using real glyph metrics."""
    words, rows, cur = text.split(), [], ""
    scratch = Image.new("RGB", (10, 10))
    d = ImageDraw.Draw(scratch)
    for w in words:
        trial = (cur + " " + w).strip()
        wpx = d.textbbox((0, 0), trial, font=fnt, stroke_width=STROKE)[2]
        if wpx <= MAXW or not cur:
            cur = trial
        else:
            rows.append(cur); cur = w
    if cur:
        rows.append(cur)
    return rows

def render_sprite(text, finale):
    fnt = font_fin if finale else font
    fill = FILL_FIN if finale else FILL
    rows = wrap(text, fnt)
    asc, desc = fnt.getmetrics()
    row_h = int((asc + desc) * LINE_SP)
    scratch = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    row_w = [scratch.textbbox((0, 0), r, font=fnt, stroke_width=STROKE)[2] for r in rows]
    bw = max(row_w) + 2 * STROKE + 4
    bh = row_h * len(rows) + 2 * STROKE + 4
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, r in enumerate(rows):
        x = (bw - row_w[i]) // 2
        y = STROKE + i * row_h
        d.text((x, y), r, font=fnt, fill=fill,
               stroke_width=STROKE, stroke_fill=STROKE_CLR)
    arr = np.asarray(img).astype(np.float32)         # bh,bw,4
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3:4] / 255.0                   # bh,bw,1
    px = (W - bw) // 2
    py = (H - MARGIN_BOT) - bh
    return {"rgb": rgb, "alpha": alpha, "x": px, "y": py, "w": bw, "h": bh}

# ---- load timing + assets ----
tj = json.load(open(TIMINGS))
fade = tj["fade"]
sprites = []
for ln in tj["lines"]:
    sp = render_sprite(ln["text"], ln["finale"])
    sp["start"] = ln["start"]; sp["end"] = ln["end"]
    sprites.append(sp)
sprites.sort(key=lambda s: s["start"])

bg = np.asarray(Image.open(BG).convert("RGB")).astype(np.uint8)  # H,W,3
bg_bytes = bg.tobytes()

# audio duration -> frame count
dur = float(subprocess.check_output(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
     "-of", "default=noprint_wrappers=1:nokey=1", AUDIO]).strip())
nframes = int(round(dur * FPS))

def alpha_at(sp, t):
    if t < sp["start"] or t > sp["end"]:
        return 0.0
    fin = (t - sp["start"]) / fade if fade > 0 else 1.0
    fout = (sp["end"] - t) / fade if fade > 0 else 1.0
    return max(0.0, min(1.0, fin, fout))

ff = subprocess.Popen(
    ["ffmpeg", "-y", "-loglevel", "error",
     "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
     "-i", AUDIO,
     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
     "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", OUT],
    stdin=subprocess.PIPE)

ptr = 0
for f in range(nframes):
    t = f / FPS
    while ptr < len(sprites) and sprites[ptr]["end"] < t:
        ptr += 1
    a = 0.0; sp = None
    for j in (ptr, ptr + 1):
        if j < len(sprites):
            aj = alpha_at(sprites[j], t)
            if aj > 0:
                a, sp = aj, sprites[j]; break
    if sp is None or a <= 0:
        ff.stdin.write(bg_bytes)
        continue
    y, x, h, w = sp["y"], sp["x"], sp["h"], sp["w"]
    frame = bg.copy()
    region = frame[y:y+h, x:x+w].astype(np.float32)
    ea = sp["alpha"] * a
    blended = region * (1 - ea) + sp["rgb"] * ea
    frame[y:y+h, x:x+w] = np.clip(blended, 0, 255).astype(np.uint8)
    ff.stdin.write(frame.tobytes())
    if f % 480 == 0:
        print(f"  frame {f}/{nframes}  ({t:5.1f}s)", flush=True)

ff.stdin.close()
ff.wait()
print("done ->", OUT)
