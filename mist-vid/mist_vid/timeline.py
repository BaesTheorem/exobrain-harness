"""Edit decision list: parse the project YAML into frame-exact clips, layers and overlays.

Time anchors (strings) resolve to OUTPUT seconds:
  o12.5   output seconds            s145.2  song seconds (song_at + t)
  b64     song beat 64 (b64.5 = halfway to beat 65)
  B12     bar 12 downbeat (B12.25 = one beat into bar 12, B12.5 = beat 3)
  L27     lyric line 27 start        L27e    its end
  any of these + or - an offset: 'b64-2f' (frames), 'L27+0.25' (seconds), 'b10+1b' (beats)
Lengths: '2b' beats (measured on the grid from the clip start), '1.5s' / '1.5' seconds, '36f' frames.
Source points: 1234.5 (seconds) | 'm:ss.xx' | '#592' shot start | '#592@0.5' fraction of shot | '#592+1.2'.
"""
from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, field

import numpy as np
import yaml

TX_ALIASES = {
    "dissolve": "fade", "dream": "Dreamy", "dreamzoom": "DreamyZoom", "burn": "FilmBurn",
    "page": "PageCurlPaper", "flip": "BookFlip", "melt": "luminance_melt", "zoom": "CrossZoom",
    "blur": "LinearBlur", "whip": "directionalwarp", "ripple": "ripple", "flash": "Overexposure",
    "dip": "fadecolor", "gray": "fadegrayscale", "wind": "wind", "swirl": "Swirl", "morph": "morph",
    "burnout": "undulatingBurnOut", "crosswarp": "crosswarp", "circle": "circleopen",
}


@dataclass
class Clip:
    idx: int
    src_frame: float          # source frame at the clip's nominal start
    start: float              # output seconds (nominal cut in)
    end: float                # output seconds (nominal cut out)
    speed: float = 1.0
    rife: bool = False
    reverse: bool = False
    ramp: list | None = None  # [[frac, speed], ...]
    grade: str = "storybook"
    look: dict = field(default_factory=dict)
    zoom: tuple = (1.0, 1.0)
    center: tuple = ((0.5, 0.5), (0.5, 0.5))
    rot: tuple = (0.0, 0.0)
    ease: str = "inout"
    tx: tuple | None = None   # (glsl name, duration, params)
    pre: float = 0.0          # handle before start (seconds), set from incoming tx
    post: float = 0.0         # handle after end, set from outgoing tx
    shot_lo: int = 0          # clamp range for handles (source frames)
    shot_hi: int = 1 << 30
    flash_in: float = 0.0
    freeze: bool = False
    layer: int = 0            # 0 = main track; >0 = double-exposure layers
    mode: int = 0             # layer blend mode for layers > 0
    opacity: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    note: str = ""


@dataclass
class Overlay:
    kind: str
    start: float
    end: float
    params: dict


