"""Kansas City grocery lanes: store directory, shelf and online prices, weekly ads, coupons.

Browse only. Nothing here signs in, builds a cart or opens a browser; every lane is plain HTTP
plus, for the two image-only circulars, Apple Vision OCR (circular_ocr.py). Measured live on
2026-10-07; what each chain exposes decides the lane it gets:

- Whole Foods: `wholefoodsmarket.com/api/search` returns shelf prices for one store id, no key.
- Costco: `search.costco.com` typeahead (public x-api-key from the page) gives names and item
  numbers; the product page embeds a schema.org Offer with the ONLINE price. Warehouse prices
  are not published anywhere; the Flipp coupon book is the only in-warehouse signal.
- Price Chopper KC: full weekly ad on Flipp (merchant "Price Chopper KC"), ad highlights per
  store on mypricechopper.com, 50 stores with operators from the same site. Shelf prices live
  on an Instacart storefront that needs a session (README).
- Cosentino's Market: the weekly ad is a PDF in the site's Strapi `ads` collection (OCR'd);
  digital coupons come from Midax EZConnect. Both need public keys shipped in the site's JS
  bundle; they are scraped from the live bundle and cached, never hardcoded, so a rotation
  heals itself on the next run.
- Sun Fresh: Freshop has the stores and the circular PDF but an empty catalog (0 products for
  every store while another Freshop banner returns priced rows), so the lane is the OCR'd ad.
- ALDI, Hy-Vee, Dillons, Sprouts, Walmart, Target, Sam's Club: Flipp flyer items, free.
- Midtown Market, United Market KC, Hen House: directory only (no price surface found).

Rows share the shop core keys (retailer, id, url, title, price, formatted) plus `kind`
("shelf", "online", "ad", "coupon"), `size`, `valid_from`/`valid_to`, `store` and `page`.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import circular_ocr
from .common import ROOT, LaneError, home_latlon, home_zip, session

DATA_FILE = Path(__file__).with_name("grocery_stores.json")
DATA = json.loads(DATA_FILE.read_text())
CACHE = ROOT / ".cache"

SEARCH_LANES = ("wholefoods", "costco", "pricechopper", "cosentinos", "sunfresh")
FLIPP_MERCHANTS = {
    "pricechopper": "Price Chopper KC", "costco": "Costco", "aldi": "ALDI", "hyvee": "Hy-Vee", "dillons": "Dillons",
    "sprouts": "Sprouts Farmers Market", "walmart": "Walmart", "target": "Target", "samsclub": "Sam's Club",
}
ALIASES = {"pc": "pricechopper", "price-chopper": "pricechopper", "cosentino": "cosentinos", "cosentino's": "cosentinos",
           "sun-fresh": "sunfresh", "wf": "wholefoods", "whole-foods": "wholefoods", "hy-vee": "hyvee", "sams": "samsclub"}
AD_STORES = tuple(FLIPP_MERCHANTS) + ("cosentinos", "sunfresh")
COUPON_STORES = ("cosentinos",)


def canon(store: str) -> str:
    s = store.strip().lower()
    return ALIASES.get(s, s)


def miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return round(2 * 3958.8 * math.asin(math.sqrt(h)), 1)


def _today() -> str:
    return dt.date.today().isoformat()


def matches(row: dict, query: str | None) -> bool:
    """Every query word appears in the row's title, size or description (case-insensitive)."""
    if not query:
        return True
    hay = " ".join(str(row.get(k) or "") for k in ("title", "size", "description", "brand")).lower()
    return all(w in hay for w in query.lower().split())


def grep(rows: list[dict], query: str | None) -> list[dict]:
    return [r for r in rows if matches(r, query)]


# ------------------------------------------------------------------ Flipp flyers (full weekly ads)

FLIPP = "https://backflipp.wishabi.com/flipp/"


