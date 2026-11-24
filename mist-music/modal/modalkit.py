"""modalkit: move a tune from one scale to another, then check that it arrived.

A tune is stored the way a lead sheet thinks: every note is a scale degree
(1 to 7) in a named scale, with an optional accidental and an octave. To put
the tune in a new scale, each note keeps its degree number and takes the pitch
that the new scale gives to that degree. C Phrygian dominant to A Dorian then
needs no table of intervals: degree 2 was D flat and becomes B, degree 3 was E
and becomes C, degree 6 was A flat and becomes F sharp.

Altered notes need one rule. An altered note in the source has a pitch that
the source scale does not contain. If the new scale contains that pitch, the
note takes it (the alteration is "absorbed"). If it does not, the note moves
to the nearest tone of the new scale, and a tie goes to the same degree number.
So the result has scale tones only, and the report records each note that moved.

Two checks tell if the result is in the new scale:

  census()        the notes: the time on each of the 12 pitch classes, the
                  share inside the scale, and the degrees that separate the
                  scale from each neighbour mode
  audio_census()  the rendered audio: the same 12 numbers from the spectrum,
                  plus the pitch class of the low band (the tonal centre)

Sources: Hooktheory TheoryTab data (fetch_hooktheory) already has this shape.
A section typed by hand uses the same Note records.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

USER_AGENT = "exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"
PC_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Seven-note scales, as semitones above the tonic. The keys are Hooktheory's names.
SCALES: dict[str, tuple[int, ...]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "harmonicMinor": (0, 2, 3, 5, 7, 8, 11),
    "melodicMinor": (0, 2, 3, 5, 7, 9, 11),
    "phrygianDominant": (0, 1, 4, 5, 7, 8, 10),
    "doubleHarmonic": (0, 1, 4, 5, 7, 8, 11),
    "hungarianMinor": (0, 2, 3, 6, 7, 8, 11),
    "lydianDominant": (0, 2, 4, 6, 7, 9, 10),
}
ALIASES = {
    "ionian": "major", "aeolian": "minor", "naturalminor": "minor", "freygish": "phrygianDominant",
    "hijaz": "phrygianDominant", "byzantine": "doubleHarmonic", "acoustic": "lydianDominant",
}
MODES = ("major", "dorian", "phrygian", "lydian", "mixolydian", "minor", "locrian")


def scale(name: str) -> tuple[int, ...]:
    key = re.sub(r"[\s_-]", "", name)
    for cand in (name, key, key[:1].lower() + key[1:]):
        if cand in SCALES:
            return SCALES[cand]
    low = key.lower()
    for k in SCALES:
        if k.lower() == low:
            return SCALES[k]
    if low in ALIASES:
        return SCALES[ALIASES[low]]
    raise KeyError(f"unknown scale {name!r}; known: {', '.join(SCALES)}")


def pc(name: str) -> int:
    """Pitch class of a note name: 'A' -> 9, 'F#' -> 6, 'Bb' -> 10."""
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[name[0].upper()]
    return (base + name.count("#") - name[1:].count("b")) % 12


@dataclass(frozen=True)
class Note:
    beat: float          # quarter-note beats from the start of the section, 0-based
    dur: float
    degree: int          # 1..7 in the section's scale
    acc: int = 0         # +1 or -1: one semitone off the scale tone
    octave: int = 0      # 0 = the octave that starts on the tonic


@dataclass(frozen=True)
class Chord:
    beat: float
    dur: float
    root: int            # degree of the root
    kind: int = 5        # 5 triad, 7 seventh, 9, 11, 13
    applied: int = 0     # secondary function: the chord belongs to the key of this degree
    inversion: int = 0
    omits: tuple[int, ...] = ()
    borrowed: str = ""


@dataclass
class Section:
    name: str
    tonic: int           # pitch class of the tonic
    scale: str
    bpm: float
    meter: int           # beats per bar
    beats: float         # length of the section
    notes: list[Note] = field(default_factory=list)
    chords: list[Chord] = field(default_factory=list)
    source: str = ""

    def bars(self) -> int:
        return int(round(self.beats / self.meter))


def semis(scale_name: str, degree: int, acc: int = 0, octave: int = 0) -> int:
    """Semitones above the octave-0 tonic."""
    return scale(scale_name)[degree - 1] + acc + 12 * octave


def midi_notes(sec: Section, tonic_midi: int) -> list[tuple[float, float, int]]:
    """(beat, duration, MIDI pitch) with the octave-0 tonic at tonic_midi."""
    if tonic_midi % 12 != sec.tonic:
        raise ValueError(f"tonic_midi {tonic_midi} is not pitch class {PC_NAMES[sec.tonic]}")
    return [(n.beat, n.dur, tonic_midi + semis(sec.scale, n.degree, n.acc, n.octave)) for n in sec.notes]


# ---------------------------------------------------------------- sources

def parse_hooktheory(payload: dict, name: str = "", source: str = "") -> Section:
    """One Hooktheory section (the object from the public song endpoint) -> Section."""
    j = json.loads(payload["jsonData"]) if "jsonData" in payload else payload
    key = j["keys"][0]
    if len(j["keys"]) > 1:
        raise ValueError(f"{name}: the section changes key at beat {j['keys'][1]['beat']}; split it first")
    notes = []
    for n in j["notes"]:
        if n["isRest"]:
            continue
        sd = n["sd"]
        notes.append(Note(beat=n["beat"] - 1, dur=n["duration"], degree=int(sd.strip("#b")),
                          acc=sd.count("#") - sd.count("b"), octave=n["octave"]))
    chords = []
    for c in j["chords"]:
        if c["isRest"]:
            continue
        chords.append(Chord(beat=c["beat"] - 1, dur=c["duration"], root=c["root"], kind=c["type"],
                            applied=c["applied"] or 0, inversion=c["inversion"] or 0,
                            omits=tuple(c["omits"] or ()), borrowed=c["borrowed"] or ""))
    return Section(name=name or payload.get("song", ""), tonic=pc(key["tonic"]), scale=key["scale"],
                   bpm=float(j["tempos"][0]["bpm"]), meter=int(j["meters"][0]["numBeats"]),
                   beats=float(j["endBeat"]) - 1, notes=notes, chords=chords, source=source)


def fetch_hooktheory(url: str, dest: Path) -> list[Path]:
    """Save every section of a TheoryTab page as JSON in dest. Returns the files.

    The page lists its sections as data-hash / data-section-url pairs, and the
    public song endpoint returns the notes and chords of one hash.
    """
    def get(u: str) -> bytes:
        req = urllib.request.Request(u, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:  # noqa: S310 (fixed https hosts)
            return r.read()

    page = get(url).decode("utf-8", "replace")
    pairs = sorted(set(re.findall(r'data-hash="([^"]+)" data-section-url="([^"]+)"', page)))
    if not pairs:
        raise SystemExit(f"no sections found at {url}")
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    for h, section in pairs:
        data = json.loads(get(f"https://api.hooktheory.com/v1/songs/public/{h}?fields=ID,xmlData,song,jsonData"))
        data["_section"], data["_url"] = section, url
        p = dest / f"{section}.json"
        p.write_text(json.dumps(data, indent=1))
        out.append(p)
    return out


def load_section(path: Path) -> Section:
    data = json.loads(path.read_text())
    return parse_hooktheory(data, name=data.get("_section", path.stem), source=data.get("_url", str(path)))


# ---------------------------------------------------------------- remap

@dataclass(frozen=True)
class Move:
    beat: float
    was: str             # the source note, for example "#7"
    now: str
    how: str             # "absorbed" or "nearest"


def _label(degree: int, acc: int) -> str:
    return ("#" * acc if acc > 0 else "b" * -acc) + str(degree)


def remap_note(n: Note, src: str, dst: str) -> tuple[Note, str]:
    """The note in the new scale, and how it got there: 'same', 'absorbed' or 'nearest'."""
    if n.acc == 0:
        return n, "same"
    want = scale(src)[n.degree - 1] + n.acc
    best: tuple[tuple[int, int, int], int, int] | None = None
    for d in range(1, 8):
        for o in (-1, 0, 1):
            got = scale(dst)[d - 1] + 12 * o
            rank = (abs(got - want), 0 if d == n.degree else 1, abs(o))
            if best is None or rank < best[0]:
                best = (rank, d, o)
    assert best is not None
    (dist, _, _), d, o = best
    return replace(n, degree=d, acc=0, octave=n.octave + o), "absorbed" if dist == 0 else "nearest"


def remap(sec: Section, dst_scale: str, dst_tonic: int | str) -> tuple[Section, list[Move]]:
    """The section in dst_scale on dst_tonic. Chords keep their degree numbers."""
    tonic = pc(dst_tonic) if isinstance(dst_tonic, str) else dst_tonic % 12
    scale(dst_scale)
    notes, moves = [], []
    for n in sec.notes:
        m, how = remap_note(n, sec.scale, dst_scale)
        notes.append(m)
        if how != "same":
            moves.append(Move(n.beat, _label(n.degree, n.acc), _label(m.degree, m.acc), how))
    out = replace(sec, tonic=tonic, scale=dst_scale, notes=notes)
    return out, moves


def contour(src: Section, dst: Section) -> tuple[int, int, int]:
    """Does the remapped line still move the way the source moves? Compares each step
    between successive notes: (steps that keep their direction, steps where two source
    pitches became one, steps in total). A step that reverses direction counts in neither."""
    a = [p for _, _, p in midi_notes(src, 60 + src.tonic)]
    b = [p for _, _, p in midi_notes(dst, 60 + dst.tonic)]
    same = merged = 0
    for i in range(1, len(a)):
        da, db = a[i] - a[i - 1], b[i] - b[i - 1]
        if (da > 0) == (db > 0) and (da < 0) == (db < 0):
            same += 1
        elif da != 0 and db == 0:
            merged += 1
    return same, merged, len(a) - 1


def describe(sec: Section, tonic_midi: int | None = None) -> str:
    """The section bar by bar, as note names on a sixteenth grid."""
    base = tonic_midi if tonic_midi is not None else 60 + sec.tonic
    rows: dict[int, list[str]] = {}
    for beat, dur, p in midi_notes(sec, base):
        bar = int(beat // sec.meter)
        slot = (beat - bar * sec.meter) * 4
        rows.setdefault(bar, []).append(f"{slot:g}:{SHARP_NAMES[p % 12]}{p // 12 - 1}/{dur * 4:g}")
    head = f"{sec.name}: {PC_NAMES[sec.tonic]} {sec.scale}, {sec.bpm:g} BPM, {sec.bars()} bars"
    return "\n".join([head] + [f"  bar {b + 1:02d} | " + "  ".join(rows[b]) for b in sorted(rows)])


# ---------------------------------------------------------------- checks on the notes

def census(notes: list[tuple[float, int]], tonic: int) -> np.ndarray:
    """Share of sounding time on each semitone above the tonic. notes = (duration, MIDI pitch)."""
    c = np.zeros(12)
    for dur, p in notes:
        c[(p - tonic) % 12] += dur
    return c / max(c.sum(), 1e-12)


def separators(dst: str) -> dict[str, tuple[tuple[int, ...], tuple[int, ...]]]:
    """For each other mode: (tones only dst has, tones only the other mode has)."""
    mine = set(scale(dst))
    out = {}
    for other in MODES:
        theirs = set(SCALES[other])
        if theirs != mine:
            out[other] = (tuple(sorted(mine - theirs)), tuple(sorted(theirs - mine)))
    return out


def scale_report(c: np.ndarray, dst: str, floor: float = 0.004) -> dict:
    """What the 12 shares say about dst: share inside the scale, degrees that never
    sound, and for each neighbour mode the share on the tones that tell the two apart."""
    tones = scale(dst)
    inside = float(sum(c[t] for t in tones))
    missing = [i + 1 for i, t in enumerate(tones) if c[t] < floor]
    versus = {}
    for other, (mine, theirs) in separators(dst).items():
        versus[other] = (float(sum(c[t] for t in mine)), float(sum(c[t] for t in theirs)))
    return {"inside": inside, "outside": 1.0 - inside, "missing_degrees": missing, "versus": versus}


def format_report(c: np.ndarray, dst: str, tonic: int, title: str) -> str:
    r = scale_report(c, dst)
    tones = scale(dst)
    lines = [f"{title}: {PC_NAMES[tonic]} {dst}",
             "  share by tone: " + "  ".join(
                 f"{PC_NAMES[(tonic + t) % 12]}{'' if t in tones else '*'} {100 * c[t]:.1f}%" for t in range(12) if c[t] >= 0.001),
             f"  inside the scale {100 * r['inside']:.1f}%, outside {100 * r['outside']:.1f}% (* marks an outside tone)"]
    if r["missing_degrees"]:
        lines.append(f"  degrees that do not sound: {r['missing_degrees']}")
    for other, (mine, theirs) in r["versus"].items():
        m_t, o_t = separators(dst)[other]
        names = lambda ts: "+".join(PC_NAMES[(tonic + t) % 12] for t in ts)  # noqa: E731
        verdict = "apart" if mine > 4 * theirs and mine >= 0.01 else "NOT SEPARATED"
        lines.append(f"  against {other:<10} {names(m_t):<8} {100 * mine:5.1f}%  vs  {names(o_t):<8} {100 * theirs:5.1f}%  {verdict}")
    return "\n".join(lines)


# ---------------------------------------------------------------- checks on audio

def _decode(path: Path, sr: int) -> np.ndarray:
    import subprocess
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def audio_census(path: Path, t0: float = 0.0, t1: float | None = None, sr: int = 22050,
                 f_lo: float = 196.0, f_hi: float = 2100.0) -> tuple[np.ndarray, np.ndarray]:
    """Spectral energy by absolute pitch class (C = 0) in [t0, t1).

    Returns (mid, low): `mid` is the band f_lo..f_hi, where melody and chords
    live, and `low` is 40..220 Hz, where the bass names the tonal centre.
    Windows are 0.74 s (mid) and 1.5 s (low), so that one semitone is more than
    eight bins wide at the bottom of each band. Each frame is normalized first,
    so a loud passage does not outvote a quiet one.

    The numbers include overtones. The fifth harmonic of every A lands on C sharp
    and the third harmonic of every B lands on F sharp, so some percent of the
    energy sits outside the scale in any real mix. Read this census against a
    control render, or use transcribed_census(), which counts note fundamentals.
    """
    x = _decode(path, sr)
    x = x[int(t0 * sr): int(t1 * sr) if t1 is not None else len(x)]
    c4 = 440.0 * 2 ** (-9 / 12)

    def profile(n: int, lo: float, hi: float) -> np.ndarray:
        f = np.fft.rfftfreq(n, 1 / sr)
        m = np.nonzero((f >= lo) & (f <= hi))[0]
        st = 12 * np.log2(f[m] / c4)
        near = np.abs(st - np.round(st)) < 0.35   # energy between two notes votes for neither
        idx, pcs = m[near], np.round(st[near]).astype(int) % 12
        out, win = np.zeros(12), np.hanning(n)
        for a in range(0, max(1, len(x) - n), n // 4):
            seg = x[a:a + n]
            if len(seg) < n:
                seg = np.pad(seg, (0, n - len(seg)))
            s = np.abs(np.fft.rfft(seg * win)) ** 2
            tot = s[idx].sum()
            if tot > 1e-9:
                out += np.bincount(pcs, weights=s[idx], minlength=12) / tot
        return out / max(out.sum(), 1e-12)

    return profile(16384, f_lo, f_hi), profile(32768, 40.0, 220.0)


def transcribe(path: Path) -> list[tuple[float, float, int, int]]:
    """Notes that Basic Pitch hears in an audio file: (start s, length s, MIDI pitch, velocity).
    A model that is neither the arranger nor the listener, and it reports fundamentals."""
    import shutil
    import subprocess
    import tempfile

    import mido
    tool = shutil.which("mp32mid") or str(Path.home() / ".local/bin/mp32mid")
    with tempfile.TemporaryDirectory() as td:
        mid_path = Path(td) / "t.mid"
        r = subprocess.run([tool, str(path), str(mid_path)], capture_output=True, text=True)
        if r.returncode != 0 or not mid_path.exists():
            raise SystemExit(f"mp32mid failed:\n{r.stdout}\n{r.stderr}")
        mid = mido.MidiFile(mid_path)
    notes, on, t = [], {}, 0.0
    for msg in mid:                                  # iterating a MidiFile yields delta times in seconds
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            on[msg.note] = (t, msg.velocity)
        elif msg.type in ("note_off", "note_on") and msg.note in on:
            start, vel = on.pop(msg.note)
            notes.append((start, t - start, msg.note, vel))
    return sorted(notes)


def transcribed_census(notes: list[tuple[float, float, int, int]], tonic: int, t0: float = 0.0, t1: float | None = None,
                       lo: int = 0, hi: int = 127) -> np.ndarray:
    """Share of transcribed note time on each semitone above the tonic, for notes that start in [t0, t1)."""
    pick = [(d, p) for s, d, p, _ in notes if s >= t0 and (t1 is None or s < t1) and lo <= p <= hi]
    return census(pick, tonic)


def melody_presence(path: Path, events: list[tuple[float, float, int]], sr: int = 22050) -> list[float]:
    """Is the tune in this audio? events = (start s, end s, MIDI pitch) of the expected line.
    Returns 12 scores, one per transposition in semitones: the mean share of spectral energy
    on the expected pitch class while each note sounds. A take that keeps the tune puts
    shift 0 clearly on top. The other 11 shifts are the control."""
    x = _decode(path, sr)
    n, hop = 4096, 1024
    f = np.fft.rfftfreq(n, 1 / sr)
    m = np.nonzero((f >= 196.0) & (f <= 4000.0))[0]
    pcs = np.round(12 * np.log2(f[m] / (440.0 * 2 ** (-9 / 12)))).astype(int) % 12
    win = np.hanning(n)
    frames = []
    for a in range(0, max(1, len(x) - n), hop):
        s = np.abs(np.fft.rfft(x[a:a + n] * win)) ** 2
        c = np.bincount(pcs, weights=s[m], minlength=12)
        frames.append(c / max(float(c.sum()), 1e-12))
    chroma = np.array(frames)
    t = (np.arange(len(chroma)) * hop + n / 2) / sr
    scores = np.zeros(12)
    used = 0
    for t0, t1, p in events:
        sel = (t >= t0) & (t < max(t1, t0 + 0.1))
        if sel.any():
            scores += np.array([chroma[sel, (p + k) % 12].mean() for k in range(12)])
            used += 1
    return [float(v) for v in scores / max(used, 1)]


def format_presence(scores: list[float]) -> str:
    order = sorted(range(12), key=lambda k: -scores[k])
    rest = sorted(scores[k] for k in range(1, 12))
    return (f"  the tune at its written pitch: {scores[0]:.3f}; the other 11 transpositions: median {rest[5]:.3f}, "
            f"highest {rest[-1]:.3f} (+{order[0] if order[0] else order[1]} semitones)"
            f"   {'PRESENT' if order[0] == 0 and scores[0] > 1.25 * rest[-1] else 'NOT CLEAR'}")


def collection_fit(mid: np.ndarray) -> list[tuple[float, int]]:
    """How much of the energy each of the 12 diatonic collections holds, best first.
    The int is the pitch class of the collection's major tonic (7 = the G major set)."""
    fits = [(float(sum(mid[(k + t) % 12] for t in SCALES["major"])), k) for k in range(12)]
    return sorted(fits, reverse=True)


