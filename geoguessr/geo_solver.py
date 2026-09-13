"""Solar-geometry and scoring math for geolocating a photo.

Everything here is closed-form and dependency-free so the common path stays instant.

INVARIANTS
- `declination` follows the NOAA Fourier series, not the 1-degree Cooper approximation.
  Callers that want the rough version should say so explicitly.
- `latitudes_from_shadow` returns EVERY latitude consistent with the inputs, including
  the second (usually out-of-range) branch. Never silently drop one: the whole point of
  the tool is that the caller sees the ambiguity instead of inheriting a guess.
- Azimuths are compass bearings: degrees clockwise from true north, 0 <= a < 360.
- Score uses S = 5000 * exp(-10 * d / D). D is the map's bounding-box diagonal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

OBLIQUITY_DEG = 23.4397
"""Earth's axial tilt, and therefore the bound on |declination|."""

WORLD_MAP_DIAGONAL_KM = 15_000.0
"""Empirically calibrated diagonal for GeoGuessr's official World map.

Not published by GeoGuessr. Calibrated so the curve reproduces the score points players
actually report (about 4700 at 100 km, 3600 at 500 km, 2550 at 1000 km, and a perfect
5000 inside roughly 150 m). Treat it as good to a few percent, not exact.
"""


def declination(day: date) -> float:
    """Solar declination in degrees, via the NOAA Fourier series."""
    n = day.timetuple().tm_yday
    days_in_year = 366 if _is_leap(day.year) else 365
    g = 2 * math.pi / days_in_year * (n - 1)
    rad = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )
    return math.degrees(rad)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def altitude_from_shadow(object_height: float, shadow_length: float) -> float:
    """Sun altitude in degrees from a vertical object and its shadow on flat ground."""
    if shadow_length <= 0:
        return 90.0
    return math.degrees(math.atan2(object_height, shadow_length))


@dataclass(frozen=True)
class ShadowSolution:
    """One latitude consistent with a sun altitude, azimuth, and declination."""

    latitude: float
    solar_time: float | None
    """Local apparent solar time in hours, or None when the hour angle is degenerate."""

    @property
    def clock(self) -> str:
        if self.solar_time is None:
            return "--:--"
        hours = int(self.solar_time) % 24
        minutes = int(round((self.solar_time - int(self.solar_time)) * 60)) % 60
        return f"{hours:02d}:{minutes:02d}"


def latitudes_from_shadow(
    altitude: float, sun_azimuth: float, decl: float
) -> list[ShadowSolution]:
    """Latitudes where the sun sits at `altitude`/`sun_azimuth` on a day of declination `decl`.

    Solves sin(d) = sin(lat) sin(alt) + cos(lat) cos(alt) cos(az) by collapsing the right
    side to R sin(lat + phase). Returns 0, 1, or 2 solutions; an empty list means the
    geometry is impossible on that date, which is itself a useful answer.
    """
    alt = math.radians(altitude)
    az = math.radians(sun_azimuth)
    d = math.radians(decl)

    a = math.sin(alt)
    b = math.cos(alt) * math.cos(az)
    r = math.hypot(a, b)
    if r == 0:
        return []

    ratio = math.sin(d) / r
    if abs(ratio) > 1:
        return []

    phase = math.atan2(b, a)
    base = math.asin(ratio)
    out: list[ShadowSolution] = []
    for candidate in (base - phase, math.pi - base - phase):
        lat = math.degrees(candidate)
        lat = (lat + 180) % 360 - 180
        if -90 <= lat <= 90:
            out.append(
                ShadowSolution(lat, _solar_time(lat, altitude, sun_azimuth, decl))
            )

    # Two branches can collapse onto the same latitude at the tangent case.
    deduped: list[ShadowSolution] = []
    for sol in out:
        if not any(abs(sol.latitude - seen.latitude) < 1e-6 for seen in deduped):
            deduped.append(sol)
    return deduped


def _solar_time(
    latitude: float, altitude: float, sun_azimuth: float, decl: float
) -> float | None:
    lat = math.radians(latitude)
    alt = math.radians(altitude)
    d = math.radians(decl)
    denom = math.cos(lat) * math.cos(d)
    if abs(denom) < 1e-9:
        return None
    cos_h = (math.sin(alt) - math.sin(lat) * math.sin(d)) / denom
    cos_h = max(-1.0, min(1.0, cos_h))
    hour_angle = math.degrees(math.acos(cos_h))
    # Sun east of the meridian means morning, which is a negative hour angle.
    if sun_azimuth < 180:
        hour_angle = -hour_angle
    return 12 + hour_angle / 15


def sun_position(
    latitude: float, longitude: float, decl: float, solar_time: float
) -> tuple[float, float]:
    """Forward check: sun (altitude, azimuth) for a latitude at a local solar time.

    `longitude` is unused by the geometry and accepted only so callers can pass a full
    coordinate; local solar time already absorbs it.
    """
    del longitude
    lat = math.radians(latitude)
    d = math.radians(decl)
    h = math.radians((solar_time - 12) * 15)

    sin_alt = math.sin(lat) * math.sin(d) + math.cos(lat) * math.cos(d) * math.cos(h)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    altitude = math.degrees(math.asin(sin_alt))

    azimuth = math.degrees(
        math.atan2(
            -math.sin(h) * math.cos(d),
            math.cos(lat) * math.sin(d) - math.sin(lat) * math.cos(d) * math.cos(h),
        )
    )
    return altitude, azimuth % 360


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in km between two (lat, lon) pairs."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    inner = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(math.sqrt(inner))


def score_for_distance(
    distance_km: float, map_diagonal_km: float = WORLD_MAP_DIAGONAL_KM
) -> int:
    """GeoGuessr round score for a miss of `distance_km` on a map of that diagonal."""
    if distance_km * 1000 < 25:
        return 5000
    return round(5000 * math.exp(-10 * distance_km / map_diagonal_km))


def distance_for_score(
    score: float, map_diagonal_km: float = WORLD_MAP_DIAGONAL_KM
) -> float:
    """Inverse of `score_for_distance`: how far off a given score puts you, in km."""
    if score >= 5000:
        return 0.0
    if score <= 0:
        return float("inf")
    return -map_diagonal_km * math.log(score / 5000) / 10