def flipp_flyers(merchant: str) -> list[dict]:
    """Flyers available at HOME_ZIP for one merchant name (Flipp pads some names with spaces)."""
    d = session().get(FLIPP + "flyers", params={"postal_code": home_zip(), "locale": "en-us"}, timeout=30).json()
    flyers = d.get("flyers", d) if isinstance(d, dict) else d
    want = merchant.strip().lower()
    return [f for f in flyers if (f.get("merchant") or "").strip().lower() == want]


def flipp_flyer_items(flyer: dict) -> list[dict]:
    d = session().get(FLIPP + f"flyers/{flyer['id']}", params={"locale": "en-us"}, timeout=40).json()
    merchant = (flyer.get("merchant") or "").strip()
    rows = []
    for i in d.get("items", []):
        name = (i.get("name") or "").strip()
        # Costco's coupon book carries unnamed slots whose "name" is an internal code (CSTUG...).
        if not name or re.fullmatch(r"[A-Z]{3,6}\d{8,}", name):
            continue
        price = _money(i.get("price"))
        rows.append({
            "retailer": merchant, "id": str(i["id"]), "url": f"https://flipp.com/item/{i['id']}", "kind": "ad",
            "title": name, "brand": i.get("brand"), "price": price,
            "formatted": f"${price:.2f}" if price is not None else None,
            "discount": i.get("discount"), "flyer": flyer.get("name"),
            "valid_from": (i.get("valid_from") or flyer.get("valid_from") or "")[:10],
            "valid_to": (i.get("valid_to") or flyer.get("valid_to") or "")[:10],
        })
    return rows


def flyer_rows(store: str, query: str | None = None, current_only: bool = False) -> list[dict]:
    merchant = FLIPP_MERCHANTS[store]
    flyers = flipp_flyers(merchant)
    if current_only:
        today = _today()
        flyers = [f for f in flyers if (f.get("valid_from") or "")[:10] <= today <= (f.get("valid_to") or "9")[:10]]
    if not flyers:
        raise LaneError(f"{store}: no {merchant!r} flyer on Flipp for {home_zip()} right now")
    rows: list[dict] = []
    seen: set[str] = set()
    for f in flyers:
        for r in flipp_flyer_items(f):
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)
    return grep(rows, query)


def _money(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v) if v else None
    if not v:
        return None
    m = re.search(r"\d[\d,]*\.?\d*", str(v))
    return float(m.group(0).replace(",", "")) if m else None


# ------------------------------------------------------------------ Price Chopper KC

PC = "https://www.mypricechopper.com/public/"


def pricechopper_stores() -> list[dict]:
    d = session().get(PC + "stores", timeout=30).json()
    out = []
    for s in d.get("data", []):
        if not s.get("Active", True):
            continue
        out.append({"chain": "pricechopper", "id": str(s["StoreId"]), "name": f"Price Chopper {s.get('Landmark') or s.get('Address1')}",
                    "operator": s.get("OwnerGroup"), "address": (s.get("Address1") or "").title(), "city": (s.get("City") or "").title(),
                    "state": s.get("State"), "zip": s.get("Zip"), "lat": s.get("Latitude"), "lon": s.get("Longitude"),
                    "hours_today": s.get("StoreHoursForToday"), "phone": s.get("Phone")})
    return out


def pricechopper_highlights(store_id: str) -> list[dict]:
    """Front-page ad groups for one store: the featured deals, not the whole ad."""
    d = session().get(PC + f"FrontPageAdGroupsForPreferredStore/{store_id}", timeout=30).json()
    rows = []
    for g in (d.get("data") or {}).get("AdGroups", []):
        price = _money(g.get("AdPriceOnly"))
        cents = g.get("AdPriceCents")
        if price is not None and cents and "/" not in (g.get("AdPricePrefix") or ""):
            price = float(f"{int(price)}.{cents}")
        elif price is not None and (m := re.match(r"(\d+)/", g.get("AdPricePrefix") or "")):
            price = round(float(g["AdPrice"].split("$")[-1]) / int(m.group(1)), 3)
        rows.append({"retailer": "Price Chopper KC", "id": str(g.get("AdGroupId")), "kind": "ad",
                     "url": "https://www.mypricechopper.com/", "title": g.get("Title", ""),
                     "description": g.get("Description"), "size": g.get("Size") or None, "price": price,
                     "formatted": (g.get("AdPrice") or "") + (f"/{g['AdPriceUOM']}" if g.get("AdPriceUOM") else ""),
                     "department": g.get("Department"), "store": {"id": store_id}})
    return rows


