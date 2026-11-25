# private pieces

This folder holds piece files and source tabs for covers of other people's tunes. Git ignores everything here except this file, because a piece file contains the melody.

- `sources/<slug>/*.json`: Hooktheory sections. Get them again with `mist-music/bin/modal-cover fetch URL --slug <slug>`.
- `<piece>.py`: the arrangement. It is in the daily backup, not in git.

To write a new piece, read `../README.md` and start from `screwbot_factory_2.py`, which uses `celtic.Band`. `screwbot_factory.py` is older than `Band` and has its own copies of the helpers.
