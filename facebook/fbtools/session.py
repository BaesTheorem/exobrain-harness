"""Reusable authenticated, read-only Facebook browser session.

Any script can drive Facebook as the logged-in user without re-implementing
cookie auth, GraphQL capture, checkpoint handling, or human-ish pacing:

    from fbtools.session import FacebookSession, RawWriter

    with FacebookSession(headless=True) as fb:
        for g in fb.discover_groups():
            print(g["name"], g["url"])

INVARIANT: read-only. This module never reacts, comments, posts, or clicks
into a post. It navigates and scrolls; callers must keep it that way.
"""

from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, cast

from playwright.sync_api import (
    BrowserContext,
    Page,
    Response,
    TimeoutError as PWTimeout,
    sync_playwright,
)

from fbtools import config

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
GRAPHQL_HINT = "/api/graphql/"
CREATION_TIME_RE = re.compile(rb'"creation_time":(\d{10})')
POST_MARKER_RE = re.compile(rb'"__typename":"Story"|"reaction_count"')
BLOCKED_URL_BITS = ("/login", "checkpoint", "/authenticate", "/recover")


class CheckpointError(RuntimeError):
    """Facebook demanded login or an identity checkpoint."""


class RawWriter:
    """Appends captured GraphQL bodies to a jsonl and tracks light progress."""

    def __init__(self, raw_path: Path) -> None:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        self.raw_path = raw_path
        self._fh = raw_path.open("ab")
        self.responses = 0
        self.post_responses = 0
        self.min_ts: int | None = None

    def handle(self, response: Response) -> None:
        if GRAPHQL_HINT not in response.url:
            return
        try:
            body = response.body()
        except Exception:
            return
        if not body:
            return
        self.responses += 1
        rec = {"url": response.url, "body": body.decode("utf-8", "replace")}
        self._fh.write((json.dumps(rec, ensure_ascii=False) + "\n").encode("utf-8"))
        # Only trust creation_time from responses that actually carry posts;
        # bootstrap/config responses have their own unrelated timestamps that
        # would otherwise pollute the resume cursor.
        if POST_MARKER_RE.search(body):
            self.post_responses += 1
            for m in CREATION_TIME_RE.finditer(body):
                ts = int(m.group(1))
                if self.min_ts is None or ts < self.min_ts:
                    self.min_ts = ts

    def close(self) -> None:
        self._fh.flush()
        self._fh.close()


