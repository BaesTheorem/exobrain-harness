"""Extract post records from a target's raw GraphQL dumps. Offline, re-runnable.

Facebook's feed GraphQL is deeply nested and its exact paths drift, so this
walks the JSON structurally rather than by fixed path: find each dict that owns
a `feedback` object (a post), read the shallowest reaction/comment/share counts
inside that feedback (breadth-first, so a preview comment's counts never
masquerade as the post's), and scrape caption text + fbcdn image URLs from the
post's subtree. Dedup by post id, keeping the MAX reactions ever seen.

  fb parse <target>
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from typing import Any

from fbtools import config

FBCDN_RE = re.compile(r"https?://[^\s\"']*(?:fbcdn|scontent)[^\s\"']*", re.IGNORECASE)
HIJACK_PREFIX = re.compile(r"^for\s*\(;;\);")

COMMENT_KEYS = {"total_comment_count", "comment_count", "i18n_comment_count"}
SHARE_KEYS = {"share_count", "i18n_share_count", "reshare_count"}
URL_KEYS = {"wwwURL", "url", "permalink_url", "story_permalink_url"}


def _iter_json_objects(body: str) -> list[Any]:
    body = HIJACK_PREFIX.sub("", body).strip()
    if not body:
        return []
    try:
        return [json.loads(body)]
    except json.JSONDecodeError:
        pass
    objs: list[Any] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            objs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return objs


def _bfs_find_first(obj: Any, keys: set[str]) -> Any:
    q: deque[Any] = deque([obj])
    while q:
        cur = q.popleft()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k in keys:
                    return v
            q.extend(cur.values())
        elif isinstance(cur, list):
            q.extend(cur)
    return None


def _as_count(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, dict):
        for key in ("count", "total_count", "count_reduced"):
            if key in val:
                return _as_count(val[key])
        return None
    if isinstance(val, str):
        s = val.strip().replace(",", "")
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([KkMm]?)", s)
        if not m:
            return None
        mult = {"": 1, "k": 1_000, "m": 1_000_000}[m.group(2).lower()]
        return int(float(m.group(1)) * mult)
    return None


def _iter_feed_nodes(obj: Any) -> list[dict[str, Any]]:
    """Yield each post node from any feed container in the response.

    Modern (Comet) Facebook delivers posts as `<something>_feed.edges[].node`
    (e.g. group_feed, news_feed). We collect the edge nodes wherever a feed
    container appears, which covers both the initial load and scroll pagination.
    """
    nodes: list[dict[str, Any]] = []
    stack: list[Any] = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if (k == "feed" or k.endswith("_feed")) and isinstance(v, dict):
                    edges = v.get("edges")
                    if isinstance(edges, list):
                        for e in edges:
                            if isinstance(e, dict) and isinstance(e.get("node"), dict):
                                nodes.append(e["node"])
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return nodes


def _post_id(node: dict[str, Any], ufi: dict[str, Any] | None) -> str | None:
    val = node.get("post_id")
    if isinstance(val, str) and val:
        return val
    if ufi is not None:
        fb = ufi.get("feedback")
        if isinstance(fb, dict):
            sid = fb.get("subscription_target_id")
            if isinstance(sid, str) and sid:
                return sid
    val = node.get("id")
    return val if isinstance(val, str) and val else None


def _extract_text(node: dict[str, Any]) -> str:
    # Prefer the main post's caption (comet_sections.content.story.message)
    # over any quoted/attached story's text.
    cs = node.get("comet_sections")
    if isinstance(cs, dict):
        content = cs.get("content")
        if isinstance(content, dict):
            story = content.get("story")
            if isinstance(story, dict):
                msg = story.get("message")
                if isinstance(msg, dict) and isinstance(msg.get("text"), str):
                    return msg["text"]
    msg = _bfs_find_first(node, {"message"})
    if isinstance(msg, dict) and isinstance(msg.get("text"), str):
        return msg["text"]
    return ""


def _extract_permalink(node: dict[str, Any]) -> str:
    val = node.get("permalink_url")
    if isinstance(val, str) and "facebook.com" in val:
        return val.split("?")[0]
    val = _bfs_find_first(node, URL_KEYS)
    if isinstance(val, str) and "facebook.com" in val:
        return val.split("?")[0]
    pid = node.get("post_id")
    return f"https://www.facebook.com/{pid}" if isinstance(pid, str) and pid else ""


def _extract_images(node: dict[str, Any]) -> list[str]:
    # The meme media lives under `attachments`; the actor avatar lives
    # elsewhere, so scoping to attachments avoids grabbing profile pics.
    scope = node.get("attachments")
    blob = json.dumps(scope if scope else node)
    seen: dict[str, None] = {}
    for url in FBCDN_RE.findall(blob):
        clean = url.replace("\\/", "/")
        if "emoji" in clean or "static" in clean:
            continue
        seen.setdefault(clean, None)
    return list(seen.keys())


def _extract_author(node: dict[str, Any]) -> dict[str, Any]:
    actor = node.get("actors")
    if isinstance(actor, list) and actor and isinstance(actor[0], dict):
        return {"name": actor[0].get("name"), "id": actor[0].get("id")}
    actor = _bfs_find_first(node, {"actors"})
    if isinstance(actor, list) and actor and isinstance(actor[0], dict):
        return {"name": actor[0].get("name"), "id": actor[0].get("id")}
    return {}


def _year_of(ts: Any) -> int | None:
    if isinstance(ts, int) and ts > 0:
        return int(time.strftime("%Y", time.localtime(ts)))
    return None


def _record_from_node(node: dict[str, Any]) -> dict[str, Any] | None:
    # Engagement lives under the post-level UFI renderer, well away from the
    # node's stub `feedback`. Anchoring on it also keeps comment-level reaction
    # counts (which live under a different subtree) out of the post total.
    ufi = _bfs_find_first(node, {"comet_ufi_summary_and_actions_renderer"})
    if not isinstance(ufi, dict):
        return None
    reactions = _as_count(_bfs_find_first(ufi, {"reaction_count"}))
    if reactions is None:
        reactions = _as_count(_bfs_find_first(ufi, {"i18n_reaction_count"}))
    if reactions is None:
        return None
    pid = _post_id(node, ufi)
    if not pid:
        return None
    cri = _bfs_find_first(ufi, {"comment_rendering_instance"})
    comments = _as_count(_bfs_find_first(cri, {"total_count"})) if isinstance(cri, dict) else None
    if comments is None:
        comments = _as_count(_bfs_find_first(node, COMMENT_KEYS))
    ts = node.get("creation_time")
    if not isinstance(ts, int):
        found = _bfs_find_first(node, {"creation_time"})
        ts = found if isinstance(found, int) else None
    return {
        "id": pid,
        "reactions": reactions,
        "comments": comments,
        "shares": _as_count(_bfs_find_first(ufi, SHARE_KEYS)),
        "creation_time": ts,
        "year": _year_of(ts),
        "text": _extract_text(node),
        "permalink": _extract_permalink(node),
        "images": _extract_images(node),
        "author": _extract_author(node),
    }


def _max_opt(a: Any, b: Any) -> Any:
    """Max of two possibly-None int counts, tolerating None on either side."""
    ints = [v for v in (a, b) if isinstance(v, int)]
    if ints:
        return max(ints)
    return a if a is not None else b


def _merge(into: dict[str, Any], rec: dict[str, Any]) -> None:
    # Reactions/comments/shares climb as a post ages, so keep the highest ever
    # observed for each independently.
    into["reactions"] = max(into["reactions"], rec["reactions"])
    into["comments"] = _max_opt(into.get("comments"), rec.get("comments"))
    into["shares"] = _max_opt(into.get("shares"), rec.get("shares"))
    # Immutable facts: fill in once, don't overwrite.
    for field in ("creation_time", "year"):
        if into.get(field) in (None, 0) and rec.get(field):
            into[field] = rec[field]
    for field in ("text", "permalink"):
        if not into.get(field) and rec.get(field):
            into[field] = rec[field]
    if not into.get("images") and rec.get("images"):
        into["images"] = rec["images"]
    if not into.get("author", {}).get("name") and rec.get("author", {}).get("name"):
        into["author"] = rec["author"]


def parse_target(name: str) -> int:
    target, _ = config.resolve_target(name)
    raw_files = sorted(target.raw.glob("raw-*.jsonl"))
    if not raw_files:
        raise SystemExit(f"No raw dumps in {target.raw}. Run `fb crawl {name}` first.")

    posts: dict[str, dict[str, Any]] = {}
    lines_read = 0
    for rf in raw_files:
        with rf.open("r", encoding="utf-8") as fh:
            for line in fh:
                lines_read += 1
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for obj in _iter_json_objects(rec.get("body", "")):
                    for node in _iter_feed_nodes(obj):
                        r = _record_from_node(node)
                        if r is None:
                            continue
                        if r["id"] in posts:
                            _merge(posts[r["id"]], r)
                        else:
                            posts[r["id"]] = r

    target.posts_file.parent.mkdir(parents=True, exist_ok=True)
    with target.posts_file.open("w", encoding="utf-8") as fh:
        for rec in sorted(posts.values(), key=lambda x: x["reactions"], reverse=True):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Write the true resume cursor from the oldest post actually parsed. This is
    # more accurate than the crawler's live regex estimate, so the next crawl
    # fast-scrolls exactly to the real frontier.
    times = [r["creation_time"] for r in posts.values() if isinstance(r.get("creation_time"), int)]
    if times:
        target.cursor_file.write_text(json.dumps({"oldest_ts": min(times)}))

    dated = sum(1 for r in posts.values() if r.get("year"))
    print(
        f"Parsed {lines_read} raw responses from {len(raw_files)} session file(s).\n"
        f"Unique posts with reaction counts: {len(posts)} ({dated} with a date/year)\n"
        f"Wrote {target.posts_file.relative_to(config.ROOT)} (ranked by reactions)."
    )
    if posts:
        top = max(posts.values(), key=lambda x: x["reactions"])
        print(f"Current #1: {top['reactions']} reactions -- {top['permalink']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="target name")
    args = ap.parse_args(argv)
    return parse_target(args.target)


if __name__ == "__main__":
    raise SystemExit(main())
