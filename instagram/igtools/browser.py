"""Browser transport: a real Chromium with the borrowed cookies loads the
profile page and we read the JSON the page itself fetches.

Why this exists next to the raw HTTP lane in session.py: the raw lane sends
the right cookies and headers and still draws a 429 on the first call, which
means Instagram is scoring the request fingerprint, not just the session.
A Chromium page load has the fingerprint for free, and the endpoint churn
(web_profile_info today, a graphql doc_id tomorrow) stops mattering because
we scrape post records out of *every* JSON response rather than one URL.

INVARIANTS
- Read-only: navigate and scroll only. Never click into a post, like,
  follow, or type.
- Login/challenge redirects raise Checkpoint and start the same cooldown as
  the HTTP lane; the two transports share one budget file.
- Pauses are human-paced (seconds, randomized). No fast path.
"""

from __future__ import annotations

import json
import os
import random
import time
from typing import Any, cast

from playwright.sync_api import Page, Response, TimeoutError as PWTimeout, sync_playwright

from . import config, fetch
from . import session as sess

PROFILE_DIR = config.ROOT / ".profile"
JSON_HINTS = ("/api/v1/", "/graphql/query", "/graphql")
BLOCKED_URL_BITS = ("/accounts/login", "/challenge", "/checkpoint", "/accounts/suspended")
GRID_SELECTOR = 'a[href*="/p/"], a[href*="/reel/"]'
ACCOUNT_GAP = (8.0, 15.0)
SCROLL_GAP = (2.0, 4.0)
DEBUG_DIR = config.DATA / "debug"


class Checkpoint(sess.Throttled):
    """Instagram bounced the browser to login or a challenge."""


def _cookie_dicts(jar: config.Cookies) -> list[dict[str, Any]]:
    out = []
    for name, value in jar.values.items():
        exp = jar.expires.get(name, 0)
        out.append(
            {
                "name": name,
                "value": value,
                "domain": ".instagram.com",
                "path": "/",
                "expires": float(exp) if exp and exp > 0 else -1,
                "httpOnly": name in ("sessionid", "ig_did", "datr"),
                "secure": True,
                "sameSite": "Lax",
            }
        )
    return out


