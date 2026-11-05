# travel

Travel search tools for the `/trip-planning` skill.

## bin/hotels

Live hotel prices from Booking.com and Priceline in one table.

```
travel/bin/hotels search "Chicago, IL" --in 2026-12-10 --out 2026-12-12 --min-stars 4
travel/bin/hotels search "Chicago, IL" --in 2026-12-10 --out 2026-12-12 --name "palmer house"
travel/bin/hotels search "Moab, UT" --in 2027-04-02 --out 2027-04-05 --refundable --json
```

| Lane | Route | Per search |
| --- | --- | --- |
| `booking` | Search page in headless Chromium, then the page's Apollo store | 1 page, approximately 25 hotels |
| `priceline` | Priceline's GraphQL API over curl_cffi with a Chrome TLS fingerprint | 30 a page, up to 4 pages |

- Booking.com sends an AWS WAF challenge to plain HTTP clients. A headless browser passes it.
- Priceline sends a PerimeterX CAPTCHA to every headless browser. Its API does not. The tool reads the
  query text from a live listings page on each run, and keeps the last good copy in `cache/`
  (gitignored). If the cache is missing, the next good run makes it again.
- Booking.com ignores the URL offset, and a headless page loads no more results. Use `--sort`,
  `--min-stars` and `--refundable` to narrow that one page.
- Booking.com ignores a hotel name in the search text. With `--name`, Booking.com filters its
  25 most popular hotels and prints a warning with a search link on a miss. Priceline filters
  by name on its server.
- Priceline Express Deals show as `priceline express` with the `opaque` flag. The hotel name is
  hidden until you book, and the rate is not refundable.
- `total` is the full stay. Priceline totals include taxes and fees. Booking.com totals add
  the taxes that Booking.com lists as excluded. A resort fee that the hotel collects at check-in is not in the total.

The tool only reads prices. It does not sign in, hold a room or book.

Dependencies: `curl_cffi`, `playwright` and its Chromium.
