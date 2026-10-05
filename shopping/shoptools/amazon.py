"""Amazon lane: read-only product, price and order lookup over a headless browser.

Amazon's `/s?` search is gated by Akamai Bot Manager (a `bm-verify` JavaScript challenge,
NOT an auth check), so plain curl gets a 1.4 KB challenge stub while a real browser engine
gets the full page. That is why this lane drives Playwright instead of a requests script.

Account-level commands reuse a session exported from Chrome (chrome_cookies.py). The
sign-in is always done by hand in a real browser; this tool has no password and cannot
log in. Read-only by construction: it never signs in, adds to cart, or buys anything.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from urllib.parse import quote_plus

from . import chrome_cookies
from .common import ua

DP = "https://www.amazon.com/dp/{}"
SEARCH = "https://www.amazon.com/s?k={}"
ORDERS = "https://www.amazon.com/gp/css/order-history"

# Sponsored carousels and "customers also viewed" strips inject OTHER products'
# titles and prices into the same HTML. Every selector below is scoped to a
# container that belongs to the item itself; do not loosen them to bare regex.
BUYBOX = (
    "#corePriceDisplay_desktop_feature_div span.a-offscreen",
    "#corePrice_feature_div span.a-offscreen",
    "#price_inside_buybox",
)
# Delivery promise is address-specific, so it only means anything with the
# session loaded. Anonymous, Amazon guesses a region and the date can be days
# off, which is worse than no answer when the question is "will it arrive".
DELIVERY = (
    "#mir-layout-DELIVERY_BLOCK",
    "#deliveryBlockMessage",
    "#fast-track-message",
)


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.inner_text()).strip() if node else ""


def _first(page, selectors: tuple[str, ...]) -> str:
    for sel in selectors:
        if hit := page.query_selector(sel):
            if t := _text(hit):
                return t
    return ""


def _money(s: str) -> float | None:
    m = re.search(r"\d[\d,]*\.?\d*", s or "")
    return float(m.group(0).replace(",", "")) if m else None


def _browser(pw, headed: bool, cookies: list[dict] | None = None):
    b = pw.chromium.launch(headless=not headed)
    ctx = b.new_context(user_agent=ua(), locale="en-US", viewport={"width": 1440, "height": 900})
    if cookies:
        ctx.add_cookies(cookies)
    return b, ctx.new_page()


def _guard(page) -> None:
    """Fail loudly instead of returning an empty list that looks like 'no results'."""
    html = page.content()
    if "bm-verify" in html or re.search(r"Enter the characters|Robot Check", html):
        raise SystemExit("amazon: hit the bot challenge. Slow down and retry in a few minutes.")


def search(query: str, limit: int = 12, headed: bool = False, timeout: int = 45) -> list[dict]:
    from playwright.sync_api import sync_playwright

    out: list[dict] = []
    with sync_playwright() as pw:
        b, page = _browser(pw, headed)
        try:
            page.goto(SEARCH.format(quote_plus(query)), wait_until="domcontentloaded", timeout=timeout * 1000)
            page.wait_for_timeout(2500)
            _guard(page)
            seen: set[str] = set()
            for card in page.query_selector_all('[data-component-type="s-search-result"]'):
                asin = card.get_attribute("data-asin") or ""
                # <h2> holds only the BRAND in the current card layout ("Ziploc"), so
                # read the title-recipe block and strip its leading "Sponsored" label.
                title = _text(card.query_selector('[data-cy="title-recipe"]')) or _text(card.query_selector("h2"))
                title = re.sub(r"^(?:Sponsored\s*)+", "", title)
                if not asin or asin in seen:
                    continue
                seen.add(asin)
                stars = card.query_selector("span.a-icon-alt")
                formatted = _text(card.query_selector("span.a-price > span.a-offscreen"))
                out.append({
                    "retailer": "Amazon",
                    "id": asin,
                    "asin": asin,
                    "url": DP.format(asin),
                    "title": title,
                    "price": _money(formatted),
                    "formatted": formatted,
                    "rating": (_text(stars).split(" out of")[0] if stars else ""),
                    "reviews": _text(card.query_selector("span.a-size-base.s-underline-text")),
                    "sponsored": bool(card.query_selector('[aria-label*="Sponsored"], .puis-sponsored-label-text')),
                })
                if len(out) >= limit:
                    break
        finally:
            b.close()
    return out


def _variants(html: str) -> dict[str, str]:
    """Sibling ASINs from the twister's `dimensionValuesDisplayData` map.

    Each color/size variant is its own ASIN with its OWN stock and delivery
    date, so a search hit on one color says nothing about the others (a grey
    tarp shipped next day while the searched green one was two days out).
    """
    m = re.search(r'"dimensionValuesDisplayData"\s*:\s*(\{.*?\})\s*,', html, re.S)
    if not m:
        return {}
    try:
        raw = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}
    return {a: " / ".join(v) for a, v in raw.items()}


def show(asin: str, headed: bool = False, timeout: int = 45, anon: bool = False) -> dict:
    from playwright.sync_api import sync_playwright

    jar = None
    if not anon:
        try:
            jar = chrome_cookies.load()
        except chrome_cookies.NotLoggedIn:
            jar = None
    with sync_playwright() as pw:
        b, page = _browser(pw, headed, cookies=jar)
        try:
            page.goto(DP.format(asin), wait_until="domcontentloaded", timeout=timeout * 1000)
            page.wait_for_timeout(2500)
            _guard(page)
            stars = page.query_selector("#acrPopover")
            specs = {}
            for row in page.query_selector_all("#productDetails_techSpec_section_1 tr, #productOverview_feature_div tr"):
                cells = row.query_selector_all("th, td")
                if len(cells) == 2:
                    specs[_text(cells[0])] = _text(cells[1])
            formatted = _first(page, BUYBOX)
            return {
                "retailer": "Amazon",
                "id": asin,
                "asin": asin,
                "variants": _variants(page.content()),
                "url": DP.format(asin),
                "title": _text(page.query_selector("#productTitle")),
                "price": _money(formatted),
                "formatted": formatted,
                "rating": (stars.get_attribute("title") or "" if stars else ""),
                "reviews": _text(page.query_selector("#acrCustomerReviewText")),
                "availability": _text(page.query_selector("#availability")),
                "delivery": _first(page, DELIVERY),
                "signed_in": bool(jar) and not page.query_selector("#ap_email"),
                "bullets": [t for li in page.query_selector_all("#feature-bullets li") if (t := _text(li))],
                "specs": specs,
            }
        finally:
            b.close()


def show_many(asins: list[str], all_variants: bool = False, headed: bool = False,
              timeout: int = 45, anon: bool = False) -> list[dict]:
    products = [show(x, headed, timeout, anon) for x in asins]
    if all_variants:
        seen = {p["asin"] for p in products}
        for p in list(products):
            for v in p["variants"]:
                if v not in seen:
                    seen.add(v)
                    products.append(show(v, headed, timeout, anon))
    return products


def orders(year: str | None, headed: bool, timeout: int) -> list[dict]:
    from playwright.sync_api import sync_playwright

    jar = chrome_cookies.load()
    url = ORDERS + (f"?timeFilter=year-{year}" if year else "")
    out: list[dict] = []
    with sync_playwright() as pw:
        b, page = _browser(pw, headed, cookies=jar)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            page.wait_for_timeout(2500)
            _guard(page)
            # A lapsed session renders the sign-in page, which parses as zero orders.
            if "/ap/signin" in page.url or page.query_selector("#ap_email"):
                raise SystemExit(
                    "amazon: the saved session is signed out or expired. "
                    "Sign in to amazon.com in Chrome, then run `shop amazon auth --from-chrome`.")
            for card in page.query_selector_all(".order-card"):
                # Each header cell is a label/value pair. Read them by LABEL rather
                # than by position: the column order varies by order type, and
                # "Ship to" is deliberately never captured. Keys are lowercased
                # because inner_text() returns RENDERED text and .a-text-caps is
                # text-transform:uppercase, so the label arrives as "ORDER PLACED".
                head: dict[str, str] = {}
                for cell in card.query_selector_all(".order-header__header-list-item"):
                    label = _text(cell.query_selector(".a-text-caps")).lower()
                    value = _text(cell.query_selector(".a-size-base"))
                    if label and label != "ship to":
                        head[label] = value
                out.append({
                    "order_id": _text(card.query_selector(".yohtmlc-order-id .a-color-secondary:last-child"))
                                or _text(card.query_selector(".yohtmlc-order-id")),
                    "placed": head.get("order placed", ""),
                    "total": head.get("total", ""),
                    "items": [t for n in card.query_selector_all(".yohtmlc-product-title") if (t := _text(n))],
                })
        finally:
            b.close()
    return out


def cmd_auth(a) -> int:
    if a.from_chrome:
        jar = chrome_cookies.export_session(a.browser)
        path = chrome_cookies.save(jar)
        print(f"exported {len(jar)} amazon.com cookies -> {path} (chmod 600, gitignored)")
        return 0
    try:
        jar = chrome_cookies.load()
    except chrome_cookies.NotLoggedIn as exc:
        print(exc, file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc)
    print(f"{len(jar)} cookies saved at {chrome_cookies.COOKIE_FILE}")
    for c in sorted(jar, key=lambda c: c["name"]):
        if c["name"] not in chrome_cookies.NEEDED:
            continue
        exp = c.get("expires", -1)
        if exp and exp > 0:
            when = datetime.fromtimestamp(exp, tz=timezone.utc)
            age = "EXPIRED" if when < now else f"expires {when.astimezone():%Y-%m-%d}"
        else:
            age = "session cookie"
        print(f"  {c['name']:14} {age}")
    return 0


def print_product(p: dict, full: bool) -> None:
    print(p["title"] or "(no title -- page may not have loaded)")
    print(f"  {p['url']}")
    print(f"  price: {p['formatted'] or '?'}   rating: {p['rating'] or '?'}   {p['reviews']}")
    if p["availability"]:
        print(f"  stock: {p['availability']}")
    if p["delivery"]:
        tag = "" if p["signed_in"] else "  (ANONYMOUS -- date is a guess, not your address)"
        print(f"  ship:  {p['delivery']}{tag}")
    if p["variants"].get(p["asin"]):
        print(f"  variant: {p['variants'][p['asin']]}  ({len(p['variants'])} siblings; --all-variants to check each)")
    if full:
        for k, v in p["specs"].items():
            print(f"  {k}: {v}")
        for bullet in p["bullets"]:
            print(f"  - {bullet}")
    print()


def main(argv: list[str] | None = None) -> int:
    # The shared flags live on a parent parser so they work on EITHER side of
    # the subcommand: `shop amazon show X --json` is the form anyone types first.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="emit raw JSON")
    common.add_argument("--headed", action="store_true", help="show the browser window")
    common.add_argument("--timeout", type=int, default=45, help="page load timeout in seconds")
    ap = argparse.ArgumentParser(prog="shop amazon", description=__doc__, parents=[common],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", parents=[common], help="search results: asin, price, rating")
    s.add_argument("query", nargs="+"); s.add_argument("-n", type=int, default=12)
    d = sub.add_parser("show", parents=[common], help="one product: price, delivery, bullets, specs")
    d.add_argument("asin", nargs="+")
    d.add_argument("--anon", action="store_true", help="skip the session (delivery dates become meaningless)")
    d.add_argument("--all-variants", action="store_true",
                   help="also load every sibling color/size ASIN; each has its own stock and delivery date")
    u = sub.add_parser("url", parents=[common], help="print the canonical product URL"); u.add_argument("asin")
    au = sub.add_parser("auth", parents=[common], help="export or inspect the Chrome session")
    au.add_argument("--from-chrome", action="store_true", help="re-export the live session from the browser")
    au.add_argument("--status", action="store_true", help="show held cookies and expiry (default)")
    au.add_argument("--browser", choices=list(chrome_cookies.BROWSERS), default="chrome")
    o = sub.add_parser("orders", parents=[common], help="order history for the signed-in account")
    o.add_argument("--year", help="e.g. 2026")
    a = ap.parse_args(argv)

    if a.cmd == "url":
        print(DP.format(a.asin)); return 0
    if a.cmd == "auth":
        return cmd_auth(a)
    if a.cmd == "orders":
        rows = orders(a.year, a.headed, a.timeout)
        if a.json:
            print(json.dumps(rows, indent=2)); return 0
        if not rows:
            print("No orders parsed. Suspect the selectors, not the account.", file=sys.stderr); return 1
        for r in rows:
            print(f"{r['placed']:<18} {r['total']:>10}  {'; '.join(r['items'])[:80]}")
        return 0
    if a.cmd == "search":
        rows = search(" ".join(a.query), a.n, a.headed, a.timeout)
        if a.json:
            print(json.dumps(rows, indent=2)); return 0
        if not rows:
            print("No results. That is suspect -- check the query before believing it.", file=sys.stderr); return 1
        for r in rows:
            tag = "[ad] " if r["sponsored"] else ""
            stars = f"{r['rating']}* {r['reviews']}" if r["rating"] else ""
            print(f"{r['asin']}  {r['formatted'] or '-':>10}  {stars:>14}  {tag}{r['title'][:70]}")
        return 0

    products = show_many(a.asin, a.all_variants, a.headed, a.timeout, a.anon)
    if a.json:
        print(json.dumps(products if len(products) > 1 else products[0], indent=2)); return 0
    for p in products:
        print_product(p, full=len(products) == 1)
    return 0
