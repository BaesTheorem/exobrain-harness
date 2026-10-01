"""Lyric text and word timing for lyric videos.

  lyrics  fetch synced lyrics from LRCLIB into work/lyrics_rows.json
  words   time every sung word: CTC forced alignment (torchaudio MMS_FA) of the known
          text against a vocal stem, one lyric row at a time, then an onset-based repair
          of rows whose first word caught the previous line's held note
  check   onset instrument: vocal onset strength at the word starts vs. random times
  strips  spectrogram strips with word-start markers, one per row

Every command prints row ids, times and statistics only. The lyric text stays in the
files, because the model output filter blocks text that repeats song lyrics.

INVARIANTS
- No function prints or returns lyric text to the terminal.
- words.json keeps one record per display word, in row order, with t0 < next t0 inside a row.
"""
from __future__ import annotations

import copy
import json
import os
import re
import urllib.parse
import urllib.request

import numpy as np

SR = 16000
UA = {"User-Agent": "mist-vid (lyric video tool)"}
ROWS = "work/lyrics_rows.json"
WORDS = "work/words_final.json"
LINES = "work/lines.json"


# ---- lyrics -----------------------------------------------------------------------
def _lrc_rows(synced: str) -> list[tuple[float, str]]:
    pat = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")
    out = []
    for line in synced.splitlines():
        m = pat.match(line)
        if m:
            out.append((int(m[1]) * 60 + float(m[2]), m[3].strip()))
    return out


def lyrics(artist: str, title: str, duration: float | None = None, out: str = ROWS, pick: int | None = None):
    """Search LRCLIB, keep the synced entry closest to `duration`, write rows. Metadata only on stdout."""
    q = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
    with urllib.request.urlopen(urllib.request.Request("https://lrclib.net/api/search?" + q, headers=UA),
                                timeout=30) as r:
        res = [x for x in json.load(r) if x.get("syncedLyrics")]
    if not res:
        raise SystemExit("LRCLIB has no synced lyrics for this track")
    for x in res:
        rows = _lrc_rows(x["syncedLyrics"])
        print(f"  id={x['id']} dur={x.get('duration')} album={x.get('albumName')!r} rows={len(rows)} "
              f"words={sum(len(t.split()) for _, t in rows)} first={rows[0][0]:.2f} last={rows[-1][0]:.2f}")
    if pick is not None:
        best = next(x for x in res if x["id"] == pick)
    else:
        best = min(res, key=lambda x: abs(float(x.get("duration") or 0) - (duration or 0)))
    rows = _lrc_rows(best["syncedLyrics"])
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump({"source": f"lrclib:{best['id']}",
               "rows": [{"row": i, "t": round(t, 3), "text": txt} for i, (t, txt) in enumerate(rows)]},
              open(out, "w"), indent=1)
    print(f"picked id={best['id']}: {len(rows)} rows ({sum(1 for _, t in rows if t)} sung) -> {out}")


# ---- forced alignment --------------------------------------------------------------
def _norm(word: str) -> list[str]:
    """Display word -> alignment tokens (hyphenated words split into their parts)."""
    parts = [re.sub(r"[^a-z']", "", p.lower()) for p in re.split(r"[-‐-―]", word)]
    return [p.strip("'") or p for p in parts if p.replace("'", "")]


def _fill(w: dict, ch: list):
    if not ch:
        w.update(t0=None, t1=None, score=0.0, chars=[], parts=[])
        return
    w["t0"], w["t1"] = round(ch[0][1], 3), round(ch[-1][2], 3)
    w["score"] = round(float(np.mean([c[3] for c in ch])), 3)
    w["chars"] = [[round(a, 3), round(b, 3)] for _, a, b, _ in ch]
    w["parts"] = [[round(min(a for p, a, _, _ in ch if p == pi), 3), round(max(b for p, _, b, _ in ch if p == pi), 3)]
                  for pi in range(w["nparts"]) if any(p == pi for p, *_ in ch)]


