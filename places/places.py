#!/usr/bin/env python3
"""Google Places API (New) client -- text search, nearby search, place details.

Stdlib only, so this island needs no venv. Auth is an API key in the harness
.env as GOOGLE_PLACES_API_KEY (see README for how to mint one).

The thing worth understanding before touching this file: on Places API (New)
you are NOT billed per call, you are billed per call at the tier of the most
expensive field you asked for. The X-Goog-FieldMask header is the price tag.
Ask for `places.displayName` and a Text Search is a Pro call; add
`places.rating` to the same request and the identical call becomes Enterprise;
add `places.reviews` and it becomes Enterprise + Atmosphere. Google publishes
free monthly allowances per tier (10k Essentials / 5k Pro / 1k Enterprise), so
a careless field mask does not just cost more per call, it burns the small
allowance instead of the large one.

That is why field masks here are never free-form strings. You pass field names,
they get classified against the published SKU tables below, and the resulting
tier is reported (and, with --max-tier, enforced) before the request goes out.

INVARIANTS:
- Never widen DEFAULT_FIELDS to include an ENTERPRISE or ATMOSPHERE field. The
  defaults exist so the common call stays in the 5k/mo Pro allowance; a field
  added here silently re-tiers every caller in the repo.
- FIELD_TIERS is transcribed from Google's published SKU tables. It is pricing
  data, not taste. Do not "tidy" a field into a cheaper tier to make a call
  cheaper -- that changes the estimate, not the bill.
- The cache key must include the field mask. Two requests with the same query
  and different masks return different payloads; collapsing them serves a
  cached response missing fields the caller paid for.
- details() takes a bare place ID and builds the resource path itself. Passing
  an already-prefixed "places/X" must not produce "places/places/X".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
HARNESS_DIR = HERE.parent
CACHE_DIR = HERE / "cache"
BASE = "https://places.googleapis.com/v1"

# Tier ranks, cheapest first. Higher rank wins when a mask spans tiers.
ESSENTIALS, PRO, ENTERPRISE, ATMOSPHERE = 0, 1, 2, 3
TIER_NAMES = {
    ESSENTIALS: "Essentials",
    PRO: "Pro",
    ENTERPRISE: "Enterprise",
    ATMOSPHERE: "Enterprise + Atmosphere",
}
# Free calls per month per tier, per Google's published allowances.
TIER_FREE_MONTHLY = {ESSENTIALS: 10_000, PRO: 5_000, ENTERPRISE: 1_000, ATMOSPHERE: 1_000}

# Transcribed from Google's Text Search / Place Details SKU tables. Keys are
# bare field names (no "places." prefix) so one table serves both the search
# endpoints (which prefix every field) and details (which does not).
FIELD_TIERS: dict[str, int] = {}


def _register(tier: int, names: str) -> None:
    for n in names.split():
        FIELD_TIERS[n] = tier


_register(ESSENTIALS, """
    attributions id name consumerAlert movedPlace movedPlaceId nextPageToken
    addressComponents adrFormatAddress formattedAddress location plusCode
    shortFormattedAddress types viewport postalAddress
""")
_register(PRO, """
    accessibilityOptions addressDescriptor businessStatus containingPlaces
    displayName googleMapsLinks googleMapsTypeLabel googleMapsUri
    iconBackgroundColor iconMaskBaseUri openingDate photos primaryType
    primaryTypeDisplayName pureServiceAreaBusiness searchUri subDestinations
    timeZone utcOffsetMinutes
""")
_register(ENTERPRISE, """
    currentOpeningHours currentSecondaryOpeningHours internationalPhoneNumber
    nationalPhoneNumber priceLevel priceRange rating regularOpeningHours
    regularSecondaryOpeningHours transitStation userRatingCount websiteUri
""")
_register(ATMOSPHERE, """
    allowsDogs curbsidePickup delivery dineIn editorialSummary
    evChargeAmenitySummary evChargeOptions fuelOptions generativeSummary
    goodForChildren goodForGroups goodForWatchingSports liveMusic
    menuForChildren neighborhoodSummary outdoorSeating parkingOptions
    paymentOptions reservable restroom reviews reviewSummary routingSummaries
    servesBeer servesBreakfast servesBrunch servesCocktails servesCoffee
    servesDessert servesDinner servesLunch servesVegetarianFood servesWine
    takeout
