"""Projecting the scraped reports into the Obsidian vault.

INVARIANTS:
- Notes are a PROJECTION of data/reports.json, which is the source of truth. A rescan
  rewrites the generated body. Anything Alex writes by hand goes below the
  `## Notes` marker and is preserved verbatim across rewrites -- that half of the file
  is his, and nothing here may clobber it.
- A note quotes only a short excerpt and always links the thread. This is an index over
  other people's writing, not a mirror of it.
- Coordinates carry their confidence into the frontmatter. A `region`-level guess must
  never render as though someone stood at that pin.
"""

from __future__ import annotations

import re
from pathlib import Path

from .geo import distance_is_meaningful, miles_from_home, proximity
from .scan import Report

VAULT = Path.home() / "Exobrain"
URBEX_DIR = VAULT / "Areas" / "Adventure & Creativity" / "Urbex"
SITES_DIR = URBEX_DIR / "Sites"
BASE_FILE = URBEX_DIR / "KC Urbex Sites.base"

HAND_MARKER = "## Notes"
CONFIDENCE_ICON = {
    "exact": "🎯", "block": "📍", "neighborhood": "🗺️", "region": "🌆", "unknown": "❓",
}


def safe_filename(title: str) -> str:
    """An Obsidian-safe note name. Colons and slashes break links and paths."""
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', "", title).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return (name or "Untitled")[:80]


def note_path(report: Report) -> Path:
    # The topic id keeps two identically-titled reports from colliding.
    return SITES_DIR / f"{safe_filename(report.title)} ({report.topic_id}).md"


def _yaml_scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


def render_note(report: Report, existing: str = "") -> str:
    """The full note body. `existing` supplies Alex's hand-written tail, if any."""
    prox = proximity(report.confidence, report.miles_from_home)
    # Only claim "within 3 miles" when the pin is precise enough for that to be a fact.
    within = prox == "near" if prox != "unplaceable" else None

    fm = {
        "type": "urbex_site",
        "source": "kcurbex",
        "topic_id": report.topic_id,
        "title": report.title,
        "posted": report.posted,
        "reported_by": report.author,
        "url": report.url,
        "place": report.place,
        "lat": report.lat,
        "lon": report.lon,
        "geo_confidence": report.confidence,
        "miles_from_home": (
            round(report.miles_from_home, 2)
            if report.miles_from_home is not None and distance_is_meaningful(report.confidence)
            else None
        ),
        "within_3mi": within,
        "proximity": prox,
        "photos": report.image_count,
        "replies": report.reply_count,
        "first_seen": report.first_seen,
    }
    lines = ["---"]
    lines += [f"{k}: {_yaml_scalar(v)}" for k, v in fm.items()]
    tags = ["urbex/site"] + [f"urbex/{t}" for t in report.tags]
    if within:
        tags.append("urbex/near-home")
    lines.append("tags:")
    lines += [f"  - {t}" for t in tags]
    lines.append("---")
    lines.append("")

    icon = CONFIDENCE_ICON.get(report.confidence, "❓")
    lines.append(f"### {report.title}")
    lines.append("")
    where = report.place or "location not determined"
    if report.miles_from_home is not None and distance_is_meaningful(report.confidence):
        where += f" -- {report.miles_from_home:.1f} mi from home"
    elif prox == "unplaceable":
        where += " -- distance unknown (pin is a city centroid, not the site)"
    lines.append(f"{icon} **{where}** (`{report.confidence}` confidence)")
    lines.append("")
    if report.reasoning:
        lines.append(f"> {report.reasoning}")
        lines.append("")
    lines.append(f"Posted by **{report.author or 'unknown'}** on {report.posted} - "
                 f"{report.image_count} photo(s), {report.reply_count} repl(y/ies).")
    lines.append("")
    if report.lat is not None:
        lines.append(f"[Open in Maps](https://www.google.com/maps/search/?api=1&query={report.lat},{report.lon})")
        lines.append("")
    if report.excerpt:
        snippet = " ".join(report.excerpt.split())[:280]
        lines.append("> [!quote] From the thread")
        lines.append(f"> {snippet}...")
        lines.append("")
    lines.append(f"[Read the full thread on KC Urbex]({report.url})")
    lines.append("")
    lines.append(HAND_MARKER)
    lines.append("")

    # Preserve Alex's own half of the file.
    if existing and HAND_MARKER in existing:
        tail = existing.split(HAND_MARKER, 1)[1].lstrip("\n")
        if tail.strip():
            lines.append(tail.rstrip() + "\n")
    return "\n".join(lines)


def write_notes(reports: dict[str, Report]) -> list[Path]:
    """Project every report to a note, preserving hand-written sections."""
    SITES_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for report in reports.values():
        if report.lat is not None and report.lon is not None and report.miles_from_home is None:
            report.miles_from_home = miles_from_home(report.lat, report.lon)
        path = note_path(report)
        existing = path.read_text() if path.exists() else ""
        body = render_note(report, existing)
        if existing != body:
            path.write_text(body)
            written.append(path)
    return written


BASE_CONTENT = """filters:
  and:
    - file.ext == "md"
    - type == "urbex_site"
formulas:
  pin: if(geo_confidence == "exact", "🎯", if(geo_confidence == "block", "📍", if(geo_confidence == "neighborhood", "🗺️", if(geo_confidence == "region", "🌆", "❓"))))
  near: if(within_3mi, "⭐", "")
  distance: if(miles_from_home, miles_from_home + " mi", "--")
properties:
  file.name:
    displayName: Site
  formula.pin:
    displayName: Geo
  formula.near:
    displayName: Near
  formula.distance:
    displayName: Distance
  place:
    displayName: Place
  posted:
    displayName: Posted
  reported_by:
    displayName: By
  photos:
    displayName: Pics
  geo_confidence:
    displayName: Confidence
  proximity:
    displayName: Near home?
  url:
    displayName: Thread
views:
  - type: table
    name: Within 3 miles
    filters:
      and:
        - within_3mi == true
    order:
      - file.name
      - formula.pin
      - formula.distance
      - place
      - posted
      - reported_by
      - photos
    sort:
      - property: miles_from_home
        direction: ASC
  - type: table
    name: All sites by distance
    order:
      - file.name
      - formula.near
      - formula.pin
      - formula.distance
      - place
      - posted
      - photos
    sort:
      - property: miles_from_home
        direction: ASC
  - type: table
    name: Newest first
    order:
      - file.name
      - posted
      - place
      - formula.distance
      - reported_by
      - photos
    sort:
      - property: posted
        direction: DESC
  - type: table
    name: Needs locating
    filters:
      and:
        - proximity == "unplaceable"
    order:
      - file.name
      - posted
      - reported_by
      - url
    sort:
      - property: posted
        direction: DESC
"""


def write_base() -> Path:
    URBEX_DIR.mkdir(parents=True, exist_ok=True)
    BASE_FILE.write_text(BASE_CONTENT)
    return BASE_FILE