class BrowserSession:
    """`with BrowserSession() as b: summary, posts = b.posts("recordbarkc")`"""

    def __init__(self, headless: bool = True, force: bool = False) -> None:
        jar = config.load_cookies()
        if not jar.ok:
            raise RuntimeError("no usable instagram cookies; run `ig cookies --from-chrome` first")
        until = config.cooldown_until()
        if until and not force:
            raise sess.Throttled(f"cooldown active until {until.astimezone().strftime('%H:%M %Z')} (use --force to override)")
        self.jar = jar
        self.headless = headless
        self.accounts_done = 0
        self._pw: Any = None
        self._ctx: Any = None
        self._page: Page | None = None
        self._captured: list[dict] = []
        self._statuses: list[int] = []

    def __enter__(self) -> "BrowserSession":
        self._pw = sync_playwright().start()
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=self.headless,
            user_agent=config.user_agent(),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="America/Chicago",
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._ctx.add_cookies(cast("Any", _cookie_dicts(self.jar)))
        self._ctx.on("response", self._on_response)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, *_exc) -> None:
        if self._ctx is not None:
            self._ctx.close()
        if self._pw is not None:
            self._pw.stop()

    @property
    def page(self) -> Page:
        assert self._page is not None
        return self._page

    def _on_response(self, r: Response) -> None:
        url = r.url
        if not any(h in url for h in JSON_HINTS):
            return
        self._statuses.append(r.status)
        if r.status != 200:
            return
        try:
            body = r.body()
        except Exception:
            return
        if not body or body[:1] not in (b"{", b"["):
            return
        try:
            self._captured.append(json.loads(body))
        except json.JSONDecodeError:
            return

    def _harvest_embedded(self) -> None:
        """The profile page server-renders its data into <script type=application/json>
        blobs; XHR only carries later pages (and the unrelated home-feed prefetch)."""
        try:
            blobs = self.page.eval_on_selector_all(
                'script[type="application/json"]', "els => els.map(e => e.textContent)"
            )
        except Exception:
            return
        for raw in blobs or []:
            if not raw or ("taken_at" not in raw and "shortcode" not in raw and "biography" not in raw):
                continue
            try:
                self._captured.append(json.loads(raw))
            except json.JSONDecodeError:
                continue

    def _grid_records(self, username: str) -> list[dict]:
        """Fallback records straight from the grid DOM: shortcode from the
        href, Instagram's own alt text from the <img>. No date or caption, so
        these only fill in when the JSON never arrived for that post."""
        try:
            rows = self.page.eval_on_selector_all(
                GRID_SELECTOR, "els => els.map(e => [e.getAttribute('href'), (e.querySelector('img')||{}).alt||''])"
            )
        except Exception:
            return []
        out = []
        for href, alt in rows or []:
            parts = [x for x in (href or "").split("/") if x]
            # /<owner>/p/<code>/ or /p/<code>/ or /<owner>/reel/<code>/
            if len(parts) >= 3 and parts[-2] in ("p", "reel") and parts[0] != parts[-2]:
                owner, code = parts[0], parts[-1]
            elif len(parts) == 2 and parts[0] in ("p", "reel"):
                owner, code = username, parts[1]
            else:
                continue
            if owner.lower() != username.lower():
                continue
            out.append({
                "id": f"ig-{code}", "account": username, "code": code, "url": f"{sess.BASE}/p/{code}/",
                "taken_at": None, "taken_at_ts": 0, "owner": owner, "caption": "", "alt_text": alt,
                "is_video": parts[-2] == "reel", "pinned": False, "location": None, "images": [], "likes": None,
                "from_grid_only": True,
            })
        return out

    def _debug_dump(self, username: str, stage: str) -> None:
        if not os.environ.get("IG_DEBUG"):
            return
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / f"{username}-{stage}.json").write_text(
            json.dumps({"url": self.page.url, "title": self.page.title(), "payloads": self._captured}, ensure_ascii=False)
        )

    def _check_blocked(self) -> None:
        landed = self.page.url
        if any(b in landed for b in BLOCKED_URL_BITS):
            until = config.set_cooldown(sess.COOLDOWN_MINUTES, f"browser redirected to {landed}")
            raise Checkpoint(f"redirected to {landed}; cooldown until {until.isoformat()}")
        if self._statuses and self._statuses.count(429) >= 2:
            until = config.set_cooldown(sess.COOLDOWN_MINUTES, "browser saw 429s")
            raise Checkpoint(f"instagram returned 429 to the page itself; cooldown until {until.isoformat()}")

    def posts(self, username: str, since_days: int = 14, max_scrolls: int = 6) -> tuple[dict, list[dict]]:
        if self.accounts_done:
            time.sleep(random.uniform(*ACCOUNT_GAP))
        self.accounts_done += 1
        self._captured.clear()
        self._statuses.clear()
        try:
            self.page.goto(f"{sess.BASE}/{username}/", wait_until="domcontentloaded", timeout=60_000)
        except PWTimeout as e:
            raise RuntimeError(f"navigation to @{username} timed out") from e
        # The grid is what we came for; give the front end up to 12s to fetch
        # it. A missing account never shows a grid, so on timeout read the body.
        try:
            self.page.wait_for_selector(GRID_SELECTOR, timeout=12_000)
        except PWTimeout:
            pass
        time.sleep(random.uniform(2.0, 4.0))
        self._check_blocked()
        self._harvest_embedded()
        self._debug_dump(username, "load")
        if not self.page.query_selector(GRID_SELECTOR):
            body = (self.page.inner_text("body") or "")[:600].lower()
            if "isn't available" in body or "page not found" in body:
                raise sess.NotFound(username)

        cutoff = time.time() - since_days * 86400
        summary: dict = {"username": username}
        seen: dict[str, dict] = {}
        for i in range(max_scrolls + 1):
            summary.update(fetch.extract_profile(self._captured, username))
            # extract_posts drops the home-feed prefetch and stories tray, trusts
            # the grid's own timeline query (collab posts carry the artist as
            # `user`, the venue only as a coauthor), and owner-checks the rest.
            for p in fetch.extract_posts(self._captured, username):
                seen.setdefault(p["code"], p)
            if i:
                self._debug_dump(username, f"scroll{i}")
            self._captured.clear()
            for p in self._grid_records(username):
                seen.setdefault(p["code"], p)
            oldest = min((p["taken_at_ts"] for p in seen.values() if not p.get("pinned") and p["taken_at_ts"]), default=None)
            if oldest is not None and oldest < cutoff:
                break
            if i == max_scrolls:
                break
            self.page.mouse.move(640, 500)
            self.page.mouse.wheel(0, random.randint(1600, 2400))
            time.sleep(random.uniform(*SCROLL_GAP))
            self._check_blocked()

        if not seen and summary.get("is_private"):
            return summary, []
        # Grid-only records carry no date, so they cannot honor the window.
        # They are a fallback for when the JSON never arrived, not a supplement.
        dated = [p for p in seen.values() if not p.get("from_grid_only")]
        pool = dated if dated else list(seen.values())
        kept = [p for p in pool if p["taken_at_ts"] >= cutoff or p.get("pinned") or p.get("from_grid_only")]
        kept.sort(key=lambda p: p["taken_at_ts"], reverse=True)
        for p in kept:
            p.pop("taken_at_ts", None)
        return summary, kept
