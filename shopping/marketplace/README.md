# Curbside: a cleaner Facebook Marketplace

Curbside is a local web app for Facebook Marketplace around home. It keeps an index of all listings near home, shows them with no ads, and sorts and filters them by the distance from home. The search box and the filters make the list smaller. It uses the `shop fbm` lane (`shoptools/fbm.py`), so it uses the session cookies of the `facebook/` toolkit and only reads.

```
shopping/bin/marketplace [--host 127.0.0.1] [--port 5041]     # the web app
shopping/bin/marketplace watch [--now] [--sweep]               # one watcher run (launchd)
```

Open <http://127.0.0.1:5041/>. To open it on the phone, start the server with `--host` set to the Mac's Tailscale address.

## What it does that Facebook does not

- **All listings in range, first.** The first page shows all indexed listings in the distance you choose. Type in the search box to filter the index by title. Press Enter to also send the term to Facebook's search, and its matches go into the list.
- **Distance filter and sort.** All cards show the miles from home. Sort by Nearest, Newest, price, the largest price drop, or search relevance.
- **No junk.** It removes ads, ship-only listings, listings from other cities that only ship, sold and gone listings, and the property rentals that Facebook adds to product searches.
- **Repost detection.** When a seller lists the same item again, the item shows as one card with a "Relisted" tag. The detail sheet tells when the first listing went up, so you know the item has not sold. A "Shared photo" tag shows when sellers that are not the same person use one photo: a stock photo, or a copied photo from a scam.
- **Filters that Facebook does not have.** Categories, "Hide dealers" (sellers with 4 or more listings in 30 days), "Hide relisted", "In title" (all search words in the title), "Price drops", and "Hide pending".
- **Saved searches with Discord alerts.** The bookmark menu saves a search with all its filters. With its bell on, the watcher sends new matches and price drops to Discord and as a banner, in one digest for each run.
- **Memory.** The index keeps price history. A listing or a seller that you hide stays hidden.
- **Map drawer** with clusters, the radius circle, and your home point, and a **light, dark, or automatic theme** (the half-circle button).

## The index

Facebook's search returns nothing for an empty search term. A category page with no term does return listings, so a sweep reads each category page (17 categories, with property sales and rentals left out). It reads them newest first (`commerce_search_sort_by: CREATION_TIME_DESCEND`), in rings of 1, 3, 10, and 25 miles:

- The first sweep reads the last 3 days. Each subsequent sweep stops at the newest listing that the last sweep saw, so it costs approximately one page for each ring and category.
- The server starts a sweep when the last one is more than 2 hours old. The watcher does the same at 30-minute intervals, from 7 am to midnight, so the index stays current when the server is off. One lock row in the database stops the two from sweeping at the same time.
- Listings that Facebook's search finds go into the index too, so older listings come in with use.

On 2026-10-24, newest-first order had 0 errors in 80 furniture listings. Facebook ignores the age filter (`ctime_days`) on category pages, which is why the sweep uses the sort and stops on its own.

## How distance works

The search cards from Facebook have no coordinates. Curbside uses two sources:

1. **Rings.** A sweep or a search reads each ring from small to large. Facebook uses integer kilometers, so the 1-mile ring is 2 km (1.24 mi). A listing that first shows in a ring is in that ring. A ring that read all of its listings for the time window also shows that a listing first found in the next ring is farther out. The card shows this band in muted text, for example "< 1.2 mi" or "3.1–9.9 mi". Facebook applies the radius only to pickup listings. It returns listings that can ship from any distance (a 1-mile ring returned listings from Florida), so a listing that can ship gets no band.
2. **Pins.** The item page has the pin that Facebook shows buyers. The page asks for pins only for the cards on the screen, and the server fetches at most 240 item pages in one hour. A listing that can ship shows only after its pin puts it in range. The server fetches those pins in the background for the states that local pickup listings come from.

A pin and a ring can disagree by up to approximately 1.5 mi, because Facebook moves pins for privacy. The card uses the pin when it has one.

## Alerts

`marketplace watch` runs from launchd at 30-minute intervals (`com.exobrain.marketplace-watch.plist`, installed in `~/Library/LaunchAgents`). For each saved search with its bell on, it:

1. sends the search term to Facebook, newest first, at the search's radius (approximately two pages)
2. finds the listings that agree with the search's filters: index listings with the search words in the title, and all of Facebook's matches
3. compares them with what that search saw before. The first run only records. Then a new listing, a price drop, or a relist at a lower price causes an alert. A relist at the same price does not.
4. gets the pin of each alert and checks the distance again
5. sends one digest for the run through `mist-notify --discord` (a banner and a Discord DM), with the price, the title, the distance, and the link

`filters.py` holds the same filter rules as `visible()` in `static/app.js`. If you change one, change the other. The log is `data/watch.log`.

## Repost detection

Each card photo gets a 64-bit difference hash (dHash, `photohash.py`) from Facebook's image server, which does not use the account. Two photos are the same when 5 bits or less of their hashes are different. On 2026-10-24, in 534 photos, 4 matched at 0 bits. The nearest photos that were not the same were 7 bits apart (a jacket and a book, for example).

- **Relisted:** two listings by one seller are one item when they share a photo, or when their titles are the same after the removal of case and punctuation, and have a minimum of 12 characters (two listings named "Shelf" can be two items).
- **Shared photo:** one photo in listings by more than one seller.

## Account safety

All requests to Facebook use Alex's session. The crawler is slow on purpose: one page at a time with a pause, at most 240 item pages in one hour, and a sweep that reads only what is new. If Facebook sends a login or checkpoint page, the pin worker stops for 10 minutes and the status line shows the error. The server binds to 127.0.0.1 and refuses POST requests from other origins, because each API call acts with the session.

## Files

| Path | Contents |
| --- | --- |
| `server.py` | HTTP server: the static UI and a JSON API (the docstring has the routes) |
| `crawl.py` | Index sweeps, text searches, the pin worker, and the photo worker |
| `store.py` | SQLite index: listings, price history, photo groups, relists, hidden items, saved searches, alert memory |
| `filters.py` | Filter rules for alerts (the same as in the page) |
| `watch.py` | The watcher: sweep, alerts, digest |
| `photohash.py` | Photo hashes |
| `static/` | `index.html`, `app.js`, `app.css`, the generated `theme.css`, and vendored Beer CSS, MapLibre GL, Inter, and IBM Plex Mono |
| `com.exobrain.marketplace-watch.plist` | The launchd job (a copy is in `~/Library/LaunchAgents`) |
| `data/` | `market.db` (the index) and the logs. Gitignored, because it holds the names and listings of other persons. Delete `market.db` to start again. |
| `DESIGN.md` | Type, palette, spacing, and layout rules |

## When it breaks

- **"session cookies are expired"**: run `facebook/bin/fb refresh-cookies`.
- **"doc_id … rejected"**: run `shopping/bin/shop fbm --refresh-docid`.
- **No alerts**: read `data/watch.log`. The first run of a saved search only records. To stop the job: `launchctl bootout gui/$(id -u)/com.exobrain.marketplace-watch`.

Map tiles come from [OpenFreeMap](https://openfreemap.org) (© OpenMapTiles, © OpenStreetMap contributors).
