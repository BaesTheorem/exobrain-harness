# shopping

Read-only retail lookup tools.

## `bin/amz` -- Amazon product and price lookup

```
amz search "retort pouch stand up" -n 10
amz show B09DS2BLYZ                    # one product
amz show B0D2PTLXDD B0FSPVM1X2 --json  # several, to compare price and shipping
amz auth --from-chrome                 # re-export the live session
amz auth --status                      # held cookies and their expiry
amz orders --year 2026                 # order history for the signed-in account
```

`--json`, `--headed` and `--timeout` work on either side of the subcommand.

`show` loads the saved session by default so the **delivery promise is for
Alex's real address**. Anonymous, Amazon guesses a region and the date can be
days off, so that case prints a warning next to it rather than passing it off
as real. `--anon` forces the anonymous path.

### Why a browser and not `requests`

Amazon's `/s?k=` search endpoint sits behind Akamai Bot Manager. A plain `curl`
gets a ~1.4 KB stub carrying a `bm-verify` meta-refresh challenge, never any
results. This is a **JavaScript challenge, not an auth gate**: an anonymous
headless Chromium clears it and returns the full result set. Tested 2026-09-22,
52 product cards, no login, no cookies, no captcha.

So this tool needs no Amazon account and never signs in. Product pages
(`/dp/<ASIN>`) do respond to plain `curl` with a browser User-Agent, but the
same browser path is used for both so there is one code path to maintain.

### Traps this tool exists to avoid

- **Sponsored carousels contaminate the HTML.** A listing page carries other
  products' titles, prices and review counts from "customers also viewed" and
  sponsored strips. A naive `grep zipper` on a product page returns four
  neighbouring products and zero of the actual item. Every selector here is
  scoped to a container owned by the item itself. Do not loosen them to regex.
- **Price is ambiguous by regex.** A page has several `a-offscreen` price
  strings. `show` reads the buy box specifically, and returns empty rather than
  guessing. An empty price usually means the item is unavailable.
- **`<h2>` is the brand, not the title.** In the current search card layout the
  `<h2>` holds only "Ziploc". The title lives in `[data-cy="title-recipe"]`
  behind a "Sponsored" prefix.
- **Read the `Capacity` spec row; never compute it from the dimensions.**
  Estimating a gusseted pouch's volume from its flat width and height
  overshoots badly: the cylinder model put a Wallaby MRE bag at 1.5 L when the
  listing states **0.4 L**, because the published dimensions include seal
  margins and the gusset constrains the shape far more than a free cylinder.
  Some listings do put junk in the field (one read `Capacity: 4.25 inches`,
  the gusset depth in the wrong slot); when that happens, find a comparable
  bag that publishes both, do not fall back on the arithmetic.
- **An empty result is suspect, not an answer.** `search` exits non-zero on
  zero rows, and both commands raise if they detect the bot challenge, so a
  block never reads as "no such product".

### Requirements

`playwright` with the chromium browser installed (both already present
system-wide: `/opt/homebrew/lib/python3.14/site-packages/playwright`).

### Scope

Read-only by construction. It never authenticates, adds to cart, or purchases.
Order history, Subscribe & Save, lists and your Prime-specific pricing are the
only things that would need credentials; none of them are implemented, and
adding them should follow the house pattern used by the LinkedIn and Instagram
tools (log in by hand once in a real browser, export the session cookie to a
gitignored file, never automate the login itself).

## `bin/discount` -- promo codes, live cart tests, cheapest source

```
discount codes allbirds.com                      # candidates: SimplyCodes, Wethrift, guesses
discount shopify <product-url> --codes A B C --harvest --max-stack 3
discount best tmp/discount/<item>.json            # rank every source x every legal code subset
```

A `uv run --script` file with `curl_cffi` declared inline, so it needs `uv` and nothing else.
The `/discount` skill drives the whole workflow.

- **Shopify is the only lane that proves a code works.** The Ajax Cart API
  (`POST /cart/update.js {"discount": "A,B"}`) returns per-code `applicable`
  flags and the discounted `total_price` for an anonymous cart. Comma-joined codes
  show whether the store lets codes combine. Each run first applies a nonsense code and
  aborts if the store reports it as applicable. Nothing ever reaches checkout.
- **Small Shopify stores rate-limit hard.** basicallyfood.com answered 429 with
  a "Verifying your connection" page after roughly 20 cart requests, and kept
  blocking this IP for more than 5 minutes. Run one test at a time. Test the
  codes you found online before `--harvest` guesses, and keep `--max-stack` low.
- **Some codes are subscription-only.** Pass `--selling-plan <id>` (ids are in
  `selling_plan_groups` of `/products/<handle>.js`) to test them on a
  subscription cart.
- **The cart has no shipping line**, so a free-shipping code shows as applicable but
  saves $0.
- **Aggregator coverage (tested 2026-09-23):** SimplyCodes puts codes in
  `data-code` attributes, and dealspotr.com and knoji.com redirect to it. Wethrift embeds
  `"code":` JSON. RetailMeNot, CouponFollow and CouponCabin hide codes behind a
  click-out. Slickdeals `/coupons/` returns 410, CouponBirds 403. The Syrup
  open-source coupon DB (`db.joinsyrup.com`) sits behind a JS challenge and hangs,
  and the repo is archived, so don't build on it.
- **`best` is arithmetic, not a measurement.** It applies percent codes before
  fixed ones, then tax, then the gift-card discount, then cashback. Rows are
  `verified` only when every code in them was confirmed on a cart.