# ------------------------------------------------------------------ Whole Foods

WF_SEARCH = "https://www.wholefoodsmarket.com/api/search"


def wholefoods_store() -> dict:
    return next(s for s in DATA["stores"] if s["chain"] == "wholefoods")


def wholefoods_search(query: str, n: int = 8, store_id: str | None = None) -> list[dict]:
    store = wholefoods_store()
    sid = store_id or store["ids"]["store"]
    r = session().get(WF_SEARCH, params={"text": query, "store": sid, "limit": min(n, 60), "offset": 0}, timeout=30)
    if r.status_code != 200:
        raise LaneError(f"wholefoods: HTTP {r.status_code} on /api/search")
    rows = []
    for p in r.json().get("results", []):
        sale, reg = p.get("salePrice"), p.get("regularPrice")
        price = sale if sale is not None else reg
        rows.append({"retailer": "Whole Foods", "id": p.get("slug"), "kind": "shelf",
                     "url": f"https://www.wholefoodsmarket.com/product/{p.get('slug')}",
                     "title": f"{p.get('brand') or ''} {p.get('name') or ''}".strip(), "brand": p.get("brand"),
                     "price": price, "formatted": f"${price:.2f}" if price is not None else None,
                     "reg_price": reg if sale is not None else None, "local": bool(p.get("isLocal")),
                     "store": {"id": sid, "name": store["name"]}})
    return rows


# ------------------------------------------------------------------ Costco

COSTCO_LOCATOR = "https://www.costco.com/AjaxWarehouseBrowseLookupView"
COSTCO_TYPEAHEAD = "https://search.costco.com/api/apps/www_costco_com/query/www_costco_com_typeahead"
COSTCO_PDP = "https://www.costco.com/.product.{}.html"
_KEY_CACHE = CACHE / "costco-keys.json"


def costco_warehouses(n: int = 6) -> list[dict]:
    lat, lon = home_latlon()
    params = {"langId": "-1", "storeId": "10301", "numOfWarehouses": str(n), "hasGas": "false", "hasTires": "false",
              "hasFood": "false", "hasHearing": "false", "hasPharmacy": "false", "hasOptical": "false", "hasBusiness": "false",
              "hasPhotoCenter": "", "tiresCheckout": "0", "isTransferWarehouse": "false", "populateWarehouseDetails": "true",
              "warehousePickupCheckout": "false", "countryCode": "US", "latitude": str(lat), "longitude": str(lon)}
    r = session().get(COSTCO_LOCATOR, params=params, timeout=30)
    if r.status_code != 200:
        raise LaneError(f"costco: HTTP {r.status_code} from the warehouse locator")
    out = []
    for w in r.json():
        if not isinstance(w, dict):
            continue
        out.append({"chain": "costco", "id": str(w.get("stlocID")), "name": f"Costco {w.get('locationName')} #{w.get('stlocID')}",
                    "address": (w.get("address1") or "").title(), "city": (w.get("city") or "").title(), "state": w.get("state"),
                    "zip": (w.get("zipCode") or "")[:5], "lat": w.get("latitude"), "lon": w.get("longitude"),
                    "miles": round(float(w["distance"]), 1) if w.get("distance") is not None else None})
    return out


def costco_keys(refresh: bool = False) -> dict:
    """Public typeahead x-api-key, read from costco.com's own search page and cached."""
    if not refresh and _KEY_CACHE.exists():
        return json.loads(_KEY_CACHE.read_text())
    r = session().get("https://www.costco.com/s", params={"dept": "All", "keyword": "milk"}, timeout=40)
    m = re.search(r'www_costco_com_typeahead\\?"[^}]{0,200}?x-api-key\\?":\\?"([0-9a-f-]{36})', r.text)
    if not m:
        raise LaneError("costco: could not find the typeahead x-api-key in the search page; the page layout changed")
    keys = {"typeahead_key": m.group(1), "fetched": _today()}
    CACHE.mkdir(parents=True, exist_ok=True)
    _KEY_CACHE.write_text(json.dumps(keys))
    return keys


