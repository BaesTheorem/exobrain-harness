# lyrics-video

Turn an **audio track + a still image + the exact lyrics** into a captioned,
line-by-line lyric video. Fully offline. The lyrics you provide are ground
truth for the *words*; whisper.cpp supplies only the *timing*.

## Why it works

whisper transcribes what it hears, and sung/layered vocals trip it up. So we
don't trust whisper's words. We run whisper for word-level timestamps, then
**fuzzy-align your exact lyric lines onto whisper's word stream** (difflib), and
read each true line's start/end off the matched words. Mishearings don't matter;
only the timeline does.

## Pipeline

1. **Transcribe** -- whisper.cpp (`whisper-cli`), large-v3, word timestamps:
   ```
   ffmpeg -y -i track.mp3 -ar 16000 -ac 1 -c:a pcm_s16le work/audio.wav
   whisper-cli -m <ggml-large-v3.bin> -f work/audio.wav -l en -dtw large.v3 \
       -ojf -of work/whisper --max-len 0
   ```
2. **Background** -- one ffmpeg pass bakes a 16:9 still: the full image centered,
   a blurred/darkened zoom of itself filling the side bars (no black bars), and a
   bottom gradient scrim for text. (See the `background.png` recipe in git log.)
3. **Align** -- `build_ass.py work/whisper.json work/lyrics.txt work/out.ass`
   also writes `work/timings.json` (per-line start/end + a `finale` flag).
4. **Render** -- `render_video.py work/background.png work/timings.json track.mp3 out.mp4`
   draws each line as a Pillow text sprite (serif, warm white, dark outline; gold
   for finale lines) and composites it over the background with fade in/out, one
   line at a time, piping raw frames to ffmpeg (H.264 + AAC).

## Inputs

- `work/lyrics.txt` -- one on-screen line per line, in order. Blank lines and
  `[Section headers]` are ignored (no on-screen text during instrumental gaps).
- A square or any-ratio still image.
- The audio track.

## Notes / gotchas

- **Stripped ffmpeg:** if your ffmpeg lacks libass/`drawtext` (check
  `ffmpeg -filters | grep ass`), that's why text is drawn in Python via Pillow
  instead of burned by ffmpeg. This path needs no libass.
- **Intro bleed:** whisper often smears the first sung token back across a silent
  intro (a "word" 25 s long). `build_ass.py` clamps any implausibly long word to a
  real sung-word length before its end, so line 1 lands on the actual downbeat.
- **Finale styling:** lines flagged `finale` (edit the detector in `build_ass.py`)
  render gold + bold for a triumphant peak. Remove that block for uniform styling.
- Tunables (font, size, fade, wrap width, margins, colors) live at the top of
  each script.
