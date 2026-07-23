---
name: music
description: "Alex's music toolset -- generate full songs from a text prompt, render sheet music (MIDI/MusicXML/photo/PDF) to audio, transcribe audio to notation, and build captioned lyric videos from a track + a still image + lyrics. Use when Alex says 'make a song', 'generate music', 'lyric video', 'captioned lyrics video', 'karaoke video', 'transcribe this audio', 'read this sheet music', 'turn this MIDI into audio', 'set these lyrics to the track', or otherwise wants to create, convert, or caption music."
metadata:
  tools_dir: "/Users/alexhedtke/Documents/Exobrain harness"
  mist_music: "mist-music/bin/mist-music (gen / render / transcribe / play); venv mist-music/.venv"
  gen_backend: "ACE-Step v1.5 on HF Space ACE-Step/ACE-Step via gradio_client; HF_TOKEN in harness .env for ZeroGPU quota"
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

A stdlib CLI at `mist-music/bin/mist-music`, own venv at `mist-music/.venv`
(music21, oemer, gradio_client). Local core (render + transcribe) is keyless and
offline; `gen` runs **ACE-Step v1.5** on a free Hugging Face Space via
`gradio_client` (cloud GPU, so it never touches this 8GB machine's RAM). **Read
`mist-music/README.md` before non-trivial work** -- full pipeline, deps, setup.

### gen -- text (+ lyrics, + a melody) → a full MP3 song

```bash
mist-music/bin/mist-music gen "acoustic folk, fingerpicked guitar, soft vocals, 90 BPM" --lyrics-file lyrics.txt
mist-music/bin/mist-music gen "cinematic orchestral, hopeful" --instrumental --duration 90
mist-music/bin/mist-music gen "full electric blues band" --ref demo.mp3 --ref-strength 0.35   # seed off a melody
```

Backend: **ACE-Step v1.5 "Studio"** Space `ACE-Step/Ace-Step-v1.5` (default,
`--backend v15`), driving its one big `/generation_wrapper` endpoint. Newer
`xl-turbo` checkpoint (few-step, so `--steps` is clamped to ≤20), plus a real
**`cover`** task mode: pass `--ref <track>` and it routes the source through the
Space's cover pipeline (Source Audio + a precomputed audio-codes encode via
`/lambda_4`) with `--ref-strength` as the cover-strength. `--backend v1` falls
back to the original `ACE-Step/ACE-Step` Space (`/__call__`) if Studio is down.
The adapter builds the 49-param arg vector from the Space's **live defaults** and
overrides by param name, so it survives the Space reordering args.

**ZeroGPU quota is the real constraint, not permission.** ACE-Step has no
copyright filter (unlike Suno, whose upload/lyric checks went distributor-grade
strict after the Nov-2025 Warner settlement and false-positive public-domain and
covers). But the v1.5 cover reserves ~180 s of GPU per gen, and the free
per-account ZeroGPU pool is small, so expect ~1 gen when fresh. HF PRO = 40
min/day (~13 gens). For *hours* of iteration the answer is a rented hourly GPU
(RunPod/Vast ~$0.30-0.50/hr) running ACE-Step 1.5 / YuE (the deferred rig).

Older backend detail: full songs (vocals + lyrics) up to **240 s**, 320 kbps MP3.

- positional `prompt` = **style tags** (genre, mood, instruments, BPM) -- a comma
  list, *not* a sentence.
- `--lyrics "…"` / `--lyrics-file f` -- words, with `[verse]`/`[chorus]`/`[bridge]`
  tags. Omit or pass `--instrumental` → no vocals (`[inst]`).
- `--duration N` -- seconds, ≤ 240 (`-1` = auto).
- `--ref PATH` -- condition on a melody. PATH is an **audio clip OR sheet music**
  (MIDI/MusicXML/score image/PDF; notation is auto-rendered to audio first).
  `--ref-strength 0..1` = how hard it leans on the reference.
- `--steps N` (clamped ≤20 on v15 xl-turbo), `--seed S`, `--backend auto|v15|v1`,
  `--space S`, `-o FILE`, `--dir`, `--no-embed`, `--open`.

