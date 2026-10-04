"""Importing a community spreadsheet of urbex sites into the same vault folder.

The forum is not the only source: explorers also pass around Google Sheets of
locations with a risk score, a recon log and a color legend. `kcurbex sheet URL`
pulls one, geocodes each address, and writes one note per row next to the forum
reports, so the Base shows both.

INVARIANTS:
- The sheet URL and everything pulled from it stay in the gitignored data/ folder.
  A shared location list is the same kind of gated material as the forum.
- Only site addresses go to the geocoders, never home coordinates.
- A row with no street address is never pinned as if it had one: a bare town name is
  `region`, an address with no city is a Kansas City guess at `neighborhood`, and an
  unmatched address is `unknown`.
- Notes keep Alex's `## Notes` tail across reimports, the same as forum notes.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import openpyxl
import requests

from .auth import HERE
from .geo import distance_is_meaningful, miles_from_home, proximity
from .vault import CONFIDENCE_ICON, HAND_MARKER, SITES_DIR, _yaml_scalar, safe_filename

DATA = HERE / "data"
SOURCE_PATH = DATA / "sheet_source.json"
SITES_PATH = DATA / "sheet_sites.json"
GEOCACHE_PATH = DATA / "sheet_geocache.json"

CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = {"User-Agent": "kcurbex-sheet-import/1.0 (personal research index)"}

# The sheet's own legend, keyed by row fill. Colors not in the legend keep their hex.
COLOR_STATUS = {
    "FF00FF00": "visited, good",
    "FFFFFF00": "medium risk",
    "FFFF0000": "high risk",
    "FF980000": "super high risk",
    "FF00FFFF": "researched, not visited",
    "FFFF9900": "not researched",
    "theme8": "not researched",
    "FF4A86E8": "nothing found",
    "FF34A853": "active or repurposed",
    "theme7": "active or repurposed",
}

DMS = re.compile(r"""(\d+)°(\d+)'([\d.]+)"?\s*([NS])\s+(\d+)°(\d+)'([\d.]+)"?\s*([EW])""")
DECIMAL = re.compile(r"\(?\s*(-?\d{1,2}\.\d{3,})\s*,\s*(-?\d{2,3}\.\d{3,})\s*\)?")
HAS_STATE = re.compile(r"\b(MO|KS|Missouri|Kansas)\b", re.I)
# Towns the geocoders no longer know by the name the sheet uses.
RENAMED = {"Stanley, KS": "Overland Park, KS"}


@dataclass
class SheetSite:
    row: int
    name: str
    address: str
    abandoned: str
    slang: str
    risk: str
    risk_notes: str
    abandoned_date: str
    history: str
    recon: str
    links: list[str]
    status: str
    lat: float | None = None
    lon: float | None = None
    confidence: str = "unknown"
    place: str = ""
    reasoning: str = ""


# -- fetch ------------------------------------------------------------------------


def sheet_id(url: str) -> str:
    m = re.search(r"/spreadsheets/d/([\w-]+)", url)
    if not m:
        raise ValueError(f"not a Google Sheets URL: {url}")
    return m.group(1)


def remember_source(url: str | None, as_of: str | None = None) -> dict:
    """The sheet URL and the date its data dates from, remembered between runs."""
    saved = json.loads(SOURCE_PATH.read_text()) if SOURCE_PATH.exists() else {}
    if url:
        saved["url"] = url
    if as_of:
        saved["as_of"] = as_of
    if "url" not in saved:
        raise RuntimeError("no sheet URL given and none remembered in data/sheet_source.json")
    DATA.mkdir(parents=True, exist_ok=True)
    SOURCE_PATH.write_text(json.dumps(saved))
    return saved


def _fill(cell) -> str:
    color = cell.fill.fgColor
    if color.type == "theme":
        return f"theme{color.theme}"
    return color.rgb if isinstance(color.rgb, str) else ""


