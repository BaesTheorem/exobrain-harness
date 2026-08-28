# Google Places API (New)

Place lookup for the harness: free-text search, nearby search, and place details.
Stdlib-only Python, no venv. CLI at `bin/places`, importable library at
`places/places.py`.

## The one thing to understand: field masks are the price tag

Places API (New) does not bill per call. It bills per call **at the tier of the
most expensive field you requested**, via the `X-Goog-FieldMask` header. The same
Text Search request is:

| If your mask tops out at | Tier | Free/month | Then $/1000 |
|---|---|---|---|
| `id`, `formattedAddress`, `location`, `types` | Essentials | 10,000 | $2.83 |
| `displayName`, `photos`, `primaryType` | Pro | 5,000 | $32.00 |
| `rating`, `websiteUri`, `regularOpeningHours` | Enterprise | 1,000 | $35.00 |
| `reviews`, `editorialSummary`, `servesBeer` | Enterprise + Atmosphere | 1,000 | $40.00 |

(Place Details is cheaper across the board: $5 / $17 / $20 / $25. Prices are
Google's published US list for the first 100,000 calls, read 2026-08-28.)

So adding `places.rating` to a search does not cost a little more, it moves the
call out of the 5,000/mo bucket into the 1,000/mo one and roughly doubles the
overage rate. Because of that, masks in this client are not free-form strings:

- `places.py` carries the published SKU tables and classifies every field.
- Every CLI run prints its billed tier to stderr before spending anything.
- `--max-tier` refuses to send a request above a ceiling (default `enterprise`).
- `places tiers` lists which fields sit in which bucket.
- Responses are cached on disk (searches 24h, details 7d) keyed on query **and**
  mask, so re-running a lookup is free. `--no-cache` to bypass.

`DEFAULT_FIELDS` is deliberately `id, displayName, formattedAddress, location,
types` (Pro tier). Do not widen it; add fields per call instead.

## Setup

The key has to be minted in a browser against a billed project, so this part is
manual. The harness already has a Google Cloud project (the one behind the Drive
backup OAuth client, whose id is the numeric prefix of `GOOGLE_OAUTH_CLIENT_ID`
in the harness `.env`); reuse it rather than making a second one.

1. **Enable billing** on the project if it is not already. Places API refuses to
   serve an unbilled project even inside the free allowance; the allowance is a
   discount on a billing account, not an anonymous free tier.
   → https://console.cloud.google.com/billing
2. **Enable the API.** Enable **Places API (New)**, not the legacy "Places API",
   which is a different, deprecated product this client does not speak.
   → https://console.cloud.google.com/apis/library/places.googleapis.com
3. **Create the key.** Credentials → *Create credentials* → *API key*.
   → https://console.cloud.google.com/apis/credentials
4. **Restrict the key** before you use it anywhere. Two restrictions matter:
   - *API restrictions*: **Restrict key** → select only **Places API (New)**. This
     is the one that limits the blast radius if the key leaks.
   - *Application restrictions*: leave as **None**. This key is used from a
     server-side script with no fixed public IP, so an IP allowlist would break
     on every network change. The API restriction is doing the real work.
5. **Set a budget alert** so a runaway loop cannot run up a bill unnoticed.
   → https://console.cloud.google.com/billing/budgets
6. **Store the key** in the harness `.env` (gitignored):
   ```
   GOOGLE_PLACES_API_KEY=AIza...
   ```
7. **Verify**: `bin/places check` makes one `id`-only Essentials call and
   reports whether the key and the enablement are both live.

## Usage

```sh
places check                              # verify key + API enablement
places tiers                              # what each field costs

places search coffee near Westport Kansas City
places search "bike shop" --near 39.0997,-94.5786,5000
places nearby 39.0997,-94.5786 -r 2000 -t restaurant,cafe

# opting into pricier fields, deliberately
places search "ramen kansas city" -f id,displayName,rating,userRatingCount,websiteUri
places details ChIJ... -f id,displayName,regularOpeningHours,nationalPhoneNumber

places search sushi --json                # raw JSON for piping into jq
places search sushi --max-tier pro        # hard stop below Enterprise fields
```

As a library (same island only; the boundary checker blocks cross-island
imports, so call `bin/places --json` from other tools and parse the output):

```python
from places import text_search, nearby_search, details, explain_tier
```

## Gotchas

- **Legacy vs New.** Enabling "Places API" instead of "Places API (New)" produces
  a 403 that reads like a key problem but is an enablement problem. The error
  body names the service; read it.
- **`name` is not the name.** In the v1 API, `name` is the resource path
  (`places/ChIJ...`) and the human-readable name is `displayName.text`.
- **A brand-new key can 403 for a few minutes** while it propagates. Retry before
  concluding the restriction is wrong.
- **`maxResultCount` caps at 20** per request; paging beyond that costs another
  billable call per page.
