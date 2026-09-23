#!/usr/bin/env python3
"""mist-ytp: script-driven YouTube Poop renderer.

A project is one YAML file. It names the source videos, and its `timeline` is a
list of one-line items (clips, word-level sentence mixes, freeze frames, title
cards), each with an optional chain of effects. Everything renders through
ffmpeg; faster-whisper supplies word timestamps for sentence mixing.

    mist-ytp index  PROJECT.yaml          # subtitles -> work/lines.tsv
    mist-ytp grep   PROJECT.yaml REGEX    # find lines with timestamps
    mist-ytp align  PROJECT.yaml S01E03@12:34 [...]   # word timestamps near a time
    mist-ytp render PROJECT.yaml [-o out.mp4] [--items 3-9]

See README.md for the item grammar and the effect list.

INVARIANTS
- Every rendered item is exactly N video frames and N * samples_per_frame audio
  samples (48 kHz, stereo, PCM), so items concatenate by stream copy with no
  drift. Anything that changes duration must restore this before returning.
- Intermediates are cached by a hash of everything that shapes them; a changed
  item re-renders, an unchanged one is reused. The hash sees effect NAMES and
  args, not their filter code: bump VERSION whenever an effect's implementation
  changes, or stale renders survive.
"""
from __future__ import annotations

import argparse
import fnmatch
import glob
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import NoReturn

import yaml

HERE = Path(__file__).resolve().parent
SR = 48000
FONT_DIR = Path("/System/Library/Fonts/Supplemental")
FONTS = {
    "impact": FONT_DIR / "Impact.ttf",
    "comic": FONT_DIR / "Comic Sans MS Bold.ttf",
    "arialblack": FONT_DIR / "Arial Black.ttf",
}


# ---------------------------------------------------------------- utilities

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def output_lock(path: Path) -> threading.Lock:
    """One lock per cache file: items that share a slice render it once."""
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(str(path), threading.Lock())


def die(msg: str) -> NoReturn:
    sys.exit(f"mist-ytp: {msg}")


def run(cmd: list[str], quiet: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-12:])
        die(f"command failed ({p.returncode}): {shlex.join(cmd)[:600]}\n{tail}")
    if not quiet and p.stderr:
        print(p.stderr, file=sys.stderr)
    return p


def parse_time(s: str | float | int) -> float:
    """'1:02:03.5', '12:34.25', '754.25' -> seconds."""
    if isinstance(s, (int, float)):
        return float(s)
    parts = str(s).strip().split(":")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    return secs


def fmt_time(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def ffprobe_json(path: str | Path, *args: str) -> dict:
    p = run(["ffprobe", "-v", "error", "-of", "json", *args, str(path)])
    return json.loads(p.stdout or "{}")


# ---------------------------------------------------------------- project

@dataclass
class Project:
    path: Path
    data: dict
    work: Path = field(init=False)
    sources: dict[str, Path] = field(init=False)
    fps: Fraction = field(init=False)
    size: tuple[int, int] = field(init=False)

    def __post_init__(self) -> None:
        self.work = (self.path.parent / self.data.get("work", "work")).resolve()
        self.work.mkdir(parents=True, exist_ok=True)
        self.fps = Fraction(str(self.data.get("fps", "24000/1001")))
        w, h = self.data.get("size", [1280, 720])
        self.size = (int(w), int(h))
        self.sources = self._resolve_sources()

    @property
    def spf(self) -> int:
        """Audio samples per video frame; must be an integer (see INVARIANTS)."""
        v = Fraction(SR) / self.fps
        if v.denominator != 1:
            die(f"fps {self.fps} does not divide {SR} Hz into whole samples")
        return int(v)

    def _resolve_sources(self) -> dict[str, Path]:
        src = self.data.get("sources", {})
        out: dict[str, Path] = {}
        pattern = os.path.expanduser(src.get("glob", ""))
        key_re = re.compile(src.get("key", r"S\d\dE\d\d"), re.I)
        for f in sorted(glob.glob(pattern)):
            m = key_re.search(os.path.basename(f))
            key = m.group(0).upper() if m else Path(f).stem
            out[key] = Path(f)
        for key, f in (src.get("files") or {}).items():
            out[str(key).upper()] = Path(os.path.expanduser(f))
        return out

    def source(self, key: str) -> Path:
        k = key.upper()
        if k not in self.sources:
            die(f"unknown source {key!r}; known: {', '.join(sorted(self.sources)) or 'none'}")
        if not self.sources[k].exists():
            die(f"source {key} is not reachable: {self.sources[k]} (drive unmounted?)")
        return self.sources[k]

    def sub_stream(self, key: str) -> str | None:
        table = (self.data.get("sources") or {}).get("subs") or {}
        for pat, idx in table.items():
            if pat != "default" and fnmatch.fnmatch(key, pat):
                return str(idx)
        d = table.get("default")
        return None if d is None else str(d)


def load_project(path: str) -> Project:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        die(f"no project file at {p}")
    return Project(p, yaml.safe_load(p.read_text()) or {})


# ---------------------------------------------------------------- index / grep

TAG_RE = re.compile(r"<[^>]+>|\{[^}]*\}")


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        for i, l in enumerate(lines):
            if "-->" in l:
                a, b = (x.strip().replace(",", ".") for x in l.split("-->")[:2])
                body = " ".join(TAG_RE.sub("", x).strip() for x in lines[i + 1:])
                if body:
                    cues.append((parse_time(a), parse_time(b.split()[0]), body))
                break
    return cues


def cmd_index(args: argparse.Namespace) -> None:
    proj = load_project(args.project)
    subs = proj.work / "subs"
    subs.mkdir(exist_ok=True)
    rows = []
    for key, f in sorted(proj.sources.items()):
        srt = subs / f"{key}.srt"
        if not srt.exists() or args.force:
            stream = proj.sub_stream(key)
            m = f"0:{stream}" if stream is not None else "0:s:0"
            run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-map", m, "-c:s", "srt", str(srt)])
        cues = parse_srt(srt.read_text(errors="replace"))
        rows += [(key, a, b, t) for a, b, t in cues]
        print(f"{key}: {len(cues)} lines")
    with open(proj.work / "lines.tsv", "w") as fh:
        for key, a, b, t in rows:
            fh.write(f"{key}\t{a:.3f}\t{b:.3f}\t{t}\n")
    print(f"wrote {len(rows)} lines -> {proj.work / 'lines.tsv'}")


def read_lines(proj: Project) -> list[tuple[str, float, float, str]]:
    f = proj.work / "lines.tsv"
    if not f.exists():
        die("no line index yet; run `mist-ytp index` first")
    out = []
    for row in f.read_text().splitlines():
        key, a, b, t = row.split("\t", 3)
        out.append((key, float(a), float(b), t))
    return out


def cmd_grep(args: argparse.Namespace) -> None:
    proj = load_project(args.project)
    rows = read_lines(proj)
    rx = re.compile(args.pattern, re.I)
    for i, (key, _a, _b, t) in enumerate(rows):
        if args.only and not fnmatch.fnmatch(key, args.only.upper()):
            continue
        if rx.search(t):
            lo, hi = max(0, i - args.context), min(len(rows), i + args.context + 1)
            for j in range(lo, hi):
                k2, a2, b2, t2 = rows[j]
                if k2 != key:
                    continue
                mark = ">" if j == i else " "
                print(f"{mark} {k2} {fmt_time(a2)}-{fmt_time(b2)}  {t2}")
            if args.context:
                print()


# ---------------------------------------------------------------- word alignment

_MODEL = None


def whisper_model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        name = os.environ.get("MIST_YTP_WHISPER", "small.en")
        _MODEL = WhisperModel(name, device="cpu", compute_type="int8")
    return _MODEL


def norm_word(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def audio_channels(proj: Project, key: str, _cache: dict = {}) -> int:  # noqa: B006 (memo)
    if key not in _cache:
        info = ffprobe_json(proj.source(key), "-select_streams", "a:0",
                            "-show_entries", "stream=channels")
        _cache[key] = int((info.get("streams") or [{}])[0].get("channels", 2))
    return _cache[key]


def dialog_pan(ch: int, dry: bool = False) -> str:
    """Stereo downmix that favours the dialogue. `dry` keeps only the centre
    channel, which on a 5.1 mix is mostly voice with the score removed."""
    if ch >= 6:
        if dry:
            return "pan=stereo|FL=FC|FR=FC,"
        return "pan=stereo|FL<1.0*FC+0.6*FL+0.35*SL|FR<1.0*FC+0.6*FR+0.35*SR,"
    if ch == 1:
        return "pan=stereo|FL=c0|FR=c0,"
    return ""


def words_file(proj: Project, key: str) -> Path:
    d = proj.work / "words"
    d.mkdir(exist_ok=True)
    return d / f"{key}.json"


def align_window(proj: Project, key: str, a: float, b: float) -> list[dict]:
    """Word timestamps for [a, b) of a source, cached per window."""
    f = words_file(proj, key)
    cache = json.loads(f.read_text()) if f.exists() else {"windows": []}
    for w in cache["windows"]:
        if w["a"] <= a + 0.01 and w["b"] >= b - 0.01:
            return w["words"]
    tmp = proj.work / "tmp"
    tmp.mkdir(exist_ok=True)
    wav = tmp / f"align_{key}_{a:.2f}.wav"
    ch = audio_channels(proj, key)
    pan = "pan=mono|c0=FC" if ch >= 6 else "pan=mono|c0=0.5*c0+0.5*c1" if ch == 2 else "anull"
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i",
         str(proj.source(key)), "-map", "0:a:0", "-af", pan, "-ar", "16000", "-ac", "1", str(wav)])
    prompt = " ".join(t for k, s, e, t in read_lines(proj) if k == key and e > a and s < b)
    segs, _ = whisper_model().transcribe(
        str(wav), language="en", word_timestamps=True, beam_size=5,
        initial_prompt=prompt[:600] or None, condition_on_previous_text=False)
    words = [{"w": w.word.strip(), "s": round(a + w.start, 3), "e": round(a + w.end, 3),
              "p": round(w.probability, 2)} for s in segs for w in (s.words or [])]
    wav.unlink(missing_ok=True)
    cache["windows"].append({"a": round(a, 3), "b": round(b, 3), "words": words})
    f.write_text(json.dumps(cache))
    return words


