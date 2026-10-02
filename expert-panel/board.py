"""Storage for an expert panel's shared message board.

A run directory holds one append-only JSONL board. Several processes append to
it at the same time (one board server per panelist, the orchestrator, the
liaison CLI), so every write holds an exclusive flock on board.lock.

INVARIANTS
- Post ids run 1..N in file order and are assigned under the lock.
- Posts are never edited or removed. An answer is a new post with reply_to.
- state.json is replaced whole through a rename, so a reader never sees half
  a file. Only the orchestrator writes it.
"""

from __future__ import annotations

import fcntl
import json
import os
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

LIAISON = "liaison"
MODERATOR = "moderator"
CRITERIA = ("demand", "reach", "build", "speed", "durability", "fit")
# Kinds every panelist sees, even in a gated round.
SHARED_KINDS = {"question", "answer", "liaison-note"}

Post = dict[str, Any]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


@contextmanager
def locked(run: Path) -> Iterator[None]:
    with open(run / "board.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_state(run: Path) -> dict[str, Any]:
    try:
        return json.loads((run / "state.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_state(run: Path, state: dict[str, Any]) -> None:
    tmp = run / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, run / "state.json")


def read_posts(run: Path) -> list[Post]:
    path = run / "board.jsonl"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_post(run: Path, author: str, kind: str, body: str, title: str = "",
                reply_to: int | None = None, data: Any = None) -> Post:
    with locked(run):
        post: Post = {"id": len(read_posts(run)) + 1, "ts": now_iso(),
                      "round": read_state(run).get("round", ""), "author": author,
                      "kind": kind, "title": title.strip(), "body": body.strip()}
        if reply_to:
            post["reply_to"] = int(reply_to)
        if data is not None:
            post["data"] = data
        with open(run / "board.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(post, ensure_ascii=False) + "\n")
    return post


def answer_for(posts: list[Post], qid: int) -> Post | None:
    return next((p for p in posts if p["kind"] == "answer" and p.get("reply_to") == qid), None)


def unanswered(posts: list[Post]) -> list[Post]:
    answered = {p.get("reply_to") for p in posts if p["kind"] == "answer"}
    return [p for p in posts if p["kind"] == "question" and p["id"] not in answered]


def visible(posts: list[Post], viewer: str, gated: bool) -> list[Post]:
    """In a gated round a panelist sees the Q&A, the liaison, the moderator and its own posts."""
    if not gated:
        return posts
    return [p for p in posts
            if p["author"] in (viewer, LIAISON, MODERATOR) or p["kind"] in SHARED_KINDS]


def format_post(p: Post, names: dict[str, str]) -> str:
    who = names.get(p["author"], p["author"])
    head = f"#{p['id']} | {p.get('round') or '-'} | {who} [{p['author']}] | {p['kind']}"
    if p.get("reply_to"):
        head += f" | reply to #{p['reply_to']}"
    head += f" | {p['ts'][11:16]}"
    title = f"\n**{p['title']}**" if p.get("title") else ""
    return f"{head}{title}\n{p['body']}"


def score_table(posts: list[Post]) -> str:
    """Mean score per criterion per item. A scorer's later row for an item replaces the earlier one."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for p in posts:
        if p["kind"] == "scores":
            for row in p.get("data") or []:
                latest[(p["author"], str(row["item"]).strip().upper())] = row
    if not latest:
        return "No scores submitted yet."
    by_item: dict[str, list[dict[str, Any]]] = {}
    for (_, item), row in latest.items():
        by_item.setdefault(item, []).append(row)
    rows: list[tuple[float, str, int, list[float], float]] = []
    for item, rs in by_item.items():
        per_criterion = [statistics.mean(r[c] for r in rs) for c in CRITERIA]
        per_scorer = [statistics.mean(r[c] for c in CRITERIA) for r in rs]
        rows.append((statistics.mean(per_scorer), item, len(rs), per_criterion,
                     max(per_scorer) - min(per_scorer)))
    lines = ["| item | scorers | " + " | ".join(CRITERIA) + " | mean | spread |",
             "|" + "---|" * (len(CRITERIA) + 4)]
    for mean, item, n, per_criterion, spread in sorted(rows, reverse=True):
        cells = " | ".join(f"{v:.1f}" for v in per_criterion)
        lines.append(f"| {item} | {n} | {cells} | {mean:.2f} | {spread:.1f} |")
    lines += ["", "Scores run from 1 (bad) to 5 (good). mean = average over criteria and scorers. "
              "spread = highest scorer mean minus lowest (disagreement)."]
    return "\n".join(lines)
