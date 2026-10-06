"""The one shape every source is normalized into before it touches the calendar.

INVARIANTS:
- `key` is stable across runs for the same meeting (legistar-<EventId>, edc-<UID>).
  It is the calendar dedup key and the prep-state key. Never derive it from a title
  or a time: both change when a meeting is rescheduled.
- `start` and `end` are timezone-aware America/Chicago datetimes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")


@dataclass
class Meeting:
    key: str
    source: str            # "legistar" | "edc" | "hold"
    body: str              # official body name
    short: str             # label for titles and file names
    tier: str              # "core" | "1" | "2"
    start: datetime
    end: datetime
    location: str = ""
    url: str = ""          # human meeting page
    agenda_url: str = ""   # agenda PDF or page, "" when not yet published
    agenda_fingerprint: str = ""  # changes when the agenda is republished
    join_link: str = ""    # Zoom/Teams link when one is posted
    cancelled: bool = False
    source_id: str = ""    # EventId or iCal UID
    extra: dict = field(default_factory=dict)

    def content_hash(self) -> str:
        d = asdict(self)
        d["start"], d["end"] = self.start.isoformat(), self.end.isoformat()
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]

    def title(self) -> str:
        prefix = "CANCELLED: " if self.cancelled else ""
        suffix = " (expected)" if self.source == "hold" else ""
        return f"{prefix}KC {self.short}{suffix}"
