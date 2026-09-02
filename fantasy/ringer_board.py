"""Extract The Ringer's preseason fantasy rankings into a full-PPR tier board.

The rankings page (theringer.com/fantasy-football/<slug>) is a Next.js app that
embeds its whole player dataset in the RSC payload, including per-format
rankings, per-expert rankings, projected points, schedule grades, and analyst
blurbs. This pulls that out so the draft board can be built offline.

Usage:
    python3 fantasy/ringer_board.py [--slug 2026-preseason] [--format ppr]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

FORMATS = ("ppr", "half-ppr", "zero-ppr", "superflex", "dynasty-all")


def fetch(slug: str) -> str:
    url = f"https://theringer.com/fantasy-football/{slug}"
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"
    out = subprocess.run(
        ["curl", "-sL", "--max-time", "40", "-A", ua, url],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def players(html: str) -> list[dict]:
    chunks = re.findall(r'self\.__next_f\.push\(\[\d+,\s*("(?:[^"\\]|\\.)*")\s*\]\)', html, re.S)
    payload = "".join(json.loads(c) for c in chunks)
    key = payload.find('"players":[')
    if key < 0:
        raise SystemExit("no players array in payload -- page structure changed")
    start = payload.index("[", key)
    depth, in_str, esc = 0, False, False
    for i in range(start, len(payload)):
        ch = payload[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return json.loads(payload[start:i + 1])
    raise SystemExit("unterminated players array")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="2026-preseason")
    ap.add_argument("--format", default="ppr", choices=FORMATS)
    ap.add_argument("--out", default=str(HERE / "ringer_board.json"))
    args = ap.parse_args()

    rows = players(fetch(args.slug))
    board = []
    for p in rows:
        rank = p.get("rankings", {}).get(args.format)
        if not rank or rank >= 9999:
            continue
        picks = {e["slug"]: e.get("rankings", {}).get(args.format) for e in p.get("expertPicks", [])}
        spread = [v for v in picks.values() if v and v < 9999]
        stats = p.get("stats", {})
        meta = p.get("playerMeta", {})
        board.append({
            "rank": rank,
            "name": p.get("name"),
            "team": meta.get("teamAbbreviation") or p.get("team"),
            "pos": (p.get("position") or "").upper(),
            "pos_rank": p.get("positionalRankings", {}).get(args.format),
            "bye": meta.get("byeWeek"),
            "auction": (p.get("auctionValues", {}).get(args.format) or "").lstrip("$"),
            "schedule": p.get("schedule"),
            "schedule_rank": p.get("scheduleRank"),
            "traits": p.get("traits", []),
            "injury": p.get("injuryDesignation", ""),
            "last_year_points": stats.get("stats", {}).get("projectedPoints", {}).get(args.format),
            "experts": picks,
            "expert_spread": (max(spread) - min(spread)) if len(spread) > 1 else 0,
            "take": p.get("ourTake", ""),
        })
    board.sort(key=lambda r: r["rank"])
    with open(args.out, "w") as f:
        json.dump({"format": args.format, "slug": args.slug, "players": board}, f, indent=1)
    print(f"{len(board)} players -> {args.out} ({args.format})", file=sys.stderr)


if __name__ == "__main__":
    main()
