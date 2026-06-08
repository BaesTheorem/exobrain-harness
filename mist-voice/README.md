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

## What's here (and what's gitignored)

Committed: code, this README, the pipeline scripts.
**Gitignored** (see `.gitignore`): everything that's copyrighted source audio
or a cloned model of a real actor (Thomasin McKenzie voices MIST). Specifically:

- `samples/raw/` — downloaded Pantheon clips (copyright). NOT committed.
- `samples/isolated/` — demucs vocal-isolated stems. NOT committed.
- `samples/reference/` — the clean MIST-only reference set fed to the clone. NOT committed.
- `models/`, `*.pth`, `speaker_embedding*` — the cloned-voice weights/embedding. NOT committed.

## Rebuild from scratch

1. `python3.12 -m venv .venv && .venv/bin/pip install demucs faster-whisper coqui-tts`
2. Source MIST dialogue: `yt-dlp -x --audio-format wav -o samples/raw/<name>.wav <clip-url>`
   (a MIST-scene supercut is the densest source).
3. Transcribe to find MIST-only windows: `scripts/transcribe.py samples/raw/<file>.wav`
4. Extract + isolate those windows into `samples/reference/`.
5. Clone + generate: `scripts/say.py "text"` (XTTS-v2, conditioned on the reference set).

## Ethics / scope

Private, non-distributed personal use only — Alex's own assistant voice, never
published or used to impersonate. MIST is itself a synthetic AI character in the
show. Do not commit the audio or the model; do not redistribute.
