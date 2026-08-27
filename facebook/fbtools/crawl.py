"""Crawl a named target's feed, dumping GraphQL to data/<target>/raw/.

Resumable: each run walks further back and updates a cursor. Read-only.

  fb crawl <target> --url <feed URL>   # first time: register the target
  fb crawl <target>                     # resume
  fb crawl <target> --minutes 15 --headless
"""

from __future__ import annotations

import argparse
import json
import time

from fbtools import config
from fbtools.session import CheckpointError, FacebookSession, RawWriter


def _read_cursor(target: config.Target) -> int | None:
    if target.cursor_file.exists():
        return json.loads(target.cursor_file.read_text()).get("oldest_ts")
    return None


def _write_cursor(target: config.Target, oldest_ts: int | None) -> None:
    if oldest_ts is None:
        return
    prev = _read_cursor(target)
    keep = min(oldest_ts, prev) if prev else oldest_ts
    target.cursor_file.parent.mkdir(parents=True, exist_ok=True)
    target.cursor_file.write_text(json.dumps({"oldest_ts": keep}))


def crawl(name: str, url: str | None, minutes: float, headless: bool) -> int:
    target, feed_url = config.resolve_target(name, url)
    feed_url = config.sanitize_feed_url(feed_url)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    writer = RawWriter(target.raw / f"raw-{stamp}.jsonl")
    cursor = _read_cursor(target)

    try:
        with FacebookSession(headless=headless) as fb:
            fb.capture_to(writer)
            fb.scroll_feed(feed_url, writer, minutes, cursor, log=print)
    except CheckpointError as e:
        writer.close()
        print(f"\n{e}")
        return 2
    except RuntimeError as e:
        writer.close()
        print(f"\nCrawl error: {e}")
        return 1
    finally:
        writer.close()

    _write_cursor(target, writer.min_ts)
    oldest = time.strftime("%Y-%m-%d", time.localtime(writer.min_ts)) if writer.min_ts else "unknown"
    print(
        f"\nSession done. {writer.responses} GraphQL responses saved to "
        f"{writer.raw_path.relative_to(config.ROOT)}\n"
        f"Oldest post reached this session: {oldest}\n"
        f"Run `fb crawl {name}` again to go further back, or `fb parse {name}` now."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="target name (e.g. dank-ea-memes)")
    ap.add_argument("--url", help="feed URL (only needed the first time)")
    ap.add_argument("--minutes", type=float, default=25.0, help="session time cap")
    ap.add_argument("--headless", action="store_true", help="run without a visible window")
    args = ap.parse_args(argv)
    return crawl(args.target, args.url, args.minutes, args.headless)


if __name__ == "__main__":
    raise SystemExit(main())
