# mist-image

MIST's text-to-image CLI. One file, pure Python stdlib (no installs). Generation
runs on a cloud GPU, so nothing touches this 8GB machine's RAM.

```
mist-image/bin/mist-image "a foggy harbor at dawn"
mist-image/bin/mist-image "a red fox in snow" -o fox.png --size 1024 --seed 42
mist-image/bin/mist-image "wide cinematic vista" --width 1344 --height 768 --open
```

- Default output dir: `mist-image/gallery/` (gitignored). The MIST Console
  renders these inline (it serves the harness root via `/file`, so no Console
  restart is ever needed) and you download the keepers from the lightbox.
  Override with `--dir`, `$MIST_IMAGE_DIR`, or a full path in `-o`.
- `stdout` is the saved path only (so callers can capture it); logs go to stderr.

## Keys (one-time, required)

The genuinely keyless image APIs are gone as of mid-2026. Pick one free key and
drop it in the **harness `.env`** (gitignored) — the CLI reads it automatically,
including from scheduled/launchd calls.

**Pollinations (fastest, one token):**
1. Sign in at https://auth.pollinations.ai and create a token.
2. Add to `.env`: `POLLINATIONS_API_KEY=...`

**Cloudflare Workers AI (more reliable, ~100k/day, FLUX.1-schnell):**
1. Free Cloudflare account → note your Account ID.
2. Create an API token with the **Workers AI** permission.
3. Add to `.env`: `CF_ACCOUNT_ID=...` and `CF_API_TOKEN=...`

`--backend auto` (the default) uses Cloudflare when its keys are present,
otherwise Pollinations. Force one with `--backend pollinations|cloudflare`.

## Keys are never committed

Keys live only in the gitignored harness `.env`. This directory ships the code,
not the secrets.
