"""Home location, distances, and the geocode cache.

INVARIANTS:
- Home coordinates are read at runtime from the gitignored harness .env
  (MYKCMO_HOME_LAT / MYKCMO_HOME_LON). They are never written into this repo, never
  logged, and never sent to a third-party geocoder as part of a query.
- Distances are great-circle miles. Over a 3-mile radius in Kansas City the error
  against road/ellipsoid distance is far below the precision of the underlying
  guesses, which are frequently "somewhere along the Missouri river".
- A geocode carries its own confidence. Anything below `exact` is a guess about a
  deliberately vague forum post and must stay visibly a guess downstream.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from .auth import HERE, env_value

GEOCACHE_PATH = HERE / "data" / "geocache.json"

# How sure we are about a coordinate, worst to best.
CONFIDENCE_ORDER = ("unknown", "region", "neighborhood", "block", "exact")

EARTH_RADIUS_MI = 3958.7613

# Confidence levels at which a computed distance actually means something.
# "region" resolves to a metro centroid, so its distance describes where the geocoder
# put the pin, not where the site is: every unidentified KC report lands at the same
# 2.44 mi from home and would otherwise sail through a 3-mile filter as a false hit.
LOCATING_CONFIDENCE = frozenset({"exact", "block", "neighborhood"})


def distance_is_meaningful(confidence: str) -> bool:
    return confidence in LOCATING_CONFIDENCE


def proximity(confidence: str, miles: float | None, radius: float = 3.0) -> str:
    """'near' | 'far' | 'unplaceable' -- the honest answer to "is this close to home?"."""
    if miles is None or not distance_is_meaningful(confidence):
        return "unplaceable"
    return "near" if miles <= radius else "far"


@dataclass
class Geocode:
    lat: float | None
    lon: float | None
    confidence: str
    place: str = ""
    reasoning: str = ""

    @property
    def located(self) -> bool:
        return self.lat is not None and self.lon is not None


def home() -> tuple[float, float]:
    """Alex's home coordinates, from the gitignored harness .env."""
    lat, lon = env_value("MYKCMO_HOME_LAT"), env_value("MYKCMO_HOME_LON")
    if not lat or not lon:
        raise RuntimeError(
            "home coordinates missing: set MYKCMO_HOME_LAT and MYKCMO_HOME_LON in the "
            "harness .env (they are gitignored on purpose)"
        )
    return float(lat), float(lon)


def miles_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle miles between two (lat, lon) pairs."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(h))


def miles_from_home(lat: float, lon: float) -> float:
    return miles_between(home(), (lat, lon))


def load_cache() -> dict[str, Geocode]:
    """Geocodes keyed by topic id, so a rescan never re-asks about a settled site."""
    if not GEOCACHE_PATH.exists():
        return {}
    raw = json.loads(GEOCACHE_PATH.read_text())
    return {k: Geocode(**v) for k, v in raw.items()}


def save_cache(cache: dict[str, Geocode]) -> Path:
    GEOCACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    GEOCACHE_PATH.write_text(json.dumps({k: asdict(v) for k, v in cache.items()}, indent=2))
    return GEOCACHE_PATH