def _align_rows(rows, wav, model, d, only=None, starts=None, pre=0.45, post=0.25, ctx=1.0):
    """Align each sung row alone inside its LRC window, with a <star> at both ends."""
    import torch
    import torchaudio.functional as F
    words = []
    n = wav.shape[1]
    for ri, r in enumerate(rows):
        disp = r["text"].split()
        if not disp or (only is not None and ri not in only):
            continue
        t_row = starts.get(ri, r["t"]) if starts else r["t"]
        nxt = next((x["t"] for x in rows[ri + 1:]), n / SR)
        a, b = max(0.0, t_row - pre), min(n / SR, nxt + post)
        c0, c1 = max(0.0, a - ctx), min(n / SR, b + ctx)
        with torch.inference_mode():
            e, _ = model(wav[:, int(c0 * SR):int(c1 * SR)])
        e = e[0]
        fps = e.shape[0] / (c1 - c0)
        f0, f1 = int((a - c0) * fps), int((b - c0) * fps)
        lp = torch.log_softmax(e[f0:f1], dim=-1)[None]
        toks: list[int] = [d["*"]]
        owner: list[tuple[int, int] | None] = [None]
        base = len(words)
        for wi, w in enumerate(disp):
            parts = _norm(w)
            for pi, p in enumerate(parts):
                for ch in p:
                    if ch in d:
                        toks.append(d[ch])
                        owner.append((base + wi, pi))
            words.append({"row": ri, "w": wi, "text": w, "nparts": len(parts)})
        toks.append(d["*"])
        owner.append(None)
        ali, sc = F.forced_align(lp, torch.tensor(toks, dtype=torch.int32)[None], blank=0)
        per: dict[int, list] = {}
        for sp, own in zip(F.merge_tokens(ali[0], sc[0].exp()), owner, strict=True):
            if own is not None:
                per.setdefault(own[0], []).append((own[1], a + sp.start / fps, a + sp.end / fps, float(sp.score)))
        for k in range(base, len(words)):
            _fill(words[k], per.get(k, []))
    return words


def _onset_env(y: np.ndarray, sr: int, hop: int):
    import librosa
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop, aggregate=np.median)
    rdb = 20 * np.log10(librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0] + 1e-9)
    return env / (env.max() + 1e-9), rdb


def words(vox: str, rows_path: str = ROWS, out: str = WORDS, overrides: str = "work/timing_overrides.json"):
    """Per-row alignment, onset repair, merge, manual overrides. Writes words + lines JSON."""
    import soundfile as sf
    import torch
    import torchaudio
    from torchaudio.pipelines import MMS_FA as bundle
    rows = json.load(open(rows_path))["rows"]
    y, sr = sf.read(vox, dtype="float32")
    y = y.mean(1) if y.ndim == 2 else y
    wav = torchaudio.functional.resample(torch.from_numpy(y)[None], sr, SR)
    model = bundle.get_model(with_star=True)
    model.eval()
    d = {c: i for i, c in enumerate(bundle.get_labels(star="*"))}
    p2 = _align_rows(rows, wav, model, d)
    # onset repair: a row whose first word sits on no onset probably caught the last line's tail
    hop = 441
    env, rdb = _onset_env(y, sr, hop)

    def fr(t: float) -> int:
        return int(round(t * sr / hop))

    def on(t: float) -> float:
        return float(env[max(0, fr(t) - 4):fr(t) + 5].max())

    def rise(t: float) -> float:
        return float(rdb[fr(t):fr(t) + 15].mean() - rdb[max(0, fr(t) - 15):fr(t)].mean())

    by: dict[int, list] = {}
    for w in p2:
        by.setdefault(w["row"], []).append(w)
    starts = {}
    for ri, ws in by.items():
        a, lrc = ws[0]["t0"], rows[ri]["t"]
        k0 = fr(lrc - 0.1)
        to = (k0 + int(np.argmax(env[k0:fr(lrc + 0.5)]))) * hop / sr
        if abs(to - a) >= 0.15 and rise(a) < rise(to) - 3:
            starts[ri] = to + 0.06     # the window opens 0.06 s before the onset
    p3 = _align_rows(rows, wav, model, d, only=set(starts), starts=starts, pre=0.12) if starts else []
    final = copy.deepcopy(p2)
    for ri in starts:
        a2 = [w for w in p2 if w["row"] == ri]
        a3 = [w for w in p3 if w["row"] == ri]
        if not a3 or on(a2[0]["t0"]) >= 0.15 or on(a3[0]["t0"]) <= on(a2[0]["t0"]):
            continue
        for w in final:
            if w["row"] == ri:
                src = next(x for x in a3 if x["w"] == w["w"])
                w.update({k: src[k] for k in ("t0", "t1", "score", "chars", "parts")})
        print(f"r{ri:02d}: first word moved {a2[0]['t0']:.2f} -> {a3[0]['t0']:.2f} (onset repair)")
    if os.path.exists(overrides):
        for key, t in json.load(open(overrides)).items():      # {"r50w1": 155.77}
            ri, wi = int(key[1:3]), int(key.split("w")[1])
            for w in final:
                if w["row"] == ri and w["w"] == wi:
                    shift = t - w["t0"]
                    w["t0"] = t
                    w["chars"] = [[a + shift, b + shift] for a, b in w["chars"]] if abs(shift) < 0.4 else [[t, t + 0.12]]
                    w["manual"] = True
            print(f"override {key} -> {t:.2f}")
    for ri in sorted({w["row"] for w in final}):
        ws = [w for w in final if w["row"] == ri]
        for a_, b_ in zip(ws, ws[1:], strict=False):
            if b_["t0"] <= a_["t0"]:
                b_["t0"] = round(a_["t0"] + 0.04, 3)
            if a_["t1"] > b_["t0"]:
                a_["t1"] = b_["t0"]
    json.dump({"source": rows_path, "vox": vox, "words": final}, open(out, "w"), indent=0)
    lines_(final)
    print(f"{len(final)} words in {len(by)} rows -> {out}")


