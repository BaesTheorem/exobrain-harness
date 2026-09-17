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
from PIL.ExifTags import TAGS, GPSTAGS

# KC Streetcar stations: (name, latitude, longitude)
# Coordinates are approximate, based on cross-street positions along Main St.
# Matching threshold: 300m (~0.003 degrees)
STATIONS = [
    ("River Market North (3rd & Grand)",    39.1068, -94.5783),
    ("River Market (4th & Delaware)",       39.1048, -94.5793),
    ("City Market (5th & Walnut)",          39.1028, -94.5808),
    ("Metro Center (7th & Main)",           39.0993, -94.5835),
    ("Library (9th & Main)",                39.0968, -94.5835),
    ("Power & Light (13th & Main)",         39.0918, -94.5838),
    ("Kauffman Center (16th & Main)",       39.0882, -94.5840),
    ("Crossroads (19th & Main)",            39.0845, -94.5840),
    ("Union Station (Pershing & Main)",     39.0830, -94.5865),
    ("Crown Center (Pershing & Grand)",     39.0836, -94.5787),
    ("27th & Main",                         39.0755, -94.5850),
    ("Armour (31st & Main)",                39.0641, -94.5856),
    ("Linwood (Linwood & Main)",            39.0590, -94.5855),
    ("39th & Main",                         39.0527, -94.5853),
    ("Westport (Westport Rd & Main)",       39.0505, -94.5852),
    ("Art Museums (45th & Main)",           39.0437, -94.5850),
    ("Plaza Transit Center (47th & Main)",  39.0410, -94.5848),
    ("UMKC (51st & Brookside)",             39.0340, -94.5780),
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
    exif = img._getexif()
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
