"""Fetching the accessible site reports and caching them locally.

INVARIANTS:
- The local cache stores extracted facts plus a short excerpt, not whole threads. It is
  a research index over other people's writing, so it keeps enough to identify and
  locate a site and no more; the canonical text stays on the forum behind its URL.
- The cache is keyed by topic id and is append-and-update, never rebuild: a topic that
  drops off the board (archived past 60 days, or moved to a tier we cannot see) keeps
  its record instead of silently vanishing from the vault.
- Only forums the account can actually read are touched. Nothing here attempts a forum
  id it was not shown.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .auth import HERE, Session
from . import forum as F

CACHE_PATH = HERE / "data" / "reports.json"

# How much of a thread to keep locally. Enough to identify and place a site.
EXCERPT_CHARS = 600
MAX_THREAD_PAGES = 2


@dataclass
class Report:
    topic_id: int
    title: str
    author: str
    posted: str  # ISO date
    url: str
    excerpt: str
    image_count: int
    reply_count: int
    first_seen: str
    # Filled in by the geocoding pass.
    lat: float | None = None
    lon: float | None = None
    confidence: str = "unknown"
    place: str = ""
    reasoning: str = ""
    miles_from_home: float | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def located(self) -> bool:
        return self.lat is not None and self.lon is not None


def load_reports() -> dict[str, Report]:
    if not CACHE_PATH.exists():
        return {}
    raw = json.loads(CACHE_PATH.read_text())
    return {k: Report(**v) for k, v in raw.items()}


def save_reports(reports: dict[str, Report]) -> Path:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ordered = dict(sorted(reports.items(), key=lambda kv: kv[1].posted, reverse=True))
    CACHE_PATH.write_text(json.dumps({k: asdict(v) for k, v in ordered.items()}, indent=2))
    return CACHE_PATH


def scan(session: Session, since_days: int = 365, progress=None) -> tuple[dict[str, Report], list[str]]:
    """Fetch site reports newer than `since_days`. Returns (all reports, ids new this run)."""
    cutoff = datetime.now().astimezone() - timedelta(days=since_days)
    reports = load_reports()
    topics = [
        t for t in F.list_topics(session, F.SHARE_FORUM)
        if t.started and t.started >= cutoff
    ]
    new_ids: list[str] = []
    for i, topic in enumerate(topics, 1):
        if progress:
            progress(i, len(topics), topic.title)
        key = str(topic.topic_id)
        if key in reports:
            continue  # already indexed; the forum archives rather than edits
        F.load_posts(session, topic, max_pages=MAX_THREAD_PAGES)
        body = topic.body.strip()
        reports[key] = Report(
            topic_id=topic.topic_id,
            title=topic.title,
            author=topic.author or (topic.posts[0].author if topic.posts else ""),
            posted=(topic.started or datetime.now().astimezone()).date().isoformat(),
            url=topic.url,
            excerpt=body[:EXCERPT_CHARS],
            image_count=sum(len(p.images) for p in topic.posts),
            reply_count=max(len(topic.posts) - 1, 0),
            first_seen=datetime.now().astimezone().date().isoformat(),
        )
        new_ids.append(key)
    save_reports(reports)
    return reports, new_ids


def needs_geocoding(reports: dict[str, Report]) -> list[Report]:
    """Reports that have never been through the geocoding pass."""
    return [r for r in reports.values() if r.confidence == "unknown" and r.lat is None]