def costco_typeahead(query: str, n: int = 8) -> list[dict]:
    keys = costco_keys()
    h = {"x-api-key": keys["typeahead_key"], "Origin": "https://www.costco.com", "Referer": "https://www.costco.com/"}
    r = session().get(COSTCO_TYPEAHEAD, params={"q": query, "rowsPerGroup": min(n, 20)}, headers=h, timeout=30)
    if r.status_code in (401, 403):
        keys = costco_keys(refresh=True)
        h["x-api-key"] = keys["typeahead_key"]
        r = session().get(COSTCO_TYPEAHEAD, params={"q": query, "rowsPerGroup": min(n, 20)}, headers=h, timeout=30)
    if r.status_code != 200:
        raise LaneError(f"costco: HTTP {r.status_code} from the typeahead")
    return [d for d in r.json().get("response", {}).get("docs", []) if d.get("item_number")][:n]


def parse_costco_offer(html: str) -> dict:
    """The schema.org Product/Offer costco.com embeds (escaped) in its product page."""
    t = html.replace('\\"', '"')
    out: dict = {}
    if m := re.search(r'"@type":"Product","name":"([^"]+)"', t):
        out["name"] = m.group(1)
    if m := re.search(r'"@type":"Offer".{0,300}?"price":([0-9.]+)', t):
        out["price"] = float(m.group(1))
    if m := re.search(r'"@type":"Offer".{0,300}?"availability":"https://schema\.org/(\w+)"', t):
        out["availability"] = m.group(1)
    if m := re.search(r'"@type":"Product".{0,600}?"url":"(https://www\.costco\.com/p/[^"]+)"', t):
        out["url"] = m.group(1)
    return out


def costco_online_price(item_number: str) -> dict:
    r = session().get(COSTCO_PDP.format(item_number), timeout=40)
    if r.status_code == 404:
        return {}
    return parse_costco_offer(r.text)


def costco_row(doc: dict, offer: dict) -> dict:
    price = offer.get("price")
    return {"retailer": "Costco.com", "id": doc["item_number"], "kind": "online",
            "url": offer.get("url") or COSTCO_PDP.format(doc["item_number"]),
            "title": offer.get("name") or doc.get("term") or doc.get("label", ""), "brand": doc.get("Brand_attr"),
            "price": price, "formatted": f"${price:.2f}" if price is not None else None,
            # The page's schema.org availability says OutOfStock for everything (Bounty paper towels
            # included, measured 2026-10-07) without a delivery ZIP context, so it is not reported.
            "note": "online price; the warehouse price is not published and is usually lower"}


def costco_search(query: str, n: int = 5) -> list[dict]:
    """Typeahead names, then each product page's online price (about 1 s a page, 3 in parallel)."""
    docs = costco_typeahead(query, n)
    with ThreadPoolExecutor(max_workers=3) as ex:
        offers = list(ex.map(lambda d: costco_online_price(d["item_number"]), docs))
    return [costco_row(d, o) for d, o in zip(docs, offers, strict=True)]


# ------------------------------------------------------------------ Cosentino's Market

COS_SITE = "https://www.cosentinosmarket.com"
COS_STRAPI = "https://bagr.iprosystems.com/api"
_COS_KEYS = CACHE / "cosentinos-keys.json"


