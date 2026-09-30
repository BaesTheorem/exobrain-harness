"""Analysis helpers for cutting a music video from a film: proxy, shot detection,
contact sheets, catalog queries, filmstrips, word timings, beat grids, and review sheets.

Every command works in the current directory (the project folder) and keeps its
outputs under work/.
"""
from __future__ import annotations

import csv
import glob
import json
import os
import re
import subprocess
import sys

import numpy as np

WHISPER_MODEL = os.environ.get(
    "MIST_VID_WHISPER", os.path.expanduser("~/Documents/one-pace/whisper-models/ggml-large-v3-turbo.bin"))
FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def _srt(path: str):
    """[(start, end, text)] from an .srt file."""
    def ts(x):
        h, m, r = x.split(":")
        s, ms = r.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    out = []
    for b in re.split(r"\n\s*\n", open(path, encoding="utf-8-sig").read().strip()):
        lines = b.split("\n")
        if len(lines) >= 3 and "-->" in lines[1]:
            a, z = [ts(v.strip()) for v in lines[1].split("-->")]
            out.append((a, z, re.sub(r"<[^>]+>", "", " ".join(lines[2:]))))
    return out


def proxy(movie: str, out: str = "work/proxy.mp4", width: int = 480):
    """Small frame-exact proxy for fast analysis (hardware decode + encode)."""
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-y", "-hwaccel", "videotoolbox", "-i", movie, "-an", "-sn",
                    "-vf", f"scale={width}:-2:flags=bilinear", "-fps_mode", "passthrough",
                    "-c:v", "h264_videotoolbox", "-b:v", "1200k", "-g", "24", out], check=True)


def shots(proxy_path: str = "work/proxy.mp4", out: str = "work/shots.csv", threshold: float = 3.0):
    """Shot boundaries with PySceneDetect's AdaptiveDetector."""
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import AdaptiveDetector
    v = open_video(proxy_path)
    sm = SceneManager()
    sm.add_detector(AdaptiveDetector(adaptive_threshold=threshold, min_scene_len=6))
    sm.detect_scenes(v, show_progress=False)
    scenes = sm.get_scene_list()
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["shot", "start_frame", "end_frame", "start_s", "end_s", "dur_s"])
        for i, (a, b) in enumerate(scenes):
            w.writerow([i + 1, a.get_frames(), b.get_frames(), f"{a.get_seconds():.3f}", f"{b.get_seconds():.3f}",
                        f"{(b - a).get_seconds():.3f}"])
    print(f"{len(scenes)} shots -> {out}")


def sheets(proxy_path: str = "work/proxy.mp4", shots_csv: str = "work/shots.csv", srt: str | None = None,
           outdir: str = "work/sheets", per: int = 12):
    """Contact sheets (start/mid/end frame per shot) and work/shotlist.json with dialogue snippets.
    Lines with a music note (song lyrics) are left out of the snippets."""
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    rows: list[dict] = [{"shot": int(r["shot"]), "start_frame": int(r["start_frame"]), "end_frame": int(r["end_frame"]),
                         "start_s": float(r["start_s"]), "end_s": float(r["end_s"]), "dur_s": float(r["dur_s"])}
                        for r in csv.DictReader(open(shots_csv))]
    cues = [c for c in _srt(srt) if "♪" not in c[2]] if srt else []
    for s in rows:
        d = [" ".join(c[2].split()[:6]) for c in cues if c[0] < s["end_s"] and c[1] > s["start_s"]]
        s["dlg"] = " / ".join(d)[:120]
    json.dump(rows, open("work/shotlist.json", "w"), indent=0)
    want: dict[int, list] = {}
    for s in rows:
        a, b = s["start_frame"], s["end_frame"] - 1
        for k, f in enumerate((a + (b - a) * 0.12, a + (b - a) * 0.5, a + (b - a) * 0.88)):
            want.setdefault(int(round(f)), []).append((s["shot"], k))
    cap = cv2.VideoCapture(proxy_path)
    frames = {}
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i in want:
            small = cv2.resize(fr, (216, 117), interpolation=cv2.INTER_AREA)
            for sid, k in want[i]:
                frames[(sid, k)] = small
        i += 1
    font = ImageFont.truetype(FONT, 15)
    tw, th, lb, cols, nrows = 216 * 3 + 4, 117, 20, 2, per // 2
    os.makedirs(outdir, exist_ok=True)
    for si in range(0, len(rows), per):
        grp = rows[si:si + per]
        sheet = Image.new("RGB", (cols * tw + (cols - 1) * 12, nrows * (th + lb + 8)), (24, 24, 24))
        dr = ImageDraw.Draw(sheet)
        for j, s in enumerate(grp):
            cx, cy = (j % cols) * (tw + 12), (j // cols) * (th + lb + 8)
            m, sec = divmod(s["start_s"], 60)
            dr.rectangle([cx, cy, cx + tw - 1, cy + lb - 1], fill=(250, 214, 60))
            dr.text((cx + 4, cy + 2), f"#{s['shot']}   {int(m)}:{sec:05.2f}   {s['dur_s']:.1f}s", fill=(0, 0, 0), font=font)
            for k in range(3):
                fr = frames.get((s["shot"], k))
                if fr is not None:
                    sheet.paste(Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)), (cx + k * 218, cy + lb))
        sheet.save(f"{outdir}/sheet_{si // per + 1:03d}.jpg", quality=86)
    print(f"{(len(rows) + per - 1) // per} sheets -> {outdir}")


