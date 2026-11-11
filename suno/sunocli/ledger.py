"""Receipts for paid requests, so a timeout or a second run never charges twice.

A generation costs credits and the answer can be lost on the way back. Before the request is
sent, a receipt goes to disk in state ``submitting``. After the answer it becomes ``submitted``
(with the clip ids), ``rejected`` (Suno said no, nothing was charged) or ``unknown`` (no answer
came back). The same request id with the same content returns the saved clips and sends
nothing.

INVARIANTS:
- A receipt is written before the paid POST and is never deleted by this tool.
- A receipt in state ``submitting`` or ``unknown`` blocks an identical request for
  ``DUPLICATE_WINDOW`` seconds. The song possibly exists; the library is the place to look.
- Receipts hold the title, the model and a hash. They never hold lyrics, tokens or the login.
- ``spend.jsonl`` gets one line for each credit spend and each download unlock, with the
  balance Suno reported before and after. Suno's numbers are the record, not this tool's sums.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from sunocli.model import fingerprint_source

Json = dict[str, Any]

STATE = Path(__file__).resolve().parent.parent / "state"
DUPLICATE_WINDOW = 30 * 60
OPEN_STATES = ("submitting", "unknown")


class Blocked(RuntimeError):
    """The request must not be sent as it is. ``receipt`` says why."""

    def __init__(self, message: str, receipt: Json | None = None) -> None:
        super().__init__(message)
        self.receipt = receipt


def fingerprint(payload: Json) -> str:
    canon = json.dumps(fingerprint_source(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


class Ledger:
    def __init__(self, root: Path = STATE, clock: Callable[[], float] = time.time) -> None:
        self.root = root
        self.clock = clock

    @property
    def receipts_dir(self) -> Path:
        return self.root / "receipts"

    def _path(self, request_id: str) -> Path:
        return self.receipts_dir / f"{request_id}.json"

    def _write(self, receipt: Json) -> Json:
        self.receipts_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(receipt["request_id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(receipt, indent=1))
        tmp.replace(path)
        return receipt

    def find(self, request_id: str) -> Json | None:
        path = self._path(request_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except ValueError:
            return None

    def all(self) -> list[Json]:
        out = []
        if self.receipts_dir.exists():
            for path in self.receipts_dir.glob("*.json"):
                try:
                    out.append(json.loads(path.read_text()))
                except ValueError:
                    continue
        return sorted(out, key=lambda r: r.get("opened_at", 0), reverse=True)

    def check(self, payload: Json, force: bool = False) -> Json | None:
        """A saved receipt to reuse, or None when the request may be sent. Raises Blocked."""
        request_id, fp = payload["transaction_uuid"], fingerprint(payload)
        known = self.find(request_id)
        if known:
            if known.get("fingerprint") != fp:
                raise Blocked("this request id was used for a different request", known)
            if known.get("state") == "submitted":
                return known
            if known.get("state") in OPEN_STATES:
                raise Blocked("this request was sent and no answer was recorded. Read `suno list` "
                              "before a second attempt.", known)
        if force:
            return None
        now = self.clock()
        for other in self.all():
            if other.get("fingerprint") != fp or other.get("request_id") == request_id:
                continue
            if now - other.get("opened_at", 0) > DUPLICATE_WINDOW:
                continue
            if other.get("state") in OPEN_STATES or other.get("state") == "submitted":
                raise Blocked("an identical request went out less than 30 minutes ago. "
                              "Pass --force to send it again.", other)
        return None

    def open(self, payload: Json, summary: Json) -> Json:
        return self._write({
            "request_id": payload["transaction_uuid"], "fingerprint": fingerprint(payload),
            "state": "submitting", "opened_at": int(self.clock()), "ids": [], **summary,
        })

    def close(self, receipt: Json, state: str, **fields: Any) -> Json:
        receipt.update(state=state, closed_at=int(self.clock()), **fields)
        return self._write(receipt)

    def log_spend(self, kind: str, **fields: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "spend.jsonl").open("a") as fh:
            fh.write(json.dumps({"at": int(self.clock()), "kind": kind, **fields}) + "\n")