def scrape_cosentinos_keys(index_html: str, bundle_js: str) -> dict:
    """The public EZConnect x-api-key and Strapi bearer token, as shipped in the site's JS."""
    out: dict = {}
    if m := re.search(r'"x-api-key":([A-Za-z0-9_$]+)\}', bundle_js):
        var = m.group(1)
        if m2 := re.search(re.escape(var) + r'="([A-Za-z0-9]{20,})"', bundle_js):
            out["ezconnect_key"] = m2.group(1)
    if m := re.search(r'"(https://[a-z0-9]+\.execute-api\.[a-z0-9-]+\.amazonaws\.com/prod/ezconnect/v1)"', bundle_js):
        out["ezconnect_base"] = m.group(1)
    if m := re.search(r'"https://bagr\.iprosystems\.com/api",[A-Za-z0-9_$]+="([0-9a-f]{100,})"', bundle_js):
        out["strapi_token"] = m.group(1)
    if m := re.search(r'src="(/assets/index-[^"]+\.js)"', index_html):
        out["bundle"] = m.group(1)
    if "ezconnect_key" not in out or "strapi_token" not in out:
        raise LaneError("cosentinos: the site's JS bundle no longer carries the EZConnect key or Strapi token where expected")
    return out


def cosentinos_keys(refresh: bool = False) -> dict:
    if not refresh and _COS_KEYS.exists():
        return json.loads(_COS_KEYS.read_text())
    s = session()
    index = s.get(COS_SITE + "/", timeout=30).text
    m = re.search(r'src="(/assets/index-[^"]+\.js)"', index)
    if not m:
        raise LaneError("cosentinos: no Vite bundle on the home page; the site changed")
    bundle = s.get(COS_SITE + m.group(1), timeout=60).text
    keys = scrape_cosentinos_keys(index, bundle)
    keys["fetched"] = _today()
    CACHE.mkdir(parents=True, exist_ok=True)
    _COS_KEYS.write_text(json.dumps(keys))
    return keys


def _strapi(path: str, **params) -> dict:
    keys = cosentinos_keys()
    params.setdefault("filters[site][SiteID][$eq]", "cosentinosmarket")
    for attempt in (0, 1):
        r = session().get(f"{COS_STRAPI}/{path}", params=params, headers={"Authorization": "Bearer " + keys["strapi_token"]}, timeout=30)
        if r.status_code in (401, 403) and attempt == 0:
            keys = cosentinos_keys(refresh=True)
            continue
        if r.status_code != 200:
            raise LaneError(f"cosentinos: Strapi HTTP {r.status_code} on /{path}")
        return r.json()
    raise LaneError("cosentinos: Strapi rejected the bundle token twice")


def cosentinos_locations() -> list[dict]:
    d = _strapi("locations", populate="*")
    out = []
    for loc in d.get("data", []):
        a = loc.get("attributes", loc)
        ad = a.get("LocationAddress") or {}
        out.append({"chain": "cosentinos", "id": str(a.get("LocationCouponID") or a.get("documentId")),
                    "name": f"{a.get('LocationBanner')} {a.get('LocationTitle')}", "address": ad.get("LocationAddressLineOne"),
                    "city": ad.get("LocationAddressCity"), "state": ad.get("LocationAddressState"), "zip": ad.get("LocationAddressZipCode"),
                    "lat": ad.get("LocationAddressLatitude"), "lon": ad.get("LocationAddressLongitude"),
                    "phone": a.get("LocationPhoneNumber"), "coupon_location": a.get("LocationCouponID")})
    return out


def cosentinos_ads() -> list[dict]:
    """Weekly ad PDFs (current and upcoming) from the Strapi `ads` collection."""
    d = _strapi("ads", populate="*", **{"sort": "AdStartDate:desc", "pagination[pageSize]": 6})
    out = []
    for ad in d.get("data", []):
        a = ad.get("attributes", ad)
        url = ((a.get("AdFile") or {}).get("url")) or ""
        if url:
            out.append({"title": a.get("AdTitle"), "start": a.get("AdStartDate"), "end": a.get("AdEndDate"), "url": url,
                        "type": (a.get("ad_type") or {}).get("AdType")})
    return out


