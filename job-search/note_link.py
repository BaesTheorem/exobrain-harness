"""Write a lane's decline back onto the listing note for the same req.

A lane script can decline a req that already has a candidate note from another
source. Before this module, the decline went to stdout and the note never heard
about it: RGA's Enterprise Access Management Analyst came in from LinkedIn as
"Remote" on 2026-09-24, workday.py polled the same req as a Creve Coeur, MO
seat, and the note stayed a candidate until 2026-10-11.

A note matches a declined posting when both are true:
  - the note text names the board (the Workday host and tenant, or an ATS
    board token), and
  - the note's `role` equals the posting title after normalization, or the
    note text carries the req id.

On a match the note gets `lane_decline: "<date> <lane>: <why>"` in its
frontmatter and a dated `## Lane decline` section. `fit-gate.py` reports that
as CONFLICT. The note is never declined here, because a lane reads coarse
location buckets and can be wrong; a person resolves the conflict.

INVARIANTS
- Only active candidates are touched (status candidate, not applied, not declined).
- Idempotent: a req id already recorded on the note is not written again.
"""

from __future__ import annotations

import datetime as dt
import os
import re

LISTINGS = os.path.expanduser("~/Exobrain/Projects/Get new job/Job Listings")


def norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _fm(txt: str) -> tuple[str, int]:
    m = re.match(r"---\n(.*?)\n---\n", txt, re.S)
    return (m.group(1), m.end()) if m else ("", 0)


def _field(fm: str, key: str) -> str:
    m = re.search(r"^%s:[ \t]*(.*)$" % key, fm, re.M)
    return m.group(1).strip().strip('"') if m else ""


def active_notes(root: str = LISTINGS) -> dict[str, str]:
    """Path -> text for every active candidate listing note."""
    out = {}
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                txt = open(p, encoding="utf-8").read()
            except OSError:
                continue
            fm, _ = _fm(txt)
            if (_field(fm, "type") == "job-listing" and _field(fm, "status") == "candidate"
                    and _field(fm, "applied") != "true" and _field(fm, "declined") != "true"):
                out[p] = txt
    return out


def match(notes: dict[str, str], board_marker: str, title: str, req: str) -> list[str]:
    hits = []
    for p, txt in notes.items():
        if board_marker.lower() not in txt.lower():
            continue
        role = _field(_fm(txt)[0], "role")
        if norm(role) == norm(title) or (req and req in txt):
            hits.append(p)
    return hits


def record(path: str, lane: str, req: str, title: str, why: str, url: str,
           today: dt.date | None = None) -> bool:
    """Stamp the decline on the note. False when this req is already recorded."""
    txt = open(path, encoding="utf-8").read()
    if req and f"req {req}" in txt:
        return False
    day = (today or dt.date.today()).isoformat()
    fm, end = _fm(txt)
    value = f'"{day} {lane}: {why}"'.replace('\\', '')
    line = f"lane_decline: {value}"
    if re.search(r"^lane_decline:", fm, re.M):
        fm = re.sub(r"^lane_decline:.*$", line, fm, count=1, flags=re.M)
    else:
        fm += "\n" + line
    section = (f"## Lane decline {day}\n"
               f"`{lane}` declined req {req} ({title}): {why}. {url}\n"
               "Resolve: confirm the location, set `location_evidence`, delete `lane_decline`.\n\n")
    body = txt[end:]
    anchor = body.find("## Fit scorecard")
    body = body[:anchor] + section + body[anchor:] if anchor >= 0 else body + "\n" + section
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"---\n{fm}\n---\n" + body)
    return True
