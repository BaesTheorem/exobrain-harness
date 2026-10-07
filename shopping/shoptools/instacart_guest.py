"""Instacart storefront guest lane: online prices from a retailer's Instacart site, no login.

Price Chopper (shopmypricechopper.com), Cosentino's Market (mymarketdelivers.com) and Costco
Same-Day (sameday.costco.com) are white-label Instacart storefronts. Plain HTTP gets no prices
from them, but a headless Chromium with no account does: the storefront creates an implicit
guest session (cookie `__Host-instacart_sid`), places it by IP, and loads prices through the
GraphQL operation `Items`. Measured 2026-10-07 on all three hosts.

How a search runs:

1. Cold path, once per host (about 8 to 17 s): load `/store/<slug>/s?k=<query>` in a headless
   browser, click "Browse as a guest" when the host shows a landing page (Costco does), and
   capture the request URLs of three persisted GraphQL queries the page itself sends:
   `DefaultShop`, `SearchResultsPlacements` and `Items`. The guest cookies and those URLs go in
   `.cache/instacart-guest.json` (gitignored).
2. Warm path, every search (about 2 s, no browser): replay the three URLs through Playwright's
   request context with the cached cookies and edited variables. `DefaultShop` with the ZIP and
   its coordinates returns the shop (and retailer location) that serves that ZIP, which is what
   prices the items: with a wrong shop id `Items` returns the names and no prices, and the
   `postalCode`/`zoneId` variables alone change nothing. `SearchResultsPlacements` returns the
   item ids in rank order; `Items` returns name, size, price, unit price, sale badge and stock.
3. A replay that fails (expired cookies, a rotated query hash) drops the host from the cache and
   takes the cold path again: once with the cached cookies, then once fresh.

Read-only: no address is saved, nothing is added to a cart. Prices are Instacart prices, which
usually run above the shelf price; every row says so.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

from .common import ROOT, LaneError, home_latlon, home_zip, ua

DATA_FILE = Path(__file__).with_name("grocery_stores.json")
CACHE_FILE = ROOT / ".cache" / "instacart-guest.json"
CACHE_MAX_AGE = 14 * 86400          # the guest session cookie outlives this; the query hashes may not
OPS = ("DefaultShop", "SearchResultsPlacements", "Items")
ITEMS_CHUNK = 30                    # the page asks for 6 at a time; 30 in one call worked
NOTE = "online (Instacart) price; usually above the shelf price"


def storefronts() -> dict[str, dict]:
    """lane name -> {host, slug, retailer, chain} from grocery_stores.json."""
    data = json.loads(DATA_FILE.read_text())
    out = {}
    for chain, c in data["chains"].items():
        ic = c.get("instacart")
        if ic and ic.get("lane"):
            out[ic["lane"]] = {"host": ic["host"], "slug": ic["slug"], "retailer": ic.get("retailer") or c["name"], "chain": chain}
    return out


# ------------------------------------------------------------------ parsers (pure, tested offline)


def parse_placements(data: dict) -> list[str]:
    """Item ids in rank order from a SearchResultsPlacements response.

    The placements list is a sequence of grid headers and grids. The grids after a header that
    reads `Results for "..."` are the search results; the ones after "Related items" (which
    also follow a `No results for "..."` header) are not, so a junk query yields [].
    """
    ids: list[str] = []
    keep = False
    seen: set[str] = set()
    for p in ((data.get("data") or {}).get("searchResultsPlacements") or {}).get("placements") or []:
        c = p.get("content") or {}
        tn = c.get("__typename") or ""
        if tn.endswith("SearchItemGridHeader"):
            text = " ".join(s.get("text") or "" for s in (((c.get("viewSection") or {}).get("titleFormattedAttributesString") or {}).get("sections") or []))
            keep = text.startswith("Results for")
        elif tn.endswith("SearchItemGrid") and keep:
            for i in c.get("itemIds") or []:
                if i not in seen:
                    seen.add(i)
                    ids.append(i)
    return ids


def _money(s: str | None) -> float | None:
    m = re.search(r"\d[\d,]*\.?\d*", s or "")
    return float(m.group(0).replace(",", "")) if m else None


def parse_items(data: dict, sf: dict, priced_at: dict) -> list[dict]:
    """Rows in the shop core shape from an Items response."""
    rows = []
    for it in (data.get("data") or {}).get("items") or []:
        pv = ((it.get("price") or {}).get("viewSection") or {})
        card, details, badge = pv.get("itemCard") or {}, pv.get("itemDetails") or {}, pv.get("badge") or {}
        price_s = pv.get("priceString") or card.get("priceString")
        full_s = pv.get("fullPriceString") or details.get("fullPriceString")
        price, full = _money(price_s), _money(full_s)
        size = it.get("size") or ""
        if size in ("", "each"):
            size = card.get("pricingUnitString") or details.get("pricingUnitString") or ""
        stock = ((it.get("availability") or {}).get("stockLevel")) or ""
        rows.append({
            "retailer": sf["retailer"], "id": str(it.get("productId") or it.get("id")), "kind": "online", "via": "Instacart",
            "url": f"https://{sf['host']}/store/{sf['slug']}/products/{it.get('evergreenUrl') or it.get('productId')}",
            "title": it.get("name") or "", "brand": it.get("brandName"), "size": size or None,
            "price": price, "formatted": price_s or None,
            "reg_price": full if full and price and full > price else None,
            "unit_price": details.get("pricePerUnitString") or card.get("pricePerUnitString"),
            "offer": badge.get("offerLabelString"),
            "availability": {"inStock": "InStock", "highlyInStock": "InStock"}.get(stock, stock),
            "item_id": it.get("id"), "store": priced_at, "note": NOTE,
        })
    return rows


# ------------------------------------------------------------------ cache


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {"hosts": {}}
    try:
        c = json.loads(CACHE_FILE.read_text())
    except json.JSONDecodeError:
        return {"hosts": {}}
    if time.time() - c.get("saved", 0) > CACHE_MAX_AGE:
        return {"hosts": {}}
    c.setdefault("hosts", {})
    return c


def _save_cache(c: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    c["saved"] = time.time()
    CACHE_FILE.write_text(json.dumps(c))


def _edit_url(url: str, **changes) -> str:
    """The same persisted-query GET with edited variables."""
    p = urlparse(url)
    qs = parse_qs(p.query)
    v = json.loads(unquote(qs["variables"][0]))
    v.update(changes)
    qs["variables"] = [json.dumps(v, separators=(",", ":"))]
    return urlunparse(p._replace(query=urlencode({k: x[0] for k, x in qs.items()})))


def _vars(url: str) -> dict:
    return json.loads(unquote(parse_qs(urlparse(url).query)["variables"][0]))


class GuestBrowser:
    """One Playwright per run: a request context for replays, a headless browser only when a host is cold."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._rc = None
        self.cache = _load_cache()

    def _playwright(self):
        if self._pw is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
        return self._pw

    def requests(self):
        if self._rc is None:
            state = cast(Any, self.cache.get("storage_state") or {"cookies": [], "origins": []})
            self._rc = self._playwright().request.new_context(
                user_agent=ua(), storage_state=state,
                extra_http_headers={"accept": "*/*", "accept-language": "en-US", "content-type": "application/json"})
        return self._rc

    def _reset_requests(self) -> None:
        if self._rc is not None:
            self._rc.dispose()
            self._rc = None

    def close(self) -> None:
        self._reset_requests()
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- cold path

    def capture(self, sf: dict, query: str, fresh: bool = False, timeout: float = 40.0) -> dict:
        """Load the search page headless, click through a guest landing, record the three op URLs."""
        pw = self._playwright()
        if self._browser is None:
            self._browser = pw.chromium.launch(headless=True)
        state = cast(Any, (None if fresh else self.cache.get("storage_state")) or {"cookies": [], "origins": []})
        ctx = self._browser.new_context(user_agent=ua(), locale="en-US", viewport={"width": 1440, "height": 900},
                                        storage_state=state)
        ops: dict[str, str] = {}

        def on_response(resp):
            if "/graphql" not in resp.url:
                return
            op = (parse_qs(urlparse(resp.url).query).get("operationName") or [""])[0]
            if op in OPS and resp.status == 200:
                ops.setdefault(op, resp.url)

        page = ctx.new_page()
        page.on("response", on_response)
        url = f"https://{sf['host']}/store/{sf['slug']}/s?k={query}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            page.wait_for_timeout(2500)
            guest = page.get_by_text(re.compile(r"as a guest", re.I))
            if guest.count():
                guest.first.click()
                page.wait_for_timeout(3000)
                if "/s?k=" not in page.url:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            deadline = time.time() + timeout
            while time.time() < deadline and not all(o in ops for o in OPS):
                page.wait_for_timeout(500)
            if not all(o in ops for o in OPS):
                missing = [o for o in OPS if o not in ops]
                raise LaneError(f"{sf['retailer']}: the storefront never sent {', '.join(missing)} for {page.url} "
                                "(landing page, block, or a changed app)")
            self.cache["storage_state"] = ctx.storage_state()
            self.cache["hosts"][sf["host"]] = {"ops": ops, "captured": time.strftime("%Y-%m-%d")}
            _save_cache(self.cache)
            self._reset_requests()
            return ops
        finally:
            ctx.close()

    # -- warm path

    def _get(self, url: str) -> dict:
        r = self.requests().get(url, timeout=30000)
        if r.status != 200:
            raise _Stale(f"HTTP {r.status}")
        try:
            d = r.json()
        except Exception as e:  # noqa: BLE001 - any non-JSON body means the session is gone
            raise _Stale(f"non-JSON body ({e})") from e
        if d.get("errors") or "data" not in d:
            raise _Stale(json.dumps(d.get("errors"))[:160])
        return d

    def search(self, lane: str, query: str, n: int = 8, zip_code: str | None = None) -> list[dict]:
        sf = dict(storefronts()[lane], lane=lane)
        zip_code = zip_code or home_zip()
        for attempt in (0, 1, 2):
            ops = (self.cache["hosts"].get(sf["host"]) or {}).get("ops")
            if not ops:
                ops = self.capture(sf, query, fresh=attempt == 2)
            try:
                return self._search(sf, ops, query, n, zip_code)
            except _Stale as e:
                self.cache["hosts"].pop(sf["host"], None)
                if attempt == 2:
                    raise LaneError(f"{sf['retailer']}: Instacart replay failed after a fresh session: {e}") from e
                if attempt == 1:
                    self.cache["storage_state"] = None
        raise LaneError(f"{sf['retailer']}: unreachable")

    def _search(self, sf: dict, ops: dict, query: str, n: int, zip_code: str) -> list[dict]:
        lat, lon = _zip_point(zip_code)
        shop = self._get(_edit_url(ops["DefaultShop"], postalCode=zip_code, coordinates={"latitude": lat, "longitude": lon}, addressId=None))
        ds = (shop.get("data") or {}).get("defaultShop") or {}
        if not ds.get("id"):
            raise LaneError(f"{sf['retailer']}: Instacart has no {sf['slug']} shop for ZIP {zip_code}")
        zone = _vars(ops["Items"]).get("zoneId")
        priced_at = {"zip": zip_code, "id": ds["id"], "retailer_location": ds.get("retailerLocationId"),
                     "service": ds.get("serviceType"), "zone": zone,
                     "name": f"{sf['retailer']} via Instacart, ZIP {zip_code} (shop {ds['id']}, retailer location {ds.get('retailerLocationId')})"}
        placements = self._get(_edit_url(ops["SearchResultsPlacements"], query=query, shopId=ds["id"], postalCode=zip_code,
                                         zoneId=zone, first=max(n, 12), action=None, clusterId=None, filters=[]))
        ids = parse_placements(placements)[:n]
        rows: list[dict] = []
        for i in range(0, len(ids), ITEMS_CHUNK):
            d = self._get(_edit_url(ops["Items"], ids=ids[i:i + ITEMS_CHUNK], shopId=ds["id"], postalCode=zip_code, zoneId=zone))
            rows.extend(parse_items(d, sf, priced_at))
        return rows


class _Stale(RuntimeError):
    """A replay answered wrongly: cookies expired, query hash rotated, or the storefront changed."""


def _zip_point(zip_code: str) -> tuple[float, float]:
    if zip_code == home_zip():
        try:
            return home_latlon()
        except SystemExit:
            pass
    from .grocery import geocode_zip
    return geocode_zip(zip_code)


def search(lane: str, query: str, n: int = 8, zip_code: str | None = None, browser: GuestBrowser | None = None) -> list[dict]:
    """One lane. Pass a shared GuestBrowser to run several lanes on one Playwright."""
    if browser is not None:
        return browser.search(lane, query, n, zip_code)
    with GuestBrowser() as gb:
        return gb.search(lane, query, n, zip_code)