def refine_bounds(proj: Project, key: str, s: float, e: float) -> tuple[float, float]:
    """Snap a phrase's edges to the pauses around it.

    Whisper's word edges drift 0.1-0.4 s before a pause (it tends to hand the
    silence to the next word, cutting "compu-ter" short). On the dialogue
    channel, a real pause is >= 80 ms well below the phrase's peak, while the
    stop-consonant gaps inside a word last 40-60 ms. An edge that lands in
    silence walks to the nearest voiced frame; an edge that lands in speech
    walks outward to the first such pause within reach. With no pause in reach
    (connected speech) whisper's edge stands, lightly padded.
    """
    import wave

    import numpy as np

    lo, hi = max(0.0, s - 0.3), e + 0.5
    tmp = proj.work / "tmp"
    tmp.mkdir(exist_ok=True)
    wav = tmp / f"edge_{key}_{s:.3f}_{os.getpid()}.wav"
    ch = audio_channels(proj, key)
    pan = "pan=mono|c0=FC" if ch >= 6 else "pan=mono|c0=0.5*c0+0.5*c1" if ch == 2 else "anull"
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{lo:.3f}", "-t", f"{hi - lo:.3f}", "-i",
         str(proj.source(key)), "-map", "0:a:0", "-af", pan, "-ar", "16000", "-ac", "1", str(wav)])
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    wav.unlink(missing_ok=True)
    hop = 160                                   # 10 ms at 16 kHz
    n = len(x) // hop
    if n < 10:
        return s - 0.02, e + 0.03
    db = 20 * np.log10(np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    t = lambda i: lo + i * 0.01
    ix = lambda sec: int(min(n - 1, max(0, round((sec - lo) / 0.01))))
    inside = db[ix(s):ix(e) + 1]
    peak = float(inside.max()) if inside.size else float(db.max())
    thr = max(peak - 36, float(np.percentile(db, 10)) + 8)
    quiet = db < thr
    run_len = 8                                 # 80 ms
    i_s, i_e = ix(s), ix(e)
    # end: inside silence -> back up to the last voiced frame; inside speech -> forward to the next pause
    if quiet[max(0, i_e - 3):i_e + 1].all():
        j = i_e
        while j > i_s and quiet[j]:
            j -= 1
        new_e = t(j) + 0.05
    else:
        new_e = e + 0.03
        for k in range(max(i_s, i_e - 12), min(n - run_len, ix(e + 0.45)) + 1):
            if quiet[k:k + run_len].all():
                new_e = t(k) + 0.02
                break
    # start: inside silence -> forward to the onset; inside speech -> back to the pause before it
    if quiet[i_s:i_s + 4].all():
        k = i_s
        while k < i_e and quiet[k]:
            k += 1
        new_s = t(k) - 0.03
    else:
        new_s = s - 0.02
        for k in range(i_s, max(run_len, ix(s - 0.2)) - 1, -1):
            if quiet[k - run_len:k].all():
                new_s = t(k) - 0.01
                break
    return max(0.0, new_s), max(new_e, new_s + 0.06)


def find_phrase(proj: Project, key: str, at: float, phrase: str, radius: float = 8.0,
                refine: bool = True) -> tuple[float, float]:
    """(start, end) of `phrase` spoken nearest `at`. Matches across whisper's
    word splits by comparing concatenated normalised text, then snaps the
    edges to the surrounding pauses (refine_bounds)."""
    words = len(phrase.split())
    try:
        s, e = _find_phrase_raw(proj, key, at, phrase, radius)
        if e - s > 0.45 * words + 0.9:          # whisper stretched a word over silence
            raise LookupError(f"whisper span {e - s:.1f}s is implausible for {words} word(s)")
    except LookupError as why:
        s, e = _find_phrase_in_subs(proj, key, at, phrase, radius, str(why))
    if not refine:
        return s, e
    f = proj.work / "words" / "refined.json"
    cache = json.loads(f.read_text()) if f.exists() else {}
    k = f"{key}:{s:.3f}:{e:.3f}"
    if k not in cache:
        cache[k] = refine_bounds(proj, key, s, e)
        f.write_text(json.dumps(cache))
    return tuple(cache[k])


def _find_phrase_raw(proj: Project, key: str, at: float, phrase: str, radius: float) -> tuple[float, float]:
    a = max(0.0, at - radius)
    words = align_window(proj, key, a, at + radius)
    target = norm_word(phrase)
    best: tuple[float, float, float] | None = None
    for i in range(len(words)):
        acc = ""
        for j in range(i, min(len(words), i + 12)):
            acc += norm_word(words[j]["w"])
            if acc == target:
                s, e = words[i]["s"], words[j]["e"]
                d = abs((s + e) / 2 - at)
                if best is None or d < best[0]:
                    best = (d, s, e)
                break
            if not target.startswith(acc):
                break
    if best is None:
        near = " ".join(f"{w['w']}@{fmt_time(w['s'])}" for w in words if abs(w["s"] - at) < 4)
        raise LookupError(f"whisper heard: {near or '(nothing)'}")
    return best[1], best[2]


def _find_phrase_in_subs(proj: Project, key: str, at: float, phrase: str, radius: float,
                         why: str) -> tuple[float, float]:
    """Fallback when whisper misses a line: place the phrase inside the subtitle
    cue(s) that contain it, by character position. Coarse; refine_bounds then
    snaps the edges to the actual speech."""
    target = norm_word(phrase)
    cues = [(a, b, t) for k, a, b, t in read_lines(proj) if k == key and b > at - radius and a < at + radius]
    best: tuple[float, float, float] | None = None
    for i in range(len(cues)):
        for j in range(i, min(len(cues), i + 2)):          # a phrase may straddle two cues
            span = cues[i:j + 1]
            chars: list[float] = []                       # time of each normalised char
            for a, b, t in span:
                nt = norm_word(t)
                chars += [a + (b - a) * (c / max(1, len(nt))) for c in range(len(nt))]
            text = "".join(norm_word(t) for _, _, t in span)
            pos = text.find(target)
            if pos < 0:
                continue
            s = chars[pos]
            e = chars[pos + len(target) - 1] + (span[-1][1] - span[-1][0]) / max(1, len(norm_word(span[-1][2])))
            d = abs((s + e) / 2 - at)
            if best is None or d < best[0]:
                best = (d, s, e)
    if best is None:
        die(f"{key}@{fmt_time(at)}: no {phrase!r} within {radius}s ({why}; not in subtitles either)")
    print(f"  note: {key}@{fmt_time(at)} {phrase!r} placed from subtitles ({why[:80]})", file=sys.stderr)
    return best[1], best[2]


def cmd_align(args: argparse.Namespace) -> None:
    proj = load_project(args.project)
    for spec in args.at:
        key, t = spec.split("@", 1)
        key, at = key.upper(), parse_time(t)
        words = align_window(proj, key, max(0.0, at - args.window), at + args.window)
        print(f"== {key} around {fmt_time(at)}")
        print("  " + "  ".join(f"{w['w']}[{fmt_time(w['s'])}-{w['e'] - w['s']:.2f}]" for w in words))


def speech_level(path: Path) -> float:
    """Speech-ish level of a file's audio: the 90th percentile of 50 ms RMS frames
    (dBFS). Mean level is useless for YTP slices: half of a 1 s cut can be silence."""
    import numpy as np

    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
                        "-ar", "16000", "-f", "s16le", "-"], capture_output=True)
    x = np.frombuffer(p.stdout, dtype=np.int16).astype(np.float32) / 32768
    n = len(x) // 800
    if n == 0:
        return -90.0
    db = 20 * np.log10(np.sqrt((x[:n * 800].reshape(n, 800) ** 2).mean(1)) + 1e-9)
    return float(np.percentile(db, 90)) if n >= 4 else float(db.max())


