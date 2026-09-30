"""Frame-exact source access: ffmpeg decode pipes and a RIFE slow-motion cache.

Conventions: source frame k starts at k * SRC_DEN / SRC_NUM seconds (2997/125 fps for
this film). Frames arrive as uint8 RGB (H, W, 3), BT.709 limited -> full range.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess

import cv2
import numpy as np

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
from .paths import CACHE, RIFE, RIFE_MODEL

YUV2RGB = "scale=in_color_matrix=bt709:in_range=tv:flags=bicubic+accurate_rnd+full_chroma_int,format=rgb24"


class Source:
    def __init__(self, path: str, fps_num: int, fps_den: int, w: int, h: int, nframes: int):
        self.path, self.num, self.den, self.w, self.h, self.n = path, fps_num, fps_den, w, h, nframes

    def t(self, k: float) -> float:
        return k * self.den / self.num

    def frame_at(self, sec: float) -> int:
        return int(round(sec * self.num / self.den))


class Reader:
    """Sequential reader from source frame `k0`. get(k) returns frame k for any k >= last k."""

    def __init__(self, src: Source, k0: int, count: int):
        self.src = src
        self.k0 = max(0, min(k0, src.n - 1))
        count = max(1, min(count, src.n - self.k0))
        ss = max(0.0, src.t(self.k0) - 0.004)
        cmd = [FFMPEG, "-v", "error", "-hwaccel", "videotoolbox", "-ss", f"{ss:.6f}", "-i", src.path,
               "-frames:v", str(count), "-an", "-sn", "-vf", YUV2RGB, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=src.w * src.h * 3)
        self.cur_k = self.k0 - 1
        self.cur = None
        self.last_k = self.k0 + count - 1

    def _next(self):
        stdout = self.proc.stdout
        if stdout is None:
            return False
        buf = stdout.read(self.src.w * self.src.h * 3)
        if len(buf) < self.src.w * self.src.h * 3:
            return False
        self.cur = np.frombuffer(buf, np.uint8).reshape(self.src.h, self.src.w, 3)
        self.cur_k += 1
        return True

    def get(self, k: int):
        k = max(self.k0, min(k, self.last_k))
        while self.cur_k < k:
            if not self._next():
                break
        return self.cur

    def close(self):
        try:
            if self.proc.stdout:
                self.proc.stdout.close()
            self.proc.kill()
            self.proc.wait(timeout=2)
        except Exception:
            pass


def grab(src: Source, k: int):
    r = Reader(src, k, 1)
    f = r.get(k)
    r.close()
    return f


class RifeClip:
    """Slow-motion frames: source frames k0..k1 interpolated `factor`x with RIFE v4.6.
    get(pos) takes a fractional source frame position (absolute) and returns the nearest
    interpolated frame."""

    def __init__(self, src: Source, k0: int, k1: int, factor: int = 8, progress=None):
        self.src, self.k0, self.k1, self.f = src, k0, k1, factor
        key = hashlib.sha1(f"{src.path}|{k0}|{k1}|{factor}|v4.6|jpg".encode()).hexdigest()[:16]
        self.dir = os.path.join(CACHE, "rife", key)
        n_in = k1 - k0 + 1
        self.n_out = n_in * factor
        done = os.path.join(self.dir, "DONE")
        if not os.path.exists(done):
            self._build(n_in, progress)
            open(done, "w").write(f"{k0} {k1} {factor}\n")
        self.files = sorted(f for f in os.listdir(os.path.join(self.dir, "out")) if f.endswith((".png", ".jpg")))
        self._cache_i, self._cache = None, None

    def _build(self, n_in: int, progress):
        ind, outd = os.path.join(self.dir, "in"), os.path.join(self.dir, "out")
        for d in (ind, outd):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
        r = Reader(self.src, self.k0, n_in)
        for i in range(n_in):
            fr = r.get(self.k0 + i)
            cv2.imwrite(os.path.join(ind, f"{i + 1:08d}.png"), cv2.cvtColor(fr, cv2.COLOR_RGB2BGR),
                        [cv2.IMWRITE_PNG_COMPRESSION, 1])
        r.close()
        if progress:
            progress(f"RIFE {n_in} -> {self.n_out} frames")
        subprocess.run([RIFE, "-i", ind, "-o", outd, "-m", RIFE_MODEL, "-n", str(self.n_out), "-f", "%08d.jpg"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(ind, ignore_errors=True)

    def get(self, pos: float):
        i = int(round((pos - self.k0) * self.f))
        i = max(0, min(i, len(self.files) - 1))
        if i != self._cache_i:
            im = cv2.imread(os.path.join(self.dir, "out", self.files[i]), cv2.IMREAD_COLOR)
            self._cache = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
            self._cache_i = i
        return self._cache