def cosentinos_ad_rows(query: str | None = None, upcoming: bool = False) -> tuple[list[dict], dict]:
    ads = cosentinos_ads()
    today = _today()
    current = [a for a in ads if (a["start"] or "") <= today <= (a["end"] or "9")]
    future = [a for a in ads if (a["start"] or "") > today]
    pick = (future[-1] if future else None) if upcoming else (current[0] if current else None)
    if not pick:
        raise LaneError("cosentinos: no " + ("upcoming" if upcoming else "current") + " weekly ad in Strapi")
    rows = circular_ocr.circular_rows(pick["url"], "Cosentino's Market", pick["start"] or "", pick["end"] or "")
    return grep(rows, query), pick


def cosentinos_coupons(query: str | None = None, location_id: str | None = None, n: int = 60) -> list[dict]:
    keys = cosentinos_keys()
    loc = location_id or DATA["chains"]["cosentinos"]["default_coupon_location"]
    base = keys.get("ezconnect_base", "https://u9051n7iej.execute-api.us-east-1.amazonaws.com/prod/ezconnect/v1")
    h = {"x-api-key": keys["ezconnect_key"], "Origin": COS_SITE, "Referer": COS_SITE + "/"}
    if query:
        path, params = "/search-offers", {"offset": 0, "limit": n, "location_id": loc, "subtitle": query}
    else:
        path, params = "/offers", {"offset": 0, "limit": n, "location_id": loc, "sort_by": "newest"}
    for attempt in (0, 1):
        r = session().get(base + path, params=params, headers=h, timeout=30)
        if r.status_code in (401, 403) and attempt == 0:
            keys = cosentinos_keys(refresh=True)
            h["x-api-key"] = keys["ezconnect_key"]
            continue
        break
    if r.status_code != 200:
        raise LaneError(f"cosentinos: EZConnect HTTP {r.status_code}: {r.text[:120]}")
    rows = [coupon_row(o, loc) for o in r.json().get("items", [])]
    # search-offers matches the product line only; a description-only hit is still a hit.
    return rows if query else grep(rows, None)


def coupon_row(o: dict, location_id: str) -> dict:
    return {"retailer": "Cosentino's Market", "id": str(o.get("id")), "kind": "coupon",
            "url": COS_SITE + "/coupons", "title": f"{o.get('subtitle') or ''}: {o.get('description') or ''}".strip(": "),
            "price": None, "formatted": o.get("title"), "value": o.get("value"), "category": o.get("category"),
            "valid_to": (o.get("to_date") or "")[:10], "store": {"id": location_id}}


# ------------------------------------------------------------------ Sun Fresh

FRESHOP = "https://api.freshop.ncrcloud.com/1/"


def sunfresh_stores() -> list[dict]:
    key = DATA["chains"]["sunfresh"]["freshop_app_key"]
    d = session().get(FRESHOP + "stores", params={"app_key": key}, timeout=30).json()
    out = []
    for s in d.get("items", []):
        if not s.get("latitude") or not s.get("address_1"):
            continue  # "Sun Fresh" and "Global" are placeholder records without an address
        out.append({"chain": "sunfresh", "id": str(s["id"]), "name": f"Sun Fresh {s.get('name')}", "address": s.get("address_1"),
                    "city": s.get("city"), "state": s.get("state") or "MO", "zip": s.get("postal_code"),
                    "lat": float(s["latitude"]), "lon": float(s["longitude"]), "phone": s.get("phone")})
    return out


def sunfresh_circular(store_id: str) -> dict:
    key = DATA["chains"]["sunfresh"]["freshop_app_key"]
    d = session().get(FRESHOP + "circulars", params={"app_key": key, "store_id": store_id}, timeout=30).json()
    items = d.get("items", [])
    if not items or not items[0].get("pdf_url"):
        raise LaneError(f"sunfresh: Freshop has no circular PDF for store {store_id}")
    return items[0]


def nearest(stores: list[dict], lat: float, lon: float) -> dict:
    return min((s for s in stores if s.get("lat") is not None), key=lambda s: miles(lat, lon, s["lat"], s["lon"]))