def level_gain(path: Path, target: float) -> float:
    lvl = speech_level(path)
    return 0.0 if lvl < -70 else max(-12.0, min(20.0, target - lvl))


# ---------------------------------------------------------------- timeline grammar

@dataclass
class Fx:
    name: str
    args: list[str]

    def num(self, i: int, default: float) -> float:
        return float(self.args[i]) if len(self.args) > i else default


@dataclass
class Part:
    """One source-backed slice: `KEY START-END`, `KEY START+DUR`, or `KEY@TIME "phrase"`."""
    key: str
    t0: float
    t1: float
    fx: list[Fx]
    spec: str


@dataclass
class Item:
    kind: str                 # clip | mix | freeze | card | still | file
    spec: str
    fx: list[Fx]
    parts: list[Part] = field(default_factory=list)
    args: list[str] = field(default_factory=list)


def split_top(s: str, sep: str) -> list[str]:
    """Split on `sep` outside quotes and [brackets]."""
    out, cur, q, depth, i = [], "", "", 0, 0
    while i < len(s):
        c = s[i]
        if q:
            q = "" if c == q else q
        elif c in "\"'":
            q = c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        elif depth == 0 and s.startswith(sep, i):
            out.append(cur); cur = ""; i += len(sep); continue
        cur += c; i += 1
    out.append(cur)
    return [x.strip() for x in out if x.strip()]


def parse_fx(s: str) -> list[Fx]:
    out = []
    for chunk in split_top(s, ";"):
        toks = shlex.split(chunk)
        if toks:
            out.append(Fx(toks[0].lower(), toks[1:]))
    return out


def parse_range(tok: str) -> tuple[float, float]:
    if "+" in tok:
        a, d = tok.split("+", 1)
        return parse_time(a), parse_time(a) + float(d)
    a, b = tok.split("-", 1)
    return parse_time(a), parse_time(b)


def parse_part(proj: Project, s: str) -> Part:
    fx: list[Fx] = []
    m = re.match(r"^(.*?)\s*\[(.*)\]\s*$", s)
    if m:
        s, fx = m.group(1), parse_fx(m.group(2))
    toks = shlex.split(s)
    if not toks:
        die(f"empty part in {s!r}")
    if "@" in toks[0]:
        key, t = toks[0].split("@", 1)
        if len(toks) < 2:
            die(f"{s!r}: KEY@TIME needs a quoted phrase")
        t0, t1 = find_phrase(proj, key.upper(), parse_time(t), " ".join(toks[1:]),
                             refine=not any(f.name == "raw" for f in fx))
        return Part(key.upper(), t0, t1, fx, s)
    if len(toks) != 2:
        die(f"can't parse part {s!r}; want KEY START-END or KEY@TIME \"phrase\"")
    t0, t1 = parse_range(toks[1])
    return Part(toks[0].upper(), t0, t1, fx, s)


def parse_item(proj: Project, spec: str) -> Item:
    chunks = split_top(spec, "|")
    head, fx = chunks[0], parse_fx(" ; ".join(chunks[1:])) if len(chunks) > 1 else []
    word = head.split(None, 1)[0].lower()
    if word in ("card", "black", "still", "freeze", "file", "credits"):
        return Item(word, spec, fx, args=shlex.split(head)[1:])
    if word == "mix":
        parts = [parse_part(proj, p) for p in split_top(head[3:], "/")]
        return Item("mix", spec, fx, parts=parts)
    return Item("clip", spec, fx, parts=[parse_part(proj, head)])


# ---------------------------------------------------------------- rendering

STRUCTURAL = {"stutter", "stutterend", "loop", "pingpong", "reverse", "rev", "speed",
              "tempo", "hold", "prehold", "cut", "trim"}
MIXING = {"sfx", "music"}
BASE_MODS = {"pad", "dry", "raw", "nolevel", "font", "size", "fg", "bg"}