def fetch(url: str) -> list[SheetSite]:
    """Pull the first tab as CSV (values) and XLSX (row colors), joined by row."""
    sid = sheet_id(url)
    base = f"https://docs.google.com/spreadsheets/d/{sid}/export"
    csv_text = requests.get(base, params={"format": "csv", "gid": "0"}, timeout=30).text
    xlsx = requests.get(base, params={"format": "xlsx"}, timeout=30).content
    ws = openpyxl.load_workbook(io.BytesIO(xlsx)).worksheets[0]

    rows = list(csv.reader(io.StringIO(csv_text)))
    sites = []
    for i, r in enumerate(rows[1:], start=1):
        r = (r + [""] * 13)[:13]
        clean = [" ".join(c.split()) for c in r]
        name, address = clean[2], clean[3].strip('"')
        if not name and not address:
            continue
        links = [c for c in (clean[9], clean[10], clean[11]) if c.startswith("http")]
        sites.append(SheetSite(
            row=i, name=name, address=address, abandoned=clean[0], slang=clean[1],
            risk=clean[4], risk_notes=clean[5], abandoned_date=clean[6], history=clean[7],
            recon=clean[8], links=links,
            status=COLOR_STATUS.get(_fill(ws.cell(i + 1, 3)), ""),
        ))
    return sites


# -- geocode ----------------------------------------------------------------------


def _census(address: str) -> tuple[float, float, str] | None:
    resp = requests.get(CENSUS, params={"address": address, "benchmark": "Public_AR_Current",
                                        "format": "json"}, timeout=30)
    matches = resp.json().get("result", {}).get("addressMatches", [])
    if not matches:
        return None
    m = matches[0]
    return m["coordinates"]["y"], m["coordinates"]["x"], m["matchedAddress"]


def _nominatim(query: str) -> tuple[float, float, str] | None:
    time.sleep(1.1)  # the public instance allows one request per second
    resp = requests.get(NOMINATIM, params={"q": query, "format": "json", "limit": 1,
                                           "countrycodes": "us"}, headers=UA, timeout=30)
    hits = resp.json()
    if not hits:
        return None
    return float(hits[0]["lat"]), float(hits[0]["lon"]), hits[0]["display_name"]


def geocode(site: SheetSite) -> tuple[float | None, float | None, str, str, str]:
    """(lat, lon, confidence, place, reasoning) for one row."""
    addr = site.address
    if m := DMS.search(addr):
        g = m.groups()
        lat = int(g[0]) + int(g[1]) / 60 + float(g[2]) / 3600
        lon = int(g[4]) + int(g[5]) / 60 + float(g[6]) / 3600
        lat = -lat if g[3] == "S" else lat
        lon = -lon if g[7] == "W" else lon
        return round(lat, 6), round(lon, 6), "exact", addr, "The sheet gives coordinates."
    if m := DECIMAL.search(addr):
        return (float(m.group(1)), float(m.group(2)), "exact", addr,
                "The sheet gives coordinates.")

    street = re.split(r"\s*&\s*", addr)[0]
    for old, new in RENAMED.items():
        street = street.replace(old, new)
    if re.match(r"^\d", street):
        assumed = not HAS_STATE.search(street)
        # Only Topeka uses quadrant prefixes like "S.W." in this region.
        city = "Topeka, KS" if re.search(r"\bS\.?W\.?\s", street) else "Kansas City, MO"
        query = f"{street.rstrip('.')}, {city}" if assumed else street
        hit = _census(query)
        conf = "exact"
        if not hit and (hit := _nominatim(query)):
            # Nominatim falls back to the street centroid when it lacks the house number.
            number = re.match(r"\d+", street)
            if not (number and number.group() in hit[2]):
                conf = "neighborhood"
        if hit:
            if assumed:
                return (hit[0], hit[1], "neighborhood", hit[2],
                        f"The sheet gives no city, so this assumes {city}.")
            if conf == "neighborhood":
                return (hit[0], hit[1], conf, hit[2],
                        "The geocoder found the street but not the house number.")
            return hit[0], hit[1], conf, hit[2], "Street address matched by a geocoder."
        return None, None, "unknown", addr, "No geocoder matched this address."

    # No street number: a town, a plus code, or a bare road name.
    town = addr if HAS_STATE.search(addr) else f"{addr}, Kansas"
    hit = _nominatim(town)
    if not hit and "," in addr:  # "PHVV+GF Delano Township, Wichita, KS": keep the town
        hit = _nominatim(", ".join(p.strip() for p in addr.split(",")[-2:]))
    if hit:
        why = "The sheet names only a town or road, so the pin is its centroid."
        if not HAS_STATE.search(addr):
            why += " The sheet gives no state, so this assumes Kansas."
        return hit[0], hit[1], "region", hit[2], why
    return None, None, "unknown", addr, "No geocoder matched this location."


