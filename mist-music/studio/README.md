# MIST Studio

A local, Suno-style song studio. Describe a song or write it out, get full
tracks with vocals back, cover a track you upload in a new style, repaint a
section, split stems, and keep everything in a library with cover art.

```
mist-music/bin/mist-studio          # http://127.0.0.1:5032
mist-music/bin/mist-studio --open   # and open the browser
```

`/Applications/MIST Studio.app` wraps the same server (app-shell) and starts it
under launchd (`com.exobrain.mist-studio`).

## What it does

| Page | Level | What you get |
|---|---|---|
| Create / Simple | one sentence | The music model's own planner writes style tags, lyrics, BPM, key and length, then renders. "Write it first" shows the draft in Custom before spending GPU time; "Surprise me" loads a random brief. |
| Create / Custom | full control | Title, style-tag chips (genre, mood, instruments, vocals, tempo, production, era), lyrics with `[Verse]`/`[Chorus]` chips, a Claude lyric writer, "Enhance" through the model's LM, language, BPM, key, time signature, length, 1 to 8 takes, model choice. |
| Create / Cover | remix | Pick an upload or a library song, **Analyze** it (the model reports what it hears: tags, lyrics, BPM, key, language and its 5 Hz codes), set the cover strength, change the tags, keep or rewrite the lyrics, render. |
| Create / Repaint | surgery | Regenerate a time range inside a track and keep the rest. |
| Pro controls | every knob | Diffusion steps, guidance, shift, ODE/SDE, custom timesteps, seed lock, ADG and CFG interval, LM temperature / CFG / top-k / top-p / negative prompt, chain-of-thought toggles, quality scores, timed lyrics (LRC), FLAC output, a style-reference track, per-run cover-art override. |
| Library | | Cards with art, inline player, favorite, download, cover-this, repaint, stems, redo art, reuse settings, details (lyrics, LRC, seed, full request JSON), delete. Uploads live here too, with drag and drop. |
| Queue | | Every job with queue position, ETA, elapsed time, cancel, and the error text (a quota rejection shows when it refills). |
| Settings | | Backend, model defaults, art, stems engine, lyric writer, UI sounds, theme seed and mode. |

## Backends

| Backend | Cost | Notes |
|---|---|---|
| **Hugging Face Space** (`ACE-Step/Ace-Step-v1.5`) | free | Runs on ZeroGPU. Every GPU call (generate, analyze, the LM song-writer) reserves about 180 s of the caller's daily pool, so a free account gets a few calls a day; HF PRO is 40 min/day. `HF_TOKEN` from the harness `.env` is sent by default. The error handling parses the "try again in HH:MM:SS" reset and shows it. |
| **Self-hosted ACE-Step server** | GPU rental | `uv run acestep-api` from the ACE-Step 1.5 repo on any box with a GPU (RunPod / Vast at roughly $0.30 to $0.50 an hour), then point Settings at `http://host:8001`. No quota. Speaks the REST contract in the repo's `docs/en/API.md`. |
| **Mock** | none | Returns a stand-in track (something from `tmp/audio`, else a synthesized tone) after a fake wait so the whole app can be driven without a GPU. |

Running the model locally is not an option on this machine: the 1.5 bundle is
10 GB of weights (20 GB for xl-turbo) and the Air has 8 GB.

## Bolted-on tools

- ACE-Step 1.5 (MIT) does the music: text2music, cover, repaint, audio
  understanding, LRC, quality scoring, 50+ vocal languages, 10 s to 10 min.
- demucs (htdemucs, already installed as a uv tool) splits stems locally,
  two-stem (vocals + instrumental) or four-stem. A 30 s clip takes about 14 s
  at a 1.8 GB peak. `--segment 7` is mandatory for the transformer model.
  Cloud fallback: `r3gm/Audio_separator` on Hugging Face, which draws on the
  same ZeroGPU pool.
- Claude writes lyrics and turns a brief into style tags through the `claude`
  CLI in print mode with settings disabled, so no persona leaks in.
- mist-image paints cover art (Cloudflare FLUX, about two seconds).
- Beer CSS on Material Design 3, themed flat and sharp (radius 0, no shadows,
  hairline outlines), Material Symbols Sharp, Roboto, and
  `material-dynamic-colors` for the tonal palette from one seed color.
- UI SFX (`romainsimon/uisfx`, audio CC0) for the click, success, error,
  processing and complete cues. Toggle in Settings.

## Layout

```
studio/
  server.py     Flask routes (33), job bodies, presets
  engine.py     GenRequest + SpaceEngine / ApiEngine / MockEngine
  jobs.py       single-worker queue the page polls
  library.py    library/<id>/{song.mp3, meta.json, cover.png, stems/}, uploads/
  stems.py      demucs local, HF Space fallback
  assist.py     Claude lyrics + mist-image art
  config.py     defaults + config.json (gitignored) + .env loader
  templates/index.html, static/{app.js, app.css, vendor/, sfx/}
```

`library/`, `uploads/`, `downloads/` and `config.json` are gitignored.

## Space API notes

`/generation_wrapper` takes 49 positional arguments. The engine builds the
vector from the Space's live defaults and writes by parameter name
(`PARAM_NAMES` in `engine.py`), where `param_N` is the N-th input wired to the
generate button in the Space's `gradio_ui/events/__init__.py`; `param_40` is a
hidden `gr.State`, so the numbering skips it. Six labels are checked on every
connection and any mismatch is reported as `drift` in `/api/health` and as a
toast.

For cover and repaint the Space skips its LM and reads the source track
directly, so no separate "convert to codes" call is needed; the analysis codes
are passed along when an Analyze has been run (Pro toggle).

## Tests

`pytest tests/test_mist_studio.py` covers request clamping, the parameter map
against a fake 49-slot signature, drift detection, quota parsing, the queue,
and the on-disk library. Nothing there touches the network.
