"""Rank a target's posts and build local reports: overall top-N and by-year.

  fb report <target> --top 25 --per-year 10

Output goes to report/<target>/ (gitignored): top-memes.md, by-year.md,
report.json, and images/. Contains real names/faces from a private group, so
it never leaves this machine.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

from fbtools import config

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


def _load_posts(target: config.Target) -> list[dict[str, Any]]:
    if not target.posts_file.exists():
        raise SystemExit(f"No parsed posts at {target.posts_file}. Run `fb parse` first.")
    posts: list[dict[str, Any]] = []
    with target.posts_file.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                posts.append(json.loads(line))
    posts.sort(key=lambda x: x.get("reactions", 0), reverse=True)
    return posts


def _download(url: str, dest: Path) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (https fbcdn only)
            data = resp.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False
    if len(data) < 1024:
        return False
    dest.write_bytes(data)
    return True


def _fmt_date(ts: Any) -> str:
    return time.strftime("%b %d, %Y", time.localtime(ts)) if isinstance(ts, int) else "unknown date"


def _snippet(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _ensure_image(post: dict[str, Any], img_dir: Path, cache: dict[str, str]) -> str:
    """Download the post's first image once; return markdown or ''."""
    pid = post["id"]
    if pid in cache:
        return f"\n\n![{pid}]({cache[pid]})" if cache[pid] else ""
    for j, url in enumerate((post.get("images") or [])[:1]):
        dest = img_dir / f"{pid}-{j}.jpg"
        if _download(url, dest):
            cache[pid] = dest.as_posix()
            return f"\n\n![{pid}]({dest.as_posix()})"
    cache[pid] = ""
    return ""


def _post_block(rank: int, p: dict[str, Any], img_dir: Path, cache: dict[str, str]) -> list[str]:
    author = (p.get("author") or {}).get("name") or "unknown"
    text = _snippet(p.get("text", "")) or "*(image-only post)*"
    img_md = _ensure_image(p, img_dir, cache)
    return [
        f"### {rank}. {p.get('reactions', 0):,} reactions",
        "",
        f"- **Posted by:** {author}",
        f"- **Date:** {_fmt_date(p.get('creation_time'))}",
        f"- **Comments:** {p.get('comments') or 0:,} | **Shares:** {p.get('shares') or 0:,}",
        f"- **Link:** {p.get('permalink', 'n/a')}",
        "",
        text + img_md,
        "",
    ]


def _year_summary(posts: list[dict[str, Any]]) -> list[str]:
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    undated = 0
    for p in posts:
        y = p.get("year")
        if isinstance(y, int):
            by_year[y].append(p)
        else:
            undated += 1
    lines = [
        "## Year-by-year summary",
        "",
        "| Year | Posts | Median reactions | Top post reactions | Top post |",
        "| ---: | ---: | ---: | ---: | :--- |",
    ]
    for y in sorted(by_year, reverse=True):
        group = by_year[y]
        med = int(statistics.median([g["reactions"] for g in group]))
        top = max(group, key=lambda x: x["reactions"])
        link = top.get("permalink", "")
        lines.append(
            f"| {y} | {len(group):,} | {med:,} | {top['reactions']:,} | {link} |"
        )
    if undated:
        lines.append(f"| (undated) | {undated:,} | - | - | - |")
    lines.append("")
    return lines


def build(name: str, top_n: int, per_year: int) -> int:
    target, _ = config.resolve_target(name)
    posts = _load_posts(target)
    img_dir = target.report / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    cache: dict[str, str] = {}

    # 1. Overall top-N + year summary.
    overall = [
        f"# {name} -- top posts of all time (by reaction count)",
        "",
        f"Ranked from {len(posts):,} unique posts captured so far. Reaction counts "
        "are the highest observed per post.",
        "",
        "> Private-group data: real names and faces. Local only, never shared.",
        "",
    ]
    overall += _year_summary(posts)
    overall += ["## Overall top posts", ""]
    for i, p in enumerate(posts[:top_n], 1):
        overall += _post_block(i, p, img_dir, cache)
    (target.report / "top-memes.md").write_text("\n".join(overall), encoding="utf-8")

    # 2. Per-year breakdown: each year's top `per_year` posts.
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for p in posts:
        if isinstance(p.get("year"), int):
            by_year[p["year"]].append(p)
    yr_lines = [f"# {name} -- top {per_year} posts of each year", ""]
    for y in sorted(by_year, reverse=True):
        group = sorted(by_year[y], key=lambda x: x["reactions"], reverse=True)
        yr_lines += [f"## {y}", "", f"{len(group):,} posts captured this year.", ""]
        for i, p in enumerate(group[:per_year], 1):
            yr_lines += _post_block(i, p, img_dir, cache)
    (target.report / "by-year.md").write_text("\n".join(yr_lines), encoding="utf-8")

    # 3. Machine-readable manifest.
    manifest = {
        "target": name,
        "total_posts": len(posts),
        "overall_top": [
            {k: p.get(k) for k in ("reactions", "comments", "shares", "year", "permalink", "text")}
            for p in posts[:top_n]
        ],
        "by_year": {
            str(y): [
                {k: p.get(k) for k in ("reactions", "permalink", "text")}
                for p in sorted(by_year[y], key=lambda x: x["reactions"], reverse=True)[:per_year]
            ]
            for y in sorted(by_year, reverse=True)
        },
    }
    (target.report / "report.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"Wrote {(target.report / 'top-memes.md').relative_to(config.ROOT)} and "
        f"by-year.md ({len(posts):,} posts, {len(by_year)} years, "
        f"{sum(1 for v in cache.values() if v)} images downloaded)."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="target name")
    ap.add_argument("--top", type=int, default=25, help="overall top-N")
    ap.add_argument("--per-year", type=int, default=10, help="top-N within each year")
    args = ap.parse_args(argv)
    return build(args.target, args.top, args.per_year)


if __name__ == "__main__":
    raise SystemExit(main())
