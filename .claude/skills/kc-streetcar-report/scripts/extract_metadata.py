#!/usr/bin/env python3
"""
Extract EXIF metadata from a photo and match GPS coordinates
to the nearest KC Streetcar station.

Usage:
    python3 extract_metadata.py <image_path>

Output: JSON with station, timestamp, coordinates, and device info.
"""

import sys
import json
import math
from PIL import Image
from PIL.ExifTags import GPSTAGS

# KC Streetcar stations: (name, latitude, longitude)
# Coordinates are approximate, based on cross-street positions along Main St.
# Matching threshold: 300m (~0.003 degrees)
# Names as the Authority's See Say form writes them; positions from
# OpenStreetMap (railway=tram_stop, ODbL), averaged over each stop's two
# platforms. Matches mykcmo/streetcar.py. Pulled 2026-10-05.
STATIONS = [
    ("Riverfront (Berkley Riverfront)", 39.11715, -94.57212),
    ("River Market (3rd & Grand)", 39.11043, -94.58133),
    ("River Market West (4th & Delaware)", 39.10880, -94.58438),
    ("City Market (5th & Walnut)", 39.10851, -94.58189),
    ("North Loop (7th & Main)", 39.10524, -94.58303),
    ("Library (9th & Main)", 39.10311, -94.58307),
    ("Metro Center (12th & Main)", 39.09994, -94.58321),
    ("Power & Light (14th & Main)", 39.09684, -94.58334),
    ("Kauffman Center (16th & Main)", 39.09451, -94.58347),
    ("Crossroads (19th & Main)", 39.09041, -94.58368),
    ("Union Station (Pershing & Main)", 39.08467, -94.58406),
    ("WWI Museum & Memorial (27th & Main)", 39.07853, -94.58453),
    ("Union Hill (31st & Main)", 39.07107, -94.58531),
    ("Armour (35th & Main)", 39.06377, -94.58569),
    ("Westport (39th & Main)", 39.05643, -94.58612),
    ("Southmoreland (43rd & Main)", 39.04937, -94.58655),
    ("Art Museums (45th & Main)", 39.04591, -94.58674),
    ("Plaza (Cleaver II & Brookside)", 39.04109, -94.58612),
    ("UMKC (51st & Brookside)", 39.03547, -94.58412),
]

MAX_MATCH_DISTANCE_M = 500  # must be within 500m of a station


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance in meters between two lat/lon points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def dms_to_dd(dms, ref):
    """Convert EXIF DMS tuple to decimal degrees."""
    d, m, s = [float(x) for x in dms]
    dd = d + m / 60 + s / 3600
    if ref in ("S", "W"):
        dd *= -1
    return dd


def extract_metadata(image_path):
    img = Image.open(image_path)
    exif = img._getexif()  # noqa: SLF001 (public getexif() returns a different shape; legacy dict API intended)
    result = {
        "station": None,
        "station_distance_m": None,
        "latitude": None,
        "longitude": None,
        "timestamp": None,
        "device": None,
        "on_streetcar_route": False,
    }

    if not exif:
        result["error"] = "No EXIF data found"
        return result

    # Timestamp
    for tag_id in (36867, 36868, 306):  # DateTimeOriginal, Digitized, DateTime
        if tag_id in exif:
            result["timestamp"] = exif[tag_id]
            break

    # Device
    make = exif.get(271, "")
    model = exif.get(272, "")
    if make or model:
        result["device"] = f"{make} {model}".strip()

    # GPS
    gps_info = exif.get(34853)
    if not gps_info:
        result["error"] = "No GPS data in EXIF"
        return result

    gps = {}
    for k, v in gps_info.items():
        gps[GPSTAGS.get(k, k)] = v

    if "GPSLatitude" in gps and "GPSLongitude" in gps:
        lat = dms_to_dd(gps["GPSLatitude"], gps["GPSLatitudeRef"])
        lon = dms_to_dd(gps["GPSLongitude"], gps["GPSLongitudeRef"])
        result["latitude"] = round(lat, 6)
        result["longitude"] = round(lon, 6)

        # Find nearest station
        best_name, best_dist = None, float("inf")
        for name, slat, slon in STATIONS:
            d = haversine_m(lat, lon, slat, slon)
            if d < best_dist:
                best_name, best_dist = name, d

        result["station_distance_m"] = round(best_dist, 1)
        if best_dist <= MAX_MATCH_DISTANCE_M:
            result["station"] = best_name
            result["on_streetcar_route"] = True
    else:
        result["error"] = "GPS data incomplete"

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 extract_metadata.py <image_path>", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(extract_metadata(sys.argv[1]), indent=2))
