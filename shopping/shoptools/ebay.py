"""eBay lane: active listings over the official Browse API, sold prices over a hosted Apify actor.

Active listings (`search`, `item`) use eBay's Browse API with an application token
(OAuth client credentials from EBAY_CLIENT_ID / EBAY_CLIENT_SECRET in the harness .env, a
free keyset from developer.ebay.com/my/keys). The token lasts about two hours and is cached in
secrets/ebay-token.json. X-EBAY-C-ENDUSERCTX carries the home ZIP so shipping costs are
quoted to home, and `--local` adds a pickup-radius filter.

Sold prices (`sold`) are walled everywhere eBay owns, measured 2026-10-07:

- The Finding API (`findCompletedItems`) was decommissioned 2025-02-04; eBay's deprecation
  table says it "has been replaced by the Browse API", which has no sold data.
- Marketplace Insights (`item_sales/search`) is the official sold API. Even its docs sit
  behind a developer sign-in (`marketplace-insights-private`), and Buy APIs in production are
  "intended for eBay partners only" through the eBay Partner Network, accepted "based on the
  proposed business model". Not reachable for personal use.
- The website's sold filter (`LH_Sold=1&LH_Complete=1`) from this machine: curl_cffi,
  headless Chromium, headless Chrome with Alex's eBay cookies, and off-screen real Chrome all
  got the "Pardon Our Interruption" bot check, then a captcha. Plain active search got the
  same. SerpApi's eBay engine documents its Sold and Complete options as "deprecated and no
  longer supported". Do not retry that route from here; each attempt hardens the block.
- Terapeak lives on the same domain behind the same wall. 130point.com and its backend 403.

So `sold` runs the Apify actor `caffein.dev/ebay-sold-listings` (3.7k users, run today when
checked, $0.004 per result; the free Apify plan includes $5 of usage a month), which scrapes
the sold search from Apify's own network. It needs APIFY_TOKEN; it needs no eBay login and
sends nothing of Alex's. Each run is capped with maxTotalChargeUsd.

Best Offer Accepted: eBay shows the listing price, not the accepted offer, on a BOA sale. The
actor flags those rows (`isBestOfferAccepted`), and the stats here treat their price as an
upper bound, so `comps` reports medians with and without them.
"""

from __future__ import annotations

import json
import statistics
import time
from typing import Any
from urllib.parse import quote

from .common import ROOT, LaneError, env, home_zip, session

RETAILER = "eBay"
API = "https://api.ebay.com"
TOKEN_URL = API + "/identity/v1/oauth2/token"
SCOPE = "https://api.ebay.com/oauth/api_scope"
TOKEN_FILE = ROOT / "secrets" / "ebay-token.json"
ITEM_URL = "https://www.ebay.com/itm/{}"
SOLD_URL = "https://www.ebay.com/sch/i.html?_nkw={}&LH_Sold=1&LH_Complete=1"
APIFY_ACTOR = "caffein.dev~ebay-sold-listings"
APIFY_RUN = f"https://api.apify.com/v2/acts/{APIFY_ACTOR}/run-sync-get-dataset-items"
APIFY_PRICE_PER_RESULT = 0.004  # FREE tier, read from the Apify store API 2026-10-07

# eBay condition ids grouped the way a buyer thinks about them.
CONDITIONS = {
    "new": "1000|1500|1750",
    "open_box": "1500",
    "refurbished": "2000|2010|2020|2030|2500",
    "used": "3000|4000|5000|6000",
    "parts": "7000",
}
SORTS = {"best": None, "price": "price", "price_desc": "-price", "newest": "newlyListed", "ending": "endingSoonest"}


def have_keys() -> bool:
    return bool(env("EBAY_CLIENT_ID") and env("EBAY_CLIENT_SECRET"))


# ------------------------------------------------------------------ Browse API


