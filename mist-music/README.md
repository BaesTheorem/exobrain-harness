# mist-music

MIST's music tool. Three real jobs, one CLI:

1. **Read sheet music → hear it.** Feed a MIDI file, a MusicXML/`.mxl` score, or a
   **photo/scan/PDF of a printed score**, and it renders to audio.
2. **Transcribe an audio clip → notation.** Feed an mp3/wav and it hands back MIDI
   and MusicXML, so MIST can "read" what you played or hummed.
3. **Generate music from a text prompt** (optionally conditioned on a melody clip),
   on a cloud GPU so it never touches this 8GB machine's RAM.

The reliable core (render + transcribe) runs **entirely locally** and needs no key.
Only `gen` needs a free Hugging Face token.

## Usage

```bash
bin/mist-music render score.mid                 # MIDI      -> out/score.mp3
bin/mist-music render sonata.musicxml --wav     # MusicXML  -> WAV
bin/mist-music render page.png --keep-xml       # photo of a score (OMR) -> mp3 + .musicxml
bin/mist-music render score.pdf                 # PDF score -> mp3
bin/mist-music play score.mid                   # render + open in the default player

bin/mist-music transcribe riff.mp3              # audio -> riff.mid + riff.musicxml
bin/mist-music transcribe hum.wav --render      # ...and render the cleaned MIDI back to mp3

bin/mist-music gen "warm lo-fi piano, rain on a window, 90bpm"
bin/mist-music gen "epic taiko drums" --model facebook/musicgen-medium --duration 15
```

Output defaults to `out/` (gitignored). Override with `-o file` or `--dir`.

## How it works

| Command | Pipeline | Deps |
|---|---|---|
| `render` (MIDI) | `mid2mp3` (FluidSynth + `FluidR3Mono_GM.sf3`) → ffmpeg | local |
| `render` (MusicXML/ABC) | music21 → MIDI → `mid2mp3` | local |
| `render` (image/PDF) | **oemer OMR** → MusicXML → music21 → MIDI → `mid2mp3` | local |
| `transcribe` | `mp32mid` (Spotify Basic Pitch, ONNX) → MIDI → music21 → MusicXML | local |
| `gen` | Hugging Face serverless Inference API (MusicGen) | `HF_TOKEN` |

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

- **`gen` (optional):** add a free Hugging Face token to the harness `.env`:
  ```
  HF_TOKEN=hf_xxxxxxxx
  ```
  Get one at https://huggingface.co/settings/tokens (role: read). HF's free serverless
  tier is rate-limited (~a few hundred calls/hour) and its MusicGen hosting has been
  spotty in 2026 — if `gen` reports the model isn't served, we wire a fallback backend.

## Notes / gotchas

- **OMR is estimation, not magic.** Clean, high-contrast, straight-on scans work best;
  a skewed phone photo of a dense orchestral page will mangle. Use `--keep-xml` to see
  what it recognized and hand-correct the MusicXML if needed.
- **Basic Pitch is also estimation** — great for monophonic lines and simple polyphony,
  fuzzier on dense mixes. It's transcription, not source separation.
- Nothing here is resident; every model run is a transient subprocess, safe under the
  `mem-watchdog`. Neural generation deliberately runs off-machine.
