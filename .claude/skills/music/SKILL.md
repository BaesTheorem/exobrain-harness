---
name: music
description: "Alex's music toolset — generate full songs from a text prompt, render sheet music (MIDI/MusicXML/photo/PDF) to audio, transcribe audio to notation, and build captioned lyric videos from a track + a still image + lyrics. Use when Alex says 'make a song', 'generate music', 'lyric video', 'captioned lyrics video', 'karaoke video', 'transcribe this audio', 'read this sheet music', 'turn this MIDI into audio', 'set these lyrics to the track', or otherwise wants to create, convert, or caption music."
metadata:
  tools_dir: "/Users/alexhedtke/Documents/Exobrain harness"
  mist_music: "mist-music/bin/mist-music (gen / render / transcribe / play)"
  lyric_video: "lyrics-video/ (build_ass.py + render_video.py)"
  whisper: "whisper-cli + one-pace/whisper-models/ggml-large-v3.bin (shared)"
---

# /music

Everything music, in one place. Two toolsets live under the harness; this skill
routes to the right one and carries the operational detail + hard-won gotchas so
we never re-tread ground.

| Alex wants | Tool | Section |
|---|---|---|
| Generate a full MP3 song from a prompt (vocals/lyrics/production) | `mist-music gen` | §1 |
| Hear sheet music (MIDI / MusicXML / photo / scan / PDF of a score) | `mist-music render` | §1 |
| Transcribe an audio clip → MIDI + MusicXML | `mist-music transcribe` | §1 |
| **Captioned lyric video** from a track + a still + lyrics | `lyrics-video/` pipeline | §2 |

Both keep user media (audio, images, rendered output) gitignored; the scripts
themselves are generic and committed. Public-repo privacy still applies.

---

## §1 · mist-music (generate / render / transcribe)

