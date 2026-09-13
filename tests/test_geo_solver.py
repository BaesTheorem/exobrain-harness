"""Round-trip and calibration tests for the geolocation solver.

The shadow solver's whole value is that it is checkable: `sun_position` projects a known
place into a shadow, and `latitudes_from_shadow` has to invert that back. If these tests
pass, a latitude the tool reports is arithmetic rather than vibes.
"""

from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "geoguessr"))

from geo_solver import (  # noqa: E402 - path shim above must run first
    OBLIQUITY_DEG,
    altitude_from_shadow,
    declination,
    distance_for_score,
    haversine_km,
    latitudes_from_shadow,
    score_for_distance,
    sun_position,
)

# (name, latitude, date, local solar time)
PLACES = [
    ("Kansas City, June noon", 39.10, date(2026, 6, 21), 12.0),
    ("Kansas City, December morning", 39.10, date(2026, 12, 8), 9.5),
    ("Sydney, March afternoon", -33.87, date(2026, 3, 15), 15.0),
    ("Reykjavik, May midmorning", 64.15, date(2026, 5, 2), 10.0),
    ("Nairobi, near equator", -1.29, date(2026, 8, 20), 13.5),
    ("Ushuaia, deep south", -54.80, date(2026, 1, 10), 16.0),
]


@pytest.mark.parametrize(("name", "latitude", "day", "solar_time"), PLACES)
def test_shadow_inverts_back_to_the_latitude_it_came_from(
    name: str, latitude: float, day: date, solar_time: float
) -> None:
    decl = declination(day)
    altitude, azimuth = sun_position(latitude, 0.0, decl, solar_time)
    assert altitude > 0, f"{name}: sun below horizon, test case is wrong"

    recovered = latitudes_from_shadow(altitude, azimuth, decl)
    assert any(abs(sol.latitude - latitude) < 0.05 for sol in recovered), (
        f"{name}: got {[round(s.latitude, 2) for s in recovered]}, wanted {latitude}"
    )


@pytest.mark.parametrize(("name", "latitude", "day", "solar_time"), PLACES)
def test_recovered_solar_time_matches(
    name: str, latitude: float, day: date, solar_time: float
) -> None:
    decl = declination(day)
    altitude, azimuth = sun_position(latitude, 0.0, decl, solar_time)
    best = min(
        latitudes_from_shadow(altitude, azimuth, decl),
        key=lambda s: abs(s.latitude - latitude),
    )
    assert best.solar_time is not None
    assert abs(best.solar_time - solar_time) < 0.05, name


def test_declination_hits_the_solstices_and_equinoxes() -> None:
    assert declination(date(2026, 6, 21)) == pytest.approx(OBLIQUITY_DEG, abs=0.2)
    assert declination(date(2026, 12, 21)) == pytest.approx(-OBLIQUITY_DEG, abs=0.2)
    assert abs(declination(date(2026, 3, 20))) < 1.0
    assert abs(declination(date(2026, 9, 22))) < 1.0


def test_shadow_length_maps_to_altitude() -> None:
    assert altitude_from_shadow(1.0, 1.0) == pytest.approx(45.0)
    assert altitude_from_shadow(1.0, 0.0) == pytest.approx(90.0)
    assert altitude_from_shadow(1.0, math.sqrt(3)) == pytest.approx(30.0)


def test_impossible_geometry_returns_nothing_rather_than_a_guess() -> None:
    # A sun due east sits at altitude |declination| at most, anywhere on Earth. So on the
    # December solstice nothing can see the sun due east and 10 degrees up, and the honest
    # answer is an empty list rather than a nearest-fit latitude.
    assert latitudes_from_shadow(altitude=10.0, sun_azimuth=90.0, decl=-23.44) == []
    assert latitudes_from_shadow(altitude=30.0, sun_azimuth=90.0, decl=-23.44) != []


def test_both_branches_are_reported_when_both_are_real() -> None:
    # Sun 5 degrees up and due north on the June solstice is genuinely ambiguous: it is
    # either polar midnight in the far north or midwinter noon in the far south.
    sols = latitudes_from_shadow(altitude=5.0, sun_azimuth=0.0, decl=OBLIQUITY_DEG)
    assert len(sols) == 2
    lats = sorted(sol.latitude for sol in sols)
    assert lats[0] == pytest.approx(-61.6, abs=0.3)
    assert lats[1] == pytest.approx(71.6, abs=0.3)


def test_haversine_against_a_known_city_pair() -> None:
    # Kansas City to St Louis is about 383 km.
    assert haversine_km((39.0997, -94.5786), (38.6270, -90.1994)) == pytest.approx(
        383, abs=5
    )


def test_score_curve_matches_reported_world_map_values() -> None:
    assert score_for_distance(0.0) == 5000
    assert score_for_distance(100) == pytest.approx(4678, abs=25)
    assert score_for_distance(500) == pytest.approx(3583, abs=25)
    assert score_for_distance(1000) == pytest.approx(2567, abs=25)


def test_score_and_distance_are_inverses() -> None:
    for km in (10, 100, 750, 3000):
        assert distance_for_score(score_for_distance(km)) == pytest.approx(km, rel=0.01)


def test_smaller_maps_punish_the_same_miss_harder() -> None:
    country_map = 1500.0
    assert score_for_distance(100, country_map) < score_for_distance(100)