def sunfresh_ad_rows(query: str | None = None, store_id: str | None = None) -> tuple[list[dict], dict]:
    if store_id:
        store = {"id": store_id, "name": f"Sun Fresh store {store_id}"}
    else:
        lat, lon = home_latlon()
        store = nearest(sunfresh_stores(), lat, lon)
    c = sunfresh_circular(store["id"])
    rows = circular_ocr.circular_rows(c["pdf_url"], "Sun Fresh", c.get("display_start_date", ""), c.get("display_finish_date", ""))
    for r in rows:
        r["store"] = {"id": store["id"], "name": store["name"]}
    meta = {"title": c.get("name"), "start": c.get("display_start_date"), "end": c.get("display_finish_date"),
            "url": c["pdf_url"], "pages": c.get("total_pages"), "store": store["name"]}
    return grep(rows, query), meta


# ------------------------------------------------------------------ directory


def geocode_zip(zip_code: str) -> tuple[float, float]:
    """ZIP centroid from Nominatim (no key; one call, User-Agent required)."""
    r = session().get("https://nominatim.openstreetmap.org/search",
                      params={"postalcode": zip_code, "country": "US", "format": "json", "limit": 1},
                      headers={"User-Agent": "exobrain-harness shop grocery"}, timeout=20)
    hits = r.json() if r.status_code == 200 else []
    if not hits:
        raise LaneError(f"grocery: could not geocode ZIP {zip_code}")
    return float(hits[0]["lat"]), float(hits[0]["lon"])


def directory(near: str | None = None) -> tuple[list[dict], dict[str, str]]:
    """Every known store with distance, lanes and status. Live chain lists merge with the data file."""
    if near and re.fullmatch(r"\d{5}", near):
        lat, lon = geocode_zip(near)
    elif near:
        lat, lon = (float(x) for x in near.split(","))
    else:
        lat, lon = home_latlon()
    stores: list[dict] = [dict(s) for s in DATA["stores"]]
    errors: dict[str, str] = {}
    live = {"pricechopper": pricechopper_stores, "sunfresh": sunfresh_stores, "cosentinos": cosentinos_locations,
            "costco": lambda: costco_warehouses(6)}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for chain, fut in [(c, ex.submit(fn)) for c, fn in live.items()]:
            try:
                stores.extend(fut.result())
            except (LaneError, KeyError, ValueError, TypeError) as e:
                errors[chain] = str(e) or e.__class__.__name__
    fixes = DATA.get("coordinate_overrides", {})
    for s in stores:
        chain = DATA["chains"].get(s["chain"], {})
        if (fix := fixes.get(f"{s['chain']}:{s.get('id')}")):
            s["lat"], s["lon"], s["coords_note"] = fix[0], fix[1], fix[2]
        s.setdefault("status", "open")
        s["chain_name"] = chain.get("name", s["chain"])
        s["lanes"] = chain.get("lanes", [])
        if s.get("lat") is not None and s.get("lon") is not None:
            s["miles"] = miles(lat, lon, float(s["lat"]), float(s["lon"]))
    stores.sort(key=lambda s: (s.get("miles") is None, s.get("miles") or 0))
    return stores, errors


# ------------------------------------------------------------------ dispatch


