# mist-voice — local MIST voice for Exobrain

Goal: give the Exobrain assistant MIST's *actual voice* (from the TV show
*Pantheon*) when it speaks — phone calls and any future voice project — using a
**fully offline** voice clone running on this Mac. No cloud TTS, no third-party
voice service.

See [[feedback_voice_mist_pantheon]] in memory for the why.

## Why local (not ElevenLabs)

Alex chose an offline clone over cloud voice services:
- No dependency on a paid cloud TTS that could clone-gate or change terms.
- Fits the local-first, privacy-conscious ethos of the harness.
- Reusable across every voice project, not just the phone.

Tradeoff: Twilio ConversationRelay (the phone's current TTS) only calls
Amazon/Google/ElevenLabs, so the phone needs an audio-path rebuild (raw Twilio
Media Streams) to use a local voice. That's a deferred phase — see the harness
task list.

## Final voice config (approved)

- **Reference: a single clip — `samples/reference/06_need_your_help.wav`.** The
  other takes are parked in `samples/reference/_archive/`. Curation history: the
  all-6 set leaned British (Thomasin McKenzie's NZ vowels, amplified by the phone
  band); per-clip A/B with Alex landed on `need_your_help` alone as the most
  American while still her.
- **Speed 1.0**, default XTTS sampling (via `TTS.api`), pronunciation dict on.
- To revisit accent/prosody, swap clips between `reference/` and `reference/_archive/`.

## What's here (repo is PRIVATE)

Alex made the repo private and chose to KEEP the voice data in it rather than
gitignore it. Committed now: the reference clips (`samples/reference/` +
`_archive/`) and `demo_mist.wav`, alongside all code.

Still gitignored for practical reasons (see `.gitignore`):
- `samples/raw/`, `samples/isolated/` — the raw supercut is >100MB (GitHub's
  per-file limit, no LFS) and is reproducible via yt-dlp.
- `models/` — ~1.8GB of PUBLIC pretrained weights (XTTS + whisper), auto-redownloaded.

Note: MIST is voiced by Thomasin McKenzie. This is private, non-distributed
personal use; do not make the repo public or redistribute the audio.

## Rebuild from scratch

1. `python3.12 -m venv .venv && .venv/bin/pip install demucs faster-whisper coqui-tts`
2. Source MIST dialogue: `yt-dlp -x --audio-format wav -o samples/raw/<name>.wav <clip-url>`
   (a MIST-scene supercut is the densest source).
3. Transcribe to find MIST-only windows: `scripts/transcribe.py samples/raw/<file>.wav`
4. Extract + isolate those windows into `samples/reference/`.
5. Clone + generate: `scripts/say.py "text"` (XTTS-v2, conditioned on the reference set).

## Usage

Resident service (keeps the model loaded; ~28s one-time load):
```bash
.venv/bin/python scripts/serve.py --device cpu --port 8087   # leave running
./bin/mist-say "Good morning, Alex."                          # fast, plays aloud
```
Cold one-shot (reloads model each call, slow — fine for scripts/pre-render):
```bash
.venv/bin/python scripts/say.py "text" -o out.wav --play
```

## Latency reality (measured on this M1 / 8GB, June 2026)

XTTS-v2 warm inference RTF: **~1.78 on CPU, ~1.58 on MPS** (MPS barely helps —
unsupported-op CPU fallback eats the GPU gain). Both are **slower than
real-time**, so a typical response sentence takes ~6-8s to generate.

**Implication for voice surfaces:**
- **Pre-rendered / non-realtime (SHIPPABLE NOW):** notifications read aloud,
  news-briefing podcast, morning briefing / evening recap audio, pre-recorded
  phone check-in set pieces. Latency irrelevant — MIST's voice is perfect here.
- **Live phone conversation (NOT viable on this box):** RTF>1 means dead air per
  turn and gappy streaming. Options if we want it: (a) hybrid — pre-render
  MIST's set pieces, keep cloud TTS for dynamic Q&A; (b) self-host XTTS on a
  GPU / a beefier Mac mini (see MAC-MINI-MIGRATION-PLAN) for real-time; (c)
  accept ~6-8s per-turn latency with a full Media Streams rebuild.

## Ethics / scope

Private, non-distributed personal use only — Alex's own assistant voice, never
published or used to impersonate. MIST is itself a synthetic AI character in the
show. Do not commit the audio or the model; do not redistribute.