""")

# Enough to identify and locate a place, and no more. Pro tier (5k free/mo).
DEFAULT_FIELDS = ["id", "displayName", "formattedAddress", "location", "types"]


class PlacesError(RuntimeError):
    pass


# --- config -------------------------------------------------------------------


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def api_key() -> str:
    env = load_env_file(HARNESS_DIR / ".env")
    key = os.environ.get("GOOGLE_PLACES_API_KEY") or env.get("GOOGLE_PLACES_API_KEY", "")
    if not key:
        raise PlacesError(
            "GOOGLE_PLACES_API_KEY missing. Add it to the harness .env -- see places/README.md."
        )
    return key


# --- billing tier -------------------------------------------------------------


def tier_of(fields: list[str]) -> tuple[int, list[str]]:
    """Return (billed tier, fields Google does not publish a tier for).

    Unknown fields are reported rather than assumed cheap: a field we have not
    transcribed is more likely a new premium one than a free one.
    """
    tier = ESSENTIALS
    unknown: list[str] = []
    for f in fields:
        bare = f.split(".")[-1].strip()
        if not bare:
            continue
        if bare in FIELD_TIERS:
            tier = max(tier, FIELD_TIERS[bare])
        else:
            unknown.append(f)
    return tier, unknown


def explain_tier(fields: list[str]) -> str:
    tier, unknown = tier_of(fields)
    msg = f"billed as {TIER_NAMES[tier]} ({TIER_FREE_MONTHLY[tier]:,} free calls/mo)"
    drivers = [f for f in fields if FIELD_TIERS.get(f.split(".")[-1]) == tier]
    if drivers:
        msg += f"; set by {', '.join(sorted(drivers))}"
    if unknown:
        msg += f"; UNKNOWN tier for {', '.join(unknown)} (may bill higher)"
    return msg


# --- transport ----------------------------------------------------------------


def _cache_path(kind: str, payload: object, mask: str) -> Path:
    blob = json.dumps([kind, payload, mask], sort_keys=True).encode()
    return CACHE_DIR / f"{kind}-{hashlib.sha256(blob).hexdigest()[:20]}.json"


def _request(
    url: str,
    mask: str,
    body: dict[str, Any] | None,
    *,
    cache_ttl: float,
    kind: str,
    cache_key: object,
) -> dict[str, Any]:
    path = _cache_path(kind, cache_key, mask)
    if cache_ttl > 0 and path.exists() and time.time() - path.stat().st_mtime < cache_ttl:
        return json.loads(path.read_text())

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("X-Goog-Api-Key", api_key())
    req.add_header("X-Goog-FieldMask", mask)
    if data:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:800]
        raise PlacesError(f"HTTP {e.code} from Places API: {detail}") from e
    except urllib.error.URLError as e:
        raise PlacesError(f"network error reaching Places API: {e.reason}") from e

    if cache_ttl > 0:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out))
    return out


def _mask(fields: list[str], prefix: str) -> str:
    return ",".join(f if "." in f else prefix + f for f in fields)


# --- endpoints ----------------------------------------------------------------


def text_search(
    query: str,
    *,
    fields: list[str] | None = None,
    max_results: int = 10,
    bias: tuple[float, float, float] | None = None,
    cache_ttl: float = 86400,
) -> list[dict[str, Any]]:
    """Free-text place search ("coffee near the Nelson-Atkins")."""
    fields = fields or DEFAULT_FIELDS
    body: dict[str, Any] = {"textQuery": query, "maxResultCount": max_results}
    if bias:
        lat, lng, radius = bias
        body["locationBias"] = {
            "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius}
        }
    out = _request(
        f"{BASE}/places:searchText",
        _mask(fields, "places."),
        body,
        cache_ttl=cache_ttl,
        kind="text",
        cache_key=body,
    )
    return out.get("places", [])


def nearby_search(
    lat: float,
    lng: float,
    radius: float,
    *,
    included_types: list[str] | None = None,
    fields: list[str] | None = None,
    max_results: int = 10,
    rank: str = "POPULARITY",
    cache_ttl: float = 86400,
) -> list[dict[str, Any]]:
    """Places within `radius` metres of a point, optionally filtered by type."""
    fields = fields or DEFAULT_FIELDS
    body: dict[str, Any] = {
        "maxResultCount": max_results,
        "rankPreference": rank,
        "locationRestriction": {
            "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": radius}
        },
    }
    if included_types:
        body["includedTypes"] = included_types
    out = _request(
        f"{BASE}/places:searchNearby",
        _mask(fields, "places."),
        body,
        cache_ttl=cache_ttl,
        kind="nearby",
        cache_key=body,
    )
    return out.get("places", [])


def details(
    place_id: str, *, fields: list[str] | None = None, cache_ttl: float = 604800
) -> dict[str, Any]:
    """Full record for one place. Details are stable, so the cache runs a week."""
    fields = fields or DEFAULT_FIELDS
    pid = place_id.split("/")[-1]  # accept bare IDs and "places/ID" resource names
    return _request(
        f"{BASE}/places/{pid}",
        _mask(fields, ""),
        None,
        cache_ttl=cache_ttl,
        kind="details",
        cache_key=pid,
    )


# --- CLI ----------------------------------------------------------------------


def _fmt(p: dict[str, Any]) -> str:
    name = (p.get("displayName") or {}).get("text") or p.get("name", "?")
    bits = [name]
    if addr := p.get("formattedAddress"):
        bits.append(f"  {addr}")
    if (rating := p.get("rating")) is not None:
        bits.append(f"  {rating}* ({p.get('userRatingCount', '?')} ratings)")
    if hours := p.get("regularOpeningHours"):
        bits.append(f"  {'open now' if hours.get('openNow') else 'closed now'}")
    if site := p.get("websiteUri"):
        bits.append(f"  {site}")
    if phone := p.get("nationalPhoneNumber"):
        bits.append(f"  {phone}")
    if pid := p.get("id"):
        bits.append(f"  id: {pid}")
    return "\n".join(bits)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Google Places API (New) client.",
        epilog="Field masks set the price. Run `places tiers` to see what each field costs.",
    )
    ap.add_argument("--json", action="store_true", help="raw JSON instead of formatted text")
    ap.add_argument(
        "-f", "--fields", help=f"comma-separated fields (default: {','.join(DEFAULT_FIELDS)})"
    )
    ap.add_argument(
        "--max-tier",
        choices=["essentials", "pro", "enterprise", "atmosphere"],
        default="enterprise",
        help="refuse to send a request billed above this tier (default: enterprise)",
    )
    ap.add_argument("--no-cache", action="store_true", help="bypass the on-disk response cache")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="free-text search")
    s.add_argument("query", nargs="+")
    s.add_argument("-n", "--max-results", type=int, default=10)
    s.add_argument("--near", help="bias to 'lat,lng,radius_m'")

    n = sub.add_parser("nearby", help="search around a point")
    n.add_argument("location", help="'lat,lng'")
    n.add_argument("-r", "--radius", type=float, default=1000, help="metres (default 1000)")
    n.add_argument("-t", "--types", help="comma-separated place types, e.g. restaurant,cafe")
    n.add_argument("-n", "--max-results", type=int, default=10)
    n.add_argument("--rank", choices=["POPULARITY", "DISTANCE"], default="POPULARITY")

    d = sub.add_parser("details", help="full record for one place id")
    d.add_argument("place_id")

    sub.add_parser("tiers", help="show which fields fall in which billing tier")
    sub.add_parser("check", help="verify the API key works (one cheap Essentials call)")

    args = ap.parse_args(argv)

    if args.cmd == "tiers":
        for t in (ESSENTIALS, PRO, ENTERPRISE, ATMOSPHERE):
            names = sorted(f for f, v in FIELD_TIERS.items() if v == t)
            print(f"\n{TIER_NAMES[t]}  ({TIER_FREE_MONTHLY[t]:,} free calls/mo)")
            print("  " + ", ".join(names))
        print(f"\nDefault field set -> {explain_tier(DEFAULT_FIELDS)}")
        return 0

    fields = [f.strip() for f in args.fields.split(",")] if args.fields else list(DEFAULT_FIELDS)
    ttl = 0.0 if args.no_cache else 86400.0

    try:
        if args.cmd == "check":
            # 'id' alone is the cheapest possible mask: proves the key and the
            # API enablement without spending anything but an Essentials call.
            res = text_search("coffee", fields=["id"], max_results=1, cache_ttl=0)
            print(f"OK -- key works, Places API enabled ({len(res)} result).")
            return 0

        ceiling = {"essentials": ESSENTIALS, "pro": PRO, "enterprise": ENTERPRISE,
                   "atmosphere": ATMOSPHERE}[args.max_tier]
        tier, _ = tier_of(fields)
        if tier > ceiling:
            print(f"refusing: request is {explain_tier(fields)}", file=sys.stderr)
            print(f"  ceiling is --max-tier {args.max_tier}; raise it or drop fields.",
                  file=sys.stderr)
            return 2
        print(f"[{explain_tier(fields)}]", file=sys.stderr)

        if args.cmd == "search":
            bias = None
            if args.near:
                lat, lng, rad = (float(x) for x in args.near.split(","))
                bias = (lat, lng, rad)
            results = text_search(
                " ".join(args.query), fields=fields, max_results=args.max_results,
                bias=bias, cache_ttl=ttl,
            )
        elif args.cmd == "nearby":
            lat, lng = (float(x) for x in args.location.split(","))
            results = nearby_search(
                lat, lng, args.radius,
                included_types=[t.strip() for t in args.types.split(",")] if args.types else None,
                fields=fields, max_results=args.max_results, rank=args.rank, cache_ttl=ttl,
            )
        else:
            results = [details(args.place_id, fields=fields, cache_ttl=ttl or 604800)]
    except PlacesError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(results, indent=2))
    elif not results:
        print("no results")
    else:
        print("\n\n".join(_fmt(p) for p in results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