def search(query: str, lanes: tuple[str, ...] = SEARCH_LANES, n: int = 8) -> tuple[list[dict], dict[str, str]]:
    """Run the grocery lanes in parallel. Returns (rows, {lane: error}) like lanes.find."""
    def one(lane: str) -> list[dict]:
        lane = canon(lane)
        if lane == "wholefoods":
            return wholefoods_search(query, n)
        if lane == "costco":
            return costco_search(query, min(n, 8))
        if lane == "pricechopper":
            try:
                return flyer_rows("pricechopper", query, current_only=True)[:n]
            except LaneError:
                lat, lon = home_latlon()
                return grep(pricechopper_highlights(nearest(pricechopper_stores(), lat, lon)["id"]), query)[:n]
        if lane == "cosentinos":
            rows = cosentinos_coupons(query)[:n]
            try:
                rows += cosentinos_ad_rows(query)[0][:n]
            except LaneError as e:
                if not rows:
                    raise
                rows.append({"retailer": "Cosentino's Market", "id": "ad", "kind": "ad", "title": f"(weekly ad unavailable: {e})",
                             "price": None, "formatted": None, "url": COS_SITE})
            return rows
        if lane == "sunfresh":
            return sunfresh_ad_rows(query)[0][:n]
        if lane in FLIPP_MERCHANTS:
            return flyer_rows(lane, query, current_only=True)[:n]
        raise LaneError(f"unknown grocery lane {lane!r}; choose from {', '.join(dict.fromkeys(SEARCH_LANES + tuple(FLIPP_MERCHANTS)))}")

    rows: list[dict] = []
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(lanes)) as ex:
        for lane, fut in [(ln, ex.submit(one, ln)) for ln in lanes]:
            try:
                got = fut.result()
            except (LaneError, KeyError, ValueError, TypeError) as e:
                errors[lane] = str(e) or e.__class__.__name__
                continue
            if not got:
                errors[lane] = "0 rows (try a broader query before concluding it is not sold there)"
            rows.extend(got)
    return rows, errors


def ad(store: str, query: str | None = None, upcoming: bool = False, store_id: str | None = None) -> tuple[list[dict], dict]:
    store = canon(store)
    if store == "cosentinos":
        return cosentinos_ad_rows(query, upcoming=upcoming)
    if store == "sunfresh":
        return sunfresh_ad_rows(query, store_id=store_id)
    if store in FLIPP_MERCHANTS:
        rows = flyer_rows(store, query)
        flyers = sorted({(r.get("flyer"), r["valid_from"], r["valid_to"]) for r in rows})
        meta = {"title": "; ".join(f"{f[0]} ({f[1]} to {f[2]})" for f in flyers), "url": "https://flipp.com/", "source": "Flipp"}
        if store == "pricechopper" and store_id:
            rows = grep(pricechopper_highlights(store_id), query) + rows
        return rows, meta
    raise LaneError(f"no weekly-ad lane for {store!r}; choose from {', '.join(AD_STORES)}")


def coupons(store: str, query: str | None = None, location_id: str | None = None) -> list[dict]:
    store = canon(store)
    if store == "cosentinos":
        return cosentinos_coupons(query, location_id)
    raise LaneError(f"no digital-coupon lane for {store!r}; only {', '.join(COUPON_STORES)} so far (Price Chopper's "
                    "coupons sit behind a member sign-in)")


# ------------------------------------------------------------------ printing


def fmt_row(r: dict) -> str:
    price = r.get("formatted") or (f"${r['price']:.2f}" if r.get("price") is not None else "-")
    if r.get("unit") and r["unit"] not in price:
        price += f"/{r['unit']}"
    extra = ""
    if r.get("size"):
        extra += f"  {r['size']}"
    if r.get("reg_price"):
        extra += f"  (reg ${r['reg_price']:.2f})"
    if r.get("availability") and r["availability"] != "InStock":
        extra += f"  {r['availability']}"
    if r.get("valid_to"):
        today = _today()
        extra += f"  from {r['valid_from']}" if (r.get("valid_from") or "") > today else f"  thru {r['valid_to']}"
    if r.get("page"):
        extra += f"  p{r['page']}"
    kind = r.get("kind") or ""
    return f"{(r.get('retailer') or '?')[:18]:<18} {kind:<6} {price:>10}  {(r.get('title') or '')[:64]}{extra}"


def fmt_store(s: dict) -> str:
    d = f"{s['miles']:>5.1f} mi" if s.get("miles") is not None else "   ?  mi"
    addr = ", ".join(x for x in (s.get("address"), s.get("city")) if x)
    lanes = ",".join(s.get("lanes") or []) or "-"
    tail = f"  [{s['status']}]" if s.get("status") != "open" else ""
    op = f" ({s['operator']})" if s.get("operator") else ""
    return f"{d}  {(s.get('name') or '')[:38]:<38}{op:<12} {addr[:40]:<40} lanes: {lanes}{tail}"