def render_text_png(out: Path, text: str, size: tuple[int, int], font: str, px: int,
                    fg: str, where: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    W, H = size
    face = ImageFont.truetype(str(FONTS.get(font, Path(font))), px)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if cur and d.textlength(trial, font=face) > W * 0.9:
                lines.append(cur); cur = word
            else:
                cur = trial
        lines.append(cur)
    body = "\n".join(lines)
    sw = max(2, px // 12)
    colour = "#" + fg[2:] if fg.lower().startswith("0x") else fg
    x0, y0, x1, y1 = d.multiline_textbbox((0, 0), body, font=face, stroke_width=sw, align="center",
                                          spacing=px // 6)
    tw, th = x1 - x0, y1 - y0
    y = {"top": H * 0.06, "bottom": H - th - H * 0.07}.get(where, (H - th) / 2)
    d.multiline_text(((W - tw) / 2 - x0, y - y0), body, font=face, fill=colour, stroke_width=sw,
                     stroke_fill="black", align="center", spacing=px // 6)
    img.save(out)


class Renderer:
    def __init__(self, proj: Project, jobs: int = 3):
        self.p = proj
        self.jobs = jobs
        self.cache = proj.work / "cache"
        self.cache.mkdir(exist_ok=True)
        self.W, self.H = proj.size
        self.fps = proj.fps
        self.label = 0

    # -- plumbing ------------------------------------------------------

    def key(self, *parts: object) -> str:
        h = hashlib.sha1(repr((VERSION, self.p.size, str(self.fps)) + parts).encode())
        return h.hexdigest()[:16]

    def resolve(self, name: str) -> str:
        """A path-looking argument, relative to the project file; else unchanged (a colour)."""
        if "/" not in name and "." not in name:
            return name
        p = Path(name).expanduser()
        return str(p if p.is_absolute() else self.p.path.parent / p)

    def frames(self, secs: float) -> int:
        return max(1, round(secs * self.fps))

    def secs(self, n: int) -> float:
        return float(n / self.fps)

    def vtail(self, n: int) -> str:
        return (f"fps={self.fps},tpad=stop_mode=clone:stop_duration=30,"
                f"trim=end_frame={n},setpts=N/FRAME_RATE/TB,format=yuv420p")

    def atail(self, n: int) -> str:
        ns = n * self.p.spf
        return (f"aresample={SR},aformat=sample_rates={SR}:channel_layouts=stereo,"
                f"apad=whole_len={ns},atrim=end_sample={ns},asetpts=N/SR/TB")

    def declick(self, n: int) -> str:
        d = self.secs(n)
        f = min(0.005, d / 4)
        return f"afade=t=in:d={f:.4f},afade=t=out:st={d - f:.4f}:d={f:.4f},"

    ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-bf", "0",
           "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-ar", str(SR), "-ac", "2"]

    def encode(self, out: Path, inputs: list[str], vf: str, af: str, n: int) -> Path:
        with output_lock(out):
            if out.exists():
                return out
            tmp = out.with_suffix(f".part{threading.get_ident()}.mkv")
            run(["ffmpeg", "-v", "error", "-y", "-threads", "3", *inputs,
                 "-filter_complex", f"[0:v]{vf},{self.vtail(n)}[v];[{self.ain}:a]{af}{self.atail(n)}[a]",
                 "-map", "[v]", "-map", "[a]", "-frames:v", str(n), *self.ENC, str(tmp)])
            os.replace(tmp, out)
        return out

    ain = 0  # input index carrying audio; overridden for synthetic sources

    def concat(self, files: list[Path], out: Path) -> Path:
        with output_lock(out):
            if out.exists() and out.name != "timeline.mkv":
                return out
            tag = threading.get_ident()
            lst = out.with_suffix(f".{tag}.txt")
            lst.write_text("".join(f"file '{f}'\n" for f in files))
            tmp = out.with_suffix(f".part{tag}.mkv")
            run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                 "-c", "copy", str(tmp)])
            os.replace(tmp, out); lst.unlink()
        return out

    # -- bases -----------------------------------------------------------

    def source_slice(self, part: Part, extra_fx: list[Fx]) -> tuple[Path, int]:
        pad = next((f for f in part.fx + extra_fx if f.name == "pad"), None)
        dry = any(f.name == "dry" for f in part.fx + extra_fx)
        t0 = part.t0 - (pad.num(0, 0) if pad else 0.0)
        t1 = part.t1 + (pad.num(1, 0) if pad else 0.0)
        n = self.frames(t1 - t0)
        lvl = None if any(f.name == "nolevel" for f in part.fx + extra_fx) else self.p.data.get("level", -20)
        out = self.cache / f"src_{self.key('src', part.key, round(t0, 3), n, dry, lvl)}.mkv"
        if out.exists():
            return out, n
        ch = audio_channels(self.p, part.key)
        self.ain = 0
        vf = f"scale={self.W}:{self.H}:flags=bicubic,setsar=1"
        af = dialog_pan(ch, dry) + self.declick(n)
        target = self.p.data.get("level", -20)
        if target is None or any(f.name == "nolevel" for f in part.fx + extra_fx):
            return self.encode(out, ["-ss", f"{max(0.0, t0):.3f}", "-i", str(self.p.source(part.key))],
                               vf, af, n), n
        raw = self.encode(out.with_name(out.stem + "_raw.mkv"),
                          ["-ss", f"{max(0.0, t0):.3f}", "-i", str(self.p.source(part.key))], vf, af, n)
        with output_lock(out):
            if not out.exists():
                g = level_gain(raw, float(target))
                tmp = out.with_suffix(f".part{threading.get_ident()}.mkv")
                run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-map", "0", "-c:v", "copy",
                     "-af", f"volume={g:.2f}dB", "-c:a", "pcm_s16le", str(tmp)])
                os.replace(tmp, out)
        return out, n

    def text_filter(self, text: str, font: str, size: int, fg: str, where: str = "center") -> str:
        """Text as a full-frame transparent PNG (Pillow), overlaid via `movie`.
        This ffmpeg build has no drawtext (no freetype)."""
        png = self.cache / f"txt_{self.key('txt', text, font, size, fg, where)}.png"
        if not png.exists():
            render_text_png(png, text.replace("\\n", "\n"), (self.W, self.H), font, size, fg, where)
        self.label += 1
        L = f"t{self.label}"
        return f"null[{L}a];movie='{png}',format=rgba[{L}b];[{L}a][{L}b]overlay=0:0"

    def card(self, item: Item) -> tuple[Path, int]:
        dur = float(item.args[0]) if item.args else 2.0
        text = item.args[1] if len(item.args) > 1 and item.kind == "card" else ""
        opt = {f.name: f.args for f in item.fx}
        bg = self.resolve((opt.get("bg") or ["black"])[0])
        n = self.frames(dur)
        out = self.cache / f"card_{self.key('card', text, n, sorted(opt.items()))}.mkv"
        if out.exists():
            return out, n
        vf = "null"
        if text:
            vf = self.text_filter(text, (opt.get("font") or ["impact"])[0],
                                  int((opt.get("size") or [72])[0]), (opt.get("fg") or ["white"])[0])
        self.ain = 1
        src = (["-loop", "1", "-framerate", str(self.fps), "-i", bg] if os.path.exists(bg)
               else ["-f", "lavfi", "-i", f"color=c={bg}:s={self.W}x{self.H}:r={self.fps}"])
        vf = f"scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H},{vf}"
        return self.encode(out, [*src, "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo"], vf, "", n), n

    def freeze(self, item: Item) -> tuple[Path, int]:
        key, t, dur = item.args[0].upper(), parse_time(item.args[1]), float(item.args[2])
        n = self.frames(dur)
        out = self.cache / f"frz_{self.key('frz', key, t, n)}.mkv"
        if out.exists():
            return out, n
        png = self.cache / f"frz_{self.key('png', key, t)}.png"
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(self.p.source(key)),
             "-map", "0:v:0", "-frames:v", "1", "-vf", f"scale={self.W}:{self.H}", str(png)])
        self.ain = 1
        return self.encode(out, ["-loop", "1", "-framerate", str(self.fps), "-i", str(png),
                                 "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo"], "null", "", n), n

    def media_file(self, item: Item) -> tuple[Path, int]:
        """`file PATH [START-END]`: any audio/video file; audio-only gets `bg` behind it."""
        path = Path(item.args[0]).expanduser()
        if not path.is_absolute():
            path = self.p.path.parent / path
        info = ffprobe_json(path, "-show_entries", "format=duration:stream=codec_type")
        dur = float(info["format"]["duration"])
        t0, t1 = parse_range(item.args[1]) if len(item.args) > 1 else (0.0, dur)
        n = self.frames(t1 - t0)
        opt = {f.name: f.args for f in item.fx}
        bg = self.resolve((opt.get("bg") or ["black"])[0])
        out = self.cache / f"file_{self.key('file', str(path), path.stat().st_mtime, t0, n, bg)}.mkv"
        if out.exists():
            return out, n
        has_v = any(s.get("codec_type") == "video" for s in info.get("streams", []))
        if has_v:
            self.ain = 0
            ins = ["-ss", f"{t0:.3f}", "-i", str(path)]
        else:
            self.ain = 1
            bgsrc = (["-loop", "1", "-framerate", str(self.fps), "-i", bg] if os.path.exists(bg)
                     else ["-f", "lavfi", "-i", f"color=c={bg}:s={self.W}x{self.H}:r={self.fps}"])
            ins = [*bgsrc, "-ss", f"{t0:.3f}", "-i", str(path)]
        vf = f"scale={self.W}:{self.H}:force_original_aspect_ratio=increase,crop={self.W}:{self.H}"
        return self.encode(out, ins, vf, self.declick(n), n), n

    # -- effects ---------------------------------------------------------

    def vfx(self, fx: Fx, n: int) -> str:
        W, H, D = self.W, self.H, self.secs(n)
        a, name = fx.args, fx.name
        self.label += 1
        L = f"m{self.label}"
        if name == "invert": return "negate"
        if name == "hflip": return "hflip"
        if name == "vflip": return "vflip"
        if name == "mirror":
            return f"crop=iw/2:ih:0:0,split[{L}a][{L}b];[{L}b]hflip[{L}c];[{L}a][{L}c]hstack"
        if name == "mirrorr":
            return f"crop=iw/2:ih:iw/2:0,split[{L}a][{L}b];[{L}b]hflip[{L}c];[{L}c][{L}a]hstack"
        if name == "mirrorv":
            return f"crop=iw:ih/2:0:0,split[{L}a][{L}b];[{L}b]vflip[{L}c];[{L}a][{L}c]vstack"
        if name == "zoom":
            z, x, y = fx.num(0, 2), fx.num(1, .5), fx.num(2, .5)
            return f"crop=iw/{z}:ih/{z}:(iw-iw/{z})*{x}:(ih-ih/{z})*{y},scale={W}:{H}"
        if name in ("zoomin", "zoomout"):
            z, x, y = fx.num(0, 2.5), fx.num(1, .5), fx.num(2, .5)
            prog = f"(on/{max(1, n - 1)})" if name == "zoomin" else f"(1-on/{max(1, n - 1)})"
            return (f"scale={W * 2}:{H * 2},zoompan=z='1+({z}-1)*{prog}':d=1:s={W}x{H}:fps={self.fps}:"
                    f"x='(iw-iw/zoom)*{x}':y='(ih-ih/zoom)*{y}'")
        if name == "shake":
            s = int(fx.num(0, 24))
            return (f"crop=iw-{2 * s}:ih-{2 * s}:'{s}+{s}*(2*random(1)-1)':'{s}+{s}*(2*random(2)-1)',"
                    f"scale={W}:{H}")
        if name == "deepfry":
            return ("eq=contrast=2.0:saturation=3.2:brightness=0.05,unsharp=9:9:2.6,noise=alls=22:allf=t,"
                    f"scale=iw/3:ih/3,scale={W}:{H}:flags=neighbor")
        if name == "rainbow": return f"hue=h=t*{fx.num(0, 720)}:s=2.2"
        if name == "hue": return f"hue=h={fx.num(0, 180)}"
        if name == "chroma":
            px = int(fx.num(0, 14))
            return f"rgbashift=rh=-{px}:bh={px}:gv={px // 2}"
        if name == "pixelate":
            k = fx.num(0, 16)
            return f"scale=iw/{k}:ih/{k},scale={W}:{H}:flags=neighbor"
        if name == "edge": return "edgedetect=low=0.08:high=0.25:mode=colormix"
        if name == "trails": return f"lagfun=decay={fx.num(0, 0.95)}"
        if name == "bw": return "hue=s=0"
        if name == "sepia": return "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"
        if name == "red": return "colorchannelmixer=rr=1.6:gg=0.35:bb=0.35,eq=contrast=1.4"
        if name == "flash":
            return f"eq=brightness='{fx.num(0, 0.5)}*lt(mod(t,{fx.num(1, 0.12)}),{fx.num(1, 0.12) / 2})':eval=frame"
        if name == "bulge":
            k = fx.num(0, -0.6)
            return f"lenscorrection=k1={k}:k2={k / 2}"
        if name == "blur": return f"boxblur={int(fx.num(0, 8))}"
        if name == "rotate": return f"rotate=a={fx.num(0, 90)}*PI/180:c=black:ow=iw:oh=ih"
        if name == "spin": return f"rotate=a=t*2*PI*{fx.num(0, 1)}:c=black:ow=iw:oh=ih"
        if name == "upside": return "hflip,vflip"
        if name == "glitch":
            return (f"rgbashift=rh=-18:bh=18:rv=6,noise=alls=35:allf=t,scale=iw/2:ih/2,"
                    f"scale={W}:{H}:flags=neighbor,eq=saturation=1.8")
        if name == "scramble":
            return f"shufflepixels=m=block:width={int(fx.num(0, 80))}:height={int(fx.num(0, 80))}:seed={self.label}"
        if name == "text":
            where = a[1] if len(a) > 1 else "bottom"
            size = int(a[2]) if len(a) > 2 else 64
            return self.text_filter(a[0], "impact", size, "white", where)
        if name == "fadein": return f"fade=t=in:d={fx.num(0, 0.3)}"
        if name == "fadeout": return f"fade=t=out:st={max(0.0, D - fx.num(0, 0.3))}:d={fx.num(0, 0.3)}"
        return ""

    def afx(self, fx: Fx) -> str:
        name = fx.name
        if name == "pitch":
            r = 2 ** (fx.num(0, 5) / 12)
            tempo = 1 / r
            chain = []
            while tempo < 0.5:
                chain.append("atempo=0.5"); tempo /= 0.5
            chain.append(f"atempo={tempo:.5f}")
            return f"asetrate={SR * r:.0f},aresample={SR}," + ",".join(chain)
        if name == "vol": return f"volume={fx.num(0, 6)}dB"
        if name in ("loud", "earrape"):
            g = fx.num(0, 18)
            # tanh + lowpass, not a hard clip: square-ish waves overshoot ~3 dB
            # past full scale once AAC-encoded, whatever the limiter says
            return (f"bass=g=10,volume={g}dB,acrusher=bits=7:mix=0.35:samples=2,"
                    "asoftclip=type=tanh,lowpass=f=10000")
        if name == "echo": return "aecho=0.8:0.85:180|320:0.45|0.3"
        if name == "robot":
            return "afftfilt=real='hypot(re,im)':imag='0':win_size=512:overlap=0.75,volume=0.6"
        if name == "vibrato": return f"vibrato=f={fx.num(0, 7)}:d={fx.num(1, 0.8)}"
        if name == "muffle": return f"lowpass=f={fx.num(0, 500)}"
        if name == "phone": return "highpass=f=400,lowpass=f=3000,volume=3dB"
        if name == "mute": return "volume=0"
        if name == "bass": return f"bass=g={fx.num(0, 15)}"
        if name == "crush": return f"acrusher=bits={fx.num(0, 4)}:mix=0.8"
        if name == "chorus":
            return "chorus=0.5:0.9:50|60|40:0.4|0.32|0.3:0.25|0.4|0.3:2|2.3|1.3"
        return ""

    def apply_filters(self, src: Path, n: int, fxs: list[Fx]) -> Path:
        vparts = [s for f in fxs if (s := self.vfx(f, n))]
        aparts = [s for f in fxs if (s := self.afx(f))]
        unknown = [f.name for f in fxs if not self.vfx(f, n) and not self.afx(f)
                   and f.name not in BASE_MODS]
        if unknown:
            die(f"unknown effect(s): {', '.join(unknown)}")
        if not vparts and not aparts:
            return src
        out = self.cache / f"fx_{self.key('fx', src.name, [(f.name, f.args) for f in fxs])}.mkv"
        if out.exists():
            return out
        self.ain = 0
        vf = ",".join(vparts) or "null"
        af = ",".join(aparts) + "," if aparts else ""
        return self.encode(out, ["-i", str(src)], f"scale={self.W}:{self.H},{vf},scale={self.W}:{self.H}", af, n)

    def structural(self, src: Path, n: int, fx: Fx) -> tuple[Path, int]:
        name, k = fx.name, self.key("st", src.name, fx.name, fx.args)
        out = self.cache / f"st_{k}.mkv"
        if name in ("reverse", "rev"):
            if not out.exists():
                self.ain = 0
                self.encode(out, ["-i", str(src)], "reverse", "areverse,", n)
            return out, n
        if name in ("speed", "tempo"):
            x = fx.num(0, 1.5)
            m = self.frames(self.secs(n) / x)
            if not out.exists():
                self.ain = 0
                if name == "speed":
                    af = f"asetrate={SR * x:.0f},aresample={SR},"
                else:
                    chain, t = [], x
                    while t < 0.5:
                        chain.append("atempo=0.5"); t /= 0.5
                    af = ",".join([*chain, f"atempo={t:.5f}"]) + ","
                self.encode(out, ["-i", str(src)], f"setpts=PTS/{x}", af, m)
            return out, m
        if name in ("hold", "prehold"):
            h = self.frames(fx.num(0, 1.0))
            if not out.exists():
                self.ain = 0
                if name == "hold":
                    vf = f"tpad=stop_mode=clone:stop={h}"
                    af = ""
                else:
                    vf = f"tpad=start_mode=clone:start={h}"
                    af = f"adelay={self.secs(h) * 1000:.1f}:all=1,"
                self.encode(out, ["-i", str(src)], vf, af, n + h)
            return out, n + h
        if name in ("cut", "trim"):
            a = 0.0 if name == "cut" else fx.num(0, 0)
            b = fx.num(0, 1) if name == "cut" else fx.num(1, self.secs(n))
            m = min(n, self.frames(b - a))
            if not out.exists():
                self.ain = 0
                self.encode(out, ["-ss", f"{a:.4f}", "-i", str(src)], "null", self.declick(m), m)
            return out, m
        if name in ("stutter", "stutterend"):
            ln, reps = self.frames(fx.num(0, 0.15)), int(fx.num(1, 4))
            ln = min(ln, n)
            head = self.cache / f"st_{self.key('head', src.name, ln, name)}.mkv"
            if not head.exists():
                self.ain = 0
                start = 0.0 if name == "stutter" else self.secs(n - ln)
                self.encode(head, ["-ss", f"{start:.4f}", "-i", str(src)], "null", self.declick(ln), ln)
            seq = [head] * reps + [src] if name == "stutter" else [src] + [head] * reps
            if not out.exists():
                self.concat(seq, out)
            return out, n + ln * reps
        if name == "loop":
            reps = int(fx.num(0, 2))
            if not out.exists():
                self.concat([src] * reps, out)
            return out, n * reps
        if name == "pingpong":
            reps = int(fx.num(0, 1))
            back, _ = self.structural(src, n, Fx("reverse", []))
            if not out.exists():
                self.concat([src, back] * reps, out)
            return out, 2 * n * reps
        die(f"unhandled structural effect {name}")

    def chain(self, src: Path, n: int, fxs: list[Fx]) -> tuple[Path, int]:
        """Apply effects in order; consecutive filter effects share one pass."""
        batch: list[Fx] = []
        for f in fxs:
            if f.name in MIXING:
                continue
            if f.name in STRUCTURAL:
                src = self.apply_filters(src, n, batch); batch = []
                src, n = self.structural(src, n, f)
            else:
                batch.append(f)
        return self.apply_filters(src, n, batch), n

    def render_item(self, item: Item) -> tuple[Path, int]:
        if item.kind in ("card", "black"):
            base, n = self.card(item)
            fxs = [f for f in item.fx if f.name not in BASE_MODS]
        elif item.kind == "freeze":
            base, n = self.freeze(item)
            fxs = item.fx
        elif item.kind == "file":
            base, n = self.media_file(item)
            fxs = [f for f in item.fx if f.name not in BASE_MODS]
        else:
            files, total = [], 0
            item_mods = [f for f in item.fx if f.name in ("pad", "dry", "nolevel")]
            for part in item.parts:
                f, m = self.source_slice(part, item_mods)
                f, m = self.chain(f, m, part.fx)
                files.append(f); total += m
            if len(files) == 1:
                base, n = files[0], total
            else:
                out = self.cache / f"mix_{self.key('mix', [f.name for f in files])}.mkv"
                base, n = (out if out.exists() else self.concat(files, out)), total
            fxs = item.fx
        return self.chain(base, n, fxs)