**HF token / quota (important):** the free Space runs on **ZeroGPU with an
anonymous per-IP daily quota** (~a handful of gens) -- then `gen` fails with
"exceeded your ZeroGPU quota". `HF_TOKEN` is already wired in the harness `.env`
(Alex's token, sourced from `~/Documents/one-pace/.hf_token`); authenticated, the
allowance is much larger. **Don't re-ask for a token -- it's set.**

### render / transcribe (sheet music ↔ audio ↔ notation)

```bash
mist-music/bin/mist-music render score.mid        # MIDI / MusicXML / score image / PDF -> mp3
mist-music/bin/mist-music transcribe riff.mp3     # audio -> riff.mid + riff.musicxml
```

- `render` reuses `mid2mp3` (FluidSynth). The **image/PDF OMR path (oemer) is
  wired but flaky** -- for a printed score, prefer **reading it with your own
  vision** to pull key/tempo/chords/lyrics, and use any source audio as the
  `--ref` melody, rather than trusting OMR.
- `transcribe` reuses `mp32mid` (Basic Pitch) -- turn a clip or a score into a
  `--ref` seed for `gen`.

### Console embedding (inline player + download button)

`gen` output defaults to `tmp/audio/` and it prints `![title](/abs/path.mp3)`.
The MIST Console renders that local-audio path as an **inline `<audio>` player
(pause / play / scrub) plus a Save-to-Downloads button** -- same chrome as
generated images. So just print the embed line in your reply, then say where it
saved. `render`/`transcribe` default to `mist-music/out/` (gitignored).

- Gotcha: serving audio needs the Console's `/file` allowlist (extended to audio
  in `app.py`), which only loads on a **Console restart**. Manual restart:
  `kill -9 $(/usr/sbin/lsof -nP -iTCP:5014 -sTCP:LISTEN -t); open ~/Desktop/Apps/"MIST Console.app"`
  (AppKit swallows plain SIGTERM → use `-9`). Since the shutdown fix, closing the
  window fully stops the server, so a plain relaunch already reloads code.

### Working method (dialing in a track)

- **Spread, then pick.** Generate a small set of variants in the **background**,
  present them as inline players, let Alex choose, then refine the winner. Don't
  one-shot a final.
- **Lock `--seed` when sweeping one variable** (e.g. `--ref-strength`) so the
  differences are that variable, not a lucky roll.
- **Reference-strength tradeoff:** higher hugs the reference's *melody* but also
  drags in its *timbre* -- a thin/lo-fi reference (e.g. a MuseScore soundfont demo)
  goes **muddy** at high strength; lower is cleaner but drifts off the tune. For
  lo-fi refs the clear-but-faithful pocket is often **~0.2-0.4**. `audio2audio`
  also **locks the output length to the reference clip** (`--duration` is ignored
  when `--ref` is set).
- **Instrumental beds for later vocals** (Alex often adds the voice in Suno):
  pass `--instrumental`, drop vocal descriptors from the tags, and add tags that
  put the **lead instrument on the melody** ("lead electric guitar carries the
  melody") so nothing sags where a singer would be.
- **Top-tier vocals:** ACE-Step vocals can be artifacty. For the best voice Alex
  may take an instrumental bed to **Suno** (free tier, browser-only -- *not* wired
  as a backend). A Suno `--backend` is the noted future upgrade.

---

## §2 · Lyric-video pipeline (`lyrics-video/`)

Turns **an audio track + a still image + the exact lyrics** into a line-by-line
captioned MP4 (fade in/out, one line at a time, over a blurred-fill background).
Fully offline. Scripts: `lyrics-video/build_ass.py`, `lyrics-video/render_video.py`.

### The one principle that makes it work

**The lyrics Alex gives are ground truth for the WORDS. Whisper supplies only the
TIMING.** Sung/layered vocals mishear badly, so we never trust whisper's text -- we
run it for word-level timestamps, then fuzzy-align Alex's exact lines onto that
timeline. Always ask Alex for the exact lyrics, **one on-screen line per line**;
blank lines and `[Section headers]` are ignored (no caption during instrumental
gaps).

### Inputs

- `lyrics-video/work/lyrics.txt` -- one on-screen line per line, in order.
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

### Gotchas -- all solved, don't re-derive

- **Stripped ffmpeg has no `ass` / `subtitles` / `drawtext` filter** (no libass /
  freetype). That's *why* text is drawn in Python (Pillow), not burned by ffmpeg.
  Don't reach for `-vf subtitles=…`. **Never replace the system ffmpeg** -- onepace
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
  separation (demucs -- not installed) if a mix is so dense the timing is rough; it
  isolates vocals for a big accuracy boost but costs compute + a dep.

### Verify before handing over

Grab frames from the **encoded mp4** (not just the sprites) and Read them:
`ffmpeg -y -ss <t> -i OUT.mp4 -frames:v 1 work/chk.png`. Check a normal verse
line, a chorus, and the finale. Confirm `ffprobe` duration matches the audio.

---

## Shared infra & paths

- `whisper-cli` (`/opt/homebrew/bin`) + `ggml-large-v3.bin` under
  `one-pace/whisper-models/` -- shared with the onepace subtitle pipeline; don't
  duplicate the model (3 GB).
- `ffmpeg` 8.x at `/opt/homebrew/bin` -- encodes fine but is a **minimal build**
  (no libass/drawtext/freetype). Pillow + numpy do the text compositing.
- mist-music reuses **midi-tools** (`~/.local/bin/mid2mp3`, `mp32mid`); see the
  `project_midi_tools` memory. Render/transcribe also need `fluidsynth` + the
  `FluidR3Mono_GM.sf3` soundfont and the Basic Pitch venv.
- mist-music `.venv` holds `music21` (MusicXML↔MIDI), `oemer` (OMR), and
  `gradio_client` (ACE-Step). Rebuild: `python3 -m venv mist-music/.venv &&
  mist-music/.venv/bin/python -m pip install music21 oemer gradio_client`.
- See the `project_mist_music` memory for the ACE-Step Space API, the ZeroGPU
  quota gotcha, and reference-conditioning notes.
