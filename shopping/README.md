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
