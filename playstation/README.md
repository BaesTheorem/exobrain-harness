# PlayStation Remote Control

Remote control of the household PS5 from this Mac, via [pyremoteplay](https://github.com/ktnrg45/pyremoteplay)
(an open-source implementation of Sony's Remote Play protocol).

## What's here vs. gitignored

- `requirements.txt` -- pinned deps that make the unmaintained library work on Python 3.14 / Apple Silicon.
- `.venv/` -- gitignored virtualenv.
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
- `async-timeout` is needed by `pyps4-2ndscreen` but not declared -- install explicitly.
- `av` (PyAV) decodes the video. The `cp312-abi3` wheel installs on Python 3.14; `numpy`
  and `pillow` turn frames into arrays and PNGs. Without `av` you can still send
  controller input and wake/standby commands.

## Pairing (one-time, needs a person at the console for about 3 minutes)

The library's own CLI pairs through `input()` prompts. `ps5-pair.py` takes the same
inputs as arguments, so a chat session can drive it:

1. `.venv/bin/python ps5-pair.py login-url` prints the PSN sign-in URL. Sign in with the
   PlayStation account. The browser lands on a redirect page that can look like an error.
   Copy the full URL from the address bar (it carries a single-use code).
2. On the PS5: Settings -> System -> Remote Play -> Link Device. An 8-digit PIN appears.
3. `.venv/bin/python ps5-pair.py register --redirect-url '<url>' --pin <8 digits>` while
   the PIN screen is still open.
4. `.venv/bin/python ps5-pair.py status` shows the console and the registered users.

## Smoke test (frames in, buttons out)

`.venv/bin/python ps5-smoke.py` streams for 8 seconds, counts decoded frames, saves one
PNG per second to `tmp/ps5-smoke/`, taps RIGHT at 3 s and LEFT at 5 s (moves the home
screen selection and back), and prints PASS or FAIL. `--press '' --undo ''` for a
frames-only run. This is the first thing to run after pairing, and the test to rerun
after a console firmware update: the library is unmaintained, so a protocol change
shows up here first.

## Console address

All scripts take `--host`, then `$PS5_HOST`, then a LAN discovery broadcast
(`ps5lib.discover()`, UDP 9302). Nothing hardcodes the console's address.

## Discovery notes

- The bundled `pyremoteplay -l` discovery only finds PS4s reliably; PS5s answer a
  discovery probe on **UDP 9302** (protocol version `00030010`), PS4s on UDP 987.
  Direct-by-IP works fine: `RPDevice('<ip>').get_status()`.
- A status of `200 Ok` means awake; `620 Server Standby` means rest mode (wakeable
  once paired).
## Live link (play through it)

`.venv/bin/python ps5-session.py` holds one Remote Play session open, writes the latest
frame to `tmp/ps5-live/latest.jpg` every 0.5 s, and serves a one-line command protocol
on `tmp/ps5-live/ctl.sock`. Start it in the background (`nohup ... &!`), then drive it
with `ps5ctl`:

```bash
./ps5ctl status                      # frames, fps, uptime
./ps5ctl tap X                       # press and release (aliases: x o sq tri opt)
./ps5ctl 'move 0 -1 1500; tap R1'    # walk forward 1.5 s, then fire
./ps5ctl look 0.6 0 400              # turn right for 0.4 s
./ps5ctl snap /tmp/now.png           # full-size PNG of the current frame
./ps5ctl quit
```

Stick axes: X left -1 to right 1, Y up -1 to down 1. One session per PSN account: the
console drops a local controller signed in as the same account when the link connects,
so the person on the couch plays as Guest (or another profile).
