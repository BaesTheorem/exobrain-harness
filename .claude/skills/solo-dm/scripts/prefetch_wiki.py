#!/usr/bin/env python3
"""Prefetch wiki summaries for every marker in a campaign, plus optional
per-marker homebrew notes.

    python3 prefetch_wiki.py --slug <campaign-slug>

Writes `wiki_cache: {title, extract, url, fetched_at}` to each marker so the
dashboard can open the info panel instantly without a live fetch.

Optionally seeds `homebrew_notes` for any marker label found in
`<DATA_ROOT>/<slug>/homebrew_notes.json` — a flat `{label: note}` map. The
file is gitignored; create one per campaign to seed story-relevant notes.
"""
from __future__ import annotations
import argparse, json, sqlite3, sys, time
from datetime import datetime, timezone
from pathlib import Path

# Pull in the fetcher from webui.py (don't duplicate the parsing logic)
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import webui  # noqa: E402

HARNESS_ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = HARNESS_ROOT / "data/solo-dm"


def load_homebrew_notes(slug: str) -> dict[str, str]:
    path = DATA_ROOT / slug / "homebrew_notes.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"warning: could not parse {path}: {e}", file=sys.stderr)
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    args = ap.parse_args()

    db_path = DATA_ROOT / args.slug / "state.sqlite"
    if not db_path.exists():
        sys.exit(f"no db for slug {args.slug!r}")

    homebrew = load_homebrew_notes(args.slug)
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT value FROM world_state WHERE key='map_markers'"
    ).fetchone()
    markers = json.loads(row[0])
    print(f"loaded {len(markers)} markers")

    now = datetime.now(timezone.utc).isoformat()
    fetched = 0
    hit = 0
    seeded = 0
    for m in markers:
        slug = m.get("wiki_slug")
        label = m.get("label", "")
        if label in homebrew:
            m["homebrew_notes"] = homebrew[label]
            seeded += 1
        if not slug:
            continue
        cache = m.get("wiki_cache") or {}
        if cache.get("extract"):
            hit += 1
            continue
        result = webui.api_wiki_summary(slug)
        m["wiki_cache"] = {
            "title": result.get("title") or label,
            "extract": result.get("extract", ""),
            "url": result.get("url", ""),
            "error": result.get("error"),
            "fetched_at": now,
        }
        fetched += 1
        short = (result.get("extract", "") or "").replace("\n", " ")[:80]
        marker = "✓" if result.get("extract") else "∅"
        print(f"  {marker} {label:22} {short}")
        time.sleep(0.4)  # polite rate limit to fandom

    cid = conn.execute("SELECT id FROM campaigns LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO world_state (campaign_id, key, value) VALUES (?,?,?) "
        "ON CONFLICT(campaign_id, key) DO UPDATE SET value=excluded.value, "
        "updated_at=datetime('now')",
        (cid, "map_markers", json.dumps(markers)),
    )
    conn.commit()
    print(f"\nfetched {fetched} fresh, {hit} already cached")
    if homebrew:
        print(f"homebrew notes seeded on {seeded} markers (from {len(homebrew)}-entry file)")
    else:
        print("no homebrew_notes.json found — skipped homebrew seeding")


if __name__ == "__main__":
    main()
