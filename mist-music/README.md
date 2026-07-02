# mist-music

MIST's music tool. Three real jobs, one CLI:

1. **Read sheet music → hear it.** Feed a MIDI file, a MusicXML/`.mxl` score, or a
   **photo/scan/PDF of a printed score**, and it renders to audio.
2. **Transcribe an audio clip → notation.** Feed an mp3/wav and it hands back MIDI
   and MusicXML, so MIST can "read" what you played or hummed.
3. **Generate a full MP3 song from a text prompt** (vocals, lyrics, production;
   optionally conditioned on a melody clip or sheet music), on a cloud GPU so it
   never touches this 8GB machine's RAM.

The reliable core (render + transcribe) runs **entirely locally** and needs no key.
`gen` uses a free public Hugging Face Space, so it needs **no key either** (an
`HF_TOKEN` is used only if present, for higher quota).

## Usage

```bash
bin/mist-music render score.mid                 # MIDI      -> out/score.mp3
bin/mist-music render sonata.musicxml --wav     # MusicXML  -> WAV
bin/mist-music render page.png --keep-xml       # photo of a score (OMR) -> mp3 + .musicxml
bin/mist-music render score.pdf                 # PDF score -> mp3
bin/mist-music play score.mid                   # render + open in the default player

bin/mist-music transcribe riff.mp3              # audio -> riff.mid + riff.musicxml
bin/mist-music transcribe hum.wav --render      # ...and render the cleaned MIDI back to mp3

bin/mist-music gen "dreamy synthwave, warm analog pads, 100 BPM, nostalgic" --duration 90
bin/mist-music gen "acoustic folk, fingerpicked guitar, soft vocals" --lyrics "[verse]..."
bin/mist-music gen "cinematic orchestral, hopeful" --instrumental
bin/mist-music gen "lo-fi hip hop over this melody" --ref riff.wav        # condition on a clip
bin/mist-music gen "full band version of this tune" --ref lead.musicxml   # ...or sheet music
```

`render`/`transcribe` output defaults to `out/` (gitignored). `gen` output defaults
to `tmp/audio/` under the harness so the MIST Console can serve + play it inline.
Override any with `-o file` or `--dir`.

`gen`'s first positional arg is **style tags** (genre, mood, instruments, BPM), not
a sentence. Words go in `--lyrics` with `[verse]`/`[chorus]`/`[bridge]` tags.

## How it works

| Command | Pipeline | Deps |
|---|---|---|
| `render` (MIDI) | `mid2mp3` (FluidSynth + `FluidR3Mono_GM.sf3`) → ffmpeg | local |
| `render` (MusicXML/ABC) | music21 → MIDI → `mid2mp3` | local |
| `render` (image/PDF) | **oemer OMR** → MusicXML → music21 → MIDI → `mid2mp3` | local |
| `transcribe` | `mp32mid` (Spotify Basic Pitch, ONNX) → MIDI → music21 → MusicXML | local |
| `gen` | **ACE-Step v1.5** on a free HF Space via `gradio_client`; `--ref` → audio2audio | cloud, keyless |

Reuses the existing **midi-tools** installs (`~/.local/bin/mid2mp3`, `~/.local/bin/mp32mid`)
rather than duplicating the render/transcribe machinery. See `project_midi_tools` memory.

## Setup

- **Local core:** already good to go. Needs `fluidsynth` + `ffmpeg` (installed), the
  midi-tools scripts, and this project's `.venv` (music21 + oemer).
  Rebuild the venv with:
  ```bash
  python3 -m venv .venv
  .venv/bin/python -m pip install music21 oemer verovio cairosvg
  ```
  (`verovio`/`cairosvg` are only used to engrave test scores; the core doesn't need them.)
  For multi-page PDF scores, `brew install poppler` (else it falls back to page 1 via `sips`).

- **`gen`:** no setup needed. It calls **ACE-Step v1.5** on a free public Hugging Face
  Space via `gradio_client` (installed in the venv). Full songs with vocals + lyrics,
  up to 240s, generated on their GPU. Optional: set `HF_TOKEN` in the harness `.env`
  for higher quota, or `MIST_MUSIC_SPACE` / `--space` to point at a different ACE-Step
  Space if the default is asleep or busy.
  - **Quality upgrade (not built):** Suno's free tier sounds better but has no free API;
    it would mean browser-driving a logged-in Suno account (fragile, ToS-gray). Wired as
    a possible `--backend suno` if we ever want top-tier vocals.

## Notes / gotchas

- **OMR is estimation, not magic.** Clean, high-contrast, straight-on scans work best;
  a skewed phone photo of a dense orchestral page will mangle. Use `--keep-xml` to see
  what it recognized and hand-correct the MusicXML if needed.
- **Basic Pitch is also estimation** — great for monophonic lines and simple polyphony,
  fuzzier on dense mixes. It's transcription, not source separation.
- Nothing here is resident; every model run is a transient subprocess, safe under the
  `mem-watchdog`. Neural generation deliberately runs off-machine.
