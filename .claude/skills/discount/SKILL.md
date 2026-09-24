---
name: discount
description: "Find the lowest real price for one item. Finds every retailer that sells it, collects every promo code, cashback portal, and discounted gift card, tests the codes and code combinations on a live cart where possible, and ranks each source by net cost. Use when Alex says '/discount', 'find me a coupon', 'promo code for', 'cheapest place to buy', 'best price on', 'any discount on', 'do these codes stack', or pastes a product link and asks what it should cost."
---

# /discount

Goal: the lowest price Alex can actually pay for **this exact item**, each figure marked as
confirmed on a live cart or estimated. Tool: `shopping/bin/discount` (see `shopping/README.md`).

## 1. Pin the item

Get the identity before you shop: brand, model, **MPN/UPC/GTIN**, size, color, quantity. Pull it
from the pasted page (JSON-LD `gtin`/`mpn`, Shopify `/products/<handle>.js`, `amz show`). Every
source you find must match on the identifier or on model plus variant. A near-match (older model
year, other cut, refurbished, marketplace seller) goes in a separate "not the same item" list and is
never ranked beside the real thing. Per [[feedback_shopping_check_all_variants]], each color/size
can carry its own price, so check all of them (`amz show <ASIN> --all-variants`).

## 2. Find every source

Run these lanes in parallel. [[reference_retail_price_lookup_lanes]] documents each one.

- **Brand direct** (often Shopify, so codes can be tested in step 4).
- **Amazon** `shopping/bin/amz search` / `show` (the on-page "clip coupon" and Subscribe & Save are
  discounts too; read them from the buy box).
- **Target** RedSky with a KC `pricing_store_id` (Target Circle deals live here), **Walmart**
  `__NEXT_DATA__` (read `sellerName`), **Best Buy / Home Depot / REI / Academy / SCHEELS** per the lanes memory.
- **Google Shopping** via WebSearch to find candidate retailers, then open each page yourself.
  WebSearch synthesis is zero-evidence.
- **Used/open-box** only if Alex asks for it: eBay, Back Market, REI Re/Supply, Amazon Warehouse. List them separately.

For every source record: price, shipping to 64111, sales tax (read it off a cart or the
store's tax estimate; don't assume a rate), stock/delivery date, seller.

## 3. Collect every discount

- **Codes:** `shopping/bin/discount codes <domain>` pulls SimplyCodes (Dealspotr and Knoji redirect
  there) and Wethrift, and adds common guesses. Also search Reddit (`r/<brand>`, `r/frugal`) via the
  Reddit lanes and read the brand's own promo banner and email-signup offer (a first-order
  code is usually 10 to 15% and works). RetailMeNot, CouponFollow and CouponCabin hide codes behind a
  click-out and don't parse; Slickdeals coupons are 410. Treat every code from an aggregator as a
  candidate until it is tested.
- **Cashback portals:** Rakuten, TopCashback, Capital One Shopping, BeFrugal: the rate for this
  store, from the portal's store page.
- **Discounted gift cards:** CardCash / Raise / GCX rate for the retailer, where one exists.
- **Stackable programs:** Target Circle, Amazon clip coupons, student/military (only if Alex
  qualifies; ask once), price match policy (Best Buy and Target match select competitors), open
  sales events.
- Gift cards, cashback and a code usually stack with each other. Codes stacking with **other codes** is
  the store's rule, and you can only learn it by testing.

## 4. Test every code and every combination

- **Shopify stores** (check with `curl -s <store>/products/<handle>.js`): run
  `shopping/bin/discount shopify <product-url> --codes <all candidates> --harvest --max-stack 3`.
  It checks the instrument with a nonsense code, tests each code alone, then every combination
  of the codes that applied, and reads the store's own cart total. It never checks out.
  A code that applies but saves $0 in the cart is usually free shipping (the Ajax cart has no
  shipping line) or has a threshold the cart doesn't meet. Try `--qty` if a threshold is close.
  Read each code's terms: if it says "subscriptions", retest with `--selling-plan <id>`.
  Never run two tests against one store in parallel. Small stores return 429 after about 20
  requests and keep blocking for more than 5 minutes, so test the codes you found online
  first and the `--harvest` guesses last.
- **Non-Shopify stores:** the code box usually appears only at checkout, after the shipping
  address, and automating a guest checkout on Alex's behalf is out of scope. Mark those codes
  `verified: false`, rank them as estimates, and give Alex the short list to paste in (best
  first, one-per-order stores flagged).

## 5. Rank

Write `tmp/discount/<item-slug>.json` and run `shopping/bin/discount best <file>`. Schema:

```json
{"item": "…", "offers": [
  {"source": "Allbirds", "url": "…", "price": 140, "qty": 1, "shipping": 0, "tax_rate": 0.0885,
   "max_codes": 1, "cashback_pct": 4, "giftcard_pct": 0,
   "codes": [{"code": "WELCOME10", "type": "pct|fixed|freeship", "value": 10,
              "min_subtotal": 0, "stackable": false, "verified": true}]}]}
```

`max_codes` and `stackable` come from the step 4 tests. Where nothing was tested, use 1 and false,
since most stores accept one code per order. The optimizer tries every legal subset at every
source. It applies percent codes before fixed ones, then shipping, then tax, then the gift-card
discount on what you pay, then cashback on the post-code subtotal. It returns the best verified row
per source, plus the best estimate where that is lower.

## 6. Report

Lead with the winner: source, codes in the order to enter them, the checkout total, net cost after
cashback, delivery date, and a link. Then show the table with every source. Say which figures were
confirmed on a live cart and which are estimates. List the dead codes you tested so Alex doesn't
retry them. Close with one question if there's a decision (buy now vs. wait for a sale, pay extra for faster
delivery). Never buy, sign in, or submit an order; Alex checks out.

Delete `tmp/discount/` files once the purchase is settled.