class Project:
    def __init__(self, path: str):
        self.path = path
        cfg = yaml.safe_load(open(path))
        self.cfg = cfg
        p = cfg["project"]
        self.p = p
        self.fps_num, self.fps_den = p.get("fps", [24000, 1001])
        self.fps = self.fps_num / self.fps_den
        self.src_num, self.src_den = p.get("src_fps", [2997, 125])
        self.src_fps = self.src_num / self.src_den
        self.W, self.H = p.get("size", [1920, 1080])
        self.song_at = float(p.get("song_at", 0.0))
        self.beats = np.load(p["beats"]) if p.get("beats") else np.array([])
        self.downbeats = np.load(p["downbeats"]) if p.get("downbeats") else np.array([])
        self.lyrics = json.load(open(p["lyrics"])) if p.get("lyrics") else []
        self.shots = []
        if p.get("shots"):
            for r in csv.DictReader(open(p["shots"])):
                self.shots.append((int(r["start_frame"]), int(r["end_frame"])))
        self.shot_starts = np.array([s[0] for s in self.shots]) if self.shots else np.array([0])
        self.clips: list[Clip] = []
        self.overlays: list[Overlay] = []
        self.audio = cfg.get("audio", [])
        self.finish_keys = []
        self._build()

    # ---- anchors ---------------------------------------------------------
    def beat_time(self, b: float) -> float:
        """Song time of fractional beat index b (extrapolates past the grid)."""
        bt = self.beats
        i = int(math.floor(b))
        f = b - i
        if i < 0:
            return bt[0] + b * (bt[1] - bt[0])
        if i >= len(bt) - 1:
            per = float(np.median(np.diff(bt[-16:])))
            return bt[-1] + (b - (len(bt) - 1)) * per
        return bt[i] + f * (bt[i + 1] - bt[i])

    def time_to_beat(self, song_t: float) -> float:
        bt = self.beats
        i = int(np.searchsorted(bt, song_t) - 1)
        i = max(0, min(i, len(bt) - 2))
        return i + (song_t - bt[i]) / (bt[i + 1] - bt[i])

    def anchor(self, a) -> float:
        if isinstance(a, (int, float)):
            return float(a)
        a = str(a).strip()
        m = re.match(r"^([obsLB])(-?[0-9.]+)(e?)((?:[+-][0-9.]+[fbs]?)*)$", a)
        if not m:
            raise ValueError(f"bad anchor {a!r}")
        kind, num, is_end, offs = m.group(1), float(m.group(2)), m.group(3), m.group(4)
        if kind == "o":
            t = num
        elif kind == "s":
            t = self.song_at + num
        elif kind == "b":
            t = self.song_at + self.beat_time(num)
        elif kind == "B":   # bar (downbeat) index, fractional = beats into the bar / 4
            bi = int(math.floor(num))
            db = self.downbeats
            if bi >= len(db):
                per = float(np.median(np.diff(db[-8:])))
                t0 = db[-1] + (bi - (len(db) - 1)) * per
            elif bi < 0:
                t0 = db[0] + bi * float(np.median(np.diff(db[:8])))
            else:
                t0 = db[bi]
            frac = num - bi
            if frac > 0:
                t0 = self.beat_time(self.time_to_beat(t0) + frac * 4)
            t = self.song_at + t0
        else:
            ln = self.lyrics[int(num) - 1]
            t = self.song_at + (ln["end"] if is_end else ln["start"])
        for om in re.finditer(r"([+-])([0-9.]+)([fbs]?)", offs):
            sgn = 1 if om.group(1) == "+" else -1
            v, unit = float(om.group(2)), om.group(3)
            if unit == "f":
                t += sgn * v / self.fps
            elif unit == "b":
                sb = self.time_to_beat(t - self.song_at)
                t = self.song_at + self.beat_time(sb + sgn * v)
            else:
                t += sgn * v
        return t

    def length(self, start: float, ln) -> float:
        if isinstance(ln, (int, float)):
            return float(ln)
        s = str(ln).strip()
        if s.endswith("b"):
            sb = self.time_to_beat(start - self.song_at)
            return self.song_at + self.beat_time(sb + float(s[:-1])) - start
        if s.endswith("f"):
            return float(s[:-1]) / self.fps
        return float(s.rstrip("s"))

    def src_point(self, s) -> float:
        """Source frame (float) for a source point spec."""
        if isinstance(s, (int, float)):
            return float(s) * self.src_fps
        s = str(s).strip()
        if s.startswith("#"):
            m = re.match(r"^#(\d+)(?:@([0-9.]+))?(?:\+([0-9.]+))?(?:-([0-9.]+))?$", s)
            if not m:
                raise ValueError(f"bad shot ref {s!r}")
            a, b = self.shots[int(m.group(1)) - 1]
            f = float(a)
            if m.group(2):
                f = a + (b - a) * float(m.group(2))
            if m.group(3):
                f += float(m.group(3)) * self.src_fps
            if m.group(4):
                f = b - float(m.group(4)) * self.src_fps
            return f
        if ":" in s:
            parts = [float(x) for x in s.split(":")]
            sec = parts[-1] + 60 * parts[-2] + (3600 * parts[-3] if len(parts) > 2 else 0)
            return sec * self.src_fps
        return float(s) * self.src_fps

    def shot_of(self, f: float):
        if not self.shots:
            return 0, 1 << 30
        i = int(np.searchsorted(self.shot_starts, f, side="right") - 1)
        i = max(0, min(i, len(self.shots) - 1))
        return self.shots[i][0], self.shots[i][1] - 1

    # ---- build -----------------------------------------------------------
    def _tx(self, spec):
        if not spec or spec == "cut":
            return None
        if isinstance(spec, dict):
            name, dur, params = spec["name"], float(spec.get("dur", 0.5)), spec.get("params", {})
            align = spec.get("align", "center")
        else:
            parts = str(spec).split()
            name, dur, params, align = parts[0], float(parts[1]) if len(parts) > 1 else 0.5, {}, "center"
            if len(parts) > 2:
                align = parts[2]
        glsl = TX_ALIASES.get(name, name)
        if name == "dip":
            params = {"color": (0.0, 0.0, 0.0), **params}
        if name == "dipwhite":
            glsl, params = "fadecolor", {"color": (1.0, 0.97, 0.9), **params}
        return glsl, dur, params, align

    def _build(self):
        t = 0.0
        prev = None
        for i, c in enumerate(self.cfg.get("track", [])):
            if "at" in c:
                t = self.anchor(c["at"])
            start = t
            if "to" in c:
                end = self.anchor(c["to"])
            elif "len" in c:
                end = start + self.length(start, c["len"])
            else:
                raise ValueError(f"clip {i} needs to/len")
            if end <= start:
                raise ValueError(f"clip {i} ends before it starts ({start:.3f} -> {end:.3f}) {c}")
            sf = self.src_point(c["src"]) if "src" in c else 0.0
            if "src_end" in c:     # fit a source range into the slot: derive speed
                ef = self.src_point(c["src_end"])
                c.setdefault("speed", (ef - sf) / self.src_fps / (end - start))
            lo, hi = self.shot_of(sf + 0.5)
            zoom = c.get("zoom", 1.0)
            zoom = tuple(zoom) if isinstance(zoom, list) else (float(zoom), float(zoom))
            cen = c.get("center", [0.5, 0.5])
            cen = (tuple(cen[0]), tuple(cen[1])) if isinstance(cen[0], list) else (tuple(cen), tuple(cen))
            rot = c.get("rot", 0.0)
            rot = tuple(math.radians(x) for x in rot) if isinstance(rot, list) else (math.radians(rot),) * 2
            clip = Clip(idx=i, src_frame=sf, start=start, end=end, speed=float(c.get("speed", 1.0)),
                        rife=bool(c.get("rife", False)), reverse=bool(c.get("reverse", False)), ramp=c.get("ramp"),
                        grade=c.get("grade", self.p.get("grade", "storybook")), look=c.get("look", {}), zoom=zoom,
                        center=cen, rot=rot, ease=c.get("ease", "inout"), tx=self._tx(c.get("tx")),
                        shot_lo=lo, shot_hi=hi, flash_in=float(c.get("flash", 0.0)), freeze=bool(c.get("freeze", False)),
                        fade_in=float(c.get("fade_in", 0.0)), fade_out=float(c.get("fade_out", 0.0)),
                        note=c.get("note", ""))
            if c.get("unclamp"):
                clip.shot_lo, clip.shot_hi = 0, 1 << 30
            if clip.tx and prev is not None:
                d, align = clip.tx[1], clip.tx[3]
                if align == "center":
                    clip.pre, prev.post = d / 2, d / 2
                elif align == "start":          # transition begins at the cut
                    clip.pre, prev.post = 0.0, d
                else:                           # 'end': transition finishes at the cut
                    clip.pre, prev.post = d, 0.0
            self.clips.append(clip)
            prev = clip
            t = end
        self.duration = max((c.end + c.post for c in self.clips), default=0.0)
        for j, c in enumerate(self.cfg.get("layers", [])):
            start = self.anchor(c["at"])
            end = self.anchor(c["to"]) if "to" in c else start + self.length(start, c["len"])
            sf = self.src_point(c["src"])
            lo, hi = self.shot_of(sf + 0.5)
            zoom = c.get("zoom", 1.0)
            zoom = tuple(zoom) if isinstance(zoom, list) else (float(zoom), float(zoom))
            cen = c.get("center", [0.5, 0.5])
            cen = (tuple(cen[0]), tuple(cen[1])) if isinstance(cen[0], list) else (tuple(cen), tuple(cen))
            lay = Clip(idx=1000 + j, src_frame=sf, start=start, end=end, speed=float(c.get("speed", 1.0)),
                       rife=bool(c.get("rife", False)), grade=c.get("grade", "dream"), look=c.get("look", {}),
                       zoom=zoom, center=cen, shot_lo=lo, shot_hi=hi, layer=1,
                       mode={"mix": 0, "add": 1, "screen": 2, "lumascreen": 3, "multiply": 4}[c.get("mode", "screen")],
                       opacity=float(c.get("opacity", 0.5)), fade_in=float(c.get("fade_in", 0.5)),
                       fade_out=float(c.get("fade_out", 0.5)))
            self.clips.append(lay)
        for o in self.cfg.get("overlays", []):
            start = self.anchor(o["at"])
            end = self.anchor(o["to"]) if "to" in o else start + self.length(start, o.get("len", 1.0))
            self.overlays.append(Overlay(o["kind"], start, end, o))
        for k in self.cfg.get("finish_keys", []):
            self.finish_keys.append((self.anchor(k["at"]), {kk: v for kk, v in k.items() if kk != "at"}))
        self.finish_keys.sort(key=lambda x: x[0])
        if "duration" in self.p:
            self.duration = self.anchor(self.p["duration"])

    # ---- per-frame queries -------------------------------------------------
    def finish_at(self, t: float) -> dict:
        base = dict(self.p.get("finish", {}))
        keys = self.finish_keys
        if not keys:
            return base
        names = set()
        for _, d in keys:
            names.update(d.keys())
        for n in names:
            pts = [(tt, d[n]) for tt, d in keys if n in d]
            if t <= pts[0][0]:
                base[n] = pts[0][1]
            elif t >= pts[-1][0]:
                base[n] = pts[-1][1]
            else:
                for (t0, v0), (t1, v1) in zip(pts, pts[1:], strict=False):
                    if t0 <= t <= t1:
                        u = (t - t0) / max(t1 - t0, 1e-9)
                        u = u * u * (3 - 2 * u)
                        if isinstance(v0, (list, tuple)):
                            base[n] = tuple(a + (b - a) * u for a, b in zip(v0, v1, strict=True))
                        else:
                            base[n] = v0 + (v1 - v0) * u
                        break
        return base


