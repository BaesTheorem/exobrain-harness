# shopping

One pipeline for buying anything at the lowest real price. The `/shopping` skill drives the
workflow; this directory is the tool. Everything is read-only toward money: nothing here signs
in, enters payment, or submits an order.

```
shop find <query> [--at target,walmart,flipp,amazon,fbm] [-n N] [--json]
shop price <url | target:<tcin> | walmart:<id> | flipp:<id> | fbm:<id> | ASIN>... [--all-variants] [--json]
shop fbm <query> [--radius KM] [--min N] [--max N] [--days D] [--condition ...] [--sort ...] [--exact]
shop ebay <query> [--condition new,used,...] [--min N] [--max N] [--auction|--bin] [--local MI] [--sort ...]
shop ebay --sold <query> [--days D] [--condition any|new|used]   # sold listings + median/quartiles
shop stores                                   # Target stores nearest HOME_ZIP
shop codes <domain> [--extra CODE ...] [--no-guess]
shop cart <shopify-product-url> --codes A B --harvest --max-stack 3 [--qty N] [--selling-plan ID]
shop best tmp/shopping/<item>.json
shop clearance <upc> [store] | --retailer homedepot <item-id> [store]
shop amazon search|show|url|orders|auth ...   # the full Amazon tool
```

`bin/shop` is a plain Python 3 entry point over the `shoptools/` package. It needs `curl_cffi`
and `playwright` (with the chromium browser) in the system Python, and `HOME_ZIP=<zip>` in the
harness `.env`, because shelf prices, store stock and weekly ads are all local. The eBay lane
needs `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET` (active listings) and `APIFY_TOKEN` (sold prices).
The Marketplace lane also needs `MYKCMO_HOME_LAT`/`MYKCMO_HOME_LON` (the harness-wide home point) and the
Facebook session from the `facebook/` toolkit. `shop clearance`
also needs Penny Lane at `~/Documents/penny-lane` (the `/penny` skill).

## Lanes

Each lane returns the same core keys (retailer, id, url, title, price, formatted) so `find`
prints one table across all of them, sorted by price. A lane that fails or returns zero rows is
reported as a warning on stderr, never dropped silently: zero rows is a fact about the query,
not evidence the item is unsold there.

### Target (`shoptools/lanes.py`, RedSky API)

Store context changes the price. The same jar was $4.99 with no store, $4.59 at an Iowa store
and $3.69 in Kansas City, so `shop` always prices at the store nearest `HOME_ZIP`
(`nearby_stores_v1`) and prints the `location_id` that priced the item. If that is not the
store you asked for, the item is online-only or the store has no price of its own.

- `plp_search_v2` (keyword search) works with `platform=desktop`, `pricing_store_id`,
  `store_ids` and a 34-character `visitor_id`. Shorter visitor ids are rejected.
- `pdp_client_v1` returns the price, the UPC (`primary_barcode`), promotions and the variant
  list. `product_fulfillment_v1` adds pickup, shipping and the store's unit count.
- **HTTP 435 is a PerimeterX block of this IP for the whole API**, and it is cheap to trip:
  about fifteen calls inside fifteen minutes did it on 2026-10-05. `shop` spaces its calls 2 s
  apart and turns a 435 into a clear error. Headless Chromium on target.com gets the same block
  and the product page's server-rendered HTML carries no price, so there is no fallback route.
  The block lifts on its own in about an hour; retrying extends it.
- The web key in the code is Target's public one, shipped in target.com's own JavaScript.

### Walmart (`__NEXT_DATA__`)