VERSION = 3


# ---------------------------------------------------------------- assets + mix

SYNTH = {
    # a low sine drop with a click on top: the "vine boom" shape
    "boom": "aevalsrc='1.4*sin(2*PI*t*(48+70*exp(-t*14)))*exp(-t*2.6)+0.5*sin(2*PI*t*160)*exp(-t*38)':d=1.8:s=48000,"
            "asoftclip=type=tanh,lowpass=f=900,aecho=0.6:0.5:60:0.25",
    "beep": "sine=f=1000:d=0.6:sample_rate=48000,volume=-6dB",
    "static": "anoisesrc=d=1.2:c=white:a=0.35:r=48000,highpass=f=800",
    "riser": "aevalsrc='0.5*sin(2*PI*(200*t+900*t*t/2))':d=2:s=48000,volume=-4dB",
    "drop": "aevalsrc='0.6*sin(2*PI*(1600*t-700*t*t))*exp(-t*1.5)':d=1.1:s=48000",
    "airhorn": "aevalsrc='0.25*((2*mod(t*466.2,1)-1)+(2*mod(t*587.3,1)-1)+(2*mod(t*698.5,1)-1))"
               "*lt(mod(t,0.6),0.45+0.15*gte(t,1.2))':d=1.9:s=48000,"
               "asoftclip=type=hard,highpass=f=200,volume=-3dB",
    "click": "aevalsrc='sin(2*PI*t*2000)*exp(-t*300)':d=0.05:s=48000",
}