def ease(u: float, kind: str = "inout") -> float:
    u = min(1.0, max(0.0, u))
    if kind == "linear":
        return u
    if kind == "in":
        return u * u
    if kind == "out":
        return 1 - (1 - u) * (1 - u)
    return u * u * (3 - 2 * u)


def src_pos(clip: Clip, t: float, src_fps: float) -> float:
    """Fractional source frame shown at output time t (t may be inside the handles)."""
    if clip.freeze:
        return clip.src_frame
    dt = t - clip.start
    if clip.ramp:
        # integrate a piecewise-linear speed curve over [0, dt] (fractions of the nominal clip length)
        L = clip.end - clip.start
        pts = [(float(a), float(b)) for a, b in clip.ramp]
        n = max(8, int(abs(dt) * 240))
        acc = 0.0
        sgn = 1.0 if dt >= 0 else -1.0
        for k in range(n):
            x = (k + 0.5) / n * abs(dt) * sgn
            u = x / L
            if u <= pts[0][0]:
                sp = pts[0][1]
            elif u >= pts[-1][0]:
                sp = pts[-1][1]
            else:
                sp = pts[-1][1]
                for (u0, s0), (u1, s1) in zip(pts, pts[1:], strict=False):
                    if u0 <= u <= u1:
                        sp = s0 + (s1 - s0) * (u - u0) / max(u1 - u0, 1e-9)
                        break
            acc += sp * abs(dt) / n * sgn
        adv = acc
    else:
        adv = dt * clip.speed
    pos = clip.src_frame + (-adv if clip.reverse else adv) * src_fps
    return min(max(pos, clip.shot_lo), clip.shot_hi)
