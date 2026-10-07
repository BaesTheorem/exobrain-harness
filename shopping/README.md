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
shop grocery stores [--near ZIP|LAT,LON]      # KC grocery directory: distance, lanes, closures
shop grocery search <query> [--at wholefoods,costco,pricechopper,cosentinos,sunfresh,aldi,...] [-n N]
shop grocery ad <store> [--grep TERM] [--upcoming] [--store-id ID]   # the whole weekly ad
shop grocery coupons <store> [--grep TERM] [--location ID]            # digital coupons (Cosentino's)
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
also needs Penny Lane at `~/Documents/penny-lane` (the `/penny` skill). The grocery circular
lanes need `pypdf` and `swiftc` (Xcode command line tools) for the one-time Vision OCR build.

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

`backflipp.wishabi.com/flipp/items/search?postal_code=<zip>&q=<term>` is the cross-store lane
into local grocery pricing: Hy-Vee, Dillons, Price Chopper, ALDI, Dollar General, Costco. The
per-store grocery lanes are below. The item
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

### Grocery lanes (`shoptools/grocery.py`, `circular_ocr.py`, `grocery_stores.json`)

`shop grocery` is browse-only for Kansas City grocery stores: directory, prices, weekly ads and
coupons. It never signs in, builds a cart or opens a browser, and it is **not part of `shop
find`**: groceries are a different market from the retail lanes, and the two OCR lanes take
about 10 s cold. Every lane was run live on 2026-10-07 with a query that returned rows and a
junk query that returned none. `grocery_stores.json` holds the fixed facts (store ids, closures,
operators, what each lane covers); the chains with a store API are enriched live. Distances
are from the harness home point (`MYKCMO_HOME_LAT/LON`), or `--near ZIP` (Nominatim, one call).

| Store | Lane | Source | What you get |
| --- | --- | --- | --- |
| Whole Foods (51st St, store 10457) | `search` | `wholefoodsmarket.com/api/search?text=&store=` (no key) | shelf `regularPrice`/`salePrice` |
| Costco | `search`, `ad`, directory | `search.costco.com` typeahead (public `x-api-key`, read from the search page and cached) + the product page's schema.org Offer; Flipp merchant `Costco ` | online prices, item numbers; the weekly coupon book; warehouses with distance |
| Price Chopper KC (50 stores) | `ad`, directory | Flipp merchant `Price Chopper KC` (230 items this week); `mypricechopper.com/public/stores` and `FrontPageAdGroupsForPreferredStore/<StoreId>` | full weekly ad; store list with operator (Ball, Cosentino, McKeever, Queen); `--store-id` adds that store's highlights |
| Cosentino's Market (Downtown, Brookside, Overland Park) | `ad`, `coupons`, directory | Strapi `bagr.iprosystems.com/api` (`locations`, `ads`) with the site's public bearer token; Midax EZConnect `search-offers`/`offers` with the site's `x-api-key` | weekly ad PDF OCR'd (current, `--upcoming` for next week); digital coupons (60 at the downtown store) |
| Sun Fresh (Westport is nearest) | `ad`, directory | Freshop `api.freshop.ncrcloud.com/1/stores` and `/circulars?store_id=` (`app_key=sun_fresh`) | circular PDF OCR'd per store (`--store-id`) |
| ALDI, Hy-Vee, Dillons, Sprouts, Walmart, Target, Sam's Club | `ad` | Flipp flyers at `HOME_ZIP` | weekly ad items with prices |
| Midtown Market (3967 Main), United Market KC (3110 Prospect), Hen House | directory only | Loc8NearMe reviews dated Aug 2026; `unitedmarketkc.com/static/state.js`; `henhouse.com` | address, status, note. No price surface found |

Gotchas, each one measured:

