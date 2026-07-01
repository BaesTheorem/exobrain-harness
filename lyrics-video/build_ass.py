#!/usr/bin/env python3
"""
Align known lyric lines onto whisper.cpp word timestamps and emit an ASS
subtitle file with per-line fade in/out (one line on screen at a time).

Usage: build_ass.py <whisper_full.json> <lyrics.txt> <out.ass>

The lyric TEXT is ground truth (from the user). Whisper supplies only the
TIMING: we fuzzy-align whisper's (mis)heard word stream to the true lyric
word stream, then read each true line's start/end off the matched words.
"""
import sys, json, re, difflib

WHISPER_JSON, LYRICS_TXT, OUT_ASS = sys.argv[1], sys.argv[2], sys.argv[3]

# ---- tunables ----
FONT        = "Baskerville"
FONTSIZE    = 58
FADE_MS     = 240          # fade in / out per line
GAP_HOLD    = 3.5          # if next line starts within this many s, hold current till then
TAIL        = 1.3          # else, keep line up this long after its own end
LEAD        = 0.10         # nudge each line to appear slightly before the vocal

def norm(w):
    w = w.lower().replace("’", "'").replace("‘", "'")
    w = w.replace("“", '"').replace("”", '"')
    return re.sub(r"[^a-z0-9']", "", w)

# ---------- load whisper words ----------
data = json.load(open(WHISPER_JSON))
segs = data.get("transcription", [])
words = []  # (norm, start_s, end_s)
for seg in segs:
    for tok in seg.get("tokens", []):
        txt = tok.get("text", "")
        if not txt or txt.strip().startswith("["):
            continue
        off = tok.get("offsets", {})
        t0, t1 = off.get("from"), off.get("to")
        if t0 is None or t1 is None:
            continue
        starts_word = txt.startswith(" ") or not words
        n = norm(txt)
        if not n:
            continue
        if starts_word or not words:
            words.append([n, t0 / 1000.0, t1 / 1000.0])
        else:
            words[-1][0] += n
            words[-1][2] = t1 / 1000.0

# ---------- load lyric lines -> flat word list tagged with line ----------
lines = [ln.rstrip("\n") for ln in open(LYRICS_TXT) if ln.strip()]
lyr_words = []      # (norm, line_idx)
for i, ln in enumerate(lines):
    for w in ln.split():
        n = norm(w)
        if n:
            lyr_words.append((n, i))

# whisper bleeds the first sung token of each phrase back across preceding
# silence/instrumental (e.g. the intro): a "word" 25s long. Clamp any word
# whose duration is implausibly long to a real sung-word length before its end.
for w in words:
    if w[2] - w[1] > 2.0:
        w[1] = w[2] - 0.55

wh_seq  = [w[0] for w in words]
ly_seq  = [w[0] for w in lyr_words]

# ---------- align the two word streams ----------
sm = difflib.SequenceMatcher(None, ly_seq, wh_seq, autojunk=False)
# matched[k] = whisper index for lyric word k, or None
matched = [None] * len(lyr_words)
for a, b, size in sm.get_matching_blocks():
    for d in range(size):
        matched[a + d] = b + d

# interpolate whisper time for every lyric word (fill gaps between anchors)
def wh_time(idx):
    return words[idx][1], words[idx][2]

times = [None] * len(lyr_words)
# forward-fill anchors, then interpolate linearly between known anchors
anchor_idx = [k for k in range(len(lyr_words)) if matched[k] is not None]
for k in anchor_idx:
    s, e = wh_time(matched[k])
    times[k] = (s, e)

if not anchor_idx:
    sys.exit("No alignment anchors found. whisper heard nothing matching the lyrics.")

# interpolate between anchors for unmatched lyric words
for a0, a1 in zip(anchor_idx, anchor_idx[1:]):
    if a1 - a0 <= 1:
        continue
    s0 = times[a0][1]      # end of left anchor
    s1 = times[a1][0]      # start of right anchor
    span = s1 - s0
    n = a1 - a0
    for j in range(1, n):
        t = s0 + span * (j / n)
        times[a0 + j] = (t, t)
# extrapolate leading/trailing unmatched words
first = anchor_idx[0]
for k in range(first):
    times[k] = times[first]
last = anchor_idx[-1]
for k in range(last + 1, len(lyr_words)):
    times[k] = times[last]

# ---------- collapse to per-line start/end ----------
line_start = {}
line_end   = {}
for (n, li), (s, e) in zip(lyr_words, times):
    if li not in line_start or s < line_start[li]:
        line_start[li] = s
    if li not in line_end or e > line_end[li]:
        line_end[li] = e

order = sorted(line_start.keys())
starts = [line_start[i] for i in order]
ends   = [line_end[i] for i in order]

# enforce monotonic, non-crossing starts
for i in range(1, len(starts)):
    if starts[i] < starts[i - 1] + 0.30:
        starts[i] = starts[i - 1] + 0.30
    if ends[i] < starts[i] + 0.30:
        ends[i] = starts[i] + 0.30

# ---------- display windows ----------
def ass_t(s):
    if s < 0: s = 0
    h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"

# finale (Verse 7): the triumphant peak -> gold + slightly larger
finale = set()
for i, ln in enumerate(lines):
    if ln.startswith("Hark!"):
        for j in range(i, min(i + 5, len(lines))):
            finale.add(j)

header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lyric,{FONT},{FONTSIZE},&H00F2F6FF,&H00F2F6FF,&H00120A04,&H00000000,0,0,0,0,100,100,0.6,0,1,3,0,2,220,220,132,1

[Events]
Format: Layer, Start, End, Style, MarginL, MarginR, MarginV, Effect, Text
"""

events = []
timings = []
for k, li in enumerate(order):
    s = starts[k] - LEAD
    own_end = ends[k]
    nxt = starts[k + 1] if k + 1 < len(order) else own_end + TAIL
    if nxt - own_end < GAP_HOLD:
        show_end = nxt - 0.05
    else:
        show_end = own_end + TAIL
    if show_end <= s:
        show_end = s + 0.8
    txt = lines[li].replace("{", "(").replace("}", ")")
    pre = f"\\fad({FADE_MS},{FADE_MS})"
    if li in finale:
        pre += "\\c&H6FD8FF&\\fs66"   # warm gold, a touch larger
    events.append(f"Dialogue: 0,{ass_t(s)},{ass_t(show_end)},Lyric,,0,0,0,,{{{pre}}}{txt}")
    timings.append({"text": lines[li], "start": round(s, 3),
                    "end": round(show_end, 3), "finale": li in finale})

open(OUT_ASS, "w").write(header + "\n".join(events) + "\n")
import os
json.dump({"fade": FADE_MS / 1000.0, "lines": timings},
          open(os.path.join(os.path.dirname(OUT_ASS), "timings.json"), "w"), indent=1)

# ---------- diagnostics ----------
anchors = sum(1 for m in matched if m is not None)
print(f"whisper words: {len(words)}  lyric words: {len(lyr_words)}  anchored: {anchors} "
      f"({100*anchors/len(lyr_words):.0f}%)")
print(f"lines: {len(order)}   first line @ {ass_t(starts[0])}   last ends @ {ass_t(ends[-1])}")
print("--- first 8 line timings ---")
for k in range(min(8, len(order))):
    print(f"  {ass_t(starts[k]):>9}  {lines[order[k]][:52]}")
print("--- last 4 line timings ---")
for k in range(max(0, len(order) - 4), len(order)):
    print(f"  {ass_t(starts[k]):>9}  {lines[order[k]][:52]}")
