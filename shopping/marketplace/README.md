# Curbside: a cleaner Facebook Marketplace

Curbside is a local web app that searches Facebook Marketplace around home. It shows only local listings, with no ads, and it sorts and filters by the distance from home. It uses the `shop fbm` lane (`shoptools/fbm.py`), so it uses the session cookies of the `facebook/` toolkit and only reads.

```
shopping/bin/marketplace [--host 127.0.0.1] [--port 5041]
```

Then open <http://127.0.0.1:5041/>. To open it on the phone, start the server with `--host` set to the Mac's Tailscale address.

## What it does that Facebook does not

- **Distance filter and sort.** All cards show the miles from home. Sort by Nearest, Newest, price, or the largest price drop.
- **No junk.** It removes ads, ship-only listings, sold and gone listings, and the property rentals that Facebook adds to product searches. "Pickup only" stops ship-only listings at the source.
- **Filters that Facebook does not have.** "Hide dealers" removes sellers with 4 or more listings in the last 30 days. "In title" keeps only titles that contain all search words. "Price drops" keeps only listings that had a price decrease. "Hide pending" removes pending listings.
- **Memory.** The index keeps all listings it sees, with its price history. A listing or a seller that you hide stays hidden.
- **Map drawer.** The map shows listings in clusters, a circle for the radius, and your home point. Pins and cards highlight together.
- **Saved searches.** The bookmark menu saves a search with all its filters. The URL also holds all filter settings.

## How distance works

The search cards from Facebook have no coordinates. Curbside uses two sources:

1. **Rings.** One search queries rings of 1, 3, 5, 10, 20, and 40 miles, up to your maximum. Facebook uses integer kilometers, so the 1-mile ring is 2 km (1.24 mi). A listing that first shows in a ring is in that ring. If the inner ring returned all of its results, the listing is also farther than that inner ring. The card shows this band in muted text, for example "< 1.2 mi" or "3.1–5.0 mi".
2. **Pins.** A background worker opens each item page (two at a time, nearest band first) and reads the pin that Facebook shows buyers. The card then shows the accurate miles. The worker opens each listing one time only, and the database keeps the result.

On 2026-10-24 a 10-mile search for "bookshelf" found 176 listings in approximately 30 seconds. All of the pins were known approximately 7 minutes after that. Facebook moves each pin a small distance for privacy. Thus a pin can be up to approximately 0.7 mi farther than the ring that found it.

A smaller distance, in the radius that the search covered, only redraws the page. A larger distance starts a new search. A page reload or a saved search reuses a search with the same parameters from the last 15 minutes.

## Account safety

All requests use Alex's Facebook session. The crawler is slow on purpose: one search page at a time, and two item pages at a time with a pause between them. If Facebook sends a login or checkpoint page, the pin worker stops for 10 minutes, and the status line shows the error. The server binds to 127.0.0.1 and refuses POST requests from other origins, because each API call acts with the session.

## Files

| Path | Contents |
| --- | --- |
| `server.py` | HTTP server: the static UI and a JSON API (the docstring has the routes) |
| `crawl.py` | Search tasks (rings) and the pin worker |
| `store.py` | SQLite index: listings, price history, hidden items, saved searches |
| `static/` | `index.html`, `app.js`, `app.css`, the generated `theme.css`, and vendored Beer CSS, MapLibre GL, Inter, and IBM Plex Mono |
| `data/market.db` | The index. It is gitignored because it holds the names and listings of other persons. Delete it to start again. |
| `DESIGN.md` | Type, palette, spacing, and layout rules |

## When it breaks

- **"session cookies are expired"**: run `facebook/bin/fb refresh-cookies`.
- **"doc_id … rejected"**: run `shopping/bin/shop fbm --refresh-docid`.
- **A search with no search term**: Facebook's search query does not accept an empty term, so Curbside needs one.

Map tiles come from [OpenFreeMap](https://openfreemap.org) (© OpenMapTiles, © OpenStreetMap contributors).
