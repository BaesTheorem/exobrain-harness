"""Retailer price lanes that work from this machine without a browser: Target, Walmart, Flipp.

Each lane returns plain dicts with the same core keys (retailer, id, url, title, price,
formatted) so `shop find` and `shop price` can print them in one table. Everything here
was measured live on 2026-10-05; the gotchas are in comments next to the code they guard.

Walled from here, do not burn time: Hy-Vee (Cloudflare 403), Kroger and Dillons (connection
refused), Instacart's /v3/ API (401), Lowe's, Bass Pro, DICK'S. Walmart's /store/finder and
Target's bare PDP HTML are JavaScript shells. Flipp is the only cross-store lane into KC grocery
pricing; the per-store grocery lanes (Whole Foods, Costco, Price Chopper, Cosentino's, Sun Fresh)
live in grocery.py.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from .common import LaneError, home_zip, session

# ------------------------------------------------------------------ Target (RedSky)

# Target's public web key, shipped in target.com's own JavaScript. Not a secret.
TARGET_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"
REDSKY = "https://redsky.target.com/redsky_aggregations/v1/web/"
# plp_search_v2 rejects a short visitor_id; 34 characters passes.
VISITOR = "0170000000000000000000000000000000"


_last_redsky = 0.0
REDSKY_SPACING = 2.0  # seconds between calls; see the 435 note below


def _redsky(s, path: str, **params) -> dict:
    global _last_redsky
    params.update(key=TARGET_KEY, channel="WEB", visitor_id=VISITOR)
    r = None
    for wait in (0, 5):
        gap = REDSKY_SPACING - (time.monotonic() - _last_redsky)
        time.sleep(max(gap, wait))
        _last_redsky = time.monotonic()
        r = s.get(REDSKY + path, params=params, timeout=25)
        if r.status_code != 435:
            break
    assert r is not None
    if r.status_code == 435:
        # 435 is a PerimeterX block of this IP for the WHOLE RedSky API, and it is
        # cheap to trip: about fifteen calls inside fifteen minutes did it on
        # 2026-10-05. Headless Chromium on target.com gets the same block, and the
        # page's server-rendered HTML carries no price, so there is no fallback
        # route. The block lifts by itself; retrying only extends it.
        raise LaneError("target: PerimeterX blocked this IP (HTTP 435) for every RedSky endpoint. "
                        "It lifts on its own in about an hour; do not retry sooner.")
    if r.status_code != 200:
        raise LaneError(f"target: HTTP {r.status_code} on {path}: {r.text[:160]}")
    return r.json()


def target_stores(limit: int = 4) -> list[dict]:
    """Target stores nearest the home ZIP. Store context changes the price, so always pass one."""
    d = _redsky(session(), "nearby_stores_v1", limit=limit, within=25, place=home_zip(), page="/sl/search")
    return [{"id": x["store_id"], "name": x["location_name"], "miles": x.get("distance")}
            for x in d["data"]["nearby_stores"]["stores"]]


def _target_row(p: dict) -> dict:
    pr = p.get("price") or {}
    item = p.get("item") or {}
    promos = [x.get("pdp_message") or x.get("plp_message") or x.get("subscription_type")
              for x in p.get("promotions") or []]
    return {
        "retailer": "Target",
        "id": p.get("tcin"),
        "url": (item.get("enrichment") or {}).get("buy_url") or f"https://www.target.com/p/-/A-{p.get('tcin')}",
        "title": (item.get("product_description") or {}).get("title", ""),
        "upc": item.get("primary_barcode"),
        "price": pr.get("current_retail"),
        "reg_price": pr.get("reg_retail"),
        "formatted": pr.get("formatted_current_price"),
        # The location that priced it. If this is not the store you asked for, the
        # item is online-only or the store has no price of its own.
        "price_location": pr.get("location_id"),
        "promotions": [x for x in promos if x],
    }


def target_search(query: str, n: int = 10, store: dict | None = None) -> list[dict]:
    store = store or target_stores(1)[0]
    d = _redsky(session(), "plp_search_v2", keyword=query, count=min(n, 24), offset=0,
                page=f"/s/{query}", platform="desktop",
                pricing_store_id=store["id"], store_ids=store["id"])
    rows = [_target_row(p) for p in d["data"]["search"].get("products", [])]
    for r in rows:
        r["store"] = store
    return rows


def _target_fulfillment(s, tcin: str, store: dict) -> dict | None:
    try:
        d = _redsky(s, "product_fulfillment_v1", tcin=tcin, store_id=store["id"], zip=home_zip(),
                    scheduled_delivery_store_id=store["id"], required_store_id=store["id"], is_bot="false")
    except LaneError:
        return None
    f = ((d.get("data") or {}).get("product") or {}).get("fulfillment") or {}
    opt = (f.get("store_options") or [{}])[0]
    return {
        "shipping": (f.get("shipping_options") or {}).get("availability_status"),
        "pickup": (opt.get("order_pickup") or {}).get("availability_status"),
        "in_store": (opt.get("in_store_only") or {}).get("availability_status"),
        "store_qty": opt.get("location_available_to_promise_quantity"),
        "store_name": opt.get("location_name"),
    }


def target_item(tcin: str, store: dict | None = None) -> dict:
    s = session()
    store = store or target_stores(1)[0]
    d = _redsky(s, "pdp_client_v1", tcin=tcin, store_id=store["id"], pricing_store_id=store["id"],
                has_pricing_store_id="true", page=f"/p/A-{tcin}")
    p = d["data"]["product"]
    row = _target_row(p)
    row["store"] = store
    row["variants"] = [{"id": v.get("tcin"), "name": f"{v.get('name')}: {v.get('value')}"}
                       for v in p.get("variation_hierarchy") or [] if v.get("tcin")]
    row["fulfillment"] = _target_fulfillment(s, tcin, store)
    return row


# ------------------------------------------------------------------ Walmart (__NEXT_DATA__)

WALMART_IP = "https://www.walmart.com/ip/{}"


def _next_data(html: str, where: str) -> dict:
    if "Robot or human" in html:
        raise LaneError(f"walmart: bot wall on {where}; wait a few minutes and retry")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise LaneError(f"walmart: no __NEXT_DATA__ on {where}; the page is not a product page")
    return json.loads(m.group(1))


def walmart_item(item_id: str) -> dict:
    r = session().get(WALMART_IP.format(item_id), timeout=30)
    p = _next_data(r.text, f"/ip/{item_id}")["props"]["pageProps"]["initialData"]["data"]["product"]
    pi = p.get("priceInfo") or {}
    cur = pi.get("currentPrice") or {}
    return {
        "retailer": "Walmart",
        "id": p.get("usItemId") or item_id,
        "url": WALMART_IP.format(p.get("usItemId") or item_id),
        "title": p.get("name", ""),
        "upc": p.get("upc"),
        "price": cur.get("price"),
        "formatted": cur.get("priceString"),
        "was": (pi.get("wasPrice") or {}).get("priceString"),
        "availability": p.get("availabilityStatus"),
        # Marketplace sellers post wild markups, so the seller is part of the price.
        "seller": p.get("sellerName"),
        "fulfillment": [{"type": f.get("type"), "status": f.get("availabilityStatus"),
                         "where": f.get("locationText")} for f in p.get("fulfillmentOptions") or []],
        "variants": len(p.get("variantsMap") or {}),
    }


def walmart_search(query: str, n: int = 10) -> list[dict]:
    r = session().get("https://www.walmart.com/search", params={"q": query}, timeout=30)
    d = _next_data(r.text, "/search")
    stacks = (((d["props"]["pageProps"].get("initialData") or {}).get("searchResult") or {}).get("itemStacks") or [])
    rows = []
    for st in stacks:
        for it in st.get("items", []):
            if it.get("__typename") != "Product" or not it.get("usItemId"):
                continue
            pi = it.get("priceInfo") or {}
            rows.append({
                "retailer": "Walmart",
                "id": it["usItemId"],
                "url": WALMART_IP.format(it["usItemId"]),
                "title": it.get("name", ""),
                # Search cards leave every priceInfo string empty; the number is the
                # top-level `price` field. Marketplace cards can lack even that.
                "price": _money(it.get("price")) or _money(pi.get("linePrice")),
                "formatted": pi.get("linePrice") or (f"${it['price']:.2f}" if isinstance(it.get("price"), (int, float)) and it.get("price") else None),
                "seller": it.get("sellerName"),
                "availability": (it.get("availabilityStatusV2") or {}).get("display"),
                "sponsored": bool(it.get("isSponsoredFlag")),
            })
            if len(rows) >= n:
                return rows
    return rows


def _money(s) -> float | None:
    if isinstance(s, (int, float)):
        return float(s)
    if not s:
        return None
    m = re.search(r"\d[\d,]*\.?\d*", str(s))
    return float(m.group(0).replace(",", "")) if m else None


# ------------------------------------------------------------------ Flipp (weekly ads)

FLIPP = "https://backflipp.wishabi.com/flipp/items/"


def flipp_search(query: str, n: int = 20) -> list[dict]:
    """Weekly-ad items near the home ZIP: Hy-Vee, Dillons, Price Chopper, ALDI, Dollar General, Costco."""
    d = session().get(FLIPP + "search", params={"locale": "en-us", "postal_code": home_zip(), "q": query},
                      timeout=25).json()
    rows = []
    for i in d.get("items", [])[:n]:
        rows.append({
            "retailer": i.get("merchant_name"),
            "id": str(i.get("id")),
            "url": f"https://flipp.com/item/{i.get('id')}",
            "title": i.get("name", ""),
            "price": _money(i.get("current_price")),
            "formatted": f"${i['current_price']}" if i.get("current_price") else i.get("price_text"),
            "valid_to": (i.get("valid_to") or "")[:10],
        })
    return rows


def flipp_item(item_id: str) -> dict:
    d = session().get(FLIPP + item_id, params={"postal_code": home_zip()}, timeout=25).json()
    i = d.get("item", d)
    return {
        # The detail carries the merchant as a bare string under "merchant"; merchant_name is null here.
        "retailer": i.get("merchant") if isinstance(i.get("merchant"), str) else i.get("merchant_name"),
        "id": item_id,
        "url": f"https://flipp.com/item/{item_id}",
        "title": i.get("name", ""),
        # `description` carries the SIZE ("28 oz."). It is what tells a 17 oz jar from a 10 oz one.
        "size": i.get("description"),
        "price": _money(i.get("current_price")),
        "formatted": f"${i['current_price']}" if i.get("current_price") else i.get("price_text"),
        "sale_story": i.get("sale_story"),
        "valid_from": (i.get("valid_from") or "")[:10],
        "valid_to": (i.get("valid_to") or "")[:10],
        "in_store_only": i.get("in_store_only"),
    }


# ------------------------------------------------------------------ dispatch

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def parse_target(spec: str) -> tuple[str, str]:
    """'<retailer>:<id>', a product URL, or a bare ASIN -> (lane, id)."""
    if ":" in spec and "//" not in spec:
        lane, _, ident = spec.partition(":")
        return lane.lower(), ident
    if "target.com" in spec and (m := re.search(r"/A-(\d+)", spec)):
        return "target", m.group(1)
    if "walmart.com" in spec and (m := re.search(r"/ip/(?:[^/]+/)?(\d+)", spec)):
        return "walmart", m.group(1)
    if "amazon." in spec and (m := re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", spec)):
        return "amazon", m.group(1)
    if "flipp.com" in spec and (m := re.search(r"/item/(\d+)", spec)):
        return "flipp", m.group(1)
    if "facebook.com" in spec and (m := re.search(r"/marketplace/item/(\d+)", spec)):
        return "fbm", m.group(1)
    if "ebay.com" in spec and (m := re.search(r"/itm/(?:[^/?]+/)?(\d{9,})", spec)):
        return "ebay", m.group(1)
    if ASIN_RE.match(spec):
        return "amazon", spec
    raise SystemExit(f"shop: cannot tell the retailer from {spec!r}; use target:<tcin>, walmart:<id>, flipp:<id>, "
                     "fbm:<listing id>, ebay:<item number>, an ASIN or a product URL")


def price(spec: str, all_variants: bool = False) -> list[dict]:
    lane, ident = parse_target(spec)
    if lane == "target":
        return [target_item(ident)]
    if lane == "walmart":
        return [walmart_item(ident)]
    if lane == "flipp":
        return [flipp_item(ident)]
    if lane == "fbm":
        from . import fbm
        return [fbm.item(ident)]
    if lane == "ebay":
        from . import ebay
        return [ebay.item(ident)]
    if lane == "amazon":
        from . import amazon
        return amazon.show_many([ident], all_variants=all_variants)
    raise SystemExit(f"shop: unknown lane {lane!r}")


SEARCH_LANES = ("target", "walmart", "flipp", "amazon")
# Used listings are a different market from new retail, so Marketplace joins `find` only on
# request (--at fbm), per the skill's "used only if Alex asks". `shop fbm` is its own command.
# eBay joins the default table once its keys are in .env, searching new condition only there.
OPTIONAL_LANES = ("fbm", "ebay")


def default_lanes() -> tuple[str, ...]:
    from . import ebay
    return SEARCH_LANES + (("ebay",) if ebay.have_keys() else ())


def find(query: str, lanes: tuple[str, ...] = SEARCH_LANES, n: int = 8) -> tuple[list[dict], dict[str, str]]:
    """Run the search lanes in parallel. Returns (rows, {lane: error}) so a dead lane is visible."""
    def one(lane: str) -> list[dict]:
        if lane == "target":
            return target_search(query, n)
        if lane == "walmart":
            return walmart_search(query, n)
        if lane == "flipp":
            return flipp_search(query, n)
        if lane == "amazon":
            from . import amazon
            return amazon.search(query, n)
        if lane == "fbm":
            from . import fbm
            return fbm.search(query, n)[0]
        if lane == "ebay":
            from . import ebay
            # `find` compares new retail; used eBay goes through `shop ebay --condition used`.
            return ebay.search(query, n, condition=["new"], sort="price")
        raise SystemExit(f"shop: unknown lane {lane!r}; choose from {', '.join(SEARCH_LANES + OPTIONAL_LANES)}")

    rows: list[dict] = []
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(lanes)) as ex:
        for lane, fut in [(ln, ex.submit(one, ln)) for ln in lanes]:
            try:
                got = fut.result()
            except (LaneError, SystemExit, KeyError, ValueError) as e:
                errors[lane] = str(e) or e.__class__.__name__
                continue
            if not got:
                # Zero rows is a fact about the query, not evidence the item is unsold there.
                errors[lane] = "0 rows (try a broader query before concluding it is not sold there)"
            rows.extend(got)
    return rows, errors