A stdlib CLI at `mist-music/bin/mist-music`. Local core (render + transcribe) is
keyless and offline; `gen` runs **ACE-Step** on a free Hugging Face Space (keyless,
cloud GPU, so it never touches this 8GB machine's RAM). **Read `mist-music/README.md`
before non-trivial work** — it has the full pipeline, deps, and setup.

```bash
mist-music/bin/mist-music gen "acoustic folk, fingerpicked guitar, soft vocals, 90 BPM" --lyrics "[verse]..."
mist-music/bin/mist-music gen "cinematic orchestral, hopeful" --instrumental --duration 90
mist-music/bin/mist-music render score.mid            # MIDI/MusicXML/photo/PDF -> mp3
mist-music/bin/mist-music transcribe riff.mp3         # audio -> riff.mid + riff.musicxml
```

- `gen`'s first arg is **style tags** (genre, mood, instruments, BPM), *not* a
  sentence. Lyrics go in `--lyrics` with `[verse]`/`[chorus]`/`[bridge]` tags.
- `gen` output defaults to `tmp/audio/` so the MIST Console can serve + play it
  inline; `render`/`transcribe` default to `mist-music/out/` (gitignored).
- Show Alex generated audio inline in the Console reply (it renders local media
  with a download control), then say where it saved.

---

## §2 · Lyric-video pipeline (`lyrics-video/`)

Turns **an audio track + a still image + the exact lyrics** into a line-by-line
captioned MP4 (fade in/out, one line at a time, over a blurred-fill background).
Fully offline. Scripts: `lyrics-video/build_ass.py`, `lyrics-video/render_video.py`.

### The one principle that makes it work

**The lyrics Alex gives are ground truth for the WORDS. Whisper supplies only the
TIMING.** Sung/layered vocals mishear badly, so we never trust whisper's text — we
run it for word-level timestamps, then fuzzy-align Alex's exact lines onto that
timeline. Always ask Alex for the exact lyrics, **one on-screen line per line**;
blank lines and `[Section headers]` are ignored (no caption during instrumental
gaps).

### Inputs

- `lyrics-video/work/lyrics.txt` — one on-screen line per line, in order.
- A still image (any aspect; it gets a 16:9 blurred-fill treatment).
- The audio track (mp3/wav).

### Pipeline (run from the harness root)

```bash
cd "/Users/alexhedtke/Documents/Exobrain harness/lyrics-video"

# 1. Transcribe -> word timestamps (shared large-v3 model from onepace)
ffmpeg -y -i TRACK.mp3 -ar 16000 -ac 1 -c:a pcm_s16le work/audio.wav
whisper-cli -m /Users/alexhedtke/Documents/one-pace/whisper-models/ggml-large-v3.bin \
    -f work/audio.wav -l en -dtw large.v3 -ojf -of work/whisper --max-len 0   # -> work/whisper.json

# 2. Background still: full image centered + blurred/darkened self-fill + bottom scrim
ffmpeg -y -i IMAGE -filter_complex "
 [0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,boxblur=40:2,eq=brightness=-0.30:saturation=0.75[bg];
 [0:v]scale=-1:1010,pad=iw+8:ih+8:4:4:color=0x1a1206[fgp];
 [bg][fgp]overlay=(W-w)/2:(H-h)/2 - 20[comp];
 color=black:s=1920x1080,format=rgba,geq=r=0:g=0:b=0:a='if(gt(Y,470),(Y-470)/610*210,0)'[scrim];
 [comp][scrim]overlay=0:0,format=rgb24[out]" -map "[out]" -frames:v 1 work/background.png

# 3. Align lyrics onto whisper timing -> work/timings.json (+ an .ass we don't use)
python3 build_ass.py work/whisper.json work/lyrics.txt work/out.ass

# 4. Render: PIL text sprites composited over the background, piped to ffmpeg
python3 render_video.py work/background.png work/timings.json TRACK.mp3 "OUTPUT.mp4"
```

Output the MP4 next to the source (e.g. `~/Downloads/<Song> - Lyric Video.mp4`).
1920×1080, 24fps, H.264 + AAC.

### Style knobs (tunables at the top of the scripts)

- `render_video.py`: `FONT_PATH` (default **Iowan Old Style**, Roman verses / Bold
  finale), `SIZE` (default 87px), `SIZE_FIN`, `FILL` (warm white), `FILL_FIN`
  (**#D4AF37 metallic gold**), `STROKE`, `FADE_MS` (in `build_ass.py`), `MAXW` wrap,
  margins. Compare fonts by rendering a sample frame before committing to a full
  render.
- **Finale styling** (gold + bold + larger) is triggered by a hard-coded detector
  in `build_ass.py` (`ln.startswith("Hark!")`). Re-point or remove it per song.

### Gotchas — all solved, don't re-derive

- **Stripped ffmpeg has no `ass` / `subtitles` / `drawtext` filter** (no libass /
  freetype). That's *why* text is drawn in Python (Pillow), not burned by ffmpeg.
  Don't reach for `-vf subtitles=…`. **Never replace the system ffmpeg** — onepace
  depends on it; it still encodes H.264 + AAC fine.
- **Whisper intro bleed:** the first sung token gets smeared back across a silent
  intro (a "word" 25 s long). `build_ass.py` clamps any implausibly long word to a
  real sung length so line 1 lands on the actual downbeat.
- **Repeated identical choruses** ("Sinking down…" ×34) make global difflib map
  chorus lines to the *wrong* occurrence (off by whole repeats → chorus seconds
  early/late). `build_ass.py` re-anchors each chorus run inside its verse-bounded
  window (verses have unique, reliably-aligned words), onset-matches when clean,
  and falls back to an even musical cadence anchored at the true first "Sinking"
  onset when whisper's timing there is degenerate (zero/neg-duration tokens, or a
  hallucinated outro loop spaced a mechanical 1.0 s).
- **A chorus can't start implausibly soon after the previous line.** Whisper may
  truncate the last verse line and start its loop early; the fallback floors the
  anchor at the prior line's start + that verse's own line-cadence.
- **Timing won't be beat-perfect on dense mixes.** First pass is whisper-accurate.
  If a line drifts, ask Alex which line and nudge it. Only reach for vocal
  separation (demucs — not installed) if a mix is so dense the timing is rough; it
  isolates vocals for a big accuracy boost but costs compute + a dep.

### Verify before handing over

Grab frames from the **encoded mp4** (not just the sprites) and Read them:
`ffmpeg -y -ss <t> -i OUT.mp4 -frames:v 1 work/chk.png`. Check a normal verse
line, a chorus, and the finale. Confirm `ffprobe` duration matches the audio.

---

## Shared infra & paths

- `whisper-cli` (`/opt/homebrew/bin`) + `ggml-large-v3.bin` under
  `one-pace/whisper-models/` — shared with the onepace subtitle pipeline; don't
  duplicate the model (3 GB).
- `ffmpeg` 8.x at `/opt/homebrew/bin` — encodes fine but is a **minimal build**
  (no libass/drawtext/freetype). Pillow + numpy do the text compositing.
- mist-music reuses **midi-tools** (`~/.local/bin/mid2mp3`, `mp32mid`); see the
  `project_midi_tools` memory.
