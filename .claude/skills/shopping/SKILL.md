---
name: shopping
description: "One pipeline for buying anything at the lowest real price. Finds every retailer that sells the exact item (Target and Walmart at the nearest stores, Amazon, weekly grocery ads, in-store clearance, used listings on Facebook Marketplace around home), collects every promo code, cashback portal and discounted gift card, tests the codes and code combinations on a live cart where possible, and ranks each source by net cost. Use when Alex says '/shopping', '/discount', 'find me a coupon', 'promo code for', 'cheapest place to buy', 'best price on', 'any discount on', 'is it cheaper at Target', 'what does X cost', 'is this on sale', 'do these codes stack', 'check this ASIN', 'anything on Marketplace', 'used X near me', or pastes a product or Marketplace link and asks what it should cost."
---

# /shopping

Goal: the lowest price Alex can actually pay for **this exact item**, each figure marked as
confirmed on a live cart or estimated. One tool: `shopping/bin/shop` (`shopping/README.md` has
the lanes, the gotchas and the limits). Never buy, sign in, or submit an order; Alex checks out.

## 1. Pin the item

Get the identity before you shop: brand, model, **MPN/UPC/GTIN**, size, color, quantity. Pull it
from the pasted page (JSON-LD `gtin`/`mpn`, Shopify `/products/<handle>.js`, `shop price <url>`,
which returns the UPC for Target and Walmart and the specs for Amazon). Every source you find must
match on the identifier or on model plus variant. A near-match (older model year, other cut,
refurbished, marketplace seller) goes in a separate "not the same item" list and is never ranked
beside the real thing. Per [[feedback_shopping_check_all_variants]], each color/size can carry its
own price, stock and delivery date, so check all of them (`shop price <ASIN> --all-variants`;
Target variants are listed in the `price` output, Walmart's count is).

## 2. Find every source

```
shop find <query>                    # Target + Walmart (nearest stores) + Flipp weekly ads + Amazon, one table
shop find <query> --at target,amazon # limit the lanes (--at fbm adds Facebook Marketplace)
shop fbm <query> [--max N] [--days D] [--radius KM] [--condition ...] [--sort price|date] [--exact]
shop price <url | target:<tcin> | walmart:<id> | flipp:<id> | fbm:<id> | ASIN> [--all-variants] [--json]
shop clearance <upc> [store]         # in-store penny or clearance price via Penny Lane
```

- `find` prints a lane as a warning when it fails or returns zero rows. Zero rows is a fact about
  the query, not evidence the item is unsold there: widen the query before concluding anything.
- **Target** prices depend on the store; `shop` prices at the store nearest `HOME_ZIP` and prints
  which location priced it. If Target answers "PerimeterX blocked this IP", leave it alone for an
  hour; retrying extends the block. No other route exists (headless Chromium gets the same block).
- **Walmart**: read the seller. Marketplace sellers post wild markups, and `find` prints the seller
  when it is not Walmart.
- **Flipp** is the only lane into local grocery pricing (Hy-Vee, Dillons, Price Chopper, ALDI,
  Dollar General, Costco). `shop price flipp:<id>` returns the **size**, which is what tells a 28 oz
  jar from a 16 oz one.
- **Amazon**: the on-page "clip coupon" and Subscribe & Save are discounts too; read them from the
  buy box. The delivery date is only real when the session is loaded (`shop amazon auth --status`).
  `search` cannot enumerate the catalog, so never claim "cheapest on Amazon".
- **Brand direct** (often Shopify, so codes can be tested in step 4), **Best Buy, Home Depot, REI,
  Academy, SCHEELS**: not in `shop`; open the page yourself. Google Shopping via WebSearch finds
  candidate retailers, then open each page. WebSearch synthesis is zero-evidence.
- **In-store clearance**: `shop clearance <upc>` asks Penny Lane for the live shelf price at Alex's
  Home Depot, Dollar General, Lowe's and Walmart stores. The `/penny` skill runs that app itself.
- **Used/open-box** only if Alex asks, and always listed separately from the new-item ranking.
  **Facebook Marketplace is in the tool:** `shop fbm <query> --max 200 --days 7 --radius 40
  --condition used_good,used_like_new --sort price` searches around home over Alex's own
  Facebook session (read-only), and `shop price fbm:<id>` or the listing URL returns the
  description, condition, photos, seller rating and pin. Facebook's search is fuzzy, so add
  `--exact` for a model name. If it answers "run refresh-cookies", run `facebook/bin/fb
  refresh-cookies`; if it warns about the `doc_id`, run `shop fbm --refresh-docid`. A fallback
  warning means the radius was the account's, not `--radius`. Still by hand: eBay, Back Market,
  REI Re/Supply, Amazon Warehouse.

For every source record: price, shipping to the home ZIP, sales tax (read it off a cart or the
store's estimate, never assume a rate), stock or delivery date, seller.

## 3. Collect every discount

- **Codes:** `shop codes <domain>` pulls SimplyCodes (Dealspotr and Knoji redirect there) and
  Wethrift, and adds common guesses. Also search Reddit (`r/<brand>`, `r/frugal`) and read the
  brand's own promo banner and e-mail signup offer (a first-order code is usually 10 to 15% and
  works). RetailMeNot, CouponFollow and CouponCabin hide codes behind a click-out and do not
  parse; Slickdeals coupons are 410. Every aggregator code is a candidate until it is tested.
- **Cashback portals:** Rakuten, TopCashback, Capital One Shopping, BeFrugal: the rate for this
  store, from the portal's store page.
- **Discounted gift cards:** CardCash / Raise / GCX rate for the retailer, where one exists.
- **Stackable programs:** Target Circle, Amazon clip coupons, student/military (only if Alex
  qualifies; ask once), price match policy (Best Buy and Target match select competitors), open
  sales events.
- Gift cards, cashback and a code usually stack with each other. Codes stacking with **other
  codes** is the store's rule, and you only learn it by testing.

## 4. Test every code and every combination

- **Shopify stores** (check with `curl -s <store>/products/<handle>.js`):
  `shop cart <product-url> --codes <all candidates> --harvest --max-stack 3`. It checks the
  instrument with a nonsense code, tests each code alone, then every combination of the codes that
  applied, and reads the store's own cart total. It never checks out. A code that applies but saves
  $0 is usually free shipping (the cart has no shipping line) or a threshold the cart does not
  meet; try `--qty` if a threshold is close. If a code's terms say "subscriptions", retest with
  `--selling-plan <id>`. Never run two tests against one store in parallel. Small stores return 429
  after about 20 requests and keep blocking for more than 5 minutes, so test the codes you found
  online first and the `--harvest` guesses last.
- **Non-Shopify stores:** the code box usually appears only at checkout, after the shipping
  address, and automating a guest checkout on Alex's behalf is out of scope. Mark those codes
  `verified: false`, rank them as estimates, and give Alex the short list to paste in (best first,
  one-per-order stores flagged).

## 5. Rank

Write `tmp/shopping/<item-slug>.json` and run `shop best <file>`. Schema:

```json
{"item": "…", "offers": [
  {"source": "Allbirds", "url": "…", "price": 140, "qty": 1, "shipping": 0, "tax_rate": 0.0885,
   "max_codes": 1, "cashback_pct": 4, "giftcard_pct": 0,
   "codes": [{"code": "WELCOME10", "type": "pct|fixed|freeship", "value": 10,
              "min_subtotal": 0, "stackable": false, "verified": true}]}]}
```

`max_codes` and `stackable` come from the step 4 tests. Where nothing was tested, use 1 and
false, since most stores accept one code per order. The optimizer tries every legal subset at
every source: percent codes before fixed ones, then shipping, then tax, then the gift-card
discount on what you pay, then cashback on the post-code subtotal. It returns the best verified
row per source, plus the best estimate where that is lower.

## 6. Report

Lead with the winner: source, codes in the order to enter them, the checkout total, net cost after
cashback, delivery date, and a link. Then the table with every source. Say which figures were
confirmed on a live cart and which are estimates. List the dead codes you tested so Alex does not
retry them. Close with one question if there is a decision (buy now or wait for a sale, pay extra
for faster delivery).

Delete `tmp/shopping/` files once the purchase is settled.

## Account commands

`shop amazon orders --year 2026` reads order history from the saved Chrome session;
`shop amazon auth --from-chrome` re-exports it after Alex signs in by hand. The tool has no
password and cannot log in. See `shopping/secrets/README.md`.
