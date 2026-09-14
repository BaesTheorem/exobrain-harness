# The wider tool landscape

`geoguessr/bin/geo` already wraps the five things worth having wired up. This file is the
survey: what else exists, what is worth reaching for, and what is a dead end so you do not
waste an hour rediscovering it.

Confidence: **[V]** verified from the primary source, **[S]** secondary source only,
**[X]** verified dead end.

---

## Already wired into `geo`

| `geo` subcommand | What it wraps |
|---|---|
| `sun`, `sunpos` | Pure closed-form solar geometry, NOAA declination series. No dependencies. Tested in `tests/test_geo_solver.py` |
| `pano` | `streetlevel`, keyless, through `bin/geo-pano` |
| `where`, `geocode` | Nominatim |
| `overpass` | Overpass API, `[out:json]` injected automatically |
| `score` | The GeoGuessr scoring curve |
| `enhance` | ImageMagick crop, Lanczos upscale, unsharp mask |

---

## Street View access

**`streetlevel`** [V] — the best keyless option, and what `geo pano` uses. Pulls panoramas
and metadata from Google, Apple Look Around, Yandex, Bing Streetside, Baidu, Kakao, Naver,
Mapy.cz and Já 360 through each service's internal API, no key for any of them.

Two gotchas, both already handled in `bin/geo-pano`:
1. It imports `pyexiv2` purely to write EXIF on download, and that ships a dylib needing
   `brew install inih` and `gettext`. Since we never download, `bin/geo-pano` stubs the
   module with a permissive `__getattr__` shim rather than adding a brew dependency.
2. It rides internal APIs, so it can break without warning. If `geo pano` starts failing
   for every coordinate including known-good ones, suspect the library, not the location.

**Street View Image Metadata endpoint** [V] —
`https://maps.googleapis.com/maps/api/streetview/metadata?location=<lat,lng>&key=<KEY>`
returns pano_id, location, date, copyright. **Metadata requests are free and consume no
quota**; only the image endpoint is billed. The harness has **no Google Maps API key** as of
this writing, which is why `geo pano` goes the keyless route. If a key ever lands in `.env`,
this becomes the authoritative cross-check. Store lat/lng rather than pano IDs long-term:
pano IDs change when Google refreshes imagery.

**Internal Google endpoints** [S] — `GeoPhotoService.SingleImageSearch`, `maps/photometa`.
Reverse-engineered, protobuf-shaped, undocumented. `streetlevel` already wraps these; do
not hand-roll them.

**Other wrappers** [S] — `google_streetview` (key-based CLI), `robolyst/streetview`
(historical panoramas, keyless).

---

## Reverse image search and ML geolocation

**Yandex Images** [S] — practitioner consensus is that it is the strongest engine for
buildings and landscapes, especially the former USSR. **No official API.** Scriptable only
through paid third-party scrapers. For a one-off, just open it in a browser.

**Google Lens, Bing Visual Search, TinEye** [S] — no free scriptable path. Bing has a paid
Azure API; TinEye is commercial per-search.

**GeoCLIP** [V] — the only top-tier image-geolocation model that ships **runnable weights**.
NeurIPS 2023, CLIP image encoder aligned against a GPS location encoder.
`pip install geoclip`, repo `VicenteVivan/geo-clip`. Worth trying as a first-pass country
guess if a round is genuinely opaque, though your own reading will usually beat it on
street-level imagery.

**StreetCLIP** [V] — `geolocal/StreetCLIP` on Hugging Face. Zero-shot country/region/city
via text-label matching, trained on 1.1M street-level images from 101 countries. **Biased
Western, excludes India and China**, which is exactly where you would want the help.

**sdan/geospot-base** [S] — SigLIP2-based GPS regressor, ~10.6M street-view images. Untested;
a fallback if GeoCLIP underperforms.

**PIGEON / PIGEOTTO** [X] — CVPR 2024, trained on GeoGuessr data, over 40% of guesses within
25 km. The repo (`LukasHaas/PIGEON`) ships **training code only**; geocells, datasets and
weights were deliberately withheld. Not runnable. Do not plan around it.

**GeoEstimation / ISNs (TIBHannover)** [X] — code and trained models **removed by the
authors** over dual-use concerns. Dead end.

**Picarta** [S] — commercial image-geolocation service with a public API and a freemium
tier. Full result details are paywalled. Could not verify pricing or accuracy claims from
the primary site.

**GeoSpy.ai** [S] — pricing figures floating around come from SEO aggregators, not the
vendor. Do not budget against them without checking geospy.ai directly.

---

## Sun and shadow

`geo sun` covers the common case. These are alternatives and cross-checks:

- **ShadowFinder (Bellingcat)** [V] — `pip install shadowfinder`, MIT. Given object height,
  shadow length and a **UTC date-time**, plots the band of Earth where that geometry is
  possible. It solves the same inverse problem as `geo sun` but needs the clock time, which
  in a game you do not have; `geo sun` trades that for needing the shadow's compass bearing.
  Use ShadowFinder for a real photo with a known timestamp. Gotcha: the CLI regenerates its
  timezone grid every run, so use the Python API and cache `timezone_grid.json`.
- **`suncalc`, `pysolar`, `pvlib`, `astral`** [V] — forward solar position from a known
  location. `pvlib.solarposition.get_solarposition()` uses the NREL SPA algorithm and is the
  most accurate. Use one to sanity-check `geo sunpos` if a result looks wrong.
- **suncalc.org** — browser tool, good for eyeballing.

---

## OSM

**Overpass** — `geo overpass` handles the HTTP. Query patterns worth keeping:

