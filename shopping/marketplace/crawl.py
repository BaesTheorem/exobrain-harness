"""Index sweeps, text searches, and the pin and photo workers for the Marketplace front end.

The index holds every listing near home. An empty query returns nothing without a category, so
a sweep walks each category page (fbm.CATEGORIES) newest first (`CREATION_TIME_DESCEND`, strictly
ordered, measured 2026-10-24) in rings of 1, 3, 10 and 25 miles:

- The first sweep of a (category, ring) goes back INITIAL_DAYS. Later sweeps stop at the newest
  listing the last sweep saw, so a refresh costs about one page per ring per category.
- A ring that reached its cutoff returned every listing in it for that time window. So a
  listing first found in ring r, and created inside the window of the ring inside r, is farther
  than that inner ring: the band is an exact interval. The GraphQL radius is honored
  (2026-10-24: a 2 km query returned pins at 1.1 to 2.3 km).

A text search adds what the categories miss (older listings, Facebook's loose matches) with the
same ring logic, in Facebook's relevance order.

Pins: the item page has the pin Facebook shows buyers. The pin worker fetches only what the
page asks for (the cards on screen) and alert candidates, under PIN_CAP_PER_HOUR. Photos: the
hash worker fingerprints each card photo from the image CDN, which does not use the account.

Every Facebook request is a read with Alex's session, so the pace is slow on purpose.
"""

from __future__ import annotations

import itertools
import json
import os
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from shoptools import fbm
from shoptools.common import LaneError, home_latlon

from .photohash import photo_hash
from .store import KM_PER_MI, Store

RINGS_MI = (1, 3, 5, 10, 20, 40)        # text search rings
SWEEP_RINGS_MI = (1, 3, 10, 25)         # index rings; 25 mi is the index radius
INDEX_MI = SWEEP_RINGS_MI[-1]
SWEEP_CATEGORIES = [c for c in fbm.CATEGORIES if c not in ("propertyforsale", "propertyrentals")]
INITIAL_DAYS = 3
OVERLAP = 3600                          # re-read one hour behind the last mark
SWEEP_PAGES_FIRST = 40
SWEEP_PAGES_LATER = 12
PAGE_PAUSE = 1.2
PAGES_PER_RING = 4
TOKEN_TTL = 20 * 60
REUSE_SECONDS = 15 * 60
SWEEP_EVERY = 2 * 3600
PIN_CAP_PER_HOUR = 240
LOCATOR_THREADS = 2
LOCATOR_PAUSE = 1.0


def rings_for(max_mi: float) -> list[float]:
    return [r for r in RINGS_MI if r < max_mi] + [max_mi]


def ring_km(mi: float) -> tuple[int, float]:
    """Facebook takes whole kilometers: (km sent, the radius that really is in miles)."""
    km = max(1, round(mi * KM_PER_MI))
    return km, round(km / KM_PER_MI, 2)


@dataclass
class Job:
    id: str
    seq: int
    params: dict
    status: str = "searching"
    rings: list[float] = field(default_factory=list)
    rings_done: int = 0
    ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    started: float = field(default_factory=time.time)