- **Costco's online price is not the warehouse price**, and warehouse prices are not published
  anywhere. The page's schema.org `availability` says `OutOfStock` for everything (Bounty paper
  towels included) without a delivery ZIP context, so it is dropped. The typeahead is site-wide:
  "chicken" returns chicken coops. The GRS search API (`gdx-api.costco.com/catalog/search`) the
  page itself calls answers `400 APIGATEWAY.INTERNAL.FAULT` to every body shape tried and 403
  to GET; the Lucidworks `www_costco_com_en_us` collection is 403. The warehouse locator
  (`AjaxWarehouseBrowseLookupView`) works; Midtown #375 (241 E Linwood) closed 2026-10-01 and
  is gone from it, so the directory carries the closure as a static entry.
- **Cosentino's keys are scraped, not hardcoded.** The Vite bundle (`/assets/index-*.js`) ships
  the EZConnect `x-api-key` and the Strapi bearer token in the clear; `cosentinos_keys()` reads
  them from the live bundle, caches them in `.cache/cosentinos-keys.json`, and refetches once on a
  401/403, so a rotation heals itself. Without the key EZConnect returns `403 Forbidden`.
  Strapi's Brookside location carries the downtown store's coordinates, so the data file
  overrides it (`coordinate_overrides`).
- **Sun Fresh has no catalog.** `/1/products?app_key=sun_fresh&q=milk` returns `total 0` for
  every store, while `app_key=festival_foods` returns priced rows from the same endpoint, so the
  endpoint works and Sun Fresh simply does not publish prices. Not on Flipp, not on Instacart.
- **The circulars are image-only PDFs** (one JPEG a page; `pdftotext` returns 6 bytes). Tesseract
  read 2 price tokens off a page with about 25 deals; Apple Vision reads 88 positioned text boxes
  in under 3 s. `circular_ocr.py` compiles `visionocr.swift` once with `swiftc` into `.cache/`,
  pulls the page JPEGs out with pypdf (rendering with `pdftoppm` took 56 s a page), and groups
  boxes into deals: a price token, then the name lines stacked under it. Ad prices are
  typographic (`$149` is $1.49, `099` is 99 cents, `99%` is Vision reading the cents sign,
  `5/$5` is five for $5) and `parse_price` knows the shapes. **Treat the rows as an index into
  the ad, not a price list**: some deals are missed, some lines attach to the wrong price, and
  page 1 of the Cosentino's ad (all-caps display type) reads worse than the inside pages. Every
  row carries the page number and the PDF URL. OCR output is cached beside the PDF for 30 days.
- **Instacart storefronts hold the shelf prices and need a session.** Price Chopper
  (shopmypricechopper.com), Cosentino's (mymarketdelivers.com), Costco same-day, Hen House and
  ALDI all run on Instacart. The storefront search page for a guest returns the retailer, zone
  and shop ids but **no prices** in its HTML (482 KB, zero `$` amounts); products load through
  Apollo persisted queries whose hashes the client computes at runtime (`PersistedQueryLink`,
  `useGETForHashedQueries:false`), so there is no hash list to lift, and open-supermarkets'
  2026-08 probe found the `Items` operation answers `Not Authenticated` to a guest. Instacart's
  `/v3/` API is 401 from here (above).
  **Correction (2026-10-07):** that holds for plain HTTP only. A headless Playwright browser
  with no login sees prices on sameday.costco.com: the landing page offers "Browse as a guest",
  the guest session is placed by IP (zone 64151 from this Mac), and `/store/costco/s?k=milk`
  rendered 55 "Current price: $X" rows, loaded by the `Items` GraphQL operation (status 200).
  shopmypricechopper.com did not route to a store in the same test, and mymarketdelivers.com
  failed TLS. No lane is built yet.
- **Hen House and United Market** publish their ad through AWG's `adstudio.com` JavaScript
  viewer; no item feed was found in the page or its state file. Price Chopper's digital coupons
  sit behind member sign-in (`SignIn`/`Register` are the only public routes beside `store` and
  `FrontPageAd`), so no coupon lane there.
- **Midtown Market** has no site of its own (`midtownmarket.com` is a store in Kentucky). Yelp
  403s plain fetches; Loc8NearMe shows reviews dated August 2026, so the directory lists it as
  open, unconfirmed first-hand, walk-in only.

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