KM_URL = "https://incompetech.com/music/royalty-free/mp3-royaltyfree/{}.mp3"
KM_TRACKS = ["Monkeys Spinning Monkeys", "Local Forecast - Elevator", "Sneaky Snitch", "Fluffing a Duck",
             "Scheming Weasel faster", "Five Armies", "Volatile Reaction", "Pixelland", "Investigations",
             "Wallpaper"]
UISFX_TGZ = "https://registry.npmjs.org/uisfx/-/uisfx-0.4.0.tgz"
ASSETS = HERE / "assets"


def km_credit(title: str) -> str:
    return (f'"{title}" Kevin MacLeod (incompetech.com). Licensed under Creative Commons: '
            "By Attribution 4.0 License. http://creativecommons.org/licenses/by/4.0/")


class Mixer:
    """Resolves sound names. In `assets:` or inline:
    synth:NAME (generated), km:TITLE (Kevin MacLeod, credited), ui:PACK/CUE (uisfx, CC0),
    src:KEY START-END (a slice of a source's own audio), say:KEY@TIME phrase (an aligned
    line, for dubbing onto other pictures), or a file path."""

    def __init__(self, proj: Project):
        self.p = proj
        self.assets: dict = proj.data.get("assets") or {}
        self.synth_dir = proj.work / "synth"
        self.synth_dir.mkdir(exist_ok=True)

    def spec(self, name: str) -> str:
        spec = self.assets.get(name, name)
        return str(spec["path"] if isinstance(spec, dict) else spec)

    def path(self, name: str) -> Path:
        spec = self.spec(name)
        if spec.startswith("synth:") or (":" not in spec and spec in SYNTH):
            key = spec.split(":", 1)[-1]
            recipe = SYNTH.get(key)
            if recipe is None:
                die(f"unknown synth {key!r} (have: {', '.join(SYNTH)})")
            out = self.synth_dir / f"{key}.wav"
            if not out.exists():
                run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", recipe, "-ac", "2", "-ar", str(SR), str(out)])
            return out
        if spec.startswith("km:"):
            f = ASSETS / "music" / f"{spec[3:]}.mp3"
            if not f.exists():
                die(f"{f.name} not downloaded; run `mist-ytp fetch-assets`")
            return f
        if spec.startswith("ui:"):
            f = ASSETS / "sfx" / "uisfx" / f"{spec[3:]}.mp3"
            if not f.exists():
                die(f"no uisfx cue {spec[3:]!r}; run `mist-ytp fetch-assets` (packs/cues in assets/sfx/uisfx)")
            return f
        if spec.startswith("say:"):
            # a line found by alignment, e.g. say:S01E01@40:07 hi kiddo -> dub it anywhere
            where, phrase = spec[4:].split(None, 1)
            key, t = where.split("@", 1)
            t0, t1 = find_phrase(self.p, key.upper(), parse_time(t), phrase)
            spec = f"src:{key} {t0:.3f}-{t1:.3f}"
        if spec.startswith("src:"):
            key, rng = spec[4:].split()
            t0, t1 = parse_range(rng)
            out = self.synth_dir / f"src_{key}_{t0:.3f}_{t1:.3f}.wav"
            if not out.exists():
                pan = dialog_pan(audio_channels(self.p, key.upper()))
                raw = out.with_name(out.stem + "_raw.wav")
                run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i",
                     str(self.p.source(key)), "-map", "0:a:0", "-af", pan + f"aresample={SR}",
                     "-ac", "2", str(raw)])
                target = self.p.data.get("level", -20)
                g = 0.0 if target is None else level_gain(raw, float(target))
                run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", f"volume={g:.2f}dB", str(out)])
                raw.unlink()
            return out
        f = Path(os.path.expanduser(spec))
        f = f if f.is_absolute() else self.p.path.parent / f
        if not f.exists():
            die(f"asset {name!r} missing: {f}")
        return f

    def credit(self, name: str) -> str | None:
        raw = self.assets.get(name)
        if isinstance(raw, dict) and raw.get("credit"):
            return raw["credit"]
        spec = self.spec(name)
        return km_credit(spec[3:]) if spec.startswith("km:") else None


def cmd_fetch_assets(args: argparse.Namespace) -> None:
    """Kevin MacLeod tracks (CC BY 4.0) + the uisfx cue library (CC0) into assets/."""
    import tarfile
    import urllib.parse
    import urllib.request

    music = ASSETS / "music"
    music.mkdir(parents=True, exist_ok=True)
    for title in KM_TRACKS:
        f = music / f"{title}.mp3"
        if f.exists() and not args.force:
            continue
        print(f"fetching {title}", flush=True)
        urllib.request.urlretrieve(KM_URL.format(urllib.parse.quote(title)), f)
    (music / "CREDITS.txt").write_text("\n".join(km_credit(t) for t in KM_TRACKS) + "\n")
    sfx = ASSETS / "sfx" / "uisfx"
    if not sfx.exists() or args.force:
        print("fetching uisfx", flush=True)
        tgz = ASSETS / "uisfx.tgz"
        urllib.request.urlretrieve(UISFX_TGZ, tgz)
        with tarfile.open(tgz) as tf:
            for m in tf.getmembers():
                parts = Path(m.name).parts          # package/sounds/<pack>/<cue>.mp3
                if len(parts) == 4 and parts[1] == "sounds" and m.name.endswith(".mp3"):
                    dest = sfx / parts[2] / parts[3]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    src = tf.extractfile(m)
                    if src:
                        dest.write_bytes(src.read())
                elif parts[-1] in ("LICENSE-AUDIO", "LICENSE"):
                    src = tf.extractfile(m)
                    if src:
                        sfx.mkdir(parents=True, exist_ok=True)
                        (sfx / parts[-1]).write_bytes(src.read())
        tgz.unlink()
    packs = sorted(p.name for p in sfx.iterdir() if p.is_dir())
    print(f"music: {len(list(music.glob('*.mp3')))} tracks; uisfx packs: {', '.join(packs)}")