```
# Everything named X in a country
area["ISO3166-1"="PL"][admin_level=2]->.a;
node(area.a)["place"="village"]["name"="Zalesie"];
out center;

# Proximity constraint: a church within 300 m of a named road
way["highway"]["name"="Hauptstraße"]->.roads;
node(around.roads:300)["amenity"="place_of_worship"];
out center;

# A specific brand in a country, to test a signage read
area["ISO3166-1"="RO"][admin_level=2]->.a;
nwr(area.a)["brand"="Rompetrol"];
out center;
```

Put tag filters **before** geometry filters, and keep the area tight. A 504 means the query
was too heavy; a 429 means you are rate-limited. `geo overpass` reports both cleanly.

**`overpy`** [V] and **`overpassforge`** [S] are Python clients if you ever need more than
the raw HTTP.

**Nominatim** [V] — free, but the usage policy is strict: **1 request/second**, custom
User-Agent required (`geo` sets one), no bulk or systematic querying. Fine for confirming a
handful of candidates, not for grid-scanning.

---

## Elevation

Both are free and keyless, and `geo elev` wraps the first.

- **Open-Meteo elevation** [V] - `https://api.open-meteo.com/v1/elevation?latitude=a,b&longitude=c,d`.
  Batches every point into one call. Roughly 90 m SRTM-class data, good to a few metres.
- **USGS EPQS** [V] - `https://epqs.nationalmap.gov/v1/json?x=<lon>&y=<lat>&units=Feet&wkid=4326`.
  1 m raster over the US, much finer, but one point per request. Use it to check a single
  number once Open-Meteo has narrowed things.

Elevation is the cheapest way to make a viewpoint hypothesis falsifiable, because the drop
from a viewpoint to a landmark plus that landmark's depression in frame pins the focal
length, and an implied field of view outside 15 to 110 degrees means the hypothesis is wrong.

---

## Other imagery

**Mapillary API v4** [V] — 2B+ crowdsourced geotagged street-level photos across 190+
countries, **free for any use**, rate-limited not paywalled. Needs a client token from the
developer dashboard (v3 tokens do not work on v4). `GET
https://graph.mapillary.com/<IMAGE_ID>?access_token=<TOKEN>&fields=thumb_original_url,computed_geometry,captured_at,computed_compass_angle`.
Genuinely useful where Google has no coverage.

**KartaView** [S] — free open street-level imagery, CC BY-SA, run by Grab. Auth flow is
poorly documented officially.

**Google Earth Pro** [S] — free desktop app. The historical-imagery time slider is uniquely
good for pinning when a building or road appeared, which is how you date a photo.

---

## Image forensics

**`exiftool`** [V] — `brew install exiftool` (**not currently installed here**). Worth it
only for photos Alex was actually sent. A GeoGuessr screenshot is composited by the browser
and carries no camera GPS; at most you get screenshot-tool metadata. Check rather than
assume, but do not expect a win.

**OCR** — you read text better than any OCR engine, so the bottleneck is pixel size, not
recognition. `geo enhance` is the right tool. If you do want OCR: `tesseract` is installed
(add language packs with `brew install tesseract-lang`), PaddleOCR handles rotated and
curved signage better, and macOS has on-device Vision-framework CLIs (`mac-ocr`,
`macos-vision-ocr`) that need no cloud call.

**Upscaling** — `geo enhance` uses ImageMagick's Lanczos plus unsharp, which is fast and
sufficient. For a genuinely destroyed sign, `Real-ESRGAN` (`pip install realesrgan`,
auto-downloads weights) does better, at the cost of hallucinating detail. Be careful: an
upscaler that invents a letter is worse than a blur, because the invention looks legible.

---

## GeoGuessr's own API and userscripts

**Unofficial API clients** [S] — `EvickaStudio/GeoGuessr-API`,
`teamcoltra/geoguessr-api-docs` (most complete endpoint reference), `Inkapa/geoguessr_api`,
and `NyxiumYuuki/GeoGuessrMCP` (an MCP server over the same endpoints). All use **cookie
auth** via the `_ncfa` session cookie, all are unsupported, all break silently when
GeoGuessr changes its backend.

**Userscripts** — `miraclewhips/geoguessr-userscripts` (coverage-line overlays, terrain
mode, hiding car metadata), map-making.app plus its helper script. **Most of these are
cheating in ranked play**, and the community says so explicitly. Fine for study, not for a
scored game.

Could not verify a tool called "GeoGuessr Resource Hub" exists as a named thing. Probably a
misremembering of the userscript collections above.

---

## Study sources, and how to actually reach them

- **plonkit.net** — canonical. Each country page is structured Country ID → Regionguessing
  → Spotlight. It is a JS SPA that blocks plain scrapers; the content is in the embedded
  `__PRELOADED_DATA__` script tag in the page HTML, so `curl` plus a JSON extract works.
- **geohints.com** — raw exhaustive database rather than a guide. Its `/meta/*` pages
  (`cameraGens`, `countries`, `phoneNumbers`, `currencies`, `domains`,
  `companies/gasStations`, `companies/beer`, `nature`) answer plain `curl`. Older top-level
  pages sit behind Cloudflare and need the Wayback Machine.
- **learnablemeta.com** — training maps plus a userscript that explains the relevant clue
  after each guess. Open source as `likeon/geometa`, metas sourced from Plonk It.
- **geotips.net** — curated resource list.
- **Bellingcat's toolkit** (`bellingcat.gitbook.io/toolkit/categories/geolocation`) — the
  best index of OSINT geolocation tools, each annotated with cost and caveats.