class FacebookSession:
    def __init__(self, headless: bool = False) -> None:
        self.headless = headless
        self._pw: Any = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None

    def __enter__(self) -> FacebookSession:
        self._pw = sync_playwright().start()
        ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(config.PROFILE),
            headless=self.headless,
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        # Cookies are validated in config.load_cookies(); Playwright wants a
        # TypedDict shape we build dynamically, so cast past the static check.
        ctx.add_cookies(cast("Any", config.load_cookies()))
        self._page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self._ctx = ctx
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._ctx is not None:
            self._ctx.close()
        if self._pw is not None:
            self._pw.stop()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Session not opened; use `with FacebookSession() as fb:`")
        return self._page

    def capture_to(self, writer: RawWriter) -> None:
        assert self._ctx is not None
        self._ctx.on("response", writer.handle)

    def goto(self, url: str) -> None:
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        except PWTimeout as e:
            raise RuntimeError(f"navigation to {url} timed out") from e
        landed = self.page.url
        if any(bit in landed for bit in BLOCKED_URL_BITS):
            raise CheckpointError(
                "Facebook redirected to login/checkpoint. Cookies are expired or an "
                "identity confirmation is needed. Re-export cookies; if checkpointed, "
                "open Facebook once in your normal browser to clear it."
            )

    def discover_groups(self) -> list[dict[str, str]]:
        """Return the user's groups as {name, url}, scraped from the groups tab."""
        self.goto("https://www.facebook.com/groups/joins/")
        # Let the list populate, then nudge lazy-loading so more than the first
        # screen of groups is present.
        for _ in range(6):
            self.page.mouse.wheel(0, 1400)
            time.sleep(random.uniform(1.0, 2.0))
        anchors = self.page.query_selector_all('a[href*="/groups/"]')
        seen: dict[str, str] = {}
        for a in anchors:
            href = a.get_attribute("href") or ""
            slug = _group_slug(href)
            if not slug:
                continue
            text = (a.inner_text() or "").strip()
            name = text.splitlines()[0].strip() if text else ""
            if name and len(name) > 1:
                seen.setdefault(f"https://www.facebook.com/groups/{slug}", name)
        return [{"name": n, "url": u} for u, n in seen.items()]

    def scroll_feed(
        self,
        url: str,
        writer: RawWriter,
        minutes: float,
        cursor: int | None,
        log: Callable[[str], None],
    ) -> None:
        """Scroll a feed until GraphQL fetching stalls (or the time cap),
        capturing responses via `writer`. Fast pace over already-seen history
        (older than `cursor`), human pace once into new territory.

        The end signal is "no new GraphQL response for a while", not any DOM
        measurement: Facebook's feed scrolls its own container and lazy-loads
        posts via GraphQL, so a stall in that traffic is the real bottom."""
        self.goto(url)
        # Park the cursor over the center feed column so wheel events land, and
        # let the first screen render before we start scrolling.
        self.page.mouse.move(640, 450)
        time.sleep(3.0)
        log(f"Loaded feed. Cursor so far: {_fmt_ts(cursor)}")
        deadline = time.monotonic() + minutes * 60
        stalled = 0
        last_posts = 0
        ticks = 0
        # Stop after this many scrolls with no *new posts* loading. Keyed on
        # post-bearing responses, not total GraphQL: Facebook keeps a trickle of
        # presence/typing/config traffic flowing forever, so a total-traffic
        # stall never fires and the crawl would spin re-fetching the same posts.
        patience = 15
        while time.monotonic() < deadline:
            fast = cursor is not None and writer.min_ts is not None and writer.min_ts > cursor
            try:
                # Programmatic scroll is focus- and layout-independent (works
                # even when the scrollable element isn't <body>); the small
                # wheel nudge adds human texture.
                self.page.evaluate("(y) => window.scrollBy(0, y)", random.randint(1200, 2400))
                self.page.mouse.wheel(0, random.randint(300, 700))
            except Exception:
                break
            ticks += 1
            _human_pause(fast=fast)
            if writer.post_responses > last_posts:
                last_posts = writer.post_responses
                stalled = 0
            elif writer.post_responses > 0:
                # Only count a stall once posts have started arriving, so a slow
                # initial render doesn't end the session before it begins.
                stalled += 1
            if ticks % 10 == 0:
                log(
                    f"  scrolled {ticks} | graphql {writer.responses} "
                    f"(posts {writer.post_responses}) | oldest {_fmt_ts(writer.min_ts)}"
                )
            if stalled >= patience:
                log("No new posts loading; reached the end of the reachable feed.")
                break


# Path segments under /groups/ that aren't actual groups.
_NON_GROUP_SEGMENTS = {
    "joins", "feed", "discover", "category", "categories", "search",
    "create", "your_groups_and_pages", "notifications", "invites",
}
_GROUP_SLUG_RE = re.compile(r"/groups/([^/?#]+)")


def _group_slug(href: str) -> str | None:
    m = _GROUP_SLUG_RE.search(href)
    if not m:
        return None
    slug = m.group(1)
    return None if slug in _NON_GROUP_SEGMENTS else slug


def _human_pause(fast: bool) -> None:
    lo, hi = (0.8, 1.6) if fast else (3.0, 7.0)
    time.sleep(random.uniform(lo, hi))
    if not fast and random.random() < 0.08:
        time.sleep(random.uniform(6.0, 14.0))


def _fmt_ts(ts: int | None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "unknown"
