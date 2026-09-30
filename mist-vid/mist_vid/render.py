"""Render a project YAML to video: frame loop over the GPU compositor, piped to ffmpeg.

  mist-vid render edit.yaml -o out.mp4 [--preview] [--from o30 --to o60] [--stills o10,b64,...]
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import subprocess
import sys
import time

import cv2
import numpy as np

from . import media, typo
from .gfx import GFX
from .timeline import Clip, Project, ease, src_pos

from .paths import CACHE


def progress(msg):
    print(msg, flush=True)


class FrameCache:
    """Random access to a range of source frames, extracted once to JPEG."""

    def __init__(self, src: media.Source, k0: int, k1: int):
        key = hashlib.sha1(f"{src.path}|{k0}|{k1}|jpg".encode()).hexdigest()[:16]
        self.dir = os.path.join(CACHE, "frames", key)
        self.k0, self.k1 = k0, k1
        if not os.path.exists(os.path.join(self.dir, "DONE")):
            os.makedirs(self.dir, exist_ok=True)
            r = media.Reader(src, k0, k1 - k0 + 1)
            for k in range(k0, k1 + 1):
                fr = r.get(k)
                cv2.imwrite(os.path.join(self.dir, f"{k:07d}.jpg"), cv2.cvtColor(fr, cv2.COLOR_RGB2BGR),
                            [cv2.IMWRITE_JPEG_QUALITY, 96])
            r.close()
            open(os.path.join(self.dir, "DONE"), "w").write("ok")
        self._k, self._f = None, None

    def get(self, k: int):
        k = max(self.k0, min(self.k1, k))
        if k != self._k:
            self._f = cv2.cvtColor(cv2.imread(os.path.join(self.dir, f"{k:07d}.jpg")), cv2.COLOR_BGR2RGB)
            self._k = k
        return self._f


class Renderer:
    def __init__(self, project: Project):
        self.P = P = project
        p = P.p
        sw, sh = p.get("src_size", [1920, 1040])
        self.src = media.Source(p["source"], P.src_num, P.src_den, sw, sh, p.get("src_frames", 0))
        self.G = GFX(P.W, P.H, sw, sh)
        self.G.set_paper(typo.paper(1024, 1024, seed=21, age=0.6))
        self.pic = tuple(p.get("pic", [0, 20, 1920, 1040]))
        self.access = {}
        self.cards = {}
        self.sprite_cache = {}
        self.main = [c for c in P.clips if c.layer == 0]
        self.layers = [c for c in P.clips if c.layer > 0]

    # ---- sources -----------------------------------------------------------
    def _window(self, c: Clip):
        ts = np.linspace(c.start - c.pre, c.end + c.post, max(3, int((c.end + c.post - c.start + c.pre) * 48)))
        ps = [src_pos(c, float(t), self.P.src_fps) for t in ts]
        return int(math.floor(min(ps))), int(math.ceil(max(ps)))

    def prepare(self):
        """Build RIFE / reverse caches up front so the frame loop never stalls."""
        todo = [c for c in self.P.clips if self._cfg(c).get("card") is None and (c.rife or c.reverse or c.ramp)]
        for n, c in enumerate(todo):
            k0, k1 = self._window(c)
            if c.rife:
                progress(f"[prep {n + 1}/{len(todo)}] RIFE clip {c.idx}: frames {k0}-{k1}")
                self.access[c.idx] = media.RifeClip(self.src, k0, k1 + 1, factor=4)
            else:
                progress(f"[prep {n + 1}/{len(todo)}] frame cache clip {c.idx}: frames {k0}-{k1}")
                self.access[c.idx] = FrameCache(self.src, k0, k1 + 1)

    def _cfg(self, c: Clip) -> dict:
        if c.layer == 0:
            return self.P.cfg["track"][c.idx]
        return self.P.cfg["layers"][c.idx - 1000]

    def frame(self, c: Clip, t: float):
        cfg = self._cfg(c)
        if cfg.get("card") is not None:
            return self.card(cfg["card"])
        pos = src_pos(c, t, self.P.src_fps)
        acc = self.access.get(c.idx)
        if isinstance(acc, media.RifeClip):
            return acc.get(pos)
        if isinstance(acc, FrameCache):
            return acc.get(int(round(pos)))
        if acc is None:
            k0, k1 = self._window(c)
            acc = self.access[c.idx] = media.Reader(self.src, k0, k1 - k0 + 2)
        return acc.get(int(round(pos)))

    def release(self, t: float):
        for c in self.P.clips:
            if c.end + c.post < t - 0.05 and c.idx in self.access and isinstance(self.access[c.idx], media.Reader):
                self.access.pop(c.idx).close()

    # ---- cards (paper pages) ----------------------------------------------
    def card(self, spec: dict):
        key = hashlib.sha1(repr(spec).encode()).hexdigest()[:16]
        if key in self.cards:
            return self.cards[key]
        path = os.path.join(CACHE, "cards", key + ".png")
        if os.path.exists(path):
            img = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB)
        else:
            W, H = self.P.W, self.P.H
            bg = spec.get("bg", "paper")
            if bg == "paper":
                canvas = typo.paper(W, H, seed=spec.get("seed", 11), age=spec.get("age", 1.0))
            else:
                canvas = np.zeros((H, W, 3), np.float32) + np.array(spec.get("color", [0, 0, 0]), np.float32)
            for it in spec.get("items", []):
                spr, _ = self.text_sprite(it)
                x = int(it.get("x", W / 2) - spr.shape[1] / 2)
                y = int(it.get("y", H / 2) - spr.shape[0] / 2)
                typo.over(canvas, spr, x, y)
            img = (np.clip(canvas, 0, 1) * 255 + 0.5).astype(np.uint8)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            cv2.imwrite(path, cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        self.cards[key] = img
        return img

    def text_sprite(self, it: dict):
        """rgba uint8 + spec (or None) for a text/ornament item."""
        key = hashlib.sha1(repr(sorted(it.items(), key=lambda kv: kv[0])).encode()).hexdigest()[:16]
        if key in self.sprite_cache:
            return self.sprite_cache[key]
        lines = it.get("lines") or [it]
        masks = []
        for ln in lines:
            if "orn" in ln:
                face = ln.get("face", "orn")
                table = typo.ORN if face == "orn" else typo.ORN2
                masks.append(typo.mask(table[ln["orn"]], face, ln.get("size", 100), pad=16))
            else:
                masks.append(typo.mask(ln["text"], ln.get("face", "fell"), ln.get("size", 100),
                                       tracking=ln.get("tracking", 0.0), pad=16))
        m = typo.stack(masks, align=it.get("align", "center"), gap=it.get("gap", 8))
        style = it.get("style", "gold")
        spec = None
        if style == "gold" or style in ("silver", "rose"):
            rgba, spec = typo.gold(m, bevel=it.get("bevel", 4.5), palette={"gold": "gold"}.get(style, style),
                                   shadow=it.get("shadow", 0.65), glow=it.get("glow_under", 0.35))
        elif style == "ink":
            rgba = typo.ink(m, color=tuple(it.get("color", (0.16, 0.10, 0.06))))
        elif style == "glow":
            rgba = typo.glow(m, color=tuple(it.get("color", (1.0, 0.85, 0.6))), radius=it.get("radius", 14))
        else:  # plain cream text with a soft dark under-glow
            col = np.array(it.get("color", (0.97, 0.93, 0.84)), np.float32)
            pad = 30
            mm = np.pad(m, pad)
            under = cv2.GaussianBlur(mm, (0, 0), 7) * it.get("shadow", 0.55)
            a = mm + under * (1 - mm)
            c = (col[None, None, :] * mm[..., None] + np.array([0.05, 0.03, 0.02]) * (under * (1 - mm))[..., None])
            c = c / np.maximum(a[..., None], 1e-5)
            rgba = (np.clip(np.dstack([c, a]), 0, 1) * 255 + 0.5).astype(np.uint8)
        self.sprite_cache[key] = (rgba, spec)
        return rgba, spec

    def leak_sprite(self, seed: int, color):
        key = ("leak", seed, tuple(color))
        if key in self.sprite_cache:
            return self.sprite_cache[key]
        h, w = 540, 960
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        rng = np.random.default_rng(seed)
        acc = np.zeros((h, w), np.float32)
        for _ in range(4):
            cx, cy = rng.uniform(0.2, 0.8) * w, rng.uniform(0.2, 0.8) * h
            sx, sy = rng.uniform(0.15, 0.45) * w, rng.uniform(0.2, 0.6) * h
            acc += np.exp(-(((xx - cx) / sx) ** 2 + ((yy - cy) / sy) ** 2)) * rng.uniform(0.5, 1.0)
        acc *= 0.75 + 0.5 * typo.fbm(h, w, seed, base=160.0, octaves=3)
        acc = np.clip(acc / acc.max(), 0, 1)
        col = np.array(color, np.float32)
        hot = np.clip(acc - 0.6, 0, 1) / 0.4
        rgb = acc[..., None] * col[None, None, :] + hot[..., None] * np.array([1.0, 0.95, 0.85]) * 0.5
        rgba = (np.clip(np.dstack([rgb, acc]), 0, 1) * 255).astype(np.uint8)
        self.sprite_cache[key] = (rgba, None)
        return rgba, None

    # ---- looks ---------------------------------------------------------------
    def look(self, c: Clip, t: float) -> dict:
        L = max(c.end - c.start, 1e-6)
        u = ease((t - c.start) / L, c.ease)
        lk: dict = {"grade": c.grade}
        lk.update(c.look)
        lk["zoom"] = c.zoom[0] + (c.zoom[1] - c.zoom[0]) * u
        lk["center"] = tuple(a + (b - a) * u for a, b in zip(c.center[0], c.center[1], strict=True))
        lk["rot"] = c.rot[0] + (c.rot[1] - c.rot[0]) * u
        wv = self.P.p.get("weave", 0.45)
        lk["weave"] = (wv * (math.sin(t * 7.3) * 0.6 + math.sin(t * 17.9 + 1.3) * 0.4),
                       wv * (math.sin(t * 5.1 + 0.7) * 0.6 + math.sin(t * 13.3) * 0.4))
        if c.flash_in > 0:
            k = max(0.0, 1.0 - (t - c.start) / 0.35)
            lk["flash"] = max(lk.get("flash", 0.0), c.flash_in * k * k)
        f = 0.0
        if c.fade_in > 0 and t < c.start + c.fade_in:
            f = max(f, 1 - (t - c.start) / c.fade_in)
        if c.fade_out > 0 and t > c.end - c.fade_out:
            f = max(f, (t - (c.end - c.fade_out)) / c.fade_out)
        if c.layer == 0 and f > 0:
            lk["fade"] = min(1.0, max(lk.get("fade", 0.0), f))
        return lk

    def draw_clip(self, layer_i: int, slot: int, c: Clip, t: float):
        img = self.frame(c, t)
        cfg = self._cfg(c)
        lk = self.look(c, t)
        if cfg.get("card") is not None:
            tex = self.G.card_tex[slot % 2]
            tex.write(np.ascontiguousarray(img).tobytes())
            lk.setdefault("lutmix", 0.35)
            return self.G.clip(layer_i, slot, (0, 0, self.P.W, self.P.H), lk, tex=tex)
        if img is None:
            img = np.zeros((self.G.SH, self.G.SW, 3), np.uint8)
        self.G.upload(slot, img)
        return self.G.clip(layer_i, slot, self.pic, lk)

    # ---- overlays ------------------------------------------------------------
    def draw_overlays(self, target, t: float):
        G = self.G
        for o in self.P.overlays:
            if not (o.start <= t < o.end):
                continue
            q = o.params
            dur = o.end - o.start
            lt = t - o.start
            env_in = float(q.get("in", 0.6))
            env_out = float(q.get("out", 0.6))
            op = float(q.get("opacity", 1.0))
            if env_out > 0 and lt > dur - env_out:
                op *= max(0.0, (dur - lt) / env_out)
            if o.kind == "flash":
                a = float(q.get("attack", 0.03))
                d = float(q.get("decay", dur))
                env = min(1.0, lt / a) if lt < a else math.exp(-(lt - a) / max(d / 3.0, 1e-3))
                col = tuple(q.get("color", (1.0, 0.95, 0.85)))
                white = self.sprite_cache.setdefault(("white",), (np.full((4, 4, 4), 255, np.uint8), None))[0]
                tex = G.sprite_tex(("white",), white)
                G.sprite(target, tex, (0, 0, self.P.W, self.P.H), opacity=float(q.get("amount", 0.8)) * env,
                         blend="add", color_mul=col)
                continue
            if o.kind == "leak":
                rgba, _ = self.leak_sprite(int(q.get("seed", 1)), q.get("color", (1.0, 0.55, 0.2)))
                tex = G.sprite_tex(("leak", int(q.get("seed", 1)), tuple(q.get("color", (1.0, 0.55, 0.2)))), rgba)
                u = lt / max(dur, 1e-6)
                p0, p1 = q.get("p0", [0.1, 0.3]), q.get("p1", [0.4, 0.2])
                cx = (p0[0] + (p1[0] - p0[0]) * u) * self.P.W
                cy = (p0[1] + (p1[1] - p0[1]) * u) * self.P.H
                sc = float(q.get("scale", 1.6))
                w, h = self.P.W * sc, self.P.H * sc
                env = min(1.0, lt / env_in) if env_in > 0 else 1.0
                G.sprite(target, tex, (cx - w / 2, cy - h / 2, w, h), opacity=op * env, blend="screen",
                         angle=float(q.get("angle", 0.0)) + u * float(q.get("spin", 0.0)))
                continue
            # text / ornament
            rgba, spec = self.text_sprite(q)
            key = hashlib.sha1(repr(sorted(q.items(), key=lambda kv: kv[0])).encode()).hexdigest()[:16]
            tex = G.sprite_tex(("txt", key), rgba)
            stex = G.spec_tex(key, spec) if spec is not None else None
            h, w = rgba.shape[:2]
            s0, s1 = q.get("drift", [1.0, 1.0]) if isinstance(q.get("drift"), list) else (1.0, float(q.get("drift", 1.0)))
            sc = (s0 + (s1 - s0) * (lt / max(dur, 1e-6))) * float(q.get("scale", 1.0))
            cx = float(q.get("x", self.P.W / 2))
            cy = float(q.get("y", self.P.H / 2))
            rw, rh = w * sc, h * sc
            reveal = -1.0
            mode = q.get("reveal", "ink")
            if mode == "ink" and env_in > 0:
                reveal = min(1.0, lt / env_in)
            elif mode == "fade" and env_in > 0:
                op *= min(1.0, lt / env_in)
            sweep, samt = 0.0, 0.0
            if spec is not None and q.get("glint", True):
                g0 = float(q.get("glint_at", env_in * 0.6))
                gd = float(q.get("glint_dur", 1.1))
                if g0 <= lt <= g0 + gd:
                    sweep = -0.25 + 1.5 * (lt - g0) / gd
                    samt = float(q.get("glint_amt", 1.3))
            G.sprite(target, tex, (cx - rw / 2, cy - rh / 2, rw, rh), opacity=op, blend=q.get("blend", "normal"),
                     reveal=reveal, soft=float(q.get("soft", 0.08)), seed=float(q.get("seed", 3.0)),
                     rdir=tuple(q.get("rdir", (1.0, 0.25))), nscale=float(q.get("nscale", 5.0)), spec=stex,
                     sweep=sweep, sweep_amt=samt)

    # ---- the frame -------------------------------------------------------------
    def render_frame(self, i: int):
        P, G = self.P, self.G
        t = i / P.fps
        act = [c for c in self.main if c.start - c.pre <= t < c.end + c.post]
        act.sort(key=lambda c: c.start)
        if not act:
            comp = G.layers[2]
            comp[0].use()
            G.ctx.clear(0, 0, 0, 1)
        elif len(act) == 1:
            comp = self.draw_clip(0, 0, act[0], t)
        else:
            a, b = act[0], act[-1]
            A = self.draw_clip(0, 0, a, t)
            B = self.draw_clip(1, 1, b, t)
            d = b.pre + a.post
            p = (t - (b.start - b.pre)) / max(d, 1e-6)
            p = min(1.0, max(0.0, p))
            name, _, params, _ = b.tx if b.tx else ("fade", 0, {}, "center")
            comp = G.layers[2]
            if name == "fade":
                G.mix(A, B, ease(p), comp, 0)
            else:
                G.transition(name, A, B, p, comp, params)
        for lay in self.layers:
            if lay.start <= t < lay.end:
                L = self.draw_clip(3, 2, lay, t)
                op = lay.opacity
                if lay.fade_in > 0 and t < lay.start + lay.fade_in:
                    op *= ease((t - lay.start) / lay.fade_in)
                if lay.fade_out > 0 and t > lay.end - lay.fade_out:
                    op *= ease((lay.end - t) / lay.fade_out)
                out = G.layers[4] if comp is not G.layers[4] else G.layers[5]
                G.mix(comp, L, op, out, lay.mode)
                comp = out
        self.draw_overlays(comp, t)
        fin = P.finish_at(t)
        bloom, halo = G.bloom(comp, thr=float(fin.get("bloom_thr", 0.70)))
        fin["flicker"] = 1.0 + float(fin.get("flicker_amt", 0.01)) * (math.sin(t * 41.0) * 0.5 + math.sin(t * 23.0 + 1.1) * 0.5)
        return G.finish(comp, bloom, halo, i, fin)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("-o", "--out", default="work/out.mp4")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--hevc-q", type=int, default=None,
                    help="encode with VideoToolbox HEVC at this quality (1-100, ~65 = visually clean); fast delivery")
    ap.add_argument("--from", dest="t0", default=None)
    ap.add_argument("--to", dest="t1", default=None)
    ap.add_argument("--stills", default=None, help="comma-separated anchors to export as JPG")
    ap.add_argument("--audio", default=None, help="wav to mux")
    ap.add_argument("--progress-label", default=None)
    a = ap.parse_args()
    P = Project(a.project)
    R = Renderer(P)
    fps = P.fps
    if a.stills:
        R.prepare()
        os.makedirs("work/stills", exist_ok=True)
        for s in a.stills.split(","):
            t = P.anchor(s)
            i = int(round(t * fps))
            buf = R.render_frame(i)
            img = np.frombuffer(buf, np.uint8).reshape(P.H, P.W, 3)
            fn = f"work/stills/{s.replace('/', '_')}.jpg"
            cv2.imwrite(fn, cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
            print(fn)
        return
    t0 = P.anchor(a.t0) if a.t0 else 0.0
    t1 = P.anchor(a.t1) if a.t1 else P.duration
    i0, i1 = int(round(t0 * fps)), int(round(t1 * fps))
    R.prepare()
    vid = a.out + ".video.mp4" if a.audio else a.out
    enc = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{P.W}x{P.H}",
           "-r", f"{P.fps_num}/{P.fps_den}", "-i", "-",
           "-vf", "scale=out_color_matrix=bt709:out_range=tv:flags=bicubic+accurate_rnd+full_chroma_int,format=yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
    vui = "colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"
    if a.hevc_q is not None:
        enc += ["-c:v", "hevc_videotoolbox", "-q:v", str(a.hevc_q), "-tag:v", "hvc1", "-bsf:v", f"hevc_metadata={vui}"]
    elif a.preview:
        enc += ["-c:v", "h264_videotoolbox", "-b:v", "14M", "-bsf:v", f"h264_metadata={vui}"]
    else:
        enc += ["-c:v", "libx264", "-preset", "slow", "-crf", "15", "-tune", "film",
                "-x264-params", "keyint=48:min-keyint=12", "-bsf:v", f"h264_metadata={vui}"]
    enc += ["-movflags", "+faststart", vid]
    proc = subprocess.Popen(enc, stdin=subprocess.PIPE)
    stdin = proc.stdin
    assert stdin is not None
    tstart = time.time()
    label = a.progress_label or os.path.basename(a.out)
    use_bar = bool(os.environ.get("MIST_CONSOLE_SESSION"))
    if use_bar:
        subprocess.run(["mist-progress", "start", "--id", "pbrender", "--label", f"Rendering {label}"], check=False)
    n = i1 - i0
    for k, i in enumerate(range(i0, i1)):
        stdin.write(R.render_frame(i))
        if k % 48 == 0:
            R.release(i / fps)
            el = time.time() - tstart
            rate = (k + 1) / max(el, 1e-6)
            msg = f"frame {k}/{n}  {rate:.1f} fps  eta {(n - k) / max(rate, 1e-6):.0f}s"
            print(msg, flush=True)
            if use_bar:
                subprocess.run(["mist-progress", "set", "--id", "pbrender", "--current", str(k), "--total", str(n),
                                "--eta", str(int((n - k) / max(rate, 1e-6))), "--detail", msg], check=False)
    stdin.close()
    proc.wait()
    for acc in R.access.values():
        if isinstance(acc, media.Reader):
            acc.close()
    if use_bar:
        subprocess.run(["mist-progress", "done", "--id", "pbrender"], check=False)
    if a.audio:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", vid, "-ss", f"{t0:.4f}", "-t", f"{t1 - t0:.4f}", "-i", a.audio,
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k",
                        "-movflags", "+faststart", a.out], check=True)
        os.remove(vid)
    print(f"done {a.out}  {n} frames in {time.time() - tstart:.0f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