def token() -> str:
    """Application token, cached until five minutes before it expires."""
    if TOKEN_FILE.exists():
        cached = json.loads(TOKEN_FILE.read_text())
        if cached.get("expires_at", 0) > time.time() + 300:
            return cached["access_token"]
    cid, secret = env("EBAY_CLIENT_ID"), env("EBAY_CLIENT_SECRET")
    if not cid or not secret:
        raise LaneError("ebay: EBAY_CLIENT_ID / EBAY_CLIENT_SECRET are not in the harness .env. "
                        "Make a production keyset at developer.ebay.com/my/keys.")
    r = session().post(TOKEN_URL, auth=(cid, secret), timeout=25,
                       data={"grant_type": "client_credentials", "scope": SCOPE})
    if r.status_code != 200:
        raise LaneError(f"ebay: token request failed, HTTP {r.status_code}: {r.text[:200]}")
    d = r.json()
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"access_token": d["access_token"],
                                      "expires_at": time.time() + int(d.get("expires_in", 7200))}))
    TOKEN_FILE.chmod(0o600)
    return d["access_token"]


def _browse(path: str, params: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {token()}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        # Shipping costs and delivery estimates are quoted to this ZIP.
        "X-EBAY-C-ENDUSERCTX": f"contextualLocation={quote(f'country=US,zip={home_zip()}', safe='')}",
    }
    r = session().get(API + "/buy/browse/v1/" + path, params=params, headers=headers, timeout=30)
    if r.status_code == 401:
        TOKEN_FILE.unlink(missing_ok=True)
        raise LaneError("ebay: token rejected (401); the cache is cleared, run again")
    if r.status_code != 200:
        raise LaneError(f"ebay: HTTP {r.status_code} on {path}: {r.text[:200]}")
    return r.json()


