"""Facebook Marketplace lane: local used listings, read-only, no browser.

Facebook has no public Marketplace API and the logged-out web is a hard login wall from
this IP (every anonymous GraphQL call answers "Rate limit exceeded", code 1675004, measured
2026-10-07). So this lane rides the session cookies the `facebook/` toolkit already keeps in
`facebook/secrets/cookies.txt` (refresh them with `facebook/bin/fb refresh-cookies`). It reads
that file as data only; it never imports the toolkit.

Two routes, both from one GET of the search page:

1. The search page HTML embeds the first 24 results and the request tokens (`fb_dtsg`, `lsd`,
   `jazoest`). URL filters (`minPrice`, `maxPrice`, `daysSinceListed`, `sortBy`, `itemCondition`)
   shape that embedded page. The location comes from the city slug plus the account's saved
   Marketplace location, so the radius is whatever the account has (3 km on 2026-10-07).
2. With the tokens, `CometMarketplaceSearchContentPaginationQuery` over `/api/graphql/` takes an
   explicit latitude, longitude and radius, plus price bounds in cents, and pages 24 at a time.
   This is the primary route. Its `doc_id` drifts when Facebook ships a new Relay bundle; the
   current one lives in `secrets/fbm-doc-id.txt` (or `FBM_DOC_ID`), and `refresh_doc_id()`
   captures a fresh one with a headless Playwright pass. When the query fails the lane falls
   back to route 1 and says so, so a stale id never reads as "nothing for sale".

Item pages embed the full listing under `viewer.marketplace_product_details_page.target`:
description, condition, photos, seller, pin location, shipping. Everything here is read-only:
no messages, no saves, no reactions.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .common import HARNESS, LaneError, ROOT, home_latlon, session

RETAILER = "FB Marketplace"
ITEM_URL = "https://www.facebook.com/marketplace/item/{}/"
SEARCH_URL = "https://www.facebook.com/marketplace/{city}/search"
GRAPHQL = "https://www.facebook.com/api/graphql/"
FRIENDLY = "CometMarketplaceSearchContentPaginationQuery"
# Captured 2026-10-07 from the live page. Overridden by secrets/fbm-doc-id.txt or FBM_DOC_ID.
DEFAULT_DOC_ID = "28383824837986211"
DOC_ID_FILE = ROOT / "secrets" / "fbm-doc-id.txt"
COOKIE_FILE = HARNESS / "facebook" / "secrets" / "cookies.txt"
PAGE = 24          # Facebook's own page size; larger counts are ignored
MAX_PAGES = 5
CONDITIONS = ("new", "used_like_new", "used_good", "used_fair")
SORTS = {"date": "creation_time_descend", "price": "price_ascend", "price_desc": "price_descend",
         "distance": "distance_ascend"}
BLOCKED_URL_BITS = ("/login", "checkpoint", "/authenticate", "/recover")


# ------------------------------------------------------------------ session


def cookie_path() -> Path:
    return Path(os.environ.get("FBM_COOKIES") or COOKIE_FILE)


def load_cookies(path: Path | None = None) -> dict[str, str]:
    """Netscape cookies.txt (what `fb refresh-cookies` writes) or a JSON list -> {name: value}."""
    p = path or cookie_path()
    if not p.exists():
        raise LaneError(f"fbm: no Facebook session at {p}. Run facebook/bin/fb refresh-cookies "
                        "(reads the live Chrome session; see facebook/README.md).")
    text = p.read_text()
    out: dict[str, str] = {}
    if text.lstrip().startswith("["):
        for c in json.loads(text):
            if "facebook.com" in c.get("domain", ""):
                out[c["name"]] = c["value"]
        return out
    for line in text.splitlines():
        if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        parts = line.removeprefix("#HttpOnly_").split("\t")
        if len(parts) >= 7 and "facebook.com" in parts[0]:
            out[parts[5]] = parts[6]
    if "c_user" not in out or "xs" not in out:
        raise LaneError(f"fbm: {p} has no c_user/xs cookies; the session is not logged in.")
    return out


def _session():
    s = session()
    for k, v in load_cookies().items():
        s.cookies.set(k, v, domain=".facebook.com")
    return s


def _get(s, url: str, **params) -> str:
    r = s.get(url, params=params or None, timeout=35)
    if any(b in r.url for b in BLOCKED_URL_BITS):
        raise LaneError("fbm: Facebook sent the request to a login or checkpoint page; the session "
                        "cookies are expired. Run facebook/bin/fb refresh-cookies.")
    if r.status_code != 200:
        raise LaneError(f"fbm: HTTP {r.status_code} on {url}")
    return r.text


# ------------------------------------------------------------------ page parsing

_TOKEN_RES = {
    "fb_dtsg": re.compile(r'"DTSGInitialData",\[\],\{"token":"([^"]+)"'),
    "lsd": re.compile(r'\["LSD",\[\],\{"token":"([^"]+)"'),
    "jazoest": re.compile(r"jazoest=(\d+)"),
}
_SCRIPT_RE = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)


def tokens(html: str) -> dict[str, str]:
    out = {}
    for k, rx in _TOKEN_RES.items():
        if m := rx.search(html):
            out[k] = m.group(1)
    if "fb_dtsg" not in out or "lsd" not in out:
        raise LaneError("fbm: the page carried no request tokens; Facebook changed the page or "
                        "served a logged-out shell.")
    return out


def blobs(html: str) -> list[Any]:
    """Every embedded JSON blob. Facebook ships page data as ~100 of these, all valid JSON."""
    out = []
    for m in _SCRIPT_RE.finditer(html):
        try:
            out.append(json.loads(m.group(1)))
        except ValueError:
            continue
    return out


def find_dicts(obj: Any, key: str) -> list[dict]:
    """Structural walk: every dict anywhere in `obj` that owns `key`. Field paths drift; keys do not."""
    hits: list[dict] = []
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if key in o:
                hits.append(o)
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return hits


# ------------------------------------------------------------------ rows


def _date(ts: Any) -> str | None:
    try:
        return dt.datetime.fromtimestamp(int(ts)).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _price(lp: dict | None) -> tuple[float | None, str | None]:
    lp = lp or {}
    amount = lp.get("amount")
    try:
        price = float(amount) if amount is not None else None
    except ValueError:
        price = None
    return price, lp.get("formatted_amount") or lp.get("formatted_amount_zeros_stripped")


def listing_row(listing: dict) -> dict:
    """A search-card listing -> the common row shape."""
    price, formatted = _price(listing.get("listing_price"))
    geo = (listing.get("location") or {}).get("reverse_geocode") or {}
    seller = listing.get("marketplace_listing_seller") or {}
    subs = [x.get("subtitle") for x in listing.get("custom_sub_titles_with_rendering_flags") or []]
    return {
        "retailer": RETAILER,
        "id": listing.get("id"),
        "url": ITEM_URL.format(listing.get("id")),
        "title": listing.get("marketplace_listing_title") or listing.get("custom_title") or "",
        "price": price,
        "formatted": formatted,
        "was": (listing.get("strikethrough_price") or {}).get("formatted_amount"),
        "city": geo.get("city"),
        "state": geo.get("state"),
        "listed": _date(listing.get("creation_time")),
        "seller": seller.get("name"),
        # IN_PERSON and/or SHIPPING. A shipped listing is not local pickup.
        "delivery": listing.get("delivery_types") or [],
        "sold": bool(listing.get("is_sold")),
        "pending": bool(listing.get("is_pending")),
        "subtitles": [x for x in subs if x],
        "photo": ((listing.get("primary_listing_photo") or {}).get("image") or {}).get("uri"),
    }


def _edges_rows(feed_units: dict) -> list[dict]:
    rows = []
    for e in feed_units.get("edges") or []:
        listing = (e.get("node") or {}).get("listing")
        # Ads and "people also searched" units have no listing; skip them, do not count them.
        if listing and listing.get("id"):
            rows.append(listing_row(listing))
    return rows


def embedded_search(html: str) -> tuple[list[dict], dict]:
    """The first page Facebook server-rendered into the search HTML, plus its page_info."""
    for b in blobs(html):
        for d in find_dicts(b, "marketplace_search"):
            fu = (d.get("marketplace_search") or {}).get("feed_units") or {}
            if "edges" in fu:
                return _edges_rows(fu), fu.get("page_info") or {}
    return [], {}


# ------------------------------------------------------------------ doc_id


def doc_id() -> str:
    v = os.environ.get("FBM_DOC_ID", "").strip()
    if not v and DOC_ID_FILE.exists():
        v = DOC_ID_FILE.read_text().strip()
    return v or DEFAULT_DOC_ID


def refresh_doc_id(headless: bool = True) -> str:
    """Capture the live doc_id for the pagination query with one headless, read-only page load.

    Playwright loads the search page with the session cookies, scrolls once so the page issues
    the pagination query, and we read doc_id off that request. Writes secrets/fbm-doc-id.txt.
    """
    from playwright.sync_api import sync_playwright

    from .common import ua

    found: list[str] = []
    cookies: list[Any] = [{"name": k, "value": v, "domain": ".facebook.com", "path": "/"}
                          for k, v in load_cookies().items()]
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless)
        ctx = b.new_context(user_agent=ua(), locale="en-US", viewport={"width": 1280, "height": 900})
        ctx.add_cookies(cookies)
        pg = ctx.new_page()

        def on_request(req):
            post = req.post_data or ""
            if "/api/graphql" in req.url and FRIENDLY in post and (m := re.search(r"doc_id=(\d+)", post)):
                found.append(m.group(1))

        pg.on("request", on_request)
        pg.goto(SEARCH_URL.format(city="kansascity") + "?query=bike", wait_until="domcontentloaded", timeout=45000)
        for _ in range(4):
            if found:
                break
            pg.mouse.wheel(0, 4000)
            pg.wait_for_timeout(2500)
        if any(bit in pg.url for bit in BLOCKED_URL_BITS):
            b.close()
            raise LaneError("fbm: login wall during doc_id refresh; run facebook/bin/fb refresh-cookies")
        b.close()
    if not found:
        raise LaneError("fbm: the page never issued the pagination query; Facebook renamed it. "
                        f"Look for the Marketplace search query in a capture and update FRIENDLY in {__file__}.")
    DOC_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOC_ID_FILE.write_text(found[0] + "\n")
    return found[0]


# ------------------------------------------------------------------ search


def _params(query: str, lat: float, lon: float, radius_km: int, min_price: float | None,
            max_price: float | None, days: int | None, condition: list[str] | None) -> dict:
    return {
        "bqf": {"callsite": "COMMERCE_MKTPLACE_WWW", "query": query},
        "browse_request_params": {
            "commerce_enable_local_pickup": True,
            "commerce_enable_shipping": True,
            "commerce_search_and_rp_available": True,
            "commerce_search_and_rp_category_id": [],
            "commerce_search_and_rp_condition": condition or None,
            "commerce_search_and_rp_ctime_days": days,
            "filter_location_latitude": lat,
            "filter_location_longitude": lon,
            # Price bounds are in cents.
            "filter_price_lower_bound": int(round((min_price or 0) * 100)),
            "filter_price_upper_bound": int(round(max_price * 100)) if max_price else 214748364700,
            "filter_radius_km": radius_km,
        },
        "custom_request_params": {
            "browse_context": None, "contextual_filters": [], "referral_code": None,
            "referral_ui_component": None, "saved_search_strid": None, "search_vertical": "C2C",
            "seo_url": None, "serp_landing_settings": {"virtual_category_id": ""},
            "surface": "SEARCH", "virtual_contextual_filters": [],
        },
    }


def _graphql_page(s, tok: dict[str, str], uid: str, params: dict, cursor: str | None, referer: str) -> dict:
    variables = {"count": PAGE, "cursor": cursor, "params": params, "scale": 2,
                 "__relay_internal__pv__GHLShouldChangeMarketplaceSponsoredDataFieldNamerelayprovider": True}
    data = {"av": uid, "__user": uid, "__a": "1", "__req": "1", "dpr": "2",
            "fb_dtsg": tok["fb_dtsg"], "lsd": tok["lsd"], "jazoest": tok.get("jazoest", ""),
            "fb_api_caller_class": "RelayModern", "fb_api_req_friendly_name": FRIENDLY,
            "variables": json.dumps(variables), "server_timestamps": "true", "doc_id": doc_id()}
    r = s.post(GRAPHQL, data=data, timeout=35, headers={
        "x-fb-lsd": tok["lsd"], "x-fb-friendly-name": FRIENDLY, "origin": "https://www.facebook.com",
        "referer": referer, "content-type": "application/x-www-form-urlencoded"})
    text = r.text.removeprefix("for (;;);")
    try:
        first = json.loads(text.split("\n", 1)[0])
    except ValueError:
        raise LaneError(f"fbm: graphql returned non-JSON (HTTP {r.status_code}): {text[:120]}") from None
    if first.get("errors") or not (first.get("data") or {}).get("marketplace_search"):
        msg = (first.get("errors") or [{}])[0].get("message", "no marketplace_search in reply")
        raise LaneError(f"fbm: graphql doc_id {doc_id()} rejected ({msg}); run `shop fbm --refresh-docid`")
    return first["data"]["marketplace_search"]["feed_units"]


def search(query: str, n: int = 24, radius_km: int = 40, min_price: float | None = None,
           max_price: float | None = None, days: int | None = None, condition: list[str] | None = None,
           sort: str = "date", exact: bool = False, city: str = "kansascity") -> tuple[list[dict], list[str]]:
    """Listings near home. Returns (rows, warnings); a warning names a degraded route, never silence."""
    lat, lon = home_latlon()
    for c in condition or []:
        if c not in CONDITIONS:
            raise LaneError(f"fbm: condition {c!r} is not one of {', '.join(CONDITIONS)}")
    if sort not in SORTS:
        raise LaneError(f"fbm: sort {sort!r} is not one of {', '.join(SORTS)}")
    url_filters = {"query": query, "exact": "true" if exact else "false", "sortBy": SORTS[sort]}
    if min_price is not None:
        url_filters["minPrice"] = str(int(min_price))
    if max_price is not None:
        url_filters["maxPrice"] = str(int(max_price))
    if days:
        url_filters["daysSinceListed"] = str(days)
    if condition:
        url_filters["itemCondition"] = ",".join(condition)
    s = _session()
    uid = s.cookies.get("c_user", domain=".facebook.com") or ""
    url = SEARCH_URL.format(city=city)
    html = _get(s, url, **url_filters)
    referer = f"{url}?{urlencode(url_filters)}"
    first_page, _ = embedded_search(html)
    warnings: list[str] = []
    rows: list[dict] = []
    try:
        tok = tokens(html)
        params = _params(query, lat, lon, radius_km, min_price, max_price, days, condition)
        cursor = None
        for _ in range(MAX_PAGES):
            fu = _graphql_page(s, tok, uid, params, cursor, referer)
            rows.extend(_edges_rows(fu))
            info = fu.get("page_info") or {}
            cursor = info.get("end_cursor")
            if len(rows) >= n or not info.get("has_next_page") or not cursor:
                break
    except LaneError as e:
        # Route 2 failed; the embedded page is still real data, just with the account's radius.
        warnings.append(f"{e} Showing the page's own first {len(first_page)} results instead "
                        "(account radius, not --radius).")
        rows = first_page
    seen: set[str] = set()
    out = []
    # Facebook's ctime_days filter is advisory: with days=7 it returned a 10-day-old listing
    # (2026-10-07), so the contract is enforced here on creation_time as well.
    floor = (dt.date.today() - dt.timedelta(days=days)).isoformat() if days else ""
    for r in rows:
        if r["id"] in seen or (r.get("listed") or "") < floor:
            continue
        seen.add(r["id"])
        out.append(r)
    if sort == "price":
        out.sort(key=lambda r: (r["price"] is None, r["price"] or 0))
    elif sort == "price_desc":
        out.sort(key=lambda r: -(r["price"] or 0))
    elif sort == "date":
        out.sort(key=lambda r: r.get("listed") or "", reverse=True)
    return out[:n], warnings


# ------------------------------------------------------------------ item


def item_row(target: dict) -> dict:
    """The product-details node -> a full row. Fields measured on a live page 2026-10-07."""
    row = listing_row(target)
    row["url"] = ITEM_URL.format(target.get("id"))
    row["description"] = ((target.get("redacted_description") or {}).get("text") or "").strip()
    attrs = {a.get("attribute_name"): a.get("label") or a.get("value") for a in target.get("attribute_data") or []}
    row["condition"] = attrs.get("Condition")
    row["attributes"] = {k: v for k, v in attrs.items() if k != "Condition"}
    row["location_text"] = (target.get("location_text") or {}).get("text")
    loc = target.get("location") or {}
    if "latitude" in loc:
        # The approximate pin Facebook shows buyers, not the seller's address.
        row["latlon"] = (loc.get("latitude"), loc.get("longitude"))
    row["photos"] = [((p.get("image") or {}).get("uri")) for p in target.get("listing_photos") or [] if p.get("image")]
    row["ships"] = bool(target.get("is_shipping_offered") or target.get("shipping_offered"))
    row["shipping_price"] = target.get("formatted_shipping_price")
    seller = target.get("marketplace_listing_seller") or {}
    stats = ((seller.get("marketplace_ratings_stats_by_role_v2") or {}).get("seller_stats") or {})
    row["seller_rating"] = stats.get("five_star_ratings_average")
    row["seller_rating_count"] = stats.get("five_star_total_rating_count_by_role")
    row["seller_joined"] = _date(seller.get("join_time")) if seller.get("join_time") else None
    row["live"] = bool(target.get("is_live"))
    return row


def item_target(html: str) -> dict:
    """The listing node, merged. Relay splits it across blobs (one carries only the photos,
    another the other ~120 fields), so every `target` on the page is folded into one dict."""
    merged: dict = {}
    for b in blobs(html):
        for d in find_dicts(b, "marketplace_product_details_page"):
            target = (d.get("marketplace_product_details_page") or {}).get("target")
            if isinstance(target, dict) and target.get("id"):
                merged.update({k: v for k, v in target.items() if v is not None or k not in merged})
    return merged


def item(listing_id: str) -> dict:
    target = item_target(_get(_session(), ITEM_URL.format(listing_id)))
    if not target:
        raise LaneError(f"fbm: no listing data on the page for {listing_id}; it is gone, or Facebook moved the node")
    return item_row(target)


LISTING_RE = re.compile(r"facebook\.com/marketplace/item/(\d+)")


def parse_url(spec: str) -> str | None:
    m = LISTING_RE.search(spec)
    return m.group(1) if m else None


def print_row(r: dict, full: bool = False) -> None:
    price = r.get("formatted") or (f"${r['price']:.2f}" if r.get("price") is not None else "-")
    flags = []
    if r.get("sold"):
        flags.append("SOLD")
    if r.get("pending"):
        flags.append("pending")
    if "SHIPPING" in (r.get("delivery") or []):
        flags.append("ships")
    where = ", ".join(x for x in (r.get("city"), r.get("state")) if x)
    print(f"{RETAILER:<14} {price:>9}  {r.get('id', ''):<17} {r.get('title', '')[:60]}  "
          f"{where}  {r.get('listed') or ''}  {' '.join(flags)}".rstrip())
    if not full:
        return
    print(f"  {r['url']}")
    for k in ("condition", "was", "location_text", "shipping_price", "seller_joined", "seller_rating"):
        if r.get(k) not in (None, "", 0):
            print(f"  {k}: {r[k]}")
    if r.get("attributes"):
        print(f"  attributes: {json.dumps(r['attributes'])}")
    if r.get("photos"):
        print(f"  photos: {len(r['photos'])}")
    if r.get("description"):
        print("  description:")
        for line in r["description"].splitlines():
            print(f"    {line}")
