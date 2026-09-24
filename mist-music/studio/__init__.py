"""MIST Studio: a local Suno-style song studio on top of ACE-Step 1.5.

Package layout (each module is importable on its own):
  config   -- per-machine settings + harness .env loader
  engine   -- generation backends (HF Space, self-hosted REST API, mock)
  jobs     -- single-worker background queue the UI polls
  library  -- songs and uploads on disk, one folder per song
  stems    -- vocal / instrumental separation (local demucs, cloud fallback)
  assist   -- lyric writer (Claude) and cover art (mist-image)
  server   -- the Flask app
"""
