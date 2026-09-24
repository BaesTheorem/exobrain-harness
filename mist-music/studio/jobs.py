"""A single-worker background queue the UI polls.

Everything slow (generation, analysis, stems, cover art, lyric writing) runs
here so a request never blocks a Flask thread. One worker on purpose: the
Space serializes GPU calls anyway, and demucs on an 8 GB machine should never
run twice at once.
"""
from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections import deque
from typing import Any, Callable

MAX_KEPT = 200


class Job:
    def __init__(self, kind: str, payload: dict, fn: Callable[["Job"], Any], label: str = ""):
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.label = label
        self.payload = payload
        self.fn = fn
        self.status = "queued"           # queued | running | done | error | cancelled
        self.progress: dict = {}
        self.result: Any = None
        self.error: str | None = None
        self.error_kind: str | None = None
        self.retry_in: int | None = None
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.cancel_requested = False
        self.on_cancel: Callable[[], None] | None = None

    def report(self, progress: dict) -> None:
        self.progress = dict(progress)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "label": self.label, "status": self.status,
            "progress": self.progress, "result": self.result, "error": self.error,
            "error_kind": self.error_kind, "retry_in": self.retry_in,
            "created": self.created, "started": self.started, "finished": self.finished,
            "payload": {k: v for k, v in self.payload.items() if k != "secret"},
        }


class JobQueue:
    def __init__(self):
        self._pending: deque[Job] = deque()
        self._jobs: dict[str, Job] = {}
        self._order: deque[str] = deque()
        self._cv = threading.Condition()
        self.current: Job | None = None
        self._thread = threading.Thread(target=self._run, name="studio-jobs", daemon=True)
        self._thread.start()

    def submit(self, kind: str, payload: dict, fn: Callable[[Job], Any], label: str = "") -> Job:
        job = Job(kind, payload, fn, label)
        with self._cv:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > MAX_KEPT:
                old = self._order.popleft()
                if self._jobs.get(old) and self._jobs[old].status in ("done", "error", "cancelled"):
                    self._jobs.pop(old, None)
                else:
                    self._order.appendleft(old)
                    break
            self._pending.append(job)
            self._cv.notify()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self, limit: int = 60) -> list[dict]:
        with self._cv:
            ids = list(self._order)[-limit:]
        return [self._jobs[i].to_dict() for i in reversed(ids) if i in self._jobs]

    def cancel(self, job_id: str) -> bool:
        with self._cv:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status == "queued":
                job.status = "cancelled"
                job.finished = time.time()
                with_removed = [j for j in self._pending if j.id != job_id]
                self._pending = deque(with_removed)
                return True
            if job.status == "running":
                job.cancel_requested = True
                if job.on_cancel:
                    try:
                        job.on_cancel()
                    except Exception:  # noqa: BLE001 - best effort
                        pass
                return True
        return False

    def clear_finished(self) -> int:
        with self._cv:
            gone = [i for i in self._order if self._jobs.get(i) and
                    self._jobs[i].status in ("done", "error", "cancelled")]
            for i in gone:
                self._jobs.pop(i, None)
            self._order = deque(i for i in self._order if i not in gone)
        return len(gone)

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._pending:
                    self._cv.wait()
                job = self._pending.popleft()
                if job.status != "queued":
                    continue
                job.status = "running"
                job.started = time.time()
                self.current = job
            try:
                job.result = job.fn(job)
                job.status = "cancelled" if job.cancel_requested else "done"
            except Exception as e:  # noqa: BLE001 - the job record carries the failure
                job.error = str(e) or type(e).__name__
                job.error_kind = type(e).__name__
                job.retry_in = getattr(e, "retry_in", None)
                job.status = "cancelled" if job.cancel_requested else "error"
                job.progress = {**job.progress, "trace": traceback.format_exc()[-1500:]}
            finally:
                job.finished = time.time()
                with self._cv:
                    self.current = None
