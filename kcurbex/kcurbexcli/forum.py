"""Reading topics and posts out of the phpBB board.

INVARIANTS:
- Read-only. Nothing here posts, replies, PMs, or edits. The account is a real person's
  standing in a small community; automated writes are not worth the risk to it.
- Forum ids are the board's, not ours. SHARE and MEETUPS are the only two content
  forums a Tier 1 account can see; everything else 403s or silently renders empty.
- Announcement/sticky topics repeat at the top of every forum listing (phpBB shows
  global announcements in all forums), so callers filter on `pinned` rather than
  assuming a listing is all real content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from .auth import Session

SHARE_FORUM = 30  # "Share Your Adventure!" -- site reports, archived after 60 days
MEETUPS_FORUM = 109  # "Meetups!"

# phpBB renders dates like "Fri Sep 04, 2026 1:34 pm" in the board's local time.
# The board runs America/Chicago, which is also Alex's timezone, so no conversion.
DATE_RE = re.compile(r"[A-Z][a-z]{2} [A-Z][a-z]{2} \d{1,2}, \d{4}(?: \d{1,2}:\d{2} [ap]m)?")
DATE_FORMATS = ("%a %b %d, %Y %I:%M %p", "%a %b %d, %Y")


def parse_forum_date(text: str) -> datetime | None:
    """The first phpBB-style timestamp in `text`, as an aware America/Chicago datetime."""
    m = DATE_RE.search(text or "")
    if not m:
        return None
    for fmt in DATE_FORMATS:
        try:
            naive = datetime.strptime(m.group(0), fmt)
        except ValueError:
            continue
        return naive.astimezone()  # attach the local zone; board time == Alex's time
    return None


@dataclass
class Post:
    author: str
    posted: datetime | None
    text: str
    images: list[str] = field(default_factory=list)


@dataclass
class Topic:
    topic_id: int
    forum_id: int
    title: str
    author: str
    started: datetime | None
    last_post: datetime | None
    replies: int
    pinned: bool
    url: str
    posts: list[Post] = field(default_factory=list)

    @property
    def body(self) -> str:
        """All post text in the thread, oldest first."""
        return "\n\n".join(p.text for p in self.posts if p.text)


def _is_pinned(row) -> bool:
    """phpBB marks stickies/announcements in the row's class list and its title prefix."""
    classes = " ".join(row.get("class") or [])
    if any(k in classes for k in ("sticky", "announce", "global")):
        return True
    prefix = row.select_one(".topic-poster, .responsive-show strong")
    label = prefix.get_text(" ", strip=True).lower() if prefix else ""
    return any(k in label for k in ("announcement", "sticky", "global"))


def list_topics(session: Session, forum_id: int, include_pinned: bool = False) -> list[Topic]:
    """Every topic in a forum, walking pagination until the pages stop advancing."""
    topics: dict[int, Topic] = {}
    start, page_size = 0, 25
    while True:
        soup = session.soup(f"viewforum.php?f={forum_id}&start={start}")
        rows = soup.select("li.row")
        found_new = False
        for row in rows:
            a = row.select_one("a.topictitle")
            if not a:
                continue
            href = a.get("href", "")
            m = re.search(r"[?&]t=(\d+)", href)
            if not m:
                continue
            tid = int(m.group(1))
            # A global announcement is echoed into forums it does not belong to; the row
            # says so with an explicit "in <Other Forum>" suffix.
            meta = " ".join(row.get_text(" ", strip=True).split())
            foreign = re.search(r"»\s*in\s+(.+?)\s*(?:Last post|$)", meta)
            pinned = _is_pinned(row) or bool(foreign)
            if tid in topics:
                continue
            found_new = True
            author_tag = row.select_one(".topic-poster .username, .topic-poster .username-coloured, .username, .username-coloured")
            dates = re.findall(DATE_RE, meta)
            topics[tid] = Topic(
                topic_id=tid,
                forum_id=forum_id,
                title=" ".join(a.get_text(" ", strip=True).split()),
                author=author_tag.get_text(strip=True) if author_tag else "",
                started=parse_forum_date(dates[0]) if dates else None,
                last_post=parse_forum_date(dates[-1]) if dates else None,
                replies=_int_after(meta, r"(\d+)\s+Replies"),
                pinned=pinned,
                url=f"https://www.kcurbex.org/viewtopic.php?t={tid}",
            )
        if not found_new or not rows:
            break
        start += page_size
    out = [t for t in topics.values() if include_pinned or not t.pinned]
    out.sort(key=lambda t: t.started or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


def _int_after(text: str, pattern: str) -> int:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else 0


def load_posts(session: Session, topic: Topic, max_pages: int = 10) -> Topic:
    """Fill in `topic.posts` by reading the thread itself."""
    seen: set[str] = set()
    start = 0
    for _ in range(max_pages):
        soup = session.soup(f"viewtopic.php?t={topic.topic_id}&start={start}")
        blocks = soup.select("div.post")
        if not blocks:
            break
        before = len(topic.posts)
        for block in blocks:
            body = block.select_one("div.postbody")
            if not body:
                continue
            # phpBB gives every post a stable DOM id ("p12345"); use it rather than a
            # text prefix, because a thread can render the same announcement twice and
            # a short start= overrun just re-serves page 1.
            key = block.get("id") or body.get_text(" ", strip=True)[:120]
            if key in seen:
                continue
            seen.add(key)
            topic.posts.append(
                Post(
                    author=_text(block.select_one(".author .username, .author .username-coloured")),
                    posted=parse_forum_date(_text(block.select_one(".author"))),
                    text=_post_text(body),
                    images=[
                        img["src"]
                        for img in block.select("div.postbody img[src]")
                        if "/images/smilies/" not in img.get("src", "")
                    ],
                )
            )
        if len(topic.posts) == before:
            break
        start += 15
    return topic


def _text(tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split()) if tag else ""


def _post_text(body: BeautifulSoup) -> str:
    """A post's own prose, minus phpBB's control furniture and minus quoted replies.

    Quotes are dropped so a site name mentioned once does not get counted again in every
    thread that quotes the post it appeared in.
    """
    clone = BeautifulSoup(str(body), "lxml")
    for junk in clone.select("blockquote, .signature, ul.post-buttons, .back2top, script, style"):
        junk.decompose()
    text = clone.get_text("\n", strip=True)
    lines = [ln for ln in text.splitlines() if ln.strip() not in {"Report", "Quote", "Unread post", ""}]
    # The author/date furniture leads the block; drop a leading bare timestamp line.
    while lines and DATE_RE.fullmatch(lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()