def lines_(final: list[dict], out: str = LINES):
    """work/lines.json: [{row, start, end}] per sung row, the targets of the L anchors (L1 = first sung row)."""
    by: dict[int, list] = {}
    for w in final:
        by.setdefault(w["row"], []).append(w)
    json.dump([{"row": r, "start": ws[0]["t0"], "end": max(w["t1"] for w in ws)} for r, ws in sorted(by.items())],
              open(out, "w"), indent=0)


# ---- instruments ---------------------------------------------------------------------
def check(vox: str, words_path: str = WORDS):
    """Onset strength at word starts, shifted -0.3..+0.3 s, against random times (the control)."""
    import soundfile as sf
    W = [w for w in json.load(open(words_path))["words"] if w["t0"] is not None]
    y, sr = sf.read(vox, dtype="float32")
    y = y.mean(1) if y.ndim == 2 else y
    hop = 441
    env, _ = _onset_env(y, sr, hop)
    t0s = np.array([w["t0"] for w in W])

    def at(ts, s):
        return float(np.mean([env[max(0, int(round((t + s) * sr / hop)) - 3):int(round((t + s) * sr / hop)) + 4].max()
                              for t in ts]))
    print("onset strength at word starts by shift (peak belongs at +0.00):")
    print("  " + "  ".join(f"{s:+.2f}:{at(t0s, s):.3f}" for s in np.arange(-0.30, 0.31, 0.05)))
    rnd = np.random.default_rng(1).uniform(t0s.min(), t0s.max(), len(t0s))
    print(f"  control, random times: {at(rnd, 0):.3f}")
    du = np.array([w["t1"] - w["t0"] for w in W])
    print(f"word length s: median {np.median(du):.3f}, max {du.max():.2f}, under 0.08 s: {int((du < 0.08).sum())}")


def strips(vox: str, rows_spec: str, out: str, rows_path: str = ROWS, words_path: str = WORDS):
    """Mel spectrogram per row: blue = LRC stamp, red = word starts (numbered). No text."""
    import cv2
    import librosa
    import soundfile as sf
    rows = json.load(open(rows_path))["rows"]
    W = json.load(open(words_path))["words"]
    y, sr = sf.read(vox, dtype="float32")
    y = y.mean(1) if y.ndim == 2 else y
    hop = 256
    M = librosa.power_to_db(librosa.feature.melspectrogram(y=y, sr=sr, n_fft=2048, hop_length=hop, n_mels=96,
                                                           fmax=6000), ref=np.max)
    px = 220
    out_rows = []
    for ri in [int(x) for x in rows_spec.split(",")]:
        t0 = rows[ri]["t"] - 0.8
        t1 = next((x["t"] for x in rows[ri + 1:]), rows[ri]["t"] + 6) + 0.4
        a, b = int(t0 * sr / hop), int(t1 * sr / hop)
        img = np.clip((M[::-1, a:b] + 70) / 70, 0, 1)
        img = cv2.applyColorMap(cv2.resize((img * 255).astype(np.uint8), (int((t1 - t0) * px), 110)),
                                cv2.COLORMAP_BONE)

        def X(t: float, t0: float = t0) -> int:
            return int((t - t0) * px)
        cv2.line(img, (X(rows[ri]["t"]), 0), (X(rows[ri]["t"]), 109), (255, 120, 0), 2)
        for w in W:
            if w["row"] == ri and w["t0"] is not None:
                cv2.line(img, (X(w["t0"]), 50), (X(w["t0"]), 109), (0, 0, 255), 2)
                cv2.putText(img, str(w["w"]), (X(w["t0"]) + 2, 106), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
        lab = np.zeros((110, 90, 3), np.uint8)
        cv2.putText(lab, f"r{ri:02d}", (8, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 220, 255), 2)
        out_rows.append(np.hstack([lab, img]))
    wd = max(r.shape[1] for r in out_rows)
    cv2.imwrite(out, np.vstack([np.pad(r, ((0, 6), (0, wd - r.shape[1]), (0, 0))) for r in out_rows]),
                [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(out)
