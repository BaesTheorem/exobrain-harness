"""mist-vid: cut a storybook music video from film footage.

  mist-vid <command> [args]     (run from the project folder, or pass the edit YAML)

Edit and render:
  render EDIT.yaml -o OUT.mp4 [--preview] [--audio MIX.wav] [--from A --to B] [--stills A,B,...]
  audio  EDIT.yaml -o work/mix.wav [--lufs -14]
  check  EDIT.yaml                          clip bounds vs shots, gaps, handle freezes, talking shots
  review VIDEO.mp4 EDIT.yaml PREFIX [A,B]   contact sheets, one frame per clip
  lookdev EDIT.yaml SHOTS GRADES OUT.jpg    grade comparison grid (e.g. 54,595 storybook,golden)

Analysis (outputs under work/):
  proxy  MOVIE [work/proxy.mp4]             480 px frame-exact proxy
  shots  [work/proxy.mp4]                   shot boundaries -> work/shots.csv
  sheets [--srt FILE]                       contact sheets + work/shotlist.json for catalog agents
  cat    [filters]                          query the shot catalog (see --help)
  strip  SPEC [N] [OUT]                     filmstrips: '592,1396' or '5563.3-5577.7'
  words  MOVIE START:DUR ...                whisper word timings from the centre channel
  hear   MIX.wav A-B ...                    transcribe windows of a mix (dialogue QA)
  beats  SONG                               beat_this beats + downbeats -> work/*.npy, bar map
  align  SONG MOVIE START DUR               find a song inside the film's audio, show edits
"""
from __future__ import annotations

import os
import sys


def _chdir_to(path: str) -> str:
    """Run relative to the folder holding the edit YAML; return the YAML's basename."""
    d = os.path.dirname(os.path.abspath(path))
    os.chdir(d)
    return os.path.basename(path)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in ("render", "audio", "check"):
        if not rest:
            print(f"usage: mist-vid {cmd} EDIT.yaml ...")
            return 2
        # outputs given on the command line stay relative to where the user ran it
        rest = [os.path.abspath(x) if i > 0 and os.path.exists(os.path.dirname(os.path.abspath(x)))
                and ("/" in x or x.endswith((".mp4", ".wav", ".mov"))) else x for i, x in enumerate(rest)]
        rest[0] = _chdir_to(rest[0])
        sys.argv = [f"mist-vid {cmd}"] + rest
        if cmd == "render":
            from .render import main as m
        elif cmd == "audio":
            from .audio import main as m
        else:
            from .check import main as m
        m()
        return 0
    from . import analyze as A
    if cmd == "review":
        video, proj = os.path.abspath(rest[0]), rest[1]
        prefix = os.path.abspath(rest[2])
        extra = rest[3] if len(rest) > 3 else None
        A.review(video, _chdir_to(proj), prefix, extra)
    elif cmd == "lookdev":
        out = os.path.abspath(rest[3])
        A.lookdev(_chdir_to(rest[0]), rest[1], rest[2], out)
    elif cmd == "proxy":
        A.proxy(rest[0], rest[1] if len(rest) > 1 else "work/proxy.mp4")
    elif cmd == "shots":
        A.shots(rest[0] if rest else "work/proxy.mp4")
    elif cmd == "sheets":
        srt = rest[rest.index("--srt") + 1] if "--srt" in rest else None
        A.sheets(srt=srt)
    elif cmd == "cat":
        A.cat(rest)
    elif cmd == "strip":
        A.strip(rest[0], int(rest[1]) if len(rest) > 1 else 8, rest[2] if len(rest) > 2 else "work/strip.jpg")
    elif cmd == "words":
        A.words(rest[0], rest[1:])
    elif cmd == "hear":
        A.hear(rest[0], rest[1:])
    elif cmd == "beats":
        A.beats(rest[0])
    elif cmd == "align":
        A.align(rest[0], rest[1], float(rest[2]), float(rest[3]))
    else:
        print(f"unknown command {cmd!r}\n{__doc__}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
