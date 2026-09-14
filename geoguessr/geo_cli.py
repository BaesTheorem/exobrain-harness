"""`geo` - the geolocation bench. Run it through `geoguessr/bin/geo`.

Subcommands are deliberately small and deterministic. Anything that needs judgment
(reading a bollard, naming a script) stays with the model; anything with a rule
(solar geometry, scoring, coverage lookup, an Overpass query) lives here.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from geo_solver import (
    OBLIQUITY_DEG,
    WORLD_MAP_DIAGONAL_KM,
    altitude_from_shadow,
    declination,
    distance_for_score,
    haversine_km,
    latitudes_from_shadow,
    score_for_distance,
    sun_position,
)

USER_AGENT = (
    "exobrain-geoguessr/1.0 (personal research; contact via github.com/BaesTheorem)"
)
HERE = Path(__file__).resolve().parent

OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
"""Tried in order. The main instance sheds load with a 504 whenever Europe is awake."""


# --------------------------------------------------------------------------- sun


def _solstice_sweep() -> list[tuple[str, float]]:
    """Declination at the four dates that bracket the year."""
    return [
        ("Jun solstice", OBLIQUITY_DEG),
        ("Equinox", 0.0),
        ("Dec solstice", -OBLIQUITY_DEG),
    ]


def cmd_sun(args: argparse.Namespace) -> int:
    if args.altitude is not None:
        altitude = args.altitude
        how = f"sun altitude {altitude:.1f} deg (given)"
    elif args.height is not None and args.shadow is not None:
        altitude = altitude_from_shadow(args.height, args.shadow)
        ratio = args.shadow / args.height if args.height else float("inf")
        how = f"shadow {ratio:.2f}x object height -> sun altitude {altitude:.1f} deg"
    else:
        print("need either --altitude, or both --height and --shadow", file=sys.stderr)
        return 2

    sun_azimuth = (
        (args.shadow_azimuth + 180) % 360
        if args.shadow_azimuth is not None
        else args.sun_azimuth
    )
    if sun_azimuth is None:
        print(
            "need --shadow-azimuth (compass bearing the shadow points) or --sun-azimuth",
            file=sys.stderr,
        )
        return 2

    print(how)
    print(f"sun azimuth {sun_azimuth:.1f} deg (compass, clockwise from true north)")
    print()

    if args.date:
        cases = [(args.date.isoformat(), declination(args.date))]
    else:
        cases = _solstice_sweep()
        print(
            "No date given, so sweeping the year. Narrow it with --date once season is known."
        )
        print()

    any_solution = False
    for label, decl in cases:
        sols = latitudes_from_shadow(altitude, sun_azimuth, decl)
        if not sols:
            print(
                f"  {label:14} declination {decl:+6.2f}   impossible geometry on this date"
            )
            continue
        any_solution = True
        for sol in sols:
            hemi = "N" if sol.latitude >= 0 else "S"
            print(
                f"  {label:14} declination {decl:+6.2f}   "
                f"lat {abs(sol.latitude):5.1f} {hemi}   local solar time ~{sol.clock}"
            )

    if not any_solution:
        print()
        print(
            "No latitude fits. Re-measure: the shadow may be on a slope, the object may"
        )
        print("not be vertical, or the bearing may be off by the compass's own error.")
        return 1

    if not args.date:
        lats = [
            sol.latitude
            for _, decl in cases
            for sol in latitudes_from_shadow(altitude, sun_azimuth, decl)
        ]
        print()
        print(
            f"Latitude band across the whole year: {min(lats):.1f} to {max(lats):.1f}"
        )
    return 0


def cmd_sunpos(args: argparse.Namespace) -> int:
    """Forward check: what a shadow should look like at a known place and time."""
    decl = declination(args.date)
    altitude, azimuth = sun_position(args.lat, args.lon, decl, args.solar_time)
    print(f"declination      {decl:+.2f} deg")
    print(f"sun altitude     {altitude:+.2f} deg")
    print(f"sun azimuth      {azimuth:.1f} deg")
    if altitude <= 0:
        print("sun is below the horizon, so there is no shadow")
        return 0
    shadow_azimuth = (azimuth + 180) % 360
    ratio = 1 / max(1e-9, math.tan(math.radians(altitude)))
    print(f"shadow bearing   {shadow_azimuth:.1f} deg")
    print(f"shadow length    {ratio:.2f}x object height")
    return 0


# ------------------------------------------------------------------------- score


def cmd_score(args: argparse.Namespace) -> int:
    diagonal = args.map_diagonal
    label = (
        "World map"
        if diagonal == WORLD_MAP_DIAGONAL_KM
        else f"map diagonal {diagonal:g} km"
    )

    if args.guess and args.answer:
        km = haversine_km(args.guess, args.answer)
        print(
            f"{km:.1f} km off -> {score_for_distance(km, diagonal)} points on the {label}"
        )
        return 0

    if args.km is not None:
        print(
            f"{args.km:.1f} km off -> {score_for_distance(args.km, diagonal)} points on the {label}"
        )
        return 0

    if args.points is not None:
        print(
            f"{args.points} points on the {label} -> within {distance_for_score(args.points, diagonal):.1f} km"
        )
        return 0

    print(f"Score curve, {label}:")
    print(f"{'points':>8}  {'max miss':>12}")
    for points in (
        5000,
        4900,
        4750,
        4500,
        4000,
        3500,
        3000,
        2500,
        2000,
        1500,
        1000,
        500,
    ):
        print(f"{points:>8}  {distance_for_score(points, diagonal):>9.1f} km")
    print()
    print("The curve is flat far out and brutal close in: on the World map the whole")
    print("difference between 'right country' and 'right country, wrong end of it' is")
    print("worth less than the difference between right and wrong country.")
    return 0


# -------------------------------------------------------------------------- pano


def cmd_pano(args: argparse.Namespace) -> int:
    script = HERE / "bin" / "geo-pano"
    cmd = [str(script), str(args.lat), str(args.lon), str(args.radius)]
    return subprocess.call(cmd)


# ------------------------------------------------------------------------- where


def _http_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https hosts
        return json.loads(response.read().decode("utf-8"))


def cmd_where(args: argparse.Namespace) -> int:
    """Reverse geocode a candidate, to confirm the country a guess actually lands in."""
    query = urllib.parse.urlencode(
        {"lat": args.lat, "lon": args.lon, "format": "jsonv2", "zoom": args.zoom}
    )
    data = _http_json(f"https://nominatim.openstreetmap.org/reverse?{query}")
    if not isinstance(data, dict) or "error" in data:
        print("nothing there (ocean, or outside OSM's coverage)")
        return 1
    address = data.get("address", {})
    print(data.get("display_name", "?"))
    print()
    for key in (
        "country",
        "country_code",
        "state",
        "region",
        "county",
        "city",
        "town",
        "village",
        "road",
    ):
        if key in address:
            print(f"  {key:14} {address[key]}")
    return 0


def cmd_geocode(args: argparse.Namespace) -> int:
    """Forward geocode: turn a place name read off a sign into coordinates."""
    params = {"q": args.query, "format": "jsonv2", "limit": args.limit}
    if args.country:
        params["countrycodes"] = args.country
    data = _http_json(
        f"https://nominatim.openstreetmap.org/search?{urllib.parse.urlencode(params)}"
    )
    if not isinstance(data, list) or not data:
        print("no match")
        return 1
    for hit in data:
        print(
            f"{float(hit['lat']):>10.5f} {float(hit['lon']):>11.5f}  {hit['display_name']}"
        )
    return 0


def cmd_elev(args: argparse.Namespace) -> int:
    """Ground elevation for one or more points, batched.

    Open-Meteo takes every point in one call and needs no key. USGS EPQS is finer over
    the US (1 m raster) but is one point per request, so it stays the fallback.
    """
    lats = ",".join(str(lat) for lat, _ in args.points)
    lons = ",".join(str(lon) for _, lon in args.points)
    query = urllib.parse.urlencode({"latitude": lats, "longitude": lons})
    data = _http_json(f"https://api.open-meteo.com/v1/elevation?{query}")
    if not isinstance(data, dict) or "elevation" not in data:
        print("elevation service returned nothing usable", file=sys.stderr)
        return 1
    for (lat, lon), metres in zip(args.points, data["elevation"], strict=False):
        print(
            f"{lat:>10.5f} {lon:>11.5f}  {metres:>7.0f} m  {metres * 3.28084:>8,.0f} ft"
        )
    return 0


# ---------------------------------------------------------------------- overpass


def cmd_overpass(args: argparse.Namespace) -> int:
    query = args.query if args.query else sys.stdin.read()
    if "[out:" not in query:
        # Overpass answers in XML unless told otherwise, which every caller here regrets.
        query = "[out:json][timeout:120];" + query
    data = urllib.parse.urlencode({"data": query}).encode()
    body = None
    failures: list[str] = []
    for mirror in OVERPASS_MIRRORS:
        request = urllib.request.Request(
            mirror, data=data, headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 - fixed https hosts
                body = response.read().decode("utf-8")
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            # The main instance 504s under load far more often than the mirrors do,
            # and a 504 says nothing about whether the query itself is sound. Only
            # give up once every mirror has refused it.
            reason = getattr(exc, "code", None) or getattr(exc, "reason", exc)
            failures.append(f"{urllib.parse.urlparse(mirror).netloc}: {reason}")
    if body is None:
        print("every Overpass mirror refused the query:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        print(
            "504 usually means too heavy: tighten the bbox or filter on tags first.",
            file=sys.stderr,
        )
        return 1
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        print(body[:2000], file=sys.stderr)
        return 1

    elements = payload.get("elements", [])
    if args.raw:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    if not elements:
        print("0 results")
        return 1
    print(f"{len(elements)} result(s)")
    for element in elements[: args.limit]:
        centre = element.get("center", element)
        lat, lon = centre.get("lat"), centre.get("lon")
        name = element.get("tags", {}).get("name", "")
        coords = f"{lat:>10.5f} {lon:>11.5f}" if lat and lon else " " * 22
        print(f"  {coords}  {element.get('type', '?'):<8} {name}")
    return 0


# ----------------------------------------------------------------------- enhance


def cmd_enhance(args: argparse.Namespace) -> int:
    """Blow up a region of a screenshot so a blurry sign becomes readable."""
    binary = shutil.which("magick") or shutil.which("convert")
    if not binary:
        print("ImageMagick not found: brew install imagemagick", file=sys.stderr)
        return 127

    out = (
        Path(args.output)
        if args.output
        else args.image.with_name(f"{args.image.stem}-enhanced.png")
    )
    cmd = [binary, str(args.image)]
    if args.crop:
        cmd += ["-crop", args.crop, "+repage"]
    cmd += [
        "-filter",
        "Lanczos",
        "-resize",
        f"{args.scale * 100:g}%",
        "-unsharp",
        "0x1.2+1.5+0.02",
        "-normalize",
    ]
    if args.grayscale:
        cmd += ["-colorspace", "Gray"]
    cmd.append(str(out))

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    print(out)
    return 0


# -------------------------------------------------------------------------- main


def _latlon(text: str) -> tuple[float, float]:
    lat, lon = text.replace(" ", "").split(",")
    return float(lat), float(lon)


def _isodate(text: str) -> date:
    return date.fromisoformat(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="geo", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sun = sub.add_parser("sun", help="latitude band from a shadow")
    sun.add_argument("--height", type=float, help="height of the vertical object")
    sun.add_argument("--shadow", type=float, help="length of its shadow, same units")
    sun.add_argument(
        "--altitude", type=float, help="sun altitude in degrees, if measured directly"
    )
    sun.add_argument(
        "--shadow-azimuth", type=float, help="compass bearing the shadow points"
    )
    sun.add_argument(
        "--sun-azimuth", type=float, help="compass bearing of the sun, if easier"
    )
    sun.add_argument("--date", type=_isodate, help="YYYY-MM-DD; omit to sweep the year")
    sun.set_defaults(func=cmd_sun)

    sunpos = sub.add_parser(
        "sunpos", help="forward check: expected shadow at a known place"
    )
    sunpos.add_argument("lat", type=float)
    sunpos.add_argument("lon", type=float)
    sunpos.add_argument("--date", type=_isodate, required=True)
    sunpos.add_argument(
        "--solar-time", type=float, default=12.0, help="local solar time, hours"
    )
    sunpos.set_defaults(func=cmd_sunpos)

    score = sub.add_parser(
        "score", help="convert between miss distance and round score"
    )
    score.add_argument("--km", type=float, help="miss distance")
    score.add_argument("--points", type=float, help="score, to invert into a distance")
    score.add_argument("--guess", type=_latlon, help="lat,lon")
    score.add_argument("--answer", type=_latlon, help="lat,lon")
    score.add_argument("--map-diagonal", type=float, default=WORLD_MAP_DIAGONAL_KM)
    score.set_defaults(func=cmd_score)

    pano = sub.add_parser("pano", help="is there Street View here, and from when")
    pano.add_argument("lat", type=float)
    pano.add_argument("lon", type=float)
    pano.add_argument("--radius", type=int, default=500, help="search radius in metres")
    pano.set_defaults(func=cmd_pano)

    where = sub.add_parser("where", help="reverse geocode a candidate guess")
    where.add_argument("lat", type=float)
    where.add_argument("lon", type=float)
    where.add_argument("--zoom", type=int, default=12)
    where.set_defaults(func=cmd_where)

    geocode = sub.add_parser("geocode", help="place name from a sign -> coordinates")
    geocode.add_argument("query")
    geocode.add_argument("--country", help="ISO code to restrict to, e.g. pl")
    geocode.add_argument("--limit", type=int, default=8)
    geocode.set_defaults(func=cmd_geocode)

    elev = sub.add_parser("elev", help="ground elevation at one or more points")
    elev.add_argument("points", nargs="+", type=_latlon, help="lat,lon (repeatable)")
    elev.set_defaults(func=cmd_elev)

    overpass = sub.add_parser(
        "overpass", help="run an Overpass QL query (or pipe one in)"
    )
    overpass.add_argument("query", nargs="?")
    overpass.add_argument("--limit", type=int, default=40)
    overpass.add_argument("--raw", action="store_true")
    overpass.set_defaults(func=cmd_overpass)

    enhance = sub.add_parser(
        "enhance", help="crop and upscale a region so a sign is legible"
    )
    enhance.add_argument("image", type=Path)
    enhance.add_argument("--crop", help="ImageMagick geometry, e.g. 400x200+1100+640")
    enhance.add_argument("--scale", type=float, default=4.0)
    enhance.add_argument("--grayscale", action="store_true")
    enhance.add_argument("-o", "--output")
    enhance.set_defaults(func=cmd_enhance)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