Product pages (`/ip/<id>`) parse through `curl_cffi` with Chrome impersonation. The price is in
`priceInfo.currentPrice`, with `availabilityStatus`, `sellerName`, `upc` and the pickup and
shipping options (defaulting to the store nearest this machine's IP). Search pages carry the
price only in the top-level `price` field; every `priceInfo` string is empty there. Always read
the seller: marketplace sellers post wild markups, and `find` prints the seller when it is not
Walmart. `/store/finder` hits the "Robot or human?" wall, so store choice is Walmart's.

### Flipp (weekly ads)

`backflipp.wishabi.com/flipp/items/search?postal_code=<zip>&q=<term>` is the only lane into
local grocery pricing: Hy-Vee, Dillons, Price Chopper, ALDI, Dollar General, Costco. The item
detail carries the **size** in `description` (`28 oz.`), the merchant as a bare string, the
sale story and the ad's valid dates. Run a broad positive control first: a zero-item result
means nothing until a wider query returns rows.

### Amazon (`shoptools/amazon.py`, headless Playwright)

Amazon's `/s?k=` search sits behind Akamai Bot Manager: plain `curl` gets a 1.4 KB `bm-verify`
challenge stub, never results. It is a **JavaScript challenge, not an auth gate**, so an
anonymous headless Chromium clears it (tested 2026-09-22, 52 product cards, no login). Product
pages respond to plain curl too, but the same browser path is used for both.

`show` loads the saved Chrome session by default so the **delivery promise is for Alex's real
address**. Anonymous, Amazon guesses a region and the date can be days off, so that case prints
a warning next to it. `--anon` forces the anonymous path. `--all-variants` loads every sibling
color/size ASIN from the twister map: each has its own stock and delivery date, and siblings can
differ in cut and weight, so read each title.

Traps the selectors exist to avoid, do not loosen them to regex:

- **Sponsored carousels contaminate the HTML.** A listing page carries other products' titles,
  prices and review counts. A naive `grep zipper` on a product page returned four neighbouring
  products and zero of the actual item. Every selector is scoped to a container the item owns.
- **Price is ambiguous by regex.** A page has several `a-offscreen` price strings. `show` reads
  the buy box specifically and returns empty rather than guessing; empty usually means unavailable.
- **`<h2>` is the brand, not the title.** The title lives in `[data-cy="title-recipe"]` behind a
  "Sponsored" prefix.
- **Read the `Capacity` spec row; never compute it from the dimensions.** The cylinder model put a
  0.4 L pouch at 1.5 L.
- **The User-Agent tracks the installed Chrome's major version.** Amazon binds a session to the
  browser identity; a stale hardcoded major bounced valid cookies to the sign-in page, which reads
  as "session expired" and sends you re-exporting cookies that were never the problem.
- **An empty result is suspect.** `search` exits non-zero on zero rows, and both commands raise if
  they detect the bot challenge, so a block never reads as "no such product".

The session comes from Chrome's cookie store (`shoptools/chrome_cookies.py`, `shop amazon auth
--from-chrome`). The login itself is never automated; see `secrets/README.md`. PA-API 5.0 needs
an Associates account with qualifying sales, so it is walled for personal use.

### Facebook Marketplace (`shoptools/fbm.py`, session cookies + GraphQL)

The used market around home. It is **not in the default `find` table**: used listings are a
different market from new retail, so they join only with `--at fbm`, or through `shop fbm`
with its own filters. `shop price fbm:<id>` (or a `marketplace/item/<id>` URL) returns the
description, condition, every photo, the seller's rating and join date, shipping, and the
approximate pin. Read-only: no messages, saves or reactions.

- **The logged-out web is a hard wall from this IP.** The search page 302s to `/login`, and
  every anonymous GraphQL call answers `Rate limit exceeded` (code 1675004), whatever the
  `doc_id` (measured 2026-10-07). The Apify actor's "cookies optional" does not hold here.
- So the lane rides the session cookies the `facebook/` toolkit keeps in
  `facebook/secrets/cookies.txt` (`facebook/bin/fb refresh-cookies` re-pulls them from Chrome).
  It reads that file as data and imports nothing from the toolkit. The cookies are Alex's
  account: keep searches modest. Facebook's realistic response to automation is an identity
  checkpoint, which the lane reports as "run refresh-cookies", not a ban.
- **Two routes from one GET.** The search HTML embeds the first 24 results and the request
  tokens (`fb_dtsg`, `lsd`, `jazoest`). With the tokens,
  `CometMarketplaceSearchContentPaginationQuery` on `/api/graphql/` takes the home point
  (`MYKCMO_HOME_LAT/LON`), an explicit radius, price bounds **in cents**, condition and age,
  and pages 24 at a time. The embedded page is the fallback: it obeys the URL filters but its
  radius is the account's saved Marketplace location (3 km on 2026-10-07), so a fallback
  result is reported as a warning.
- **The `doc_id` drifts** with Facebook's Relay bundles and is not in the page HTML. The current
  one is a constant, overridden by `secrets/fbm-doc-id.txt` or `FBM_DOC_ID`;
  `shop fbm --refresh-docid` recaptures it with one headless, read-only Playwright pass. A
  rejected id falls back to the embedded page and says so, so drift never reads as "nothing
  for sale".
- **Facebook's search is fuzzy.** `query=bike` returned ellipticals and skates; `--exact` sends
  `exact=true`. The `ctime_days` filter is advisory (days=7 returned a 10-day-old listing), so
  `--days` is enforced again on `creation_time`. Sort by price or date is applied client-side
  to the pages fetched; `--sort distance` only shapes the fallback page.
- Item pages split the listing across two Relay blobs (one carries only `listing_photos`),
  so `item_target` merges every `marketplace_product_details_page.target` on the page.

### eBay (`shoptools/ebay.py`, Browse API + Apify for sold prices)

**Active listings** come from eBay's official Browse API (`item_summary/search`,
`item/get_item_by_legacy_id`) with an application token. It needs `EBAY_CLIENT_ID` and
`EBAY_CLIENT_SECRET` in the harness `.env`, a free production keyset from
developer.ebay.com/my/keys. The token lasts about two hours and is cached in
`secrets/ebay-token.json`. `X-EBAY-C-ENDUSERCTX` carries `HOME_ZIP`, so shipping is quoted to
home, and `--local MI` filters to local pickup within that radius. Once the keys exist, eBay
joins the default `find` table, new condition only; used eBay goes through `shop ebay`.

**Sold prices** are what a used item is actually worth, and every route eBay owns is walled
(measured 2026-10-07):

| Route | Result |
| --- | --- |
| Finding API `findCompletedItems` | Decommissioned 2025-02-04, "replaced by the Browse API", which has no sold data |
| Marketplace Insights API | The official sold API. Docs behind a sign-in; Buy APIs in production are "intended for eBay partners only", by application through the eBay Partner Network |
| Website sold filter (`LH_Sold=1&LH_Complete=1`) | curl_cffi, headless Chromium, headless Chrome with Alex's eBay cookies and off-screen real Chrome all hit "Pardon Our Interruption", then a captcha. Active search from this IP got the same. Do not retry: each attempt hardens the block |
| SerpApi eBay engine | Documents its Sold and Complete options as "deprecated and no longer supported" |
| Terapeak, 130point | Terapeak is on the same walled domain; 130point and its backend return 403 |

So `shop ebay --sold` runs the Apify actor `caffein.dev/ebay-sold-listings` (3.7k users,
active the day it was chosen, $0.004 per result; Apify's free plan includes $5 of usage a
month). It scrapes the sold search from Apify's network, needs `APIFY_TOKEN` and no eBay login,
and each run is capped with `maxTotalChargeUsd`. Without a token it prints the sold-search URL
to open by hand. The output adds median, quartiles and range, with shipping and without.

**Best Offer Accepted:** on a BOA sale eBay shows the listing price, not the accepted offer, so
that price is a ceiling. Those rows are flagged and the stats give a median without them.

### Codes, cart tests, ranking

- `shop codes` harvests SimplyCodes (`data-code` attributes; dealspotr.com and knoji.com redirect
  there) and Wethrift (`"code":` JSON), then adds common guesses. RetailMeNot, CouponFollow and
  CouponCabin hide codes behind a click-out; Slickdeals `/coupons/` is 410, CouponBirds 403; the
  Syrup open-source DB sits behind a JS challenge and its repo is archived.
- `shop cart` is **the only lane that proves a code works.** Shopify's Ajax Cart API
  (`POST /cart/update.js {"discount": "A,B"}`) returns per-code `applicable` flags and the
  discounted total for an anonymous cart; comma-joined codes show whether codes combine. Each run
  first applies a nonsense code and aborts if the store reports it as applicable. Small stores
  return 429 after about 20 cart requests and keep blocking for more than 5 minutes: run one test
  at a time, codes found online before `--harvest` guesses, `--max-stack` low. The cart has no
  shipping line, so a free-shipping code applies but saves $0. Subscription-only codes need
  `--selling-plan <id>` (ids in `selling_plan_groups` of `/products/<handle>.js`).
- `shop best` is arithmetic, not a measurement: percent codes before fixed ones, then shipping,
  tax, the gift-card discount, then cashback. Rows are `verified` only when every code in them was
  confirmed on a cart. The offers schema is in the skill.

### Clearance (Penny Lane)

`shop clearance` hands off to `~/Documents/penny-lane/bin/penny upc` or `penny lookup`, which
reads the live per-store price, clearance state and shelf quantity at Alex's Home Depot, Dollar
General, Lowe's and Walmart stores. That app has its own repo and skill (`/penny`).

## Walled from here, do not burn time

Hy-Vee (Cloudflare 403), Kroger and Dillons (connection refused), Instacart's `/v3/` API (401),
Lowe's, Bass Pro, DICK'S, Tractor Supply store stock. Instacart product and search pages do
server-render prices. Store-stock lanes that do work but are not in `shop` yet, all via
`curl_cffi`: REI category pages with `?r=stores%3A<id>`, Academy's `inventory_pick` list,
SCHEELS per-store inventory on the product page, Home Depot's GraphQL
`fulfillment.locations.inventory.quantity`, Harbor Freight's `api.harborfreight.com`
`stockStatus.stock_code`.