class Crawler:
    def __init__(self, store: Store, background: bool = True):
        self.store = store
        self.home = home_latlon()
        self.jobs: dict[str, Job] = {}
        self._seq = itertools.count(1)
        self._tok: tuple[float, Any, dict, str] | None = None
        self._tok_lock = threading.Lock()
        self._pins: queue.PriorityQueue = queue.PriorityQueue()
        self._pin_queued: set[str] = set()
        self._pin_times: deque[float] = deque()
        self._hashes: queue.Queue = queue.Queue()
        self._hash_queued: set[str] = set()
        self.locator_error: str | None = None
        self.owner = f"{os.getpid()}-{uuid.uuid4().hex[:6]}"
        if background:
            for _ in range(LOCATOR_THREADS):
                threading.Thread(target=self._pin_loop, daemon=True).start()
            threading.Thread(target=self._hash_loop, daemon=True).start()

    # ------------------------------------------------------------ session

    def _session(self) -> tuple[Any, dict, str]:
        with self._tok_lock:
            if self._tok and time.time() - self._tok[0] < TOKEN_TTL:
                return self._tok[1], self._tok[2], self._tok[3]
            s, tok, uid = fbm.open_search_session()
            self._tok = (time.time(), s, tok, uid)
            return s, tok, uid

    def _page(self, params: dict, cursor: str | None, referer: str) -> tuple[list[dict], dict]:
        try:
            s, tok, uid = self._session()
            return fbm.search_page(s, tok, uid, params, cursor, referer)
        except LaneError:
            # Tokens go stale; one fresh page load, then one retry.
            self._tok = None
            s, tok, uid = self._session()
            return fbm.search_page(s, tok, uid, params, cursor, referer)

    # ------------------------------------------------------------ text search

    def start(self, params: dict) -> Job:
        # A reload or a saved search repeats a query; reuse a fresh identical job, no new crawl.
        for job in reversed(list(self.jobs.values())):
            if job.params == params and job.status != "error" and time.time() - job.started < REUSE_SECONDS:
                return job
        job = self.new_job(params)
        self.jobs[job.id] = job
        for old in list(self.jobs)[:-20]:
            self.jobs.pop(old, None)
        threading.Thread(target=self.run_job, args=(job,), daemon=True).start()
        return job

    def new_job(self, params: dict, rings: list[float] | None = None) -> Job:
        return Job(id=uuid.uuid4().hex[:10], seq=next(self._seq), params=params,
                   rings=rings or rings_for(float(params.get("max_mi") or 20)))

    def run_job(self, job: Job, sort: str | None = None, pages: int = PAGES_PER_RING) -> None:
        p = job.params
        seen: set[str] = set()
        inner, inner_complete = 0.0, True
        referer = fbm.SEARCH_URL.format(city="kansascity") + "?query=" + p["q"]
        try:
            for ring_mi in job.rings:
                km, radius = ring_km(ring_mi)
                params = fbm.search_params(p["q"], *self.home, km, p.get("min"), p.get("max"), p.get("days"),
                                           p.get("condition") or None, shipping=not p.get("local_only", True),
                                           sort=sort)
                rows: list[dict] = []
                cursor, complete = None, False
                for _ in range(pages):
                    page, info = self._page(params, cursor, referer)
                    rows.extend(page)
                    cursor = info.get("end_cursor")
                    if not info.get("has_next_page") or not cursor:
                        complete = True
                        break
                    time.sleep(PAGE_PAUSE / 2)
                band = (inner if inner_complete else 0.0, radius)
                for r in rows:
                    if not r.get("id"):
                        continue
                    self.store.upsert_card(r, band if r["id"] not in seen else None)
                    if r["id"] not in seen:
                        seen.add(r["id"])
                        job.ids.append(r["id"])
                        self.queue_hash(r["id"])
                inner, inner_complete = radius, complete
                job.rings_done += 1
            job.status = "done"
            self.pin_local_shippers()
        except LaneError as e:
            job.warnings.append(str(e))
            job.status = "error" if not job.ids else "done"
        except Exception as e:  # noqa: BLE001 - a crashed thread must still report to the UI
            job.warnings.append(f"search failed: {type(e).__name__}: {e}")
            job.status = "error"

    # ------------------------------------------------------------ index sweep

    def sweep_due(self) -> bool:
        last = self.store.get_meta("sweep_finished")
        return not last or time.time() - float(last) > SWEEP_EVERY

    def sweep_status(self) -> dict:
        raw = self.store.get_meta("sweep_status")
        st: dict[str, Any] = json.loads(raw) if raw else {"running": False}
        st["finished"] = float(self.store.get_meta("sweep_finished") or 0)
        return st

    def start_sweep(self) -> bool:
        if not self.store.try_lock("sweep", self.owner, ttl=1800):
            return False
        threading.Thread(target=self.sweep, kwargs={"locked": True}, daemon=True).start()
        return True

    def sweep(self, locked: bool = False, categories: list[str] | None = None) -> list[str] | None:
        """Walk every category newest first, ring by ring. Returns the ids new to the index,
        or None when another process (the server or the watcher) holds the sweep."""
        if not locked and not self.store.try_lock("sweep", self.owner, ttl=1800):
            return None
        cats = categories or SWEEP_CATEGORIES
        new_ids: list[str] = []
        st: dict[str, Any] = {"running": True, "started": time.time(), "done": 0, "total": len(cats),
                              "pages": 0, "new": 0, "category": None, "error": None}
        try:
            for cat in cats:
                st["category"] = cat
                self.store.set_meta("sweep_status", json.dumps(st))
                self._sweep_category(cat, st, new_ids)
                st["done"] += 1
                self.store.try_lock("sweep", self.owner, ttl=1800)   # refresh the lock
            self.store.set_meta("sweep_finished", str(time.time()))
            self.pin_local_shippers()
        except LaneError as e:
            st["error"] = str(e)
        finally:
            st["running"] = False
            self.store.set_meta("sweep_status", json.dumps(st))
            self.store.set_meta("sweep", None)
        return new_ids

    def _sweep_category(self, cat: str, st: dict, new_ids: list[str]) -> None:
        referer = f"https://www.facebook.com/marketplace/kansascity/{cat}/"
        seen_inner: set[str] = set()
        inner_radius, inner_floor = 0.0, None     # radius and oldest creation time it fully covers
        for ring_mi in SWEEP_RINGS_MI:
            km, radius = ring_km(ring_mi)
            mark = self.store.sweep_mark(cat, ring_mi)
            cutoff = (mark - OVERLAP) if mark else int(time.time() - INITIAL_DAYS * 86400)
            params = fbm.browse_params(cat, *self.home, km)
            cursor, newest, oldest, reached = None, 0, None, False
            ring_ids: list[str] = []
            for _ in range(SWEEP_PAGES_LATER if mark else SWEEP_PAGES_FIRST):
                rows, info = self._page(params, cursor, referer)
                st["pages"] += 1
                self.store.set_meta("sweep_status", json.dumps(st))
                for r in rows:
                    created = r.get("created") or 0
                    newest = max(newest, created)
                    oldest = created if oldest is None else min(oldest, created)
                    lo = inner_radius if (inner_floor is not None and created >= inner_floor
                                          and r["id"] not in seen_inner) else 0.0
                    if not self.store.has(r["id"]):
                        new_ids.append(r["id"])
                        st["new"] += 1
                    self.store.upsert_card(r, (lo, radius), browse_cat=cat)
                    self.queue_hash(r["id"])
                    ring_ids.append(r["id"])
                cursor = info.get("end_cursor")
                if (oldest is not None and oldest < cutoff) or not info.get("has_next_page") or not cursor:
                    reached = True
                    break
                time.sleep(PAGE_PAUSE)
            if newest:
                self.store.set_sweep_mark(cat, ring_mi, max(newest, mark or 0))
            seen_inner.update(ring_ids)
            # This ring is complete back to its cutoff, or back to the oldest row it got.
            inner_radius = radius
            inner_floor = cutoff if reached else (oldest or int(time.time()))
            time.sleep(PAGE_PAUSE)

    # ------------------------------------------------------------ pins

    def request_pins(self, ids: list[str], urgent: bool = True) -> int:
        """Queue item-page fetches; the page sends the cards on screen, in order."""
        n = 0
        stamp = time.time()
        for rank, i in enumerate(ids):
            if i in self._pin_queued or not self.store.needs_item(i):
                continue
            self._pin_queued.add(i)
            self._pins.put(((0 if urgent else 1, -stamp, rank), i))
            n += 1
        return n

    def pin_local_shippers(self) -> int:
        """A shippable listing has no ring band, so only its pin can place it. Queue pins, at low
        priority, for those from the states local pickup listings come from (not Florida)."""
        return self.request_pins(self.store.unpinned_shippers(self.store.local_states()), urgent=False)

    def locate_now(self, listing_id: str) -> None:
        """Synchronous fetch for the detail view and the watcher. Not counted against the cap."""
        self._fetch(listing_id)

    def _fetch(self, listing_id: str) -> None:
        try:
            d = fbm.item(listing_id)
            d["id"] = listing_id
            self.store.save_item(d, self.home)
        except LaneError as e:
            msg = str(e)
            gone = "no listing data" in msg
            self.store.mark_error(listing_id, msg, gone=gone)
            if not gone:
                raise

    def _pin_loop(self) -> None:
        while True:
            _, listing_id = self._pins.get()
            self._pin_queued.discard(listing_id)
            if not self.store.needs_item(listing_id):
                continue
            now = time.time()
            while self._pin_times and now - self._pin_times[0] > 3600:
                self._pin_times.popleft()
            if len(self._pin_times) >= PIN_CAP_PER_HOUR:
                self.locator_error = f"pin cap reached ({PIN_CAP_PER_HOUR} item pages an hour); resumes shortly"
                time.sleep(60)
                self.request_pins([listing_id], urgent=False)
                continue
            self._pin_times.append(now)
            try:
                self._fetch(listing_id)
                self.locator_error = None
            except LaneError as e:
                self.locator_error = str(e)
                if "checkpoint" in str(e) or "expired" in str(e):
                    time.sleep(600)   # the session is gone; do not hammer a login wall
            except Exception as e:  # noqa: BLE001 - keep the thread alive, report the cause
                self.locator_error = f"{type(e).__name__}: {e}"
            time.sleep(LOCATOR_PAUSE)

    def pending(self) -> int:
        return self._pins.qsize()

    # ------------------------------------------------------------ photo hashes

    def queue_hash(self, listing_id: str) -> None:
        if listing_id not in self._hash_queued and self.store.needs_hash(listing_id):
            self._hash_queued.add(listing_id)
            self._hashes.put(listing_id)

    def hash_now(self, listing_id: str) -> None:
        photo = self.store.photo(listing_id)
        if photo:
            try:
                self.store.set_phash(listing_id, photo_hash(photo))
            except (OSError, ValueError):
                pass   # an expired or missing photo; the next sighting brings a fresh URL

    def drain_hashes(self) -> int:
        """Hash everything queued, in this thread (the watcher has no background threads)."""
        n = 0
        while not self._hashes.empty():
            listing_id = self._hashes.get()
            self._hash_queued.discard(listing_id)
            if self.store.needs_hash(listing_id):
                self.hash_now(listing_id)
                n += 1
        return n

    def _hash_loop(self) -> None:
        while True:
            listing_id = self._hashes.get()
            self._hash_queued.discard(listing_id)
            if self.store.needs_hash(listing_id):
                self.hash_now(listing_id)
                time.sleep(0.15)