def locate(sites: list[SheetSite]) -> None:
    cache = json.loads(GEOCACHE_PATH.read_text()) if GEOCACHE_PATH.exists() else {}
    for s in sites:
        if s.address not in cache:
            cache[s.address] = geocode(s) if s.address else (None, None, "unknown", "", "No address.")
        s.lat, s.lon, s.confidence, s.place, s.reasoning = cache[s.address]
    GEOCACHE_PATH.write_text(json.dumps(cache, indent=2))
    SITES_PATH.write_text(json.dumps([asdict(s) for s in sites], indent=2))


# -- project ----------------------------------------------------------------------


def title(site: SheetSite) -> str:
    name = site.name.strip()
    if not re.search(r"[A-Za-z]{3}", name):  # "?", "????", "611"
        name = site.address or f"Unnamed site {site.row}"
    return " ".join(w if not w.isupper() or len(w) <= 3 else w.title() for w in name.split())


def note_path(site: SheetSite) -> Path:
    return SITES_DIR / f"{safe_filename(title(site))} (sheet {site.row}).md"


def render(site: SheetSite, existing: str = "", as_of: str | None = None) -> str:
    miles = miles_from_home(site.lat, site.lon) if site.lat is not None and site.lon is not None else None
    prox = proximity(site.confidence, miles)
    within = prox == "near" if prox != "unplaceable" else None
    risk = re.match(r"\d+(\.\d+)?", site.risk)

    fm = {
        "type": "urbex_site",
        "source": "sheet",
        "sheet_row": site.row,
        "title": title(site),
        "address": site.address,
        "place": site.place,
        "lat": site.lat,
        "lon": site.lon,
        "geo_confidence": site.confidence,
        "miles_from_home": round(miles, 2) if miles is not None and distance_is_meaningful(site.confidence) else None,
        "within_3mi": within,
        "proximity": prox,
        "risk": float(risk.group()) if risk else None,
        "sheet_status": site.status or None,
        "abandoned": site.abandoned or None,
        "abandoned_since": site.abandoned_date or None,
        # Every row is someone else's recon from when the sheet was written. Nothing here
        # is verified until Alex goes, and then he flips this by hand in the note, so a
        # re-import keeps whatever value the note already has.
        "data_as_of": as_of,
        "verified": bool(re.search(r"^verified: true$", existing, re.M)),
    }
    lines = ["---", *(f"{k}: {_yaml_scalar(v)}" for k, v in fm.items()), "tags:",
             "  - urbex/site", "  - urbex/sheet", "  - urbex/unverified"]
    if within:
        lines.append("  - urbex/near-home")
    lines += ["---", "", f"### {title(site)}", ""]
    lines += ["> [!warning] Old and unverified",
              f"> This entry comes from a shared spreadsheet with data from {as_of or 'an unknown date'}. "
              "Nobody has checked it since. The site can be demolished, secured, or reused.", ""]

    where = site.address or "no address given"
    if miles is not None and distance_is_meaningful(site.confidence):
        where += f" -- {miles:.1f} mi from home"
    elif prox == "unplaceable":
        where += " -- distance unknown"
    lines += [f"{CONFIDENCE_ICON.get(site.confidence, '❓')} **{where}** (`{site.confidence}` confidence)", ""]
    if site.reasoning:
        lines += [f"> {site.reasoning} {site.place}".rstrip(), ""]

    facts = [
        ("Type", site.slang), ("Abandoned?", site.abandoned), ("Since", site.abandoned_date),
        ("Risk (1-10)", site.risk), ("Sheet color", site.status),
    ]
    lines += [f"- **{k}**: {v}" for k, v in facts if v]
    lines.append("")
    if site.risk_notes:
        lines += ["**Risks**", "", site.risk_notes, ""]
    if site.history:
        lines += ["**History**", "", site.history, ""]
    if site.recon:
        lines += ["> [!info] Latest recon from the sheet", f"> {site.recon}", ""]
    for link in site.links:
        lines += [f"[Source]({link})", ""]
    if site.lat is not None:
        lines += [f"[Open in Maps](https://www.google.com/maps/search/?api=1&query={site.lat},{site.lon})", ""]
    lines += [HAND_MARKER, ""]

    if existing and HAND_MARKER in existing:
        tail = existing.split(HAND_MARKER, 1)[1].lstrip("\n")
        if tail.strip():
            lines.append(tail.rstrip() + "\n")
    return "\n".join(lines)


def write_notes(sites: list[SheetSite], as_of: str | None = None) -> list[Path]:
    SITES_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for s in sites:
        path = note_path(s)
        existing = path.read_text() if path.exists() else ""
        body = render(s, existing, as_of)
        if body != existing:
            path.write_text(body)
            written.append(path)
    return written
