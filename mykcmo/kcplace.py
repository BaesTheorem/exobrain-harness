"""Where a report comes from: photo GPS, nearest address, nearest intersection.

Used to fill a report's location fields and to add one location line to its
free-text description, so a crew can find the spot without the map pin.

- exif_gps(path): (lat, lon) from a photo's EXIF GPS block, or None.
- nearest_address(lat, lon): USPS-style street address (OpenStreetMap Nominatim).
- nearest_intersection(lat, lon): (["E 12th St", "Main St"], meters) (US Census TIGER).
- describe(lat, lon, source): the one-line summary for the description.

INVARIANTS:
- Network lookups fail soft: they return "" and never raise, because a
  report must not fail for want of a cross street.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request

UA = "mykcmo-mcp/1.0 (personal 311 client)"
OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
ABBR = {
    "North": "N", "South": "S", "East": "E", "West": "W", "Street": "St", "Road": "Rd",
    "Avenue": "Ave", "Boulevard": "Blvd", "Drive": "Dr", "Parkway": "Pkwy", "Terrace": "Ter",
    "Place": "Pl", "Lane": "Ln", "Court": "Ct", "Trafficway": "Trfy", "Highway": "Hwy",
}
# Road classes a person would name as a cross street.
ROADS = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street"


def usps(name: str) -> str:
    return " ".join(ABBR.get(w, w) for w in name.split())


def meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = (lat2 - lat1) * 111_320
    dx = (lon2 - lon1) * 111_320 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


def exif_gps(path: str) -> tuple[float, float] | None:
    from PIL import Image

    try:
        gps = Image.open(path).getexif().get_ifd(0x8825)
    except OSError:
        return None
    if not gps or 2 not in gps or 4 not in gps:
        return None

    def dd(v, ref) -> float:
        d, m, s = (float(x) for x in v)
        x = d + m / 60 + s / 3600
        return -x if ref in ("S", "W") else x

    return dd(gps[2], gps.get(1, "N")), dd(gps[4], gps.get(3, "E"))


def _get(url: str, data: bytes | None = None, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def nearest_address(lat: float, lon: float) -> str:
    try:
        d = _get("https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
            {"lat": lat, "lon": lon, "format": "json", "zoom": 18, "addressdetails": 1}))
    except (OSError, ValueError):
        return ""
    a = d.get("address", {})
    street = usps(" ".join(x for x in (a.get("house_number"), a.get("road")) if x))
    zip_ = a.get("postcode", "")
    return f"{street}, Kansas City, MO {zip_}".strip() if street else ""


TIGER_ROADS = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Transportation/MapServer/8/query?"


def _ordinal(name: str) -> str:
    """TIGER mixes "E 13 St" and "E 13th St"; make both "E 13th St"."""
    def fix(m: re.Match) -> str:
        n = int(m.group(1))
        suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suf} {m.group(2)}"

    return re.sub(r"\b(\d+) (St|Ter|Pl|Ave|Rd|Ct|Dr|Ln|Cir)\b", fix, name)


def _core(name: str) -> str:
    """"E Linwood Blvd" and "W Linwood Blvd" are one road for this purpose."""
    return re.sub(r"^[NSEW] ", "", name)


def nearest_intersection(lat: float, lon: float, radius: int = 150) -> tuple[list[str], float] | None:
    """Two different roads that share the vertex nearest the point, as
    (names, meters away). US Census TIGER roads (fast, topologically noded);
    OpenStreetMap Overpass is the fallback."""
    try:
        d = _get(TIGER_ROADS + urllib.parse.urlencode({
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "distance": radius, "units": "esriSRUnit_Meter",
            "outFields": "NAME", "returnGeometry": "true", "outSR": 4326, "f": "json"}))
        roads = [(usps(_ordinal(f["attributes"]["NAME"] or "")), [tuple(pt) for path in f["geometry"]["paths"] for pt in path])
                 for f in d.get("features", []) if f["attributes"].get("NAME")]
    except (OSError, ValueError, KeyError):
        roads = []
    if not roads:
        return _overpass_intersection(lat, lon, radius)
    names_at: dict[tuple[float, float], set[str]] = {}
    for name, pts in roads:
        for x, y in pts:
            names_at.setdefault((round(x, 6), round(y, 6)), set()).add(name)
    best = None
    for (x, y), names in names_at.items():
        by_core = {_core(n): n for n in sorted(names)}
        if len(by_core) >= 2:
            dist = meters(lat, lon, y, x)
            if best is None or dist < best[1]:
                best = (sorted(by_core.values())[:2], dist)
    return best


def _overpass_intersection(lat: float, lon: float, radius: int) -> tuple[list[str], float] | None:
    q = (f'[out:json][timeout:15];way(around:{radius},{lat},{lon})["highway"~"^({ROADS})$"]["name"];'
         "out body;>;out skel qt;")
    data = None
    for url in OVERPASS:
        try:
            data = _get(url, urllib.parse.urlencode({"data": q}).encode())
            break
        except (OSError, ValueError):
            continue
    if not data:
        return None
    nodes = {e["id"]: (e["lat"], e["lon"]) for e in data["elements"] if e["type"] == "node"}
    names_at: dict[int, set[str]] = {}
    for w in (e for e in data["elements"] if e["type"] == "way"):
        for n in w.get("nodes", []):
            names_at.setdefault(n, set()).add(usps(w["tags"]["name"]))
    best = None
    for n, names in names_at.items():
        by_core = {_core(x): x for x in sorted(names)}
        if len(by_core) >= 2 and n in nodes:
            dist = meters(lat, lon, *nodes[n])
            if best is None or dist < best[1]:
                best = (sorted(by_core.values())[:2], dist)
    return best


def describe(lat: float, lon: float, source: str) -> dict:
    """Location facts plus the one-line text for the description."""
    address = nearest_address(lat, lon)
    inter = nearest_intersection(lat, lon)
    cross = f"{' & '.join(inter[0])} (about {round(inter[1])} m away)" if inter else ""
    street = re.sub(r"^\d+[A-Z]?\s+", "", address.split(",")[0]) if address else ""
    other = next((n for n in (inter[0] if inter else []) if _core(n) != _core(street)), "")
    parts = [f"GPS {lat:.6f}, {lon:.6f} ({source})"]
    if address:
        parts.append(f"nearest address {address}")
    if cross:
        parts.append(f"nearest intersection {cross}")
    return {"lat": lat, "lon": lon, "source": source, "address": address, "intersection": cross,
            "street": street, "cross_street": other,
            "line": "Location: " + "; ".join(parts) + "."}


# Free-text questions that ask where the problem is. The negative list keeps
# out questions about the reporter (their address, email, employer) and
# questions that only mention a place in passing (how many, when).
WHERE = re.compile(r"locat|intersection|where is|street ?/ ?location|address or intersection|specific address"
                   r"|area of (traffic )?concern|where .*needed", re.I)
NOT_WHERE = re.compile(r"e-?mail|employer|current address|your name|rental|business|company|manager|how many"
                       r"|property issues|when|visit|assisted|county|verify", re.I)


def answer_for(caption: str, place: dict) -> str | None:
    """The text to put in a free-text question about location, or None."""
    c = caption.strip().lower()
    if c == "street":
        return place["street"] or None
    if c in ("intersecting street", "cross street"):
        return place["cross_street"] or None
    if WHERE.search(caption) and not NOT_WHERE.search(caption):
        return place["line"].removeprefix("Location: ")
    return None