def cat(argv: list[str]):
    """Query work/catalog/part_*.json (records written by catalog agents; schema in the README)."""
    import argparse
    ap = argparse.ArgumentParser(prog="mist-vid cat")
    ap.add_argument("--tag", action="append")
    ap.add_argument("--char", action="append")
    ap.add_argument("--mood")
    ap.add_argument("--min-mv", type=int, default=0)
    ap.add_argument("--min-beauty", type=int, default=0)
    ap.add_argument("--hero", action="store_true")
    ap.add_argument("--range", help="film minutes, e.g. 30-45")
    ap.add_argument("--shots", help="shot ids, e.g. 540-560")
    ap.add_argument("--text")
    ap.add_argument("--notalk", action="store_true")
    ap.add_argument("--sort", default="time", choices=["time", "mv", "beauty", "energy"])
    ap.add_argument("-n", type=int, default=60)
    a = ap.parse_args(argv)
    recs = []
    for f in sorted(glob.glob("work/catalog/part_*.json")):
        recs += json.load(open(f))
    times = {int(r["shot"]): r for r in csv.DictReader(open("work/shots.csv"))}
    out = []
    for r in recs:
        s = int(r["shot"])
        st, du = float(times[s]["start_s"]), float(times[s]["dur_s"])
        tags = {x.lower() for x in r.get("tags", [])}
        if a.tag and not all(t.lower() in tags for t in a.tag):
            continue
        if a.char and not all(c in r.get("chars", []) for c in a.char):
            continue
        if a.mood and r.get("mood") != a.mood:
            continue
        if r.get("mv", 0) < a.min_mv or r.get("beauty", 0) < a.min_beauty:
            continue
        if (a.hero and not r.get("hero")) or (a.notalk and r.get("talk")):
            continue
        if a.range:
            m0, m1 = [float(x) for x in a.range.split("-")]
            if not m0 * 60 <= st <= m1 * 60:
                continue
        if a.shots:
            s0, s1 = [int(x) for x in a.shots.split("-")]
            if not s0 <= s <= s1:
                continue
        if a.text and a.text.lower() not in (r.get("desc", "") + " " + r.get("notes", "")).lower():
            continue
        out.append((r, st, du))
    keys = {"time": lambda x: x[1], "mv": lambda x: (-x[0].get("mv", 0), -x[0].get("beauty", 0)),
            "beauty": lambda x: -x[0].get("beauty", 0), "energy": lambda x: -x[0].get("energy", 0)}
    out.sort(key=keys[a.sort])
    print(f"{len(out)} shots")
    for r, st, du in out[:a.n]:
        m, sec = divmod(st, 60)
        fl = ("H" if r.get("hero") else " ") + ("t" if r.get("talk") else " ")
        note = f" [{r['notes'][:70]}]" if r.get("notes") else ""
        print(f"#{r['shot']:<5}{int(m):3d}:{sec:05.2f} {du:5.1f}s {r.get('framing', ''):5} mv{r.get('mv')} "
              f"b{r.get('beauty')} e{r.get('energy')} {fl} {r.get('mood', '')[:8]:8} "
              f"{','.join(r.get('chars', []))[:28]:28} | {r.get('desc', '')[:95]}{note}")