def audio_report(path: Path, tonic: int, dst: str, t0: float = 0.0, t1: float | None = None, title: str = "") -> str:
    """The audio check: the pitch-class shares against the scale on this tonic, the
    centre in the low band, and (for a diatonic mode) the best diatonic collection."""
    mid, low = audio_census(path, t0, t1)
    rel = np.roll(mid, -tonic)
    lines = [format_report(rel, dst, tonic, title or path.name)]
    order = np.argsort(low)[::-1][:3]
    lines.append("  low band (40-220 Hz): " + "  ".join(f"{PC_NAMES[i]} {100 * low[i]:.0f}%" for i in order))
    if set(scale(dst)) in [set(SCALES[m]) for m in MODES]:
        fits = collection_fit(mid)
        home = (tonic - scale(dst)[0] - MODES_OFFSET[_mode_name(dst)]) % 12
        lines.append("  diatonic collections: " + "  ".join(f"{PC_NAMES[k]} major set {100 * v:.1f}%" for v, k in fits[:3])
                     + f"   (this scale uses the {PC_NAMES[home]} major set)")
    return "\n".join(lines)


# semitones from a mode's tonic down to the tonic of the major scale with the same notes
MODES_OFFSET = {"major": 0, "dorian": 2, "phrygian": 4, "lydian": 5, "mixolydian": 7, "minor": 9, "locrian": 11}


def _mode_name(dst: str) -> str:
    target = set(scale(dst))
    return next(m for m in MODES if set(SCALES[m]) == target)
