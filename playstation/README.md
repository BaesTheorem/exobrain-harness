# PlayStation Remote Control

Remote control of the household PS5 from this Mac, via [pyremoteplay](https://github.com/ktnrg45/pyremoteplay)
(an open-source implementation of Sony's Remote Play protocol).

## What's here vs. gitignored

- `requirements.txt` — pinned deps that make the unmaintained library work on Python 3.14 / Apple Silicon.
- `.venv/` — gitignored virtualenv.
- **Credentials are NOT in this repo.** pyremoteplay stores the PSN OAuth profile and
  per-console registration keys in `~/.pyremoteplay/.profile.json` in the home directory.
  Treat that file as a secret.

## Setup (rebuild from scratch)

```bash
python3 -m venv .venv
ARCHFLAGS="-arch arm64" .venv/bin/pip install --no-binary netifaces -r requirements.txt
```

Build gotchas discovered the hard way:

- `netifaces` has no arm64 wheel for new Pythons, and pip's source build can emit an
  x86_64 binary even while tagging the wheel `arm64`. Force it with
  `ARCHFLAGS="-arch arm64"` + `--no-binary netifaces`.
- `pyee>=10` breaks the import (`ExecutorEventEmitter` moved); pin `pyee==9.1.1`.
- `async-timeout` is needed by `pyps4-2ndscreen` but not declared — install explicitly.
- `av` (video decode for actually viewing the stream) is optional; without it you can
  still send controller input and wake/standby commands.

## Pairing (one-time, requires a human at the console)

1. On the PS5: Settings → System → Remote Play → Link Device → note the 8-digit PIN.
2. On the Mac: `.venv/bin/pyremoteplay <console-ip> --register` and follow the PSN
   sign-in flow (opens a login URL; paste the redirect URL back), then enter the PIN.

## Discovery notes

- The bundled `pyremoteplay -l` discovery only finds PS4s reliably; PS5s answer a
  discovery probe on **UDP 9302** (protocol version `00030010`), PS4s on UDP 987.
  Direct-by-IP works fine: `RPDevice('<ip>').get_status()`.
- A status of `200 Ok` means awake; `620 Server Standby` means rest mode (wakeable
  once paired).