def strip(spec: str, n: int = 8, out: str = "work/strip.jpg", proxy_path: str = "work/proxy.mp4"):
    """Filmstrips: comma-separated shot ids or 'start-end' second ranges, n frames each."""
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    shot_t = {int(r["shot"]): (float(r["start_s"]), float(r["end_s"])) for r in csv.DictReader(open("work/shots.csv"))}
    font = ImageFont.truetype(FONT, 16)
    rows = []
    cap = cv2.VideoCapture(proxy_path)
    for item in spec.split(","):
        if "-" in item and "." in item:
            a, b = [float(x) for x in item.split("-")]
            label = item
        else:
            a, b = shot_t[int(item)]
            label = f"#{item}"
        tiles = []
        for i in range(n):
            t = a + (b - a) * (i + 0.5) / n
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, fr = cap.read()
            if not ok:
                fr = np.zeros((260, 480, 3), np.uint8)
            im = Image.fromarray(cv2.cvtColor(cv2.resize(fr, (240, 130)), cv2.COLOR_BGR2RGB))
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, 240, 18], fill=(0, 0, 0))
            d.text((3, 1), f"{label} {t:.2f}", font=font, fill=(255, 220, 0))
            tiles.append(np.array(im))
        rows.append(np.hstack(tiles))
    cv2.imwrite(out, cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    print(out)


def _whisper_words(wav: str, offset: float):
    subprocess.run(["whisper-cli", "-m", WHISPER_MODEL, "-f", wav, "-l", "en", "-ojf", "-dtw", "large.v3.turbo",
                    "-of", "/tmp/mist_vid_words", "-np"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    words = []
    for seg in json.load(open("/tmp/mist_vid_words.json"))["transcription"]:
        for tok in seg.get("tokens", []):
            t = tok["text"]
            if t.startswith("[_") or not t.strip():
                continue
            a, z = tok["offsets"]["from"] / 1000 + offset, tok["offsets"]["to"] / 1000 + offset
            if t.startswith(" ") or not words:
                words.append([t.strip(), a, z])
            else:
                words[-1][0] += t
                words[-1][2] = z
    return words


def words(movie: str, specs: list[str], channel: str = "FC"):
    """Word timings for film segments ('start:dur', film seconds). Short windows time better:
    whisper's DTW drifts by up to a second over long segments. Check against voice-energy spans."""
    for spec in specs:
        s, d = [float(x) for x in spec.split(":")]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(s), "-t", str(d), "-i", movie, "-vn",
                        "-af", f"pan=mono|c0={channel}", "-ar", "16000", "/tmp/mist_vid_seg.wav"], check=True)
        ws = _whisper_words("/tmp/mist_vid_seg.wav", s)
        print(f"## {spec}\n  " + "  ".join(f"{w}@{a:.2f}-{z:.2f}" for w, a, z in ws))


def hear(mix: str, windows: list[str]):
    """Transcribe windows of a rendered mix (output seconds 'a-b') to check dialogue edits."""
    for w in windows:
        a, b = [float(x) for x in w.split("-")]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a), "-t", str(b - a), "-i", mix, "-ac", "1",
                        "-ar", "16000", "/tmp/mist_vid_hear.wav"], check=True)
        subprocess.run(["whisper-cli", "-m", WHISPER_MODEL, "-f", "/tmp/mist_vid_hear.wav", "-l", "en", "-ojf",
                        "-of", "/tmp/mist_vid_hear", "-np"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        segs = json.load(open("/tmp/mist_vid_hear.json"))["transcription"]
        print(f"## o{a}-o{b}: " + " | ".join(f"[{a + s['offsets']['from'] / 1000:.1f}] {s['text'].strip()}" for s in segs))


def beats(song: str, outdir: str = "work"):
    """Beats and downbeats with beat_this (CPJKU). Writes beats.npy / downbeats.npy and prints a bar map."""
    from beat_this.inference import File2Beats
    f2b = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
    b, d = f2b(song)
    b, d = np.asarray(b), np.asarray(d)
    np.save(os.path.join(outdir, "beats.npy"), b)
    np.save(os.path.join(outdir, "downbeats.npy"), d)
    ibi = float(np.median(np.diff(b)))
    print(f"{len(b)} beats, {len(d)} bars, {60 / ibi:.1f} BPM; first beat {b[0]:.2f}s, first downbeat {d[0]:.2f}s")
    print("  ".join(f"B{i:02d} {t:6.2f}" for i, t in enumerate(d)))


def align(song: str, movie: str, start: float, dur: float, win: float = 4.0):
    """Map a stretch of the film's audio onto a song, window by window (chroma). Finds where a song
    sits in the film and any edits the film made to it (a jump in the lag = a cut)."""
    import librosa
    sr, hop = 22050, 512
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(dur), "-i", movie, "-vn", "-ac", "1",
                    "-ar", str(sr), "/tmp/mist_vid_film.wav"], check=True)
    y_s, _ = librosa.load(song, sr=sr)
    y_f, _ = librosa.load("/tmp/mist_vid_film.wav", sr=sr)

    def feat(y):
        c = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
        c = c - c.mean(axis=0, keepdims=True)
        return c / (np.linalg.norm(c, axis=0, keepdims=True) + 1e-9)
    fs, ff = feat(y_s), feat(y_f)
    fps = sr / hop
    W = int(win * fps)
    prev = None
    for c0 in range(0, ff.shape[1] - W, int(2 * fps)):
        A = ff[:, c0:c0 + W]
        sc = np.array([(A * fs[:, k:k + W]).sum() for k in range(0, fs.shape[1] - W)]) / W
        k = int(sc.argmax())
        mt, st = start + c0 / fps, k / fps
        lag = mt - st
        flag = "" if prev is None or abs(lag - prev) < 0.3 else "   <-- jump"
        print(f"film {mt:8.2f}  song {st:7.2f}  lag {lag:8.2f}  score {sc.max():.2f}{flag}")
        prev = lag