# ---------------------------------------------------------------- render command

def parse_items_arg(s: str | None, n: int) -> list[int]:
    if not s:
        return list(range(n))
    out: list[int] = []
    for chunk in s.split(","):
        if "-" in chunk:
            a, b = chunk.split("-")
            out += range(int(a), int(b) + 1)
        else:
            out.append(int(chunk))
    return [i for i in out if 0 <= i < n]


def credits_text(proj: Project, items: list[Item]) -> str:
    """Card text for a `credits` item: the project's own lines, then every credited
    sound actually used (Kevin MacLeod tracks need incompetech's wording on screen)."""
    mixer = Mixer(proj)
    used = [f.args[0] for it in items for f in it.fx if f.name in MIXING and f.args]
    used = [u for u in used if not mixer.spec(u).startswith(("say:", "src:"))]
    specs = [mixer.spec(u) for u in dict.fromkeys(used)]
    cfg = proj.data.get("credits") or {}
    lines = [str(x) for x in (cfg.get("lines") or [])]
    km = [sp[3:] for sp in specs if sp.startswith("km:")]
    if km:
        lines += ["", "Music"] + [f'"{t}" Kevin MacLeod (incompetech.com)' for t in km]
        lines += ["Licensed under Creative Commons: By Attribution 4.0 License",
                  "http://creativecommons.org/licenses/by/4.0/"]
    if any(sp.startswith("ui:") for sp in specs):
        lines += ["", "Sound effects - uisfx by Romain Simon (CC0)"]
    return "\n".join(lines)


def cmd_render(args: argparse.Namespace) -> None:
    from concurrent.futures import ThreadPoolExecutor

    proj = load_project(args.project)
    timeline = [t for t in (proj.data.get("timeline") or []) if isinstance(t, str) and t.strip()]
    idx = parse_items_arg(args.items, len(timeline))
    if args.dry:
        # resolve every item (phrases included) and report, without rendering
        for i in idx:
            try:
                it = parse_item(proj, timeline[i])
            except SystemExit as e:
                print(f"[{i:3d}] ERROR {e}")
                continue
            cuts = "  ".join(f"{p.key}@{fmt_time(p.t0)}+{p.t1 - p.t0:.2f}" for p in it.parts)
            print(f"[{i:3d}] {it.kind:6s} {cuts}  |  {timeline[i][:70]}")
        return
    items = [parse_item(proj, timeline[i]) for i in idx]
    if any(it.kind == "credits" for it in items):
        fx_only = [Item("fx", t, parse_fx(" ; ".join(split_top(t, "|")[1:]))) for t in timeline]
        text = credits_text(proj, fx_only)
        for it in items:
            if it.kind == "credits":
                it.kind, it.args = "card", [it.args[0] if it.args else "8", text]
                if not any(f.name == "size" for f in it.fx):
                    it.fx.append(Fx("size", ["30"]))
                if not any(f.name == "font" for f in it.fx):
                    it.fx.append(Fx("font", ["arialblack"]))
    rnd = Renderer(proj, jobs=args.jobs)

    def work(it: Item) -> tuple[Path, int]:
        return Renderer(proj).render_item(it)

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        results = list(ex.map(work, items))
    for i, (_f, n) in zip(idx, results, strict=True):
        print(f"  [{i:3d}] {rnd.secs(n):6.2f}s  {timeline[i][:90]}", file=sys.stderr)

    # timeline positions, then the concat
    starts, t = [], 0
    for _f, n in results:
        starts.append(t); t += n
    total = t
    cat = proj.work / "timeline.mkv"
    rnd.concat([f for f, _ in results], cat)
    with open(proj.work / "timeline.tsv", "w") as fh:
        for i, s, (_f, n) in zip(idx, starts, results, strict=True):
            fh.write(f"{i}\t{rnd.secs(s):.3f}\t{rnd.secs(s + n):.3f}\t{timeline[i]}\n")

    # music beds (continuous across consecutive items naming the same track) + sfx
    mixer = Mixer(proj)
    inputs: list[str] = ["-i", str(cat)]
    chains: list[str] = []
    used: set[str] = set()
    runs: list[list] = []   # [name, gain, track_offset, start_frame, end_frame]
    for it, s, (_f, n) in zip(items, starts, results, strict=True):
        mus = next((f for f in it.fx if f.name == "music"), None)
        if mus:
            gain, off = mus.num(1, -12), mus.num(2, -1)
            if runs and runs[-1][0] == mus.args[0] and runs[-1][4] == s and off < 0:
                runs[-1][4] = s + n
            else:
                runs.append([mus.args[0], gain, max(0.0, off), s, s + n])
        for f in it.fx:
            if f.name != "sfx":
                continue
            at = f.num(1, 0.0)
            at = rnd.secs(n) + at if at < 0 else at
            k = len(inputs) // 2
            inputs += ["-i", str(mixer.path(f.args[0]))]
            used.add(f.args[0])
            ms = (rnd.secs(s) + at) * 1000
            chains.append(f"[{k}:a]aresample={SR},aformat=channel_layouts=stereo,volume={f.num(2, 0)}dB,"
                          f"adelay={ms:.0f}:all=1[x{k}]")
    for name, gain, off, s, e in runs:
        k = len(inputs) // 2
        inputs += ["-i", str(mixer.path(name))]
        used.add(name)
        d = rnd.secs(e - s)
        chains.append(f"[{k}:a]aresample={SR},aformat=channel_layouts=stereo,atrim=start={off}:duration={d:.3f},"
                      f"asetpts=PTS-STARTPTS,afade=t=in:d=0.04,afade=t=out:st={max(0.0, d - 0.12):.3f}:d=0.12,"
                      f"volume={gain}dB,adelay={rnd.secs(s) * 1000:.0f}:all=1[x{k}]")
    labels = "".join(f"[x{i}]" for i in range(1, len(inputs) // 2))
    ns = total * proj.spf
    mixed = proj.work / "mix.wav"
    graph = ";".join(chains + [f"[0:a]{labels}amix=inputs={1 + labels.count('[')}:normalize=0:duration=first,"
                               f"atrim=end_sample={ns},alimiter=limit=0.9:level=false[out]"])
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[out]",
         "-c:a", "pcm_s24le", str(mixed)])

    # One static gain to the target loudness, then a limiter. (loudnorm fell back
    # to dynamic mode on YTP-style peaks and ducked everything after a loud item.)
    m = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(mixed), "-af",
             "loudnorm=I=-16:TP=-1.5:LRA=14:print_format=json", "-f", "null", "-"])
    js = json.loads(m.stderr[m.stderr.rindex("{"):m.stderr.rindex("}") + 1])
    gain = -16.0 - float(js["input_i"])
    ln = f"volume={gain:.2f}dB,alimiter=limit=0.7:attack=3:release=60:level=false,aresample={SR}"
    out = Path(args.output).expanduser() if args.output else proj.path.with_suffix(".mp4")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(cat), "-i", str(mixed), "-map", "0:v", "-map", "1:a",
         "-af", ln, "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    credits = sorted({c for u in used if (c := mixer.credit(u))})
    if credits:
        out.with_name(out.stem + ".CREDITS.txt").write_text("\n".join(credits) + "\n")
    print(f"{out}  ({rnd.secs(total):.1f}s, {len(items)} items)")


