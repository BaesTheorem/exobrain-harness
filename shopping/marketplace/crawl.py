"""Search jobs and the pin locator for the Marketplace front end.

Facebook's search cards carry no coordinates, so distance comes from two sources:

1. Rings. The GraphQL search honors `filter_radius_km` (measured 2026-10-24: a 2 km query
   returned pins at 1.1 to 2.3 km). A job queries rings of 1, 3, 5, 10, 20 and 40 miles up to
   the chosen maximum. A listing first seen in ring r is within r. When the ring inside it
   returned all of its results (no next page), the listing is also farther than that ring.
2. Pins. The item page has the approximate pin Facebook shows buyers. The locator fetches item
   pages in the background, two at a time, nearest band first, and records the exact distance.
   Each listing is fetched once and cached for good.

Every request is a read with Alex's session, so the pace is slow on purpose: a checkpoint on
the account costs more than a slow search.
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from shoptools import fbm
from shoptools.common import LaneError, home_latlon

from .store import KM_PER_MI, Store

RINGS_MI = (1, 3, 5, 10, 20, 40)
PAGES_PER_RING = 4          # ~14 to 24 listings a page
TOKEN_TTL = 20 * 60
REUSE_SECONDS = 15 * 60
LOCATOR_THREADS = 2
LOCATOR_PAUSE = 1.0         # seconds between item pages, per thread


def rings_for(max_mi: float) -> list[float]:
    return [r for r in RINGS_MI if r < max_mi] + [max_mi]


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
    def __init__(self, store: Store):
        self.store = store
        self.home = home_latlon()
        self.jobs: dict[str, Job] = {}
        self._seq = itertools.count(1)
        self._tok: tuple[float, Any, dict, str] | None = None
        self._tok_lock = threading.Lock()
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._queued: set[str] = set()
        self.locator_error: str | None = None
        for _ in range(LOCATOR_THREADS):
            threading.Thread(target=self._locate_loop, daemon=True).start()

    # ------------------------------------------------------------ session

    def _session(self) -> tuple[Any, dict, str]:
        with self._tok_lock:
            if self._tok and time.time() - self._tok[0] < TOKEN_TTL:
                return self._tok[1], self._tok[2], self._tok[3]
            s, tok, uid = fbm.open_search_session()
            self._tok = (time.time(), s, tok, uid)
            return s, tok, uid

    # ------------------------------------------------------------ search

    def start(self, params: dict) -> Job:
        # A reload or a saved search repeats a query; reuse a fresh identical job, no new crawl.
        for job in reversed(list(self.jobs.values())):
            if job.params == params and job.status != "error" and time.time() - job.started < REUSE_SECONDS:
                return job
        job = Job(id=uuid.uuid4().hex[:10], seq=next(self._seq), params=params,
                  rings=rings_for(float(params.get("max_mi") or 20)))
        self.jobs[job.id] = job
        # Keep the last 20 jobs; the listings themselves stay in the store.
        for old in list(self.jobs)[:-20]:
            self.jobs.pop(old, None)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _ring(self, job: Job, km: int) -> tuple[list[dict], bool]:
        """One ring of `km` (Facebook takes whole kilometers). Returns (rows, complete)."""
        p = job.params
        s, tok, uid = self._session()
        params = fbm.search_params(p["q"], *self.home, km, p.get("min"), p.get("max"),
                             p.get("days"), p.get("condition") or None, shipping=not p.get("local_only", True))
        referer = fbm.SEARCH_URL.format(city="kansascity") + "?query=" + p["q"]
        rows: list[dict] = []
        cursor = None
        for _ in range(PAGES_PER_RING):
            page, info = fbm.search_page(s, tok, uid, params, cursor, referer)
            rows.extend(page)
            cursor = info.get("end_cursor")
            if not info.get("has_next_page") or not cursor:
                return rows, True
        return rows, False

    def _run(self, job: Job) -> None:
        seen: set[str] = set()
        inner, inner_complete = 0.0, True
        try:
            for ring_mi in job.rings:
                # The band records the radius Facebook actually got: 1 mi goes out as 2 km (1.24 mi).
                km = max(1, round(ring_mi * KM_PER_MI))
                radius = round(km / KM_PER_MI, 2)
                try:
                    rows, complete = self._ring(job, km)
                except LaneError:
                    # Tokens can go stale mid-session; one fresh page, then one retry.
                    self._tok = None
                    rows, complete = self._ring(job, km)
                band = (inner if inner_complete else 0.0, radius)
                for rank, r in enumerate(rows):
                    if not r.get("id"):
                        continue
                    self.store.upsert_card(r, band if r["id"] not in seen else None)
                    if r["id"] not in seen:
                        seen.add(r["id"])
                        job.ids.append(r["id"])
                        if self.store.needs_item(r["id"]):
                            self.enqueue(r["id"], job.seq, radius, rank)
                inner, inner_complete = radius, complete
                job.rings_done += 1
            job.status = "done"
        except LaneError as e:
            job.warnings.append(str(e))
            job.status = "error" if not job.ids else "done"
        except Exception as e:  # noqa: BLE001 - a crashed thread must still report to the UI
            job.warnings.append(f"search failed: {type(e).__name__}: {e}")
            job.status = "error"

    # ------------------------------------------------------------ locator

    def enqueue(self, listing_id: str, job_seq: int, band_hi: float, rank: int) -> None:
        if listing_id in self._queued:
            return
        self._queued.add(listing_id)
        # Newest job first, then nearest ring, then Facebook's own rank.
        self._q.put(((-job_seq, band_hi, rank), listing_id))

    def locate_now(self, listing_id: str) -> None:
        """Synchronous fetch for the detail view."""
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

    def _locate_loop(self) -> None:
        while True:
            _, listing_id = self._q.get()
            if not self.store.needs_item(listing_id):
                continue
            try:
                self._fetch(listing_id)
                self.locator_error = None
            except LaneError as e:
                self.locator_error = str(e)
                if "checkpoint" in str(e) or "expired" in str(e):
                    # The session is gone; stop the locator so it does not hammer a login wall.
                    time.sleep(600)
            except Exception as e:  # noqa: BLE001 - keep the thread alive, report the cause
                self.locator_error = f"{type(e).__name__}: {e}"
            time.sleep(LOCATOR_PAUSE)

    def pending(self) -> int:
        return self._q.qsize()