def review(video: str, project: str, prefix: str, extra: str | None = None):
    """Contact sheets of a render: one frame per main-track clip midpoint (30 per sheet)."""
    import cv2
    from PIL import Image, ImageDraw, ImageFont

    from .timeline import Project
    P = Project(project)
    pts = [((c.start + c.end) / 2, f"{c.idx} {(c.start + c.end) / 2:.1f}s") for c in P.clips if c.layer == 0]
    for a in (extra.split(",") if extra else []):
        t = P.anchor(a)
        pts.append((t, f"x {a} {t:.1f}s"))
    pts.sort()
    font = ImageFont.truetype(FONT, 18)
    tiles = []
    for t, lab in pts:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1", "-vf",
                              "scale=384:216", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        im = (np.frombuffer(raw, np.uint8).reshape(216, 384, 3).copy() if len(raw) == 384 * 216 * 3
              else np.zeros((216, 384, 3), np.uint8))
        pim = Image.fromarray(im)
        d = ImageDraw.Draw(pim)
        d.rectangle([0, 0, 150, 22], fill=(0, 0, 0))
        d.text((3, 1), lab, font=font, fill=(255, 220, 0))
        tiles.append(np.array(pim))
    for k in range(0, len(tiles), 30):
        grp = tiles[k:k + 30]
        while len(grp) % 5:
            grp.append(np.zeros_like(tiles[0]))
        rows = [np.hstack(grp[i:i + 5]) for i in range(0, len(grp), 5)]
        fn = f"{prefix}_{k // 30 + 1:02d}.jpg"
        cv2.imwrite(fn, cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
        print(fn)


def lookdev(project: str, shots_arg: str, grades_arg: str, out: str):
    """Grade comparison grid: rows = shots (mid frame), columns = raw + each grade."""
    import cv2
    from PIL import Image, ImageDraw, ImageFont

    from . import media
    from .gfx import GFX
    from .timeline import Project
    P = Project(project)
    sw, sh = P.p.get("src_size", [1920, 1040])
    src = media.Source(P.p["source"], P.src_num, P.src_den, sw, sh, P.p.get("src_frames", 0))
    G = GFX(P.W, P.H, sw, sh)
    pic = tuple(P.p.get("pic", [0, 20, 1920, 1040]))
    font = ImageFont.truetype(FONT, 22)
    rows = []
    for s in [int(x) for x in shots_arg.split(",")]:
        a, b = P.shots[s - 1]
        fr = media.grab(src, (a + b) // 2)
        if fr is None:
            continue
        row = []
        for g in ["raw"] + grades_arg.split(","):
            G.upload(0, fr)
            L = G.clip(0, 0, pic, {"grade": "neutral" if g == "raw" else g, "lutmix": 0.0 if g == "raw" else 1.0})
            bl, ha = G.bloom(L)
            fin = {"bloom": 0.0, "halo": 0.0, "grain": 0.0, "vignette": 0.0} if g == "raw" else {}
            im = np.frombuffer(G.finish(L, bl, ha, 3, fin), np.uint8).reshape(P.H, P.W, 3)
            pim = Image.fromarray(cv2.resize(im, (480, 270), interpolation=cv2.INTER_AREA))
            ImageDraw.Draw(pim).text((6, 4), f"#{s} {g}", font=font, fill=(255, 255, 0))
            row.append(np.array(pim))
        rows.append(np.hstack(row))
    cv2.imwrite(out, cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 86])
    print(out)


if __name__ == "__main__":
    sys.exit("use: mist-vid <command>")