def cmd_sheet(args: argparse.Namespace) -> None:
    """Contact sheet: one frame every N seconds, tiled, for eyeballing a render."""
    info = ffprobe_json(args.video, "-show_entries", "format=duration")
    dur = float(info["format"]["duration"])
    a, b = (parse_range(args.range) if args.range else (0.0, dur))
    cols = args.cols
    count = max(1, int((b - a) / args.every))
    rows = math.ceil(count / cols)
    out = Path(args.output).expanduser()
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", args.video,
         "-vf", f"fps=1/{args.every},scale=320:-2,tile={cols}x{rows}:padding=4:color=gray",
         "-frames:v", "1", str(out)])
    print(f"{out}  (frame k = {a:.1f}s + k*{args.every}s, row-major)")


def cmd_peek(args: argparse.Namespace) -> None:
    """Labelled stills for KEY@TIME specs, tiled: pick freeze frames by face."""
    from concurrent.futures import ThreadPoolExecutor

    from PIL import Image, ImageDraw, ImageFont

    proj = load_project(args.project)
    tmp = proj.work / "tmp"
    tmp.mkdir(exist_ok=True)
    specs = [x.split("@", 1) for x in args.at]

    def grab(i_spec: tuple[int, list[str]]) -> Path:
        i, (key, t) = i_spec
        out = tmp / f"peek_{os.getpid()}_{i}.png"
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{parse_time(t):.3f}", "-i", str(proj.source(key)),
             "-map", "0:v:0", "-frames:v", "1", "-vf", "scale=400:-2", str(out)])
        return out

    with ThreadPoolExecutor(max_workers=4) as ex:
        frames = list(ex.map(grab, enumerate(specs)))
    cols = args.cols
    w, h = Image.open(frames[0]).size
    sheet = Image.new("RGB", (cols * (w + 4), math.ceil(len(frames) / cols) * (h + 4)), "gray")
    face = ImageFont.truetype(str(FONTS["impact"]), 22)
    for i, f in enumerate(frames):
        im = Image.open(f).convert("RGB")
        ImageDraw.Draw(im).text((6, 4), f"{i} {specs[i][0]}@{specs[i][1]}", font=face, fill="yellow",
                                stroke_width=2, stroke_fill="black")
        sheet.paste(im, ((i % cols) * (w + 4), (i // cols) * (h + 4)))
        f.unlink()
    sheet.save(args.output)
    print(args.output)


def speech_segments(proj: Project, key: str, a: float, b: float) -> list[tuple[float, float]]:
    """Voiced spans on the dialogue channel in [a, b): runs above (peak - 36 dB),
    with gaps under 80 ms bridged (stop consonants), same rule as refine_bounds."""
    import wave

    import numpy as np

    tmp = proj.work / "tmp"
    tmp.mkdir(exist_ok=True)
    wav = tmp / f"seg_{key}_{a:.3f}_{os.getpid()}.wav"
    ch = audio_channels(proj, key)
    pan = "pan=mono|c0=FC" if ch >= 6 else "pan=mono|c0=0.5*c0+0.5*c1" if ch == 2 else "anull"
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i",
         str(proj.source(key)), "-map", "0:a:0", "-af", pan, "-ar", "16000", "-ac", "1", str(wav)])
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    wav.unlink(missing_ok=True)
    n = len(x) // 160
    db = 20 * np.log10(np.sqrt((x[:n * 160].reshape(n, 160) ** 2).mean(1)) + 1e-9)
    thr = max(float(db.max()) - 36, float(np.percentile(db, 10)) + 8)
    loud = db >= thr
    segs: list[tuple[float, float]] = []
    i = 0
    while i < n:
        if loud[i]:
            j = i
            while j < n and (loud[j] or (j + 8 < n and loud[j:j + 8].any())):
                j += 1
            segs.append((a + i * 0.01, a + j * 0.01))
            i = j
        else:
            i += 1
    return segs


def cmd_inspect(args: argparse.Namespace) -> None:
    """Cues, whisper words and voiced spans around KEY@TIME: fixes cuts by evidence."""
    proj = load_project(args.project)
    for spec in args.at:
        key, t = spec.split("@", 1)
        key, at, w = key.upper(), parse_time(t), args.window
        print(f"== {key} {fmt_time(at - w)} .. {fmt_time(at + w)}")
        for k, a, b, text in read_lines(proj):
            if k == key and b > at - w and a < at + w:
                print(f"  cue   {fmt_time(a)}-{fmt_time(b)}  {text}")
        words = align_window(proj, key, max(0.0, at - 8), at + 8)
        near = [x for x in words if at - w <= x["s"] <= at + w]
        print("  words " + "  ".join(f"{x['w']}[{fmt_time(x['s'])}+{x['e'] - x['s']:.2f}]" for x in near))
        segs = speech_segments(proj, key, max(0.0, at - w), at + w)
        print("  voice " + "  ".join(f"{fmt_time(a)}-{fmt_time(b)}" for a, b in segs))


def cmd_hear(args: argparse.Namespace) -> None:
    """Transcribe a render to check what the sentence mixes actually say. With
    --timeline, each item is transcribed on its own: whisper run over a whole
    YTP loses the thread after the first heavily processed item."""
    info = ffprobe_json(args.video, "-show_entries", "format=duration")
    if args.timeline:
        rows = [r.split("\t", 3) for r in Path(args.timeline).read_text().splitlines()]
        want = set(parse_items_arg(args.items, 10_000)) if args.items else None
        spans = [(float(a), float(b), f"[{i}]") for i, a, b, _ in rows if want is None or int(i) in want]
    else:
        a, b = parse_range(args.range) if args.range else (0.0, float(info["format"]["duration"]))
        spans = [(a, b, "")]
    wav = Path("/tmp") / f"mist_ytp_hear_{os.getpid()}.wav"
    for a, b, tag in spans:
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", args.video,
             "-map", "0:a:0", "-ac", "1", "-ar", "16000", str(wav)])
        segs, _ = whisper_model().transcribe(str(wav), language="en", beam_size=5,
                                             condition_on_previous_text=False)
        text = " ".join(x.text.strip() for x in segs)
        print(f"{tag:>5} {fmt_time(a)}  {text}")
    wav.unlink(missing_ok=True)


# ---------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(prog="mist-ytp", description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="extract subtitles into work/lines.tsv")
    p.add_argument("project"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("grep", help="search dialogue lines")
    p.add_argument("project"); p.add_argument("pattern")
    p.add_argument("-C", "--context", type=int, default=0)
    p.add_argument("--only", help="source key glob, e.g. S02E*")
    p.set_defaults(fn=cmd_grep)

    p = sub.add_parser("align", help="word timestamps around KEY@TIME (cached)")
    p.add_argument("project"); p.add_argument("at", nargs="+")
    p.add_argument("--window", type=float, default=8.0)
    p.set_defaults(fn=cmd_align)

    p = sub.add_parser("render", help="render the timeline")
    p.add_argument("project"); p.add_argument("-o", "--output")
    p.add_argument("--items", help="subset, e.g. 0-5,9")
    p.add_argument("--jobs", type=int, default=3)
    p.add_argument("--crf", type=int, default=20)
    p.add_argument("--dry", action="store_true", help="resolve items and print cuts; no render")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("fetch-assets", help="download Kevin MacLeod tracks + uisfx cues")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_fetch_assets)

    p = sub.add_parser("sheet", help="contact sheet of a video")
    p.add_argument("video"); p.add_argument("-o", "--output", required=True)
    p.add_argument("--every", type=float, default=2.0)
    p.add_argument("--cols", type=int, default=6)
    p.add_argument("--range", help="START-END within the video")
    p.set_defaults(fn=cmd_sheet)

    p = sub.add_parser("inspect", help="cues, whisper words and voiced spans around KEY@TIME")
    p.add_argument("project"); p.add_argument("at", nargs="+")
    p.add_argument("--window", type=float, default=3.0)
    p.set_defaults(fn=cmd_inspect)

    p = sub.add_parser("peek", help="tiled stills for KEY@TIME specs")
    p.add_argument("project"); p.add_argument("at", nargs="+")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--cols", type=int, default=5)
    p.set_defaults(fn=cmd_peek)

    p = sub.add_parser("hear", help="transcribe a render to check what it says")
    p.add_argument("video"); p.add_argument("--range")
    p.add_argument("--timeline", help="work/timeline.tsv: transcribe item by item")
    p.add_argument("--items", help="with --timeline, only these items")
    p.set_defaults(fn=cmd_hear)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