def _money(m: dict | None) -> float | None:
    try:
        return float((m or {}).get("value"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _shipping(options: list | None) -> float | None:
    """Cheapest quoted shipping. None means not quoted (often 'calculated' or pickup only)."""
    costs = [_money(o.get("shippingCost")) for o in options or [] if o.get("shippingCost")]
    costs = [c for c in costs if c is not None]
    return min(costs) if costs else None


def summary_row(s: dict) -> dict:
    """An item_summary (search) or full item -> the common row shape."""
    price = _money(s.get("price"))
    bid = _money(s.get("currentBidPrice"))
    buying = s.get("buyingOptions") or []
    if price is None and bid is not None:
        price = bid
    ship = _shipping(s.get("shippingOptions"))
    seller = s.get("seller") or {}
    loc = s.get("itemLocation") or {}
    # REST ids look like "v1|<legacy id>|<variation>"; the legacy id is what URLs and humans use.
    parts = str(s.get("itemId") or "").split("|")
    legacy = s.get("legacyItemId") or (parts[1] if len(parts) > 1 else None)
    return {
        "retailer": RETAILER,
        "id": legacy or s.get("itemId"),
        "url": ITEM_URL.format(legacy) if legacy else s.get("itemWebUrl"),
        "title": s.get("title", ""),
        "price": price,
        "formatted": f"${price:,.2f}" if price is not None else None,
        "shipping": ship,
        "total": round(price + ship, 2) if price is not None and ship is not None else None,
        "condition": s.get("condition"),
        "buying": buying,
        "bids": s.get("bidCount"),
        "ends": (s.get("itemEndDate") or "")[:16].replace("T", " ") or None,
        "seller": seller.get("username"),
        "seller_feedback": seller.get("feedbackPercentage"),
        "seller_score": seller.get("feedbackScore"),
        "location": ", ".join(x for x in (loc.get("city"), loc.get("stateOrProvince"), loc.get("postalCode")) if x) or None,
    }


def _filters(min_price: float | None, max_price: float | None, condition: list[str] | None,
             buying: str | None, local_miles: int | None) -> str:
    parts = ["deliveryCountry:US"]
    if min_price is not None or max_price is not None:
        lo = "" if min_price is None else f"{min_price:g}"
        hi = "" if max_price is None else f"{max_price:g}"
        parts += [f"price:[{lo}..{hi}]", "priceCurrency:USD"]
    if condition:
        ids = "|".join(CONDITIONS[c] for c in condition)
        parts.append(f"conditionIds:{{{ids}}}")
    if buying:
        parts.append(f"buyingOptions:{{{buying}}}")
    if local_miles:
        parts += ["deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}", "pickupCountry:US",
                  f"pickupPostalCode:{home_zip()}", f"pickupRadius:{local_miles}", "pickupRadiusUnit:mi"]
    return ",".join(parts)


def search(query: str, n: int = 20, min_price: float | None = None, max_price: float | None = None,
           condition: list[str] | None = None, buying: str | None = None, local_miles: int | None = None,
           sort: str = "best") -> list[dict]:
    for c in condition or []:
        if c not in CONDITIONS:
            raise LaneError(f"ebay: condition {c!r} is not one of {', '.join(CONDITIONS)}")
    params: dict[str, Any] = {"q": query, "limit": min(max(n, 1), 200),
                              "filter": _filters(min_price, max_price, condition, buying, local_miles)}
    if SORTS.get(sort):
        params["sort"] = SORTS[sort]
    d = _browse("item_summary/search", params)
    return [summary_row(s) for s in d.get("itemSummaries") or []]


def item(legacy_id: str) -> dict:
    d = _browse("item/get_item_by_legacy_id", {"legacy_item_id": legacy_id})
    row = summary_row(d)
    row["condition_note"] = d.get("conditionDescription")
    row["description"] = d.get("shortDescription")
    row["aspects"] = {a.get("name"): a.get("value") for a in d.get("localizedAspects") or []}
    row["returns"] = (d.get("returnTerms") or {}).get("returnsAccepted")
    row["photos"] = 1 + len(d.get("additionalImages") or []) if d.get("image") else 0
    avail = (d.get("estimatedAvailabilities") or [{}])[0]
    row["availability"] = avail.get("estimatedAvailabilityStatus")
    row["mpn"] = d.get("mpn")
    row["gtin"] = d.get("gtin")
    return row


# ------------------------------------------------------------------ sold (Apify)


def _num(v: Any) -> float | None:
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def sold_row(d: dict) -> dict:
    price = _num(d.get("soldPrice"))
    ship = _num(d.get("shippingPrice"))
    return {
        "retailer": "eBay sold",
        "id": d.get("itemId"),
        "url": d.get("url") or ITEM_URL.format(d.get("itemId")),
        "title": d.get("title") or "",
        "price": price,
        "formatted": f"${price:,.2f}" if price is not None else None,
        "shipping": 0.0 if d.get("shippingType") == "free" else ship,
        "total": _num(d.get("totalPrice")),
        "condition": d.get("condition"),
        "sold_on": (d.get("endedAt") or "")[:10] or None,
        "format": d.get("listingType") or d.get("buyingFormat"),
        "bids": d.get("bidCount"),
        # eBay shows the listing price on a Best Offer sale, so this price is a ceiling.
        "best_offer": bool(d.get("isBestOfferAccepted")),
    }


def sold(query: str, n: int = 50, days: int = 90, condition: str = "any", min_price: float | None = None,
         max_price: float | None = None) -> list[dict]:
    tok = env("APIFY_TOKEN")
    if not tok:
        raise LaneError("ebay sold: APIFY_TOKEN is not in the harness .env (free account at apify.com, "
                        "Settings > API & Integrations). Until then, check sold prices by hand: "
                        + SOLD_URL.format(quote(query)))
    body: dict[str, Any] = {"keywords": [query], "count": n, "daysToScrape": days, "ebaySite": "ebay.com",
                            "sortOrder": "endedRecently", "itemCondition": condition,
                            "itemLocation": "domestic", "includeCompletedListings": True}
    if min_price is not None:
        body["minPrice"] = int(min_price)
    if max_price is not None:
        body["maxPrice"] = int(max_price)
    cap = round(n * APIFY_PRICE_PER_RESULT + 0.05, 2)
    r = session().post(APIFY_RUN, json=body, timeout=300, headers={"Authorization": f"Bearer {tok}"},
                       params={"maxTotalChargeUsd": cap, "timeout": 280})
    if r.status_code not in (200, 201):
        raise LaneError(f"ebay sold: Apify HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    if not isinstance(data, list):
        raise LaneError(f"ebay sold: Apify returned {type(data).__name__}, not a dataset list")
    return [sold_row(d) for d in data if isinstance(d, dict) and d.get("soldPrice") not in (None, "")]


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    i = (len(xs) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (i - lo), 2)


def comps(rows: list[dict]) -> dict:
    """Summary of sold rows. Totals include shipping when it was quoted."""
    def stats(xs: list[float]) -> dict:
        if not xs:
            return {}
        return {"n": len(xs), "median": round(statistics.median(xs), 2), "p25": _pct(xs, 0.25),
                "p75": _pct(xs, 0.75), "min": min(xs), "max": max(xs)}
    prices = [r["price"] for r in rows if r.get("price") is not None]
    firm = [r["price"] for r in rows if r.get("price") is not None and not r.get("best_offer")]
    totals = [r["total"] for r in rows if r.get("total") is not None]
    dates = sorted(r["sold_on"] for r in rows if r.get("sold_on"))
    return {"price": stats(prices), "price_no_best_offer": stats(firm), "total": stats(totals),
            "best_offer_rows": sum(1 for r in rows if r.get("best_offer")),
            "from": dates[0] if dates else None, "to": dates[-1] if dates else None}


# ------------------------------------------------------------------ printing


def print_row(r: dict, full: bool = False) -> None:
    price = r.get("formatted") or "-"
    extra = []
    if r.get("shipping"):
        extra.append(f"+${r['shipping']:.2f} ship")
    elif r.get("shipping") == 0:
        extra.append("free ship")
    if r.get("condition"):
        extra.append(str(r["condition"]))
    if "AUCTION" in (r.get("buying") or []):
        extra.append(f"auction, {r.get('bids') or 0} bids, ends {r.get('ends')}")
    if r.get("sold_on"):
        extra.append(f"sold {r['sold_on']}")
    if r.get("best_offer"):
        extra.append("best offer (price is a ceiling)")
    print(f"{r['retailer']:<10} {price:>10}  {str(r.get('id') or ''):<13} {r.get('title', '')[:60]}  {'; '.join(extra)}")
    if not full:
        return
    print(f"  {r['url']}")
    for k in ("total", "seller", "seller_feedback", "location", "availability", "returns", "mpn", "gtin",
              "condition_note", "photos"):
        if r.get(k) not in (None, "", []):
            print(f"  {k}: {r[k]}")
    if r.get("aspects"):
        print(f"  aspects: {json.dumps(r['aspects'])}")
    if r.get("description"):
        print(f"  description: {r['description']}")


def print_comps(c: dict, query: str) -> None:
    def line(label: str, s: dict) -> None:
        if s:
            print(f"  {label:<22} median ${s['median']:,.2f}  (p25 ${s['p25']:,.2f}, p75 ${s['p75']:,.2f}, "
                  f"range ${s['min']:,.2f} to ${s['max']:,.2f}, n={s['n']})")
    print(f"Sold comps for {query!r}, {c.get('from')} to {c.get('to')}:")
    line("price", c["price"])
    if c["best_offer_rows"]:
        line("price, no best offers", c["price_no_best_offer"])
        print(f"  {c['best_offer_rows']} best-offer sales: their real price is lower than shown")
    line("price + shipping", c["total"])
