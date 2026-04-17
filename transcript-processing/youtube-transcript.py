#!/usr/bin/env python3
"""
Extract a transcript from a YouTube URL or video ID using yt-dlp.

Usage:
    youtube-transcript.py <url_or_id> [--lang en] [--timestamps] [--out FILE]

By default prints clean text (no timestamps, deduped) to stdout.
Falls back from manual captions -> auto-captions.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def extract_video_id(s: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", s)
    if m:
        return m.group(1)
    raise ValueError(f"Could not extract video id from: {s}")


def fetch_subs(video_id: str, lang: str, tmpdir: Path) -> Path | None:
    url = f"https://www.youtube.com/watch?v={video_id}"
    for flag in ("--write-subs", "--write-auto-subs"):
        subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                flag,
                "--sub-lang",
                lang,
                "--sub-format",
                "json3",
                "-o",
                str(tmpdir / "%(id)s.%(ext)s"),
                url,
            ],
            check=False,
            capture_output=True,
        )
        hits = list(tmpdir.glob(f"{video_id}*.json3"))
        if hits:
            return hits[0]
    return None


def parse_json3(path: Path, include_timestamps: bool) -> str:
    data = json.loads(path.read_text())
    out = []
    last = None
    for ev in data.get("events", []):
        segs = ev.get("segs") or []
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if not text or text == last:
            continue
        last = text
        if include_timestamps:
            t = ev.get("tStartMs", 0) / 1000
            h, rem = divmod(int(t), 3600)
            m, s = divmod(rem, 60)
            stamp = f"[{h:02d}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"
            out.append(f"{stamp} {text}")
        else:
            out.append(text)
    return "\n".join(out) if include_timestamps else " ".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="YouTube URL or 11-char video id")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--timestamps", action="store_true")
    ap.add_argument("--out", type=Path, help="Write to file instead of stdout")
    args = ap.parse_args()

    video_id = extract_video_id(args.source)

    with tempfile.TemporaryDirectory() as td:
        sub_file = fetch_subs(video_id, args.lang, Path(td))
        if not sub_file:
            print(
                f"No {args.lang} captions (manual or auto) available for {video_id}",
                file=sys.stderr,
            )
            return 1
        text = parse_json3(sub_file, args.timestamps)

    if args.out:
        args.out.write_text(text)
        print(f"Wrote {len(text)} chars to {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
